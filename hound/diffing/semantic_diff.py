"""Semantic diffing engine for unstructured API documentation and changelogs."""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from hound.fetchers.docs_fetcher import DocChunk


@dataclass
class ChangedDocSection:
    """Represents a documentation section with notable textual changes."""

    heading: str
    old_text: str
    new_text: str
    diff_ratio: float
    excerpt: str


class SemanticDiffEngine:
    """Computes textual and semantic differences between documentation chunks."""

    def __init__(self, change_threshold: float = 0.85) -> None:
        self.change_threshold = change_threshold

    def diff_chunks(
        self, old_chunks: list[DocChunk], new_chunks: list[DocChunk]
    ) -> list[ChangedDocSection]:
        """Pair chunks by heading and detect meaningful content modifications."""
        old_map = {c.heading: c for c in old_chunks}
        new_map = {c.heading: c for c in new_chunks}

        changed_sections: list[ChangedDocSection] = []

        for heading, new_chunk in new_map.items():
            if heading in old_map:
                old_chunk = old_map[heading]
                ratio = difflib.SequenceMatcher(None, old_chunk.content, new_chunk.content).ratio()

                if ratio < self.change_threshold:
                    # Meaningful difference
                    diff = difflib.unified_diff(
                        old_chunk.content.splitlines(),
                        new_chunk.content.splitlines(),
                        fromfile="old",
                        tofile="new",
                        lineterm="",
                    )
                    excerpt = "\n".join(list(diff)[:15])
                    changed_sections.append(
                        ChangedDocSection(
                            heading=heading,
                            old_text=old_chunk.content,
                            new_text=new_chunk.content,
                            diff_ratio=ratio,
                            excerpt=excerpt,
                        )
                    )
            else:
                # Newly added section
                changed_sections.append(
                    ChangedDocSection(
                        heading=heading,
                        old_text="",
                        new_text=new_chunk.content,
                        diff_ratio=0.0,
                        excerpt=f"+ Added section: {heading}",
                    )
                )

        return changed_sections
