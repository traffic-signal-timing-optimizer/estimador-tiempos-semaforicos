"""Lectura de los archivos de una corrida para la base, sin base de datos (DEV31 F3)."""

import pytest

from prepared_inputs import DURATIONS, json_of
from semaforo.bd.carga import corridas, crudo, planes
from semaforo.bd.carga.modelo import CargaError
from semaforo.dominio.case import parse_case

LOG = "\n".join(
    [
        "Loading net-file from 'inputs/red.net.xml.gz' ... done (31ms).",
        "Warning: Missing yellow phase in tlLogic 'J1', program '0' for tl-index 23 when "
        "switching to phase 4.",
        "Warning: Teleporting vehicle 'M03.passenger.29'; waited too long (jam), "
        "lane='279893869#6_0', time=1488.00.",
        "Warning: Vehicle 'M03.passenger.29' ends teleporting on edge '1290849747#3', "
        "time=1488.00.",
        "Warning: Teleporting vehicle 'A'; waited too long (wrong lane), lane='x_1', time=10.00.",
        "Warning: Teleporting vehicle 'B'; junction collision with vehicle 'C', lane=':J_3_0', "
        "gap=-1.39, latGap=0.48, time=1555.00, stage=move.",
        "Error: algo salió mal",
        "Simulation ended at time: 2100.00",
    ]
)


def test_the_log_gives_one_event_per_warning_or_error_with_its_line() -> None:
    events = corridas.log_events(LOG)
    assert [(e["orden"], e["tipo"], e["subtipo"]) for e in events] == [
        (2, "warning", None),
        (3, "teleport", "jam"),
        (4, "warning", None),
        (5, "teleport", "wrong_lane"),
        (6, "collision", "move"),
        (7, "error", None),
    ]
    jam = events[1]
    assert (jam["vehiculo_id"], jam["carril_id"], jam["tiempo_s"]) == (
        "M03.passenger.29",
        "279893869#6_0",
        1488.0,
    )
    crash = events[4]
    assert (crash["vehiculo_id"], crash["otro_vehiculo_id"]) == ("B", "C")
    assert all(e["texto"] == LOG.splitlines()[int(str(e["orden"])) - 1] for e in events)


def test_a_line_without_time_keeps_it_empty_never_zero() -> None:
    (error,) = [e for e in corridas.log_events(LOG) if e["tipo"] == "error"]
    assert error["tiempo_s"] is None


def test_the_cohort_table_is_read_without_the_excel_protection() -> None:
    data = (
        "﻿vehicle_id;movement_id;vehicle_class;en_cohorte;depart_programada_s;estado;"
        'entrada_real_s;llegada_s\r\n"=""M01.cal.passenger.1""";"=""M01""";"=""passenger""";'
        'no;0;finished;0;138\r\n"=""M02.bus.3""";"=""M02""";"=""bus""";sí;301.5;not_inserted;;\r\n'
    ).encode()
    rows = corridas.cohort_rows(data)
    assert rows[0] == {
        "vehiculo_id": "M01.cal.passenger.1",
        "movimiento_id": "M01",
        "clase_id": "passenger",
        "en_cohorte": False,
        "salida_programada_s": 0.0,
        "estado": "finished",
        "entrada_real_s": 0.0,
        "llegada_s": 138.0,
    }
    assert rows[1]["en_cohorte"] is True
    assert (rows[1]["entrada_real_s"], rows[1]["llegada_s"]) == (None, None)


def test_a_cohort_table_with_another_header_is_refused() -> None:
    with pytest.raises(CargaError, match="cabecera"):
        corridas.cohort_rows(b"id;movimiento\n")


def test_sumo_minus_one_means_missing_and_empty_vaporized_means_no() -> None:
    xml = (
        b'<tripinfos><tripinfo id="a" depart="-1.00" departLane="" departDelay="300.00" '
        b'arrival="-1.00" arrivalLane="" duration="-1.00" routeLength="10.0" waitingTime="0" '
        b'waitingCount="0" stopTime="0" timeLoss="5.5" vType="passenger" speedFactor="1.1" '
        b'vaporized=""/><tripinfo id="b" duration="3" vaporized="end"/></tripinfos>'
    )
    trips = corridas._trips(xml)  # pyright: ignore[reportPrivateUsage]
    first = trips["a"]
    assert (first["duracion_s"], first["carril_salida"], first["carril_llegada"]) == (
        None,
        None,
        None,
    )
    assert (first["demora_salida_s"], first["perdida_tiempo_s"]) == (300.0, 5.5)
    assert first["vaporizado"] is False
    assert trips["b"]["vaporizado"] is True
    assert trips["b"]["recorrido_m"] is None


