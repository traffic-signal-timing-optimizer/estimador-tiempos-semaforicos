"""Unidades del caso, los protocolos, los escenarios y las particiones (DEV31 F3).

- ``datos/casos/<caso>/case.json``: el cruce (``caso.casos`` y sus movimientos, clases, tramos y
  grupos de verde).
- ``datos/derivados/protocolos/<caso>/*.json``: los protocolos y sus semillas por etapa.
- ``datos/escenarios/<caso>/*.json``: escenarios escritos a mano. Nunca tienen partición: solo se
  cargan como **preliminares**, con la autorización explícita de la carga (regla de F1).
- ``datos/derivados/escenarios/<caso>/<carpeta>``: conjuntos de escenarios publicados (DEV11). Si
  hay una partición publicada de ese conjunto (``datos/derivados/particiones``, DEV12), el
  conjunto y la partición se cargan juntos; si no, solo como preliminares.
"""

import json
from collections.abc import Sequence
from pathlib import Path

from semaforo.aprendizaje.split_store import MANIFEST_FILE as SPLIT_MANIFEST
from semaforo.aprendizaje.split_store import SPLIT_FILE, StoredSplit
from semaforo.bd.carga import crudo
from semaforo.bd.carga.modelo import (
    DATA_ROOT,
    CargaError,
    FileRecord,
    Unit,
    read_file,
    verified_record,
)
from semaforo.caso.case_validation import read_case
from semaforo.datos.scenario_set import MANIFEST_FILE as SET_MANIFEST
from semaforo.datos.scenario_set import ScenarioSet
from semaforo.dominio.case import Case, canonical_sha256, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.protocol import Protocol, parse_protocol
from semaforo.dominio.scenario import Scenario, accept_scenario
from semaforo.dominio.scenario_spec import Family
from semaforo.simulacion.prepare import canonical_json_sha256

__all__ = [
    "CASES",
    "PROTOCOLS",
    "SCENARIOS",
    "case_unit",
    "protocol_unit",
    "scenario_set_unit",
    "scenario_unit",
]

CASES = "casos"
PROTOCOLS = "derivados/protocolos"
SCENARIOS = "escenarios"
CASE_FILE = "case.json"


def _json(data: bytes, where: str) -> object:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise CargaError(
            ErrorCode.INPUT_SCHEMA, f"no es JSON válido ({type(error).__name__})", where
        ) from error


# --- caso ------------------------------------------------------------------------------------


def case_unit(workspace: Path, case_folder: str) -> tuple[Unit, Case]:
    """La unidad del caso de ``datos/casos/<case_folder>`` y el caso leído."""
    relative = f"{CASES}/{case_folder}/{CASE_FILE}"
    record, data = read_file(workspace, DATA_ROOT, relative, "case")
    case = read_case(workspace / relative)
    if canonical_sha256(parse_case(_json(data, relative))) != canonical_sha256(case):
        raise CargaError(ErrorCode.HASH_MISMATCH, "el caso cambió mientras se leía", relative)
    unit = Unit(key=f"caso:{case.case_id}:{case.case_version}", kind="case")
    unit.add_file(record)
    ids = {"caso_id": case.case_id, "caso_version": case.case_version}
    network = case.network
    unit.add(
        "caso.casos",
        {
            **ids,
            "origen": case.origin,
            "descripcion": case.description,
            "estado_representacion": case.representation_status,
            "red_ruta": None if network is None else network.path,
            "red_sha256": None if network is None else network.sha256,
            "tick_s": case.tick_s,
            "ciclo_min_s": case.cycle_s.min,
            "ciclo_max_s": case.cycle_s.max,
            "politica_frontera": case.boundary_policy_id,
            "evidencia_restricciones": list(case.restrictions_evidence),
            "huella_caso": canonical_sha256(case),
        },
        record,
    )
    for order, movement in enumerate(case.movements):
        unit.add(
            "caso.movimientos",
            {
                **ids,
                "movimiento_id": movement.id,
                "orden": order,
                "acceso": movement.approach_id,
                "carriles_entrada": list(movement.incoming_lanes),
                "aristas_salida": list(movement.outgoing_edges),
                "tls_id": movement.tls_id,
                "indices_enlace": list(movement.link_indices),
                "flujo_min_vph": movement.flow_domain_vph.min,
                "flujo_max_vph": movement.flow_domain_vph.max,
            },
            record,
        )
    for order, name in enumerate(case.vehicle_classes):
        unit.add("caso.tipos_vehiculo", {**ids, "clase_id": name, "orden": order}, record)
    for order, slot in enumerate(case.slots):
        unit.add(
            "caso.tramos",
            {
                **ids,
                "tramo_id": slot.id,
                "orden": order,
                "tipo": slot.kind,
                "minimo_s": slot.min_s,
                "maximo_s": slot.max_s,
                "estados": [state.model_dump(mode="json") for state in slot.states],
            },
            record,
        )
    for group in case.green_groups:
        unit.add(
            "caso.grupos_verde",
            {
                **ids,
                "grupo_id": group.id,
                "minimo_s": group.min_s,
                "maximo_s": group.max_s,
                "proposito": group.purpose,
            },
            record,
        )
        for order, slot_id in enumerate(group.slot_ids):
            unit.add(
                "caso.grupo_tramo",
                {**ids, "grupo_id": group.id, "tramo_id": slot_id, "orden": order},
                record,
            )
    return unit, case


