"""Métricas de una corrida publicada (DEV19 F4; decisiones D5, D15 y D18 de F0).

``evaluate_run`` es el núcleo que usarán la búsqueda (DEV14, para puntuar candidatos) y la
comparación (DEV20). Para una corrida ``succeeded`` hecha con una carpeta de entradas de DEV06:

1. Concilia la cohorte con la corrida (``reconcile_run``): comprueba que la corrida terminó bien,
   que no fue alterada y que se hizo con esas mismas entradas.
2. Comprueba que el caso y el escenario son los de las entradas (por su huella) y que el protocolo
   pide una población y una censura que se saben medir.
3. Calcula la demora de la cohorte con su censura (F2) y, si la corrida tiene la FCD de la zona
   (ADR11), la cola y las detenciones (F3). Una corrida sin FCD (carpeta 1.0.0) no tiene cola ni
   detenciones: se dice por qué; no se inventan.

Copia también los avisos de la corrida (teletransportes, choques, avisos de SUMO): un atasco que
SUMO resuelve teletransportando vehículos esconde demora, y quien use las métricas debe verlo.

No escribe nada: devuelve un modelo con unidades y denominadores. Publicarlo como ``metricas.json``
de la corrida es de ``published_metrics`` (DEV31 F2); compararlo con otra corrida, de DEV20. La FCD
puede estar comprimida (``fcd.xml.gz``, corridas de DEV31 F2 en adelante) o no (las anteriores).
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import ValidationError, model_validator

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case, canonical_sha256
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.protocol import Protocol
from semaforo.dominio.scenario import Scenario, evidence_origin
from semaforo.dominio.timing import shown
from semaforo.evaluacion.cohort import CohortDelay, cohort_delay, require_supported
from semaforo.evaluacion.errors import EvaluacionError
from semaforo.evaluacion.metrics import MAX_FCD_BYTES, ZoneMetrics, zone_metrics
from semaforo.simulacion.prepare import canonical_json_sha256
from semaforo.simulacion.reconcile import MAX_TRIPINFO_BYTES, reconcile_run
from semaforo.simulacion.run_inputs import verify_inputs
from semaforo.simulacion.runner import FCD, SUMMARY, TRIPINFO, fcd_file
from semaforo.simulacion.summary import SimulationFinding, SimulationSummary
from semaforo.simulacion.tripinfo import read_trips

__all__ = ["DELAY_DEFINITION", "RunMetrics", "evaluate_run"]

MAX_SUMMARY_BYTES = 1024 * 1024
DELAY_DEFINITION = (
    "demora por vehículo = timeLoss + departDelay de SUMO (s); media = suma / N solicitados solo "
    "si la cohorte terminó; si no, cota inferior con lo acumulado"
)


class RunMetrics(FrozenModel):
    """Métricas de una corrida, con unidades y denominadores (DEV19).

    ``zone`` es None si la corrida no tiene la FCD de la zona; ``zone_unavailable`` dice por qué.
    Tres campos dicen de dónde sale lo medido (auditoría A03): ``case_origin`` es el del caso (la
    red y sus reglas), ``demand_origin`` el de la demanda del escenario y ``evidence_origin`` el que
    debe mostrar cualquier tabla: ``field`` solo si ambos lo son. Un caso real con demanda supuesta
    es ``synthetic``: una cifra sintética nunca se presenta como de campo.
    ``simulation_findings``, ``teleports_total`` y ``collisions`` vienen del resumen de la corrida:
    con teletransportes, la demora de esos vehículos está subestimada.
    """

    schema_version: Literal["2.1.0"] = "2.1.0"
    run_id: str
    case_id: str
    case_version: str
    case_origin: Literal["synthetic", "field"]
    demand_origin: Literal["synthetic", "field"]
    evidence_origin: Literal["synthetic", "field"]
    scenario_id: str
    sumo_seed: int
    protocol_id: str
    protocol_status: Literal["draft", "frozen"]
    delay_definition: str
    cohort: CohortDelay
    zone: ZoneMetrics | None
    zone_unavailable: str | None
    teleports_total: int
    collisions: int
    simulation_findings: list[SimulationFinding]

    @model_validator(mode="after")
    def _origins_agree(self) -> Self:
        if self.evidence_origin != evidence_origin(self.case_origin, self.demand_origin):
            raise ValueError(
                "el origen de la evidencia no sale del origen del caso y de la demanda"
            )
        return self


def _zone_lanes_recorded(protocol: Protocol, edges: list[str]) -> None:
    """Los carriles de la zona del protocolo son de calles que la corrida registró en su FCD."""
    missing = [lane for lane in protocol.zone_lane_ids if lane.rsplit("_", 1)[0] not in edges]
    if missing:
        raise EvaluacionError(
            ErrorCode.INPUT_SCHEMA,
            f"{len(missing)} carriles de la zona del protocolo no están en la FCD de la corrida "
            f"(el primero: {shown(missing[0])!r})",
            "zone_lane_ids",
        )


def _run_summary(outputs: Path) -> SimulationSummary:
    """Resumen de la corrida (``outputs/summary.json``), ya verificado por su huella."""
    path = outputs / SUMMARY
    try:
        if path.stat().st_size > MAX_SUMMARY_BYTES:
            raise EvaluacionError(
                ErrorCode.OUTPUT_INVALID, "el resumen es demasiado grande", SUMMARY
            )
        return SimulationSummary.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise EvaluacionError(
            ErrorCode.OUTPUT_INVALID,
            f"el resumen de la corrida no se puede leer ({type(error).__name__})",
            SUMMARY,
        ) from error


def evaluate_run(  # noqa: PLR0913  (el escenario es de solo palabra clave)
    inputs_dir: Path,
    runs_root: Path,
    run_id: str,
    case: Case,
    protocol: Protocol,
    *,
    scenario: Scenario,
) -> RunMetrics:
    """Métricas de la corrida ``run_id`` de ``runs_root``, hecha con la carpeta ``inputs_dir``.

    Raises:
        DomainError: lo que lanzan ``verify_inputs`` y ``reconcile_run`` (corrida inexistente,
            alterada, no exitosa o de otras entradas); HASH_MISMATCH si el caso o el escenario
            no son los de las entradas; INPUT_SCHEMA si el protocolo pide algo que no se sabe medir
            o una zona que la corrida no registró; OUTPUT_INVALID si las salidas no son coherentes.
    """
    manifest = verify_inputs(inputs_dir)
    if canonical_sha256(case) != manifest.case_sha256:
        raise EvaluacionError(
            ErrorCode.HASH_MISMATCH, "el caso no es el de las entradas de la corrida", "case"
        )
    if canonical_json_sha256(scenario.model_dump(mode="json")) != manifest.scenario_sha256:
        raise EvaluacionError(
            ErrorCode.HASH_MISMATCH,
            "el escenario no es el de las entradas de la corrida",
            "scenario",
        )
    require_supported(protocol)
    reconciliation = reconcile_run(inputs_dir, runs_root, run_id)
    outputs = runs_root / run_id / "outputs"
    try:
        trips = read_trips(outputs / TRIPINFO, MAX_TRIPINFO_BYTES)
    except DomainError as error:
        raise EvaluacionError(ErrorCode.OUTPUT_INVALID, error.message, TRIPINFO) from error
    summary = _run_summary(outputs)
    times = manifest.times
    cohort = cohort_delay(reconciliation, trips, case, times.end_s)
    zone: ZoneMetrics | None = None
    unavailable: str | None = None
    if manifest.measurement_edges:
        _zone_lanes_recorded(protocol, manifest.measurement_edges)
        fcd = fcd_file(outputs)
        if fcd is None:
            raise EvaluacionError(ErrorCode.OUTPUT_INVALID, f"falta {FCD}", FCD)
        zone = zone_metrics(
            fcd,
            protocol,
            case,
            cohort,
            step_s=times.step_length_s,
            start_s=times.cohort_start_s,
            end_s=times.cohort_end_s,
            max_bytes=MAX_FCD_BYTES,
            edge_access=manifest.measurement_access,
        )
    else:
        unavailable = (
            "la carpeta de entradas no declara zona de medición (manifiesto "
            f"{manifest.schema_version}): la corrida no tiene FCD"
        )
    demand_origin = scenario.request.origin
    return RunMetrics(
        run_id=run_id,
        case_id=case.case_id,
        case_version=case.case_version,
        case_origin=case.origin,
        demand_origin=demand_origin,
        evidence_origin=evidence_origin(case.origin, demand_origin),
        scenario_id=manifest.scenario_id,
        sumo_seed=manifest.seeds.sumo_seed,
        protocol_id=protocol.protocol_id,
        protocol_status=protocol.status,
        delay_definition=DELAY_DEFINITION,
        cohort=cohort,
        zone=zone,
        zone_unavailable=unavailable,
        teleports_total=summary.teleports_total,
        collisions=summary.collisions,
        simulation_findings=list(summary.findings),
    )
