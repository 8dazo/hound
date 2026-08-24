"""LLM-assisted severity classifier for unstructured prose and changelog changes."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import requests

from hound.models import LLMConfig

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    severity: str  # "breaking" | "deprecation" | "non_breaking"
    summary: str
    excerpt: str


class LLMClassifier:
    """Classifies prose changes using OpenAI, Azure OpenAI, or heuristic fallback."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def classify_prose_change(self, heading: str, excerpt: str) -> ClassificationResult:
        """Classify a documentation / changelog text diff."""
        if self.config.provider == "none" or not self.config.api_key:
            return self._heuristic_fallback(heading, excerpt)

        if self.config.provider == "openai":
            return self._classify_openai(heading, excerpt)

        return self._heuristic_fallback(heading, excerpt)

    def _heuristic_fallback(self, heading: str, excerpt: str) -> ClassificationResult:
        """Deterministic keyword-based classification when LLM is disabled or unavailable."""
        lower = (heading + "\n" + excerpt).lower()
        if any(w in lower for w in ("breaking", "removed", "no longer supported", "deleted")):
            severity = "breaking"
        elif any(w in lower for w in ("deprecat", "sunset", "planned removal")):
            severity = "deprecation"
        else:
            severity = "non_breaking"

        return ClassificationResult(
            severity=severity,
            summary=f"Section '{heading}' modified",
            excerpt=excerpt,
        )

    def _classify_openai(self, heading: str, excerpt: str) -> ClassificationResult:
        """Call OpenAI API to classify changelog text into JSON."""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        prompt = f"""You are an API compatibility analyzer. Analyze the following documentation diff excerpt from section '{heading}' and determine if it introduces a breaking change, a deprecation, or a non-breaking modification.

Excerpt:
\"\"\"
{excerpt}
\"\"\"

Respond with a JSON object strictly matching this schema:
{{
  "severity": "breaking" | "deprecation" | "non_breaking",
  "summary": "one sentence explanation"
}}
"""
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise API compatibility analyzer. Always return JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            sev = parsed.get("severity", "non_breaking").lower()
            if sev not in ("breaking", "deprecation", "non_breaking"):
                sev = "non_breaking"
            summary = parsed.get("summary", f"Change in {heading}")
            return ClassificationResult(severity=sev, summary=summary, excerpt=excerpt)
        except Exception as e:
            logger.warning(f"OpenAI classification failed, falling back to heuristic: {e}")
            return self._heuristic_fallback(heading, excerpt)
