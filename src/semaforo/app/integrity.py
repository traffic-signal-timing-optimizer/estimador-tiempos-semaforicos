"""Vínculos de una corrida y revisión de todo el espacio de trabajo (DEV08 F2, decisiones D6 y D7).

``trace_run`` sigue la cadena de una corrida hacia atrás y comprueba cada eslabón con las huellas
que quedaron registradas:

- la corrida (su carpeta frente a su manifiesto);
- su copia de las entradas y, si vino de una carpeta de entradas de DEV06, esa carpeta publicada,
  el programa derivado que usó y el caso;
- si vino de una recepción de DEV00, la copia de los originales;
- si es un reintento, la corrida anterior.

``verify_workspace`` recorre las familias de carpetas publicadas de ``datos/`` y dice de cada una
si está íntegra, alterada, incompleta, en curso o si no sigue un formato conocido. Solo lee: no
mueve ni corrige nada. Las rutas de los informes son relativas al espacio de trabajo.
"""

import re
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Literal

from semaforo.app.reception import RECEPTION_ID_PATTERN, RECEPTIONS, RUNS, SNAPSHOTS, read_reception
from semaforo.caso.case_validation import read_case
from semaforo.datos.quality_report import read_quality_report
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import canonical_sha256
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.compiler import read_program
from semaforo.simulacion.prepare import InputsManifest
from semaforo.simulacion.run_inputs import verify_inputs
from semaforo.trazabilidad.fs import INCOMPLETE_DIR, TEMP_PREFIX, is_plain_folder
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.ids import content_id
from semaforo.trazabilidad.interrupted import list_interrupted
from semaforo.trazabilidad.manifest import RunManifest
from semaforo.trazabilidad.store import INPUTS, MANIFEST, read_run, scan_files, utc_now

__all__ = [
    "CASES",
    "INPUT_FOLDERS",
    "PROGRAMS",
    "QUALITY",
    "Link",
    "RunTrace",
    "WorkspaceItem",
    "WorkspaceReport",
    "trace_run",
    "verify_workspace",
]

CASES = "casos"
PROGRAMS = "derivados/programas"
INPUT_FOLDERS = "derivados/entradas"
QUALITY = "derivados/calidad"
INPUTS_MANIFEST = "manifiesto.json"
CASE_FILE = "case.json"
_SNAPSHOT_ID = re.compile(r"[a-f0-9]{64}")

LinkKind = Literal["run", "inputs_copy", "inputs", "program", "case", "snapshot", "retry_of"]
LinkStatus = Literal["verified", "altered", "not_found", "incomplete", "changed"]


class Link(FrozenModel):
    """Un eslabón de la cadena de una corrida.

    ``changed`` solo se usa para el caso: es un archivo editable y su contenido ya no es el que
    usó la corrida. ``incomplete``: la corrida anterior de un reintento quedó interrumpida.
    """

    kind: LinkKind
    status: LinkStatus
    path: str | None
    detail: str | None


