"""Registro de ejecución de pruebas: lectura de pytest, severidades y ausencia de rutas."""

import json
from pathlib import Path

import pytest

from evidence_lib import (
    EvidenceReport,
    Result,
    classify,
    fixtures_digest,
    git_state,
    parse_junit,
    render_markdown,
    scrub,
)
from qa_catalog import CATALOG, ROOT, Qa, resolve

COUNTS = "tests/unit/test_counts.py"
SYMLINK = "este equipo no permite crear enlaces simbólicos sin privilegios"


def key_results() -> list[Result]:
    """Todas las pruebas clave del catálogo, todas pasando."""
    seen: set[tuple[str, str]] = set()
    results: list[Result] = []
    for qa in CATALOG:
        for entry in qa.key_tests:
            for item in resolve(entry):
                path, _, function = item.partition("::")
                if function:
                    key = (path, function)
                    if key not in seen:
                        seen.add(key)
                        results.append(
                            Result(file=path, name=function, outcome="passed", message=None)
                        )
    return results


def build(
    results: list[Result],
    *,
    sensitivity: dict[str, int] | None = None,
) -> EvidenceReport:
    return classify(
        results,
        generated_at="2026-11-02T00:00:00+00:00",
        command=["python", "-m", "pytest"],
        commit="a" * 40,
        dirty=False,
        environment={"python": "3.12"},
        fixtures=(3, "f" * 64),
        sensitivity=sensitivity,
    )


