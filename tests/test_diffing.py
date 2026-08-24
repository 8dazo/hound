from hound.diffing.spec_diff import SpecDiffEngine


def test_diff_field_removed():
    old_spec = {
        "openapi": "3.0.0",
        "paths": {
            "/v1/charges": {
                "post": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "source": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    new_spec = {
        "openapi": "3.0.0",
        "paths": {
            "/v1/charges": {
                "post": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    engine = SpecDiffEngine(prefer_oasdiff=False)
    changes = engine.diff(old_spec, new_spec)

    assert len(changes) == 1
    c = changes[0]
    assert c.endpoint == "/v1/charges"
    assert c.method == "POST"
    assert c.field == "source"
    assert c.change_type == "field_removed"
    assert c.breaking is True


def test_diff_endpoint_removed():
    old_spec = {
        "openapi": "3.0.0",
        "paths": {
            "/v1/charges": {"post": {}},
            "/v1/tokens": {"post": {}},
        },
    }
    new_spec = {
        "openapi": "3.0.0",
        "paths": {
            "/v1/charges": {"post": {}},
        },
    }

    engine = SpecDiffEngine(prefer_oasdiff=False)
    changes = engine.diff(old_spec, new_spec)

    assert len(changes) == 1
    assert changes[0].endpoint == "/v1/tokens"
    assert changes[0].change_type == "endpoint_removed"
    assert changes[0].breaking is True
