"""YAML that refuses a repeated key instead of keeping the last one, and reads only true and false as booleans."""

import re
from typing import Final

import yaml

BOOL_TAG: Final = "tag:yaml.org,2002:bool"
MERGE_TAG: Final = "tag:yaml.org,2002:merge"


class UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader whose mappings reject a repeated key and whose booleans are only true and false.

    YAML 1.1 reads `off`, `no`, and `yes` as booleans; here they stay strings, so `reasoning: off` parses."""


def construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode) -> dict[str, object]:
    """Every key is a string, as JSON needs; a key repeats only to override one that a `<<` merge brought in.

    A second `<<` key is refused, since `<<: [*a, *b]` merges several mappings."""
    merge_keys = [key_node for key_node, _ in node.value if key_node.tag == MERGE_TAG]
    if len(merge_keys) > 1:
        raise yaml.constructor.ConstructorError(
            "while constructing a mapping", node.start_mark, "found repeated key '<<'", merge_keys[1].start_mark
        )
    own_count = len(node.value) - len(merge_keys)
    # flatten_mapping puts the merged pairs before the mapping's own, so later pairs override earlier ones
    loader.flatten_mapping(node)
    merged_count = len(node.value) - own_count
    mapping: dict[str, object] = {}
    own_keys: set[str] = set()
    for index, (key_node, value_node) in enumerate(node.value):
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark, f"found non-string key {key!r}", key_node.start_mark
            )
        if index >= merged_count and key in own_keys:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark, f"found repeated key {key!r}", key_node.start_mark
            )
        if index >= merged_count:
            own_keys.add(key)
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


# copy SafeLoader's resolvers without its YAML 1.1 booleans, so SafeLoader itself is untouched
UniqueKeyLoader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers if tag != BOOL_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
UniqueKeyLoader.add_implicit_resolver(BOOL_TAG, re.compile(r"^(?:true|false)$"), list("tf"))
UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping)


def parse_yaml(text: str) -> object:
    return yaml.load(text, Loader=UniqueKeyLoader)
