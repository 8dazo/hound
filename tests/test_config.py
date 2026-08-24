import pytest

from hound.config import interpolate_env_vars, load_config


def test_interpolate_env_vars(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret_123")
    monkeypatch.setenv("TEST_URL", "https://api.example.com")

    data = {
        "key": "${TEST_KEY}",
        "url": "$TEST_URL",
        "nested": {"list": ["${TEST_KEY}", "plain"]},
    }
    res = interpolate_env_vars(data)
    assert res["key"] == "secret_123"
    assert res["url"] == "https://api.example.com"
    assert res["nested"]["list"][0] == "secret_123"
    assert res["nested"]["list"][1] == "plain"


def test_valid_config(tmp_path):
    yaml_content = """version: 1
watch:
  - name: test-api
    spec_url: https://example.com/openapi.json
    scan_paths:
      - src/
    language: python
report:
  min_severity: breaking
"""
    cfg_file = tmp_path / "hound.yaml"
    cfg_file.write_text(yaml_content)

    config = load_config(cfg_file)
    assert config.version == 1
    assert len(config.watch) == 1
    assert config.watch[0].name == "test-api"
    assert config.watch[0].scan_paths == ["src/"]


def test_invalid_config_schema(tmp_path):
    # Missing version & watch
    yaml_content = """report:
  min_severity: invalid_sev
"""
    cfg_file = tmp_path / "hound.yaml"
    cfg_file.write_text(yaml_content)

    with pytest.raises(ValueError, match="Config schema validation error"):
        load_config(cfg_file)


def test_missing_config_file():
    with pytest.raises(FileNotFoundError):
        load_config("non_existent_hound.yaml")
