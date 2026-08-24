"""Changelog feed and HTML web scraper for non-spec APIs."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional

import requests

from hound.fetchers.docs_fetcher import DocChunk


@dataclass
class ChangelogEntry:
    """Represents a discrete changelog item or release note."""

    title: str
    date: str
    content: str
    url: Optional[str] = None


class ChangelogScraper:
    """Scrapes and parses RSS/Atom feeds or HTML changelog web pages."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def scrape(self, url: str) -> List[ChangelogEntry]:
        """Fetch and parse changelog from URL (auto-detects RSS/Atom or HTML)."""
        resp = requests.get(
            url, timeout=self.timeout_seconds, headers={"User-Agent": "Hound-Watchdog/0.1.0"}
        )
        resp.raise_for_status()
        text = resp.text

        # Detect RSS / Atom XML
        if "<rss" in text or "<feed" in text or "xmlns=" in text:
            try:
                entries = self.parse_feed(text)
                if entries:
                    return entries
            except Exception:
                pass

        return self.parse_html(text, base_url=url)

    def parse_feed(self, xml_text: str) -> List[ChangelogEntry]:
        """Parse RSS or Atom XML feed."""
        entries: List[ChangelogEntry] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        # 1. RSS 2.0
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "Untitled Release").strip()
            date = (item.findtext("pubDate") or "").strip()
            desc = (item.findtext("description") or "").strip()
            link = (item.findtext("link") or "").strip()
            clean_content = self._strip_html_tags(desc)
            entries.append(
                ChangelogEntry(
                    title=title,
                    date=date,
                    content=clean_content,
                    url=link or None,
                )
            )

        # 2. Atom Feed
        if not entries:
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                title = (
                    entry.findtext("{http://www.w3.org/2005/Atom}title") or "Untitled Release"
                ).strip()
                date = (
                    entry.findtext("{http://www.w3.org/2005/Atom}updated")
                    or entry.findtext("{http://www.w3.org/2005/Atom}published")
                    or ""
                ).strip()
                content = (
                    entry.findtext("{http://www.w3.org/2005/Atom}content")
                    or entry.findtext("{http://www.w3.org/2005/Atom}summary")
                    or ""
                ).strip()
                clean_content = self._strip_html_tags(content)
                entries.append(
                    ChangelogEntry(
                        title=title,
                        date=date,
                        content=clean_content,
                    )
                )

        return entries

    def parse_html(self, html_text: str, base_url: str = "") -> List[ChangelogEntry]:
        """Heuristic parser for HTML changelog pages."""
        entries: List[ChangelogEntry] = []

        # Find article or section tags
        sections = re.findall(
            r"""<(?:article|section)[^>]*>([\s\S]*?)</(?:article|section)>""",
            html_text,
            re.IGNORECASE,
        )
        if not sections:
            # Fallback: split by headings <h2>, <h3>
            sections = re.split(r"""(?=<h[1-3][^>]*>)""", html_text, flags=re.IGNORECASE)

        for sec in sections:
            title_match = re.search(r"""<h[1-4][^>]*>([\s\S]*?)</h[1-4]>""", sec, re.IGNORECASE)
            title = (
                self._strip_html_tags(title_match.group(1)).strip()
                if title_match
                else "General Update"
            )
            clean_content = self._strip_html_tags(sec).strip()

            if clean_content and len(clean_content) > 20:
                entries.append(
                    ChangelogEntry(
                        title=title,
                        date="",
                        content=clean_content,
                        url=base_url or None,
                    )
                )

        return entries

    def to_doc_chunks(self, entries: List[ChangelogEntry]) -> List[DocChunk]:
        """Convert changelog entries into DocChunk objects for semantic diffing."""
        chunks = []
        for i, entry in enumerate(entries):
            heading = f"{entry.title}" + (f" ({entry.date})" if entry.date else "")
            chunks.append(
                DocChunk(
                    heading=heading,
                    content=entry.content,
                    chunk_id=f"entry_{i}",
                )
            )
        return chunks

    def _strip_html_tags(self, text: str) -> str:
        """Remove HTML tags, scripts, and normalize whitespace."""
        no_scripts = re.sub(
            r"""<(?:script|style)[^>]*>[\s\S]*?</(?:script|style)>""", "", text, flags=re.IGNORECASE
        )
        no_tags = re.sub(r"""<[^>]+>""", " ", no_scripts)
        unescaped = html.unescape(no_tags)
        return re.sub(r"""\s+""", " ", unescaped).strip()
