"""Etiqueta de una búsqueda, publicada y verificable (DEV14 F3, HU08; contrato label v1.0).

``publish_label`` escribe de una vez, sin sobrescribir, la carpeta
``<datos>/derivados/referencias/<caso>/<AAAAMMDDTHHMMSSZ>_<huella8>/`` con:

- ``label.json``: la etiqueta con el contrato ``label`` v1.0;
- ``traza.json``: la búsqueda completa (candidatos, semillas, puntuaciones y la regla de selección);
- ``cobertura.json``: cuántos candidatos y corridas se usaron y por qué no contaron los demás;
- ``manifiesto.json``: identidad de la etiqueta, huellas de los tres archivos y la red usada.

``read_label`` vuelve a leerla comprobando que la carpeta tiene exactamente esos archivos, que cada
uno conserva su huella y que la etiqueta coincide con su manifiesto.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from semaforo.datos.scenario_set import SAFE_FOLDER
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.timing import reconstruct
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.evaluation import SearchOutcome, SearchSetup, search_identity
from semaforo.referencias.selection import CandidateScore, Selection
from semaforo.trazabilidad.fs import publish_files, read_at_most
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import TrazabilidadError, utc_now
from semaforo.trazabilidad.verify import read_verified

__all__ = [
    "LABELS",
    "Label",
    "LabelManifest",
    "Plan",
    "StoredLabel",
    "publish_label",
    "read_label",
]

LABELS = "derivados/referencias"
LABEL_FILE = "label.json"
TRACE_FILE = "traza.json"
COVERAGE_FILE = "cobertura.json"
MANIFEST_FILE = "manifiesto.json"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SHORT_HASH_CHARS = 8
IDENTITY_CHARS = 16
MAX_LABEL_BYTES = 1024 * 1024
_CONFIG = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class Plan(BaseModel):
    """Plan de la etiqueta: la duración de cada slot, el ciclo y el verde de cada grupo."""

    model_config = _CONFIG

    slot_durations_s: dict[str, float]
    cycle_s: float = Field(gt=0)
    greens_s: dict[str, float]


class Label(BaseModel):
    """Contrato ``label`` v1.0 (``schemas/label.schema.json``).

    Los campos del contrato están fijos; lo que no cabe aquí (la traza y la cobertura) va en los
    archivos hermanos de la carpeta. Un ``reference`` lleva plan; un ``no_reference`` no lleva plan
    y sí su motivo.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        title="Contrato label v1.0",
        json_schema_extra={"$schema": SCHEMA_DIALECT},
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    label_id: str
    scenario_id: str
    case_version: str
    status: Literal["reference", "no_reference"]
    plan: Plan | None
    search_run_id: str
    protocol_id: str
    candidate_count: int = Field(ge=0)
    simulation_count: int = Field(ge=0)
    evidence_status: Literal["fixture_only", "evaluated"]
    reason: str | None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.status == "reference" and self.plan is None:
            raise ValueError("una etiqueta con referencia necesita su plan")
        if self.status == "no_reference" and (self.plan is not None or self.reason is None):
            raise ValueError("una etiqueta sin referencia no lleva plan y sí su motivo")
        return self


