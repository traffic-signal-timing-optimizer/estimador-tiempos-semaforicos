"""Utilidades compartidas por las pruebas de integración que ejecutan SUMO."""

import os
import shutil
from pathlib import Path

import pytest


def _find_sumo() -> Path | None:
    home = os.environ.get("SUMO_HOME")
    if home:
        for name in ("sumo.exe", "sumo"):
            candidate = Path(home) / "bin" / name
            if candidate.is_file():
                return candidate
    found = shutil.which("sumo")
    return Path(found) if found else None


@pytest.fixture
def sumo_binary() -> Path:
    """Ruta del ejecutable de SUMO; la prueba se salta si no está instalado (``SUMO_HOME``)."""
    binary = _find_sumo()
    if binary is None:
        pytest.skip("SUMO no está instalado (SUMO_HOME)")
    return binary
