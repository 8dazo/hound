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
