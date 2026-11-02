"""Llegadas de cada escenario en un archivo fijo (DEV11 F3): iguales para todos los comparadores."""

import math
from collections import Counter
from dataclasses import replace

import pytest

from scenario_tools import generated, spec_data, the_case
from semaforo.datos import scenario_demand as module
from semaforo.datos.scenario_demand import (
    DEMAND_HEADER,
    MAX_DEMAND_BYTES,
    MAX_SET_VEHICLES,
    MaterializedDemand,
    ScenarioDemandError,
    demand_path,
    load_demand,
    materialize_all,
    materialize_demand,
    parse_demand,
    render_demand,
)
from semaforo.dominio.case import Artifact
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.scenario import Scenario
from semaforo.simulacion.cohort import MAX_VEHICLES, CohortError, CohortVehicle, generate_cohort
from semaforo.trazabilidad.hashing import sha256_bytes

CASE = the_case()


def vehicles_of(scenario: Scenario) -> tuple[CohortVehicle, ...]:
    return generate_cohort(scenario, CASE).vehicles


def with_data(scenario: Scenario, data: bytes) -> Scenario:
    """El escenario enlazado a ``data`` con la huella correcta."""
    artifact = Artifact(
        artifact_id="x", path=demand_path(scenario.scenario_id), sha256=sha256_bytes(data)
    )
    return scenario.model_copy(update={"demand_artifact": artifact})


def rows(*lines: str) -> bytes:
    return ("\n".join([DEMAND_HEADER, *lines]) + "\n").encode()


def rounded(value: float) -> int:
    """Vehículos de un flujo en 900 s: redondeo al más cercano, la mitad sube."""
    return math.floor(value * 900 / 3600 + 0.5)


# --- formato ----------------------------------------------------------------------------------


def test_the_header_is_the_documented_one() -> None:
    assert DEMAND_HEADER == "vehicle_id,movement_id,vehicle_class,depart_s,in_cohort"


def test_the_text_is_fixed_and_exact() -> None:
    vehicles = (
        CohortVehicle("N_S.cal.bus.1", "N_S", "bus", 0.5, False),
        CohortVehicle("N_S.car.1", "N_S", "car", 12.25, True),
    )
    assert render_demand(vehicles) == (
        b"vehicle_id,movement_id,vehicle_class,depart_s,in_cohort\n"
        b"N_S.cal.bus.1,N_S,bus,0.5,false\n"
        b"N_S.car.1,N_S,car,12.25,true\n"
    )


def test_an_empty_list_is_just_the_header() -> None:
    assert render_demand(()) == (DEMAND_HEADER + "\n").encode()
    assert parse_demand(render_demand(())) == ()


def test_what_is_written_is_read_back_exactly() -> None:
    vehicles = vehicles_of(generated()[0].scenario)
    assert len(vehicles) > 100
    assert parse_demand(render_demand(vehicles)) == vehicles


def test_the_limits_are_the_documented_ones() -> None:
    assert MAX_SET_VEHICLES == 2_000_000
    assert MAX_DEMAND_BYTES == 32 * 1024 * 1024


def test_a_departure_at_zero_is_valid() -> None:
    [vehicle] = parse_demand(rows("A.b.1,A,b,0.0,true"))
    assert vehicle.depart_s == 0.0