# --- protocolos ------------------------------------------------------------------------------


def protocol_unit(workspace: Path, relative: str) -> tuple[Unit, Protocol]:
    """La unidad de un protocolo (``datos/<relative>``) y el protocolo leído."""
    record, data = read_file(workspace, DATA_ROOT, relative, "protocol")
    protocol = parse_protocol(_json(data, relative))
    unit = Unit(key=f"protocolo:{protocol.protocol_id}", kind="protocol")
    unit.add_file(record)
    weights = protocol.group_weight_artifact
    unit.add(
        "experimento.protocolos",
        {
            "protocolo_id": protocol.protocol_id,
            "estado": protocol.status,
            "proposito": protocol.purpose,
            "definicion_metrica": protocol.metric_definition,
            "politica_cohorte": protocol.cohort_policy,
            "politica_censura": protocol.censoring_policy,
            "regla_censura_alternativa": protocol.alternate_censoring_rule,
            "presupuesto_busqueda": protocol.search_budget,
            "limite_intentos": protocol.sampling_attempt_limit,
            "finalistas": protocol.finalist_count,
            "epsilon_empate_s": protocol.tie_epsilon_s,
            "umbral_cola_mps": protocol.queue_speed_threshold_mps,
            "umbral_detencion_mps": protocol.stop_speed_threshold_mps,
            "muestreo_cola_s": protocol.queue_sampling_s,
            "carriles_zona": list(protocol.zone_lane_ids),
            "nivel_confianza": protocol.confidence_level,
            "remuestreos_bootstrap": protocol.bootstrap_repetitions,
            "margen_aceptacion_s": protocol.acceptance_margin_s,
            "tolerancia_error_conteo": protocol.count_error_tolerance,
            "tolerancia_ajuste_simulacion": protocol.simulation_fit_tolerance,
            "referencia_aprobacion": protocol.approval_reference,
            "criterios_calibracion": [
                c.model_dump(mode="json") for c in protocol.calibration_criteria
            ],
            "agregacion_grupos": protocol.group_aggregation,
            "pesos_grupos_ruta": None if weights is None else weights.path,
            "politica_reajuste": protocol.refit_policy,
            "tolerancia_numerica": protocol.numeric_abs_tolerance,
        },
        record,
    )
    stages = (
        ("search", protocol.seeds.search),
        ("finalists", protocol.seeds.finalists),
        ("final", protocol.seeds.final),
    )
    for stage, seeds in stages:
        for order, seed in enumerate(seeds):
            unit.add(
                "experimento.protocolo_semillas",
                {
                    "protocolo_id": protocol.protocol_id,
                    "etapa": stage,
                    "semilla": seed,
                    "orden": order,
                },
                record,
            )
    return unit, protocol


# --- escenarios ------------------------------------------------------------------------------


def _family(unit: Unit, scenario: Scenario, source: FileRecord, family: Family | None) -> None:
    unit.add(
        "experimento.familias",
        {
            "caso_id": scenario.case_id,
            "caso_version": scenario.case_version,
            "familia_id": scenario.group_id,
            "origen": scenario.origin,
            "variantes": None if family is None else family.variants,
            "semillas": None if family is None else family.seeds,
            "rangos_demanda": None
            if family is None
            else [row.model_dump(mode="json") for row in family.demand],
        },
        source,
    )


def _scenario_rows(
    unit: Unit, scenario: Scenario, case: Case, source: FileRecord, *, preliminary: bool
) -> None:
    request = scenario.request
    artifact = scenario.demand_artifact
    unit.need(
        "caso.casos",
        {"caso_id": scenario.case_id, "caso_version": scenario.case_version},
        f"falta el caso {scenario.case_id} {scenario.case_version}",
    )
    unit.add(
        "experimento.escenarios",
        {
            "escenario_id": scenario.scenario_id,
            "caso_id": scenario.case_id,
            "caso_version": scenario.case_version,
            "familia_id": scenario.group_id,
            "origen": scenario.origin,
            "preliminar": preliminary,
            "request_id": request.request_id,
            "origen_solicitud": request.origin,
            "inicio_observacion": request.observation_start,
            "fin_observacion": request.observation_end,
            "fuentes": list(scenario.source_ids),
            "politica_frontera": scenario.boundary_policy_id,
            "calentamiento_s": scenario.warmup_s,
            "medicion_s": scenario.measure_s,
            "vaciado_max_s": scenario.drain_max_s,
            "semilla_demanda": scenario.demand_seed,
            "demanda_ruta": None if artifact is None else artifact.path,
            "demanda_sha256": None if artifact is None else artifact.sha256,
            "huella_escenario": canonical_json_sha256(scenario.model_dump(mode="json")),
        },
        source,
    )
    ids = {
        "escenario_id": scenario.scenario_id,
        "caso_id": scenario.case_id,
        "caso_version": scenario.case_version,
    }
    for row in request.demand:
        if row.flow_vph == 0 or row.composition is None:
            shares: dict[str, float | None] = dict.fromkeys(case.vehicle_classes)
        else:
            shares = dict(row.composition)
        for name, share in shares.items():
            unit.add(
                "experimento.demanda",
                {
                    **ids,
                    "movimiento_id": row.movement_id,
                    "clase_id": name,
                    "flujo_vph": row.flow_vph,
                    "proporcion": share,
                },
                source,
            )


