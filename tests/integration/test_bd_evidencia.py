"""``bd evidencia`` y la selección del respaldo (DEV31 F4c, C3.5).

La evidencia une verificación, red, conciliación, cobertura, barrido y respaldo en una carpeta
nueva de solo lectura. Estas pruebas usan una base temporal vacía, un ``datos/`` vacío y un
repositorio git temporal con la referencia de huellas confirmada.
"""

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bd_tools import scalar
from semaforo.app.bd_commands import verify
from semaforo.app.bd_evidencia import (
    EvidenceReport,
    collect_evidence,
    resolve_backup,
    select_backup,
)
from semaforo.bd.conexion import ADMIN, BdError, connect
from semaforo.bd.esquema import installed_version
from semaforo.bd.respaldo import backup
from semaforo.cli.main import main
from semaforo.trazabilidad.hashing import sha256_file
from workspace_tools import build_workspace

pytestmark = pytest.mark.bd

GIT = ["git", "-c", "user.name=prueba", "-c", "user.email=prueba@example.com", "-C"]
HBA_CLOSED = "host all all 127.0.0.1/32 scram-sha-256\nhost all all ::1/128 scram-sha-256\n"
HBA_OPEN = HBA_CLOSED + "host all all 0.0.0.0/0 scram-sha-256\n"
SECTIONS = ["verificar", "red", "conciliar", "cobertura", "barrido", "respaldo"]


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run([*GIT, str(repository), *arguments], check=True, capture_output=True)  # noqa: S603


def _states(report: EvidenceReport) -> dict[str, str]:
    return {section.name: section.state for section in report.sections}


class Setup:
    """Una base vacía con su referencia confirmada en git y un respaldo suyo."""

    def __init__(self, base: str, tmp_path: Path) -> None:
        self.base = base
        self.workspace = tmp_path / "datos"
        self.workspace.mkdir()
        self.repository = tmp_path / "repo"
        (self.repository / "docs" / "bd").mkdir(parents=True)
        _git(self.repository, "init", "-q")
        reference = self.repository / "docs" / "bd" / "huellas.json"
        assert (
            verify(
                self.workspace, None, compare=False, fingerprints=reference, database=base
            ).status
            == "intact"
        )
        _git(self.repository, "add", "docs/bd/huellas.json")
        _git(self.repository, "commit", "-q", "-m", "referencia")
        self.backups = tmp_path / "respaldos"
        saved = backup(self.backups, database=base)
        self.dump = self.backups / saved.file
        self.hba = tmp_path / "pg_hba.conf"
        self.hba.write_text(HBA_CLOSED, encoding="utf-8")

    def evidence(self, **changes: object) -> EvidenceReport:
        options: dict[str, object] = {
            "backup": self.dump,
            "hba": self.hba,
            "database": self.base,
        }
        return collect_evidence(self.workspace, self.repository, **{**options, **changes})  # pyright: ignore[reportArgumentType]


@pytest.fixture
def setup(base: str, tmp_path: Path) -> Setup:
    return Setup(base, tmp_path)


def test_the_evidence_of_a_sound_base_is_all_in_agreement_and_is_published_read_only(
    setup: Setup,
) -> None:
    report = setup.evidence()
    assert [section.name for section in report.sections] == SECTIONS
    assert _states(report) == dict.fromkeys(SECTIONS, "ok")
    assert (report.status, report.exit_code) == ("ok", 0)
    folder = setup.workspace.joinpath(*report.folder.split("/"))
    assert sorted(path.name for path in folder.iterdir()) == [
        "barrido.json",
        "conciliar.json",
        "manifiesto.json",
        "respaldo.json",
        "resumen.txt",
        "verificar.json",
    ]
    # El manifiesto lleva la huella de cada archivo y coincide con lo publicado.
    manifest = json.loads((folder / "manifiesto.json").read_text(encoding="utf-8"))
    assert manifest["files"] == {name: sha256_file(folder / name) for name in manifest["files"]}
    assert set(manifest["files"]) == {
        "barrido.json",
        "conciliar.json",
        "respaldo.json",
        "resumen.txt",
        "verificar.json",
    }
    assert manifest["content_sha256"] == report.content_sha256
    assert manifest["repository_clean"] is True
    assert report.version_esquema is not None and report.version_esquema.startswith("sql-")
    assert "coincide" in (folder / "resumen.txt").read_text(encoding="utf-8")
    with pytest.raises(PermissionError):
        (folder / "verificar.json").write_text("cambiado", encoding="utf-8")
    # La evidencia no escribió nada en la base.
    assert scalar(setup.base, "SELECT count(*) FROM control.cargas") == 0


