"""Pruebas del runner de SUMO que no necesitan SUMO: versión, ubicación, comando y resumen."""

import subprocess
import sys
from pathlib import Path

import pytest

from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.runner import (
    RunLimits,
    find_sumo,
    parse_sumo_version,
    run_simulation,
    summarize_outputs,
    sumo_arguments,
)
from semaforo.trazabilidad.store import RunSpec

STATISTICS = """<?xml version="1.0"?>
<!-- configuración con rutas del equipo: C:\\Users\\alguien\\demo.sumocfg -->
<statistics>
    <performance begin="0.00" end="{end}" duration="{end}"/>
    <vehicles loaded="{loaded}" inserted="{inserted}" running="{running}" waiting="{waiting}"/>
    <teleports total="{teleports}" jam="{teleports}" yield="0" wrongLane="0"/>
    <safety collisions="{collisions}" emergencyStops="0" emergencyBraking="0"/>
    <vehicleTripStatistics count="{inserted}" departDelay="2.50"/>
</statistics>
"""


DEFAULTS = {
    "loaded": 10,
    "inserted": 10,
    "running": 0,
    "waiting": 0,
    "teleports": 0,
    "collisions": 0,
}


def write_outputs(folder: Path, **values: int) -> Path:
    """Escribe salidas sintéticas; ``tripinfos`` y ``unfinished`` las vuelven incoherentes."""
    figures = {**DEFAULTS, **values}
    folder.mkdir(parents=True, exist_ok=True)
    stats = STATISTICS.format(end="916.00", **{k: figures[k] for k in DEFAULTS})
    (folder / "statistics.xml").write_text(stats, encoding="utf-8")
    total = figures.get("tripinfos", figures["inserted"])
    open_trips = figures.get("unfinished", figures["running"])
    rows = [
        f'<tripinfo id="v{i}" arrival="{"-1.00" if i < open_trips else "50.00"}"/>'
        for i in range(total)
    ]
    (folder / "tripinfo.xml").write_text(
        f"<tripinfos>{''.join(rows)}</tripinfos>", encoding="utf-8"
    )
    return folder


def test_parses_the_sumo_version() -> None:
    text = "Eclipse SUMO sumo 1.27.1\n Build features: Windows-10 AMD64\n"
    assert parse_sumo_version(text) == "1.27.1"


def test_an_unrecognised_version_is_a_missing_dependency() -> None:
    with pytest.raises(DomainError) as raised:
        parse_sumo_version("otra cosa")
    assert raised.value.code is ErrorCode.DEPENDENCY_MISSING


@pytest.mark.parametrize("suffix", ["", "/", "\\"])
def test_finds_sumo_from_sumo_home_with_or_without_trailing_slash(
    tmp_path: Path, suffix: str
) -> None:
    binary = tmp_path / "Sumo" / "bin" / "sumo.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    assert find_sumo({"SUMO_HOME": str(tmp_path / "Sumo") + suffix}) == binary


def test_a_missing_sumo_is_a_missing_dependency(tmp_path: Path) -> None:
    with pytest.raises(DomainError) as raised:
        find_sumo({"SUMO_HOME": str(tmp_path / "no-existe")})
    assert raised.value.code is ErrorCode.DEPENDENCY_MISSING
    with pytest.raises(DomainError):
        find_sumo({})


def test_the_command_uses_relative_paths_and_the_end_limit() -> None:
    arguments = sumo_arguments("sub/caso.sumocfg", 7200)
    assert arguments[:4] == ["-c", "inputs/sub/caso.sumocfg", "--end", "7200"]
    assert "outputs/tripinfo.xml" in arguments
    assert "outputs/statistics.xml" in arguments
    assert arguments[arguments.index("--tripinfo-output.write-unfinished") + 1] == "true"
    assert all(not Path(argument).is_absolute() for argument in arguments)


def test_gui_only_file_options_are_neutralized() -> None:
    arguments = sumo_arguments("caso.sumocfg", 60, gui_options=["gui-settings-file"])
    index = arguments.index("--gui-settings-file")
    assert arguments[index + 1] == ""


def test_sumo_warnings_are_counted(tmp_path: Path) -> None:
    folder = write_outputs(tmp_path / "out")
    (folder / "sumo.log").write_text(
        "Warning: phase 6 has no controlling detector.\nLoading done.\nWarning: otro aviso\n",
        encoding="utf-8",
    )
    summary = summarize_outputs(folder, None)
    assert summary.sumo_warnings == 2
    assert [f.code for f in summary.findings] == ["SUMO_WARNINGS"]
    assert summary.demand_unmet is False


def test_limits_must_be_positive() -> None:
    assert RunLimits().end_s == 7200
    assert RunLimits().wall_timeout_s == 900
    for changes in (
        {"end_s": 0},
        {"wall_timeout_s": -1},
        {"smoke_end_s": 0},
        {"max_path_chars": 0},
    ):
        with pytest.raises(ValueError, match="positiv"):
            RunLimits(**changes)


