"""Prueba de aceptación de ADR01 (monolito modular): reglas de dependencia entre módulos.

Dirección permitida: interfaz (cli) → servicios de aplicación (app) → reglas de dominio.
Ningún módulo de negocio importa la capa de interfaz ni de aplicación, y la consulta
(estimacion) no depende de simulación, búsqueda ni evaluación.
"""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "semaforo"
MODULES = {
    "app",
    "cli",
    "dominio",
    "datos",
    "caso",
    "simulacion",
    "referencias",
    "aprendizaje",
    "estimacion",
    "evaluacion",
    "trazabilidad",
}

# módulo de origen -> módulos que no puede importar
FORBIDDEN: dict[str, frozenset[str]] = {
    "dominio": frozenset(MODULES - {"dominio"}),
    "estimacion": frozenset({"simulacion", "referencias", "evaluacion", "app", "cli"}),
    "cli": frozenset(MODULES - {"cli", "app"}),
    "datos": frozenset({"app", "cli"}),
    "caso": frozenset({"app", "cli"}),
    "simulacion": frozenset({"app", "cli"}),
    "referencias": frozenset({"app", "cli"}),
    "aprendizaje": frozenset({"app", "cli"}),
    "evaluacion": frozenset({"app", "cli"}),
    "trazabilidad": frozenset({"app", "cli"}),
}


def _targets(node: ast.AST) -> set[str]:
    """Módulos semaforo.* que referencia un nodo de import."""
    found: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            parts = alias.name.split(".")
            if parts[0] == "semaforo" and len(parts) > 1:
                found.add(parts[1])
    elif isinstance(node, ast.ImportFrom):
        if node.level == 0 and node.module and node.module.split(".")[0] == "semaforo":
            parts = node.module.split(".")
            if len(parts) > 1:
                found.add(parts[1])
        elif node.level >= 2:
            # Desde semaforo.<paquete>.<archivo>, ".." apunta a semaforo.
            if node.module:
                found.add(node.module.split(".")[0])
            else:
                found.update(alias.name for alias in node.names)
    return found


def dependencies(path: Path, owner: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    targets: set[str] = set()
    for node in ast.walk(tree):
        targets |= _targets(node)
    targets.discard(owner)
    return targets & MODULES


def violations(source: Path) -> list[str]:
    result: list[str] = []
    for owner, forbidden in FORBIDDEN.items():
        package = source / owner
        if not package.is_dir():
            continue
        for file in sorted(package.rglob("*.py")):
            bad = dependencies(file, owner) & forbidden
            relative = file.relative_to(source).as_posix()
            result.extend(f"{relative} -> {mod}" for mod in sorted(bad))
    return result


def test_module_dependencies_follow_adr01() -> None:
    assert not violations(SOURCE), "\n".join(violations(SOURCE))


def test_detector_flags_forbidden_import(tmp_path: Path) -> None:
    (tmp_path / "estimacion").mkdir()
    (tmp_path / "estimacion" / "servicio.py").write_text(
        "from semaforo.simulacion import runner\n", encoding="utf-8"
    )
    assert violations(tmp_path) == ["estimacion/servicio.py -> simulacion"]


def test_detector_flags_relative_import_into_cli(tmp_path: Path) -> None:
    (tmp_path / "dominio").mkdir()
    (tmp_path / "dominio" / "reglas.py").write_text("from .. import cli\n", encoding="utf-8")
    assert violations(tmp_path) == ["dominio/reglas.py -> cli"]


def test_detector_allows_own_package_and_app_to_dominio(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "servicio.py").write_text(
        "from semaforo.dominio import reglas\nfrom semaforo.estimacion import servicio\n",
        encoding="utf-8",
    )
    assert violations(tmp_path) == []
