from hound.llm.classify import LLMClassifier
from hound.models import LLMConfig


def test_heuristic_classifier_breaking():
    cfg = LLMConfig(provider="none")
    classifier = LLMClassifier(cfg)

    res = classifier.classify_prose_change(
        heading="Breaking Changes in 2026-05",
        excerpt="The old endpoint is removed and no longer supported.",
    )
    assert res.severity == "breaking"


def test_heuristic_classifier_deprecation():
    cfg = LLMConfig(provider="none")
    classifier = LLMClassifier(cfg)

    res = classifier.classify_prose_change(
        heading="Deprecation Warning",
        excerpt="The source field is deprecated and will sunset in Q4.",
    )
    assert res.severity == "deprecation"


def test_heuristic_classifier_non_breaking():
    cfg = LLMConfig(provider="none")
    classifier = LLMClassifier(cfg)

    res = classifier.classify_prose_change(
        heading="New Features",
        excerpt="We added support for French translations.",
    )
    assert res.severity == "non_breaking"


def test_openrouter_classifier_mock(monkeypatch):
    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '```json\n{"severity": "breaking", "summary": "Field removed"}\n```'
                        }
                    }
                ]
            }

    import requests

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: MockResponse())

    cfg = LLMConfig(provider="openrouter", model="stealth/ox-alpha", api_key="sk-test")
    classifier = LLMClassifier(cfg)
    res = classifier.classify_prose_change("Heading", "Excerpt")

    assert res.severity == "breaking"
    assert res.summary == "Field removed"
