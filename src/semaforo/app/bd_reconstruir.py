"""``bd reconstruir``: reconstruir la base de forma segura (DEV31 F4c, C1.11; hallazgo N4).

Reemplaza el guion temporal con que se reconstruyó la base en DEV31 F4. Tiene dos fases, y la base
vigente **no se toca hasta la segunda**.

**Preparar.** Crea una base *candidata* con nombre temporal (``semaforo_candidata_…``) y la valida
paso a paso. Cada paso tiene una puerta: si falla, se detiene, se borra la candidata y la vigente
queda como estaba.

- **P0** la base vigente coincide con su referencia de git;
- **P1** se crea la candidata con el esquema del código, los mismos permisos y las mismas reglas;
- **P2** se carga lo publicado en ``datos/`` (con las mismas autorizaciones que la vigente);
- **P3** la conciliación da *coincide*: cobertura completa, conteos y demora recalculada;
- **P4** una regeneración desde cero da la misma huella (QA36);
- **P5** su respaldo, con la huella registrada **antes** de exportarlo, se restaura en otra base
  temporal y la huella recalculada coincide;
- **P7** se calculan la versión, la huella de contenido y la huella de reglas de la candidata, para
  que el PO apruebe la huella nueva (D11).

Las pruebas de cegado y de seguridad (**P6**) corren en una base desechable con el mismo esquema:
no pueden correr aquí, porque insertan datos de prueba y la base es de solo agregar. Quien ejecuta
las declara aprobadas al pasar a la segunda fase.

**Cambiar.** Solo con la huella aprobada y las pruebas de seguridad declaradas:

- **P8** la vigente pasa a ``semaforo_anterior_<fecha>`` y la candidata ocupa su lugar. Si el
  segundo cambio de nombre falla, se **revierte** el primero y la vigente queda como estaba. La
  anterior **no se borra** nunca aquí;
- **P9** se verifica la base nueva contra la huella aprobada y, si se pide, se escribe el archivo
  de huellas. Si no coincide, también se revierte.

Nunca toca bases que no sean del proyecto: los nombres tienen que ser ``semaforo`` o empezar con
``semaforo_candidata_``, ``semaforo_anterior_`` o ``semaforo_pruebas_``.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from psycopg import sql

from semaforo.app.bd_commands import load_options_of, regenerate, verify
from semaforo.bd.carga.motor import LoadOptions, load_workspace
from semaforo.bd.conciliacion import reconcile
from semaforo.bd.conexion import ADMIN, DATABASE, BdError, Connection, connect
from semaforo.bd.esquema import installed_version, schema_version
from semaforo.bd.prueba_respaldo import probar_respaldo
from semaforo.bd.respaldo import backup
from semaforo.bd.temporales import CANDIDATE_PREFIX, create_database, drop_database
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.trazabilidad.store import utc_now

__all__ = ["Preparation", "Rename", "Step", "SwitchReport", "prepare_rebuild", "switch_database"]

NAME = re.compile(r"^semaforo(_(candidata|anterior|pruebas)_[a-z0-9_]+)?$")
PREVIOUS_PREFIX = "semaforo_anterior_"

Rename = Callable[[Connection, str, str], None]


class Step(FrozenModel):
    """Un paso del proceso, con su resultado."""

    paso: str
    nombre: str
    resultado: Literal["ok", "falla"]
    detalle: str | None


class Preparation(FrozenModel):
    """Resultado de ``bd reconstruir preparar``."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["lista", "detenida"]
    current: str
    candidate: str | None
    stopped_at: str | None
    reason: str | None
    steps: list[Step]
    version_esquema: str | None
    content_sha256: str | None
    rules_sha256: str | None
    backup: str | None


