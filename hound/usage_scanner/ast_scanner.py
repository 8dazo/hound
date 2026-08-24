"""AST-based static code scanner for API call sites."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import yaml

from hound.models import UsageRecord
from hound.usage_scanner.field_extractor import FieldExtractor

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}


class ASTScanner:
    """Walks Python codebases using AST to build API usage tables."""

    def __init__(self, signatures_path: Path | str | None = None) -> None:
        self.signatures = self._load_signatures(signatures_path)

    def _load_signatures(self, path: Path | str | None) -> list[dict[str, str]]:
        if path is None:
            pkg_dir = Path(__file__).resolve().parent
            path = pkg_dir / "sdk_signatures.yaml"
        p = Path(path)
        if p.is_file():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                return data.get("signatures", [])
            except Exception:
                pass
        return []

    def scan_directory(self, scan_path: str | Path) -> list[UsageRecord]:
        """Recursively scan a directory or file for API usage call sites."""
        path = Path(scan_path)
        usage_records: list[UsageRecord] = []

        if path.is_file() and path.suffix == ".py":
            usage_records.extend(self.scan_file(path))
        elif path.is_dir():
            for root, _, files in os.walk(path):
                for f in files:
                    if f.endswith(".py"):
                        full_path = Path(root) / f
                        usage_records.extend(self.scan_file(full_path))

        return usage_records

    def scan_file(self, file_path: Path | str) -> list[UsageRecord]:
        """Scan a single Python file using AST parsing."""
        path = Path(file_path)
        if not path.is_file():
            return []

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except Exception:
            return []

        visitor = _CallSiteVisitor(
            file_path=str(path),
            source_tree=tree,
            signatures=self.signatures,
        )
        visitor.visit(tree)
        return visitor.records


class _CallSiteVisitor(ast.NodeVisitor):
    """Internal AST visitor that inspects function calls and parent scopes."""

    def __init__(
        self,
        file_path: str,
        source_tree: ast.Module,
        signatures: list[dict[str, str]],
    ) -> None:
        self.file_path = file_path
        self.source_tree = source_tree
        self.signatures = signatures
        self.records: list[UsageRecord] = []
        self.scope_stack: list[ast.AST] = [source_tree]
        self.known_urls: dict[str, str] = {}  # Tracks variable assignments like `url = ...`

    def generic_visit(self, node: ast.AST) -> None:
        is_scope = isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)
        )
        if is_scope:
            self.scope_stack.append(node)
        super().generic_visit(node)
        if is_scope:
            self.scope_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        # 1. Track URL variables: `url = "..."` or `url = f"{BASE_URL}/v1/charges"`
        extracted_url = self._extract_url_from_node(node.value)
        if extracted_url:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.known_urls[target.id] = extracted_url

        # 2. Check if right-hand side is an API call
        if isinstance(node.value, ast.Call):
            target_var = None
            if node.targets and isinstance(node.targets[0], ast.Name):
                target_var = node.targets[0].id
            self._check_call(node.value, target_var=target_var)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Call):
            self._check_call(node.value, target_var=None)
        self.generic_visit(node)

    def _check_call(self, call_node: ast.Call, target_var: str | None) -> None:
        """Check if call_node matches requests/httpx or known SDK signatures."""
        call_name = self._get_full_attr_name(call_node.func)
        if not call_name:
            return

        endpoint = None
        method = "ALL"

        # 1. Match Direct HTTP libraries (requests.get, httpx.post, client.get, session.post)
        parts = call_name.split(".")
        if len(parts) >= 2 and parts[-1].lower() in HTTP_METHODS:
            lib_or_obj = parts[-2].lower()
            method = parts[-1].upper()
            if lib_or_obj in ("requests", "httpx", "client", "session", "http", "api"):
                endpoint = self._extract_url_from_args(call_node)
        elif len(parts) >= 2 and parts[-1].lower() == "request":
            # e.g. requests.request("POST", url)
            if len(call_node.args) >= 2:
                if isinstance(call_node.args[0], ast.Constant) and isinstance(
                    call_node.args[0].value, str
                ):
                    method = call_node.args[0].value.upper()
                    endpoint = self._extract_url_from_node(call_node.args[1])

        # 2. Match known SDK signatures
        if not endpoint:
            for sig in self.signatures:
                pattern = sig.get("pattern", "")
                if call_name == pattern or call_name.endswith(pattern):
                    endpoint = sig.get("endpoint")
                    method = sig.get("method", "ALL")
                    break

        if endpoint:
            # Extract request fields written
            written_fields = FieldExtractor.extract_written_fields(call_node)

            # Extract response fields read
            current_scope = self.scope_stack[-1] if self.scope_stack else self.source_tree
            read_fields = []
            if target_var:
                read_fields = FieldExtractor.extract_read_fields(current_scope, target_var)

            self.records.append(
                UsageRecord(
                    endpoint=endpoint,
                    method=method,
                    fields_read=read_fields,
                    fields_written=written_fields,
                    file=self.file_path,
                    line=call_node.lineno,
                )
            )

    def _get_full_attr_name(self, node: ast.AST) -> str | None:
        """Convert an AST attribute tree (e.g. stripe.Charge.create) to dotted string."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            parent = self._get_full_attr_name(node.value)
            if parent:
                return f"{parent}.{node.attr}"
            return node.attr
        return None

    def _extract_url_from_args(self, call_node: ast.Call) -> str | None:
        """Extract and normalize URL from first argument or 'url' keyword."""
        if call_node.args:
            return self._extract_url_from_node(call_node.args[0])
        for kw in call_node.keywords:
            if kw.arg == "url":
                return self._extract_url_from_node(kw.value)
        return None

    def _extract_url_from_node(self, node: ast.AST) -> str | None:
        """Normalize URL literal string, formatted string, or variable lookup into path format."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return self._clean_url(node.value)
        elif isinstance(node, ast.JoinedStr):
            # f-string: f"{BASE_URL}/v1/charges/{id}"
            parts = []
            for val in node.values:
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    parts.append(val.value)
                elif isinstance(val, ast.FormattedValue):
                    # Replace variable interpolation with {param} placeholder
                    param_name = "_"
                    if isinstance(val.value, ast.Name):
                        param_name = val.value.id
                    parts.append(f"{{{param_name}}}")
            joined = "".join(parts)
            return self._clean_url(joined)
        elif isinstance(node, ast.Name) and node.id in self.known_urls:
            return self.known_urls[node.id]
        return None

    def _clean_url(self, raw_url: str) -> str:
        """Strip domain/scheme to yield normalized API path."""
        url = raw_url.strip()
        # Remove scheme and domain (e.g. https://api.stripe.com/v1/charges -> /v1/charges)
        url = re.sub(r"^https?://[^/]+", "", url)
        # Remove leading {BASE_URL} or similar placeholder if present at start of f-string
        url = re.sub(r"^\{[^}]+\}", "", url)
        # Ensure starts with /
        if not url.startswith("/"):
            url = "/" + url
        # Strip query string or fragments if present
        if "?" in url:
            url = url.split("?")[0]
        if "#" in url:
            url = url.split("#")[0]
        return url
