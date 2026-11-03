"""Comparadores de DEV15 F1: parámetros, plan vigente, estructura del cruce y camino crítico.

Datos sintéticos: el caso de demostración y casos armados a mano con la forma del caso-001. Las
cifras esperadas del camino crítico están calculadas a mano en cada prueba.
"""

import json
import stat
from collections.abc import Mapping
from fractions import Fraction
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
    WebsterTiming,
    crossing_structure,
    read_current_plan,
    read_parameters,
    webster_cycle,
    webster_inputs,
    webster_timing,
)
from semaforo.referencias.errors import ReferenciasError
from semaforo.simulacion.compiler import SLOTS_FILE
from semaforo.trazabilidad.store import TrazabilidadError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "webster" / "parametros-v2.json"
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


def case_from(
    states: dict[str, str],
    movements: list[tuple[str, list[str], list[int]]],
    *,
    fixed: Mapping[str, float] | None = None,
    cycle: tuple[float, float] = (40, 100),
) -> Case:
    """Caso de un semáforo ``T`` con los tramos y movimientos dados: (id, carriles, enlaces).

    ``fixed`` da la duración de los tramos fijos; por defecto son fijos, de 1 s, los tramos sin
    ningún verde (como un ámbar o un todo rojo).
    """
    if fixed is None:
        fixed = {slot_id: 1.0 for slot_id, state in states.items() if not set(state) & set("Gg")}
    data = json_of("case.json")
    data["cycle_s"] = {"min": cycle[0], "max": cycle[1]}
    data["slots"] = [
        {
            "id": slot_id,
            "kind": "fixed" if slot_id in fixed else "variable",
            "min_s": fixed.get(slot_id, 1),
            "max_s": fixed.get(slot_id, 100),
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


def inputs_of(case: Case, flows: Mapping[str, float], **changes: Any) -> WebsterInputs:  # noqa: ANN401
    request = request_with(case, flows)
    return webster_inputs(crossing_structure(case), case, request, parameters(**changes))


def timing_of(case: Case, flows: Mapping[str, float], **changes: Any) -> WebsterTiming:  # noqa: ANN401
    request = request_with(case, flows)
    return webster_timing(crossing_structure(case), case, request, parameters(**changes))


# Forma del caso-001: Javier Prado este→oeste (E) solo en t1; Javier Prado oeste→este (O) en t1, t2
# y t3, y su flecha (O3) solo en t3; Frutales norte→sur (S) en t5; Frutales sur→norte (N) en t5, t6
# y t7. Fijos como en el caso: t2, t4, t6 y t8 de 5 s y t9 de 4 s.
SHAPE = {
    "t1": "GGgrr",
    "t2": "yGgrr",
    "t3": "rGGrr",
    "t4": "ryyrr",
    "t5": "rrrGG",
    "t6": "rrryG",
    "t7": "rrrrG",
    "t8": "rrrry",
    "t9": "rrrrr",
}
SHAPE_FIXED = {"t2": 5.0, "t4": 5.0, "t6": 5.0, "t8": 5.0, "t9": 4.0}


def shape_case(cycle: tuple[float, float] = (40, 100)) -> Case:
    return case_from(SHAPE, SHAPE_MOVEMENTS, fixed=SHAPE_FIXED, cycle=cycle)


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
    assert committed.lost_time_rule == "intergreens_outside_critical_path"
    assert committed.parameter_set == "webster-parametros-v2"
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
        {"lost_time_rule": "fixed_24_s"},
        {"vehicle_equivalence": {"car": -1.0}},
        {
            "applicability": {
                "y_must_be_below": 1.5,
                "cycle_must_be_inside_bounds": True,
                "clipping_allowed": False,
            }
        },
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
        "otra-regla-de-perdida",
        "equivalencia-negativa",
        "limite-de-y-sobre-uno",
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
    structure = crossing_structure(shape_case())
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
    # E 750, O 750, O3 190, S 100, N 260 veh/h; saturación 1800. Recorridos que cubren t1, t3, t5
    # y t7 (S no sirve: t7 solo lo atiende N, que empieza en t5):
    # - E+O3+N: Y = 1200/1800 = 2/3; pierde t2, t4, t8 y t9: L = 19; C0 = 33,5 / (1/3) = 100,5 s.
    # - O+N:    Y = 1010/1800;       pierde t4, t8 y t9:     L = 14; C0 = 26 / (790/1800) = 59,2 s.
    # Gana E+O3+N, el que pide más ciclo.
    inputs = inputs_of(shape_case(), {"E": 750, "O": 750, "O3": 190, "S": 100, "N": 260})
    assert inputs.status == "applicable"
    path = inputs.critical_path
    assert path is not None
    assert path.y == pytest.approx(2 / 3)
    assert path.lost_time_s == pytest.approx(19)
    assert path.cycle_s == pytest.approx(100.5)
    assert path.lane_ids == ("E_0", "O_3", "N_1")
    assert path.lost_slot_ids == ("t2", "t4", "t8", "t9")


def test_the_critical_path_changes_with_the_flows() -> None:
    # Con E en 300: E+O3+N da Y = 750/1800 y C0 = 33,5 / (1050/1800) = 57,4 s; O+N da
    # Y = 1010/1800 y C0 = 26 / (790/1800) = 59,2 s. Gana O+N.
    inputs = inputs_of(shape_case(), {"E": 300, "O": 750, "O3": 190, "S": 100, "N": 260})
    path = inputs.critical_path
    assert path is not None
    assert path.y == pytest.approx(1010 / 1800)
    assert path.lost_time_s == pytest.approx(14)
    assert path.cycle_s == pytest.approx(26 / (790 / 1800))
    assert path.lane_ids == ("O_0", "N_1")


def test_the_path_that_asks_for_more_cycle_wins_even_with_less_y() -> None:
    # A atiende v1, f (fijo, 10 s) y v2: Y = 0,5, L = 0, C0 = 5 / 0,5 = 10 s.
    # B (v1) y C (v2) pierden f: Y = 0,25 + 0,2 = 0,45, L = 10, C0 = 20 / 0,55 = 36,4 s.
    # Gana B+C aunque su Y es menor: con su pérdida exige un ciclo más largo.
    case = case_from(
        {"v1": "GGr", "f": "Gyr", "v2": "GrG"},
        [("A", ["A_0"], [0]), ("B", ["B_0"], [1]), ("C", ["C_0"], [2])],
        fixed={"f": 10.0},
        cycle=(1, 240),
    )
    path = inputs_of(case, {"A": 900, "B": 450, "C": 360}).critical_path
    assert path is not None
    assert path.lane_ids == ("B_0", "C_0")
    assert path.cycle_s == pytest.approx(20 / 0.55)


def test_a_green_shared_by_two_lanes_is_not_counted_twice() -> None:
    # Sumar el carril mayor de cada tramo contaría O en t1 y otra vez en t3: (750+750+260+260)/1800.
    flows = {"E": 750, "O": 750, "O3": 190, "S": 100, "N": 260}
    inputs = inputs_of(shape_case(), flows)
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
    assert inputs.parameter_set == "webster-parametros-v2"
    assert inputs.adaptation == ADAPTATION


# --- ciclo y verdes de Webster (QA17, calculado a mano) ----------------------------------------


def test_the_webster_formula() -> None:
    # C0 = (1,5 * 10 + 5) / (1 - 0,5) = 40 s.
    assert webster_cycle(Fraction(1, 2), Fraction(10)) == 40
    assert webster_cycle(Fraction(0), Fraction(0)) == 5


def test_two_phases_by_hand() -> None:
    # Caso de demostración: N 720 y E 540 veh/h, saturación 1800: y = 0,4 y 0,3; Y = 0,7.
    # Pierde los fijos s2, s3, s5 y s6: L = 3 + 1 + 3 + 1 = 8 s.
    # C0 = (1,5 * 8 + 5) / 0,3 = 17 / 0,3 = 56,667 s. Verde efectivo C0 - L = 48,667 s:
    # N = 48,667 * 0,4 / 0,7 = 27,810 s y E = 48,667 * 0,3 / 0,7 = 20,857 s.
    case = parse_case(json_of("case.json"))
    timing = webster_timing(
        crossing_structure(case), case, request_with(case, {"N_S": 720, "E_W": 540}), parameters()
    )
    assert timing.status == "applicable"
    assert timing.cycle_s == pytest.approx(17 / 0.3)
    assert timing.effective_green_s == {
        "demo_N_0": pytest.approx((17 / 0.3 - 8) * 4 / 7),
        "demo_E_0": pytest.approx((17 / 0.3 - 8) * 3 / 7),
    }


def test_the_caso_001_shape_by_hand() -> None:
    # Recorrido E+O3+N: Y = 2/3, L = 19, C0 = 100,5 s, verde efectivo 81,5 s.
    # Cada carril recibe y * 81,5 / (2/3) = y * 122,25 s:
    # E y O 750/1800 → 50,9375 s; O3 190/1800 → 12,904 s;
    # N 260/1800 → 17,658 s; S 100/1800 → 6,792 s.
    timing = timing_of(
        shape_case(cycle=(60, 240)), {"E": 750, "O": 750, "O3": 190, "S": 100, "N": 260}
    )
    assert timing.status == "applicable"
    assert timing.cycle_s == pytest.approx(100.5)
    factor = 81.5 / (2 / 3)
    assert timing.effective_green_s == {
        "E_0": pytest.approx(750 / 1800 * factor),
        "O_0": pytest.approx(750 / 1800 * factor),
        "O_3": pytest.approx(190 / 1800 * factor),
        "S_0": pytest.approx(100 / 1800 * factor),
        "N_1": pytest.approx(260 / 1800 * factor),
    }
    critical = sum(timing.effective_green_s[lane] for lane in ("E_0", "O_3", "N_1"))
    assert critical == pytest.approx(100.5 - 19)


def test_a_cycle_outside_the_case_bounds_is_reported_and_not_clipped() -> None:
    # La misma forma con los límites del caso real (120 a 240 s): C0 = 100,5 s queda fuera.
    timing = timing_of(
        shape_case(cycle=(120, 240)), {"E": 750, "O": 750, "O3": 190, "S": 100, "N": 260}
    )
    assert timing.status == "not_applicable"
    assert [problem.code for problem in timing.problems] == ["cycle_out_of_bounds"]
    assert timing.cycle_s == pytest.approx(100.5)
    assert timing.effective_green_s == {}
    assert "100.5" in timing.problems[0].message


def test_a_cycle_above_the_case_maximum_is_not_applicable() -> None:
    # Demostración (40 a 100 s): N 900 y E 720 dan Y = 0,5 + 0,4 = 0,9; C0 = 17 / 0,1 = 170 s.
    case = parse_case(json_of("case.json"))
    timing = webster_timing(
        crossing_structure(case), case, request_with(case, {"N_S": 900, "E_W": 720}), parameters()
    )
    assert [problem.code for problem in timing.problems] == ["cycle_out_of_bounds"]
    assert timing.cycle_s == pytest.approx(170)


def test_an_oversaturated_crossing_has_no_webster_cycle() -> None:
    # N 900 y E 900: Y = 0,5 + 0,5 = 1.
    case = parse_case(json_of("case.json"))
    timing = webster_timing(
        crossing_structure(case), case, request_with(case, {"N_S": 900, "E_W": 900}), parameters()
    )
    assert timing.status == "not_applicable"
    assert [problem.code for problem in timing.problems] == ["oversaturated"]
    assert timing.cycle_s is None


def test_the_saturation_limit_comes_from_the_parameters() -> None:
    # Y = 0,7 con un límite de 0,6: no aplica.
    case = parse_case(json_of("case.json"))
    rules = {"y_must_be_below": 0.6, "cycle_must_be_inside_bounds": True, "clipping_allowed": False}
    timing = webster_timing(
        crossing_structure(case),
        case,
        request_with(case, {"N_S": 720, "E_W": 540}),
        parameters(applicability=rules),
    )
    assert [problem.code for problem in timing.problems] == ["oversaturated"]


def test_without_demand_there_is_no_webster_cycle() -> None:
    case = parse_case(json_of("case.json"))
    timing = webster_timing(
        crossing_structure(case), case, request_with(case, {"N_S": 0, "E_W": 0}), parameters()
    )
    assert [problem.code for problem in timing.problems] == ["no_demand"]


def test_a_variable_slot_that_nobody_uses_leaves_no_covering_path() -> None:
    case = case_from({"a": "G", "b": "r"}, [("X", ["X_0"], [0])], fixed={})
    timing = timing_of(case, {"X": 300})
    assert [problem.code for problem in timing.problems] == ["no_covering_path"]
    assert timing.critical_path is None


def test_missing_data_also_stops_the_cycle() -> None:
    case = case_from({"a": "GG", "b": "rr"}, [("X", ["X_0"], [0]), ("W", ["W_0"], [1])])
    timing = webster_timing(
        crossing_structure(case), case, request_with(case, {"X": 300}), parameters()
    )
    assert timing.status == "not_applicable"
    assert [problem.code for problem in timing.problems] == ["missing_flow"]
    assert timing.cycle_s is None


def test_the_timing_carries_its_parameters() -> None:
    timing = timing_of(
        case_from({"a": "G", "b": "r"}, [("X", ["X_0"], [0])], cycle=(1, 240)), {"X": 900}
    )
    assert timing.provisional
    assert timing.parameter_set == "webster-parametros-v2"
    assert timing.adaptation == ADAPTATION


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
