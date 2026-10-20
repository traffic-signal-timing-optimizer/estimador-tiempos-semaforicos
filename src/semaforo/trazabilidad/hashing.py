"""Hash SHA-256 de archivos y de bytes."""

import hashlib
from pathlib import Path

CHUNK_SIZE_BYTES = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    """SHA-256 hexadecimal, en minúsculas, de unos bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = CHUNK_SIZE_BYTES) -> str:
    """SHA-256 hexadecimal, en minúsculas, de un archivo.

    Lee por bloques de ``chunk_size`` bytes para no cargar archivos grandes en memoria.
    Propaga ``OSError`` si el archivo no existe o lo tiene bloqueado otro proceso: qué hacer con
    un archivo ilegible le corresponde a quien llama, no a esta función.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size debe ser un número positivo de bytes")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
