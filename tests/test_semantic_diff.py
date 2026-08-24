from hound.diffing.semantic_diff import SemanticDiffEngine
from hound.fetchers.docs_fetcher import DocChunk, DocsFetcher


def test_docs_chunking():
    doc = """# Introduction
Welcome to our API.

## Authentication
Use Bearer tokens for all requests.

## Rate Limits
You can make up to 100 req/min.
"""
    fetcher = DocsFetcher()
    chunks = fetcher.chunk_text(doc)
    assert len(chunks) == 3
    assert chunks[0].heading == "Introduction"
    assert chunks[1].heading == "Authentication"
    assert chunks[2].heading == "Rate Limits"


def test_semantic_diff():
    old_chunks = [
        DocChunk(heading="Rate Limits", content="Limit is 100 req/min.", chunk_id="1"),
    ]
    new_chunks = [
        DocChunk(
            heading="Rate Limits",
            content="Limit is drastically reduced to 10 req/min and violates legacy quotas.",
            chunk_id="1",
        ),
    ]
    engine = SemanticDiffEngine(change_threshold=0.8)
    diffs = engine.diff_chunks(old_chunks, new_chunks)
    assert len(diffs) == 1
    assert diffs[0].heading == "Rate Limits"
    assert diffs[0].diff_ratio < 0.8
