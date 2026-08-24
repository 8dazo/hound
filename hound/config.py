"""Configuration loader and validator for Hound."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from hound.models import HoundConfig

ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}|\$(\w+)")


def interpolate_env_vars(obj: Any) -> Any:
    """Recursively replace ${VAR} or $VAR in strings with environment variable values."""
    if isinstance(obj, str):

        def replace_match(match: re.Match) -> str:
            var_name = match.group(1) or match.group(2)
            return os.environ.get(var_name, "")

        return ENV_VAR_PATTERN.sub(replace_match, obj)
    elif isinstance(obj, dict):
        return {k: interpolate_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [interpolate_env_vars(item) for item in obj]
    return obj


def get_schema_path() -> Path:
    """Return path to configs/schema.json."""
    pkg_dir = Path(__file__).resolve().parent
    # Check parent repo dir first, then package dir
    candidates = [
        pkg_dir.parent / "configs" / "schema.json",
        pkg_dir / "schema.json",
        Path.cwd() / "configs" / "schema.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError("Could not find configs/schema.json")


def load_schema() -> dict[str, Any]:
    """Load JSON schema for configuration validation."""
    schema_path = get_schema_path()
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_raw_config(data: dict[str, Any]) -> None:
    """Validate raw dictionary config against JSON schema."""
    schema = load_schema()
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        field_path = " -> ".join(str(p) for p in e.path) if e.path else "root"
        raise ValueError(f"Config schema validation error at '{field_path}': {e.message}") from e


def load_config(config_path: str | Path = "hound.yaml") -> HoundConfig:
    """Load and validate Hound configuration from a YAML file."""
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path.resolve()}")

    with open(path, "r", encoding="utf-8") as f:
        try:
            raw_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML from {path}: {e}") from e

    if not isinstance(raw_data, dict):
        raise ValueError(f"Invalid configuration format in {path}: expected dictionary root")

    # Step 1: Validate against raw schema
    validate_raw_config(raw_data)

    # Step 2: Interpolate environment variables
    interpolated_data = interpolate_env_vars(raw_data)

    # Step 3: Parse through Pydantic
    try:
        return HoundConfig.model_validate(interpolated_data)
    except Exception as e:
        raise ValueError(f"Config validation error: {e}") from e


def generate_default_config(with_action: bool = False) -> str:
    """Generate default template for hound.yaml."""
    return """version: 1

watch:
  - name: stripe
    spec_url: https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json
    scan_paths:
      - src/services/payments/
    language: python
    ignore_fields: []

report:
  github_issues:
    enabled: true
    labels:
      - hound
      - dependency-risk
    assignees: []
  slack:
    enabled: false
    webhook_url: ${SLACK_WEBHOOK_URL}
  min_severity: breaking

llm:
  provider: none
  model: gpt-4o-mini
  api_key: ${OPENAI_API_KEY}
"""
