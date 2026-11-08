"""Los archivos de conexión del usuario conservan lo de otros proyectos (DEV31 F3; QA34)."""

from pathlib import Path

import pytest

from semaforo.bd import conexion
from semaforo.bd.instalacion import merge_password_lines, merge_service_text

OTHER = [
    "# otro proyecto",
    "localhost:5432:trading_predict:analista:secreto-de-otro",
    "localhost:5432:*:semaforo_lectura:vieja",
]


def test_the_project_lines_are_replaced_and_the_others_kept_in_order() -> None:
    merged = merge_password_lines(OTHER, {"semaforo_lectura": "nueva", "semaforo_carga": "otra"})
    assert merged[:2] == OTHER[:2]
    assert "localhost:5432:*:semaforo_lectura:vieja" not in merged
    assert merged[2:] == [
        "localhost:5432:*:semaforo_lectura:nueva",
        "localhost:5432:*:semaforo_carga:otra",
    ]


def test_an_entry_of_another_database_with_the_same_user_is_not_touched() -> None:
    lines = ["localhost:5432:otra_base:semaforo_carga:ajena"]
    assert merge_password_lines(lines, {"semaforo_carga": "x"})[0] == lines[0]


def test_the_service_file_keeps_other_sections_and_writes_the_four_users() -> None:
    before = "[trading]\nhost=localhost\ndbname=trading_predict\n\n[semaforo_carga]\nuser=viejo\n"
    after = merge_service_text(before, "semaforo")
    assert after.startswith("[trading]\nhost=localhost\ndbname=trading_predict\n")
    assert "user=viejo" not in after
    for role in ("semaforo_admin", "semaforo_carga", "semaforo_lectura", "semaforo_panel"):
        assert f"[{role}]\nhost=localhost\nport=5432\ndbname=semaforo\nuser={role}\n" in after
    assert merge_service_text(after, "semaforo") == after


def test_no_password_goes_to_the_service_file() -> None:
    text = merge_service_text("", "semaforo")
    assert "password" not in text.lower()


def test_the_connection_files_are_outside_the_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PGSERVICEFILE", raising=False)
    monkeypatch.delenv("PGPASSFILE", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    repository = Path(__file__).resolve().parents[2]
    for path in (conexion.service_file(), conexion.password_file()):
        assert repository not in path.resolve().parents


def test_an_unknown_user_is_refused_before_connecting() -> None:
    with pytest.raises(ValueError, match="usuario desconocido"):
        conexion.connect("postgres")
