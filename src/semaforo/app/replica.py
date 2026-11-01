"""Reporte de réplica publicado en el espacio de trabajo (DEV08 F3, decisión D10).

``replicate`` compara dos corridas de ``<workspace>/ejecuciones`` y publica el reporte en
``<workspace>/derivados/replicas/<fecha>_<huella>/`` (``replica.json`` y su ``manifiesto.json``),
sin sobrescribir nunca. ``read_replica`` lo vuelve a leer verificando sus huellas.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from semaforo.app.reception import RUNS
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.replica import ReplicaReport, Tolerance, compare_runs
from semaforo.trazabilidad.fs import publish_files
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import utc_now
from semaforo.trazabilidad.verify import read_verified

__all__ = ["REPLICAS", "REPORT_FILE", "ReplicaManifest", "read_replica", "replicate"]

REPLICAS = "derivados/replicas"
REPORT_FILE = "replica.json"
MANIFEST_FILE = "manifiesto.json"
SHORT_HASH = 8


class ReplicaManifest(FrozenModel):
    """Manifiesto de un reporte de réplica publicado."""

    schema_version: str = "1.0.0"
    run_a: str
    run_b: str
    verdict: str
    files: dict[str, str]


def replicate(
    workspace: Path,
    run_a: str,
    run_b: str,
    *,
    tolerance: Tolerance | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> tuple[ReplicaReport, Path]:
    """Compara ``run_a`` con ``run_b`` y publica el reporte. Devuelve el reporte y su carpeta.

    Raises:
        DomainError: lo que lanza ``compare_runs``; RUN_EXISTS si la carpeta del reporte ya existe.
    """
    created_at = clock()
    report = compare_runs(
        workspace / RUNS, run_a, run_b, created_at=created_at, tolerance=tolerance
    )
    data = (report.model_dump_json(indent=2) + "\n").encode("utf-8")
    digest = sha256_bytes(data)
    manifest = ReplicaManifest(
        run_a=run_a, run_b=run_b, verdict=report.verdict, files={REPORT_FILE: digest}
    )
    folder = (
        workspace / REPLICAS / f"{created_at.astimezone(UTC):%Y%m%dT%H%M%SZ}_{digest[:SHORT_HASH]}"
    )
    try:
        publish_files(
            folder,
            {
                REPORT_FILE: data,
                MANIFEST_FILE: (manifest.model_dump_json(indent=2) + "\n").encode(),
            },
        )
    except FileExistsError as error:
        raise DomainError(
            ErrorCode.RUN_EXISTS, "ya existe ese reporte de réplica", "run_b"
        ) from error
    return report, folder


def read_replica(folder: Path) -> ReplicaReport:
    """Reporte de réplica publicado, después de verificar la carpeta y su manifiesto.

    Raises:
        DomainError: PATH_NOT_ALLOWED, INPUT_SCHEMA o HASH_MISMATCH como ``read_verified``; también
            HASH_MISMATCH si el reporte no dice lo mismo que su manifiesto.
    """
    manifest = read_verified(folder, MANIFEST_FILE, ReplicaManifest, lambda m: m.files)
    try:
        report = ReplicaReport.model_validate_json((folder / REPORT_FILE).read_bytes())
    except ValidationError as error:
        raise DomainError(ErrorCode.INPUT_SCHEMA, "el reporte no es válido", REPORT_FILE) from error
    if (report.run_a, report.run_b, report.verdict) != (
        manifest.run_a,
        manifest.run_b,
        manifest.verdict,
    ):
        raise DomainError(
            ErrorCode.HASH_MISMATCH, "el reporte no coincide con su manifiesto", REPORT_FILE
        )
    return report
