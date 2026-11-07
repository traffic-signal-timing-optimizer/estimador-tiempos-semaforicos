"""Catálogo de lo publicado en ``datos/``: la única forma de recorrerlo (DEV31 F4c, C1.1).

El cargador, la publicación de métricas y la conciliación recorren ``datos/`` con este módulo, así
que ven las mismas cosas. Una familia nueva de archivos (por ejemplo, los escenarios generados) se
agrega **aquí**, en un solo lugar, y las tres herramientas la ven a la vez.

Una *fuente* es una unidad publicada: su clase, su nombre en los informes, su archivo principal
(el manifiesto que la identifica) y todos los archivos principales que la hacen íntegra. El catálogo
solo mira nombres de carpetas y archivos: no lee ni valida su contenido, salvo para distinguir un
escenario escrito a mano de las rutas y tipos de vehículo que comparten su carpeta.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from semaforo.aprendizaje.split_store import SPLITS
from semaforo.bd.carga.caso import CASES, PROTOCOLS, SCENARIOS
from semaforo.bd.carga.decisiones import DECISIONS
from semaforo.bd.carga.hitos import MILESTONES
from semaforo.datos.scenario_set import SCENARIO_SETS
from semaforo.evaluacion.published_metrics import MANIFEST_FILE as METRICS_MANIFEST
from semaforo.evaluacion.published_metrics import METRICS, RUNS
from semaforo.referencias.comparators import COMPARATORS
from semaforo.referencias.label import LABELS
from semaforo.trazabilidad.fs import INCOMPLETE_DIR, TEMP_PREFIX, is_plain_folder
from semaforo.trazabilidad.store import MANIFEST

__all__ = [
    "KINDS",
    "Source",
    "Sources",
    "children",
    "discover",
    "grouped",
    "metrics_manifest",
    "relative",
]

MANIFEST_NAME = "manifiesto.json"
MAX_SCENARIO_BYTES = 1024 * 1024
# Clases de fuente, en el orden en que se cargan.
KINDS = (
    "case",
    "protocol",
    "split",
    "scenario_set",
    "scenario",
    "search",
    "run",
    "comparators",
    "milestone",
    "decision",
)


@dataclass(frozen=True)
class Source:
    """Una unidad publicada de ``datos/``.

    ``key`` es el nombre que lleva en los informes; ``main`` es la ruta (relativa a ``datos/``)
    de su archivo principal; ``mains`` son todos los archivos principales que la hacen íntegra
    (una corrida con métricas publicadas tiene dos: su manifiesto y el de sus métricas);
    ``name`` es el nombre de su carpeta o archivo; ``folder`` es su carpeta, si tiene.
    """

    kind: str
    key: str
    main: str
    mains: tuple[str, ...]
    name: str
    folder: str


@dataclass(frozen=True)
class Sources:
    """Todo lo publicado en ``datos/``, por clase."""

    items: tuple[Source, ...] = field(default_factory=tuple[Source, ...])

    def of(self, kind: str) -> list[Source]:
        """Las fuentes de una clase, en orden."""
        return [item for item in self.items if item.kind == kind]

    def keys(self, kind: str) -> set[str]:
        """Los nombres de las fuentes de una clase."""
        return {item.key for item in self.of(kind)}


def children(folder: Path) -> list[Path]:
    """Subcarpetas publicadas de ``folder`` (sin temporales, incompletas ni ocultas)."""
    if not is_plain_folder(folder):
        return []
    return [
        child
        for child in sorted(folder.iterdir())
        if is_plain_folder(child)
        and not child.name.startswith((".", TEMP_PREFIX))
        and child.name != INCOMPLETE_DIR
    ]


def relative(workspace: Path, path: Path) -> str:
    """La ruta de ``path`` relativa a ``datos/``, con barras normales."""
    return path.relative_to(workspace).as_posix()


def grouped(workspace: Path, family: str) -> list[str]:
    """``datos/<family>/<caso>/<carpeta>``, en orden, como rutas relativas."""
    return [
        relative(workspace, folder)
        for group in children(workspace / family)
        for folder in children(group)
    ]


def metrics_manifest(workspace: Path, run_id: str) -> str | None:
    """El manifiesto de las métricas publicadas de la corrida, si las tiene."""
    for group in children(workspace / METRICS):
        path = group / run_id / METRICS_MANIFEST
        if path.is_file():
            return relative(workspace, path)
    return None


def _is_scenario_file(path: Path) -> bool:
    """Si el JSON es un escenario (y no las rutas o los tipos de vehículo de la misma carpeta)."""
    try:
        if path.is_symlink() or path.stat().st_size > MAX_SCENARIO_BYTES:
            return False
        raw = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return False
    return isinstance(raw, dict) and "scenario_id" in raw


def _single(kind: str, key: str, main: str, name: str, folder: str = "") -> Source:
    return Source(kind, key, main, (main,), name, folder)


def _cases(workspace: Path) -> Iterable[Source]:
    for folder in children(workspace / CASES):
        main = f"{CASES}/{folder.name}/case.json"
        if (folder / "case.json").is_file():
            yield _single(
                "case", f"caso:{folder.name}", main, folder.name, f"{CASES}/{folder.name}"
            )


def _json_files(workspace: Path, family: str) -> Iterable[Path]:
    for group in children(workspace / family):
        yield from sorted(group.glob("*.json"))


def _folders(workspace: Path, kind: str, family: str, label: str) -> Iterable[Source]:
    for folder in grouped(workspace, family):
        name = folder.rsplit("/", 1)[-1]
        yield _single(kind, f"{label}:{folder}", f"{folder}/{MANIFEST_NAME}", name, folder)


def discover(workspace: Path) -> Sources:
    """Todo lo publicado en ``workspace`` (la carpeta ``datos/``), por clase y en orden."""
    items: list[Source] = []
    items += _cases(workspace)
    for path in _json_files(workspace, PROTOCOLS):
        rel = relative(workspace, path)
        items.append(_single("protocol", f"protocolo:{rel}", rel, path.name))
    items += _folders(workspace, "split", SPLITS, "particion")
    items += _folders(workspace, "scenario_set", SCENARIO_SETS, "conjunto")
    for path in _json_files(workspace, SCENARIOS):
        if _is_scenario_file(path):
            rel = relative(workspace, path)
            items.append(_single("scenario", f"escenario:{rel}", rel, path.name))
    items += _folders(workspace, "search", LABELS, "busqueda")
    for folder in children(workspace / RUNS):
        main = f"{RUNS}/{folder.name}/{MANIFEST}"
        metrics = metrics_manifest(workspace, folder.name)
        mains = (main,) if metrics is None else (main, metrics)
        items.append(
            Source(
                "run", f"corrida:{folder.name}", main, mains, folder.name, f"{RUNS}/{folder.name}"
            )
        )
    items += _folders(workspace, "comparators", COMPARATORS, "comparadores")
    for kind, family, label in (
        ("milestone", MILESTONES, "hito"),
        ("decision", DECISIONS, "decision"),
    ):
        for folder in children(workspace / family):
            rel = relative(workspace, folder)
            items.append(
                _single(kind, f"{label}:{folder.name}", f"{rel}/{MANIFEST_NAME}", folder.name, rel)
            )
    return Sources(tuple(items))
