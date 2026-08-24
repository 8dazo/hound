"""OpenAPI Specification fetcher and normalizer."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml


@dataclass
class FetchedSpec:
    """Represents a fetched and normalized OpenAPI spec with content hash."""

    spec: dict[str, Any]
    content_hash: str
    source_url: str


class OpenAPIFetcher:
    """Fetches, parses, resolves references in, and hashes OpenAPI/Swagger specs."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, url_or_path: str) -> FetchedSpec:
        """Fetch spec from remote URL or local file path."""
        raw_text = self._read_source(url_or_path)
        spec = self._parse_content(raw_text, url_or_path)
        normalized = self.normalize(spec)
        content_hash = self.compute_hash(normalized)
        return FetchedSpec(spec=normalized, content_hash=content_hash, source_url=url_or_path)

    def _read_source(self, url_or_path: str) -> str:
        """Read content from HTTP/HTTPS URL or local path."""
        if url_or_path.startswith(("http://", "https://")):
            try:
                resp = requests.get(url_or_path, timeout=self.timeout_seconds)
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                raise RuntimeError(f"Failed to fetch spec from {url_or_path}: {e}") from e
        else:
            clean_path = url_or_path
            clean_path = clean_path.removeprefix("file://")
            path = Path(clean_path)
            if not path.is_file():
                raise FileNotFoundError(f"Local spec file not found: {clean_path}")
            try:
                return path.read_text(encoding="utf-8")
            except Exception as e:
                raise RuntimeError(f"Failed to read local spec file {clean_path}: {e}") from e

    def _parse_content(self, text: str, source_label: str) -> dict[str, Any]:
        """Parse JSON or YAML text into a dict."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        try:
            parsed = yaml.safe_load(text)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("Parsed YAML is not a dictionary")
        except Exception as e:
            raise ValueError(
                f"Failed to parse spec from {source_label} as JSON or YAML: {e}"
            ) from e

    def normalize(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Resolve internal $ref references and return fully normalized spec."""
        spec_copy = copy.deepcopy(spec)
        return self._resolve_refs(spec_copy, root=spec_copy, visited=set(), depth=0)

    def _resolve_refs(
        self,
        node: Any,
        root: dict[str, Any],
        visited: set[str],
        depth: int,
        max_depth: int = 15,
    ) -> Any:
        """Recursively resolve $ref pointers within the spec document."""
        if depth > max_depth:
            return node

        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                ref_path = node["$ref"]
                if ref_path.startswith("#/"):
                    if ref_path in visited:
                        # Break circular ref
                        return {"type": "object", "_circular_ref": ref_path}

                    resolved_target = self._lookup_json_pointer(root, ref_path[2:])
                    if resolved_target is not None:
                        new_visited = visited | {ref_path}
                        # Merge any other keys alongside $ref (e.g. description override in OpenAPI 3.1)
                        if isinstance(resolved_target, dict):
                            resolved_expanded = self._resolve_refs(
                                resolved_target, root, new_visited, depth + 1, max_depth
                            )
                            merged = copy.deepcopy(resolved_expanded)
                            for k, v in node.items():
                                if k != "$ref":
                                    merged[k] = self._resolve_refs(
                                        v, root, new_visited, depth + 1, max_depth
                                    )
                            return merged
                        return self._resolve_refs(
                            resolved_target, root, new_visited, depth + 1, max_depth
                        )

            return {
                k: self._resolve_refs(v, root, visited, depth, max_depth) for k, v in node.items()
            }

        elif isinstance(node, list):
            return [self._resolve_refs(item, root, visited, depth, max_depth) for item in node]

        return node

    def _lookup_json_pointer(self, root: dict[str, Any], pointer: str) -> Any | None:
        """Resolve a JSON pointer like components/schemas/Pet against the root dict."""
        parts = pointer.split("/")
        current: Any = root
        for part in parts:
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return None
        return current

    @staticmethod
    def compute_hash(spec: dict[str, Any]) -> str:
        """Compute deterministic SHA256 content hash of the normalized spec."""
        serialized = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
