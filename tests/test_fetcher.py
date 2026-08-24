import json

import pytest

from hound.fetchers.openapi_fetcher import OpenAPIFetcher


def test_fetch_local_file_with_ref_resolution(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                    },
                }
            }
        },
        "paths": {
            "/users": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/User"}
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    file_path = tmp_path / "openapi.json"
    file_path.write_text(json.dumps(spec))

    fetcher = OpenAPIFetcher()
    fetched = fetcher.fetch(str(file_path))

    assert fetched.content_hash is not None
    # Verify $ref is normalized/resolved
    resolved_schema = fetched.spec["paths"]["/users"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert resolved_schema["type"] == "object"
    assert "id" in resolved_schema["properties"]


def test_fetch_missing_file():
    fetcher = OpenAPIFetcher()
    with pytest.raises(FileNotFoundError):
        fetcher.fetch("non_existent_spec.json")
