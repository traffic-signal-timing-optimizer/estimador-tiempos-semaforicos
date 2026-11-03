"""Comparadores de DEV15 F1: parámetros, plan vigente, estructura del cruce y camino crítico.

Datos sintéticos: el caso de demostración y casos armados a mano con la forma del caso-001. Las
cifras esperadas del camino crítico están calculadas a mano en cada prueba.
"""

import json
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from prepared_inputs import DURATIONS, json_of, request_for
from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.feasibility import prepare
from semaforo.dominio.scenario import Request
from semaforo.referencias.baselines import (
    ADAPTATION,
    WebsterInputs,
    WebsterParameters,
    crossing_structure,
    read_current_plan,
    read_parameters,
    webster_inputs,
)
from semaforo.referencias.errors import ReferenciasError
from semaforo.simulacion.compiler import SLOTS_FILE
from semaforo.trazabilidad.store import TrazabilidadError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "webster" / "parametros-v1.json"
TLS = "T"


def parameters_data(**changes: Any) -> dict[str, Any]:  # noqa: ANN401 - campos del archivo
    data: dict[str, Any] = json.loads(CONFIG.read_text(encoding="utf-8"))
    data.update(
        case_id="SYNTHETIC_DEMO",
        case_version="1.0.0",
        vehicle_equivalence={"car": 1.0, "bus": 2.0},
    )
    data["current_plan"] = {**data["current_plan"], "cycle_s": sum(DURATIONS.values())}
    data.update(changes)
    return data


def parameters(**changes: Any) -> WebsterParameters:  # noqa: ANN401 - campos del archivo
    return WebsterParameters.model_validate(parameters_data(**changes))


def case_from(states: dict[str, str], movements: list[tuple[str, list[str], list[int]]]) -> Case:
    """Caso de un semáforo ``T`` con los tramos y movimientos dados: (id, carriles, enlaces)."""
    data = json_of("case.json")
    data["slots"] = [
        {
            "id": slot_id,
            "kind": "variable",
            "min_s": 1,
            "max_s": 100,
            "states": [{"tls_id": TLS, "state": state}],
        }
        for slot_id, state in states.items()
    ]
    data["movements"] = [
        {
            "id": movement_id,
            "approach_id": lanes[0].split("_")[0],
            "incoming_lanes": lanes,
            "outgoing_edges": ["salida"],
            "tls_id": TLS,
            "link_indices": links,
            "flow_domain_vph": {"min": 0, "max": 3600},
        }
        for movement_id, lanes, links in movements
    ]
    data["green_groups"] = [
        {
            "id": "G1",
            "slot_ids": [next(iter(states))],
            "min_s": 1,
            "max_s": 100,
            "purpose": "vehicle",
        }
    ]
    return parse_case(data)


def request_with(
    case: Case, flows: Mapping[str, float], composition: dict[str, float] | None = None
) -> Request:
    """Solicitud con esos flujos; por defecto, todos autos."""
    data = json_of("request.json")
    data.update(case_id=case.case_id, case_version=case.case_version)
    mix = {"car": 1.0, "bus": 0.0} if composition is None else composition
    data["demand"] = [
        {"movement_id": movement_id, "flow_vph": flow, "composition": mix if flow > 0 else None}
        for movement_id, flow in flows.items()
    ]
    return Request.model_validate(data)


def inputs_of(case: Case, flows: Mapping[str, float]) -> WebsterInputs:
    return webster_inputs(crossing_structure(case), case, request_with(case, flows), parameters())


# Forma del caso-001: Javier Prado este (E) solo en t1; Javier Prado oeste (O) en t1, t2 y t3, y su
# giro (O3) solo en t3; Frutales sur (S) en t5; Frutales norte (N) en t5, t6 y t7.
SHAPE = {
    "t1": "GGgrr",
    "t2": "yGgrr",
    "t3": "rGGrr",
    "t4": "ryyrr",
    "t5": "rrrGG",
    "t6": "rrryG",
    "t7": "rrrrG",
    "t8": "rrrry",
}
SHAPE_MOVEMENTS = [
    ("E", ["E_0"], [0]),
    ("O", ["O_0"], [1]),
    ("O3", ["O_3"], [2]),
    ("S", ["S_0"], [3]),
    ("N", ["N_1"], [4]),
]


# --- parámetros --------------------------------------------------------------------------------


def test_the_committed_parameters_are_valid_and_provisional() -> None:
    committed = WebsterParameters.model_validate(json.loads(CONFIG.read_text(encoding="utf-8")))
    assert committed.provisional
    assert committed.approval.especialista is None
    assert committed.adaptation == ADAPTATION
    assert committed.lost_time_s >= 0
    assert committed.case_id == "caso-001"


