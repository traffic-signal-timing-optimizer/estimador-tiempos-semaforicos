"""Lectura en flujo de ``tripinfo.xml`` (DEV07 F0, decisión D18)."""

import gzip
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import pytest

from semaforo.caso.errors import CasoError
from semaforo.caso.xml_input import parse_root
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.tripinfo import Trip, read_trips

LIMIT = 64 * 1024 * 1024


def write(tmp_path: Path, body: str, *, compressed: bool = False, root: str = "tripinfos") -> Path:
    text = f'<?xml version="1.0" encoding="UTF-8"?>\n<{root}>\n{body}</{root}>\n'
    path = tmp_path / ("tripinfo.xml.gz" if compressed else "tripinfo.xml")
    data = text.encode("utf-8")
    path.write_bytes(gzip.compress(data) if compressed else data)
    return path


def trip(vehicle_id: str, depart: str = "1.00", arrival: str = "9.00") -> str:
    return f'    <tripinfo id="{vehicle_id}" depart="{depart}" arrival="{arrival}"/>\n'


def peak_of(action: Callable[[], object]) -> int:
    tracemalloc.start()
    try:
        action()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_each_trip_keeps_its_depart_and_arrival(tmp_path: Path) -> None:
    path = write(tmp_path, trip("a", "1.00", "9.50") + trip("b", "2.00", "-1.00"))
    assert read_trips(path, LIMIT) == {"a": Trip(1.0, 9.5), "b": Trip(2.0, -1.0)}


def test_the_trips_keep_the_order_of_the_file(tmp_path: Path) -> None:
    path = write(tmp_path, trip("z") + trip("a") + trip("m"))
    assert list(read_trips(path, LIMIT)) == ["z", "a", "m"]


def test_missing_times_are_none(tmp_path: Path) -> None:
    path = write(tmp_path, '    <tripinfo id="a"/>\n')
    assert read_trips(path, LIMIT) == {"a": Trip(None, None)}


def test_an_empty_list_has_no_trips(tmp_path: Path) -> None:
    assert read_trips(write(tmp_path, ""), LIMIT) == {}


def test_a_compressed_file_is_read(tmp_path: Path) -> None:
    path = write(tmp_path, trip("a") + trip("b"), compressed=True)
    assert list(read_trips(path, LIMIT)) == ["a", "b"]


def test_children_of_a_trip_and_other_elements_are_not_trips(tmp_path: Path) -> None:
    body = (
        '    <tripinfo id="a" depart="1" arrival="2"><emissions CO_abs="1"/></tripinfo>\n'
        '    <personinfo id="p"/>\n'
        '    <grupo><tripinfo id="dentro"/></grupo>\n'
    )
    assert read_trips(write(tmp_path, body), LIMIT) == {"a": Trip(1.0, 2.0)}


# --- rechazos -------------------------------------------------------------------------------


def refused(path: Path, message: str, limit: int = LIMIT) -> CasoError:
    with pytest.raises(CasoError, match=message) as error:
        read_trips(path, limit)
    assert error.value.code is ErrorCode.INPUT_SCHEMA
    assert error.value.field == path.name
    return error.value


def test_a_repeated_vehicle_is_refused(tmp_path: Path) -> None:
    refused(write(tmp_path, trip("a") + trip("a")), "dos viajes del vehículo «a»")


def test_a_trip_without_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CasoError, match="falta el atributo id"):
        read_trips(write(tmp_path, '    <tripinfo depart="1"/>\n'), LIMIT)


def test_a_time_that_is_not_a_number_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CasoError, match="arrival no es un número"):
        read_trips(write(tmp_path, trip("a", arrival="pronto")), LIMIT)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_a_time_that_is_not_finite_is_refused(tmp_path: Path, value: str) -> None:
    with pytest.raises(CasoError, match="no es finito"):
        read_trips(write(tmp_path, trip("a", depart=value)), LIMIT)


def test_another_root_is_refused(tmp_path: Path) -> None:
    refused(write(tmp_path, "", root="statistics"), "la raíz <statistics> no es la esperada")


def test_a_truncated_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "tripinfo.xml"
    path.write_text("<tripinfos>\n" + trip("a")[:20], encoding="utf-8")
    refused(path, "no es un XML válido o seguro")


def test_an_empty_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "tripinfo.xml"
    path.write_bytes(b"")
    refused(path, "no es un XML válido o seguro")


@pytest.mark.parametrize(
    "doctype",
    [
        "<!DOCTYPE tripinfos>",
        '<!DOCTYPE tripinfos [<!ENTITY x "y">]>',
        '<!DOCTYPE tripinfos SYSTEM "fuera.dtd">',
    ],
)
def test_a_dtd_is_refused(tmp_path: Path, doctype: str) -> None:
    path = tmp_path / "tripinfo.xml"
    path.write_text(f"{doctype}\n<tripinfos/>\n", encoding="utf-8")
    refused(path, "no es un XML válido o seguro")


def test_an_entity_bomb_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "tripinfo.xml"
    path.write_text(
        '<!DOCTYPE t [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        '<tripinfos><tripinfo id="&b;"/></tripinfos>',
        encoding="utf-8",
    )
    refused(path, "no es un XML válido o seguro")


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    refused(tmp_path / "tripinfo.xml", "no se puede leer el archivo")


def test_a_broken_gzip_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "tripinfo.xml.gz"
    path.write_bytes(gzip.compress(b"<tripinfos></tripinfos>")[:15])
    refused(path, "no se puede leer el archivo|no es un XML válido")


def test_a_file_over_the_limit_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, trip("a") * 1 + trip("b"))
    size = path.stat().st_size
    assert list(read_trips(path, size)) == ["a", "b"]
    refused(path, f"supera el límite de {size - 1} bytes", limit=size - 1)


def test_the_limit_counts_the_decompressed_bytes(tmp_path: Path) -> None:
    body = "".join(trip(f"v{i}") for i in range(2000))
    path = write(tmp_path, body, compressed=True)
    assert path.stat().st_size < 20_000
    refused(path, "supera el límite de 20000 bytes", limit=20_000)


# --- memoria ----------------------------------------------------------------------------------


def test_reading_in_flow_takes_far_less_memory_than_the_whole_tree(tmp_path: Path) -> None:
    body = "".join(
        f'    <tripinfo id="v{i}" depart="{i}.00" departLane="a_0" departPos="5.10" '
        f'departSpeed="13.89" departDelay="0.00" arrival="{i + 60}.00" arrivalLane="b_0" '
        f'arrivalPos="90.00" arrivalSpeed="13.80" duration="60.00" routeLength="190.00" '
        f'waitingTime="12.00" waitingCount="1" stopTime="0.00" timeLoss="20.00" '
        f'rerouteNo="0" devices="tripinfo_v{i}" vType="car" speedFactor="1.00" vaporized=""/>\n'
        for i in range(20_000)
    )
    path = write(tmp_path, body)
    tree = peak_of(lambda: parse_root(path, LIMIT, frozenset({"tripinfos"}), "tripinfo"))
    flow = peak_of(lambda: read_trips(path, LIMIT))
    assert flow < tree / 4
