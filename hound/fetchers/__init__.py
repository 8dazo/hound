"""Spec and documentation fetchers."""

from hound.fetchers.changelog_scraper import ChangelogEntry, ChangelogScraper
from hound.fetchers.docs_fetcher import DocChunk, DocsFetcher
from hound.fetchers.openapi_fetcher import FetchedSpec, OpenAPIFetcher

__all__ = [
    "OpenAPIFetcher",
    "FetchedSpec",
    "DocsFetcher",
    "DocChunk",
    "ChangelogScraper",
    "ChangelogEntry",
]