def test_parameters_are_read_for_their_case(tmp_path: Path) -> None:
    path = tmp_path / "parametros.json"
    path.write_text(json.dumps(parameters_data()), encoding="utf-8")
    case = parse_case(json_of("case.json"))
    assert read_parameters(path, case).saturation_flow_veh_h_lane == 1800
    other = case.model_copy(update={"case_id": "OTRO"})
    with pytest.raises(ReferenciasError) as error:
        read_parameters(path, other)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


@pytest.mark.parametrize(
    "changes",
    [
        {"saturation_flow_veh_h_lane": 0},
        {"lost_time_s": -1},
        {"vehicle_equivalence": {"car": -1.0}},
        {"cycle_bounds_s": [240, 120]},
        {"cycle_bounds_s": [120]},
        {"status": "approved"},
        {
            "applicability": {
                "y_must_be_below": 1.0,
                "cycle_must_be_inside_bounds": True,
                "clipping_allowed": True,
            }
        },
        {"adaptation": "webster-puro"},
        {"sobra": 1},
    ],
    ids=[
        "saturacion-cero",
        "perdida-negativa",
        "equivalencia-negativa",
        "limites-al-reves",
        "un-limite",
        "aprobado-sin-especialista",
        "con-recorte",
        "otra-adaptacion",
        "campo-extra",
    ],
)
def test_invalid_parameters_are_rejected(tmp_path: Path, changes: dict[str, Any]) -> None:
    path = tmp_path / "parametros.json"
    path.write_text(json.dumps(parameters_data(**changes)), encoding="utf-8")
    with pytest.raises(ReferenciasError) as error:
        read_parameters(path, parse_case(json_of("case.json")))
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_approved_parameters_with_a_specialist_are_not_provisional() -> None:
    approval = {"decision": "DEC08", "especialista": "Nombre", "nota": ""}
    assert not parameters(status="approved", approval=approval).provisional


# --- estructura del cruce ----------------------------------------------------------------------


def test_the_demo_lanes_are_served_in_their_own_slot() -> None:
    structure = crossing_structure(parse_case(json_of("case.json")))
    by_lane = {lane.lane_id: lane for lane in structure.lanes}
    assert structure.slot_ids == ("s1", "s2", "s3", "s4", "s5", "s6")
    assert by_lane["demo_N_0"].protected == ("s1",)
    assert by_lane["demo_N_0"].span == (0, 0)
    assert by_lane["demo_E_0"].protected == ("s4",)
    assert by_lane["demo_E_0"].span == (3, 3)


def test_a_lane_is_served_across_consecutive_slots_including_fixed_ones() -> None:
    structure = crossing_structure(case_from(SHAPE, SHAPE_MOVEMENTS))
    by_lane = {lane.lane_id: lane for lane in structure.lanes}
    assert by_lane["O_0"].protected == ("t1", "t2", "t3")
    assert by_lane["O_0"].span == (0, 2)
    assert by_lane["O_3"].protected == ("t3",)
    assert by_lane["O_3"].permissive == ("t1", "t2")
    assert by_lane["N_1"].span == (4, 6)


@pytest.mark.parametrize(
    ("states", "shape"),
    [
        ({"a": "G", "b": "G", "c": "r"}, "contiguous"),
        ({"a": "G", "b": "r", "c": "G"}, "wrapping"),
        ({"a": "G", "b": "r", "c": "G", "d": "r"}, "split"),
        ({"a": "g", "b": "r"}, "none"),
        ({"a": "r", "b": "y"}, "none"),
    ],
    ids=["seguidos", "cruza-el-fin", "partido", "solo-cede", "nunca"],
)
def test_the_shape_of_the_service(states: dict[str, str], shape: str) -> None:
    [lane] = crossing_structure(case_from(states, [("X", ["X_0"], [0])])).lanes
    assert lane.shape == shape


def test_a_movement_is_protected_only_when_all_its_links_are() -> None:
    [lane] = crossing_structure(case_from({"a": "Gg", "b": "GG"}, [("X", ["X_0"], [0, 1])])).lanes
    assert lane.protected == ("b",)
    assert lane.permissive == ("a",)


def test_a_shared_lane_with_priority_is_not_also_reported_as_yielding() -> None:
    # Como el carril 0 de Javier Prado oeste→este en t1: un movimiento con G y otro con g.
    case = case_from({"a": "Gg", "b": "rr"}, [("X", ["L_0"], [0]), ("Y", ["L_0"], [1])])
    [lane] = crossing_structure(case).lanes
    assert lane.movement_ids == ("X", "Y")
    assert lane.protected == ("a",)
    assert lane.permissive == ()