def test_the_path_is_inside_the_demand_folder() -> None:
    assert demand_path("FAM_A-V01-S01") == "demanda/FAM_A-V01-S01.csv"


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (b"", "terminar con uno"),
        (b"\xef\xbb\xbf" + rows(), "terminar con uno"),
        (rows().replace(b"\n", b"\r\n"), "terminar con uno"),
        (rows()[:-1], "terminar con uno"),
        (b"\xff\xfe\x00\n", "no es UTF-8"),
        (b"id,movement_id,vehicle_class,depart_s,in_cohort\n", "encabezado"),
        (rows("A.b.1,A,b,1.0"), "5 campos y tiene 4"),
        (rows("A.b.1,A,b,1.0,true,x"), "5 campos y tiene 6"),
        (rows("A,A,b,1.0,true"), "identificador de vehículo"),
        (rows("A b.1,A,b,1.0,true"), "identificador de vehículo"),
        (rows("A.b.1,A B,b,1.0,true"), "movimiento o clase"),
        (rows("A.b.1,A,b/c,1.0,true"), "movimiento o clase"),
        (rows("A.b.1,,b,1.0,true"), "movimiento o clase"),
        (rows("A.b.1,A,b,uno,true"), "no es un número"),
        (rows("A.b.1,A,b,nan,true"), "finito"),
        (rows("A.b.1,A,b,inf,true"), "finito"),
        (rows("A.b.1,A,b,-1.0,true"), "finito"),
        (rows("A.b.1,A,b,1.0,si"), "true o false"),
        (rows("A.b.1,A,b,1.0,True"), "true o false"),
        (rows("A.b.1,A,b,1.0,true", "A.b.1,A,b,2.0,true"), "repetido"),
        (rows("A.b.2,A,b,2.0,true", "A.b.1,A,b,1.0,true"), "por hora de salida"),
        (rows("A.b.2,A,b,1.0,true", "A.b.1,A,b,1.0,true"), "por hora de salida"),
        (rows("A.b.1,A,b,1.0,true", ""), "5 campos y tiene 1"),
    ],
)
def test_a_file_that_is_not_valid_is_rejected_with_its_reason(data: bytes, fragment: str) -> None:
    with pytest.raises(ScenarioDemandError) as raised:
        parse_demand(data)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert fragment in raised.value.message


def test_the_line_of_the_problem_is_reported() -> None:
    data = rows("A.b.1,A,b,1.0,true", "A.b.2,A,b,2.0,true", "A.b.3,A,b,x,true")
    with pytest.raises(ScenarioDemandError) as raised:
        parse_demand(data)
    assert raised.value.field == "línea 4"


def test_a_repeated_vehicle_reports_its_second_line() -> None:
    data = rows("A.b.1,A,b,1.0,true", "A.b.1,A,b,2.0,true")
    with pytest.raises(ScenarioDemandError) as raised:
        parse_demand(data)
    assert raised.value.field == "línea 3"


def test_equal_times_are_ordered_by_identifier() -> None:
    first = parse_demand(rows("A.b.1,A,b,1.0,true", "A.b.2,A,b,1.0,true"))
    assert [v.vehicle_id for v in first] == ["A.b.1", "A.b.2"]


def test_a_file_over_the_size_limit_is_rejected_before_reading_it() -> None:
    with pytest.raises(ScenarioDemandError) as raised:
        parse_demand(b"x" * (MAX_DEMAND_BYTES + 1))
    assert "demasiado grande" in raised.value.message
    parse_demand(rows())  # un archivo mínimo no se queja


def test_a_file_exactly_at_the_size_limit_is_not_called_too_big() -> None:
    with pytest.raises(ScenarioDemandError) as raised:
        parse_demand(b"x" * MAX_DEMAND_BYTES)
    assert "demasiado grande" not in raised.value.message


def test_too_many_vehicles_are_rejected() -> None:
    lines = [f"A.b.{n},A,b,{n}.0,true" for n in range(1, MAX_VEHICLES + 2)]
    with pytest.raises(ScenarioDemandError) as raised:
        parse_demand(rows(*lines))
    assert "máximo" in raised.value.message


def test_the_vehicle_limit_itself_is_allowed() -> None:
    lines = [f"A.b.{n},A,b,{n}.0,true" for n in range(1, MAX_VEHICLES + 1)]
    assert len(parse_demand(rows(*lines))) == MAX_VEHICLES


# --- materializar -----------------------------------------------------------------------------


def test_the_file_holds_exactly_the_cohort_of_the_scenario() -> None:
    for member in generated():
        item = materialize_demand(member, CASE)
        assert parse_demand(item.data) == vehicles_of(member.scenario)


def test_the_scenario_links_its_file_by_path_and_hash() -> None:
    member = generated()[3]
    item = materialize_demand(member, CASE)
    artifact = item.scenario.demand_artifact
    assert artifact is not None
    assert artifact.path == item.path == "demanda/FAM_PUNTA-V02-S02.csv"
    assert artifact.sha256 == sha256_bytes(item.data)
    assert artifact.artifact_id == "FAM_PUNTA-V02-S02-demand"


