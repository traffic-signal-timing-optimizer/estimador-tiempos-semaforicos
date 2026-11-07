"""Probar un respaldo: restaurarlo en una base temporal y recalcular su huella (C1.8, C3.5; B10).

``probar_respaldo`` verifica **un respaldo específico** con seis pasos, cada uno con su resultado
por separado (el del archivo, el de la restauración y el del contenido):

1. elegir el archivo (el que se indica);
2. comprobar el archivo: su SHA-256 contra su ``.sha256``. Si falta la referencia o difiere, **se
   detiene antes de restaurar**;
3. restaurarlo en una base temporal. Se borra solo la base temporal que se creó;
4. identificar el esquema (la versión instalada en la base restaurada) y **recalcular la huella
   leyendo sus tablas**. Un número guardado no prueba que las tablas restauradas sean las mismas;
5. comparar con la **referencia del respaldo**: la ficha que se generó al respaldar, o, en un
   respaldo antiguo, la huella que dejó la última carga en su propia base (``control.cargas``),
   solo si esa carga está completa, tiene huella y no hay cargas posteriores (D14). Sin una
   referencia válida el contenido queda *no comprobado*, aunque la restauración salga bien;
6. guardar la evidencia en un archivo junto al respaldo, sin reescribir la ficha.

La referencia de un respaldo antiguo es la de **su** base, no ``docs/bd/huellas.json``, que es de
la versión vigente.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from semaforo.bd.carga.insercion import Catalog
from semaforo.bd.conexion import ADMIN, BdError, Connection, connect
from semaforo.bd.esquema import installed_version
from semaforo.bd.respaldo import read_ficha, restore
from semaforo.bd.temporales import create_database, drop_database
from semaforo.bd.verificacion import HASH_ALGORITHM, content_hash
from semaforo.dominio.base_model import FrozenModel
from semaforo.simulacion.environment import capture_environment
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.store import utc_now

__all__ = ["BackupTest", "ContentResult", "StepResult", "backup_test_exit_code", "probar_respaldo"]

Outcome = Literal["coincide", "difiere", "no_comprobado", "exitosa", "fallida", "no_intentada"]
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StepResult(FrozenModel):
    """El resultado de un paso, con su motivo."""

    estado: Outcome
    detalle: str | None


class ContentResult(FrozenModel):
    """El resultado del contenido: lo recalculado, lo esperado y de dónde sale lo esperado."""

    estado: Literal["coincide", "difiere", "no_comprobado"]
    version_detectada: str | None
    version_esperada: str | None
    huella_calculada: str | None
    huella_esperada: str | None
    procedencia: str | None
    detalle: str | None


class BackupTest(FrozenModel):
    """La evidencia de la prueba de un respaldo (sin rutas de la máquina)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    archivo: str
    probado_en: datetime
    commit_verificador: str | None
    algoritmo_huella: str
    sha256: StepResult
    restauracion: StepResult
    contenido: ContentResult


def _unchecked(reason: str) -> ContentResult:
    return ContentResult(
        estado="no_comprobado",
        version_detectada=None,
        version_esperada=None,
        huella_calculada=None,
        huella_esperada=None,
        procedencia=None,
        detalle=reason,
    )


def _check_file(dump: Path) -> StepResult:
    recorded = dump.with_name(f"{dump.name}.sha256")
    try:
        expected = recorded.read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError):
        return StepResult(estado="no_comprobado", detalle="falta su archivo .sha256")
    if not SHA256.fullmatch(expected):
        return StepResult(estado="no_comprobado", detalle="su .sha256 no es una huella válida")
    if sha256_file(dump) != expected:
        return StepResult(estado="difiere", detalle="el archivo no coincide con su .sha256")
    return StepResult(estado="coincide", detalle=None)


def _historic_reference(connection: Connection) -> tuple[str, str, str] | str:
    """La huella y la versión que dejó la última carga de la base restaurada (D14).

    Devuelve ``(huella, versión, carga)`` o el motivo por el que no sirve como referencia.
    """
    running = connection.execute(
        "SELECT count(*) FROM control.cargas WHERE estado = 'running'"
    ).fetchone()
    if running is not None and int(running[0]):
        return "hay cargas «en curso» (running) en la base del respaldo"
    last = connection.execute(
        "SELECT carga_id, estado, huella_contenido, version_esquema FROM control.cargas "
        "ORDER BY inicio DESC, carga_id DESC LIMIT 1"
    ).fetchone()
    if last is None:
        return "la base del respaldo no tiene ninguna carga"
    load, state, digest, version = last
    if state != "completed" or digest is None:
        return f"la última carga ({load}) no está completa o no guardó su huella"
    return str(digest), str(version), str(load)


