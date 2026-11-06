"""Réplica de una corrida: reglas de comparación y reporte publicado, sin SUMO (DEV08 F3, D8 a D10).

Las corridas se fabrican con ``RunWriter``: salidas con la forma de las de SUMO, para probar cada
regla sin depender de una simulación.
"""

import gzip
import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from semaforo.app.integrity import verify_workspace
from semaforo.app.replica import MANIFEST_FILE, REPLICAS, REPORT_FILE, read_replica, replicate
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion import replica as replica_module
from semaforo.simulacion.replica import ReplicaReport, Tolerance, compare_runs
from semaforo.trazabilidad.fs import publish_files, remove_tree
from semaforo.trazabilidad.manifest import Error as RunError
from semaforo.trazabilidad.store import RunSpec, RunWriter
from workspace_tools import tamper, writable

NOW = datetime(2026, 11, 1, 23, 0, tzinfo=UTC)
GENERATED = "<!-- generated on {stamp} by Eclipse SUMO sumo 1.27.1 -->"
TRIPINFO = """<?xml version="1.0" encoding="UTF-8"?>
{generated}
<tripinfos>
    <tripinfo id="v1" depart="1.00" arrival="{arrival}" duration="10.50" vType="car"/>
    <tripinfo id="v2" depart="2.00" arrival="20.00" duration="18.00" vType="{vtype}"/>
</tripinfos>
"""
STATISTICS = """<?xml version="1.0" encoding="UTF-8"?>
{generated}
<statistics>
    <performance clockBegin="{clock}" duration="{clock}"/>
    <vehicles loaded="2" inserted="2" running="0" waiting="{waiting}"/>
</statistics>
"""
SHEET = "id;estado\r\nv1;finished\r\nv2;finished\r\n"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clock() -> datetime:
    return NOW


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "datos"
    yield root
    remove_tree(root)


def outputs(**changes: str) -> dict[str, str]:
    values = {
        "stamp": "2026-11-01T10:00:00",
        "arrival": "11.50",
        "vtype": "car",
        "clock": "1",
        "waiting": "0",
    }
    values.update(changes)
    generated = GENERATED.format(stamp=values["stamp"])
    return {
        "tripinfo.xml": TRIPINFO.format(
            generated=generated, arrival=values["arrival"], vtype=values["vtype"]
        ),
        "statistics.xml": STATISTICS.format(
            generated=generated, clock=values["clock"], waiting=values["waiting"]
        ),
        "cohorte_conciliada.csv": SHEET,
        "tiempos.json": '{"duration_s": ' + values["clock"] + "}",
        "sumo.log": "Duration: " + values["clock"],
    }


def run(  # noqa: PLR0913  (los opcionales son de solo palabra clave)
    workspace: Path,
    files: Mapping[str, str],
    *,
    seed: int = 7,
    case_id: str = "CASO_A",
    inputs: Mapping[str, str] | None = None,
    status: str = "succeeded",
    binary: Mapping[str, bytes] | None = None,
) -> str:
    spec = RunSpec(
        kind="simulation", case_id=case_id, case_version="1.0.0", scenario_id="ESC_1", seed=seed
    )
    with RunWriter(workspace / "ejecuciones", spec, clock=clock) as writer:
        for name, text in (inputs or {"demo.sumocfg": "<configuration/>"}).items():
            source = workspace.parent / f"fuente-{name}"
            source.write_text(text, encoding="utf-8")
            writer.add_input(source, name)
        for name, text in files.items():
            writer.output_path(name).write_text(text, encoding="utf-8")
        for name, data in (binary or {}).items():
            writer.output_path(name).write_bytes(data)
        failed = status == "failed"
        manifest = writer.publish(
            status="failed" if failed else "succeeded",
            command=["sumo"],
            environment={"sumo": "1.27.1"},
            exit_code=1 if failed else 0,
            error=RunError(code="SIM_FAILED", field=None, message="falló") if failed else None,
        )
    return manifest.run_id


def verdict(
    workspace: Path,
    a_files: Mapping[str, str],
    b_files: Mapping[str, str],
    *,
    tolerance: Tolerance | None = None,
) -> ReplicaReport:
    a, b = run(workspace, a_files), run(workspace, b_files)
    return compare_runs(workspace / "ejecuciones", a, b, created_at=NOW, tolerance=tolerance)


# --- lo que no cuenta -------------------------------------------------------------------------


def test_two_identical_runs_are_equivalent(workspace: Path) -> None:
    report = verdict(workspace, outputs(), outputs())
    assert (report.verdict, report.reasons, report.inputs_equal) == ("equivalent", [], True)
    rules = {item.path: (item.rule, item.equal) for item in report.files}
    assert rules == {
        "outputs/cohorte_conciliada.csv": ("exact", True),
        "outputs/statistics.xml": ("xml", True),
        "outputs/sumo.log": ("excluded", None),
        "outputs/tiempos.json": ("excluded", None),
        "outputs/tripinfo.xml": ("xml", True),
    }


