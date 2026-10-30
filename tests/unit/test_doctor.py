"""Reglas del diagnóstico del entorno (DEV01, F1): sin medir el equipo y sin SUMO."""

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from semaforo.app.doctor import (
    EXPECTED_SUMO_VERSION,
    REQUIRED_PACKAGES,
    EnvironmentFacts,
    WorkspaceFacts,
    build_report,
)
from semaforo.app.doctor_models import Check, DoctorReport

GIB = 1024**3
WORKSPACE = WorkspaceFacts(
    path="datos", exists=True, is_directory=True, is_link=False, writable=True
)
GOOD = EnvironmentFacts(
    python_version="3.12.3",
    packages={"semaforo": "0.1.0", "pydantic": "2.9.2", "defusedxml": "0.7.1"},
    operating_system="Windows-11-10.0.26200-SP0",
    cpu_count=16,
    memory_total_bytes=16 * GIB,
    memory_available_bytes=8 * GIB,
    workspace=WORKSPACE,
    disk_free_bytes=100 * GIB,
    sumo_binary="C:/Sumo/bin/sumo.exe",
    sumo_version=EXPECTED_SUMO_VERSION,
)
ORDER = [
    "python",
    *(f"package:{name}" for name in REQUIRED_PACKAGES),
    "os",
    "cpu",
    "memory_total",
    "memory_available",
    "workspace",
    "disk_free",
    "sumo",
    "sumo_version",
]


def check(report: DoctorReport, name: str) -> Check:
    return next(item for item in report.checks if item.name == name)


def with_workspace(**changes: bool) -> EnvironmentFacts:
    return replace(GOOD, workspace=replace(WORKSPACE, **changes))


def test_a_good_environment_passes_every_check() -> None:
    report = build_report(GOOD)
    assert report.status == "ok"
    assert report.exit_code == 0
    assert [item.name for item in report.checks] == ORDER
    assert all(item.status == "ok" and item.code is None for item in report.checks)


def test_the_report_survives_a_json_round_trip() -> None:
    report = build_report(GOOD)
    assert DoctorReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("version", ["3.11.9", "3.13.0", "2.7.18", "no es una versión"])
def test_python_other_than_3_12_is_a_missing_dependency(version: str) -> None:
    report = build_report(replace(GOOD, python_version=version))
    assert check(report, "python").status == "error"
    assert check(report, "python").code == "DEPENDENCY_MISSING"
    assert report.status == "failed"
    assert report.exit_code == 3


def test_any_python_3_12_patch_release_passes() -> None:
    assert check(build_report(replace(GOOD, python_version="3.12.0")), "python").status == "ok"


@pytest.mark.parametrize("package", REQUIRED_PACKAGES)
def test_a_missing_package_is_a_missing_dependency(package: str) -> None:
    packages = {**GOOD.packages, package: None}
    report = build_report(replace(GOOD, packages=packages))
    assert check(report, f"package:{package}").code == "DEPENDENCY_MISSING"
    assert report.exit_code == 3


def test_package_versions_are_reported() -> None:
    report = build_report(GOOD)
    assert check(report, "package:pydantic").value == "2.9.2"


@pytest.mark.parametrize(
    ("changes", "code", "exit_code"),
    [
        ({"exists": False, "is_directory": False}, "INPUT_SCHEMA", 2),
        ({"is_link": True}, "PATH_NOT_ALLOWED", 5),
        ({"is_directory": False}, "PATH_NOT_ALLOWED", 5),
        ({"writable": False}, "PATH_NOT_ALLOWED", 5),
    ],
    ids=["missing", "link", "not-a-folder", "read-only"],
)
def test_an_unusable_workspace_fails(changes: dict[str, bool], code: str, exit_code: int) -> None:
    report = build_report(with_workspace(**changes))
    assert check(report, "workspace").status == "error"
    assert check(report, "workspace").code == code
    assert report.exit_code == exit_code


def test_a_link_is_rejected_even_if_it_is_writable() -> None:
    report = build_report(with_workspace(is_link=True, writable=True))
    assert check(report, "workspace").code == "PATH_NOT_ALLOWED"


@pytest.mark.parametrize("free", [0, None])
def test_no_free_space_or_no_measure_is_only_a_warning(free: int | None) -> None:
    report = build_report(replace(GOOD, disk_free_bytes=free))
    assert check(report, "disk_free").status == "warning"
    assert report.status == "warnings"
    assert report.exit_code == 0


def test_little_free_space_is_reported_without_a_threshold() -> None:
    report = build_report(replace(GOOD, disk_free_bytes=1))
    assert check(report, "disk_free").status == "ok"
    assert check(report, "disk_free").value == 1


def test_memory_is_reported_in_bytes() -> None:
    report = build_report(GOOD)
    assert check(report, "memory_total").value == 16 * GIB
    assert check(report, "memory_available").value == 8 * GIB
    assert "GiB" in check(report, "memory_total").message


