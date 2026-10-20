"""Pruebas del identificador por contenido definido en ADR09."""

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.ids import content_id

HASH_A = "a" * 64
HASH_B = "b" * 64
HASHES = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)
PATHS = st.text(
    alphabet=st.characters(blacklist_characters="\t\n\r", blacklist_categories=("Cs",)),
    min_size=1,
    max_size=20,
)
ENTRIES = st.lists(st.tuples(PATHS, HASHES), min_size=1, max_size=8, unique_by=lambda item: item[0])


def test_matches_the_definition_in_adr09() -> None:
    expected = sha256_bytes(f"a.xml\t{HASH_A}\nb.xml\t{HASH_B}\n".encode())
    assert content_id([("b.xml", HASH_B), ("a.xml", HASH_A)]) == expected


@given(data=st.data())
@settings(max_examples=50, deadline=None)
def test_order_does_not_matter(data: st.DataObject) -> None:
    entries = data.draw(ENTRIES)
    shuffled = data.draw(st.permutations(entries))
    assert content_id(entries) == content_id(shuffled)


@given(entries=ENTRIES, new_hash=HASHES, position=st.integers(min_value=0, max_value=7))
@settings(max_examples=50, deadline=None)
def test_changing_a_hash_changes_the_id(
    entries: list[tuple[str, str]], new_hash: str, position: int
) -> None:
    index = position % len(entries)
    assume(entries[index][1] != new_hash)
    changed = list(entries)
    changed[index] = (entries[index][0], new_hash)
    assert content_id(changed) != content_id(entries)


@given(entries=ENTRIES, position=st.integers(min_value=0, max_value=7))
@settings(max_examples=50, deadline=None)
def test_changing_a_path_changes_the_id(entries: list[tuple[str, str]], position: int) -> None:
    index = position % len(entries)
    renamed = entries[index][0] + "_"
    assume(all(renamed != path for path, _ in entries))
    changed = list(entries)
    changed[index] = (renamed, entries[index][1])
    assert content_id(changed) != content_id(entries)


def test_rejects_an_empty_set() -> None:
    with pytest.raises(ValueError, match="vacío"):
        content_id([])


def test_rejects_duplicated_paths() -> None:
    with pytest.raises(ValueError, match="duplicad"):
        content_id([("a.xml", HASH_A), ("a.xml", HASH_B)])


@pytest.mark.parametrize("path", ["a\tb", "a\nb", "a\rb", ""])
def test_rejects_paths_that_break_the_line_format(path: str) -> None:
    with pytest.raises(ValueError, match="ruta"):
        content_id([(path, HASH_A)])


@pytest.mark.parametrize("digest", ["", "abc", "g" * 64, "A" * 64, "a" * 63, "a" * 65])
def test_rejects_malformed_hashes(digest: str) -> None:
    with pytest.raises(ValueError, match="sha256"):
        content_id([("a.xml", digest)])
