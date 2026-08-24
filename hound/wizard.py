"""Auto-discovery wizard for detecting third-party API dependencies in repositories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

KNOWN_API_CATALOG = {
    "stripe": {
        "name": "stripe",
        "spec_url": "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json",
        "keywords": ["stripe", "stripe-node"],
    },
    "github": {
        "name": "github-api",
        "spec_url": "https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json",
        "keywords": ["@octokit/rest", "octokit", "pygithub", "github"],
    },
    "openai": {
        "name": "openai",
        "spec_url": "https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml",
        "keywords": ["openai"],
    },
    "twilio": {
        "name": "twilio",
        "spec_url": "https://raw.githubusercontent.com/twilio/twilio-oai/main/spec/yaml/twilio_api_v2010.yaml",
        "keywords": ["twilio"],
    },
}


class AutoDiscoveryWizard:
    """Discovers third-party API dependencies in a repository and scaffolds configuration."""

    def __init__(self, repo_dir: Path | str = ".") -> None:
        self.repo_dir = Path(repo_dir)

    def detect_apis(self) -> List[Dict[str, Any]]:
        """Detect APIs used in project dependencies and source code."""
        detected_names = set()
        lang = "python"

        # 1. Check Python dependencies
        req_file = self.repo_dir / "requirements.txt"
        if req_file.is_file():
            text = req_file.read_text(encoding="utf-8").lower()
            for key, info in KNOWN_API_CATALOG.items():
                if any(kw in text for kw in info["keywords"]):
                    detected_names.add(key)

        pyproject_file = self.repo_dir / "pyproject.toml"
        if pyproject_file.is_file():
            text = pyproject_file.read_text(encoding="utf-8").lower()
            for key, info in KNOWN_API_CATALOG.items():
                if any(kw in text for kw in info["keywords"]):
                    detected_names.add(key)

        # 2. Check Node / JS / TS dependencies
        pkg_file = self.repo_dir / "package.json"
        if pkg_file.is_file():
            try:
                pkg_data = json.loads(pkg_file.read_text(encoding="utf-8"))
                deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                for dep_name in deps:
                    d_lower = dep_name.lower()
                    for key, info in KNOWN_API_CATALOG.items():
                        if any(
                            kw.lower() in d_lower or d_lower in kw.lower()
                            for kw in info["keywords"]
                        ):
                            detected_names.add(key)
                            lang = "typescript"
            except Exception:
                pass

        # 3. Detect scan paths
        scan_paths = []
        for candidate in ("src/", "lib/", "app/", "services/", "integrations/", "./"):
            if (self.repo_dir / candidate).exists():
                scan_paths.append(candidate)
                break
        if not scan_paths:
            scan_paths = ["./"]

        # Default fallback target if none auto-detected
        if not detected_names:
            detected_names.add("stripe")

        targets = []
        for name in detected_names:
            catalog_entry = KNOWN_API_CATALOG.get(
                name,
                {
                    "name": name,
                    "spec_url": f"https://api.example.com/{name}/openapi.json",
                },
            )
            targets.append(
                {
                    "name": catalog_entry["name"],
                    "spec_url": catalog_entry["spec_url"],
                    "scan_paths": scan_paths,
                    "language": lang,
                    "ignore_fields": [],
                }
            )

        return targets

    def generate_config(self) -> str:
        """Generate tailored hound.yaml content based on auto-discovery."""
        targets = self.detect_apis()
        config_dict = {
            "version": 1,
            "watch": targets,
            "report": {
                "github_issues": {
                    "enabled": True,
                    "labels": ["hound", "dependency-risk"],
                    "assignees": [],
                },
                "slack": {
                    "enabled": False,
                    "webhook_url": "${SLACK_WEBHOOK_URL}",
                },
                "min_severity": "breaking",
            },
            "llm": {
                "provider": "none",
                "model": "gpt-4o-mini",
                "api_key": "${OPENAI_API_KEY}",
            },
        }
        return yaml.safe_dump(config_dict, sort_keys=False)
