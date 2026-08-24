from hound.diffing.graphql_diff import GraphQLDiffEngine
from hound.usage_scanner.graphql_scanner import GraphQLScanner


def test_graphql_diff_field_removed_and_deprecated():
    old_sdl = """
type Query {
    user(id: ID!): User
}

type User {
    id: ID!
    name: String!
    legacyToken: String
}
"""

    new_sdl = """
type Query {
    user(id: ID!): User
}

type User {
    id: ID!
    name: String! @deprecated(reason: "Use fullName")
}
"""

    engine = GraphQLDiffEngine()
    changes = engine.diff(old_sdl, new_sdl)

    # legacyToken removed (breaking), name deprecated (non-breaking deprecation)
    breaking = [c for c in changes if c.breaking]
    deprecated = [c for c in changes if not c.breaking and "deprecated" in c.change_type]

    assert len(breaking) == 1
    assert breaking[0].field == "legacyToken"
    assert breaking[0].change_type == "field_removed"

    assert len(deprecated) == 1
    assert deprecated[0].field == "name"
    assert deprecated[0].change_type == "field_deprecated"


def test_graphql_scanner(tmp_path):
    gql_code = """
import { gql } from '@apollo/client';

const GET_USER = gql`
    query GetUser($id: ID!) {
        user(id: $id) {
            id
            name
            legacyToken
        }
    }
`;
"""
    file_path = tmp_path / "userQuery.ts"
    file_path.write_text(gql_code)

    scanner = GraphQLScanner()
    records = scanner.scan_file(file_path)

    assert len(records) >= 1
    r = records[0]
    assert "name" in r.fields_read
    assert "legacyToken" in r.fields_read
