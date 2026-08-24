"""GraphQL SDL schema parser and diffing engine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Set

from hound.models import ChangeRecord


@dataclass
class GraphQLField:
    name: str
    type_name: str
    is_deprecated: bool = False
    deprecation_reason: str = ""
    args: Dict[str, str] = field(default_factory=dict)


@dataclass
class GraphQLType:
    name: str
    kind: str  # "type" | "interface" | "input" | "enum"
    fields: Dict[str, GraphQLField] = field(default_factory=dict)
    enum_values: Set[str] = field(default_factory=set)


class GraphQLDiffEngine:
    """Computes structural diffs between two GraphQL SDL schema definitions."""

    def parse_sdl(self, sdl_text: str) -> Dict[str, GraphQLType]:
        """Lightweight parser for GraphQL SDL schema text."""
        types: Dict[str, GraphQLType] = {}

        # Strip comments
        clean_sdl = re.sub(r"""#[^\n]*""", "", sdl_text)

        # Match type / input / interface definitions: type User { ... }
        type_pattern = re.compile(
            r"""\b(type|input|interface|enum)\s+([A-Za-z0-9_]+)(?:\s+implements\s+[^{]+)?\s*\{([^}]*)\}""",
            re.MULTILINE,
        )

        for match in type_pattern.finditer(clean_sdl):
            kind = match.group(1)
            name = match.group(2)
            body = match.group(3)

            gt = GraphQLType(name=name, kind=kind)

            if kind == "enum":
                # Enum values
                for val in body.split():
                    val = val.strip()
                    if val and val.isidentifier():
                        gt.enum_values.add(val)
            else:
                # Fields
                field_lines = [f.strip() for f in body.splitlines() if f.strip()]
                for line in field_lines:
                    # fieldName(arg: Type): Type @deprecated(reason: "...")
                    f_match = re.match(
                        r"""([A-Za-z0-9_]+)(?:\(([^)]*)\))?\s*:\s*([A-Za-z0-9_!\[\]]+)(?:\s*@deprecated(?:\(reason:\s*["']([^"']*)["']\))?)?""",
                        line,
                    )
                    if f_match:
                        f_name = f_match.group(1)
                        f_args_raw = f_match.group(2)
                        f_type = f_match.group(3)
                        is_dep = "@deprecated" in line
                        dep_reason = f_match.group(4) or ""

                        args_dict = {}
                        if f_args_raw:
                            for arg_part in f_args_raw.split(","):
                                if ":" in arg_part:
                                    aname, atype = arg_part.split(":", 1)
                                    args_dict[aname.strip()] = atype.strip()

                        gt.fields[f_name] = GraphQLField(
                            name=f_name,
                            type_name=f_type,
                            is_deprecated=is_dep,
                            deprecation_reason=dep_reason,
                            args=args_dict,
                        )

            types[name] = gt

        return types

    def diff(self, old_sdl: str, new_sdl: str) -> List[ChangeRecord]:
        """Diff two GraphQL SDL schemas and return discrete change records."""
        old_types = self.parse_sdl(old_sdl)
        new_types = self.parse_sdl(new_sdl)

        changes: List[ChangeRecord] = []

        # 1. Check for removed types
        for type_name, old_t in old_types.items():
            if type_name not in new_types:
                changes.append(
                    ChangeRecord(
                        endpoint=f"GraphQL:{type_name}",
                        method="POST",
                        change_type="type_removed",
                        breaking=True,
                        description=f"GraphQL type `{type_name}` was removed from schema",
                        raw={"type": type_name},
                    )
                )
            else:
                new_t = new_types[type_name]
                changes.extend(self._diff_type(type_name, old_t, new_t))

        # 2. Check for newly added types (non-breaking)
        for type_name in new_types:
            if type_name not in old_types:
                changes.append(
                    ChangeRecord(
                        endpoint=f"GraphQL:{type_name}",
                        method="POST",
                        change_type="type_added",
                        breaking=False,
                        description=f"GraphQL type `{type_name}` was added to schema",
                        raw={"type": type_name},
                    )
                )

        return changes

    def _diff_type(
        self, type_name: str, old_t: GraphQLType, new_t: GraphQLType
    ) -> List[ChangeRecord]:
        changes: List[ChangeRecord] = []

        # Check fields
        for field_name, old_f in old_t.fields.items():
            if field_name not in new_t.fields:
                changes.append(
                    ChangeRecord(
                        endpoint=f"GraphQL:{type_name}",
                        method="POST",
                        field=field_name,
                        change_type="field_removed",
                        breaking=True,
                        description=f"Field `{field_name}` was removed from GraphQL type `{type_name}`",
                        raw={"type": type_name, "field": field_name},
                    )
                )
            else:
                new_f = new_t.fields[field_name]
                # Deprecation
                if not old_f.is_deprecated and new_f.is_deprecated:
                    reason = f": {new_f.deprecation_reason}" if new_f.deprecation_reason else ""
                    changes.append(
                        ChangeRecord(
                            endpoint=f"GraphQL:{type_name}",
                            method="POST",
                            field=field_name,
                            change_type="field_deprecated",
                            breaking=False,
                            description=f"Field `{type_name}.{field_name}` has been marked as deprecated{reason}",
                            raw={"type": type_name, "field": field_name},
                        )
                    )
                # Type change
                if old_f.type_name != new_f.type_name:
                    changes.append(
                        ChangeRecord(
                            endpoint=f"GraphQL:{type_name}",
                            method="POST",
                            field=field_name,
                            change_type="field_type_changed",
                            breaking=True,
                            description=f"Type of `{type_name}.{field_name}` changed from `{old_f.type_name}` to `{new_f.type_name}`",
                            raw={
                                "type": type_name,
                                "field": field_name,
                                "old_type": old_f.type_name,
                                "new_type": new_f.type_name,
                            },
                        )
                    )

        # Added fields
        for field_name in new_t.fields:
            if field_name not in old_t.fields:
                changes.append(
                    ChangeRecord(
                        endpoint=f"GraphQL:{type_name}",
                        method="POST",
                        field=field_name,
                        change_type="field_added",
                        breaking=False,
                        description=f"Field `{field_name}` was added to GraphQL type `{type_name}`",
                        raw={"type": type_name, "field": field_name},
                    )
                )

        return changes
