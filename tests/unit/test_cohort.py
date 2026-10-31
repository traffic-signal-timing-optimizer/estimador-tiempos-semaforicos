"""Cohorte de vehículos (DEV06 F1): cantidades exactas, horas reproducibles e identificadores."""

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.scenario import Scenario, ScenarioInvalidError, parse_scenario
from semaforo.simulacion.cohort import (
    MAX_VEHICLES,
    Cohort,
    CohortCount,
    CohortError,
    CohortVehicle,
    generate_cohort,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str) -> dict[str, Any]:
    return copy.deepcopy(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def build(
    case: dict[str, Any] | None = None, scenario: dict[str, Any] | None = None
) -> tuple[Scenario, Case]:
    return parse_scenario(scenario or load("scenario.json")), parse_case(case or load("case.json"))


def make(**changes: object) -> Cohort:
    """Cohorte del ejemplo con cambios del escenario (``warmup_s``, ``demand_seed``…)."""
    data = load("scenario.json")
    data.update(changes)
    scenario, case = build(scenario=data)
    return generate_cohort(scenario, case)


def counts_of(cohort: Cohort, *, measured: bool = True) -> dict[tuple[str, str], int]:
    return {
        (count.movement_id, count.vehicle_class): count.measured if measured else count.warmup
        for count in cohort.counts
    }


def set_demand(data: dict[str, Any], movement: str, **values: object) -> None:
    for row in data["request"]["demand"]:
        if row["movement_id"] == movement:
            row.update(values)


# --- cantidades exactas ---------------------------------------------------------------------


def test_the_example_scenario_asks_for_the_exact_number_of_vehicles() -> None:
    cohort = make()
    assert cohort.counts == (
        CohortCount("N_S", "bus", 0, 10),
        CohortCount("N_S", "car", 0, 90),
        CohortCount("E_W", "bus", 0, 0),
        CohortCount("E_W", "car", 0, 50),
    )
    assert len(cohort.vehicles) == 150
    assert Counter((v.movement_id, v.vehicle_class) for v in cohort.vehicles) == {
        ("N_S", "bus"): 10,
        ("N_S", "car"): 90,
        ("E_W", "car"): 50,
    }


def test_every_vehicle_of_a_scenario_without_warmup_is_in_the_cohort() -> None:
    cohort = make()
    assert all(vehicle.in_cohort for vehicle in cohort.vehicles)
    assert cohort.measured == cohort.vehicles


def test_the_count_is_the_flow_over_the_measuring_time() -> None:
    cohort = make(measure_s=1800)
    assert sum(counts_of(cohort).values()) == 300  # (400 + 200) veh/h durante media hora


@pytest.mark.parametrize(
    ("flow", "expected"),
    [
        (0.5, 0),
        (1.5, 0),
        (1.6, 0),
        (2, 1),
        (2.2, 1),
        (3, 1),
        (5, 1),
        (6, 2),
        (7, 2),
        (10, 3),
        (4, 1),
    ],
)
def test_the_count_is_rounded_to_the_nearest_integer_with_halves_going_up(
    flow: float, expected: int
) -> None:
    # 900 s = un cuarto de hora: 2 veh/h son 0.5 vehículos, 6 veh/h son 1.5, 10 veh/h son 2.5
    data = load("scenario.json")
    set_demand(data, "N_S", flow_vph=flow)
    scenario, case = build(scenario=data)
    cohort = generate_cohort(scenario, case)
    assert counts_of(cohort)[("N_S", "bus")] + counts_of(cohort)[("N_S", "car")] == expected


def test_a_flow_of_zero_asks_for_no_vehicles() -> None:
    data = load("scenario.json")
    set_demand(data, "E_W", flow_vph=0, composition=None)
    scenario, case = build(scenario=data)
    cohort = generate_cohort(scenario, case)
    assert {v.movement_id for v in cohort.vehicles} == {"N_S"}
    assert counts_of(cohort)[("E_W", "car")] == 0


def case_with_four_classes() -> dict[str, Any]:
    case = load("case.json")
    case["vehicle_classes"] = ["passenger", "motorcycle", "truck", "bus"]
    return case


def scenario_with(composition: dict[str, float], flow: float = 40) -> dict[str, Any]:
    data = load("scenario.json")
    set_demand(data, "N_S", flow_vph=flow, composition=composition)
    set_demand(data, "E_W", flow_vph=0, composition=None)
    return data


def test_the_classes_are_split_by_the_largest_remainder() -> None:
    # 10 vehículos: 8.2, 0.8, 0.6, 0.4 → 8 + 0 + 0 + 0 y los dos que sobran van a 0.8 y 0.6
    composition = {"passenger": 0.82, "motorcycle": 0.08, "truck": 0.06, "bus": 0.04}
    scenario, case = build(case_with_four_classes(), scenario_with(composition))
    counts = counts_of(generate_cohort(scenario, case))
    assert counts == {
        ("N_S", "bus"): 0,
        ("N_S", "motorcycle"): 1,
        ("N_S", "passenger"): 8,
        ("N_S", "truck"): 1,
        ("E_W", "bus"): 0,
        ("E_W", "motorcycle"): 0,
        ("E_W", "passenger"): 0,
        ("E_W", "truck"): 0,
    }


def test_a_tie_in_the_remainders_goes_to_the_smaller_class_name() -> None:
    # 3 vehículos al 50 % y 50 %: 1.5 y 1.5 → uno extra, para «bus» y no para «car»
    scenario, case = build(scenario=scenario_with({"car": 0.5, "bus": 0.5}, flow=12))
    counts = counts_of(generate_cohort(scenario, case))
    assert (counts[("N_S", "bus")], counts[("N_S", "car")]) == (2, 1)


def test_a_class_with_proportion_zero_gets_no_vehicles_and_one_with_all_gets_all() -> None:
    scenario, case = build(scenario=scenario_with({"car": 0.0, "bus": 1.0}))
    counts = counts_of(generate_cohort(scenario, case))
    assert (counts[("N_S", "bus")], counts[("N_S", "car")]) == (10, 0)


def test_a_class_left_out_of_the_composition_gets_no_vehicles() -> None:
    scenario, case = build(scenario=scenario_with({"car": 1.0}))
    counts = counts_of(generate_cohort(scenario, case))
    assert (counts[("N_S", "bus")], counts[("N_S", "car")]) == (0, 10)


def test_shares_that_add_up_to_one_only_within_rounding_still_give_the_exact_total() -> None:
    scenario, case = build(scenario=scenario_with({"car": 0.1 + 0.2, "bus": 0.7}, flow=400))
    counts = counts_of(generate_cohort(scenario, case))
    assert counts[("N_S", "bus")] + counts[("N_S", "car")] == 100


@pytest.mark.parametrize("flow", [13, 37, 101, 523, 777, 1111])
def test_the_split_always_adds_up_to_the_total(flow: float) -> None:
    composition = {"passenger": 0.82, "motorcycle": 0.08, "truck": 0.06, "bus": 0.04}
    case = case_with_four_classes()
    case["movements"][0]["flow_domain_vph"]["max"] = 5000
    scenario, parsed_case = build(case, scenario_with(composition, flow))
    cohort = generate_cohort(scenario, parsed_case)
    expected = int(flow * 900 / 3600 + 0.5)
    assert sum(v for (m, _), v in counts_of(cohort).items() if m == "N_S") == expected
    assert len([v for v in cohort.vehicles if v.movement_id == "N_S"]) == expected


def test_the_decimals_of_a_flow_are_taken_as_written() -> None:
    # 1.2 veh/h durante 1500 s son exactamente 0.5 vehículos, y la mitad sube. En coma flotante
    # 1.2 es un poco menos que 1.2 y daría 0.4999…, que bajaría a 0.
    data = scenario_with({"car": 1.0}, flow=1.2)
    data["measure_s"] = 1500
    data["request"]["observation_end"] = "2026-10-18T08:25:00-05:00"
    scenario, case = build(scenario=data)
    assert counts_of(generate_cohort(scenario, case))[("N_S", "car")] == 1


# --- reproducibilidad -----------------------------------------------------------------------


def test_the_same_inputs_and_seed_give_the_same_list() -> None:
    assert make() == make()


def test_another_seed_gives_other_hours_but_the_same_numbers() -> None:
    base, other = make(), make(demand_seed=101)
    assert base.vehicles != other.vehicles
    assert base.counts == other.counts


def test_the_list_does_not_depend_on_the_order_of_the_demand_rows() -> None:
    data = load("scenario.json")
    data["request"]["demand"].reverse()
    scenario, case = build(scenario=data)
    reversed_rows = generate_cohort(scenario, case)
    assert reversed_rows.vehicles == make().vehicles


def test_the_list_is_the_same_as_the_recorded_one() -> None:
    cohort = make()
    first = [(v.vehicle_id, v.depart_s) for v in cohort.vehicles[:4]]
    assert first == [
        ("N_S.car.1", 0.0),
        ("E_W.car.1", 4.0),
        ("E_W.car.2", 5.0),
        ("E_W.car.3", 17.0),
    ]
    text = ";".join(f"{v.vehicle_id}@{v.depart_s}" for v in cohort.vehicles)
    assert hashlib.sha256(text.encode()).hexdigest() == (
        "71df33d9b8612dbae2795225b4fff3151b04617ceff38bcf76299aa96b2ab6bb"
    )


def test_removing_a_movement_does_not_change_the_vehicles_of_the_others() -> None:
    data = load("scenario.json")
    set_demand(data, "E_W", flow_vph=0, composition=None)
    scenario, case = build(scenario=data)
    without_east = generate_cohort(scenario, case)
    only_north = [v for v in make().vehicles if v.movement_id == "N_S"]
    assert list(without_east.vehicles) == only_north


def test_changing_the_warmup_does_not_change_the_cohort_vehicles() -> None:
    plain = [v for v in make().vehicles if v.in_cohort]
    warmed = [v for v in make(warmup_s=300).vehicles if v.in_cohort]
    assert [(v.vehicle_id, v.depart_s - 300) for v in warmed] == [
        (v.vehicle_id, v.depart_s) for v in plain
    ]


def test_each_movement_draws_its_own_hours() -> None:
    data = load("scenario.json")
    set_demand(data, "E_W", flow_vph=400, composition={"car": 0.9, "bus": 0.1})
    scenario, case = build(scenario=data)
    cohort = generate_cohort(scenario, case)
    north = [v.depart_s for v in cohort.vehicles if v.movement_id == "N_S"]
    east = [v.depart_s for v in cohort.vehicles if v.movement_id == "E_W"]
    assert len(north) == len(east) == 100
    assert north != east


# --- horas de salida ------------------------------------------------------------------------


def test_the_vehicles_come_sorted_by_departure_and_then_by_id() -> None:
    vehicles = make().vehicles
    keys = [(v.depart_s, v.vehicle_id) for v in vehicles]
    assert keys == sorted(keys)


def test_every_hour_is_inside_the_measuring_window_and_on_the_tick() -> None:
    case = load("case.json")
    case["tick_s"] = 0.5
    data = load("scenario.json")
    data["measure_s"] = 900.5
    scenario, parsed = build(case, data)
    vehicles = generate_cohort(scenario, parsed).vehicles
    assert all(0 <= v.depart_s < 900.5 for v in vehicles)
    assert all((v.depart_s * 2) == int(v.depart_s * 2) for v in vehicles)


def test_every_tick_of_a_short_window_gets_vehicles() -> None:
    case = load("case.json")
    case["movements"][0]["flow_domain_vph"]["max"] = 100000
    data = scenario_with({"car": 1.0}, flow=36000)
    data["measure_s"] = 2
    data["request"]["observation_end"] = "2026-10-18T08:00:02-05:00"
    scenario, parsed = build(case, data)
    departs = [v.depart_s for v in generate_cohort(scenario, parsed).vehicles]
    assert len(departs) == 20
    assert set(departs) == {0.0, 1.0}


def test_the_warmup_hours_stay_inside_the_warmup_window() -> None:
    case = load("case.json")
    case["movements"][0]["flow_domain_vph"]["max"] = 100000
    data = scenario_with({"car": 1.0}, flow=36000)
    data["warmup_s"] = 2
    scenario, parsed = build(case, data)
    warm = [v.depart_s for v in generate_cohort(scenario, parsed).vehicles if not v.in_cohort]
    assert len(warm) == 20
    assert set(warm) == {0.0, 1.0}


def test_the_hours_are_clean_decimals_with_a_tick_of_a_tenth() -> None:
    case = load("case.json")
    case["tick_s"] = 0.1
    scenario, parsed = build(case, load("scenario.json"))
    departs = [v.depart_s for v in generate_cohort(scenario, parsed).vehicles]
    assert all(round(depart, 1) == depart for depart in departs)
    assert any(depart != int(depart) for depart in departs)


def test_the_hours_cover_the_whole_window() -> None:
    case = load("case.json")
    case["movements"][0]["flow_domain_vph"]["max"] = 5000
    data = load("scenario.json")
    set_demand(data, "N_S", flow_vph=4000)
    scenario, parsed = build(case, data)
    departs = [
        v.depart_s for v in generate_cohort(scenario, parsed).vehicles if v.movement_id == "N_S"
    ]
    assert len(departs) == 1000
    quarters = Counter(int(d // 225) for d in departs)
    assert set(quarters) == {0, 1, 2, 3}
    assert all(150 < count < 350 for count in quarters.values())
    assert min(departs) < 20
    assert max(departs) > 880


def test_the_classes_are_mixed_along_the_window() -> None:
    buses = [v.depart_s for v in make().vehicles if v.vehicle_id.startswith("N_S.bus")]
    cars = [v.depart_s for v in make().vehicles if v.vehicle_id.startswith("N_S.car")]
    assert min(buses) < max(cars)
    assert max(buses) > min(cars)
    assert buses != sorted(buses, reverse=True)


# --- calentamiento --------------------------------------------------------------------------


def test_the_warmup_generates_demand_that_is_not_part_of_the_cohort() -> None:
    cohort = make(warmup_s=300)
    assert counts_of(cohort, measured=False) == {
        ("N_S", "bus"): 3,  # 400 veh/h x 300 s = 33.3 → 33 (30 + 3 de bus)
        ("N_S", "car"): 30,
        ("E_W", "bus"): 0,
        ("E_W", "car"): 17,  # 200 veh/h x 300 s = 16.7 → 17
    }
    warm = [v for v in cohort.vehicles if not v.in_cohort]
    measured = [v for v in cohort.vehicles if v.in_cohort]
    assert len(warm) == 50
    assert len(measured) == 150
    assert all(0 <= v.depart_s < 300 for v in warm)
    assert all(300 <= v.depart_s < 1200 for v in measured)
    assert cohort.measured == tuple(measured)


def test_the_warmup_and_the_measurement_draw_different_hours() -> None:
    cohort = make(warmup_s=900)
    warm = [v.depart_s for v in cohort.vehicles if not v.in_cohort and v.movement_id == "N_S"]
    measured = [v.depart_s - 900 for v in cohort.vehicles if v.in_cohort and v.movement_id == "N_S"]
    assert len(warm) == len(measured) == 100
    assert warm != measured


def test_the_warmup_vehicles_have_their_own_ids() -> None:
    cohort = make(warmup_s=300)
    warm_ids = [v.vehicle_id for v in cohort.vehicles if not v.in_cohort]
    assert all(".cal." in vehicle_id for vehicle_id in warm_ids)
    assert "N_S.cal.car.1" in warm_ids
    assert not any(".cal." in v.vehicle_id for v in cohort.vehicles if v.in_cohort)


def test_the_warmup_does_not_change_what_was_asked_for_the_cohort() -> None:
    assert counts_of(make(warmup_s=300)) == counts_of(make())


# --- identificadores ------------------------------------------------------------------------


def test_the_ids_are_movement_class_and_a_number_in_departure_order() -> None:
    cohort = make()
    for movement, name in (("N_S", "car"), ("N_S", "bus"), ("E_W", "car")):
        mine = [v for v in cohort.vehicles if (v.movement_id, v.vehicle_class) == (movement, name)]
        assert [v.vehicle_id for v in mine] == [
            f"{movement}.{name}.{n}" for n in range(1, len(mine) + 1)
        ]


def test_the_ids_are_unique() -> None:
    ids = [v.vehicle_id for v in make(warmup_s=300).vehicles]
    assert len(ids) == len(set(ids))


def test_a_vehicle_carries_what_the_list_says_of_it() -> None:
    vehicle = make().vehicles[0]
    assert vehicle == CohortVehicle("N_S.car.1", "N_S", "car", 0.0, True)


# --- límites y seguridad --------------------------------------------------------------------


def test_the_default_limit_is_two_hundred_thousand_vehicles() -> None:
    assert MAX_VEHICLES == 200_000


def test_more_vehicles_than_the_limit_are_refused_before_generating_them() -> None:
    scenario, case = build()
    with pytest.raises(CohortError) as raised:
        generate_cohort(scenario, case, max_vehicles=149)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert "150" in raised.value.message
    assert "149" in raised.value.message


def test_exactly_the_limit_is_allowed() -> None:
    scenario, case = build()
    assert len(generate_cohort(scenario, case, max_vehicles=150).vehicles) == 150


def test_the_warmup_vehicles_count_toward_the_limit() -> None:
    data = load("scenario.json")
    data["warmup_s"] = 300
    scenario, case = build(scenario=data)
    with pytest.raises(CohortError):
        generate_cohort(scenario, case, max_vehicles=199)
    assert len(generate_cohort(scenario, case, max_vehicles=200).vehicles) == 200


def renamed(old: str, new: str) -> tuple[Scenario, Case]:
    """El ejemplo con todas las apariciones del identificador ``old`` cambiadas por ``new``."""
    case_text = json.dumps(load("case.json")).replace(f'"{old}"', json.dumps(new))
    scenario_text = json.dumps(load("scenario.json")).replace(f'"{old}"', json.dumps(new))
    return build(json.loads(case_text), json.loads(scenario_text))


@pytest.mark.parametrize("name", ["N S", "N.S", "N/S", "N;S", 'N"S', "N<S", "Ñ_S"])
def test_a_movement_name_with_unsafe_characters_is_refused(name: str) -> None:
    scenario, case = renamed("N_S", name)
    with pytest.raises(CohortError) as raised:
        generate_cohort(scenario, case)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == "movements[0].id"
    assert "letras, números" in raised.value.message


@pytest.mark.parametrize("name", ["c ar", "c.ar", "c/ar", "c&ar", "cär"])
def test_a_class_name_with_unsafe_characters_is_refused(name: str) -> None:
    scenario, case = renamed("car", name)
    with pytest.raises(CohortError) as raised:
        generate_cohort(scenario, case)
    assert raised.value.field == "vehicle_classes[0]"


def test_names_with_letters_digits_underscore_and_hyphen_are_accepted() -> None:
    scenario, case = renamed("N_S", "M-01_a")
    assert {v.movement_id for v in generate_cohort(scenario, case).vehicles} == {"M-01_a", "E_W"}


def test_a_scenario_that_does_not_fit_the_case_is_refused() -> None:
    data = load("scenario.json")
    data["case_id"] = "OTHER"
    scenario, case = build(scenario=data)
    with pytest.raises(ScenarioInvalidError) as raised:
        generate_cohort(scenario, case)
    assert raised.value.issues[0].rule_id == "SCEN-C01"
