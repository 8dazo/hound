"""AST-based field access and payload extractor."""

from __future__ import annotations

import ast


class FieldExtractor:
    """Extracts fields sent in requests (written) and fields accessed in responses (read)."""

    @staticmethod
    def extract_written_fields(call_node: ast.Call) -> list[str]:
        """Extract field names passed in keyword arguments (e.g. json={...}, params={...}, or direct SDK kwargs)."""
        fields: set[str] = set()

        for kw in call_node.keywords:
            if kw.arg in ("json", "params", "data"):
                # e.g. json={"source": "tok_123", "amount": 100}
                if isinstance(kw.value, ast.Dict):
                    for key in kw.value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            fields.add(key.value)
            elif kw.arg not in (
                "headers",
                "auth",
                "timeout",
                "cookies",
                "verify",
                "cert",
                "stream",
                "allow_redirects",
                "proxies",
            ):
                # In direct SDK calls like stripe.Charge.create(amount=1000, source="tok_123")
                if kw.arg is not None:
                    fields.add(kw.arg)

        return sorted(list(fields))

    @staticmethod
    def extract_read_fields(scope_node: ast.AST, target_var_name: str) -> list[str]:
        """Inspect the enclosing scope (function/module) to find fields accessed on the response variable."""
        fields: set[str] = set()
        tracked_vars: set[str] = {target_var_name}

        for node in ast.walk(scope_node):
            # 1. Track secondary assignments like `data = resp.json()` or `body = resp`
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    # Check resp.json()
                    func = node.value.func
                    if isinstance(func, ast.Attribute) and func.attr in ("json", "to_dict"):
                        if isinstance(func.value, ast.Name) and func.value.id in tracked_vars:
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    tracked_vars.add(target.id)
                elif isinstance(node.value, ast.Name) and node.value.id in tracked_vars:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            tracked_vars.add(target.id)

            # 2. Track subscript reads: `charge["source"]` or `data['amount']`
            if isinstance(node, ast.Subscript):
                if isinstance(node.value, ast.Name) and node.value.id in tracked_vars:
                    slice_node = node.slice
                    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
                        fields.add(slice_node.value)

            # 3. Track .get(...) method calls: `charge.get("source")`
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "get":
                    if isinstance(func.value, ast.Name) and func.value.id in tracked_vars:
                        if (
                            node.args
                            and isinstance(node.args[0], ast.Constant)
                            and isinstance(node.args[0].value, str)
                        ):
                            fields.add(node.args[0].value)

            # 4. Track direct attribute lookups: `charge.source` or `response.amount`
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id in tracked_vars:
                    if node.attr not in (
                        "json",
                        "text",
                        "status_code",
                        "headers",
                        "content",
                        "raise_for_status",
                    ):
                        fields.add(node.attr)

        return sorted(list(fields))
