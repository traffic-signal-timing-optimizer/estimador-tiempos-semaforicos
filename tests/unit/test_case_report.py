"""Reporte del caso (DEV02, F3): estado, huella SHA-256, límites efectivos y reglas en orden."""

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from semaforo.app.exit_codes import EXIT_CODES
from semaforo.caso import case_validation
from semaforo.caso.case_report_models import (
    REPORT_EXIT_CODES,
    CaseReport,
    Interval,
    RuleOutcome,
)
from semaforo.caso.case_validation import validate_case
from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.dominio.case import canonical_sha256, parse_case

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "case.json"
RULE_ORDER = [
    "CASE-S01",
    "CASE-S02",
    "CASE-S03",
    "CASE-S04",
    *(f"CASE-C{number:02d}" for number in range(1, 14)),
    "CASE-N01",
    "CASE-N02",
]


def fixture_data() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return result


def write_case(folder: Path, data: object, name: str = "case.json") -> Path:
    path = folder / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def report_of(folder: Path, data: object) -> CaseReport:
    return validate_case(write_case(folder, data))


def _bounds(interval: Interval | None) -> tuple[float, float] | None:
    return None if interval is None else (interval.min, interval.max)


def rule(report: CaseReport, rule_id: str) -> RuleOutcome:
    return next(item for item in report.rules if item.rule_id == rule_id)


def test_the_reference_case_is_valid_with_its_limits() -> None:
    report = validate_case(FIXTURE)
    assert (report.status, report.exit_code, report.network) == ("valid", 0, "not_declared")
    assert (report.case_id, report.origin) == ("SYNTHETIC_DEMO", "synthetic")
    assert report.limits is not None
    assert report.limits.tick_s == 1
    assert (report.limits.cycle_declared_s.min, report.limits.cycle_declared_s.max) == (40, 100)
    feasible = report.limits.cycle_feasible_s
    assert feasible is not None and (feasible.min, feasible.max) == (40, 100)
    assert report.limits.fixed_time_s == 8
    assert report.limits.variable_slots == 2
    assert [(g.id, _bounds(g.reachable_s)) for g in report.limits.green_groups] == [
        ("NS", (10, 50)),
        ("EW", (10, 50)),
    ]


def test_every_rule_appears_once_in_a_fixed_order(tmp_path: Path) -> None:
    report = validate_case(FIXTURE)
    assert [item.rule_id for item in report.rules] == RULE_ORDER


def test_the_reference_case_passes_all_applicable_rules() -> None:
    report = validate_case(FIXTURE)
    statuses = {item.rule_id: item.status for item in report.rules}
    assert {status for rule_id, status in statuses.items() if rule_id.startswith("CASE-C")} == {
        "passed"
    }
    assert {statuses["CASE-N01"], statuses["CASE-N02"]} == {"not_applicable"}


def test_the_hash_is_the_canonical_hash_of_the_parsed_case() -> None:
    report = validate_case(FIXTURE)
    assert report.case_sha256 == canonical_sha256(parse_case(fixture_data()))
    assert re.fullmatch(r"[0-9a-f]{64}", report.case_sha256 or "")


def test_formatting_and_key_order_do_not_change_the_hash(tmp_path: Path) -> None:
    data = fixture_data()
    compact = validate_case(write_case(tmp_path, data, "compacto.json"))
    reordered = dict(reversed(list(data.items())))
    spaced_path = tmp_path / "con_espacios.json"
    spaced_path.write_text(json.dumps(reordered, indent=4), encoding="utf-8")
    assert compact.case_sha256 == validate_case(spaced_path).case_sha256


def test_the_hash_of_the_reference_case_is_pinned() -> None:
    """Valor de regresión: cambiar el formato canónico cambia la huella de todos los casos."""
    assert validate_case(FIXTURE).case_sha256 == (
        "da02de6f956007d5aa02c864e27fdc256f118bd197e1196f595ddbb3d151a2a3"
    )


def test_accented_text_is_hashed_as_utf8_text(tmp_path: Path) -> None:
    data = fixture_data()
    data["description"] = "descripción con ñ y tilde"
    report = report_of(tmp_path, data)
    assert report.case_sha256 == (
        "de731e8e481e8b160dbefd1816595a2bd8fe21f2f222cf51c766c55c79ce8a80"
    )


def test_a_change_of_value_changes_the_hash(tmp_path: Path) -> None:
    data = fixture_data()
    changed = copy.deepcopy(data)
    changed["description"] = "otra descripción"
    original = validate_case(write_case(tmp_path, data, "a.json"))
    other = validate_case(write_case(tmp_path, changed, "b.json"))
    assert original.case_sha256 != other.case_sha256


