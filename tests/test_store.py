from hound.store.snapshot_store import LocalSnapshotStore


def test_snapshot_store_lifecycle(tmp_path):
    store = LocalSnapshotStore(base_dir=tmp_path / "snapshots")

    # Initial state
    assert store.get_snapshot("stripe") is None
    assert store.get_snapshot_hash("stripe") is None

    # Save
    spec_data = {"openapi": "3.0.0", "paths": {}}
    store.save_snapshot("stripe", spec_data, "hash_12345")

    # Read back
    saved = store.get_snapshot("stripe")
    assert saved == spec_data
    assert store.get_snapshot_hash("stripe") == "hash_12345"

    # Reset
    assert store.reset_snapshot("stripe") is True
    assert store.get_snapshot("stripe") is None
    assert store.reset_snapshot("stripe") is False