def test_only_the_artifact_changes_in_the_scenario() -> None:
    member = generated()[0]
    item = materialize_demand(member, CASE)
    assert item.scenario.model_dump(exclude={"demand_artifact"}) == member.scenario.model_dump(
        exclude={"demand_artifact"}
    )
    assert member.scenario.demand_artifact is None


def test_the_counts_are_the_vehicles_of_the_file_and_of_the_cohort() -> None:
    for member in generated():
        item = materialize_demand(member, CASE)
        parsed = parse_demand(item.data)
        assert item.vehicles == len(parsed)
        assert item.measured == sum(1 for v in parsed if v.in_cohort)
        expected = sum(rounded(flow) for flow in member.flows.values())
        assert item.measured == expected


def test_the_warmup_vehicles_are_in_the_file_but_not_in_the_cohort() -> None:
    data = spec_data()
    data["warmup_s"] = 60
    for member in generated(data):
        item = materialize_demand(member, CASE)
        parsed = parse_demand(item.data)
        assert item.vehicles > item.measured > 0
        assert all(v.in_cohort == (v.depart_s >= 60) for v in parsed)


def test_materializing_twice_gives_the_same_bytes() -> None:
    first = [materialize_demand(m, CASE) for m in generated()]
    second = [materialize_demand(m, CASE) for m in generated()]
    assert [i.data for i in first] == [i.data for i in second]
    assert [i.scenario.model_dump_json() for i in first] == [
        i.scenario.model_dump_json() for i in second
    ]


def test_a_scenario_that_already_has_a_file_is_not_materialized_again() -> None:
    original = generated()[0]
    item = materialize_demand(original, CASE)
    with pytest.raises(ScenarioDemandError) as raised:
        materialize_demand(replace(original, scenario=item.scenario), CASE)
    assert "ya tiene un archivo" in raised.value.message


def test_a_scenario_with_too_many_vehicles_names_the_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def too_many(scenario: Scenario, case: object) -> None:
        raise CohortError("el escenario pide 300000 vehículos y el máximo permitido es 200000")

    monkeypatch.setattr(module, "generate_cohort", too_many)
    with pytest.raises(ScenarioDemandError) as raised:
        materialize_demand(generated()[0], CASE)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.message.startswith("FAM_PUNTA-V01-S01: el escenario pide 300000")
    assert raised.value.field == "FAM_PUNTA-V01-S01"


# --- el conjunto entero -----------------------------------------------------------------------


def test_materialize_all_keeps_the_order_of_the_scenarios() -> None:
    members = generated()
    items = materialize_all(members, CASE)
    assert [i.scenario.scenario_id for i in items] == [m.scenario.scenario_id for m in members]


def test_the_total_limit_is_checked_across_the_whole_set() -> None:
    members = generated()
    total = sum(materialize_demand(m, CASE).vehicles for m in members)
    assert len(materialize_all(members, CASE, max_vehicles=total)) == len(members)
    with pytest.raises(ScenarioDemandError) as raised:
        materialize_all(members, CASE, max_vehicles=total - 1)
    assert f"más de {total - 1} vehículos en total" in raised.value.message
    assert raised.value.field == members[-1].scenario.scenario_id


def test_the_total_limit_counts_the_warmup_vehicles_too() -> None:
    data = spec_data()
    data["warmup_s"] = 60
    members = generated(data)
    items = [materialize_demand(m, CASE) for m in members]
    everything = sum(i.vehicles for i in items)
    measured = sum(i.measured for i in items)
    assert everything > measured
    with pytest.raises(ScenarioDemandError):
        materialize_all(members, CASE, max_vehicles=everything - 1)
    assert len(materialize_all(members, CASE, max_vehicles=everything)) == len(members)


def test_the_total_limit_stops_early() -> None:
    members = generated()
    first = materialize_demand(members[0], CASE).vehicles
    with pytest.raises(ScenarioDemandError) as raised:
        materialize_all(members, CASE, max_vehicles=first)
    assert raised.value.field == members[1].scenario.scenario_id


def test_an_empty_list_materializes_to_nothing() -> None:
    assert materialize_all([], CASE) == []


# --- mismas llegadas para todos los comparadores ----------------------------------------------


