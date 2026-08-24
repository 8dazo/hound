"""LLM-assisted severity classifier for unstructured prose and changelog changes."""

from __future__ import annotations

import json
import logging
import re
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
    """Classifies prose changes using OpenRouter, OpenAI, or heuristic fallback."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def classify_prose_change(self, heading: str, excerpt: str) -> ClassificationResult:
        """Classify a documentation / changelog text diff."""
        if self.config.provider == "none" or not self.config.api_key:
            return self._heuristic_fallback(heading, excerpt)

        if self.config.provider in ("openai", "openrouter"):
            return self._classify_chat_completion(heading, excerpt)

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

    def _classify_chat_completion(self, heading: str, excerpt: str) -> ClassificationResult:
        """Call OpenRouter or OpenAI API to classify changelog text into JSON."""
        if self.config.api_base:
            url = self.config.api_base
        elif self.config.provider == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
        else:
            url = "https://api.openai.com/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/8dazo/hound",
            "X-Title": "Hound API Watchdog",
        }

        prompt = f"""You are an API compatibility analyzer. Analyze the following documentation diff excerpt from section '{heading}' and determine if it introduces a breaking change, a deprecation, or a non-breaking modification.

Excerpt:
\"\"\"
{excerpt}
\"\"\"

Respond strictly with a JSON object in this format:
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
                    "content": "You are a precise API compatibility analyzer. Always output valid JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=25.0)
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"].strip()

            # Clean markdown fences like ```json ... ```
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw_content, flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

            # Find JSON block if extra text is present
            json_match = re.search(r"\{[\s\S]*\}", cleaned)
            if json_match:
                cleaned = json_match.group(0)

            parsed = json.loads(cleaned)
            sev = parsed.get("severity", "non_breaking").lower()
            if sev not in ("breaking", "deprecation", "non_breaking"):
                sev = "non_breaking"
            summary = parsed.get("summary", f"Change in {heading}")
            return ClassificationResult(severity=sev, summary=summary, excerpt=excerpt)
        except Exception as e:
            logger.warning(
                f"LLM classification ({self.config.provider}/{self.config.model}) failed, falling back to heuristic: {e}"
            )
            return self._heuristic_fallback(heading, excerpt)