def junit(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(
        f'<?xml version="1.0"?><testsuites><testsuite name="p">{body}</testsuite></testsuites>',
        encoding="utf-8",
    )
    return path


# --- lectura de pytest ------------------------------------------------------------------------


def test_a_junit_file_is_read_with_each_outcome(tmp_path: Path) -> None:
    path = junit(
        tmp_path,
        '<testcase classname="tests.unit.test_counts" name="test_a">'
        "</testcase>"
        '<testcase classname="tests.unit.test_counts" name="test_b[param]">'
        '<failure message="se esperaba 1"/></testcase>'
        '<testcase classname="tests.unit.test_counts" name="test_c">'
        '<skipped type="pytest.skip" message="motivo"/></testcase>'
        '<testcase classname="tests.unit.test_counts" name="test_d">'
        '<error message="no arrancó"/></testcase>',
    )
    results = parse_junit(path)
    assert [(r.file, r.name, r.outcome, r.message) for r in results] == [
        (COUNTS, "test_a", "passed", None),
        (COUNTS, "test_b", "failed", "se esperaba 1"),
        (COUNTS, "test_c", "skipped", "motivo"),
        (COUNTS, "test_d", "error", "no arrancó"),
    ]


def test_a_junit_file_with_a_dtd_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "malo.xml"
    path.write_text('<!DOCTYPE x [<!ENTITY a "b">]><testsuites>&a;</testsuites>', encoding="utf-8")
    with pytest.raises(Exception, match=r"Entities|DTD|forbidden"):
        parse_junit(path)


# --- estado de cada caso y puerta -------------------------------------------------------------


def test_when_every_key_test_passes_every_case_is_met_and_the_gate_is_clean() -> None:
    report = build(key_results())
    assert [q.status for q in report.qa] == ["cumplido"] * 10
    assert report.gate.result == "sin fallos críticos"
    assert (report.gate.critical_failures, report.gate.major_findings) == (0, 0)


def test_a_failed_key_test_is_critical_names_its_task_and_breaks_the_gate() -> None:
    results = key_results()
    victim = next(r for r in results if r.file == COUNTS and r.name.startswith("test_qa04_"))
    broken = [
        r if r is not victim else r.model_copy(update={"outcome": "failed", "message": "falló"})
        for r in results
    ]
    report = build(broken)
    qa04 = next(q for q in report.qa if q.qa_id == "QA04")
    assert qa04.status == "no cumplido"
    assert [(f.severity, f.task, f.test) for f in qa04.failures] == [
        ("crítico", "DEV04", f"{COUNTS}::{victim.name}")
    ]
    assert report.gate.result == "con fallos críticos"
    assert report.gate.critical_failures == 1
    assert sum(1 for q in report.qa if q.status == "no cumplido") >= 1


def test_an_error_counts_as_a_failure() -> None:
    results = key_results()
    broken = [r.model_copy(update={"outcome": "error"}) if r is results[0] else r for r in results]
    report = build(broken)
    assert report.gate.critical_failures >= 1


def test_a_declared_skip_is_met_with_a_caveat_and_does_not_break_the_gate() -> None:
    results = key_results()
    link = next(r for r in results if r.name == "test_a_folder_that_is_a_link_is_refused")
    skipped = [
        r if r is not link else r.model_copy(update={"outcome": "skipped", "message": SYMLINK})
        for r in results
    ]
    report = build(skipped)
    qa10 = next(q for q in report.qa if q.qa_id == "QA10")
    assert qa10.status == "cumplido con salvedad"
    assert qa10.skips[0].declared
    assert "Modo de desarrollador" in str(qa10.skips[0].note)
    assert report.gate.result == "sin fallos críticos"


def test_an_undeclared_skip_is_a_major_finding_and_the_case_is_not_met() -> None:
    results = key_results()
    skipped = [
        r.model_copy(update={"outcome": "skipped", "message": "no tuve ganas"})
        if r is results[0]
        else r
        for r in results
    ]
    report = build(skipped)
    assert report.gate.critical_failures == 0
    assert report.gate.major_findings == 1
    assert report.undeclared_skips[0].reason == "no tuve ganas"
    assert any(q.status == "no cumplido" for q in report.qa)


def test_a_failure_outside_the_key_tests_is_major_not_critical() -> None:
    extra = Result(file="tests/unit/test_otro.py", name="test_algo", outcome="failed", message="x")
    report = build([*key_results(), extra])
    assert report.gate.critical_failures == 0
    assert [(f.severity, f.test) for f in report.other_failures] == [
        ("mayor", "tests/unit/test_otro.py::test_algo")
    ]
    assert report.gate.major_findings == 1
    assert all(q.status == "cumplido" for q in report.qa)


def test_a_whole_file_entry_counts_every_test_of_the_file() -> None:
    results = [
        Result(
            file="tests/unit/test_paths.py", name="test_cualquiera", outcome="passed", message=None
        )
    ]
    qa = Qa("QA10", "Seguridad", "DEVX", "resumen", ("tests/unit/test_paths.py",))
    report = classify(
        results,
        generated_at="t",
        command=[],
        commit="c",
        dirty=False,
        environment={},
        fixtures=(0, "x"),
        sensitivity=None,
        catalog=(qa,),
    )
    assert report.qa[0].key_tests == 1


def test_totals_count_every_outcome_in_the_suite() -> None:
    results = [
        Result(file="a.py", name="t1", outcome="passed", message=None),
        Result(file="a.py", name="t2", outcome="failed", message="x"),
        Result(file="a.py", name="t3", outcome="skipped", message="y"),
        Result(file="a.py", name="t4", outcome="error", message="z"),
        Result(file="a.py", name="t5", outcome="passed", message=None),
    ]
    totals = build(results).totals
    assert (totals.passed, totals.failed, totals.skipped, totals.errors) == (2, 1, 1, 1)


# --- el informe y la ausencia de rutas de la máquina ------------------------------------------


def test_the_markdown_report_shows_the_gate_the_cases_and_does_not_claim_approval() -> None:
    sensitivity = {"ensayados": 32, "detectados": 32, "sobrevivieron": 0}
    text = render_markdown(build(key_results(), sensitivity=sensitivity))
    assert "sin fallos críticos" in text
    assert "| QA10 | Seguridad | DEV00, DEV06, DEV07 |" in text
    assert "32 cambios a propósito: 32 detectados, 0 sobrevivieron" in text
    assert "No completa las tablas de resultados del Sprint 1" in text
    assert "aprobado" not in text.lower().replace("no completa", "")
    assert "Ninguno." in text


def test_the_report_without_the_sensitivity_run_says_so() -> None:
    assert "No se ejecutó en esta corrida." in render_markdown(build(key_results()))


def test_paths_of_this_machine_are_removed_from_the_texts() -> None:
    dirty = f"falló en {ROOT}\\tests\\x.py y en {ROOT.as_posix()}/tests/y.py desde {Path.home()}"
    cleaned = scrub(dirty)
    assert str(ROOT) not in cleaned
    assert ROOT.as_posix() not in cleaned
    assert str(Path.home()) not in cleaned
    assert cleaned.count("<equipo>") == 3


def test_failure_messages_in_the_record_carry_no_machine_path() -> None:
    results = key_results()
    broken = [
        r.model_copy(update={"outcome": "failed", "message": f"error en {ROOT}\\src\\x.py"})
        if r is results[0]
        else r
        for r in results
    ]
    shown = build(broken).model_dump_json()
    assert str(ROOT) not in shown
    assert json.loads(shown)["gate"]["critical_failures"] == 1


# --- datos de prueba y commit -----------------------------------------------------------------


def test_the_fixtures_have_a_stable_content_identifier(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "sub" / "b.txt").write_text("b", encoding="utf-8")
    first = fixtures_digest(tmp_path)
    assert first[0] == 2
    assert fixtures_digest(tmp_path) == first
    (tmp_path / "a.txt").write_text("cambio", encoding="utf-8")
    assert fixtures_digest(tmp_path)[1] != first[1]


def test_the_real_fixtures_are_counted() -> None:
    count, identifier = fixtures_digest()
    assert count > 10
    assert len(identifier) == 64


def test_the_commit_is_a_full_hash() -> None:
    commit, dirty = git_state()
    assert len(commit) == 40
    assert isinstance(dirty, bool)