class RunTrace(FrozenModel):
    """La cadena de una corrida. ``complete`` si todos los eslabones están verificados."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str
    status: Literal["complete", "broken"]
    links: list[Link]


def _rel(workspace: Path, path: Path) -> str:
    return path.relative_to(workspace).as_posix()


def _problem(error: DomainError) -> str:
    return f"{error.code.value}: {error.message}"


# --- vínculos de una corrida ------------------------------------------------------------------


def _plain_children(folder: Path) -> Iterator[Path]:
    if not is_plain_folder(folder):
        return
    for child in sorted(folder.iterdir()):
        if is_plain_folder(child) and not child.name.startswith("."):
            yield child


def _find_by_manifest(parent: Path, digest: str) -> Path | None:
    """La carpeta de ``parent`` cuyo ``manifiesto.json`` tiene la huella ``digest``."""
    for folder in _plain_children(parent):
        manifest = folder / INPUTS_MANIFEST
        if manifest.is_file() and not manifest.is_symlink() and sha256_file(manifest) == digest:
            return folder
    return None


def _inputs_links(workspace: Path, run_folder: Path) -> list[Link]:
    """Copia de las entradas, carpeta de entradas publicada, programa y caso."""
    copy = run_folder / INPUTS
    try:
        manifest = verify_inputs(copy)
    except DomainError as error:
        return [
            Link(
                kind="inputs_copy",
                status="altered",
                path=_rel(workspace, copy),
                detail=_problem(error),
            )
        ]
    links = [Link(kind="inputs_copy", status="verified", path=_rel(workspace, copy), detail=None)]
    links.append(_published_inputs(workspace, manifest, sha256_file(copy / INPUTS_MANIFEST)))
    links.append(_program(workspace, manifest))
    links.append(_case(workspace, manifest))
    return links


def _published_inputs(workspace: Path, manifest: InputsManifest, digest: str) -> Link:
    folder = _find_by_manifest(workspace / INPUT_FOLDERS / manifest.scenario_id, digest)
    if folder is None:
        return Link(
            kind="inputs", status="not_found", path=None, detail="no está la carpeta de entradas"
        )
    try:
        verify_inputs(folder)
    except DomainError as error:
        return Link(
            kind="inputs", status="altered", path=_rel(workspace, folder), detail=_problem(error)
        )
    return Link(kind="inputs", status="verified", path=_rel(workspace, folder), detail=None)


def _program(workspace: Path, manifest: InputsManifest) -> Link:
    record = manifest.program
    folder = _find_by_manifest(
        workspace / PROGRAMS / manifest.case_id, record.source_manifest_sha256
    )
    if folder is None:
        return Link(
            kind="program", status="not_found", path=None, detail="no está el programa derivado"
        )
    try:
        program = read_program(folder)
    except DomainError as error:
        return Link(
            kind="program", status="altered", path=_rel(workspace, folder), detail=_problem(error)
        )
    if program.files.get(record.file) != record.sha256:
        return Link(
            kind="program",
            status="altered",
            path=_rel(workspace, folder),
            detail="el programa no es el que copiaron las entradas",
        )
    return Link(kind="program", status="verified", path=_rel(workspace, folder), detail=None)


def _case(workspace: Path, manifest: InputsManifest) -> Link:
    path = workspace / CASES / manifest.case_id / CASE_FILE
    if not path.is_file():
        return Link(
            kind="case", status="not_found", path=None, detail="no está el archivo del caso"
        )
    try:
        case = read_case(path)
    except DomainError as error:
        return Link(
            kind="case", status="changed", path=_rel(workspace, path), detail=_problem(error)
        )
    if canonical_sha256(case) != manifest.case_sha256:
        return Link(
            kind="case",
            status="changed",
            path=_rel(workspace, path),
            detail="el caso cambió después de preparar las entradas",
        )
    return Link(kind="case", status="verified", path=_rel(workspace, path), detail=None)


def _snapshot(workspace: Path, run: RunManifest) -> Link:
    """Copia de los originales con el mismo contenido que las entradas de la corrida (DEV00)."""
    entries = [(a.path.removeprefix(f"{INPUTS}/"), a.sha256) for a in run.inputs]
    if not entries:
        return Link(
            kind="snapshot", status="not_found", path=None, detail="la corrida no tiene entradas"
        )
    snapshot_id = content_id(entries)
    folder = workspace / SNAPSHOTS / snapshot_id
    if not is_plain_folder(folder):
        return Link(
            kind="snapshot",
            status="not_found",
            path=None,
            detail="no está la copia de los originales",
        )
    status = _snapshot_status(folder)
    return Link(
        kind="snapshot",
        status="verified" if status is None else "altered",
        path=_rel(workspace, folder),
        detail=status,
    )


def _snapshot_status(folder: Path) -> str | None:
    """``None`` si la copia tiene la huella de su nombre; si no, el motivo."""
    try:
        files = scan_files(folder)
        if not files:
            return "la copia está vacía"
        if content_id((name, sha256_file(folder / name)) for name in files) != folder.name:
            return "el contenido no corresponde a su identificador"
    except DomainError as error:
        return _problem(error)
    except OSError as error:
        return f"no se puede leer ({type(error).__name__})"
    return None


def _retry(workspace: Path, run: RunManifest) -> Link | None:
    if run.retry_of is None:
        return None
    runs_root = workspace / RUNS
    previous = runs_root / run.retry_of
    if (previous / MANIFEST).is_file():
        try:
            read_run(runs_root, run.retry_of)
        except DomainError as error:
            return Link(
                kind="retry_of",
                status="altered",
                path=_rel(workspace, previous),
                detail=_problem(error),
            )
        return Link(kind="retry_of", status="verified", path=_rel(workspace, previous), detail=None)
    for item in list_interrupted(runs_root):
        if item.run_id == run.retry_of:
            return Link(
                kind="retry_of", status="incomplete", path=f"{RUNS}/{item.folder}", detail=None
            )
    return Link(
        kind="retry_of", status="not_found", path=None, detail="no está la corrida anterior"
    )


def trace_run(workspace: Path, run_id: str) -> RunTrace:
    """La cadena de la corrida ``run_id`` de ``workspace/ejecuciones``, eslabón por eslabón.

    Raises:
        DomainError: PATH_NOT_ALLOWED si ``run_id`` no es un nombre seguro; INPUT_SCHEMA si la
            corrida no existe. Una corrida alterada no es una excepción: su eslabón queda
            ``altered`` y la cadena ``broken``.
    """
    runs_root = workspace / RUNS
    folder = runs_root / run_id
    try:
        run = read_run(runs_root, run_id)
    except DomainError as error:
        if error.code in (ErrorCode.PATH_NOT_ALLOWED, ErrorCode.INPUT_SCHEMA):
            raise
        link = Link(
            kind="run", status="altered", path=_rel(workspace, folder), detail=_problem(error)
        )
        return RunTrace(run_id=run_id, status="broken", links=[link])
    links = [Link(kind="run", status="verified", path=_rel(workspace, folder), detail=None)]
    if (folder / INPUTS / INPUTS_MANIFEST).is_file():
        links.extend(_inputs_links(workspace, folder))
    else:
        links.append(_snapshot(workspace, run))
    retry = _retry(workspace, run)
    if retry is not None:
        links.append(retry)
    complete = all(link.status == "verified" for link in links)
    return RunTrace(run_id=run_id, status="complete" if complete else "broken", links=links)


# --- revisión del espacio de trabajo ----------------------------------------------------------

Family = Literal["runs", "receptions", "snapshots", "programs", "inputs", "quality"]
ItemStatus = Literal["intact", "altered", "incomplete", "temporary", "unknown"]


class WorkspaceItem(FrozenModel):
    """Una carpeta revisada. ``detail`` explica una alterada o una desconocida."""

    family: Family
    path: str
    status: ItemStatus
    detail: str | None


class WorkspaceReport(FrozenModel):
    """Resultado de revisar el espacio de trabajo. ``altered`` si alguna carpeta está alterada."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    checked_at: datetime
    status: Literal["intact", "altered"]
    counts: dict[str, int]
    items: list[WorkspaceItem]