def test_a_tripinfo_with_an_entity_is_refused() -> None:
    xml = b'<!DOCTYPE t [<!ENTITY x "y">]><tripinfos><tripinfo id="&x;"/></tripinfos>'
    with pytest.raises(Exception):  # noqa: B017  (defusedxml rechaza el DTD)
        corridas._trips(xml)  # pyright: ignore[reportPrivateUsage]


def test_the_environment_row_translates_the_cloud_and_explains_a_missing_commit() -> None:
    old = corridas.entorno_row({"sumo": "1.27.1", "python": "3.12.3", "os": "Windows 11"})
    assert old["commit_codigo"] is None
    assert old["motivo_sin_commit"] is not None
    assert (old["ubicacion"], old["nucleos"], old["memoria_gb"]) == (None, None, None)
    cloud = corridas.entorno_row(
        {
            "python": "3.12.3",
            "os": "Linux",
            "commit": "abc",
            "code_modified": "false",
            "location": "cloud",
            "cloud_provider": "Nube Ejemplo",
            "cpu_cores": "8",
            "memory_gb": "31.4",
        }
    )
    assert (cloud["ubicacion"], cloud["proveedor_nube"]) == ("nube", "Nube Ejemplo")
    assert (cloud["codigo_modificado"], cloud["nucleos"], cloud["memoria_gb"]) == (False, 8, 31.4)
    assert cloud["motivo_sin_commit"] is None
    assert cloud["entorno_id"] != old["entorno_id"]
    assert (
        corridas.entorno_row({"python": "3.12.3", "os": "Linux"})["entorno_id"]
        == (corridas.entorno_row({"os": "Linux", "python": "3.12.3"})["entorno_id"])
    )


def test_a_plan_is_identified_by_its_durations_in_the_case_order() -> None:
    case = parse_case(json_of("case.json"))
    same = dict(reversed(list(DURATIONS.items())))
    assert planes.plan_id(case, DURATIONS) == planes.plan_id(case, same)
    longer = {**DURATIONS, "s1": DURATIONS["s1"] + 1}
    assert planes.plan_id(case, longer) != planes.plan_id(case, DURATIONS)
    with pytest.raises(CargaError, match="tramos del caso"):
        planes.plan_id(case, {"s1": 30.0})


def test_a_declared_cycle_must_be_the_sum_of_the_slots() -> None:
    from semaforo.bd.carga.modelo import FileRecord, Unit  # noqa: PLC0415

    case = parse_case(json_of("case.json"))
    source = FileRecord("datos", "x.json", "other", "0" * 64, 1)
    unit = Unit(key="u", kind="test")
    planes.add_plan(unit, case, DURATIONS, source, cycle_s=sum(DURATIONS.values()))
    assert len(unit.rows["simulacion.plan_tramos"]) == len(DURATIONS)
    with pytest.raises(CargaError, match="suma"):
        planes.add_plan(unit, case, DURATIONS, source, cycle_s=1.0)


def test_metric_columns_without_metrics_are_all_empty() -> None:
    empty = corridas.metric_columns(None)
    assert set(empty) == set(corridas.METRIC_COLUMNS)
    assert all(value is None for value in empty.values())


def test_raw_json_helpers_say_where_the_problem_is() -> None:
    assert crudo.mapping(crudo.loads(b'{"a": 1}', "x"), "x") == {"a": 1}
    with pytest.raises(CargaError, match="JSON"):
        crudo.loads(b"{no", "x")
    with pytest.raises(CargaError, match="entero"):
        crudo.integer(True, "x")
    with pytest.raises(CargaError, match="número"):
        crudo.number("1", "x")
    assert crudo.optional_number(None, "x") is None
    assert crudo.number(3, "x") == 3.0