def test_memory_that_cannot_be_measured_is_only_a_warning() -> None:
    report = build_report(replace(GOOD, memory_total_bytes=None, memory_available_bytes=None))
    assert check(report, "memory_total").status == "warning"
    assert check(report, "memory_available").status == "warning"
    assert report.exit_code == 0


@pytest.mark.parametrize("count", [None, 0])
def test_an_unknown_cpu_count_is_only_a_warning(count: int | None) -> None:
    assert check(build_report(replace(GOOD, cpu_count=count)), "cpu").status == "warning"


def test_an_unknown_operating_system_is_only_a_warning() -> None:
    assert check(build_report(replace(GOOD, operating_system=None)), "os").status == "warning"


def test_missing_sumo_is_a_missing_dependency() -> None:
    report = build_report(replace(GOOD, sumo_binary=None, sumo_version=None))
    assert check(report, "sumo").code == "DEPENDENCY_MISSING"
    assert check(report, "sumo_version").status == "warning"
    assert report.exit_code == 3


def test_missing_sumo_keeps_the_reason_found_when_measuring() -> None:
    problem = "no se encuentra SUMO: revise SUMO_HOME"
    report = build_report(replace(GOOD, sumo_binary=None, sumo_version=None, sumo_problem=problem))
    assert check(report, "sumo").message == problem


def test_an_unreadable_sumo_version_is_a_missing_dependency() -> None:
    facts = replace(GOOD, sumo_version=None, sumo_problem="no se pudo ejecutar SUMO (OSError)")
    report = build_report(facts)
    assert check(report, "sumo").status == "ok"
    assert check(report, "sumo_version").code == "DEPENDENCY_MISSING"
    assert "OSError" in check(report, "sumo_version").message
    assert report.exit_code == 3


def test_another_sumo_version_is_only_a_warning() -> None:
    report = build_report(replace(GOOD, sumo_version="1.26.0"))
    assert check(report, "sumo_version").status == "warning"
    assert EXPECTED_SUMO_VERSION in check(report, "sumo_version").message
    assert report.status == "warnings"
    assert report.exit_code == 0


def test_with_several_errors_the_exit_code_is_the_first_one() -> None:
    facts = replace(with_workspace(is_link=True), python_version="3.11.9")
    assert build_report(facts).exit_code == 3
    assert build_report(with_workspace(is_link=True)).exit_code == 5


def test_a_check_has_a_code_if_and_only_if_it_is_an_error() -> None:
    with pytest.raises(ValidationError):
        Check(name="x", status="error", value=None, message="m")
    with pytest.raises(ValidationError):
        Check(name="x", status="ok", value=None, message="m", code="INPUT_SCHEMA")


def test_the_report_rejects_unknown_fields() -> None:
    data = build_report(GOOD).model_dump()
    data["extra"] = 1
    with pytest.raises(ValidationError):
        DoctorReport.model_validate(data)


VERSIONS = st.sampled_from(["3.12.3", "3.11.9", "x"])
OPTIONAL_VERSION = st.one_of(st.none(), st.just("1.0"))
SIZES = st.one_of(st.none(), st.integers(min_value=0, max_value=2**45))


@given(
    python=VERSIONS,
    package=OPTIONAL_VERSION,
    cpu=st.one_of(st.none(), st.integers(min_value=0, max_value=256)),
    memory=SIZES,
    disk=SIZES,
    exists=st.booleans(),
    link=st.booleans(),
    writable=st.booleans(),
    sumo=st.one_of(st.none(), st.just("sumo")),
    sumo_version=st.sampled_from([None, EXPECTED_SUMO_VERSION, "1.26.0"]),
)
def test_status_and_exit_code_always_follow_the_checks(  # noqa: PLR0913  (un dato por medición)
    python: str,
    package: str | None,
    cpu: int | None,
    memory: int | None,
    disk: int | None,
    *,
    exists: bool,
    link: bool,
    writable: bool,
    sumo: str | None,
    sumo_version: str | None,
) -> None:
    facts = EnvironmentFacts(
        python_version=python,
        packages={"semaforo": package, "pydantic": "2", "defusedxml": "0.7"},
        operating_system="X",
        cpu_count=cpu,
        memory_total_bytes=memory,
        memory_available_bytes=memory,
        workspace=WorkspaceFacts(
            path="w", exists=exists, is_directory=exists, is_link=link, writable=writable
        ),
        disk_free_bytes=disk,
        sumo_binary=sumo,
        sumo_version=sumo_version,
    )
    report = build_report(facts)
    statuses = {item.status for item in report.checks}
    assert [item.name for item in report.checks] == ORDER
    assert (report.status == "failed") == ("error" in statuses)
    assert (report.status == "warnings") == ("error" not in statuses and "warning" in statuses)
    assert (report.exit_code == 0) == (report.status != "failed")
    if report.status == "failed":
        assert report.exit_code in {2, 3, 5}