def test_the_generation_time_written_by_sumo_does_not_count(workspace: Path) -> None:
    report = verdict(
        workspace, outputs(stamp="2026-11-01T10:00:00"), outputs(stamp="2026-11-01T10:00:09")
    )
    assert report.verdict == "equivalent"


def test_the_clock_times_of_the_run_do_not_count(workspace: Path) -> None:
    report = verdict(
        workspace, outputs(clock="1"), outputs(clock="9")
    )  # performance, tiempos y log
    assert report.verdict == "equivalent"


def test_a_tiny_float_difference_is_within_tolerance(workspace: Path) -> None:
    report = verdict(workspace, outputs(arrival="11.50"), outputs(arrival="11.500000000001"))
    assert report.verdict == "equivalent"


# --- lo que sí cuenta -------------------------------------------------------------------------


def test_a_float_beyond_the_tolerance_makes_them_different(workspace: Path) -> None:
    report = verdict(workspace, outputs(arrival="11.50"), outputs(arrival="11.51"))
    assert report.verdict == "different"
    (trip,) = [item for item in report.files if item.path == "outputs/tripinfo.xml"]
    assert (trip.equal, trip.differing_values) == (False, 1)
    assert trip.detail == "elemento 1 <tripinfo> arrival: 11.50 frente a 11.51"
    assert report.reasons == [f"outputs/tripinfo.xml: {trip.detail}"]


def test_a_wider_tolerance_can_be_asked_for(workspace: Path) -> None:
    wide = Tolerance(relative=0.01, absolute=0.01)
    report = verdict(workspace, outputs(arrival="11.50"), outputs(arrival="11.51"), tolerance=wide)
    assert (report.verdict, report.tolerance) == ("equivalent", wide)


def test_a_count_outside_the_performance_block_counts(workspace: Path) -> None:
    report = verdict(workspace, outputs(waiting="0"), outputs(waiting="1"))
    assert report.verdict == "different"
    assert any(
        item.path == "outputs/statistics.xml" and item.equal is False for item in report.files
    )


def test_a_text_value_must_be_identical(workspace: Path) -> None:
    assert verdict(workspace, outputs(vtype="car"), outputs(vtype="bus")).verdict == "different"


def extra_element(text: str) -> str:
    return text.replace("</tripinfos>", '<tripinfo id="v3"/></tripinfos>')


def extra_attribute(text: str) -> str:
    first = 'vType="car"/>\n    <tripinfo id="v2"'
    return text.replace(first, 'vType="car" extra="1"/>\n    <tripinfo id="v2"')


def other_tag(text: str) -> str:
    return text.replace("<tripinfos>", "<otra>").replace("</tripinfos>", "</otra>")


def truncated(text: str) -> str:
    return text[: len(text) // 2]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (extra_element, "elemento 3"),
        (extra_attribute, "frente a"),
        (other_tag, "frente a"),
        (truncated, "no se puede leer"),
    ],
    ids=["extra-element", "extra-attribute", "other-tag", "truncated"],
)
def test_a_different_structure_makes_them_different(
    workspace: Path, change: Callable[[str], str], expected: str
) -> None:
    changed = outputs()
    changed["tripinfo.xml"] = change(changed["tripinfo.xml"])
    report = verdict(workspace, outputs(), changed)
    (trip,) = [item for item in report.files if item.path == "outputs/tripinfo.xml"]
    assert report.verdict == "different"
    assert trip.detail is not None and expected in trip.detail


def test_infinite_and_missing_numbers_compare_by_value(workspace: Path) -> None:
    assert (
        verdict(workspace, outputs(arrival="11.50"), outputs(arrival="inf")).verdict == "different"
    )
    assert (
        verdict(workspace, outputs(arrival="inf"), outputs(arrival="Infinity")).verdict
        == "equivalent"
    )
    assert (
        verdict(workspace, outputs(arrival="nan"), outputs(arrival="nan")).verdict == "equivalent"
    )
    assert verdict(workspace, outputs(arrival="nan"), outputs(arrival="NaN")).verdict == "different"


def test_what_is_inside_a_skipped_block_does_not_count_either(workspace: Path) -> None:
    def nested(clock: str) -> dict[str, str]:
        files = outputs(clock=clock)
        files["statistics.xml"] = files["statistics.xml"].replace(
            f'duration="{clock}"/>', f'duration="{clock}"><step time="{clock}"/></performance>'
        )
        return files

    assert verdict(workspace, nested("1"), nested("9")).verdict == "equivalent"