def test_summarizes_a_complete_run(tmp_path: Path) -> None:
    summary = summarize_outputs(write_outputs(tmp_path / "out"), declared_vehicles=10)
    assert (summary.vehicles_loaded, summary.vehicles_inserted) == (10, 10)
    assert (summary.vehicles_running, summary.vehicles_waiting) == (0, 0)
    assert (summary.trips_finished, summary.trips_unfinished) == (10, 0)
    assert summary.simulated_end_s == 916
    assert summary.mean_depart_delay_s == 2.5
    assert summary.demand_unmet is False
    assert summary.findings == []


def test_unmet_demand_is_flagged(tmp_path: Path) -> None:
    outputs = write_outputs(tmp_path / "out", loaded=8, inserted=6, running=2, waiting=2)
    summary = summarize_outputs(outputs, declared_vehicles=10)
    assert summary.demand_unmet is True
    assert [f.code for f in summary.findings] == [
        "LOADED_BELOW_DECLARED",
        "DEMAND_NOT_INSERTED",
        "VEHICLES_STILL_RUNNING",
    ]
    assert (summary.trips_finished, summary.trips_unfinished) == (4, 2)


def test_a_trip_arriving_at_time_zero_is_finished(tmp_path: Path) -> None:
    folder = write_outputs(tmp_path / "out", inserted=1, loaded=1)
    (folder / "tripinfo.xml").write_text(
        '<tripinfos><tripinfo id="v0" arrival="0.00"/></tripinfos>', encoding="utf-8"
    )
    summary = summarize_outputs(folder, None)
    assert (summary.trips_finished, summary.trips_unfinished) == (1, 0)


@pytest.mark.skipif(sys.platform != "win32", reason="las uniones solo existen en Windows")
def test_a_junction_in_the_source_is_refused_before_running(tmp_path: Path) -> None:
    source = tmp_path / "case"
    source.mkdir()
    (source / "demo.sumocfg").write_text("<configuration/>", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = source / "linked"
    subprocess.run(  # noqa: S603
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(elsewhere)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    spec = RunSpec(kind="simulation", case_id="C", case_version="1")
    try:
        with pytest.raises(DomainError) as raised:
            run_simulation(source, "demo.sumocfg", tmp_path / "runs", spec, sumo=tmp_path / "x")
        assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    finally:
        link.rmdir()


def test_teleports_and_collisions_are_flagged(tmp_path: Path) -> None:
    summary = summarize_outputs(write_outputs(tmp_path / "out", teleports=3, collisions=1), None)
    assert [f.code for f in summary.findings] == ["TELEPORTS", "COLLISIONS"]
    assert (summary.teleports_total, summary.teleports_jam, summary.collisions) == (3, 3, 1)
    assert summary.demand_unmet is False


def test_without_declared_demand_only_the_end_state_counts(tmp_path: Path) -> None:
    summary = summarize_outputs(write_outputs(tmp_path / "out", loaded=5, inserted=5), None)
    assert summary.declared_vehicles is None
    assert summary.demand_unmet is False


INCOHERENT = {
    "fewer-tripinfos-than-inserted": {"tripinfos": 9},
    "unfinished-differ-from-running": {"running": 2, "unfinished": 1},
    "inserted-above-loaded": {"loaded": 5, "inserted": 6},
}


@pytest.mark.parametrize("changes", INCOHERENT.values(), ids=INCOHERENT.keys())
def test_incoherent_outputs_are_invalid(tmp_path: Path, changes: dict[str, int]) -> None:
    with pytest.raises(DomainError) as raised:
        summarize_outputs(write_outputs(tmp_path / "out", **changes), None)
    assert raised.value.code is ErrorCode.OUTPUT_INVALID


def test_empty_but_well_formed_outputs_are_invalid(tmp_path: Path) -> None:
    """Una corrida fallida puede dejar XML vacío pero bien formado (acta de F1)."""
    folder = tmp_path / "out"
    folder.mkdir()
    (folder / "statistics.xml").write_text("<statistics/>", encoding="utf-8")
    (folder / "tripinfo.xml").write_text("<tripinfos/>", encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        summarize_outputs(folder, None)
    assert raised.value.code is ErrorCode.OUTPUT_INVALID


@pytest.mark.parametrize("missing", ["statistics.xml", "tripinfo.xml"])
def test_missing_outputs_are_invalid(tmp_path: Path, missing: str) -> None:
    folder = write_outputs(tmp_path / "out")
    (folder / missing).unlink()
    with pytest.raises(DomainError) as raised:
        summarize_outputs(folder, None)
    assert raised.value.code is ErrorCode.OUTPUT_INVALID
