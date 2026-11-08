"""Métricas de una corrida, publicadas una sola vez (DEV31 F2; decisión B10 de F0).

``publish_run_metrics`` escribe de una vez, sin sobrescribir, la carpeta
``<datos>/derivados/metricas/<caso>/<run_id>/`` con:

- ``metricas.json``: las métricas que calcula ``evaluate_run`` (demora de la cohorte, cola,
  detenciones, avisos), incluida la cola paso a paso;
- ``manifiesto.json``: quién es (caso, escenario, protocolo, corrida), la huella del manifiesto de
  la corrida de la que salen, el código y el equipo que las calcularon y la huella de
  ``metricas.json``.

Así hay una sola definición de cada métrica en todo el proyecto: la base de datos y el panel las
copian de aquí, no las vuelven a calcular. ``read_run_metrics`` las vuelve a leer comprobando que
la carpeta tiene exactamente esos archivos y que ninguno cambió.

``metricas.json`` es JSON con una línea por vehículo y una línea por serie: legible y sin ocupar
más de lo necesario (una corrida real tiene unos 1 800 vehículos y más de 7 000 pasos de cola).
"""

import json
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import ValidationError, model_validator

from semaforo.datos.scenario_set import SAFE_FOLDER
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.protocol import parse_protocol
from semaforo.evaluacion.errors import EvaluacionError
from semaforo.evaluacion.run_metrics import RunMetrics
from semaforo.simulacion.environment import capture_environment
from semaforo.trazabilidad.fs import publish_files, read_at_most
from semaforo.trazabilidad.hashing import sha256_bytes, sha256_file
from semaforo.trazabilidad.store import MANIFEST, TrazabilidadError, utc_now
from semaforo.trazabilidad.verify import read_verified

__all__ = [
    "MANIFEST_FILE",
    "METRICS",
    "METRICS_FILE",
    "RUNS",
    "MetricsManifest",
    "StoredMetrics",
    "metrics_bytes",
    "protocol_fingerprint",
    "publish_run_metrics",
    "read_run_metrics",
]

METRICS = "derivados/metricas"
RUNS = "ejecuciones"
METRICS_FILE = "metricas.json"
MANIFEST_FILE = "manifiesto.json"
MAX_METRICS_BYTES = 256 * 1024 * 1024
INDENT = "  "
SHA256_HEX_LENGTH = 64


class MetricsManifest(FrozenModel):
    """Manifiesto de las métricas publicadas de una corrida."""

    schema_version: Literal["1.0.0", "1.1.0"] = "1.1.0"
    created_at: datetime
    case_id: str
    case_version: str
    scenario_id: str
    protocol_id: str
    protocol_sha256: str | None = None
    run_id: str
    metrics_schema_version: str
    run_manifest_sha256: str
    environment: dict[str, str]
    files: dict[str, str]

    @model_validator(mode="after")
    def protocol_fingerprint_matches_version(self) -> "MetricsManifest":
        digest = self.protocol_sha256
        if self.schema_version == "1.1.0" and (
            digest is None
            or len(digest) != SHA256_HEX_LENGTH
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("el manifiesto 1.1.0 exige la huella SHA-256 del protocolo")
        if self.schema_version == "1.0.0" and digest is not None:
            raise ValueError("el manifiesto 1.0.0 no registra la huella del protocolo")
        return self


@dataclass(frozen=True)
class StoredMetrics:
    """Métricas leídas y verificadas."""

    manifest: MetricsManifest
    metrics: RunMetrics


def _render(value: object, depth: int) -> str:
    """JSON legible: los diccionarios con una clave por línea; una lista de números, de textos o
    de otros valores simples, en una sola línea; una lista de objetos, con un objeto por línea."""
    pad = INDENT * depth
    if isinstance(value, dict):
        items = cast("dict[str, object]", value)
        if not items:
            return "{}"
        lines = [
            f"{pad}{INDENT}{json.dumps(key, ensure_ascii=False)}: {_render(item, depth + 1)}"
            for key, item in items.items()
        ]
        return "{\n" + ",\n".join(lines) + f"\n{pad}}}"
    if isinstance(value, list):
        elements = cast("list[object]", value)
        if not any(isinstance(item, dict | list) for item in elements):
            return json.dumps(elements, ensure_ascii=False)
        lines = [
            f"{pad}{INDENT}{json.dumps(item, ensure_ascii=False, separators=(',', ':'))}"
            for item in elements
        ]
        return "[\n" + ",\n".join(lines) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False)


def metrics_bytes(metrics: RunMetrics) -> bytes:
    """El contenido de ``metricas.json``: siempre los mismos bytes para las mismas métricas."""
    return (_render(metrics.model_dump(mode="json"), 0) + "\n").encode("utf-8")


def _environment() -> dict[str, str]:
    return {"python": platform.python_version(), **capture_environment()}


