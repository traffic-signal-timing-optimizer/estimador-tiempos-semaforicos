"""Pruebas de las funciones de hash SHA-256."""

import hashlib
from pathlib import Path

import pytest

from semaforo.trazabilidad.hashing import sha256_bytes, sha256_file

ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_known_vectors() -> None:
    assert sha256_bytes(b"abc") == ABC_SHA256
    assert sha256_bytes(b"") == EMPTY_SHA256


def test_file_hash_matches_known_vector(tmp_path: Path) -> None:
    path = tmp_path / "abc.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == ABC_SHA256


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    assert sha256_file(path) == EMPTY_SHA256


@pytest.mark.parametrize("chunk_size", [1, 3, 7, 4096])
def test_chunk_size_does_not_change_the_result(tmp_path: Path, chunk_size: int) -> None:
    data = bytes(range(256)) * 5
    path = tmp_path / "data.bin"
    path.write_bytes(data)
    assert sha256_file(path, chunk_size=chunk_size) == hashlib.sha256(data).hexdigest()


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sha256_file(tmp_path / "missing.bin")


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_non_positive_chunk_size_is_rejected(tmp_path: Path, chunk_size: int) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"x")
    with pytest.raises(ValueError, match="chunk_size"):
        sha256_file(path, chunk_size=chunk_size)
