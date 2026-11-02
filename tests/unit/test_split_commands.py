"""Casos de uso de ``splits create`` y ``splits validate`` (DEV12 F3, decisión D11)."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scenario_tools import publish_set, scenarios_of
from semaforo.app.split_commands import (
    MAX_SEED,
    SplitResult,
    create_split_set,
    validate_split_set,
)
from semaforo.aprendizaje.split_store import read_split
from semaforo.aprendizaje.splits import PROVISIONAL_POLICY, create_split
from semaforo.caso.errors import CasoError
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.split import SplitInvalidError
from workspace_tools import tamper, writable

NOW = datetime(2026, 11, 2, 15, 30, 0, tzinfo=UTC)
SEED = 7


def policy_data(**changes: object) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": "1.0.0",
        "policy_id": "mi_politica",
        "proportions": {"train": 0.5, "validation": 0.25, "test": 0.25},
    }
    data.update(changes)
    return data


def write_policy(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "politica.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def prepared(tmp_path: Path, families: int = 5) -> tuple[Path, Path]:
    workspace = tmp_path / "datos"
    return workspace, publish_set(workspace, families).folder


def created(tmp_path: Path, policy_path: Path | None = None) -> tuple[Path, Path, SplitResult]:
    workspace, folder = prepared(tmp_path)
    result = create_split_set(workspace, folder, SEED, policy_path, NOW)
    return workspace, folder, result


# --- create -----------------------------------------------------------------------------------


def test_the_summary_describes_the_published_split(tmp_path: Path) -> None:
    workspace, folder, result = created(tmp_path)
    assert result.status == "published"
    assert (result.case_id, result.policy_id, result.provisional, result.seed) == (
        "SYNTHETIC_DEMO",
        "family_holdout",
        True,
        SEED,
    )
    assert result.groups == {"train": 3, "validation": 1, "test": 1}
    assert result.scenarios == {"train": 12, "validation": 4, "test": 4}
    short = result.scenario_set_content_id[:16]
    assert result.folder == f"derivados/particiones/SYNTHETIC_DEMO/{short}"
    assert result.manifest == f"{result.folder}/manifiesto.json"
    assert (workspace / str(result.manifest)).is_file()
    assert folder.is_dir()


def test_the_summary_has_exactly_the_documented_fields(tmp_path: Path) -> None:
    data = created(tmp_path)[2].model_dump(mode="json")
    assert set(data) == {
        "schema_version",
        "status",
        "split_id",
        "case_id",
        "scenario_set_content_id",
        "policy_id",
        "provisional",
        "seed",
        "groups",
        "scenarios",
        "folder",
        "manifest",
    }
    assert data["schema_version"] == "1.0.0"


def test_the_published_split_reads_back_verified(tmp_path: Path) -> None:
    workspace, _, result = created(tmp_path)
    stored = read_split(workspace / str(result.folder))
    assert stored.manifest.split_id == result.split_id


def test_a_policy_file_sets_the_proportions_and_is_not_provisional(tmp_path: Path) -> None:
    policy = write_policy(tmp_path, policy_data())
    _, _, result = created(tmp_path, policy_path=policy)
    assert (result.policy_id, result.provisional) == ("mi_politica", False)
    assert result.groups == {"train": 3, "validation": 1, "test": 1}


def test_a_policy_file_can_declare_itself_provisional(tmp_path: Path) -> None:
    policy = write_policy(tmp_path, policy_data(provisional=True))
    assert created(tmp_path, policy_path=policy)[2].provisional is True


def test_the_proportions_of_the_policy_change_the_counts(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path, families=8)
    policy = write_policy(
        tmp_path, policy_data(proportions={"train": 0.5, "validation": 0.25, "test": 0.25})
    )
    result = create_split_set(workspace, folder, SEED, policy, NOW)
    assert result.groups == {"train": 4, "validation": 2, "test": 2}


def test_an_invalid_policy_publishes_nothing(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path)
    bad = write_policy(
        tmp_path, policy_data(proportions={"train": 0.5, "validation": 0.2, "test": 0.2})
    )
    with pytest.raises(SplitInvalidError) as raised:
        create_split_set(workspace, folder, SEED, bad, NOW)
    assert raised.value.issues[0].rule_id == "SPLIT-P01"
    assert not (workspace / "derivados" / "particiones").exists()


def test_a_policy_with_an_unknown_field_is_rejected(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path)
    bad = write_policy(tmp_path, policy_data(extra=1))
    with pytest.raises(SplitInvalidError) as raised:
        create_split_set(workspace, folder, SEED, bad, NOW)
    assert raised.value.issues[0].field == "extra"


def test_a_missing_or_unreadable_policy_is_reported(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path)
    with pytest.raises(CasoError) as raised:
        create_split_set(workspace, folder, SEED, tmp_path / "no-existe.json", NOW)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert "política" in raised.value.message
    broken = tmp_path / "rota.json"
    broken.write_text("{no es json", encoding="utf-8")
    with pytest.raises(CasoError):
        create_split_set(workspace, folder, SEED, broken, NOW)


def test_a_policy_that_is_a_link_is_not_followed(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path)
    real = write_policy(tmp_path, policy_data())
    link = tmp_path / "enlace.json"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    with pytest.raises(CasoError) as raised:
        create_split_set(workspace, folder, SEED, link, NOW)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED


@pytest.mark.parametrize("seed", [-1, MAX_SEED + 1])
def test_a_bad_seed_is_reported_and_publishes_nothing(tmp_path: Path, seed: int) -> None:
    workspace, folder = prepared(tmp_path)
    with pytest.raises(SplitInvalidError) as raised:
        create_split_set(workspace, folder, seed, now=NOW)
    assert raised.value.issues[0].field == "seed"
    assert not (workspace / "derivados" / "particiones").exists()


def test_a_set_gets_one_split_only(tmp_path: Path) -> None:
    workspace, folder, _ = created(tmp_path)
    with pytest.raises(DomainError) as raised:
        create_split_set(workspace, folder, SEED + 1, now=NOW)
    assert raised.value.code is ErrorCode.RUN_EXISTS


def test_two_families_cannot_be_split_and_nothing_is_published(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path, families=2)
    with pytest.raises(SplitInvalidError) as raised:
        create_split_set(workspace, folder, SEED, now=NOW)
    assert "hay 2" in raised.value.message
    assert not (workspace / "derivados" / "particiones").exists()


def test_a_set_folder_that_does_not_exist_is_reported(tmp_path: Path) -> None:
    with pytest.raises(DomainError) as raised:
        create_split_set(tmp_path / "datos", tmp_path / "no-existe", SEED, now=NOW)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_an_altered_set_is_refused_before_splitting(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path)
    tamper(folder / "escenarios" / "FAM_01-V01-S01.json")
    with pytest.raises(DomainError) as raised:
        create_split_set(workspace, folder, SEED, now=NOW)
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    assert not (workspace / "derivados" / "particiones").exists()


def test_the_clock_of_the_machine_is_used_when_no_date_is_given(tmp_path: Path) -> None:
    workspace, folder = prepared(tmp_path)
    before = datetime.now(UTC)
    result = create_split_set(workspace, folder, SEED)
    stored = read_split(workspace / str(result.folder))
    assert before <= stored.manifest.created_at <= datetime.now(UTC)


# --- validate ---------------------------------------------------------------------------------


def test_a_published_split_is_valid_against_its_set(tmp_path: Path) -> None:
    workspace, folder, created_result = created(tmp_path)
    result = validate_split_set(workspace / str(created_result.folder), folder)
    assert result.status == "valid"
    assert result.folder is None
    assert result.manifest is None
    assert result.split_id == created_result.split_id
    assert result.groups == created_result.groups
    assert result.scenarios == created_result.scenarios


def test_a_split_does_not_validate_against_another_set(tmp_path: Path) -> None:
    workspace, _, result = created(tmp_path)
    other = publish_set(workspace, 5, seed=SEED + 1).folder
    with pytest.raises(SplitInvalidError) as raised:
        validate_split_set(workspace / str(result.folder), other)
    assert raised.value.issues[0].field == "scenario_set_content_id"


def test_an_altered_split_is_refused(tmp_path: Path) -> None:
    workspace, folder, result = created(tmp_path)
    tamper(workspace / str(result.folder) / "split.json")
    with pytest.raises(DomainError) as raised:
        validate_split_set(workspace / str(result.folder), folder)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_an_altered_set_is_refused_when_validating(tmp_path: Path) -> None:
    workspace, folder, result = created(tmp_path)
    tamper(folder / "spec.json")
    with pytest.raises(DomainError) as raised:
        validate_split_set(workspace / str(result.folder), folder)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_validating_does_not_change_anything(tmp_path: Path) -> None:
    workspace, folder, result = created(tmp_path)
    split_folder = workspace / str(result.folder)
    before = {p.name: p.read_bytes() for p in split_folder.iterdir()}
    validate_split_set(split_folder, folder)
    assert {p.name: p.read_bytes() for p in split_folder.iterdir()} == before


def test_a_copied_split_still_validates(tmp_path: Path) -> None:
    workspace, folder, result = created(tmp_path)
    copy = tmp_path / "copia"
    shutil.copytree(workspace / str(result.folder), copy)
    for path in [copy, *copy.rglob("*")]:
        writable(path)
    assert validate_split_set(copy, folder).status == "valid"


def test_the_seed_limit_is_the_documented_one() -> None:
    assert MAX_SEED == 9223372036854775807


def test_creating_a_split_directly_with_a_bad_seed_names_the_field() -> None:
    with pytest.raises(SplitInvalidError) as raised:
        create_split(scenarios_of(5), PROVISIONAL_POLICY, -5, "SPLIT_T")
    assert (raised.value.issues[0].rule_id, raised.value.issues[0].field) == ("SPLIT-S01", "seed")
    assert "y es -5" in raised.value.issues[0].message


@pytest.mark.parametrize("seed", [0, MAX_SEED])
def test_the_seed_limits_themselves_work(tmp_path: Path, seed: int) -> None:
    workspace, folder = prepared(tmp_path)
    assert create_split_set(workspace, folder, seed, now=NOW).seed == seed


def test_the_date_given_is_the_date_recorded(tmp_path: Path) -> None:
    workspace, _, result = created(tmp_path)
    assert read_split(workspace / str(result.folder)).manifest.created_at == NOW
