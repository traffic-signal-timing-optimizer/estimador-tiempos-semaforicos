"""QA34 de la base: contraseñas fuera del repositorio y bases ajenas intocables (DEV31 F3)."""

import re
import subprocess
from pathlib import Path

import pytest

from semaforo.bd import conexion
from semaforo.bd.conexion import BdError
from semaforo.bd.instalacion import InstallReport, Step
from semaforo.bd.temporales import drop_database
from semaforo.dominio.errors import ErrorCode

ROOT = Path(__file__).resolve().parents[2]
PGPASS_LINE = re.compile(r"^[^:\s]+:\d+:[^:\s]*:semaforo_(admin|carga|lectura):\S+", re.MULTILINE)
SECRET = "Secreto-de-prueba-42"  # noqa: S105  (inventada: se comprueba que no aparezca)


def _tracked() -> list[Path]:
    listed = subprocess.run(  # noqa: S603
        ["git", "-C", str(ROOT), "ls-files"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines()
    return [ROOT / name for name in listed]


def test_no_tracked_file_holds_a_password_line_of_the_project() -> None:
    offenders: list[str] = []
    for path in _tracked():
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if PGPASS_LINE.search(text):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_the_installation_report_only_says_what_happened_to_the_password_file() -> None:
    """El informe de «bd iniciar» dice si el archivo de contraseñas se creó o no, nunca su
    contenido: ningún campo puede llevar un texto libre que contenga una contraseña."""
    for name, field in InstallReport.model_fields.items():
        if "pass" in name or "secret" in name or "clave" in name:
            assert field.annotation == Step, name


@pytest.mark.parametrize(
    "name", ["semaforo", "tickers_report_db", "trading_predict", "semaforo_pruebas_x; DROP"]
)
def test_only_scratch_databases_can_be_dropped(name: str) -> None:
    with pytest.raises(BdError) as raised:
        drop_database(name)
    assert raised.value.code == ErrorCode.PATH_NOT_ALLOWED


def test_a_connection_error_never_shows_the_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    services = tmp_path / "servicios.conf"
    services.write_text(
        f"[semaforo_lectura]\nhost=localhost\nport=1\ndbname=nada\nuser=nadie\npassword={SECRET}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PGSERVICEFILE", str(services))
    with pytest.raises(BdError) as raised:
        conexion.connect(conexion.LECTURA)
    assert raised.value.code == ErrorCode.DEPENDENCY_MISSING
    assert SECRET not in str(raised.value)
    assert SECRET not in raised.value.message