def test_two_comparators_get_exactly_the_same_vehicles() -> None:
    item = materialize_demand(generated()[0], CASE)
    for_current_plan = load_demand(item.scenario, item.data)
    for_webster = load_demand(item.scenario, bytes(item.data))
    assert for_current_plan == for_webster
    assert for_current_plan == vehicles_of(generated()[0].scenario)


def test_the_loaded_vehicles_are_the_cohort_of_the_original_scenario() -> None:
    for member in generated():
        item = materialize_demand(member, CASE)
        assert load_demand(item.scenario, item.data) == vehicles_of(member.scenario)


def test_repetitions_of_a_variant_share_the_demand_but_not_the_arrivals() -> None:
    first, second = (materialize_demand(m, CASE) for m in generated()[:2])
    assert first.data != second.data

    def totals(item: MaterializedDemand) -> Counter[tuple[str, str]]:
        vehicles = load_demand(item.scenario, item.data)
        return Counter((v.movement_id, v.vehicle_class) for v in vehicles if v.in_cohort)

    assert totals(first) == totals(second)
    times = [v.depart_s for v in load_demand(first.scenario, first.data)]
    other = [v.depart_s for v in load_demand(second.scenario, second.data)]
    assert times != other


def test_other_variants_have_other_demand() -> None:
    first, second = (materialize_demand(m, CASE) for m in (generated()[0], generated()[2]))
    assert first.measured != second.measured or first.data != second.data


def test_a_changed_byte_is_detected() -> None:
    item = materialize_demand(generated()[0], CASE)
    tampered = bytearray(item.data)
    tampered[-3] = ord("9") if tampered[-3] != ord("9") else ord("8")
    with pytest.raises(ScenarioDemandError) as raised:
        load_demand(item.scenario, bytes(tampered))
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    assert raised.value.field == item.path


def test_the_file_of_another_scenario_is_detected() -> None:
    first = materialize_demand(generated()[0], CASE)
    second = materialize_demand(generated()[1], CASE)
    with pytest.raises(ScenarioDemandError) as raised:
        load_demand(first.scenario, second.data)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_scenario_without_a_file_cannot_load_demand() -> None:
    member = generated()[0]
    with pytest.raises(ScenarioDemandError) as raised:
        load_demand(member.scenario, b"")
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert "no tiene archivo de llegadas" in raised.value.message


def test_a_file_with_the_right_hash_but_a_movement_the_scenario_lacks_is_rejected() -> None:
    scenario = generated()[0].scenario
    data = rows("X_Y.car.1,X_Y,car,1.0,true")
    with pytest.raises(ScenarioDemandError) as raised:
        load_demand(with_data(scenario, data), data)
    assert "no tiene el movimiento «X_Y»" in raised.value.message
    assert raised.value.field == "línea 2"


def test_the_cohort_starts_exactly_at_the_end_of_the_warmup() -> None:
    data = spec_data()
    data["warmup_s"] = 60
    scenario = generated(data)[0].scenario
    body = rows("N_S.cal.car.1,N_S,car,59.0,false", "N_S.car.1,N_S,car,60.0,true")
    assert len(load_demand(with_data(scenario, body), body)) == 2


def test_a_cohort_mark_that_does_not_match_the_departure_is_rejected() -> None:
    scenario = generated()[0].scenario
    data = rows("N_S.cal.car.1,N_S,car,1.0,false")
    with pytest.raises(ScenarioDemandError) as raised:
        load_demand(with_data(scenario, data), data)
    assert "marca de cohorte" in raised.value.message


def test_a_file_with_the_right_hash_but_a_bad_format_is_rejected() -> None:
    scenario = generated()[0].scenario
    data = b"hola\n"
    with pytest.raises(ScenarioDemandError) as raised:
        load_demand(with_data(scenario, data), data)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert "encabezado" in raised.value.message


def test_the_hash_is_checked_before_the_format() -> None:
    scenario = generated()[0].scenario
    linked = with_data(scenario, b"otro")
    with pytest.raises(ScenarioDemandError) as raised:
        load_demand(linked, b"hola\n")
    assert raised.value.code is ErrorCode.HASH_MISMATCH
