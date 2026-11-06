"""Utilidades compartidas por las pruebas de integración que ejecutan SUMO o usan PostgreSQL."""

import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from semaforo.bd.temporales import create_database, drop_database

if TYPE_CHECKING:
    from bd_tools import Loadable


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


@pytest.fixture(scope="session")
def sumo_session() -> Path:
    """Como ``sumo_binary``, para los preparativos que se hacen una vez por sesión."""
    binary = _find_sumo()
    if binary is None:
        pytest.skip("SUMO no está instalado (SUMO_HOME)")
    return binary


@pytest.fixture(scope="session")
def cargable(tmp_path_factory: pytest.TempPathFactory, sumo_session: Path) -> "Loadable":
    """Un ``datos/`` sintético completo y cargable, armado una vez (ver ``bd_tools``)."""
    from bd_tools import loadable_workspace  # noqa: PLC0415  (solo si alguna prueba lo usa)

    return loadable_workspace(tmp_path_factory.mktemp("cargable"), sumo_session)


@pytest.fixture(scope="session")
def bd_plantilla() -> Iterator[str]:
    """Base temporal con el esquema, que sirve de molde para las demás (DEV31 F3).

    Sin PostgreSQL preparado con «bd iniciar» la prueba **falla**, no se salta: la puerta de
    calidad necesita la base (acta de F0, despliegue).
    """
    name = create_database()
    yield name
    drop_database(name)


@pytest.fixture
def base(bd_plantilla: str) -> Iterator[str]:
    """Una base temporal nueva, con el esquema, que se borra al terminar la prueba."""
    name = create_database(template=bd_plantilla)
    yield name
    drop_database(name)