def scenario_unit(
    workspace: Path, relative: str, cases: dict[tuple[str, str], Case]
) -> tuple[Unit, Scenario] | None:
    """La unidad de un escenario escrito a mano (siempre preliminar); ``None`` si el archivo no
    es un escenario (por ejemplo, las rutas o los tipos de vehículo de la misma carpeta)."""
    record, data = read_file(workspace, DATA_ROOT, relative, "scenario")
    try:
        raw = crudo.mapping(_json(data, relative), relative)
    except CargaError:
        return None
    if "scenario_id" not in raw:
        return None
    case_id, version = str(raw.get("case_id")), str(raw.get("case_version"))
    case = cases.get((case_id, version))
    if case is None:
        raise CargaError(ErrorCode.INPUT_SCHEMA, f"falta el caso {case_id} {version}", relative)
    scenario = accept_scenario(raw, case)
    unit = Unit(key=f"escenario:{scenario.scenario_id}", kind="scenario")
    unit.add_file(record)
    _family(unit, scenario, record, None)
    _scenario_rows(unit, scenario, case, record, preliminary=True)
    return unit, scenario


def _set_files(unit: Unit, workspace: Path, folder: str, files: dict[str, str]) -> None:
    """El manifiesto del conjunto y cada archivo que declara (ya verificados por su lector)."""
    manifest, _ = read_file(workspace, DATA_ROOT, f"{folder}/{SET_MANIFEST}", "manifest")
    unit.add_file(manifest)
    for name, digest in sorted(files.items()):
        kind = "scenario" if name.startswith("escenarios/") else "other"
        unit.add_file(
            verified_record(
                workspace, DATA_ROOT, f"{folder}/{name}", kind, digest, manifest.artifact_id
            )
        )


def scenario_set_unit(  # noqa: PLR0913  (todos describen la misma carga)
    workspace: Path,
    folder: str,
    scenario_set: ScenarioSet,
    case: Case,
    split: tuple[str, StoredSplit] | None,
    *,
    preliminary: bool,
) -> Unit:
    """La unidad de un conjunto de escenarios publicado, con su partición si la hay.

    Sin partición, los escenarios se cargan como preliminares (si la carga lo autoriza).
    """
    manifest = scenario_set.manifest
    unit = Unit(key=f"conjunto:{manifest.case_id}:{manifest.content_id[:16]}", kind="scenario_set")
    files = dict(manifest.files)
    _set_files(unit, workspace, folder, files)
    by_family = {family.family_id: family for family in scenario_set.spec.families}
    records = {record.relative: record for record in unit.files}
    for scenario in scenario_set.scenarios:
        source = records[f"{folder}/escenarios/{scenario.scenario_id}.json"]
        _family(unit, scenario, source, by_family.get(scenario.group_id))
        _scenario_rows(unit, scenario, case, source, preliminary=split is None and preliminary)
    if split is not None:
        _split_rows(unit, workspace, split, scenario_set.scenarios)
    return unit


def _split_rows(
    unit: Unit, workspace: Path, split: tuple[str, StoredSplit], scenarios: Sequence[Scenario]
) -> None:
    folder, stored = split
    if not stored.split.frozen:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "solo se cargan particiones congeladas", folder)
    manifest_relative = f"{folder}/{SPLIT_MANIFEST}"
    manifest, _ = read_file(workspace, DATA_ROOT, manifest_relative, "manifest")
    unit.add_file(manifest)
    source = unit.add_file(
        verified_record(
            workspace,
            DATA_ROOT,
            f"{folder}/{SPLIT_FILE}",
            "split",
            stored.manifest.files[SPLIT_FILE],
            manifest.artifact_id,
        )
    )
    known = {scenario.scenario_id for scenario in scenarios}
    unit.add(
        "experimento.particiones",
        {
            "particion_id": stored.split.split_id,
            "politica": stored.split.policy,
            "semilla": stored.split.seed,
            "congelada": stored.split.frozen,
        },
        source,
    )
    for assignment in stored.split.assignments:
        if assignment.scenario_id not in known:
            raise CargaError(
                ErrorCode.INPUT_SCHEMA,
                "la partición asigna un escenario que no es de su conjunto",
                assignment.scenario_id,
            )
        unit.add(
            "experimento.asignaciones",
            {
                "particion_id": stored.split.split_id,
                "escenario_id": assignment.scenario_id,
                "familia_id": assignment.group_id,
                "asignacion": assignment.partition,
            },
            source,
        )
