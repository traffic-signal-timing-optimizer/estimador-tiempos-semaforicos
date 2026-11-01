"""Corridas interrumpidas: se detectan, se apartan sin borrar y nunca se publican (DEV07 F3, D8).

Una corrida en curso vive en ``<ejecuciones>/.tmp-<8 caracteres>`` con el bloqueo
``.lock-<run_id>`` tomado (``RunLock``). Si el proceso muere —apagón, cierre a la fuerza, error— el
sistema suelta el bloqueo y la carpeta queda. ``recover_interrupted`` la reconoce porque el bloqueo
se puede tomar, escribe ``INCOMPLETA.json`` y la mueve a ``<ejecuciones>/.incompletas/<run_id>/``.

- No se borra nada: lo escrito hasta la caída queda como evidencia.
- No se publica nunca como corrida: ``read_run`` de ese ``run_id`` no la encuentra, así que jamás
  aparece como ``succeeded``. El contrato ``run_manifest`` no cambia.
- Una corrida viva (bloqueo tomado por otro proceso) no se toca.
"""

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from semaforo.dominio.base_model import FrozenModel
from semaforo.trazabilidad.fs import (
    INCOMPLETE_DIR,
    INCOMPLETE_MARK,
    free_name,
    is_plain_folder,
    read_at_most,
)
from semaforo.trazabilidad.lock import RunLock
from semaforo.trazabilidad.manifest import RunManifest
from semaforo.trazabilidad.store import (
    LOCK_PREFIX,
    MANIFEST,
    MAX_MANIFEST_BYTES,
    TEMP_PREFIX,
    utc_now,
)

__all__ = [
    "INCOMPLETE_DIR",
    "INCOMPLETE_MARK",
    "InterruptedRun",
    "list_interrupted",
    "recover_interrupted",
]

CAUSE = "el proceso que ejecutaba la corrida terminó sin publicarla"
# Una carpeta sin manifiesto legible puede estar naciendo; antes de este tiempo no se toca.
FRESH_S = 60.0


class InterruptedRun(FrozenModel):
    """Una corrida que quedó a medias. Lo que no se sabe (manifiesto ilegible) queda en ``None``."""

    run_id: str | None
    folder: str
    source_folder: str | None
    created_at: datetime | None
    detected_at: datetime | None
    provisional_status: str | None
    case_id: str | None
    case_version: str | None
    scenario_id: str | None
    cause: str


def _read_provisional(folder: Path) -> RunManifest | None:
    try:
        with (folder / MANIFEST).open("rb") as stream:
            data = read_at_most(stream, MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            return None
        return RunManifest.model_validate_json(data)
    except (OSError, ValidationError):
        return None


def _age_s(folder: Path) -> float:
    """Segundos desde el último cambio de la carpeta o de su manifiesto."""
    newest = 0.0
    for path in (folder, folder / MANIFEST):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return time.time() - newest


def _move(root: Path, folder: Path, run_id: str | None, now: datetime) -> InterruptedRun:
    """Escribe la marca y mueve la carpeta a ``.incompletas``. Se llama con el bloqueo tomado."""
    provisional = _read_provisional(folder)
    destination_root = root / INCOMPLETE_DIR
    destination_root.mkdir(exist_ok=True)
    name = free_name(destination_root, run_id or folder.name.removeprefix(TEMP_PREFIX))
    record = InterruptedRun(
        run_id=run_id,
        folder=f"{INCOMPLETE_DIR}/{name}",
        source_folder=folder.name,
        created_at=None if provisional is None else provisional.created_at,
        detected_at=now,
        provisional_status=None if provisional is None else provisional.status,
        case_id=None if provisional is None else provisional.case_id,
        case_version=None if provisional is None else provisional.case_version,
        scenario_id=None if provisional is None else provisional.scenario_id,
        cause=CAUSE,
    )
    (folder / INCOMPLETE_MARK).write_text(record.model_dump_json(indent=2), encoding="utf-8")
    folder.replace(destination_root / name)
    return record


def recover_interrupted(
    root: Path, *, clock: Callable[[], datetime] = utc_now
) -> list[InterruptedRun]:
    """Aparta las corridas caídas de ``root`` y devuelve las que apartó, en orden.

    Una carpeta que no se pudo mover (otro programa la tiene abierta, por ejemplo un SUMO que
    quedó vivo) se deja donde está y se vuelve a intentar la próxima vez. Si ``root`` no existe,
    no se crea nada.
    """
    if not is_plain_folder(root):
        return []
    now = clock()
    moved: list[InterruptedRun] = []
    for folder in sorted(root.iterdir()):
        if not (folder.name.startswith(TEMP_PREFIX) and is_plain_folder(folder)):
            continue
        provisional = _read_provisional(folder)
        if provisional is None:
            if _age_s(folder) < FRESH_S:
                continue  # puede estar naciendo: su manifiesto todavía no es legible
            moved_one = _recover_one(root, folder, None, now)
        else:
            lock = RunLock.acquire(root / f"{LOCK_PREFIX}{provisional.run_id}")
            if lock is None:
                continue  # sigue viva
            with lock:
                moved_one = _recover_one(root, folder, provisional.run_id, now)
        if moved_one is not None:
            moved.append(moved_one)
    return moved


def _recover_one(
    root: Path, folder: Path, run_id: str | None, now: datetime
) -> InterruptedRun | None:
    try:
        return _move(root, folder, run_id, now)
    except OSError:
        return None


def list_interrupted(root: Path) -> list[InterruptedRun]:
    """Corridas apartadas en ``root/.incompletas``, por nombre. Una marca mala no lanza error."""
    parent = root / INCOMPLETE_DIR
    if not is_plain_folder(parent):
        return []
    found: list[InterruptedRun] = []
    for folder in sorted(parent.iterdir()):
        if not is_plain_folder(folder):
            continue
        relative = f"{INCOMPLETE_DIR}/{folder.name}"
        found.append(_read_mark(folder, relative))
    return found


def _read_mark(folder: Path, relative: str) -> InterruptedRun:
    try:
        with (folder / INCOMPLETE_MARK).open("rb") as stream:
            data = read_at_most(stream, MAX_MANIFEST_BYTES + 1)
        if len(data) <= MAX_MANIFEST_BYTES:
            mark = InterruptedRun.model_validate_json(data)
            return mark.model_copy(update={"folder": relative})
    except (OSError, ValidationError):
        pass
    return InterruptedRun(
        run_id=None,
        folder=relative,
        source_folder=None,
        created_at=None,
        detected_at=None,
        provisional_status=None,
        case_id=None,
        case_version=None,
        scenario_id=None,
        cause=CAUSE,
    )