def test_a_change_in_the_rules_without_touching_a_row_makes_the_evidence_differ(
    setup: Setup,
) -> None:
    with connect(ADMIN, database=setup.base, autocommit=True) as connection:
        connection.execute("ALTER TABLE simulacion.corridas DISABLE TRIGGER solo_agregar")
    report = setup.evidence()
    assert _states(report)["verificar"] == "difiere"
    assert (report.status, report.exit_code) == ("difiere", 5)
    # Las demás comprobaciones se hicieron igual y la evidencia se publicó completa.
    assert _states(report)["barrido"] == "ok"
    assert setup.workspace.joinpath(*report.folder.split("/"), "manifiesto.json").is_file()


def test_without_a_backup_the_backup_section_is_not_concluding(setup: Setup) -> None:
    report = setup.evidence(backup=None)
    assert _states(report)["respaldo"] == "no_concluyente"
    assert (report.status, report.exit_code) == ("no_concluyente", 6)
    folder = setup.workspace.joinpath(*report.folder.split("/"))
    assert not (folder / "respaldo.json").exists()


def test_the_latest_backup_of_the_current_version_is_picked_when_none_is_named(
    setup: Setup,
) -> None:
    report = setup.evidence(backup=None, backups=setup.backups)
    assert _states(report)["respaldo"] == "ok"
    with connect(ADMIN, database=setup.base) as connection:
        version = installed_version(connection)
    assert version is not None
    assert select_backup(setup.backups, version) == setup.dump
    # Con dos respaldos de la misma versión se elige el más reciente por su fecha.
    newer = setup.dump.with_name("29981231T000000Z.dump")
    newer.write_bytes(b"x")
    assert select_backup(setup.backups, version) == newer
    newer.unlink()
    # Un respaldo más nuevo, pero de otra versión del esquema, no se elige.
    other = setup.backups / "sql-0000000000000000"
    other.mkdir()
    (other / "29990101T000000Z.dump").write_bytes(b"x")
    assert select_backup(setup.backups, version) == setup.dump
    with pytest.raises(BdError, match="no hay un respaldo"):
        select_backup(setup.backups, "sql-ffffffffffffffff")
    assert resolve_backup(setup.dump, None, setup.base) == setup.dump
    with pytest.raises(BdError, match="indique --respaldo o --respaldos"):
        resolve_backup(None, None, setup.base)


def test_an_open_network_rule_makes_the_evidence_differ(setup: Setup) -> None:
    setup.hba.write_text(HBA_OPEN, encoding="utf-8")
    report = setup.evidence()
    assert _states(report)["red"] == "difiere"
    assert report.exit_code == 5


def test_every_run_publishes_a_new_folder_and_never_overwrites(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    moments = iter(
        datetime(2026, 11, 8, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=second)
        for second in (0, 0, 1)
    )
    monkeypatch.setattr("semaforo.app.bd_evidencia.utc_now", lambda: next(moments))
    first = setup.evidence()
    with pytest.raises(FileExistsError):  # el mismo segundo: no se pisa la anterior
        setup.evidence()
    second = setup.evidence()
    assert first.folder != second.folder
    folders = sorted(path.name for path in setup.workspace.joinpath("reportes", "bd").iterdir())
    assert folders == ["20261108T120000Z", "20261108T120001Z"]


def test_the_command_line_prints_the_report_and_exits_with_its_code(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            *("bd", "evidencia", "--workspace", str(setup.workspace), "--base", setup.base),
            *("--repositorio", str(setup.repository), "--respaldo", str(setup.dump)),
            *("--hba", str(setup.hba)),
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert (code, out["status"], out["exit_code"]) == (0, "ok", 0)
    assert [section["name"] for section in out["sections"]] == SECTIONS


def test_probing_a_backup_without_naming_it_takes_the_latest_of_the_current_version(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["bd", "probar-respaldo", "--respaldos", str(setup.backups), "--base", setup.base])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["archivo"] == setup.dump.name
    assert main(["bd", "probar-respaldo", "--base", setup.base]) != 0  # sin ninguna de las dos
    capsys.readouterr()


def test_what_is_published_but_not_loaded_makes_the_coverage_differ(
    setup: Setup, tmp_path: Path
) -> None:
    (tmp_path / "otro").mkdir()
    workspace, _ = build_workspace(tmp_path / "otro")  # tiene un caso que la base no tiene
    report = collect_evidence(
        workspace, setup.repository, backup=setup.dump, hba=setup.hba, database=setup.base
    )
    states = _states(report)
    assert (states["cobertura"], states["conciliar"]) == ("difiere", "difiere")
    detail = next(s.detail for s in report.sections if s.name == "cobertura")
    assert detail is not None and "1 faltan" in detail
    assert report.exit_code == 5


def test_the_evidence_says_when_the_repository_has_unconfirmed_changes(setup: Setup) -> None:
    reference = setup.repository / "docs" / "bd" / "huellas.json"
    reference.write_text(reference.read_text(encoding="utf-8") + " ", encoding="utf-8")
    report = setup.evidence()
    assert report.repository_clean is False
    assert "con cambios sin confirmar" in setup.workspace.joinpath(
        *report.folder.split("/"), "resumen.txt"
    ).read_text(encoding="utf-8")
