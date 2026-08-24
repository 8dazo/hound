# Contributing to Hound

Thank you for contributing to Hound! Hound is an open-source tool built to protect software systems from silent third-party API breakages.

---

## Development Setup

Hound uses [`uv`](https://github.com/astral-sh/uv) for fast and deterministic dependency management.

```bash
# 1. Clone repository
git clone https://github.com/8dazo/hound.git
cd hound

# 2. Create virtual environment & install dependencies with dev extras
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# 3. Run tests
pytest
```

---

## Code Quality & Standards

Before opening a pull request, ensure all linters and tests pass:

```bash
# Run Ruff linting
ruff check .

# Check formatting
ruff format --check .

# Run pytest with full coverage
pytest -v --cov=hound
```

---

## Adding a New Language Scanner or SDK Signature

### Adding an SDK Signature
Edit `hound/usage_scanner/sdk_signatures.yaml` to map new client libraries or SDK method patterns to their underlying OpenAPI endpoints:

```yaml
- pattern: "twilio.messages.create"
  endpoint: "/2010-04-01/Accounts/{AccountSid}/Messages.json"
  method: "POST"
```

### Adding a Language Scanner
1. Implement the scanner interface under `hound/usage_scanner/<language>_scanner.py`.
2. Ensure it produces standard `UsageRecord` objects with accurate `file` and `line` numbers.
3. Wire the scanner into `hound/agent.py`.
4. Add unit test coverage in `tests/`.

---

## Pull Request Guidelines

1. **Keep PRs focused**: One feature or bugfix per PR.
2. **Include tests**: Every bugfix or new feature must have accompanying unit tests.
3. **Update documentation**: Update `README.md` or `CHANGELOG.md` when introducing user-facing changes.
