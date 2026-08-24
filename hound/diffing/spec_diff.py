"""Structural diffing engine for OpenAPI and Swagger specifications."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any

from hound.models import ChangeRecord

logger = logging.getLogger(__name__)


class SpecDiffEngine:
    """Computes structural breaking and non-breaking diffs between two OpenAPI specs."""

    def __init__(self, prefer_oasdiff: bool = True) -> None:
        self.prefer_oasdiff = prefer_oasdiff
        self.has_oasdiff = prefer_oasdiff and (shutil.which("oasdiff") is not None)

    def diff(self, old_spec: dict[str, Any], new_spec: dict[str, Any]) -> list[ChangeRecord]:
        """Compute full list of structural changes between old_spec and new_spec."""
        if self.has_oasdiff:
            try:
                records = self._diff_with_oasdiff(old_spec, new_spec)
                if records is not None:
                    return records
            except Exception as e:
                logger.warning(
                    f"oasdiff execution failed, falling back to internal diff engine: {e}"
                )

        return self._diff_internal(old_spec, new_spec)

    def _diff_with_oasdiff(
        self, old_spec: dict[str, Any], new_spec: dict[str, Any]
    ) -> list[ChangeRecord] | None:
        """Run external oasdiff binary and parse its structured output."""
        with (
            tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f_old,
            tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f_new,
        ):
            json.dump(old_spec, f_old)
            json.dump(new_spec, f_new)
            old_path = f_old.name
            new_path = f_new.name

        try:
            # 1. Run oasdiff breaking changes
            cmd_breaking = ["oasdiff", "breaking", "-f", "json", old_path, new_path]
            res_breaking = subprocess.run(cmd_breaking, capture_output=True, text=True, check=False)

            # 2. Run oasdiff full changelog
            cmd_diff = ["oasdiff", "changelog", "-f", "json", old_path, new_path]
            res_diff = subprocess.run(cmd_diff, capture_output=True, text=True, check=False)

            changes: list[ChangeRecord] = []

            # Parse breaking
            if res_breaking.stdout.strip():
                try:
                    breaking_data = json.loads(res_breaking.stdout)
                    for item in breaking_data if isinstance(breaking_data, list) else []:
                        changes.append(self._parse_oasdiff_item(item, breaking=True))
                except json.JSONDecodeError:
                    pass

            # Parse non-breaking from changelog if needed
            if res_diff.stdout.strip():
                try:
                    diff_data = json.loads(res_diff.stdout)
                    for item in diff_data if isinstance(diff_data, list) else []:
                        # Avoid duplicates
                        rec = self._parse_oasdiff_item(item, breaking=False)
                        if not any(
                            c.endpoint == rec.endpoint
                            and c.method == rec.method
                            and c.field == rec.field
                            and c.change_type == rec.change_type
                            for c in changes
                        ):
                            changes.append(rec)
                except json.JSONDecodeError:
                    pass

            return changes
        finally:
            if os.path.exists(old_path):
                os.remove(old_path)
            if os.path.exists(new_path):
                os.remove(new_path)

    def _parse_oasdiff_item(self, item: dict[str, Any], breaking: bool) -> ChangeRecord:
        path = item.get("path") or item.get("endpoint") or ""
        method = (item.get("operation") or item.get("method") or "ALL").upper()
        prop = item.get("property") or item.get("param") or item.get("field")
        desc = (
            item.get("description") or item.get("text") or item.get("id") or "Specification change"
        )
        change_id = item.get("id") or ("breaking_change" if breaking else "spec_change")

        return ChangeRecord(
            endpoint=path,
            method=method,
            field=prop,
            change_type=change_id,
            breaking=breaking,
            description=desc,
            raw=item,
        )

    def _diff_internal(
        self, old_spec: dict[str, Any], new_spec: dict[str, Any]
    ) -> list[ChangeRecord]:
        """Built-in Python OpenAPI 3.x / Swagger 2.0 structural diffing engine."""
        changes: list[ChangeRecord] = []

        old_paths: dict[str, Any] = old_spec.get("paths") or {}
        new_paths: dict[str, Any] = new_spec.get("paths") or {}

        # 1. Check for removed paths
        for path, path_item in old_paths.items():
            if not isinstance(path_item, dict):
                continue
            if path not in new_paths:
                changes.append(
                    ChangeRecord(
                        endpoint=path,
                        method="ALL",
                        change_type="endpoint_removed",
                        breaking=True,
                        description=f"Endpoint `{path}` was removed from the API specification",
                        raw={"path": path, "reason": "path_removed"},
                    )
                )
            else:
                new_path_item = new_paths[path]
                if isinstance(new_path_item, dict):
                    changes.extend(self._diff_path_item(path, path_item, new_path_item))

        # 2. Check for newly added paths (non-breaking)
        for path in new_paths:
            if path not in old_paths:
                changes.append(
                    ChangeRecord(
                        endpoint=path,
                        method="ALL",
                        change_type="endpoint_added",
                        breaking=False,
                        description=f"Endpoint `{path}` was added to the API specification",
                        raw={"path": path, "reason": "path_added"},
                    )
                )

        return changes

    def _diff_path_item(
        self, path: str, old_item: dict[str, Any], new_item: dict[str, Any]
    ) -> list[ChangeRecord]:
        """Diff operations within a path item."""
        changes: list[ChangeRecord] = []
        http_methods = {"get", "post", "put", "delete", "patch", "options", "head"}

        # Deprecation at path level
        if not old_item.get("deprecated") and new_item.get("deprecated"):
            changes.append(
                ChangeRecord(
                    endpoint=path,
                    method="ALL",
                    change_type="endpoint_deprecated",
                    breaking=False,
                    description=f"Endpoint `{path}` has been marked as deprecated",
                    raw={"path": path, "deprecated": True},
                )
            )

        for method in http_methods:
            old_op = old_item.get(method)
            new_op = new_item.get(method)

            if old_op is not None and new_op is None:
                changes.append(
                    ChangeRecord(
                        endpoint=path,
                        method=method.upper(),
                        change_type="operation_removed",
                        breaking=True,
                        description=f"Method `{method.upper()} {path}` was removed",
                        raw={"path": path, "method": method},
                    )
                )
            elif old_op is None and new_op is not None:
                changes.append(
                    ChangeRecord(
                        endpoint=path,
                        method=method.upper(),
                        change_type="operation_added",
                        breaking=False,
                        description=f"Method `{method.upper()} {path}` was added",
                        raw={"path": path, "method": method},
                    )
                )
            elif isinstance(old_op, dict) and isinstance(new_op, dict):
                changes.extend(self._diff_operation(path, method.upper(), old_op, new_op))

        return changes

    def _diff_operation(
        self, path: str, method: str, old_op: dict[str, Any], new_op: dict[str, Any]
    ) -> list[ChangeRecord]:
        """Diff operation parameters, request body, and responses."""
        changes: list[ChangeRecord] = []

        # Deprecation at operation level
        if not old_op.get("deprecated") and new_op.get("deprecated"):
            changes.append(
                ChangeRecord(
                    endpoint=path,
                    method=method,
                    change_type="operation_deprecated",
                    breaking=False,
                    description=f"Operation `{method} {path}` was marked as deprecated",
                    raw={"path": path, "method": method, "deprecated": True},
                )
            )

        # 1. Diff Parameters (query, path, header, etc.)
        old_params = {
            p.get("name"): p
            for p in old_op.get("parameters", [])
            if isinstance(p, dict) and "name" in p
        }
        new_params = {
            p.get("name"): p
            for p in new_op.get("parameters", [])
            if isinstance(p, dict) and "name" in p
        }

        for param_name, old_p in old_params.items():
            if param_name not in new_params:
                # Removed parameter
                changes.append(
                    ChangeRecord(
                        endpoint=path,
                        method=method,
                        field=param_name,
                        change_type="parameter_removed",
                        breaking=True,
                        description=f"Parameter `{param_name}` was removed from `{method} {path}`",
                        raw={"parameter": param_name, "old": old_p},
                    )
                )
            else:
                new_p = new_params[param_name]
                # Check deprecation
                if not old_p.get("deprecated") and new_p.get("deprecated"):
                    changes.append(
                        ChangeRecord(
                            endpoint=path,
                            method=method,
                            field=param_name,
                            change_type="parameter_deprecated",
                            breaking=False,
                            description=f"Parameter `{param_name}` on `{method} {path}` was marked as deprecated",
                            raw={"parameter": param_name},
                        )
                    )
                # Check type changes
                old_type = self._get_schema_type(old_p)
                new_type = self._get_schema_type(new_p)
                if old_type and new_type and old_type != new_type:
                    changes.append(
                        ChangeRecord(
                            endpoint=path,
                            method=method,
                            field=param_name,
                            change_type="parameter_type_changed",
                            breaking=True,
                            description=f"Type of parameter `{param_name}` changed from `{old_type}` to `{new_type}`",
                            raw={
                                "parameter": param_name,
                                "old_type": old_type,
                                "new_type": new_type,
                            },
                        )
                    )

        for param_name, new_p in new_params.items():
            if param_name not in old_params:
                # If a newly added param is required, it is breaking
                is_required = new_p.get("required", False)
                changes.append(
                    ChangeRecord(
                        endpoint=path,
                        method=method,
                        field=param_name,
                        change_type="required_parameter_added"
                        if is_required
                        else "optional_parameter_added",
                        breaking=is_required,
                        description=f"{'Required' if is_required else 'Optional'} parameter `{param_name}` was added to `{method} {path}`",
                        raw={"parameter": param_name, "required": is_required},
                    )
                )

        # 2. Diff Request Body Schema (OpenAPI 3.x)
        old_req_schema = self._extract_body_schema(old_op.get("requestBody"))
        new_req_schema = self._extract_body_schema(new_op.get("requestBody"))
        if old_req_schema or new_req_schema:
            changes.extend(
                self._diff_schema(
                    path=path,
                    method=method,
                    old_schema=old_req_schema or {},
                    new_schema=new_req_schema or {},
                    location="request_body",
                )
            )

        # 3. Diff Response Schemas (200 / 201 / 2xx)
        old_responses = old_op.get("responses") or {}
        new_responses = new_op.get("responses") or {}
        for status_code, old_resp in old_responses.items():
            if not isinstance(old_resp, dict):
                continue
            if status_code not in new_responses:
                changes.append(
                    ChangeRecord(
                        endpoint=path,
                        method=method,
                        change_type="response_code_removed",
                        breaking=True,
                        description=f"Response status `{status_code}` was removed from `{method} {path}`",
                        raw={"status_code": status_code},
                    )
                )
            else:
                new_resp = new_responses[status_code]
                if isinstance(new_resp, dict):
                    old_resp_schema = self._extract_response_schema(old_resp)
                    new_resp_schema = self._extract_response_schema(new_resp)
                    if old_resp_schema or new_resp_schema:
                        changes.extend(
                            self._diff_schema(
                                path=path,
                                method=method,
                                old_schema=old_resp_schema or {},
                                new_schema=new_resp_schema or {},
                                location=f"response_{status_code}",
                            )
                        )

        return changes

    def _extract_body_schema(self, request_body: dict[str, Any] | None) -> dict[str, Any] | None:
        """Extract schema from OpenAPI 3.x requestBody or Swagger 2.0 body param."""
        if not isinstance(request_body, dict):
            return None
        content = request_body.get("content")
        if isinstance(content, dict):
            for media_type in ("application/json", "application/x-www-form-urlencoded", "*/*"):
                if media_type in content and isinstance(content[media_type], dict):
                    return content[media_type].get("schema")
            first_val = next(iter(content.values()), None)
            if isinstance(first_val, dict):
                return first_val.get("schema")
        if "schema" in request_body:
            return request_body["schema"]
        return None

    def _extract_response_schema(self, response_item: dict[str, Any]) -> dict[str, Any] | None:
        """Extract schema from OpenAPI 3.x response content or Swagger 2.0 schema."""
        content = response_item.get("content")
        if isinstance(content, dict):
            for media_type in ("application/json", "*/*"):
                if media_type in content and isinstance(content[media_type], dict):
                    return content[media_type].get("schema")
            first_val = next(iter(content.values()), None)
            if isinstance(first_val, dict):
                return first_val.get("schema")
        if "schema" in response_item:
            return response_item["schema"]
        return None

    def _get_schema_type(self, item: dict[str, Any]) -> str | None:
        schema = item.get("schema") if isinstance(item.get("schema"), dict) else item
        return schema.get("type")

    def _diff_schema(
        self,
        path: str,
        method: str,
        old_schema: dict[str, Any],
        new_schema: dict[str, Any],
        location: str,
    ) -> list[ChangeRecord]:
        """Diff object schema properties recursively."""
        changes: list[ChangeRecord] = []

        old_props: dict[str, Any] = old_schema.get("properties") or {}
        new_props: dict[str, Any] = new_schema.get("properties") or {}
        old_required = set(old_schema.get("required") or [])
        new_required = set(new_schema.get("required") or [])

        is_response = location.startswith("response")

        # 1. Removed properties
        for prop_name, old_p in old_props.items():
            if not isinstance(old_p, dict):
                continue
            if prop_name not in new_props:
                # In responses, removing a property breaks clients reading it.
                # In requests, removing a property breaks clients sending it.
                changes.append(
                    ChangeRecord(
                        endpoint=path,
                        method=method,
                        field=prop_name,
                        change_type="field_removed",
                        breaking=True,
                        description=f"Field `{prop_name}` was removed from `{method} {path}` ({location})",
                        raw={"field": prop_name, "location": location, "old_property": old_p},
                    )
                )
            else:
                new_p = new_props[prop_name]
                if isinstance(new_p, dict):
                    # Check deprecation
                    if not old_p.get("deprecated") and new_p.get("deprecated"):
                        desc = f"Field `{prop_name}` is deprecated"
                        if "description" in new_p and "deprecated" in new_p["description"].lower():
                            desc += f": {new_p['description']}"
                        changes.append(
                            ChangeRecord(
                                endpoint=path,
                                method=method,
                                field=prop_name,
                                change_type="field_deprecated",
                                breaking=False,
                                description=desc,
                                raw={"field": prop_name, "location": location},
                            )
                        )

                    # Check type change
                    old_t = old_p.get("type")
                    new_t = new_p.get("type")
                    if old_t and new_t and old_t != new_t:
                        changes.append(
                            ChangeRecord(
                                endpoint=path,
                                method=method,
                                field=prop_name,
                                change_type="field_type_changed",
                                breaking=True,
                                description=f"Field `{prop_name}` type changed from `{old_t}` to `{new_t}` in `{method} {path}`",
                                raw={"field": prop_name, "old_type": old_t, "new_type": new_t},
                            )
                        )

        # 2. Added properties
        for prop_name, new_p in new_props.items():
            if prop_name not in old_props:
                is_req = prop_name in new_required
                # Adding a required field in request body is breaking
                breaking = is_req and not is_response
                changes.append(
                    ChangeRecord(
                        endpoint=path,
                        method=method,
                        field=prop_name,
                        change_type="required_field_added" if is_req else "field_added",
                        breaking=breaking,
                        description=f"Field `{prop_name}` was added to `{method} {path}` ({location})",
                        raw={"field": prop_name, "location": location, "required": is_req},
                    )
                )

        # 3. Existing property made required
        for req_prop in new_required - old_required:
            if req_prop in old_props and not is_response:
                changes.append(
                    ChangeRecord(
                        endpoint=path,
                        method=method,
                        field=req_prop,
                        change_type="field_made_required",
                        breaking=True,
                        description=f"Field `{req_prop}` was made required in `{method} {path}` ({location})",
                        raw={"field": req_prop, "location": location},
                    )
                )

        return changes
