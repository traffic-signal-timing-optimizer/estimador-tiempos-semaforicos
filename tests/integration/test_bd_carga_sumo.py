"""La carga completa con corridas reales de SUMO (DEV31 F3; QA32, QA34 y QA36).

El ``datos/`` sintético (``cargable``) tiene un caso, un protocolo, un escenario escrito a mano,
cuatro corridas de SUMO con sus métricas y una búsqueda con su etiqueta que usa esas corridas.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from bd_tools import Loadable, copy_workspace, rows_of, scalar
from semaforo.app.bd_commands import register_milestone, verify
from semaforo.bd.carga.motor import LoadOptions, LoadReport, load_workspace
from semaforo.bd.conexion import ADMIN, CARGA, BdError
from semaforo.bd.respaldo import backup, restore
from semaforo.bd.temporales import create_database, drop_database

pytestmark = [pytest.mark.bd, pytest.mark.sumo]

PRELIMINARY = LoadOptions(preliminary=True)


def _status(report: LoadReport) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for unit in report.units:
        found.setdefault(unit.status, []).append(unit.kind)
    return {status: sorted(kinds) for status, kinds in found.items()}


def test_qa32_everything_published_is_loaded_with_its_rows(cargable: Loadable, base: str) -> None:
    report = load_workspace(cargable.workspace, PRELIMINARY, database=base)
    assert report.status == "completed"
    assert _status(report) == {
        "loaded": ["case", "protocol", "run", "run", "run", "run", "scenario", "search"]
    }

    def count(source: str) -> int:
        return int(str(scalar(base, f"SELECT count(*) FROM {source}")))  # noqa: S608

    assert count("simulacion.corridas") == 4
    assert count("simulacion.vehiculos") == 4 * cargable.vehicles_per_run
    assert count("simulacion.resultados_corrida WHERE artefacto_metricas_id IS NOT NULL") == 4
    assert count("simulacion.cola_segundo") > 0
    assert count("simulacion.resultados_acceso") > 0
    assert count("simulacion.busquedas") == count("simulacion.etiquetas") == 1
    assert count("simulacion.candidato_semillas") == 4
    assert count("control.entornos") == 1
    stages = rows_of(base, "SELECT etapa, count(*) FROM simulacion.corridas GROUP BY 1 ORDER BY 1")
    assert stages == [("finalists", 2), ("search", 2)]
    seeds = rows_of(
        base,
        "SELECT s.etapa, c.etapa FROM simulacion.candidato_semillas AS s "
        "JOIN simulacion.corridas AS c ON c.run_id = s.run_id ORDER BY s.semilla",
    )
    assert seeds == [("search", "search")] * 2 + [("finalists", "finalists")] * 2
    plans = scalar(base, "SELECT count(DISTINCT plan_id) FROM simulacion.corridas")
    assert plans == 1
    assert report.content_sha256 is not None
    closed = scalar(
        base, "SELECT estado || ':' || huella_contenido FROM control.cargas", role=ADMIN
    )
    assert closed == f"completed:{report.content_sha256}"


def test_qa32_loading_again_writes_nothing_and_keeps_the_content_hash(
    cargable: Loadable, base: str
) -> None:
    first = load_workspace(cargable.workspace, PRELIMINARY, database=base)
    second = load_workspace(cargable.workspace, PRELIMINARY, database=base)
    assert set(_status(second)) == {"already"}
    assert second.rows_by_table == {}
    assert second.content_sha256 == first.content_sha256
    assert scalar(base, "SELECT count(*) FROM control.cargas") == 2


def test_qa36_a_new_database_from_the_same_files_has_the_same_content_hash(
    cargable: Loadable, base: str
) -> None:
    load_workspace(cargable.workspace, PRELIMINARY, database=base)
    report = verify(cargable.workspace, None, regenerate=True, database=base)
    assert report.regenerated_equal is True
    assert report.status == "intact"
    assert report.roots_changed == []
    assert report.roots_checked >= 8


def test_without_authorization_a_hand_written_scenario_and_what_hangs_from_it_wait(
    cargable: Loadable, base: str
) -> None:
    report = load_workspace(cargable.workspace, LoadOptions(), database=base)
    assert _status(report) == {
        "loaded": ["case", "protocol"],
        "pending": ["run", "run", "run", "run", "scenario", "search"],
    }
    assert scalar(base, "SELECT count(*) FROM simulacion.corridas") == 0


def test_a_run_without_published_metrics_waits_unless_it_is_authorized(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    run_id = cargable.runs[min(cargable.runs)]
    shutil.rmtree(workspace / "derivados" / "metricas" / cargable.case_id / run_id)
    report = load_workspace(workspace, PRELIMINARY, database=base)
    pending = [u for u in report.units if u.status == "pending"]
    assert sorted(u.kind for u in pending) == ["run", "search"]
    assert any("métricas" in str(u.detail) for u in pending)
    allowed = LoadOptions(preliminary=True, without_metrics=True)
    report = load_workspace(workspace, allowed, database=base)
    assert sorted(u.kind for u in report.units if u.status == "loaded") == ["run", "search"]
    empty = scalar(
        base,
        "SELECT count(*) FROM simulacion.resultados_corrida "
        "WHERE run_id = %s AND artefacto_metricas_id IS NULL AND demora_media_s IS NULL",
        (run_id,),
    )
    assert empty == 1


def test_a_file_changed_after_loading_is_a_conflict_and_nothing_else_is_written(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    load_workspace(workspace, PRELIMINARY, database=base)
    case_file = workspace / "casos" / cargable.case_id / "case.json"
    case_file.write_bytes(
        case_file.read_bytes().replace(b'"description": "', b'"description": "X', 1)
    )
    checked = verify(workspace, None, database=base)
    assert checked.status == "changed"
    assert [c.artefacto_id for c in checked.roots_changed] == [
        f"datos:casos/{cargable.case_id}/case.json"
    ]
    before = scalar(base, "SELECT count(*) FROM caso.casos")
    for _ in range(2):  # el mismo conflicto no se registra dos veces
        report = load_workspace(workspace, PRELIMINARY, database=base)
        assert [u.kind for u in report.units if u.status == "rejected"] == ["case"]
    kinds = rows_of(base, "SELECT tipo FROM control.conflictos ORDER BY tipo", CARGA)
    assert kinds == [("hash_mismatch",), ("key_conflict",)]
    assert scalar(base, "SELECT count(*) FROM caso.casos") == before
    # Un archivo de una unidad que se salta rápido (un protocolo) también se compara.
    protocol_file = next((workspace / "derivados" / "protocolos").rglob("*.json"))
    protocol_file.write_bytes(protocol_file.read_bytes() + b"\n")
    report = load_workspace(workspace, PRELIMINARY, database=base)
    assert sorted(u.kind for u in report.units if u.status == "rejected") == ["case", "protocol"]


def test_a_folder_that_cannot_be_read_is_registered_once_as_not_loadable(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    trace = workspace / cargable.label_folder / "traza.json"
    trace.write_bytes(trace.read_bytes() + b" ")
    for _ in range(2):
        report = load_workspace(workspace, PRELIMINARY, database=base)
        assert [u.kind for u in report.units if u.status == "not_loadable"] == ["search"]
    state = rows_of(
        base,
        "SELECT estado FROM control.artefactos WHERE ruta_relativa LIKE %s".replace(
            "%s", f"'{cargable.label_folder}/manifiesto.json'"
        ),
        CARGA,
    )
    assert state == [("not_loadable",)]
    assert scalar(base, "SELECT count(*) FROM control.conflictos WHERE tipo = 'not_loadable'") == 1


def _repository(tmp_path: Path) -> tuple[Path, str]:
    """Un repositorio git con un acta confirmada."""
    repository = tmp_path / "repo"
    (repository / "docs" / "actas").mkdir(parents=True)
    acta = "docs/actas/hito.md"
    (repository / acta).write_text("Acta de prueba del hito.\n", encoding="utf-8")
    git = [
        "git",
        "-c",
        "user.name=prueba",
        "-c",
        "user.email=prueba@example.com",
        "-C",
        str(repository),
    ]
    for arguments in (["init", "-q"], ["add", acta], ["commit", "-q", "-m", "acta"]):
        subprocess.run([*git, *arguments], check=True, capture_output=True)  # noqa: S603
    return repository, acta


def test_a_milestone_is_checked_published_loaded_and_regenerated(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    protocol_file = next((workspace / "derivados" / "protocolos").rglob("*.json"))
    protocol_file.write_bytes(protocol_file.read_bytes().replace(b'"draft"', b'"frozen"', 1))
    repository, acta = _repository(tmp_path)
    options = LoadOptions(preliminary=True, repository=repository)
    load_workspace(workspace, options, database=base)
    milestone, report = register_milestone(
        workspace,
        repository,
        kind="protocol_frozen",
        target=cargable.protocol_id,
        acta=acta,
        responsible="prueba",
        database=base,
    )
    assert [u.status for u in report.units if u.kind == "milestone"] == ["loaded"]
    assert (workspace / "derivados" / "hitos" / milestone / "hito.json").is_file()
    assert rows_of(base, "SELECT hito_id, tipo FROM vistas.estado_hitos") == [
        (milestone, "protocol_frozen")
    ]
    with pytest.raises(BdError, match="rechaza el hito"):
        register_milestone(
            workspace,
            repository,
            kind="protocol_frozen",
            target=cargable.protocol_id,
            acta=acta,
            responsible="prueba",
            database=base,
        )
    assert len(list((workspace / "derivados" / "hitos").iterdir())) == 1
    regenerated = verify(workspace, repository, regenerate=True, database=base)
    assert regenerated.regenerated_equal is True


def test_a_milestone_needs_its_minutes_committed(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    repository, acta = _repository(tmp_path)
    (repository / acta).write_text("cambiada\n", encoding="utf-8")
    with pytest.raises(BdError, match="sin confirmar"):
        register_milestone(
            cargable.workspace,
            repository,
            kind="protocol_frozen",
            target=cargable.protocol_id,
            acta=acta,
            responsible="prueba",
            database=base,
        )


def test_qa36_a_backup_restored_elsewhere_has_the_same_content(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    report = load_workspace(cargable.workspace, PRELIMINARY, database=base)
    saved = backup(tmp_path / "respaldos", database=base)
    assert (tmp_path / "respaldos" / f"{saved.file}.sha256").is_file()
    restored = create_database(schema=False)
    try:
        restore(tmp_path / "respaldos" / saved.file, restored)
        again = verify(cargable.workspace, None, database=restored)
        assert again.content_sha256 == report.content_sha256
    finally:
        drop_database(restored)
    dump = tmp_path / "respaldos" / saved.file
    dump.write_bytes(dump.read_bytes() + b"x")
    with pytest.raises(BdError, match="cambió"):
        restore(dump, "semaforo_pruebas_no_usada")