def test_the_text_of_an_element_counts(workspace: Path) -> None:
    def with_note(note: str) -> dict[str, str]:
        files = outputs()
        files["tripinfo.xml"] = files["tripinfo.xml"].replace(
            "</tripinfos>", f"<note>{note}</note></tripinfos>"
        )
        return files

    report = verdict(workspace, with_note("ida"), with_note("vuelta"))
    (trip,) = [item for item in report.files if item.path == "outputs/tripinfo.xml"]
    assert (report.verdict, trip.detail) == ("different", "elemento 3 <note>: el texto cambia")


def test_a_table_must_be_identical_byte_by_byte(workspace: Path) -> None:
    changed = outputs()
    changed["cohorte_conciliada.csv"] = SHEET.replace("finished", "unfinished", 1)
    report = verdict(workspace, outputs(), changed)
    (sheet,) = [item for item in report.files if item.path == "outputs/cohorte_conciliada.csv"]
    assert (report.verdict, sheet.equal, sheet.detail) == (
        "different",
        False,
        "el contenido no es idéntico",
    )


def test_an_output_that_only_one_run_has_makes_them_different(workspace: Path) -> None:
    extra = {**outputs(), "otra.csv": "x"}
    report = verdict(workspace, outputs(), extra)
    assert report.verdict == "different"
    assert "una corrida tiene salidas que la otra no: otra.csv" in report.reasons
    only_log = dict(outputs())
    del only_log["sumo.log"]
    assert (
        verdict(workspace, outputs(), only_log).verdict == "equivalent"
    )  # los registros no cuentan


def test_different_inputs_or_seeds_make_them_different(workspace: Path) -> None:
    a = run(workspace, outputs())
    other_inputs = run(workspace, outputs(), inputs={"demo.sumocfg": "<configuration a='1'/>"})
    other_seed = run(workspace, outputs(), seed=8)
    other_case = run(workspace, outputs(), case_id="CASO_B")
    by_inputs = compare_runs(workspace / "ejecuciones", a, other_inputs, created_at=NOW)
    assert (by_inputs.verdict, by_inputs.inputs_equal, by_inputs.input_differences) == (
        "different",
        False,
        ["inputs/demo.sumocfg"],
    )
    by_seed = compare_runs(workspace / "ejecuciones", a, other_seed, created_at=NOW)
    assert "la semilla no es la misma (7 frente a 8)" in by_seed.reasons
    by_case = compare_runs(workspace / "ejecuciones", a, other_case, created_at=NOW)
    assert "no son del mismo caso, versión y escenario" in by_case.reasons


def test_a_dtd_in_an_output_is_not_followed(workspace: Path) -> None:
    changed = outputs()
    changed["tripinfo.xml"] = changed["tripinfo.xml"].replace(
        "<tripinfos>", '<!DOCTYPE tripinfos [<!ENTITY x "y">]>\n<tripinfos>'
    )
    report = verdict(workspace, changed, changed)
    (trip,) = [item for item in report.files if item.path == "outputs/tripinfo.xml"]
    assert report.verdict == "different"
    assert trip.detail is not None and "no se puede leer" in trip.detail


