"""Los conjuntos de escenarios en la revisión del espacio de trabajo (DEV11 F4, decisión D11)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from scenario_tools import SEED, the_case, the_spec
from semaforo.app.integrity import verify_workspace, workspace_exit_code
from semaforo.datos.scenario_set import SCENARIO_SETS, PublishedSet, publish_scenario_set
from workspace_tools import tamper

CLOCK = datetime(2026, 11, 2, 14, 0, 7, tzinfo=UTC)


def publish(workspace: Path, hours: int = 0) -> PublishedSet:
    when = CLOCK + timedelta(hours=hours)
    return publish_scenario_set(workspace, the_case(), the_spec(), SEED, clock=lambda: when)


def scenario_items(workspace: Path) -> list[tuple[str, str]]:
    report = verify_workspace(workspace)
    return [(item.path, item.status) for item in report.items if item.family == "scenarios"]


def test_the_scenario_sets_live_in_the_derived_folder() -> None:
    assert SCENARIO_SETS == "derivados/escenarios"


def test_a_published_set_is_checked_and_intact(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    published = publish(workspace)
    path = published.folder.relative_to(workspace).as_posix()
    assert scenario_items(workspace) == [(path, "intact")]
    report = verify_workspace(workspace)
    assert report.status == "intact"
    assert workspace_exit_code(report) == 0


def test_every_set_of_every_case_is_checked(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    publish(workspace)
    publish(workspace, hours=2)
    assert [status for _, status in scenario_items(workspace)] == ["intact", "intact"]


def test_a_changed_scenario_makes_the_workspace_altered(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    published = publish(workspace)
    tamper(published.folder / "escenarios" / "FAM_PUNTA-V01-S01.json")
    [(path, status)] = scenario_items(workspace)
    assert status == "altered"
    report = verify_workspace(workspace)
    assert report.status == "altered"
    assert workspace_exit_code(report) == 5
    [item] = [i for i in report.items if i.family == "scenarios"]
    assert item.detail is not None
    assert "HASH_MISMATCH" in item.detail
    assert path == published.folder.relative_to(workspace).as_posix()


def test_a_changed_demand_file_makes_the_workspace_altered(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    published = publish(workspace)
    tamper(published.folder / "demanda" / "FAM_VALLE-V02-S02.csv")
    assert [status for _, status in scenario_items(workspace)] == ["altered"]


def test_the_scenarios_written_by_hand_are_not_part_of_the_check(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    by_hand = workspace / "escenarios" / "caso-001"
    by_hand.mkdir(parents=True)
    (by_hand / "ESC-SINT-001.json").write_text("{}", encoding="utf-8")
    (by_hand / "rutas.json").write_text("{}", encoding="utf-8")
    publish(workspace)
    report = verify_workspace(workspace)
    assert report.counts["unknown"] == 0
    assert [status for _, status in scenario_items(workspace)] == ["intact"]


def test_a_loose_file_in_the_sets_folder_is_unknown(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    publish(workspace)
    (workspace / SCENARIO_SETS / "NOTAS.txt").write_text("x", encoding="utf-8")
    items = scenario_items(workspace)
    assert (f"{SCENARIO_SETS}/NOTAS.txt", "unknown") in items


def test_a_temporary_publication_is_reported_but_does_not_alter_the_status(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "datos"
    publish(workspace)
    (workspace / SCENARIO_SETS / "SYNTHETIC_DEMO" / ".tmp-x").mkdir()
    report = verify_workspace(workspace)
    assert report.status == "intact"
    assert report.counts["temporary"] == 1
