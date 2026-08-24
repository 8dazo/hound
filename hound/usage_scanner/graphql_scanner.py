"""Scanner for GraphQL query and mutation usage in codebases."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Set

from hound.models import UsageRecord

GQL_EXTENSIONS = {".graphql", ".gql", ".ts", ".tsx", ".js", ".jsx", ".py"}


class GraphQLScanner:
    """Scans codebases for GraphQL query selections and field accesses."""

    def scan_directory(self, scan_path: str | Path) -> List[UsageRecord]:
        """Recursively scan directory for GraphQL queries."""
        path = Path(scan_path)
        records: List[UsageRecord] = []

        if path.is_file() and path.suffix in GQL_EXTENSIONS:
            records.extend(self.scan_file(path))
        elif path.is_dir():
            for root, _, files in os.walk(path):
                if "node_modules" in root or ".next" in root or ".venv" in root:
                    continue
                for f in files:
                    if Path(f).suffix in GQL_EXTENSIONS:
                        full_path = Path(root) / f
                        records.extend(self.scan_file(full_path))

        return records

    def scan_file(self, file_path: Path | str) -> List[UsageRecord]:
        path = Path(file_path)
        if not path.is_file():
            return []

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return []

        return self.scan_source(content, str(path))

    def scan_source(self, source: str, file_path: str = "query.graphql") -> List[UsageRecord]:
        records: List[UsageRecord] = []

        # 1. Match gql`...` or graphql`...` or plain query { ... } / mutation { ... }
        gql_block_pattern = re.compile(
            r"""(?:gql|graphql)?\s*`([\s\S]*?)`|\b(query|mutation)\s+([A-Za-z0-9_]+)?\s*\{([\s\S]*?)\}""",
            re.MULTILINE,
        )

        for m in gql_block_pattern.finditer(source):
            line_no = source[: m.start()].count("\n") + 1
            query_body = m.group(1) or m.group(4) or m.group(0)

            # Extract fields requested
            fields_read = self._extract_selection_fields(query_body)

            if fields_read:
                records.append(
                    UsageRecord(
                        endpoint="GraphQL:Query",
                        method="POST",
                        fields_read=fields_read,
                        fields_written=[],
                        file=file_path,
                        line=line_no,
                    )
                )

        return records

    def _extract_selection_fields(self, query_text: str) -> List[str]:
        """Extract field identifiers inside GraphQL query braces."""
        fields: Set[str] = set()

        # Remove strings and comments
        clean = re.sub(r"""#[^\n]*""", "", query_text)
        clean = re.sub(r"""\"[^\"]*\"""", "", clean)

        # Match words before { or whitespace
        tokens = re.findall(r"""\b([A-Za-z0-9_]+)\b""", clean)
        keywords = {"query", "mutation", "subscription", "fragment", "on", "true", "false", "null"}

        for t in tokens:
            if t not in keywords and not t.isdigit():
                fields.add(t)

        return sorted(list(fields))
