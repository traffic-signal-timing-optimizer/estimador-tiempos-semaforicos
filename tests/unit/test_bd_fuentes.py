"""El catálogo de lo publicado en ``datos/`` (DEV31 F4c, C1.1): una sola forma de recorrerlo."""

import json
from pathlib import Path

import pytest

from semaforo.bd.carga.fuentes import discover, grouped, metrics_manifest
from semaforo.trazabilidad.fs import INCOMPLETE_DIR, TEMP_PREFIX


def _touch(path: Path, text: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "datos"
    _touch(root / "casos" / "caso-001" / "case.json")
    _touch(root / "casos" / "sin-caso" / "otro.xml")  # una carpeta sin case.json no es un caso
    _touch(root / "derivados" / "protocolos" / "caso-001" / "p1.json")
    _touch(root / "derivados" / "protocolos" / "caso-001" / "leeme.txt")
    _touch(root / "escenarios" / "caso-001" / "S1.json", json.dumps({"scenario_id": "S1"}))
    _touch(root / "escenarios" / "caso-001" / "rutas.json", json.dumps({"routes": []}))
    _touch(root / "escenarios" / "caso-001" / "roto.json", "{no es json")
    _touch(root / "ejecuciones" / "RUN-1" / "manifest.json")
    _touch(root / "ejecuciones" / "RUN-2" / "manifest.json")
    _touch(root / "ejecuciones" / f"{TEMP_PREFIX}RUN-3" / "manifest.json")
    _touch(root / "ejecuciones" / INCOMPLETE_DIR / "RUN-4" / "manifest.json")
    _touch(root / "ejecuciones" / ".oculta" / "manifest.json")
    _touch(root / "derivados" / "metricas" / "caso-001" / "RUN-1" / "manifiesto.json")
    _touch(root / "derivados" / "escenarios" / "caso-001" / "conjunto-1" / "manifiesto.json")
    _touch(root / "derivados" / "particiones" / "caso-001" / "particion-1" / "manifiesto.json")
    _touch(root / "derivados" / "referencias" / "caso-001" / "busqueda-1" / "manifiesto.json")
    _touch(root / "derivados" / "comparadores" / "caso-001" / "comp-1" / "manifiesto.json")
    _touch(root / "derivados" / "hitos" / "hito-1" / "manifiesto.json")
    _touch(root / "derivados" / "decisiones" / "decision-1" / "manifiesto.json")
    return root


def _keys(workspace: Path, kind: str) -> list[str]:
    return [source.key for source in discover(workspace).of(kind)]


def test_each_family_is_listed_with_its_key_and_main_file(workspace: Path) -> None:
    found = discover(workspace)
    assert _keys(workspace, "case") == ["caso:caso-001"]
    assert found.of("case")[0].main == "casos/caso-001/case.json"
    assert _keys(workspace, "protocol") == ["protocolo:derivados/protocolos/caso-001/p1.json"]
    assert _keys(workspace, "scenario") == ["escenario:escenarios/caso-001/S1.json"]
    assert _keys(workspace, "scenario_set") == ["conjunto:derivados/escenarios/caso-001/conjunto-1"]
    assert _keys(workspace, "split") == ["particion:derivados/particiones/caso-001/particion-1"]
    assert _keys(workspace, "search") == ["busqueda:derivados/referencias/caso-001/busqueda-1"]
    assert _keys(workspace, "comparators") == [
        "comparadores:derivados/comparadores/caso-001/comp-1"
    ]
    assert _keys(workspace, "milestone") == ["hito:hito-1"]
    assert _keys(workspace, "decision") == ["decision:decision-1"]


def test_only_scenarios_count_as_scenarios_and_temporary_runs_are_left_out(workspace: Path) -> None:
    assert _keys(workspace, "scenario") == ["escenario:escenarios/caso-001/S1.json"]
    assert discover(workspace).keys("run") == {"corrida:RUN-1", "corrida:RUN-2"}


def test_a_run_with_published_metrics_has_both_manifests_as_main_files(workspace: Path) -> None:
    runs = {source.name: source for source in discover(workspace).of("run")}
    assert runs["RUN-1"].mains == (
        "ejecuciones/RUN-1/manifest.json",
        "derivados/metricas/caso-001/RUN-1/manifiesto.json",
    )
    assert runs["RUN-2"].mains == ("ejecuciones/RUN-2/manifest.json",)
    assert metrics_manifest(workspace, "RUN-2") is None


def test_a_new_family_member_shows_up_for_every_reader_at_once(workspace: Path) -> None:
    before = discover(workspace).keys("run")
    _touch(workspace / "ejecuciones" / "RUN-9" / "manifest.json")
    assert discover(workspace).keys("run") == before | {"corrida:RUN-9"}


def test_grouped_lists_folders_two_levels_down_in_order(workspace: Path) -> None:
    assert grouped(workspace, "derivados/comparadores") == [
        "derivados/comparadores/caso-001/comp-1"
    ]


def test_an_empty_or_missing_workspace_lists_nothing(tmp_path: Path) -> None:
    assert discover(tmp_path / "no-existe").items == ()
