"""docs/architecture.md lists each report type's fields as `Name(field, ...)`; every such list matches the schema."""

import json
import re
from pathlib import Path
from typing import Final

from compass_bench.contract.schema import POOLED_SCHEMA_FILE, SCHEMA_FILE
from compass_bench.domain.claims import ReasonKind

REPOSITORY: Final = Path(__file__).parent.parent
ARCHITECTURE: Final = REPOSITORY / "docs" / "architecture.md"
# `Name(field, field)`: a type and its fields in the order the schema holds them
TYPE_LISTING: Final = re.compile(r"`([A-Z][A-Za-z]+)\(([a-z_, ]+)\)")
# a reason's tag and fields, as the doc lists a variant: `tag(field, field)`
REASON_LISTING: Final = re.compile(r"^  - `([a-z_]+)\(([a-z_, ]+)\)`")
# a union's discriminator: the doc leaves it out of every listing
TAG: Final = "kind"


def schema_fields() -> dict[str, list[str]]:
    """Each object type of both schemas, by name, with its fields in order and the tag left out."""
    fields: dict[str, list[str]] = {}
    for name in (SCHEMA_FILE, POOLED_SCHEMA_FILE):
        schema = json.loads((REPOSITORY / "schema" / name).read_text(encoding="utf-8"))
        definitions = {**schema["$defs"], schema["title"]: schema}
        for title, definition in definitions.items():
            if "properties" in definition:
                fields[title] = [field for field in definition["properties"] if field != TAG]
    return fields


def reason_fields() -> dict[str, list[str]]:
    """Each reason variant's fields, keyed by its tag, the ReasonKind value the doc lists it under."""
    tags = {str(kind) for kind in ReasonKind}
    schema = json.loads((REPOSITORY / "schema" / SCHEMA_FILE).read_text(encoding="utf-8"))
    variants: dict[str, list[str]] = {}
    for definition in schema["$defs"].values():
        tag = definition.get("properties", {}).get(TAG, {}).get("const")
        if tag in tags:
            variants[tag] = [field for field in definition["properties"] if field != TAG]
    return variants


def test_every_field_list_in_the_architecture_doc_matches_the_schema() -> None:
    known, reasons = schema_fields(), reason_fields()
    listed: list[tuple[int, str, list[str], list[str]]] = []
    for number, line in enumerate(ARCHITECTURE.read_text(encoding="utf-8").splitlines(), 1):
        for name, fields in TYPE_LISTING.findall(line):
            if name in known:
                listed.append((number, name, [field.strip() for field in fields.split(",")], known[name]))
        for tag, fields in REASON_LISTING.findall(line):
            if tag in reasons:
                listed.append((number, tag, [field.strip() for field in fields.split(",")], reasons[tag]))

    assert {name for _, name, _, _ in listed} >= set(reasons)
    for number, name, doc, schema in listed:
        assert doc == schema, f"docs/architecture.md:{number} lists {name}({', '.join(doc)})"