def _compare(connection: Connection, dump: Path) -> ContentResult:
    """Recalcula la huella desde las tablas restauradas y la compara con su referencia."""
    detected = installed_version(connection)
    ficha = read_ficha(dump)
    expected_version: str | None
    if (
        ficha is not None
        and ficha.huella_contenido.estado == "verificado"
        and isinstance(ficha.huella_contenido.valor, str)
    ):
        if ficha.algoritmo_huella != HASH_ALGORITHM:
            return _unchecked(
                f"algoritmo distinto: la ficha usa {ficha.algoritmo_huella}; ahora {HASH_ALGORITHM}"
            )
        expected = ficha.huella_contenido.valor
        expected_version = (
            ficha.version_esquema.valor if isinstance(ficha.version_esquema.valor, str) else None
        )
        origin = "ficha del respaldo (huella tomada de la misma instantánea que se exportó)"
    else:
        found = _historic_reference(connection)
        if isinstance(found, str):
            return _unchecked(f"sin referencia válida: {found}")
        expected, expected_version, load = found
        origin = f"carga {load} de la propia base del respaldo (control.cargas)"
    try:
        calculated, _ = content_hash(connection, Catalog.load(connection))
    except Exception as error:
        return _unchecked(
            f"no se pudo reproducir el cálculo para ese esquema: {type(error).__name__}"
        )
    changed: list[str] = []
    if expected_version is not None and detected != expected_version:
        changed.append("versión del esquema")
    if calculated != expected:
        changed.append("huella de contenido")
    return ContentResult(
        estado="difiere" if changed else "coincide",
        version_detectada=detected,
        version_esperada=expected_version,
        huella_calculada=calculated,
        huella_esperada=expected,
        procedencia=origin,
        detalle=f"difiere: {', '.join(changed)}" if changed else None,
    )


def probar_respaldo(dump: Path, *, write: bool = True) -> BackupTest:
    """Prueba el respaldo ``dump`` (ver el módulo) y devuelve su evidencia.

    Con ``write``, la guarda en ``<respaldo>.verificacion-<fecha>.json`` junto al respaldo.
    """
    file_step = (
        _check_file(dump)
        if dump.is_file()
        else StepResult(estado="no_comprobado", detalle="no existe el archivo")
    )
    skipped = StepResult(estado="no_intentada", detalle="se detuvo antes de restaurar")
    restoration, content = skipped, _unchecked("no se restauró el respaldo")
    if file_step.estado == "coincide":
        name = create_database(schema=False)
        try:
            try:
                restore(dump, name)
            except BdError as error:
                restoration = StepResult(estado="fallida", detalle=error.message)
            else:
                restoration = StepResult(estado="exitosa", detalle=None)
                with connect(ADMIN, database=name) as connection:
                    content = _compare(connection, dump)
        finally:
            drop_database(name)
    evidence = BackupTest(
        archivo=dump.name,
        probado_en=utc_now(),
        commit_verificador=capture_environment().get("commit"),
        algoritmo_huella=HASH_ALGORITHM,
        sha256=file_step,
        restauracion=restoration,
        contenido=content,
    )
    if write and dump.is_file():
        stamp = f"{evidence.probado_en:%Y%m%dT%H%M%SZ}"
        target = dump.with_name(f"{dump.name}.verificacion-{stamp}.json")
        target.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return evidence


def backup_test_exit_code(evidence: BackupTest) -> int:
    """0 si archivo, restauración y contenido coinciden; 5 si alguno difiere o falla; 6 si algo
    quedó sin comprobar."""
    results = (evidence.sha256.estado, evidence.restauracion.estado, evidence.contenido.estado)
    if "difiere" in results or "fallida" in results:
        return 5
    return 0 if results == ("coincide", "exitosa", "coincide") else 6