class LabelManifest(FrozenModel):
    """Manifiesto de una etiqueta publicada."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    created_at: datetime
    case_id: str
    case_version: str
    scenario_id: str
    label_id: str
    search_run_id: str
    protocol_id: str
    status: Literal["reference", "no_reference"]
    evidence_status: Literal["fixture_only", "evaluated"]
    network_sha256: str | None
    files: dict[str, str]


@dataclass(frozen=True)
class StoredLabel:
    """Una etiqueta leída y verificada."""

    manifest: LabelManifest
    label: Label


def _json_bytes(data: object) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _search_digest(identity: Mapping[str, object]) -> str:
    text = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:IDENTITY_CHARS]


def _finished(setup: SearchSetup, outcome: SearchOutcome) -> Selection:
    if outcome.interrupted or outcome.selection is None:
        raise ReferenciasError(
            ErrorCode.INPUT_SCHEMA, "la búsqueda no terminó: no hay etiqueta que publicar", "search"
        )
    if dict(outcome.identity) != search_identity(setup, outcome.candidates):
        raise ReferenciasError(
            ErrorCode.INPUT_SCHEMA,
            "la búsqueda no es la de este escenario y protocolo",
            "identity",
        )
    return outcome.selection


def _winner_durations(outcome: SearchOutcome, winner: CandidateScore) -> dict[str, float]:
    for candidate in outcome.candidates.candidates:
        if candidate.candidate_id == winner.candidate_id:
            return dict(candidate.durations_s)
    raise ReferenciasError(
        ErrorCode.OUTPUT_INVALID, "el ganador no está entre los candidatos", "winner"
    )


def _evidence(purpose: str) -> Literal["fixture_only", "evaluated"]:
    return "evaluated" if purpose == "main_experiment" else "fixture_only"


def _label(setup: SearchSetup, outcome: SearchOutcome, selection: Selection, digest: str) -> Label:
    plan = None
    if selection.winner is not None:
        durations = _winner_durations(outcome, selection.winner)
        timing = reconstruct(setup.case, durations)
        plan = Plan(slot_durations_s=durations, cycle_s=timing.cycle_s, greens_s=timing.greens_s)
    return Label(
        label_id=f"label-{digest}",
        scenario_id=setup.scenario.scenario_id,
        case_version=setup.case.case_version,
        status=selection.status,
        plan=plan,
        search_run_id=f"search-{digest}",
        protocol_id=setup.protocol.protocol_id,
        candidate_count=len(outcome.candidates.candidates),
        simulation_count=outcome.simulation_count,
        evidence_status=_evidence(setup.protocol.purpose),
        reason=selection.reason,
    )


def _stage_coverage(
    scores: Sequence[CandidateScore], ineligible: Mapping[str, int]
) -> dict[str, object]:
    return {
        "evaluated": len(scores),
        "eligible": sum(1 for score in scores if score.eligible),
        "ineligible": dict(ineligible),
    }


def _coverage(outcome: SearchOutcome, selection: Selection) -> dict[str, object]:
    candidates = outcome.candidates
    return {
        "method": candidates.method,
        "space_size": candidates.space_size,
        "grid_feasible": candidates.grid_feasible,
        "budget": candidates.budget,
        "budget_used": candidates.budget_used,
        "attempt_limit": candidates.attempt_limit,
        "attempts": candidates.attempts,
        "duplicates": candidates.duplicates,
        "infeasible": candidates.infeasible,
        "infeasible_by_rule": dict(candidates.infeasible_by_rule),
        "exhausted": candidates.exhausted,
        "current_plan": candidates.current_plan,
        "webster": candidates.webster,
        "search": _stage_coverage(outcome.search_scores, selection.ineligible_search),
        "finalists": _stage_coverage(outcome.finalist_scores, selection.ineligible_finalists),
        "simulations": outcome.simulation_count,
    }


def publish_label(
    workspace: Path,
    setup: SearchSetup,
    outcome: SearchOutcome,
    now: datetime | None = None,
) -> Path:
    """Publica la etiqueta de ``outcome`` en ``workspace/derivados/referencias/<caso>/``.

    Raises:
        ReferenciasError: INPUT_SCHEMA si la búsqueda no terminó o no es la de este escenario y
            protocolo; OUTPUT_INVALID si el ganador no está entre los candidatos; RUN_EXISTS si ya
            hay una etiqueta idéntica publicada en el mismo instante; PATH_NOT_ALLOWED si el
            identificador del caso no sirve como nombre de carpeta.
    """
    selection = _finished(setup, outcome)
    case_id = setup.case.case_id
    if SAFE_FOLDER.fullmatch(case_id) is None:
        raise ReferenciasError(
            ErrorCode.PATH_NOT_ALLOWED,
            "el identificador del caso solo puede tener letras, números, punto, guion bajo y "
            "guion para usarse como nombre de carpeta",
            "case_id",
        )
    digest = _search_digest(outcome.identity)
    label = _label(setup, outcome, selection, digest)
    label_bytes = (label.model_dump_json(indent=2) + "\n").encode("utf-8")
    trace_bytes = _json_bytes(outcome.to_json())
    coverage_bytes = _json_bytes(_coverage(outcome, selection))
    moment = (utc_now() if now is None else now).astimezone(UTC)
    manifest = LabelManifest(
        created_at=moment,
        case_id=case_id,
        case_version=setup.case.case_version,
        scenario_id=label.scenario_id,
        label_id=label.label_id,
        search_run_id=label.search_run_id,
        protocol_id=label.protocol_id,
        status=label.status,
        evidence_status=label.evidence_status,
        network_sha256=None if setup.case.network is None else setup.case.network.sha256,
        files={
            LABEL_FILE: sha256_bytes(label_bytes),
            TRACE_FILE: sha256_bytes(trace_bytes),
            COVERAGE_FILE: sha256_bytes(coverage_bytes),
        },
    )
    final = (
        workspace
        / LABELS
        / case_id
        / f"{moment:%Y%m%dT%H%M%SZ}_{sha256_bytes(label_bytes)[:SHORT_HASH_CHARS]}"
    )
    try:
        publish_files(
            final,
            {
                LABEL_FILE: label_bytes,
                TRACE_FILE: trace_bytes,
                COVERAGE_FILE: coverage_bytes,
                MANIFEST_FILE: (manifest.model_dump_json(indent=2) + "\n").encode("utf-8"),
            },
        )
    except FileExistsError as error:
        raise ReferenciasError(
            ErrorCode.RUN_EXISTS, "ya existe una etiqueta publicada con estos datos", "label"
        ) from error
    return final


def _bad(message: str, field: str | None = None) -> TrazabilidadError:
    return TrazabilidadError(ErrorCode.INPUT_SCHEMA, message, field)


def _label_bytes(folder: Path) -> bytes:
    try:
        with (folder / LABEL_FILE).open("rb") as stream:
            data = read_at_most(stream, MAX_LABEL_BYTES + 1)
    except OSError as error:
        raise _bad(f"no se puede leer ({type(error).__name__})", LABEL_FILE) from error
    if len(data) > MAX_LABEL_BYTES:
        raise _bad("el archivo es demasiado grande", LABEL_FILE)
    return data


def read_label(folder: Path) -> StoredLabel:
    """La etiqueta de ``folder``, después de verificar la carpeta, las huellas y el manifiesto.

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si hay enlaces; INPUT_SCHEMA si la carpeta, el
            manifiesto o la etiqueta no existen o no son válidos, o no coinciden entre sí;
            HASH_MISMATCH si un archivo sobra, falta o cambió.
    """
    manifest = read_verified(folder, MANIFEST_FILE, LabelManifest, lambda m: m.files)
    if set(manifest.files) != {LABEL_FILE, TRACE_FILE, COVERAGE_FILE}:
        raise _bad("el manifiesto no lista los archivos de una etiqueta", MANIFEST_FILE)
    try:
        label = Label.model_validate_json(_label_bytes(folder))
    except ValidationError as error:
        raise _bad(
            f"la etiqueta no es válida ({error.error_count()} problemas)", LABEL_FILE
        ) from error
    same = (
        label.label_id == manifest.label_id
        and label.scenario_id == manifest.scenario_id
        and label.case_version == manifest.case_version
        and label.status == manifest.status
        and label.search_run_id == manifest.search_run_id
        and label.protocol_id == manifest.protocol_id
        and label.evidence_status == manifest.evidence_status
    )
    if not same:
        raise _bad("la etiqueta no coincide con su manifiesto", LABEL_FILE)
    return StoredLabel(manifest, label)
