"""Las particiones en la revisión del espacio de trabajo (DEV12 F3, decisión D10)."""

from datetime import UTC, datetime
from pathlib import Path

from scenario_tools import publish_set
from semaforo.app.integrity import verify_workspace, workspace_exit_code
from semaforo.aprendizaje.split_store import SPLITS, PublishedSplit, publish_split
from semaforo.aprendizaje.splits import PROVISIONAL_POLICY
from semaforo.datos.scenario_set import read_scenario_set
from workspace_tools import tamper

NOW = datetime(2026, 11, 2, 15, 30, 0, tzinfo=UTC)


def published(workspace: Path, seed: int = 7) -> PublishedSplit:
    scenario_set = read_scenario_set(publish_set(workspace, 5, seed=seed).folder)
    return publish_split(workspace, scenario_set, PROVISIONAL_POLICY, 7, clock=lambda: NOW)


def split_items(workspace: Path) -> list[tuple[str, str]]:
    report = verify_workspace(workspace)
    return [(item.path, item.status) for item in report.items if item.family == "splits"]


def test_the_splits_live_in_the_derived_folder() -> None:
    assert SPLITS == "derivados/particiones"


def test_a_published_split_is_checked_and_intact(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    split = published(workspace)
    path = split.folder.relative_to(workspace).as_posix()
    assert split_items(workspace) == [(path, "intact")]
    report = verify_workspace(workspace)
    assert report.status == "intact"
    assert workspace_exit_code(report) == 0


def test_every_split_of_every_set_is_checked(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    published(workspace, seed=1)
    published(workspace, seed=2)
    assert [status for _, status in split_items(workspace)] == ["intact", "intact"]


def test_a_changed_split_makes_the_workspace_altered(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    split = published(workspace)
    tamper(split.folder / "split.json")
    [(path, status)] = split_items(workspace)
    assert status == "altered"
    report = verify_workspace(workspace)
    assert report.status == "altered"
    assert workspace_exit_code(report) == 5
    [item] = [i for i in report.items if i.family == "splits"]
    assert item.detail is not None
    assert "HASH_MISMATCH" in item.detail
    assert path == split.folder.relative_to(workspace).as_posix()


def test_a_changed_manifest_makes_the_workspace_altered(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    split = published(workspace)
    tamper(split.folder / "manifiesto.json")
    assert [status for _, status in split_items(workspace)] == ["altered"]


def test_a_loose_file_in_the_splits_folder_is_unknown(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    published(workspace)
    (workspace / SPLITS / "NOTAS.txt").write_text("x", encoding="utf-8")
    assert (f"{SPLITS}/NOTAS.txt", "unknown") in split_items(workspace)


def test_a_temporary_publication_is_reported_but_does_not_alter_the_status(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "datos"
    published(workspace)
    (workspace / SPLITS / "SYNTHETIC_DEMO" / ".tmp-x").mkdir()
    report = verify_workspace(workspace)
    assert report.status == "intact"
    assert report.counts["temporary"] == 1


def test_scenario_sets_and_splits_are_both_in_the_report(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    published(workspace)
    report = verify_workspace(workspace)
    assert {item.family: item.status for item in report.items} == {
        "scenarios": "intact",
        "splits": "intact",
    }
