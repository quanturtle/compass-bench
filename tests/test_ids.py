from compass_bench.domain.ids import content_hash


def test_content_hash_ignores_key_order() -> None:
    assert content_hash({"a": 1, "b": [2, 3]}) == content_hash({"b": [2, 3], "a": 1})
