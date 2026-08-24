from pathlib import Path

from hound.agent import HoundAgent
from hound.config import load_config
from hound.store.snapshot_store import LocalSnapshotStore


def test_agent_end_to_end_baseline_and_breaking_detection(tmp_path):
    # Setup paths
    repo_dir = Path(__file__).resolve().parent.parent
    demo_dir = repo_dir / "examples" / "stripe_demo"

    store_dir = tmp_path / "snapshots"
    store = LocalSnapshotStore(base_dir=store_dir)

    cfg = load_config(demo_dir / "hound.yaml")
    # Point scan_paths and spec_url to absolute demo paths
    cfg.watch[0].spec_url = str(demo_dir / "specs" / "stripe_v1.json")
    cfg.watch[0].scan_paths = [str(demo_dir / "src")]

    agent = HoundAgent(config=cfg, store=store)

    # 1. Baseline run
    summary_1 = agent.run_check()
    assert summary_1.exit_code == 0
    assert summary_1.results[0].is_baseline is True
    assert summary_1.total_breaking == 0

    # 2. Re-run without spec change -> unchanged
    summary_2 = agent.run_check()
    assert summary_2.exit_code == 0
    assert summary_2.results[0].is_unchanged is True
    assert summary_2.total_breaking == 0

    # 3. Update spec to v2 (which removes source field)
    cfg.watch[0].spec_url = str(demo_dir / "specs" / "stripe_v2.json")
    agent_v2 = HoundAgent(config=cfg, store=store)

    summary_3 = agent_v2.run_check()
    assert summary_3.exit_code == 1
    assert summary_3.total_breaking >= 1
    assert len(summary_3.results[0].findings) >= 1
    finding = summary_3.results[0].findings[0]
    assert finding.is_breaking is True
    assert finding.change.field == "source"
    assert len(finding.usage_sites) == 1
    assert "charge.py" in finding.usage_sites[0].file
