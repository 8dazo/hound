import json

from hound.wizard import AutoDiscoveryWizard


def test_wizard_detect_python_stripe(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("stripe==5.0.0\nrequests>=2.30.0\n")

    wizard = AutoDiscoveryWizard(repo_dir=tmp_path)
    targets = wizard.detect_apis()

    assert any(t["name"] == "stripe" for t in targets)
    assert any("stripe/openapi" in t["spec_url"] for t in targets)

    config_yaml = wizard.generate_config()
    assert "version: 1" in config_yaml
    assert "stripe" in config_yaml


def test_wizard_detect_node_octokit(tmp_path):
    pkg_file = tmp_path / "package.json"
    pkg_file.write_text(
        json.dumps({"name": "my-app", "dependencies": {"@octokit/rest": "^19.0.0"}})
    )

    wizard = AutoDiscoveryWizard(repo_dir=tmp_path)
    targets = wizard.detect_apis()

    assert any(t["name"] == "github-api" for t in targets)
    assert any("rest-api-description" in t["spec_url"] for t in targets)