class SwitchReport(FrozenModel):
    """Resultado de ``bd reconstruir cambiar``."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["cambiada", "detenida"]
    current: str
    candidate: str
    previous: str | None
    reason: str | None
    steps: list[Step]
    content_sha256: str | None
    fingerprints_file: str | None


def _checked(name: str) -> str:
    if NAME.fullmatch(name) is None:
        raise BdError(
            ErrorCode.PATH_NOT_ALLOWED, "solo se tocan bases del proyecto (semaforo…)", name
        )
    return name


def _rename(admin: Connection, old: str, new: str) -> None:
    admin.execute(
        sql.SQL("ALTER DATABASE {} RENAME TO {}").format(sql.Identifier(old), sql.Identifier(new))
    )


def _connections(admin: Connection, names: list[str]) -> int:
    row = admin.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = ANY(%s) AND pid <> pg_backend_pid()",
        (names,),
    ).fetchone()
    return 0 if row is None else int(row[0])


class _Process:
    """Los pasos ya hechos."""

    def __init__(self) -> None:
        self.steps: list[Step] = []

    def ok(self, code: str, name: str, detail: str | None = None) -> None:
        self.steps.append(Step(paso=code, nombre=name, resultado="ok", detalle=detail))

    def fail(self, code: str, name: str, reason: str) -> None:
        self.steps.append(Step(paso=code, nombre=name, resultado="falla", detalle=reason))


def _stopped(
    process: _Process, current: str, candidate: str | None, code: str, reason: str
) -> Preparation:
    """Cierra la fase de preparar con una falla: borra la candidata y deja la vigente igual."""
    if candidate is not None:
        drop_database(candidate)
    return Preparation(
        status="detenida",
        current=current,
        candidate=None,
        stopped_at=code,
        reason=reason,
        steps=process.steps,
        version_esquema=None,
        content_sha256=None,
        rules_sha256=None,
        backup=None,
    )


def prepare_rebuild(  # noqa: PLR0911, PLR0913  (un paso por puerta; opciones por nombre)
    workspace: Path,
    repository: Path,
    *,
    backups: Path,
    database: str = DATABASE,
    candidate: str | None = None,
    reference: Path | None = None,
    compare: bool = True,
) -> Preparation:
    """Prepara y valida la base candidata (pasos P0 a P5 y P7; ver el módulo).

    Si algún paso falla, la candidata se borra y la base vigente no cambia.
    """
    current = _checked(database)
    name = _checked(candidate or f"{CANDIDATE_PREFIX}{utc_now():%Y%m%d%H%M%S}")
    process = _Process()

    verified = verify(workspace, repository, reference=reference, compare=compare, database=current)
    if verified.status != "intact":
        process.fail("P0", "la base vigente coincide con su referencia", verified.reason or "no")
        return _stopped(process, current, None, "P0", verified.reason or verified.status)
    process.ok("P0", "la base vigente coincide con su referencia")

    options = load_options_of(current)
    create_database(schema=True, name=name)
    process.ok("P1", "candidata creada", name)

    report = load_workspace(
        workspace,
        LoadOptions(
            preliminary=options.preliminary,
            loose_runs=options.loose_runs,
            without_metrics=options.without_metrics,
            repository=repository,
        ),
        database=name,
    )
    open_items = {key: report.counts.get(key, 0) for key in ("rejected", "pending", "not_loadable")}
    if any(open_items.values()):
        reason = ", ".join(f"{count} {key}" for key, count in open_items.items() if count)
        process.fail("P2", "carga de lo publicado", reason)
        return _stopped(process, current, name, "P2", reason)
    process.ok("P2", "carga de lo publicado", f"{report.counts.get('loaded', 0)} unidades cargadas")

    reconciled = reconcile(workspace, database=name, repository=repository)
    if reconciled.status != "equal":
        reason = reconciled.reason or f"conciliación: {reconciled.status}"
        process.fail("P3", "conciliación con los archivos", reason)
        return _stopped(process, current, name, "P3", reason)
    process.ok("P3", "conciliación con los archivos")

    regenerated = regenerate(workspace, repository, database=name)
    if regenerated.status != "same":
        reason = regenerated.reason or f"regeneración: {regenerated.status}"
        process.fail("P4", "regeneración desde cero", reason)
        return _stopped(process, current, name, "P4", reason)
    process.ok("P4", "regeneración desde cero", "misma huella")

    saved = backup(backups, database=name)
    tested = probar_respaldo(backups / saved.file)
    if (tested.sha256.estado, tested.restauracion.estado, tested.contenido.estado) != (
        "coincide",
        "exitosa",
        "coincide",
    ):
        reason = tested.contenido.detalle or tested.restauracion.detalle or "no coincide"
        process.fail("P5", "respaldo restaurado con la misma huella", reason)
        return _stopped(process, current, name, "P5", reason)
    process.ok("P5", "respaldo restaurado con la misma huella", saved.file)

    final = verify(workspace, repository, compare=False, database=name)
    process.ok("P7", "huella de la candidata para aprobar", final.content_sha256)
    with connect(ADMIN, database=name) as connection:
        version = installed_version(connection)
    if version != schema_version():
        process.fail("P7", "versión del esquema", f"{version} no es {schema_version()}")
        return _stopped(process, current, name, "P7", "la candidata no tiene el esquema del código")
    return Preparation(
        status="lista",
        current=current,
        candidate=name,
        stopped_at=None,
        reason=None,
        steps=process.steps,
        version_esquema=version,
        content_sha256=final.content_sha256,
        rules_sha256=final.rules_sha256,
        backup=saved.file,
    )


def _swap(admin: Connection, current: str, candidate: str, previous: str, rename: Rename) -> None:
    """Pasa la vigente a ``previous`` y la candidata a ``current``; si falla, revierte."""
    rename(admin, current, previous)
    try:
        rename(admin, candidate, current)
    except BaseException:
        rename(admin, previous, current)
        raise


def _switch_stopped(  # noqa: PLR0913, PLR0917  (describe la falla de un paso)
    process: _Process, current: str, candidate: str, code: str, name: str, reason: str
) -> SwitchReport:
    process.fail(code, name, reason)
    return SwitchReport(
        status="detenida",
        current=current,
        candidate=candidate,
        previous=None,
        reason=reason,
        steps=process.steps,
        content_sha256=None,
        fingerprints_file=None,
    )


def switch_database(  # noqa: PLR0913  (opciones de solo palabra clave)
    workspace: Path,
    repository: Path,
    *,
    candidate: str,
    approved_sha256: str,
    tests_approved: bool,
    database: str = DATABASE,
    previous: str | None = None,
    fingerprints: Path | None = None,
    rename: Rename = _rename,
) -> SwitchReport:
    """Cambia la candidata por la vigente (pasos P6 a P9; ver el módulo).

    La vigente conserva su contenido con el nombre ``previous`` y no se borra.
    """
    current, name = _checked(database), _checked(candidate)
    old = _checked(previous or f"{PREVIOUS_PREFIX}{utc_now():%Y%m%d%H%M%S}")
    process = _Process()
    if not tests_approved:
        return _switch_stopped(
            process,
            current,
            name,
            "P6",
            "pruebas de cegado y seguridad",
            "las pruebas de seguridad no están declaradas como aprobadas",
        )
    process.ok("P6", "pruebas de cegado y seguridad declaradas aprobadas por quien ejecuta")
    measured = verify(workspace, repository, compare=False, database=name)
    if measured.status != "intact" or measured.content_sha256 != approved_sha256:
        return _switch_stopped(
            process,
            current,
            name,
            "P7",
            "huella aprobada",
            "la huella de la candidata no es la aprobada",
        )
    process.ok("P7", "huella aprobada", approved_sha256)
    with connect(ADMIN, database="postgres", autocommit=True) as admin:
        if _connections(admin, [current, name]):
            return _switch_stopped(
                process, current, name, "P8", "cambio de nombre", "hay conexiones abiertas"
            )
        _swap(admin, current, name, old, rename)
        process.ok("P8", "cambio de nombre", f"la vigente quedó como {old}")
        after = verify(workspace, repository, compare=False, database=current)
        if after.content_sha256 != approved_sha256 or after.status != "intact":
            _swap(admin, current, old, name, rename)  # la vigente vuelve a su lugar
            return _switch_stopped(
                process,
                current,
                name,
                "P9",
                "verificación de la base nueva",
                "la base nueva no da la huella aprobada: se revirtió el cambio",
            )
    process.ok("P9", "verificación de la base nueva", "misma huella")
    written: str | None = None
    if fingerprints is not None:
        written = verify(
            workspace, repository, compare=False, fingerprints=fingerprints, database=current
        ).fingerprints_file
    return SwitchReport(
        status="cambiada",
        current=current,
        candidate=name,
        previous=old,
        reason=None,
        steps=process.steps,
        content_sha256=after.content_sha256,
        fingerprints_file=written,
    )
