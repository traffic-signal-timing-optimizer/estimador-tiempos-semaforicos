"""Conciliación de la cohorte con los viajes de SUMO (DEV06 F3, D20, QA25)."""

import csv
import gzip
import io
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.caso.errors import CasoError
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion import reconcile as reconcile_module
from semaforo.simulacion.prepare import COHORT_FILE, MANIFEST_FILE, publish_inputs
from semaforo.simulacion.reconcile import (
    Reconciliation,
    ReconciliationError,
    reconcile,
    reconciliation_csv,
)
from semaforo.trazabilidad.hashing import sha256_bytes

HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n<tripinfos>\n'
FOOTER = "</tripinfos>\n"
CAR = "N_S.car.1"
BUS = "N_S.bus.1"
WARMUP = "N_S.cal.car.1"


def trip(vehicle_id: str, depart: float, arrival: float) -> str:
    return (
        f'    <tripinfo id="{vehicle_id}" depart="{depart:.2f}" departLane="demo_N_0" '
        f'arrival="{arrival:.2f}" arrivalLane="demo_S_0"/>\n'
    )


def write_trips(path: Path, *trips: str) -> Path:
    path.write_text(HEADER + "".join(trips) + FOOTER, encoding="utf-8")
    return path


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Carpeta de entradas del ejemplo: 160 vehículos, 10 de calentamiento y 150 de cohorte."""
    return publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)


@pytest.fixture
def editable(folder: Path, tmp_path: Path) -> Path:
    """Copia de la carpeta publicada, que sí se puede cambiar."""
    copy = tmp_path / "copia"
    shutil.copytree(folder, copy)
    for item in copy.iterdir():
        item.chmod(0o666)
    return copy


def cohort_rows(folder: Path) -> list[list[str]]:
    text = (folder / COHORT_FILE).read_text(encoding="utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))


def rewrite_cohort(folder: Path, rows: list[list[str]], *, fix_hash: bool = True) -> None:
    """Escribe la planilla con otras filas y, por defecto, actualiza su huella en el manifiesto."""
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";", lineterminator="\r\n").writerows(rows)
    data = buffer.getvalue().encode("utf-8-sig")
    (folder / COHORT_FILE).write_bytes(data)
    if fix_hash:
        change_manifest(
            folder, lambda manifest: manifest["files"].update({COHORT_FILE: sha256_bytes(data)})
        )


def change_manifest(folder: Path, change: Callable[[dict[str, Any]], None]) -> None:
    path = folder / MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def all_trips(folder: Path) -> list[str]:
    """Un viaje terminado por cada vehículo pedido."""
    return [
        trip(row[0][2:-1], float(row[5]), float(row[5]) + 30) for row in cohort_rows(folder)[1:]
    ]


def reconcile_with(folder: Path, tmp_path: Path, *trips: str) -> Reconciliation:
    return reconcile(folder, write_trips(tmp_path / "tripinfo.xml", *trips))


def status_of(result: Reconciliation, vehicle_id: str) -> str:
    return next(v.status for v in result.outcomes if v.vehicle_id == vehicle_id)


# --- los tres estados -----------------------------------------------------------------------


def test_every_vehicle_that_finished_is_finished(folder: Path, tmp_path: Path) -> None:
    result = reconcile_with(folder, tmp_path, *all_trips(folder))
    assert (result.requested, result.finished, result.unfinished, result.not_inserted) == (
        150,
        150,
        0,
        0,
    )
    assert len(result.outcomes) == 160


def test_a_vehicle_with_negative_arrival_is_unfinished(folder: Path, tmp_path: Path) -> None:
    trips = [t for t in all_trips(folder) if f'"{CAR}"' not in t] + [trip(CAR, 61.0, -1.0)]
    result = reconcile_with(folder, tmp_path, *trips)
    assert status_of(result, CAR) == "unfinished"
    outcome = next(v for v in result.outcomes if v.vehicle_id == CAR)
    assert (outcome.inserted_s, outcome.arrival_s) == (61.0, None)
    assert (result.finished, result.unfinished, result.not_inserted) == (149, 1, 0)


def test_a_vehicle_without_trip_is_not_inserted(folder: Path, tmp_path: Path) -> None:
    result = reconcile_with(
        folder, tmp_path, *[t for t in all_trips(folder) if f'"{CAR}"' not in t]
    )
    assert status_of(result, CAR) == "not_inserted"
    outcome = next(v for v in result.outcomes if v.vehicle_id == CAR)
    assert (outcome.inserted_s, outcome.arrival_s) == (None, None)
    assert (result.finished, result.unfinished, result.not_inserted) == (149, 0, 1)


def test_arrival_zero_counts_as_finished(folder: Path, tmp_path: Path) -> None:
    trips = [t for t in all_trips(folder) if f'"{CAR}"' not in t] + [trip(CAR, 0.0, 0.0)]
    assert status_of(reconcile_with(folder, tmp_path, *trips), CAR) == "finished"


def test_a_run_with_all_three_states_keeps_the_requested_number(
    folder: Path, tmp_path: Path
) -> None:
    trips = [t for t in all_trips(folder) if f'"{CAR}"' not in t and f'"{BUS}"' not in t]
    trips.append(trip(CAR, 61.0, -1.0))
    result = reconcile_with(folder, tmp_path, *trips)
    assert (result.finished, result.unfinished, result.not_inserted) == (148, 1, 1)
    assert result.finished + result.unfinished + result.not_inserted == result.requested == 150
    for count in result.counts:
        assert count.requested == count.finished + count.unfinished + count.not_inserted


def test_counts_split_each_state_by_movement_and_class_in_sorted_order(
    folder: Path, tmp_path: Path
) -> None:
    trips = [t for t in all_trips(folder) if f'"{CAR}"' not in t and f'"{BUS}"' not in t]
    result = reconcile_with(folder, tmp_path, *trips, trip(CAR, 61.0, -1.0))
    expected: dict[tuple[str, str], dict[str, int]] = {}
    for outcome in result.outcomes:
        if outcome.in_cohort:
            states = expected.setdefault(
                (outcome.movement_id, outcome.vehicle_class),
                {"finished": 0, "unfinished": 0, "not_inserted": 0},
            )
            states[outcome.status] += 1
    got = {
        (count.movement_id, count.vehicle_class): {
            "finished": count.finished,
            "unfinished": count.unfinished,
            "not_inserted": count.not_inserted,
        }
        for count in result.counts
    }
    assert got == expected
    assert got[("N_S", "car")]["unfinished"] == 1
    assert got[("N_S", "bus")]["not_inserted"] == 1
    keys = [(count.movement_id, count.vehicle_class) for count in result.counts]
    assert keys == sorted(keys)


def test_warmup_vehicles_are_recorded_but_not_counted(folder: Path, tmp_path: Path) -> None:
    trips = [t for t in all_trips(folder) if f'"{WARMUP}"' not in t]
    result = reconcile_with(folder, tmp_path, *trips)
    outcome = next(v for v in result.outcomes if v.vehicle_id == WARMUP)
    assert (outcome.in_cohort, outcome.status) == (False, "not_inserted")
    assert (result.requested, result.not_inserted) == (150, 0)


def test_counts_match_the_manifest_by_movement_and_class(folder: Path, tmp_path: Path) -> None:
    result = reconcile_with(folder, tmp_path, *all_trips(folder))
    declared = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))["vehicles"]
    assert {(c.movement_id, c.vehicle_class): c.requested for c in result.counts} == {
        (c["movement_id"], c["vehicle_class"]): c["measured"]
        for c in declared["counts"]
        if c["measured"]
    }
    assert sum(c.requested for c in result.counts) == result.requested == declared["cohort"]


def test_the_scheduled_time_comes_from_the_sheet(folder: Path, tmp_path: Path) -> None:
    result = reconcile_with(folder, tmp_path, *all_trips(folder))
    assert next(v for v in result.outcomes if v.vehicle_id == WARMUP).scheduled_s == 7.0


def test_the_result_does_not_change_the_inputs(folder: Path, tmp_path: Path) -> None:
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    reconcile_with(folder, tmp_path, *all_trips(folder))
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


def test_the_same_inputs_give_the_same_table(folder: Path, tmp_path: Path) -> None:
    trips = all_trips(folder)
    first = reconciliation_csv(reconcile_with(folder, tmp_path, *trips))
    second = reconciliation_csv(reconcile_with(folder, tmp_path, *trips))
    assert first == second


# --- tabla de cohorte -----------------------------------------------------------------------


def test_the_table_has_the_team_sheet_format(folder: Path, tmp_path: Path) -> None:
    trips = [t for t in all_trips(folder) if f'"{CAR}"' not in t] + [trip(CAR, 61.0, -1.0)]
    data = reconciliation_csv(reconcile_with(folder, tmp_path, *trips))
    assert data.startswith(b"\xef\xbb\xbfvehicle_id;")
    text = data.decode("utf-8-sig")
    assert text.endswith("\r\n")
    assert "\n" not in text.replace("\r\n", "")
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    assert rows[0] == [
        "vehicle_id",
        "movement_id",
        "vehicle_class",
        "en_cohorte",
        "depart_programada_s",
        "estado",
        "entrada_real_s",
        "llegada_s",
    ]
    assert len(rows) == 161
    by_id = {row[0]: row for row in rows[1:]}
    assert by_id[f'="{CAR}"'][3:] == ["sí", "60", "unfinished", "61", ""]
    assert by_id[f'="{WARMUP}"'][3:] == ["no", "7", "finished", "7", "37"]


def test_the_table_leaves_blank_what_did_not_happen(folder: Path, tmp_path: Path) -> None:
    result = reconcile_with(
        folder, tmp_path, *[t for t in all_trips(folder) if f'"{CAR}"' not in t]
    )
    rows = list(
        csv.reader(io.StringIO(reconciliation_csv(result).decode("utf-8-sig")), delimiter=";")
    )
    assert next(r for r in rows if r[0] == f'="{CAR}"')[5:] == ["not_inserted", "", ""]


# --- planilla alterada ----------------------------------------------------------------------


def test_a_changed_sheet_is_refused_by_its_hash(editable: Path, tmp_path: Path) -> None:
    with (editable / COHORT_FILE).open("ab") as handle:
        handle.write(b"x")
    with pytest.raises(ReconciliationError) as error:
        reconcile_with(editable, tmp_path)
    assert error.value.code is ErrorCode.HASH_MISMATCH
    assert error.value.field == COHORT_FILE


def test_a_missing_vehicle_is_refused_even_with_a_matching_hash(
    editable: Path, tmp_path: Path
) -> None:
    rows = cohort_rows(editable)
    rewrite_cohort(editable, rows[:-1])
    with pytest.raises(ReconciliationError, match="159 vehículos") as error:
        reconcile_with(editable, tmp_path)
    assert error.value.code is ErrorCode.HASH_MISMATCH


def test_a_vehicle_moved_to_another_class_is_refused(editable: Path, tmp_path: Path) -> None:
    rows = cohort_rows(editable)
    rows[-1][2] = '="bus"'
    rewrite_cohort(editable, rows)
    with pytest.raises(ReconciliationError, match="por movimiento y clase") as error:
        reconcile_with(editable, tmp_path)
    assert error.value.code is ErrorCode.HASH_MISMATCH


def test_a_warmup_vehicle_turned_into_cohort_is_refused(editable: Path, tmp_path: Path) -> None:
    rows = cohort_rows(editable)
    rows[1][7] = "sí"
    rewrite_cohort(editable, rows)
    with pytest.raises(ReconciliationError, match="151 de cohorte") as error:
        reconcile_with(editable, tmp_path)
    assert error.value.code is ErrorCode.HASH_MISMATCH


def test_a_manifest_with_other_totals_is_refused(editable: Path, tmp_path: Path) -> None:
    change_manifest(editable, lambda manifest: manifest["vehicles"].update({"total": 999}))
    with pytest.raises(ReconciliationError, match="declara 999") as error:
        reconcile_with(editable, tmp_path)
    assert error.value.code is ErrorCode.HASH_MISMATCH


@pytest.mark.parametrize(
    ("cell", "value", "message"),
    [
        ((0, 0), "id", "encabezado"),
        ((1, 0), "N_S.cal.car.1", "formato esperado"),
        ((1, 0), '="N_S;rm"', "caracteres no permitidos"),
        ((1, 0), '=""', "caracteres no permitidos"),
        ((1, 0), '="N_S', "formato esperado"),
        ((1, 0), 'N_S"', "formato esperado"),
        ((1, 0), '="=cmd"', "caracteres no permitidos"),
        ((1, 1), '="N S"', "caracteres no permitidos"),
        ((1, 2), '="a/b"', "caracteres no permitidos"),
        ((1, 7), "tal vez", "en_cohorte"),
        ((1, 5), "pronto", "depart_s"),
    ],
)
def test_a_malformed_sheet_is_refused_even_with_a_matching_hash(
    editable: Path, tmp_path: Path, cell: tuple[int, int], value: str, message: str
) -> None:
    rows = cohort_rows(editable)
    rows[cell[0]][cell[1]] = value
    rewrite_cohort(editable, rows)
    with pytest.raises(ReconciliationError, match=message) as error:
        reconcile_with(editable, tmp_path)
    assert error.value.code is ErrorCode.INPUT_SCHEMA


def test_a_row_with_a_missing_column_is_refused(editable: Path, tmp_path: Path) -> None:
    rows = cohort_rows(editable)
    rows[1].pop()
    rewrite_cohort(editable, rows)
    with pytest.raises(ReconciliationError, match="línea 2: tiene 8 columnas") as error:
        reconcile_with(editable, tmp_path)
    assert error.value.code is ErrorCode.INPUT_SCHEMA


def test_a_repeated_vehicle_in_the_sheet_is_refused(editable: Path, tmp_path: Path) -> None:
    rows = cohort_rows(editable)
    rows[1][0] = rows[2][0]
    rewrite_cohort(editable, rows)
    with pytest.raises(
        ReconciliationError, match=r"repite el vehículo «N_S\.cal\.car\.2»"
    ) as error:
        reconcile_with(editable, tmp_path)
    assert error.value.code is ErrorCode.INPUT_SCHEMA


def test_an_empty_sheet_is_refused(editable: Path, tmp_path: Path) -> None:
    rewrite_cohort(editable, [])
    with pytest.raises(ReconciliationError, match="encabezado"):
        reconcile_with(editable, tmp_path)


def test_a_missing_sheet_is_refused(editable: Path, tmp_path: Path) -> None:
    (editable / COHORT_FILE).unlink()
    with pytest.raises(CasoError, match="no existe") as error:
        reconcile_with(editable, tmp_path)
    assert error.value.code is ErrorCode.INPUT_SCHEMA


def test_an_oversized_sheet_is_refused(
    folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reconcile_module, "MAX_COHORT_BYTES", 100)
    with pytest.raises(CasoError, match="supera el límite"):
        reconcile_with(folder, tmp_path)


def test_a_broken_manifest_is_refused(editable: Path, tmp_path: Path) -> None:
    change_manifest(editable, lambda manifest: manifest.pop("vehicles"))
    with pytest.raises(ReconciliationError, match="manifiesto") as error:
        reconcile_with(editable, tmp_path)
    assert (error.value.code, error.value.field) == (ErrorCode.INPUT_SCHEMA, MANIFEST_FILE)


def test_a_missing_manifest_is_refused(editable: Path, tmp_path: Path) -> None:
    (editable / MANIFEST_FILE).unlink()
    with pytest.raises(CasoError, match="manifiesto"):
        reconcile_with(editable, tmp_path)


def test_a_sheet_that_is_a_link_is_refused(editable: Path, tmp_path: Path) -> None:
    (editable / COHORT_FILE).rename(tmp_path / "otra.csv")
    try:
        (editable / COHORT_FILE).symlink_to(tmp_path / "otra.csv")
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    with pytest.raises(CasoError) as error:
        reconcile_with(editable, tmp_path)
    assert error.value.code is ErrorCode.PATH_NOT_ALLOWED


# --- viajes de SUMO inválidos ---------------------------------------------------------------


def test_a_repeated_trip_is_refused(folder: Path, tmp_path: Path) -> None:
    with pytest.raises(ReconciliationError, match="dos viajes") as error:
        reconcile_with(folder, tmp_path, trip(CAR, 61.0, 90.0), trip(CAR, 62.0, 91.0))
    assert error.value.code is ErrorCode.OUTPUT_INVALID
    assert error.value.field == "tripinfo.xml"


def test_a_trip_of_a_vehicle_that_was_not_requested_is_refused(
    folder: Path, tmp_path: Path
) -> None:
    with pytest.raises(ReconciliationError, match=r"1 viajes.*«intruso»") as error:
        reconcile_with(folder, tmp_path, trip("intruso", 61.0, 90.0))
    assert error.value.code is ErrorCode.OUTPUT_INVALID


def test_the_unknown_trips_are_counted(folder: Path, tmp_path: Path) -> None:
    with pytest.raises(ReconciliationError, match=r"2 viajes.*«a»"):
        reconcile_with(folder, tmp_path, trip("b", 1.0, 2.0), trip("a", 1.0, 2.0))


def test_a_trip_without_an_id_is_refused(folder: Path, tmp_path: Path) -> None:
    with pytest.raises(ReconciliationError, match="falta el atributo id") as error:
        reconcile_with(folder, tmp_path, '    <tripinfo depart="1.00" arrival="2.00"/>\n')
    assert error.value.code is ErrorCode.OUTPUT_INVALID


def test_a_trip_with_a_non_numeric_arrival_is_refused(folder: Path, tmp_path: Path) -> None:
    with pytest.raises(ReconciliationError, match="arrival no es un número"):
        reconcile_with(folder, tmp_path, f'    <tripinfo id="{CAR}" depart="1.00" arrival="x"/>\n')


def test_a_trip_without_arrival_is_not_finished(folder: Path, tmp_path: Path) -> None:
    result = reconcile_with(folder, tmp_path, f'    <tripinfo id="{CAR}" depart="61.00"/>\n')
    assert status_of(result, CAR) == "unfinished"


def test_an_xml_with_a_dtd_is_refused(folder: Path, tmp_path: Path) -> None:
    path = tmp_path / "tripinfo.xml"
    path.write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE tripinfos [<!ENTITY x "boom">]>\n<tripinfos/>\n',
        encoding="utf-8",
    )
    with pytest.raises(ReconciliationError, match="XML válido o seguro") as error:
        reconcile(folder, path)
    assert error.value.code is ErrorCode.OUTPUT_INVALID


def test_an_xml_with_nested_entities_is_refused(folder: Path, tmp_path: Path) -> None:
    path = tmp_path / "tripinfo.xml"
    path.write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE tripinfos [<!ENTITY a "aaaa">'
        '<!ENTITY b "&a;&a;&a;&a;">]>\n<tripinfos><tripinfo id="&b;"/></tripinfos>\n',
        encoding="utf-8",
    )
    with pytest.raises(ReconciliationError, match="XML válido o seguro"):
        reconcile(folder, path)


def test_a_truncated_xml_is_refused(folder: Path, tmp_path: Path) -> None:
    path = tmp_path / "tripinfo.xml"
    path.write_text(HEADER + trip(CAR, 1.0, 2.0)[:30], encoding="utf-8")
    with pytest.raises(ReconciliationError, match="XML válido o seguro"):
        reconcile(folder, path)


def test_an_xml_with_another_root_is_refused(folder: Path, tmp_path: Path) -> None:
    path = tmp_path / "tripinfo.xml"
    path.write_text("<statistics/>", encoding="utf-8")
    with pytest.raises(ReconciliationError, match="la raíz <statistics>"):
        reconcile(folder, path)


def test_a_missing_tripinfo_is_refused(folder: Path, tmp_path: Path) -> None:
    with pytest.raises(ReconciliationError) as error:
        reconcile(folder, tmp_path / "no_existe.xml")
    assert error.value.code is ErrorCode.OUTPUT_INVALID


def test_an_oversized_tripinfo_is_refused(
    folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "tripinfo.xml"
    path.write_bytes(gzip.compress(HEADER.encode() + b" " * 5000 + FOOTER.encode()))
    monkeypatch.setattr(reconcile_module, "MAX_TRIPINFO_BYTES", 1000)
    with pytest.raises(ReconciliationError, match="supera el límite"):
        reconcile(folder, path)


def test_a_tripinfo_that_is_a_link_is_refused(folder: Path, tmp_path: Path) -> None:
    real = write_trips(tmp_path / "real.xml")
    link = tmp_path / "tripinfo.xml"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    with pytest.raises(CasoError) as error:
        reconcile(folder, link)
    assert error.value.code is ErrorCode.PATH_NOT_ALLOWED


def test_an_unfinished_vehicle_that_arrives_later_is_unfinished_only_if_negative(
    folder: Path, tmp_path: Path
) -> None:
    result = reconcile_with(folder, tmp_path, trip(CAR, 61.0, -0.01), trip(BUS, 62.0, 0.0))
    assert (status_of(result, CAR), status_of(result, BUS)) == ("unfinished", "finished")