def _check(check: Callable[[Path], object], folder: Path) -> tuple[ItemStatus, str | None]:
    try:
        check(folder)
    except DomainError as error:
        return "altered", _problem(error)
    except OSError as error:
        return "altered", f"no se puede leer ({type(error).__name__})"
    return "intact", None


def _special(family: Family, workspace: Path, entry: Path) -> list[WorkspaceItem] | None:
    """Carpetas temporales e incompletas de una familia; ``None`` si ``entry`` es una normal."""
    if entry.name.startswith(TEMP_PREFIX):
        return [
            WorkspaceItem(
                family=family, path=_rel(workspace, entry), status="temporary", detail=None
            )
        ]
    if entry.name == INCOMPLETE_DIR:
        return [
            WorkspaceItem(
                family=family, path=_rel(workspace, child), status="incomplete", detail=None
            )
            for child in sorted(entry.iterdir())
            if is_plain_folder(child)
        ]
    if entry.name.startswith("."):
        return []  # candados y otros archivos de control
    return None


def _walk(
    workspace: Path,
    family: Family,
    root: Path,
    check: Callable[[Path], tuple[ItemStatus, str | None]],
    *,
    grouped: bool,
) -> Iterator[WorkspaceItem]:
    """Revisa ``root`` (con un nivel de agrupación si ``grouped``: caso o escenario)."""
    if not is_plain_folder(root):
        return
    for entry in sorted(root.iterdir()):
        special = _special(family, workspace, entry)
        if special is not None:
            yield from special
            continue
        if not is_plain_folder(entry):
            yield WorkspaceItem(
                family=family,
                path=_rel(workspace, entry),
                status="unknown",
                detail="no es una carpeta",
            )
            continue
        if grouped:
            yield from _walk(workspace, family, entry, check, grouped=False)
            continue
        status, detail = check(entry)
        yield WorkspaceItem(
            family=family, path=_rel(workspace, entry), status=status, detail=detail
        )


def verify_workspace(
    workspace: Path, *, clock: Callable[[], datetime] = utc_now
) -> WorkspaceReport:
    """Revisa todas las carpetas publicadas de ``workspace``. Solo lee.

    Familias: corridas (``ejecuciones``), recepciones, copias de originales, programas derivados,
    carpetas de entradas y reportes de calidad (``derivados/calidad``). Los casos, escenarios y
    demás archivos editables no son carpetas publicadas y no se revisan aquí.
    """
    runs_root = workspace / RUNS

    def run(folder: Path) -> tuple[ItemStatus, str | None]:
        return _check(lambda f: read_run(runs_root, f.name), folder)

    def reception(folder: Path) -> tuple[ItemStatus, str | None]:
        if not RECEPTION_ID_PATTERN.fullmatch(folder.name):
            return "unknown", "el nombre no es un identificador de recepción"
        return _check(lambda f: read_reception(workspace, f.name), folder)

    def snapshot(folder: Path) -> tuple[ItemStatus, str | None]:
        if not _SNAPSHOT_ID.fullmatch(folder.name):
            return "unknown", "el nombre no es la huella de una copia"
        problem = _snapshot_status(folder)
        return ("intact", None) if problem is None else ("altered", problem)

    families: list[tuple[Family, Path, Callable[[Path], tuple[ItemStatus, str | None]], bool]] = [
        ("runs", runs_root, run, False),
        ("receptions", workspace / RECEPTIONS, reception, False),
        ("snapshots", workspace / SNAPSHOTS, snapshot, False),
        ("programs", workspace / PROGRAMS, lambda f: _check(read_program, f), True),
        ("inputs", workspace / INPUT_FOLDERS, lambda f: _check(verify_inputs, f), True),
        ("quality", workspace / QUALITY, lambda f: _check(read_quality_report, f), True),
    ]
    items = [
        item
        for family, root, check, grouped in families
        for item in _walk(workspace, family, root, check, grouped=grouped)
    ]
    counts = {
        status: sum(1 for item in items if item.status == status)
        for status in ("intact", "altered", "incomplete", "temporary", "unknown")
    }
    return WorkspaceReport(
        checked_at=clock(),
        status="altered" if counts["altered"] else "intact",
        counts=counts,
        items=items,
    )
