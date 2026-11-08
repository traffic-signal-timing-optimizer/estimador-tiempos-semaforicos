"""``bd panel``: publica una foto de la base, de solo lectura, con el rol del panel (DEV31 F5).

El cegado del panel se prueba en ``test_bd_reglas.py``, junto con el barrido; estas pruebas miran la
publicación: qué archivos salen, qué dice el manifiesto y qué avisa.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from bd_tools import Loadable, scalar
from semaforo.app.bd_panel import PROGRESS_FILE, generate_panel, read_progress
from semaforo.bd.carga.motor import LoadOptions, load_workspace
from semaforo.bd.conexion import ADMIN, LECTURA, PANEL, BdError, connect
from semaforo.bd.panel_datos import QUERIES, QUEUE_BIN_S, read_panel_rows
from semaforo.cli.main import main
from semaforo.trazabilidad.hashing import sha256_file

pytestmark = pytest.mark.bd

REPOSITORY = Path(__file__).resolve().parents[2]


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "datos"
    workspace.mkdir()
    return workspace


def _data(folder: Path) -> dict[str, Any]:
    text = (folder / "datos.js").read_text(encoding="utf-8")
    prefix = "window.PANEL_DATA = "
    assert text.startswith(prefix)
    data: dict[str, Any] = json.loads(text[len(prefix) :].rstrip().rstrip(";"))
    return data


def test_the_panel_is_a_new_read_only_folder_with_a_manifest(base: str, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    report = generate_panel(workspace, REPOSITORY, database=base)
    folder = workspace.joinpath(*report.folder.split("/"))
    assert report.folder.startswith("reportes/panel/")
    assert sorted(path.name for path in folder.iterdir()) == [
        "app.js",
        "datos.js",
        "estilos.css",
        "index.html",
        "manifiesto.json",
    ]
    manifest = json.loads((folder / "manifiesto.json").read_text(encoding="utf-8"))
    assert manifest["files"] == {name: sha256_file(folder / name) for name in manifest["files"]}
    assert set(manifest["files"]) == {"app.js", "datos.js", "estilos.css", "index.html"}
    assert manifest["database"] == base
    with pytest.raises(PermissionError):
        (folder / "datos.js").write_text("cambiado", encoding="utf-8")


def test_an_empty_base_gives_a_panel_that_says_so(base: str, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    report = generate_panel(workspace, REPOSITORY, database=base)
    assert report.counts["corridas"] == 0
    assert any("no hay evidencia" in warning for warning in report.warnings)
    data = _data(workspace.joinpath(*report.folder.split("/")))
    assert data["corridas"] == []
    assert data["comparaciones"] == []
    assert data["evidencia"] is None
    assert data["base"]["version_esquema"].startswith("sql-")
    assert data["avance"]["fases"]  # el avance sale del repositorio, no de la base


def test_the_data_has_no_machine_paths(base: str, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    report = generate_panel(workspace, REPOSITORY, database=base)
    folder = workspace.joinpath(*report.folder.split("/"))
    text = (folder / "datos.js").read_text(encoding="utf-8")
    for fragment in (str(tmp_path), tmp_path.as_posix(), str(REPOSITORY), REPOSITORY.as_posix()):
        assert fragment.replace("\\", "\\\\") not in text
        assert fragment not in text
    assert "manifiesto" not in json.loads((folder / "manifiesto.json").read_text(encoding="utf-8"))
    assert not _data(folder)["enlaces"]["datos"].startswith(("C:", "D:", "/"))


def test_the_panel_never_overwrites_a_previous_one(
    base: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    start = datetime(2026, 11, 8, 12, 0, 0, tzinfo=UTC)
    moments = iter(start + timedelta(seconds=second) for second in (0, 0, 1))
    monkeypatch.setattr("semaforo.app.bd_panel.utc_now", lambda: next(moments))
    first = generate_panel(workspace, REPOSITORY, database=base)
    with pytest.raises(FileExistsError):
        generate_panel(workspace, REPOSITORY, database=base)
    assert generate_panel(workspace, REPOSITORY, database=base).folder != first.folder


def test_a_base_without_the_panel_views_is_refused_with_its_reason(
    base: str, tmp_path: Path
) -> None:
    with connect(ADMIN, database=base, autocommit=True) as connection:
        connection.execute("DROP VIEW vistas.caso_resumen")
    with pytest.raises(BdError, match="no tiene las vistas del panel"):
        generate_panel(_workspace(tmp_path), REPOSITORY, database=base)


def test_the_panel_role_only_reads_and_cannot_write(base: str) -> None:
    assert read_panel_rows(base)["corridas"] == []
    with connect(PANEL, database=base, autocommit=True) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("CREATE TABLE vistas.intruso (x integer)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM control.cargas")
        with pytest.raises(psycopg.Error):  # ni permiso ni una vista que se pueda borrar
            connection.execute("DELETE FROM vistas.corridas_resumen")


def test_the_panel_reads_with_its_own_role_not_with_a_wider_one(base: str, tmp_path: Path) -> None:
    with connect(ADMIN, database=base, autocommit=True) as connection:
        connection.execute("REVOKE SELECT ON vistas.caso_resumen FROM semaforo_panel")
    with pytest.raises(BdError, match="no tiene las vistas del panel"):
        generate_panel(_workspace(tmp_path), REPOSITORY, database=base)


@pytest.mark.sumo
def test_real_runs_reach_the_panel_with_their_origin_and_their_queue(
    cargable: Loadable, base: str
) -> None:
    load_workspace(cargable.workspace, LoadOptions(preliminary=True), database=base)
    rows = read_panel_rows(base)
    assert len(rows["corridas"]) == 4
    assert {row["run_id"] for row in rows["procedencia"]} == set(cargable.runs.values())
    for row in rows["procedencia"]:
        assert row["manifiesto"].endswith("manifest.json")
        assert len(row["manifiesto_sha256"]) == 64
        assert len(row["metricas_sha256"]) == 64
        assert row["protocolo_metricas_id"] == cargable.protocol_id
    assert rows["busquedas"]
    assert rows["candidatos"]
    assert rows["demanda"]
    # El promedio por intervalo que muestra el panel es el de la cola segundo a segundo.
    run_id = sorted(rows["cola"])[0]
    queue = rows["cola"][run_id]
    access = sorted(queue["accesos"])[0]
    assert len(queue["desde_s"]) == len(queue["accesos"][access])
    start = queue["desde_s"][1]
    raw = scalar(
        base,
        "SELECT avg(vehiculos_en_cola)::double precision FROM vistas.cola_por_segundo "
        "WHERE run_id = %s AND acceso = %s AND tiempo_s >= %s AND tiempo_s < %s",
        (run_id, access, start, start + QUEUE_BIN_S),
        role=LECTURA,
    )
    assert isinstance(raw, float)
    assert queue["accesos"][access][1] == pytest.approx(raw, abs=0.01)


def test_every_query_reads_only_approved_views() -> None:
    for name, query in QUERIES.items():
        assert " FROM vistas." in query, name


def test_a_latest_evidence_of_another_base_is_said_out_loud(base: str, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    folder = workspace / "reportes" / "bd" / "20260101T000000Z"
    folder.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "status": "ok",
        "exit_code": 0,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "database": "semaforo",
        "version_esquema": "sql-de-otra-version",
        "content_sha256": "0" * 64,
        "rules_sha256": "0" * 64,
        "commit": None,
        "repository_clean": True,
        "folder": "reportes/bd/20260101T000000Z",
        "sections": [
            {
                "name": "verificar",
                "file": None,
                "state": "ok",
                "exit_code": 0,
                "detail": "143 filas",
            }
        ],
        "files": {},
    }
    (folder / "manifiesto.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = generate_panel(workspace, REPOSITORY, database=base)
    assert any("otra versión de la base" in warning for warning in report.warnings)
    data = _data(workspace.joinpath(*report.folder.split("/")))
    assert data["evidencia"]["de_esta_base"] is False
    assert data["evidencia"]["secciones"] == [{"nombre": "verificar", "estado": "ok"}]
    assert "143 filas" not in json.dumps(data)  # los conteos de la evidencia no pasan al panel


def test_the_command_line_publishes_and_exits_0(
    base: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    code = main(
        [
            *("bd", "panel", "--workspace", str(workspace), "--base", base),
            *("--repositorio", str(REPOSITORY)),
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert (code, out["status"]) == (0, "published")
    assert workspace.joinpath(*out["folder"].split("/"), "index.html").is_file()


# --- el avance del proyecto ------------------------------------------------------------------


def test_the_progress_of_the_project_is_valid_and_every_minutes_exists() -> None:
    progress, warnings = read_progress(REPOSITORY)
    assert warnings == []
    assert progress["proyecto"]["objetivo"]
    phases = progress["fases"]
    assert phases
    for phase in phases:
        assert phase["estado"] in {"hecho", "en_curso", "pendiente"}, phase["id"]
        assert phase["titulo"], phase["id"]
        if phase["estado"] == "hecho":
            assert phase.get("acta"), f"{phase['id']} está hecho y no tiene acta"
            assert phase.get("fecha"), phase["id"]
    assert (REPOSITORY / PROGRESS_FILE).is_file()


def test_a_minutes_that_does_not_exist_or_a_strange_state_is_warned(tmp_path: Path) -> None:
    path = tmp_path / PROGRESS_FILE
    path.parent.mkdir(parents=True)
    path.write_text(
        '[[fase]]\nid = "X"\ntitulo = "t"\nestado = "raro"\nacta = "docs/no-existe.md"\n',
        encoding="utf-8",
    )
    _, warnings = read_progress(tmp_path)
    assert any("estado desconocido" in warning for warning in warnings)
    assert any("no existe el acta" in warning for warning in warnings)


def test_without_a_progress_file_the_panel_still_works_and_says_it(tmp_path: Path) -> None:
    progress, warnings = read_progress(tmp_path)
    assert progress["fases"] == []
    assert warnings
