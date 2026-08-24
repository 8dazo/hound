from click.testing import CliRunner

from hound.cli import main


def test_cli_init_and_validate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    # hound init
    res_init = runner.invoke(main, ["init"])
    assert res_init.exit_code == 0
    assert (tmp_path / "hound.yaml").exists()

    # hound validate
    res_val = runner.invoke(main, ["validate"])
    assert res_val.exit_code == 0
    assert "is valid" in res_val.output


def test_cli_add_and_baseline_reset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    runner.invoke(main, ["init"])
    res_add = runner.invoke(
        main,
        [
            "add",
            "stripe",
            "--spec-url",
            "https://api.example.com/spec.json",
            "--scan-path",
            "src/services/",
        ],
    )
    assert res_add.exit_code == 0

    res_reset = runner.invoke(main, ["baseline", "reset", "stripe"])
    assert res_reset.exit_code == 0