def protocol_fingerprint(workspace: Path, protocol_id: str) -> str:
    """Huella del único protocolo publicado con esta identidad, sin seguir enlaces externos."""
    matches: list[Path] = []
    for path in (workspace / "derivados" / "protocolos").rglob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            raw = json.loads(path.read_bytes())
        except (OSError, ValueError):
            continue
        if (
            isinstance(raw, dict)
            and cast("dict[str, object]", raw).get("protocol_id") == protocol_id
        ):
            matches.append(path)
    if len(matches) != 1:
        raise EvaluacionError(
            ErrorCode.INPUT_SCHEMA,
            "se exige un único archivo publicado para el protocolo de las métricas",
            "protocol_id",
        )
    try:
        parse_protocol(json.loads(matches[0].read_bytes()))
    except (DomainError, OSError, ValueError) as error:
        raise EvaluacionError(
            ErrorCode.INPUT_SCHEMA, "el protocolo no es válido", "protocol_id"
        ) from error
    return sha256_file(matches[0])


def publish_run_metrics(
    workspace: Path,
    metrics: RunMetrics,
    *,
    now: datetime | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Publica las métricas de la corrida ``metrics.run_id`` de ``workspace/ejecuciones``.

    Args:
        workspace: la carpeta de datos (``datos/``).
        metrics: lo que devolvió ``evaluate_run`` para esa corrida.
        now: la fecha del manifiesto; por defecto, ahora.
        environment: código y equipo que las calcularon; por defecto, los de este proceso.

    Raises:
        EvaluacionError: PATH_NOT_ALLOWED si el caso o la corrida no sirven como nombre de
            carpeta; INPUT_SCHEMA si la corrida no está publicada en ``workspace``; RUN_EXISTS si
            sus métricas ya están publicadas (no se sobrescriben); OUTPUT_INVALID si
            ``metricas.json`` supera el tope.
    """
    for field, name in (("case_id", metrics.case_id), ("run_id", metrics.run_id)):
        if SAFE_FOLDER.fullmatch(name) is None:
            raise EvaluacionError(
                ErrorCode.PATH_NOT_ALLOWED,
                "el nombre solo puede tener letras, números, punto, guion bajo y guion para "
                "usarse como nombre de carpeta",
                field,
            )
    run_manifest = workspace / RUNS / metrics.run_id / MANIFEST
    if not run_manifest.is_file() or run_manifest.is_symlink():
        raise EvaluacionError(
            ErrorCode.INPUT_SCHEMA, "la corrida no está publicada en esta carpeta", "run_id"
        )
    data = metrics_bytes(metrics)
    if len(data) > MAX_METRICS_BYTES:
        raise EvaluacionError(
            ErrorCode.OUTPUT_INVALID, "las métricas son demasiado grandes", METRICS_FILE
        )
    manifest = MetricsManifest(
        created_at=(utc_now() if now is None else now).astimezone(UTC),
        case_id=metrics.case_id,
        case_version=metrics.case_version,
        scenario_id=metrics.scenario_id,
        protocol_id=metrics.protocol_id,
        protocol_sha256=protocol_fingerprint(workspace, metrics.protocol_id),
        run_id=metrics.run_id,
        metrics_schema_version=metrics.schema_version,
        run_manifest_sha256=sha256_file(run_manifest),
        environment=dict(_environment() if environment is None else environment),
        files={METRICS_FILE: sha256_bytes(data)},
    )
    final = workspace / METRICS / metrics.case_id / metrics.run_id
    try:
        publish_files(
            final,
            {
                METRICS_FILE: data,
                MANIFEST_FILE: (manifest.model_dump_json(indent=2) + "\n").encode("utf-8"),
            },
        )
    except FileExistsError as error:
        raise EvaluacionError(
            ErrorCode.RUN_EXISTS, "las métricas de esta corrida ya están publicadas", "run_id"
        ) from error
    return final


def _bad(message: str, field: str | None = None) -> TrazabilidadError:
    return TrazabilidadError(ErrorCode.INPUT_SCHEMA, message, field)


def read_run_metrics(folder: Path) -> StoredMetrics:
    """Las métricas de ``folder``, después de verificar la carpeta, las huellas y el manifiesto.

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si hay enlaces; INPUT_SCHEMA si la carpeta, el
            manifiesto o las métricas no existen o no son válidos, o no coinciden entre sí;
            HASH_MISMATCH si un archivo sobra, falta o cambió.
    """
    manifest = read_verified(folder, MANIFEST_FILE, MetricsManifest, lambda m: m.files)
    if set(manifest.files) != {METRICS_FILE}:
        raise _bad("el manifiesto no lista el archivo de las métricas", MANIFEST_FILE)
    try:
        with (folder / METRICS_FILE).open("rb") as stream:
            data = read_at_most(stream, MAX_METRICS_BYTES + 1)
    except OSError as error:
        raise _bad(f"no se puede leer ({type(error).__name__})", METRICS_FILE) from error
    if len(data) > MAX_METRICS_BYTES:
        raise _bad("el archivo es demasiado grande", METRICS_FILE)
    try:
        metrics = RunMetrics.model_validate_json(data)
    except ValidationError as error:
        raise _bad(
            f"las métricas no son válidas ({error.error_count()} problemas)", METRICS_FILE
        ) from error
    same = (
        metrics.run_id == manifest.run_id == folder.name
        and metrics.case_id == manifest.case_id == folder.parent.name
        and metrics.case_version == manifest.case_version
        and metrics.scenario_id == manifest.scenario_id
        and metrics.protocol_id == manifest.protocol_id
        and metrics.schema_version == manifest.metrics_schema_version
    )
    if not same:
        raise _bad("las métricas no coinciden con su manifiesto", METRICS_FILE)
    return StoredMetrics(manifest=manifest, metrics=metrics)
