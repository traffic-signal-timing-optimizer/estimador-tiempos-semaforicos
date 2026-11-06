"""Código y equipo que se anotan en el manifiesto de una corrida (DEV31 F2; indicador I7)."""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from semaforo.simulacion import environment
from semaforo.simulacion.environment import capture_environment
from semaforo.simulacion.resources import available_memory_bytes, total_memory_bytes

GIT = ["git", "-c", "user.name=prueba", "-c", "user.email=prueba@example.com"]
NO_VARIABLES: dict[str, str] = {}


def git(root: Path, *arguments: str) -> None:
    subprocess.run([*GIT, "-C", str(root), *arguments], check=True, capture_output=True)  # noqa: S603


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proyecto"
    root.mkdir()
    git(root, "init", "-q")
    (root / "codigo.py").write_text("x = 1\n", encoding="utf-8")
    git(root, "add", "codigo.py")
    git(root, "commit", "-q", "-m", "primero")
    return root


def machine_says(facts: dict[str, str]) -> Callable[[str], str | None]:
    """Lo que el equipo declara de sí mismo (``/sys/class/dmi/id``), armado a mano."""

    def read(name: str) -> str | None:
        return facts.get(name)

    return read


@pytest.fixture(autouse=True)
def no_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Las pruebas no dependen de la máquina donde corren: sin datos de la nube por defecto."""
    monkeypatch.setattr(environment, "_dmi", machine_says({}))


def test_the_commit_is_the_one_of_the_project(repo: Path) -> None:
    found = capture_environment(repo, NO_VARIABLES)
    head = subprocess.run(  # noqa: S603  (lista fija, sin shell)
        [*GIT, "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert found["commit"] == head
    assert found["code_modified"] == "false"


def test_a_change_in_a_tracked_file_marks_the_code_as_modified(repo: Path) -> None:
    (repo / "codigo.py").write_text("x = 2\n", encoding="utf-8")
    assert capture_environment(repo, NO_VARIABLES)["code_modified"] == "true"


def test_a_new_untracked_file_does_not_mark_the_code_as_modified(repo: Path) -> None:
    (repo / "apuntes.txt").write_text("nada\n", encoding="utf-8")
    assert capture_environment(repo, NO_VARIABLES)["code_modified"] == "false"


def test_outside_a_repository_there_is_no_commit(tmp_path: Path) -> None:
    folder = tmp_path / "suelto"
    folder.mkdir()
    found = capture_environment(folder, NO_VARIABLES)
    assert "commit" not in found
    assert "code_modified" not in found


def test_the_machine_is_recorded_without_inventing_zeros() -> None:
    found = capture_environment(Path(), NO_VARIABLES)
    assert int(found["cpu_cores"]) > 0
    assert float(found["memory_gb"]) > 0
    assert re.fullmatch(r"\d+\.\d", found["memory_gb"])
    assert found.get("cpu", "x").strip() != ""
    assert "host" not in found
    assert all(isinstance(value, str) for value in found.values())


def test_the_memory_recorded_is_the_total_of_the_machine_not_the_free_part() -> None:
    total = total_memory_bytes()
    available = available_memory_bytes()
    assert total is not None
    assert available is not None
    assert total > available
    recorded = float(capture_environment(Path(), NO_VARIABLES)["memory_gb"])
    assert abs(recorded - total / 1024**3) < 0.1


def test_without_a_declaration_the_location_is_local() -> None:
    found = capture_environment(Path(), NO_VARIABLES)
    assert found["location"] == "local"
    assert not {"cloud_provider", "machine_type", "region"} & found.keys()


def test_a_declared_cloud_can_be_any_provider() -> None:
    found = capture_environment(
        Path(),
        {
            "SEMAFORO_UBICACION": "nube",
            "SEMAFORO_NUBE_PROVEEDOR": "Nube Ejemplo",
            "SEMAFORO_NUBE_TIPO_MAQUINA": "tipo-4x16",
            "SEMAFORO_NUBE_REGION": "sa-este-1",
        },
    )
    assert found["location"] == "cloud"
    assert found["cloud_provider"] == "Nube Ejemplo"
    assert found["machine_type"] == "tipo-4x16"
    assert found["region"] == "sa-este-1"


def test_a_declared_cloud_without_provider_says_it_is_unidentified() -> None:
    found = capture_environment(Path(), {"SEMAFORO_UBICACION": "NUBE"})
    assert (found["location"], found["cloud_provider"]) == ("cloud", "no identificado")
    assert not {"machine_type", "region"} & found.keys()


def test_a_declared_local_ignores_the_cloud_details() -> None:
    found = capture_environment(
        Path(), {"SEMAFORO_UBICACION": "local", "SEMAFORO_NUBE_PROVEEDOR": "Nube Ejemplo"}
    )
    assert found["location"] == "local"
    assert "cloud_provider" not in found


def test_a_declaration_that_is_neither_local_nor_cloud_records_no_location() -> None:
    found = capture_environment(Path(), {"SEMAFORO_UBICACION": "marte"})
    assert not {"location", "cloud_provider", "machine_type", "region"} & found.keys()


def test_a_machine_that_presents_itself_as_a_known_cloud_is_not_taken_for_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = {"sys_vendor": "Amazon EC2", "product_name": "tipo-ejemplo"}
    monkeypatch.setattr(environment, "_dmi", machine_says(facts))
    found = capture_environment(Path(), NO_VARIABLES)
    assert found["location"] == "cloud"
    assert found["cloud_provider"] == "Amazon EC2"
    assert found["machine_type"] == "tipo-ejemplo"


def test_a_declaration_wins_over_what_the_machine_says(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment, "_dmi", machine_says({"sys_vendor": "Amazon EC2"}))
    found = capture_environment(Path(), {"SEMAFORO_UBICACION": "local"})
    assert found["location"] == "local"


def test_texts_are_cleaned_and_limited() -> None:
    found = capture_environment(
        Path(),
        {
            "SEMAFORO_UBICACION": "nube",
            "SEMAFORO_NUBE_PROVEEDOR": "  Nube\tcon\nsaltos\x00 y   espacios  ",
            "SEMAFORO_NUBE_REGION": "r" * 500,
        },
    )
    assert found["cloud_provider"] == "Nube con saltos y espacios"
    assert len(found["region"]) == environment.MAX_TEXT_CHARS


def test_nothing_in_the_record_is_a_path_or_a_host_name() -> None:
    found = capture_environment(Path(), NO_VARIABLES)
    assert not any("\\" in value or "/" in value for key, value in found.items() if key != "cpu")
