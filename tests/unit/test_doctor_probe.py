"""Medición del equipo para el diagnóstico (DEV01, F2), sin ejecutar SUMO."""

import platform
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

import pytest

from semaforo.app.doctor import REQUIRED_PACKAGES, build_report
from semaforo.app.doctor_probe import (
    PROBE_PREFIX,
    can_write,
    free_bytes,
    measure_environment,
    memory_bytes,
    package_versions,
    sumo_facts,
    workspace_facts,
)
from semaforo.dominio.errors import DomainError, ErrorCode

WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="las uniones (junctions) solo existen en Windows"
)


def make_junction(link: Path, target: Path) -> None:
    """Crea una unión de Windows (``mklink /J``), que no necesita privilegios."""
    subprocess.run(  # noqa: S603
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],  # noqa: S607
        check=True,
        capture_output=True,
    )


def fake_sumo(folder: Path) -> Path:
    binary = folder / "Sumo" / "bin" / "sumo.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    return binary


def test_package_versions_come_from_the_installed_metadata() -> None:
    versions = package_versions()
    assert set(versions) == set(REQUIRED_PACKAGES)
    assert versions["pydantic"] == metadata.version("pydantic")


def test_a_package_that_is_not_installed_is_none() -> None:
    def lookup(name: str) -> str:
        if name == "defusedxml":
            raise metadata.PackageNotFoundError(name)
        return "1.0"

    assert package_versions(lookup) == {"semaforo": "1.0", "pydantic": "1.0", "defusedxml": None}


def test_memory_is_measured_with_the_standard_library() -> None:
    total, available = memory_bytes()
    if sys.platform == "win32":
        assert total is not None
        assert available is not None
        assert 0 < available <= total
    else:
        assert total is None or total > 0


def test_a_real_folder_is_usable(tmp_path: Path) -> None:
    facts = workspace_facts(tmp_path)
    assert facts.exists
    assert facts.is_directory
    assert not facts.is_link
    assert facts.writable


def test_the_write_probe_leaves_nothing_behind(tmp_path: Path) -> None:
    assert can_write(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_folder_where_files_cannot_be_created_is_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simula el permiso denegado: en Windows, quitarlo a una carpeta exige cambiar sus ACL."""

    def denied(**_: object) -> tuple[int, str]:
        raise PermissionError("acceso denegado")

    monkeypatch.setattr(tempfile, "mkstemp", denied)
    assert not can_write(tmp_path)
    assert not workspace_facts(tmp_path).writable


def test_a_missing_folder_does_not_exist(tmp_path: Path) -> None:
    facts = workspace_facts(tmp_path / "no-existe")
    assert not facts.exists
    assert not facts.writable


def test_a_file_is_not_a_folder(tmp_path: Path) -> None:
    file = tmp_path / "datos.txt"
    file.write_text("x", encoding="utf-8")
    facts = workspace_facts(file)
    assert facts.exists
    assert not facts.is_directory
    assert not facts.writable


@WINDOWS_ONLY
def test_a_junction_is_a_link_and_is_not_written_through(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "enlace"
    make_junction(link, target)
    try:
        facts = workspace_facts(link)
        assert facts.is_link
        assert not facts.writable
        assert list(target.iterdir()) == []
        assert free_bytes(link) is None
    finally:
        link.rmdir()


def test_free_space_is_measured_only_for_a_real_folder(tmp_path: Path) -> None:
    free = free_bytes(tmp_path)
    assert free is not None
    assert free > 0
    assert free_bytes(tmp_path / "no-existe") is None


def test_sumo_is_found_with_sumo_home(tmp_path: Path) -> None:
    binary = fake_sumo(tmp_path)
    found = sumo_facts(None, {"SUMO_HOME": str(tmp_path / "Sumo")}, lambda _: "1.27.1")
    assert found == (str(binary), "1.27.1", None)


def test_the_sumo_bin_argument_wins_over_sumo_home(tmp_path: Path) -> None:
    binary = fake_sumo(tmp_path)
    found = sumo_facts(binary, {"SUMO_HOME": str(tmp_path / "otro")}, lambda _: "1.27.1")
    assert found[0] == str(binary)


def test_without_sumo_home_the_reason_is_kept() -> None:
    binary, version, problem = sumo_facts(None, {}, lambda _: "1.27.1")
    assert binary is None
    assert version is None
    assert problem is not None
    assert "SUMO_HOME" in problem


def test_a_sumo_bin_that_does_not_exist_is_reported(tmp_path: Path) -> None:
    binary, version, problem = sumo_facts(tmp_path / "sumo.exe", {}, lambda _: "1.27.1")
    assert (binary, version) == (None, None)
    assert problem == "no existe el ejecutable indicado en --sumo-bin"


def test_a_sumo_that_does_not_answer_keeps_the_reason(tmp_path: Path) -> None:
    binary = fake_sumo(tmp_path)

    def broken(_: Path) -> str:
        raise DomainError(ErrorCode.DEPENDENCY_MISSING, "no se pudo ejecutar SUMO (OSError)")

    assert sumo_facts(binary, {}, broken) == (
        str(binary),
        None,
        "no se pudo ejecutar SUMO (OSError)",
    )


def test_measuring_this_computer_without_sumo_fails_only_on_sumo(tmp_path: Path) -> None:
    facts = measure_environment(tmp_path, environment={})
    assert facts.python_version == platform.python_version()
    report = build_report(facts)
    errors = [check.name for check in report.checks if check.status == "error"]
    assert errors == ["sumo"]
    assert report.exit_code == 3
    assert not any(path.name.startswith(PROBE_PREFIX) for path in tmp_path.iterdir())
