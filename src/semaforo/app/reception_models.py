"""Modelos del registro de una recepción (``reception.json``) y de la comparación entre dos."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from semaforo.caso.base_model import FrozenModel
from semaforo.simulacion.summary import SimulationSummary
from semaforo.trazabilidad.manifest import Artifact

SHA256_PATTERN = r"^[a-f0-9]{64}$"
ProposedStatus = Literal["acceptable", "with_findings", "failed"]
ChangeArea = Literal["snapshot", "inventory", "audit", "run"]


class BaseRunRecord(FrozenModel):
    """La corrida base de la recepción, enlazada por la huella de su manifiesto."""

    run_id: str
    path: str
    status: str
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    exit_code: int | None
    error_code: str | None
    summary: SimulationSummary | None


class IncompleteRun(FrozenModel):
    """Una ejecución que quedó sin publicar (carpeta ``.tmp-``), por ejemplo tras una caída."""

    folder: str
    run_id: str | None
    created_at: datetime | None


class ReceptionRecord(FrozenModel):
    """Registro de una recepción: qué se recibió, qué se produjo y en qué estado quedó.

    Las rutas son relativas al espacio de trabajo. ``proposed_status`` es una propuesta: la valida
    el Product Owner (QA23 y QA24). ``exit_code`` es el código de salida de la CLI.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    reception_id: str
    created_at: datetime
    source_name: str
    entry_config: str
    case_id: str
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    snapshot_path: str
    snapshot_reused: bool
    sumo_version: str | None
    artifacts: list[Artifact]
    base_run: BaseRunRecord
    finding_counts: dict[str, int]
    proposed_status: ProposedStatus
    exit_code: int
    incomplete_runs: list[IncompleteRun]


class Change(FrozenModel):
    """Una diferencia entre dos recepciones. ``before`` o ``after`` es None si el elemento falta."""

    area: ChangeArea
    item: str
    before: str | None
    after: str | None


class ReceptionComparison(FrozenModel):
    """Qué cambió entre la recepción ``before`` y la ``after``."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    before: str
    after: str
    same_snapshot: bool
    changes: list[Change]