def test_a_repeated_consecutive_state_is_a_warning_and_still_valid(tmp_path: Path) -> None:
    data = fixture_data()
    data["slots"].insert(1, {**copy.deepcopy(data["slots"][0]), "id": "s1b"})
    report = report_of(tmp_path, data)
    assert (report.status, report.exit_code) == ("valid_with_warnings", 0)
    c07 = rule(report, "CASE-C07")
    assert c07.status == "warning"
    assert c07.issues


def test_a_duplicated_slot_id_is_invalid_and_keeps_the_limits(tmp_path: Path) -> None:
    data = fixture_data()
    data["slots"][2]["id"] = "s1"
    report = report_of(tmp_path, data)
    assert (report.status, report.exit_code) == ("invalid", 2)
    assert rule(report, "CASE-C01").status == "failed"
    assert report.limits is not None
    assert report.case_sha256 is not None


def test_a_group_whose_window_is_empty_has_no_reachable_limit(tmp_path: Path) -> None:
    data = fixture_data()
    data["green_groups"][0]["min_s"] = 60
    report = report_of(tmp_path, data)
    assert report.status == "invalid"
    assert report.limits is not None
    assert report.limits.green_groups[0].reachable_s is None
    assert report.limits.green_groups[1].reachable_s is not None


def test_a_structural_error_describes_the_field_and_leaves_consistency_out(tmp_path: Path) -> None:
    data = fixture_data()
    data["tick_s"] = "1"
    report = report_of(tmp_path, data)
    assert (report.status, report.exit_code, report.network) == ("invalid", 2, "not_checked")
    s01 = rule(report, "CASE-S01")
    assert s01.status == "failed"
    assert [issue.field for issue in s01.issues] == ["tick_s"]
    assert rule(report, "CASE-S02").status == "passed"
    assert {rule(report, f"CASE-C{n:02d}").status for n in range(1, 14)} == {"not_applicable"}
    assert report.limits is None
    assert report.case_sha256 is None
    assert report.case_id is None


def test_invalid_json_is_reported_without_a_field_and_the_other_structure_rules_wait(
    tmp_path: Path,
) -> None:
    path = tmp_path / "case.json"
    path.write_bytes(b'{"case_id": 1,}')
    report = validate_case(path)
    assert report.exit_code == 2
    s01 = rule(report, "CASE-S01")
    assert (s01.status, [issue.field for issue in s01.issues]) == ("failed", [None])
    assert rule(report, "CASE-S02").status == "not_applicable"
    assert rule(report, "CASE-S04").status == "passed"


def test_a_file_over_the_size_limit_fails_s04_only(tmp_path: Path) -> None:
    path = tmp_path / "case.json"
    path.write_bytes(b" " * (1024 * 1024 + 1))
    report = validate_case(path)
    assert (report.exit_code, rule(report, "CASE-S04").status) == (2, "failed")
    assert rule(report, "CASE-S01").status == "not_applicable"


def test_a_missing_file_is_reported_with_its_reason(tmp_path: Path) -> None:
    report = validate_case(tmp_path / "no-existe.json")
    assert (report.status, report.exit_code, report.network) == ("invalid", 2, "not_checked")
    assert report.error == "no existe el archivo del caso"
    assert report.case_sha256 is None
    assert {item.status for item in report.rules} == {"not_applicable"}
    assert [item.rule_id for item in report.rules] == RULE_ORDER


def test_a_folder_given_as_case_is_reported_as_not_a_file(tmp_path: Path) -> None:
    report = validate_case(tmp_path)
    assert report.exit_code == 2
    assert report.error == "la ruta del caso no es un archivo"


def test_a_case_file_that_is_a_symlink_is_path_not_allowed(tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_bytes(FIXTURE.read_bytes())
    link = tmp_path / "enlace.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    report = validate_case(link)
    assert (report.status, report.exit_code) == ("invalid", 5)
    assert report.error == "el archivo del caso es un enlace o una unión"


def test_a_case_path_not_allowed_by_the_reader_has_exit_code_5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(path: Path) -> bytes:
        raise CasoError(ErrorCode.PATH_NOT_ALLOWED, "el archivo del caso es un enlace", "case")

    monkeypatch.setattr(case_validation, "_read_bytes", refused)
    report = validate_case(tmp_path / "case.json")
    assert (report.status, report.exit_code) == ("invalid", 5)
    assert report.error == "el archivo del caso es un enlace"


def test_the_report_round_trips_through_json() -> None:
    report = validate_case(FIXTURE)
    assert CaseReport.model_validate_json(report.model_dump_json()) == report


def test_report_exit_codes_are_the_cli_exit_codes_for_the_same_errors() -> None:
    assert REPORT_EXIT_CODES == {code: EXIT_CODES[code] for code in REPORT_EXIT_CODES}
