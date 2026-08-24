"""TypeScript and JavaScript codebase scanner for API call sites."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

import yaml

from hound.models import UsageRecord

TS_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}

# Common TypeScript / JS SDK signatures
JS_SDK_SIGNATURES = [
    {
        "pattern": r"stripe\.(?:charges|charges\(\))\.(?:create|retrieve|update)",
        "endpoint": "/v1/charges",
        "method": "POST",
    },
    {
        "pattern": r"stripe\.(?:paymentIntents|paymentIntents\(\))\.(?:create|retrieve)",
        "endpoint": "/v1/payment_intents",
        "method": "POST",
    },
    {
        "pattern": r"stripe\.(?:customers|customers\(\))\.(?:create|retrieve)",
        "endpoint": "/v1/customers",
        "method": "POST",
    },
    {"pattern": r"octokit\.rest\.repos\.get", "endpoint": "/repos/{owner}/{repo}", "method": "GET"},
    {
        "pattern": r"openai\.chat\.completions\.create",
        "endpoint": "/v1/chat/completions",
        "method": "POST",
    },
]


class TSScanner:
    """Scans TypeScript and JavaScript files for API call sites and field usages."""

    def __init__(self, signatures_path: Optional[Path | str] = None) -> None:
        self.signatures = list(JS_SDK_SIGNATURES)
        if signatures_path:
            p = Path(signatures_path)
            if p.is_file():
                try:
                    data = yaml.safe_load(p.read_text(encoding="utf-8"))
                    for sig in data.get("signatures", []):
                        self.signatures.append(
                            {
                                "pattern": re.escape(sig.get("pattern", "")),
                                "endpoint": sig.get("endpoint", ""),
                                "method": sig.get("method", "ALL"),
                            }
                        )
                except Exception:
                    pass

    def scan_directory(self, scan_path: str | Path) -> List[UsageRecord]:
        """Recursively scan directory or file for TS/JS API call sites."""
        path = Path(scan_path)
        records: List[UsageRecord] = []

        if path.is_file() and path.suffix in TS_EXTENSIONS:
            records.extend(self.scan_file(path))
        elif path.is_dir():
            for root, _, files in os.walk(path):
                # Skip node_modules and build dirs
                if "node_modules" in root or ".next" in root or "dist" in root:
                    continue
                for f in files:
                    ext = Path(f).suffix
                    if ext in TS_EXTENSIONS:
                        full_path = Path(root) / f
                        records.extend(self.scan_file(full_path))

        return records

    def scan_file(self, file_path: Path | str) -> List[UsageRecord]:
        """Scan a single TypeScript/JavaScript file."""
        path = Path(file_path)
        if not path.is_file():
            return []

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return []

        return self.scan_source(content, str(path))

    def scan_source(self, source: str, file_path: str = "source.ts") -> List[UsageRecord]:
        """Parse TS/JS source text to extract API call sites."""
        records: List[UsageRecord] = []

        # Regex patterns for API calls:
        # 1. axios.post('/v1/charges', { ... })
        axios_pattern = re.compile(
            r"""(?:await\s+)?(?:axios|api|client|http)\.(get|post|put|delete|patch)\s*\(\s*['"`]([^'"`]+)['"`](?:\s*,\s*(\{[\s\S]*?\}))?""",
            re.MULTILINE,
        )

        # 2. fetch('/v1/charges', { method: 'POST', body: ... })
        fetch_pattern = re.compile(
            r"""(?:await\s+)?fetch\s*\(\s*['"`]([^'"`]+)['"`](?:\s*,\s*(\{[\s\S]*?\}))?""",
            re.MULTILINE,
        )

        # 3. SDK calls e.g. stripe.charges.create({ ... })
        for sig in self.signatures:
            sdk_regex = re.compile(
                r"""(?:const|let|var)?\s*(?:\{([^}]+)\}|(\w+))\s*=\s*(?:await\s+)?"""
                + sig["pattern"]
                + r"""\s*\(\s*(\{[\s\S]*?\})?""",
                re.MULTILINE,
            )
            for m in sdk_regex.finditer(source):
                line_no = source[: m.start()].count("\n") + 1
                destructured = m.group(1)
                assigned_var = m.group(2)
                arg_obj = m.group(3)

                written_fields = self._extract_object_keys(arg_obj) if arg_obj else []
                read_fields = []

                if destructured:
                    read_fields.extend(
                        [
                            k.strip().split(":")[0].strip()
                            for k in destructured.split(",")
                            if k.strip()
                        ]
                    )
                elif assigned_var:
                    read_fields.extend(self._find_property_reads(source, assigned_var))

                records.append(
                    UsageRecord(
                        endpoint=sig["endpoint"],
                        method=sig.get("method", "ALL"),
                        fields_read=sorted(list(set(read_fields))),
                        fields_written=sorted(list(set(written_fields))),
                        file=file_path,
                        line=line_no,
                    )
                )

        # Process Axios matches
        for m in axios_pattern.finditer(source):
            line_no = source[: m.start()].count("\n") + 1
            method = m.group(1).upper()
            raw_url = m.group(2)
            payload_str = m.group(3)

            endpoint = self._clean_url(raw_url)
            written_fields = self._extract_object_keys(payload_str) if payload_str else []

            # Find assigned response variable on same line or preceding
            preceding_text = source[: m.start()]
            last_line_match = re.search(
                r"""(?:const|let|var)\s+(?:\{([^}]+)\}|(\w+))\s*=\s*$""",
                preceding_text.splitlines()[-1] if preceding_text.splitlines() else "",
            )
            read_fields = []
            if last_line_match:
                if last_line_match.group(1):
                    read_fields.extend(
                        [
                            k.strip().split(":")[0].strip()
                            for k in last_line_match.group(1).split(",")
                            if k.strip()
                        ]
                    )
                elif last_line_match.group(2):
                    read_fields.extend(self._find_property_reads(source, last_line_match.group(2)))

            records.append(
                UsageRecord(
                    endpoint=endpoint,
                    method=method,
                    fields_read=sorted(list(set(read_fields))),
                    fields_written=sorted(list(set(written_fields))),
                    file=file_path,
                    line=line_no,
                )
            )

        # Process Fetch matches
        # Match fetch(url, options) with balanced-ish braces
        fetch_pattern = re.compile(
            r"""(?:await\s+)?fetch\s*\(\s*['"`]([^'"`]+)['"`](?:\s*,\s*(\{[\s\S]*?\}))?\s*\)""",
            re.MULTILINE,
        )
        for m in fetch_pattern.finditer(source):
            line_no = source[: m.start()].count("\n") + 1
            raw_url = m.group(1)
            options_str = m.group(2)

            endpoint = self._clean_url(raw_url)
            method = "GET"
            written_fields = []

            if options_str:
                method_match = re.search(
                    r"""method\s*:\s*['"`]([A-Z]+)['"`]""", options_str, re.IGNORECASE
                )
                if method_match:
                    method = method_match.group(1).upper()
                body_match = re.search(
                    r"""body\s*:\s*(?:JSON\.stringify\s*\(\s*)?(\{[\s\S]*?\})""", options_str
                )
                if body_match:
                    written_fields = self._extract_object_keys(body_match.group(1))

            records.append(
                UsageRecord(
                    endpoint=endpoint,
                    method=method,
                    fields_read=[],
                    fields_written=sorted(list(set(written_fields))),
                    file=file_path,
                    line=line_no,
                )
            )

        return records

    def _extract_object_keys(self, obj_str: str) -> list[str]:
        """Extract keys from a JS object literal string, including shorthand properties."""
        keys = set()
        # Clean outermost braces
        clean = obj_str.strip()
        if clean.startswith("{") and clean.endswith("}"):
            clean = clean[1:-1].strip()

        # Split by comma (ignoring nested structures roughly)
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        for part in parts:
            if ":" in part:
                # key: value
                key_part = part.split(":")[0].strip().strip("'\"`")
                if key_part and key_part not in (
                    "headers",
                    "method",
                    "body",
                    "data",
                    "params",
                    "auth",
                ):
                    keys.add(key_part)
            else:
                # Shorthand property: e.g. amount or source
                shorthand = part.strip().strip("'\"`")
                if shorthand.isidentifier() and shorthand not in (
                    "headers",
                    "method",
                    "body",
                    "data",
                    "params",
                    "auth",
                ):
                    keys.add(shorthand)

        return sorted(list(keys))

    def _find_property_reads(self, source: str, var_name: str) -> List[str]:
        """Find accesses like varName.property, varName.data.property, varName['property']."""
        fields = set()
        # 1. varName.data.field or varName.field
        prop_matches = re.findall(rf"""\b{var_name}(?:\.data)?\.([a-zA-Z0-9_]+)\b""", source)
        for p in prop_matches:
            if p not in ("data", "status", "headers", "json", "text", "catch", "then"):
                fields.add(p)

        # 2. const { a, b } = varName.data || varName
        destruct_matches = re.findall(
            rf"""(?:const|let|var)\s*\{{([^}}]+)\}}\s*=\s*(?:{var_name}\.data|{var_name})""", source
        )
        for d in destruct_matches:
            for piece in d.split(","):
                clean = piece.strip().split(":")[0].strip()
                if clean:
                    fields.add(clean)

        # 3. varName['field']
        subscript_matches = re.findall(
            rf"""\b{var_name}(?:\.data)?\[['"`]([a-zA-Z0-9_-]+)['"`]\]""", source
        )
        for s in subscript_matches:
            fields.add(s)

        return list(fields)

    def _clean_url(self, raw_url: str) -> str:
        """Strip host/scheme to yield API path."""
        url = raw_url.strip()
        url = re.sub(r"^https?://[^/]+", "", url)
        if not url.startswith("/"):
            url = "/" + url
        if "?" in url:
            url = url.split("?")[0]
        return url