def test_a_slot_without_the_signal_of_a_movement_is_an_error() -> None:
    case = case_from({"a": "G"}, [("X", ["X_0"], [3])])
    with pytest.raises(ReferenciasError) as error:
        crossing_structure(case)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


# --- camino crítico (calculado a mano) ---------------------------------------------------------


def test_the_critical_path_of_the_caso_001_shape() -> None:
    # E 750, O 750, O3 190, S 100, N 260 veh/h; saturación 1800.
    # Caminos posibles sin tramos compartidos: E+O3+N = 1200; O+N = 1010; E+O3+S = 1040; O+S = 850.
    # Y = 1200/1800 = 2/3, con los carriles E_0, O_3 y N_1.
    inputs = inputs_of(
        case_from(SHAPE, SHAPE_MOVEMENTS), {"E": 750, "O": 750, "O3": 190, "S": 100, "N": 260}
    )
    assert inputs.status == "applicable"
    assert inputs.critical_path is not None
    assert inputs.critical_path.y == pytest.approx(2 / 3)
    assert inputs.critical_path.lane_ids == ("E_0", "O_3", "N_1")


def test_the_critical_path_changes_with_the_flows() -> None:
    # Con E en 300: E+O3+N = 750 y O+N = 1010; gana O+N: Y = 1010/1800.
    inputs = inputs_of(
        case_from(SHAPE, SHAPE_MOVEMENTS), {"E": 300, "O": 750, "O3": 190, "S": 100, "N": 260}
    )
    assert inputs.critical_path is not None
    assert inputs.critical_path.y == pytest.approx(1010 / 1800)
    assert inputs.critical_path.lane_ids == ("O_0", "N_1")


def test_a_green_shared_by_two_lanes_is_not_counted_twice() -> None:
    # Sumar el carril mayor de cada tramo contaría O en t1 y otra vez en t3: (750+750+260+260)/1800.
    flows = {"E": 750, "O": 750, "O3": 190, "S": 100, "N": 260}
    inputs = inputs_of(case_from(SHAPE, SHAPE_MOVEMENTS), flows)
    assert inputs.critical_path is not None
    assert inputs.critical_path.y < (750 + 750 + 260 + 260) / 1800


def test_equal_paths_are_chosen_the_same_way_every_time() -> None:
    case = case_from({"a": "GG", "b": "rr"}, [("B", ["B_0"], [1]), ("A", ["A_0"], [0])])
    inputs = inputs_of(case, {"A": 900, "B": 900})
    assert inputs.critical_path is not None
    assert inputs.critical_path.y == pytest.approx(0.5)
    assert inputs.critical_path.lane_ids == ("A_0",)


def test_vehicle_equivalences_weigh_the_flow() -> None:
    # 600 veh/h, mitad autos (1,0) y mitad buses (2,0): 900 equivalentes; 900/1800 = 0,5.
    case = case_from({"a": "G", "b": "r"}, [("X", ["X_0"], [0])])
    request = request_with(case, {"X": 600}, {"car": 0.5, "bus": 0.5})
    inputs = webster_inputs(crossing_structure(case), case, request, parameters())
    assert inputs.flow_ratios == {"X_0": pytest.approx(0.5)}


def test_a_class_with_no_share_needs_no_equivalence() -> None:
    case = case_from({"a": "G", "b": "r"}, [("X", ["X_0"], [0])])
    request = request_with(case, {"X": 900}, {"car": 1.0, "truck": 0.0})
    inputs = webster_inputs(crossing_structure(case), case, request, parameters())
    assert inputs.status == "applicable"
    assert inputs.flow_ratios == {"X_0": pytest.approx(0.5)}


def test_a_movement_on_two_lanes_splits_its_flow() -> None:
    case = case_from({"a": "G", "b": "r"}, [("X", ["X_0", "X_1"], [0])])
    inputs = inputs_of(case, {"X": 1800})
    assert inputs.flow_ratios == {"X_0": pytest.approx(0.5), "X_1": pytest.approx(0.5)}


def test_inputs_are_marked_with_their_parameters_and_adaptation() -> None:
    inputs = inputs_of(case_from({"a": "G", "b": "r"}, [("X", ["X_0"], [0])]), {"X": 100})
    assert inputs.provisional
    assert inputs.parameter_set == "webster-parametros-v1"
    assert inputs.adaptation == ADAPTATION


# --- no aplicable ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("states", "code"),
    [
        ({"a": "g", "b": "r"}, "permissive_only"),
        ({"a": "r", "b": "y"}, "lane_never_green"),
        ({"a": "G", "b": "r", "c": "G", "d": "r"}, "split_service"),
        ({"a": "G", "b": "r", "c": "G"}, "wrapping_service"),
    ],
)
def test_a_lane_that_webster_cannot_size_makes_it_not_applicable(
    states: dict[str, str], code: str
) -> None:
    inputs = inputs_of(case_from(states, [("X", ["X_0"], [0])]), {"X": 300})
    assert inputs.status == "not_applicable"
    assert [problem.code for problem in inputs.problems] == [code]
    assert inputs.critical_path is None