def test_an_output_over_the_size_limit_is_refused(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(replica_module, "MAX_XML_BYTES", 10)
    with pytest.raises(DomainError) as raised:
        verdict(workspace, outputs(), outputs())
    assert raised.value.code is ErrorCode.OUTPUT_INVALID


# --- la FCD comprimida (DEV31 F2) se compara como XML, no como bytes ---------------------------

FCD = (
    '<fcd-export><timestep time="0.00"><vehicle id="a" speed="{speed}" lane="L_0"/></timestep>'
    "</fcd-export>"
)


def compressed(speed: str) -> dict[str, bytes]:
    return {"fcd.xml.gz": gzip.compress(FCD.format(speed=speed).encode(), mtime=0)}


def compare_fcd(
    workspace: Path, first: Mapping[str, bytes], second: Mapping[str, bytes]
) -> ReplicaReport:
    a = run(workspace, outputs(), binary=first)
    b = run(workspace, outputs(), binary=second)
    return compare_runs(workspace / "ejecuciones", a, b, created_at=NOW)


def test_a_compressed_fcd_is_compared_as_xml_with_tolerance(workspace: Path) -> None:
    report = compare_fcd(workspace, compressed("5.50"), compressed("5.500000000001"))
    (item,) = [item for item in report.files if item.path == "outputs/fcd.xml.gz"]
    assert (item.rule, item.equal, report.verdict) == ("xml", True, "equivalent")


def test_a_compressed_fcd_beyond_the_tolerance_makes_them_different(workspace: Path) -> None:
    report = compare_fcd(workspace, compressed("5.50"), compressed("5.51"))
    (item,) = [item for item in report.files if item.path == "outputs/fcd.xml.gz"]
    assert (item.rule, item.equal, report.verdict) == ("xml", False, "different")
    assert item.detail is not None and "speed: 5.50 frente a 5.51" in item.detail


def test_a_broken_compressed_fcd_makes_them_different(workspace: Path) -> None:
    report = compare_fcd(workspace, compressed("5.50"), {"fcd.xml.gz": b"esto no es gzip"})
    (item,) = [item for item in report.files if item.path == "outputs/fcd.xml.gz"]
    assert item.equal is False
    assert item.detail is not None and "no se puede leer" in item.detail


def test_a_compressed_fcd_that_grows_past_the_limit_is_refused(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una bomba de compresión: pesa poco comprimida y mucho descomprimida."""
    monkeypatch.setattr(replica_module, "MAX_XML_BYTES", 2000)
    rows = "".join(f'<timestep time="{n}.00"/>' for n in range(1, 400))
    big = gzip.compress(f"<fcd-export>{rows}</fcd-export>".encode(), mtime=0)
    assert len(big) < 2000 < len(rows)
    with pytest.raises(DomainError) as raised:
        compare_fcd(workspace, {"fcd.xml.gz": big}, {"fcd.xml.gz": big})
    assert raised.value.code is ErrorCode.OUTPUT_INVALID


# --- qué corridas se pueden comparar ----------------------------------------------------------


def test_only_two_distinct_succeeded_and_intact_runs_are_compared(workspace: Path) -> None:
    a = run(workspace, outputs())
    failed = run(workspace, outputs(), status="failed")
    altered = run(workspace, outputs())
    tamper(workspace / "ejecuciones" / altered / "outputs" / "tripinfo.xml")
    cases = [
        (a, ErrorCode.INPUT_SCHEMA),  # consigo misma
        (failed, ErrorCode.INPUT_SCHEMA),
        (altered, ErrorCode.HASH_MISMATCH),
        ("20261101T230000Z_simulation_noexiste", ErrorCode.INPUT_SCHEMA),
        ("../fuera", ErrorCode.PATH_NOT_ALLOWED),
    ]
    for other, code in cases:
        with pytest.raises(DomainError) as raised:
            compare_runs(workspace / "ejecuciones", a, other, created_at=NOW)
        assert raised.value.code is code, other


# --- el reporte publicado ---------------------------------------------------------------------


def test_the_report_is_published_and_read_back_verified(workspace: Path) -> None:
    a, b = run(workspace, outputs()), run(workspace, outputs())
    report, folder = replicate(workspace, a, b, clock=clock)
    assert folder.parent == workspace / REPLICAS
    assert folder.name.startswith("20261101T230000Z_")
    assert sorted(p.name for p in folder.iterdir()) == [MANIFEST_FILE, REPORT_FILE]
    assert read_replica(folder) == report
    items = [
        item for item in verify_workspace(workspace, clock=clock).items if item.family == "replicas"
    ]
    assert [(item.path, item.status) for item in items] == [(f"{REPLICAS}/{folder.name}", "intact")]


def test_the_same_report_is_never_overwritten(workspace: Path) -> None:
    a, b = run(workspace, outputs()), run(workspace, outputs())
    replicate(workspace, a, b, clock=clock)
    with pytest.raises(DomainError) as raised:
        replicate(workspace, a, b, clock=clock)
    assert raised.value.code is ErrorCode.RUN_EXISTS


def test_an_altered_report_is_detected(workspace: Path) -> None:
    a, b = run(workspace, outputs()), run(workspace, outputs(arrival="99"))
    _, folder = replicate(workspace, a, b, clock=clock)
    path = writable(folder / REPORT_FILE)
    path.write_text(
        path.read_text(encoding="utf-8").replace('"different"', '"equivalent"'), encoding="utf-8"
    )
    with pytest.raises(DomainError) as raised:
        read_replica(folder)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_report_that_does_not_match_its_manifest_is_detected(workspace: Path) -> None:
    a, b = run(workspace, outputs()), run(workspace, outputs())
    report, _ = replicate(workspace, a, b, clock=clock)
    data = report.model_dump_json().encode("utf-8")
    lying = json.dumps(
        {"run_a": a, "run_b": b, "verdict": "different", "files": {REPORT_FILE: digest(data)}}
    ).encode("utf-8")
    folder = workspace / REPLICAS / "falso"
    publish_files(folder, {REPORT_FILE: data, MANIFEST_FILE: lying})
    with pytest.raises(DomainError) as raised:
        read_replica(folder)
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    bad = workspace / REPLICAS / "invalido"
    junk = b"{}"
    manifest = json.dumps(
        {"run_a": "x", "run_b": "y", "verdict": "different", "files": {REPORT_FILE: digest(junk)}}
    ).encode("utf-8")
    publish_files(bad, {REPORT_FILE: junk, MANIFEST_FILE: manifest})
    with pytest.raises(DomainError) as raised:
        read_replica(bad)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
