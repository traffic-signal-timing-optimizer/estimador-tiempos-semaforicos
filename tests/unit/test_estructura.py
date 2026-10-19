"""Comprueba que el andamiaje del paquete coincide con la arquitectura de 01_Diseno_tecnico.md."""

import ast
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "semaforo"
PACKAGES = [
    "semaforo.app",
    "semaforo.cli",
    "semaforo.dominio",
    "semaforo.datos",
    "semaforo.caso",
    "semaforo.simulacion",
    "semaforo.referencias",
    "semaforo.aprendizaje",
    "semaforo.estimacion",
    "semaforo.evaluacion",
    "semaforo.trazabilidad",
]
# Regla inamovible: solo semaforo.simulacion accede a SUMO, TraCI y procesos hijos.
FORBIDDEN_MODULES = frozenset({"traci", "sumolib", "subprocess"})
DYNAMIC_IMPORTERS = frozenset({"import_module", "__import__"})


def _dynamic_import_target(call: ast.Call) -> str | None:
    """Devuelve el módulo literal de ``import_module("x")`` o ``__import__("x")``, si aplica."""
    func = call.func
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    else:
        return None
    if name not in DYNAMIC_IMPORTERS or not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def forbidden_imports(source: str) -> set[str]:
    """Módulos prohibidos que importa ``source``, incluidos los imports dinámicos literales.

    Analiza el árbol sintáctico, así que ignora docstrings, comentarios e imports relativos.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots = {node.module.split(".")[0]}
        elif isinstance(node, ast.Call) and (target := _dynamic_import_target(node)):
            roots = {target.split(".")[0]}
        else:
            continue
        found |= roots & FORBIDDEN_MODULES
    return found


@pytest.mark.parametrize("name", PACKAGES)
def test_package_exists_and_imports(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__doc__, f"{name} debe documentar su responsabilidad"


def test_test_and_adr_directories_exist() -> None:
    for folder in ["tests/unit", "tests/integration", "tests/e2e", "tests/security", "docs/adr"]:
        assert (ROOT / folder).is_dir(), f"falta {folder}"


NONE: set[str] = set()
DETECTOR_CASES: list[tuple[str, set[str]]] = [
    ("import subprocess", {"subprocess"}),
    ("import traci.constants as tc", {"traci"}),
    ("from sumolib import net", {"sumolib"}),
    ('import importlib\nimportlib.import_module("traci.constants")', {"traci"}),
    ('__import__("sumolib")', {"sumolib"}),
    ('"""import subprocess"""\nimport os.path', NONE),
    ("# import traci\nx = 1", NONE),
    ("from . import traci_utils", NONE),
    ("from .subprocess import run", NONE),
    ("import importlib\nimportlib.import_module(name)", NONE),
]


@pytest.mark.parametrize(("source", "expected"), DETECTOR_CASES)
def test_forbidden_imports_detector(source: str, expected: set[str]) -> None:
    assert forbidden_imports(source) == expected


def test_only_simulacion_touches_sumo_or_processes() -> None:
    offenders: list[str] = []
    for file in SOURCE.rglob("*.py"):
        if "simulacion" in file.relative_to(SOURCE).parts:
            continue
        found = forbidden_imports(file.read_text(encoding="utf-8"))
        offenders.extend(f"{file.relative_to(ROOT)}: {module}" for module in sorted(found))
    assert not offenders, "\n".join(offenders)