def test_a_lane_without_flow_does_not_need_green() -> None:
    case = case_from({"a": "Gr", "b": "rr"}, [("X", ["X_0"], [0]), ("Z", ["Z_0"], [1])])
    inputs = inputs_of(case, {"X": 300, "Z": 0})
    assert inputs.status == "applicable"
    assert "Z_0" not in inputs.flow_ratios


def test_missing_data_is_not_invented() -> None:
    case = case_from({"a": "GG", "b": "rr"}, [("X", ["X_0"], [0]), ("W", ["W_0"], [1])])
    structure = crossing_structure(case)
    missing_row = webster_inputs(structure, case, request_with(case, {"X": 300}), parameters())
    assert [p.code for p in missing_row.problems] == ["missing_flow"]
    no_mix = request_with(case, {"X": 300, "W": 0})
    no_mix = no_mix.model_copy(
        update={
            "demand": [no_mix.demand[0].model_copy(update={"composition": None}), no_mix.demand[1]]
        }
    )
    assert [p.code for p in webster_inputs(structure, case, no_mix, parameters()).problems] == [
        "missing_composition"
    ]
    trucks = request_with(case, {"X": 300, "W": 0}, {"car": 0.5, "truck": 0.5})
    unknown = webster_inputs(structure, case, trucks, parameters())
    assert [(p.code, p.subject) for p in unknown.problems] == [("missing_equivalence", "truck")]
    assert all(result.status == "not_applicable" for result in (missing_row, unknown))


def test_a_request_or_parameters_of_another_case_are_refused() -> None:
    case = case_from({"a": "G", "b": "r"}, [("X", ["X_0"], [0])])
    structure = crossing_structure(case)
    other = request_with(case, {"X": 1}).model_copy(update={"case_id": "OTRO"})
    with pytest.raises(ReferenciasError):
        webster_inputs(structure, case, other, parameters())
    with pytest.raises(ReferenciasError):
        webster_inputs(structure, case, request_with(case, {"X": 1}), parameters(case_id="OTRO"))


# --- plan vigente ------------------------------------------------------------------------------


def test_the_current_plan_is_read_with_its_source(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    plan = read_current_plan(request.program_dir, prepare(request.case), parameters())
    assert dict(plan.durations_s) == DURATIONS
    assert plan.cycle_s == sum(DURATIONS.values())
    assert plan.feasible
    assert plan.source == parameters().current_plan.source
    assert plan.hourly_variation == parameters().current_plan.hourly_variation
    assert plan.program_folder == request.program_dir.name


def test_an_observed_plan_that_breaks_the_rules_is_kept_with_them(tmp_path: Path) -> None:
    def narrow(data: dict[str, Any]) -> None:
        data["slots"][0]["max_s"] = 25

    request = request_for(tmp_path, case_change=narrow)
    plan = read_current_plan(request.program_dir, prepare(request.case), parameters())
    assert not plan.feasible
    assert plan.violated


def test_a_current_plan_with_another_cycle_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    record = {**parameters_data()["current_plan"], "cycle_s": 61}
    with pytest.raises(ReferenciasError) as error:
        read_current_plan(
            request.program_dir, prepare(request.case), parameters(current_plan=record)
        )
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_a_program_with_other_slots_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    case = request.case
    renamed = [slot.model_copy(update={"id": f"x{slot.id}"}) for slot in case.slots]
    groups = [
        group.model_copy(update={"slot_ids": [f"x{slot_id}" for slot_id in group.slot_ids]})
        for group in case.green_groups
    ]
    other = prepare(case.model_copy(update={"slots": renamed, "green_groups": groups}))
    with pytest.raises(ReferenciasError) as error:
        read_current_plan(request.program_dir, other, parameters())
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_a_program_of_another_case_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    other = prepare(request.case.model_copy(update={"case_id": "OTRO"}))
    with pytest.raises(ReferenciasError):
        read_current_plan(request.program_dir, other, parameters())


def test_an_altered_program_is_not_read(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    path = request.program_dir / SLOTS_FILE
    path.chmod(stat.S_IWRITE)
    path.write_text(path.read_text(encoding="utf-8").replace("30.0", "31.0", 1), encoding="utf-8")
    with pytest.raises(TrazabilidadError) as error:
        read_current_plan(request.program_dir, prepare(request.case), parameters())
    assert error.value.code == ErrorCode.HASH_MISMATCH
