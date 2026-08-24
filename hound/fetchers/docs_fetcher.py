"""HTML/Markdown documentation fetcher for non-spec APIs."""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests


@dataclass
class DocChunk:
    """A section of documentation with heading context."""

    heading: str
    content: str
    chunk_id: str


class DocsFetcher:
    """Fetches unstructured documentation and chunks it by section headers."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch_and_chunk(self, url: str) -> list[DocChunk]:
        resp = requests.get(url, timeout=self.timeout_seconds)
        resp.raise_for_status()
        text = resp.text
        return self.chunk_text(text)

    def chunk_text(self, text: str) -> list[DocChunk]:
        """Split text by markdown headings (#, ##, ###)."""
        lines = text.splitlines()
        chunks: list[DocChunk] = []
        current_heading = "Overview"
        current_lines: list[str] = []

        heading_pattern = re.compile(r"^(#{1,4})\s+(.+)$")

        for line in lines:
            match = heading_pattern.match(line)
            if match:
                if current_lines:
                    content = "\n".join(current_lines).strip()
                    if content:
                        chunks.append(
                            DocChunk(
                                heading=current_heading,
                                content=content,
                                chunk_id=f"chunk_{len(chunks)}",
                            )
                        )
                    current_lines = []
                current_heading = match.group(2).strip()
            else:
                current_lines.append(line)

        if current_lines:
            content = "\n".join(current_lines).strip()
            if content:
                chunks.append(
                    DocChunk(
                        heading=current_heading,
                        content=content,
                        chunk_id=f"chunk_{len(chunks)}",
                    )
                )

        return chunks
