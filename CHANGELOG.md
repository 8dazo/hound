# Changelog

All notable changes to **Hound** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2026-08-24

### Added
- **Core Engine**: Deterministic OpenAPI diffing and blast-radius correlation with codebase usage sites.
- **Python AST Scanner**: Static analysis for `requests`, `httpx`, HTTP clients, f-strings, variable URLs, and SDK calls.
- **Scope Field Analyzer**: Dataflow tracking for response dictionary subscripts (`res["source"]`), `.get()`, attribute accesses, and request payload keyword arguments.
- **TypeScript / JavaScript Scanner**: Multi-language support for `.ts`, `.tsx`, `.js`, `.jsx` files detecting `fetch()`, `axios`, and JS SDK calls.
- **Vendor Changelog Scraper**: HTML and RSS/Atom feed parser for non-spec APIs.
- **Snapshot Persistence**: Idempotent baseline management (`.hound/snapshots/`) with SHA256 content hashing.
- **Reporters**: Markdown GitHub Issues generator with blast-radius tables and Slack incoming webhook notifications.
- **CLI**: Rich terminal interface with `init`, `add`, `check`, `validate`, `diff`, and `baseline reset`.
- **CI/CD & Workflows**: GitHub Actions test matrix across Python 3.10–3.12 and automated PyPI release publishing on tags.
