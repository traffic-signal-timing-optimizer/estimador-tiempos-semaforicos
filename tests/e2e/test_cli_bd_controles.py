"""Los comandos de control de ``bd`` desde la línea de comandos (DEV31 F4c, C1).

Sin SUMO: una carpeta ``datos/`` mínima y una base temporal. Cada prueba mira el código de salida
(0 todo bien, 4 errores aislados, 5 diferencia o incompleto, 6 sin resultado concluyente) y el
informe en JSON que sale por la salida estándar.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from bd_tools import scalar
from semaforo.bd.respaldo import ficha_path
from semaforo.bd.temporales import drop_database
from semaforo.cli.main import main
from workspace_tools import build_workspace

pytestmark = pytest.mark.bd

HBA_CLOSED = "host all all 127.0.0.1/32 scram-sha-256\nhost all all ::1/128 scram-sha-256\n"
HBA_OPEN = HBA_CLOSED + "host all all 0.0.0.0/0 scram-sha-256\n"


def _run(capsys: pytest.CaptureFixture[str], *arguments: str) -> tuple[int, dict[str, object]]:
    code = main(list(arguments))
    out = capsys.readouterr().out
    return code, json.loads(out)


def _field(report: dict[str, object], name: str) -> dict[str, object]:
    value = report[name]
    assert isinstance(value, dict)
    return value  # pyright: ignore[reportUnknownVariableType]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return build_workspace(tmp_path)[0]


def test_reconciling_an_empty_base_exits_5_and_says_it_is_incomplete(
    workspace: Path, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = _run(
        capsys, "bd", "conciliar", "--workspace", str(workspace), "--base", base, "--sin-recalcular"
    )
    assert (code, report["status"]) == (5, "incomplete")
    assert _field(report, "coverage")["missing"] == 1


def test_loading_then_reconciling_exits_0(
    workspace: Path, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    where = ("--workspace", str(workspace), "--base", base)
    assert _run(capsys, "bd", "cargar", *where)[0] == 0
    code, report = _run(capsys, "bd", "conciliar", *where, "--sin-recalcular")
    assert (code, report["status"]) == (0, "equal")


def test_a_backup_comes_with_its_card_and_the_probe_restores_it_and_exits_0(
    base: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "respaldos"
    code, saved = _run(capsys, "bd", "respaldar", "--base", base, "--carpeta", str(folder))
    assert code == 0
    dump = folder / str(saved["file"])
    assert ficha_path(dump).is_file()
    # La ficha que salió con el respaldo no se reescribe con una que sabe menos.
    assert main(["bd", "ficha", "--respaldo", str(dump)]) != 0
    capsys.readouterr()
    code, probe = _run(capsys, "bd", "probar-respaldo", "--respaldo", str(dump))
    assert code == 0
    assert _field(probe, "restauracion")["estado"] == "exitosa"
    assert _field(probe, "contenido")["estado"] == "coincide"


def test_the_card_of_an_old_backup_is_written_with_what_can_be_read_without_restoring(
    base: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "respaldos"
    _, saved = _run(capsys, "bd", "respaldar", "--base", base, "--carpeta", str(folder))
    dump = folder / str(saved["file"])
    ficha_path(dump).unlink()
    code, card = _run(capsys, "bd", "ficha", "--respaldo", str(dump))
    assert code == 0
    assert _field(card, "sha256")["estado"] == "verificado"
    assert _field(card, "huella_contenido")["estado"] == "no_comprobado"
    code, probe = _run(capsys, "bd", "probar-respaldo", "--respaldo", str(dump))
    assert code == 6  # restaura bien, pero no hay con qué comparar el contenido
    assert _field(probe, "restauracion")["estado"] == "exitosa"


def test_a_backup_whose_file_changed_exits_5_without_restoring(
    base: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "respaldos"
    _, saved = _run(capsys, "bd", "respaldar", "--base", base, "--carpeta", str(folder))
    dump = folder / str(saved["file"])
    dump.with_name(f"{dump.name}.sha256").write_text(f"{'0' * 64}  {dump.name}\n", encoding="utf-8")
    code, probe = _run(capsys, "bd", "probar-respaldo", "--respaldo", str(dump))
    assert code == 5
    assert _field(probe, "restauracion")["estado"] == "no_intentada"


def test_the_network_state_is_read_from_the_file_it_is_given(
    workspace: Path, base: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    where = ("--workspace", str(workspace), "--base", base, "--sin-referencia", "--red")
    closed = tmp_path / "cerrada.conf"
    closed.write_text(HBA_CLOSED, encoding="utf-8")
    _, report = _run(capsys, "bd", "verificar", *where, "--hba", str(closed))
    assert _field(report, "network")["verdict"] == "aislada"
    opened = tmp_path / "abierta.conf"
    opened.write_text(HBA_OPEN, encoding="utf-8")
    _, report = _run(capsys, "bd", "verificar", *where, "--hba", str(opened))
    network = _field(report, "network")
    assert network["verdict"] == "abierta"
    assert network["remote_rules"]


def test_a_decision_without_a_conflict_is_refused(
    workspace: Path, base: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            *("bd", "decidir", "--workspace", str(workspace), "--base", base),
            *("--repositorio", str(tmp_path)),
            *("--ruta", "casos/no-existe/case.json", "--decision", "accepted_risk"),
            *("--motivo", "prueba", "--acta", "docs/actas/x.md", "--responsable", "PO"),
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code != 0
    assert out["code"]


@pytest.fixture
def candidate() -> Iterator[str]:
    name = "semaforo_pruebas_cand_cli"
    yield name
    drop_database(name)


def test_preparing_a_rebuild_validates_a_candidate_and_leaves_the_current_base_alone(
    workspace: Path, base: str, tmp_path: Path, candidate: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = _run(
        capsys,
        *("bd", "reconstruir", "preparar", "--workspace", str(workspace), "--base", base),
        *("--respaldos", str(tmp_path / "respaldos"), "--candidata", candidate),
        *("--repositorio", str(tmp_path), "--sin-referencia"),
    )
    assert (code, report["status"]) == (0, "lista")
    assert report["candidate"] == candidate
    assert scalar(candidate, "SELECT count(*) FROM control.cargas") == 1
