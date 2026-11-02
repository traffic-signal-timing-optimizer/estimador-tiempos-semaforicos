"""Partición publicada e inmutable, manifiesto y lectura verificada (DEV12 F3, D8, D10)."""

import json
import os
import shutil
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scenario_tools import publish_set
from semaforo.aprendizaje import split_store as module
from semaforo.aprendizaje.split_store import (
    MANIFEST_FILE,
    SPLITS,
    PublishedSplit,
    publish_split,
    read_split,
    validate_split,
)
from semaforo.aprendizaje.splits import PROVISIONAL_POLICY
from semaforo.datos.scenario_set import ScenarioSet, read_scenario_set
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.split import (
    Proportions,
    SplitInvalidError,
    SplitPolicy,
    parse_split,
)
from semaforo.trazabilidad.hashing import sha256_bytes
from workspace_tools import writable

NOW = datetime(2026, 11, 2, 15, 30, 0, tzinfo=UTC)
SEED = 7
APPROVED = SplitPolicy(
    policy_id="mi_politica", proportions=Proportions(train=0.5, validation=0.25, test=0.25)
)


def prepared(tmp_path: Path, families: int = 5) -> tuple[Path, ScenarioSet]:
    workspace = tmp_path / "datos"
    return workspace, read_scenario_set(publish_set(workspace, families).folder)


def publish(
    tmp_path: Path, policy: SplitPolicy = PROVISIONAL_POLICY, seed: int = SEED
) -> tuple[PublishedSplit, ScenarioSet]:
    workspace, scenario_set = prepared(tmp_path)
    return publish_split(workspace, scenario_set, policy, seed, clock=lambda: NOW), scenario_set


def editable_copy(published: PublishedSplit, tmp_path: Path) -> Path:
    target = tmp_path / "copia"
    shutil.copytree(published.folder, target)
    for path in [target, *target.rglob("*")]:
        writable(path)
    return target


def manifest_of(folder: Path) -> dict[str, Any]:
    return json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))


def save_manifest(folder: Path, manifest: dict[str, Any]) -> None:
    writable(folder / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def split_data(folder: Path) -> dict[str, Any]:
    return json.loads((folder / "split.json").read_text(encoding="utf-8"))


def put_split(folder: Path, data: dict[str, Any], *, fix_manifest: bool = False) -> None:
    """Escribe ``split.json`` y deja la huella del manifiesto al día; opcionalmente, también los
    grupos y las cantidades, para probar solo lo que mira ``validate``."""
    raw = (json.dumps(data, indent=2) + "\n").encode()
    writable(folder / "split.json").write_bytes(raw)
    manifest = manifest_of(folder)
    manifest["files"]["split.json"] = sha256_bytes(raw)
    if fix_manifest:
        groups: dict[str, set[str]] = {"train": set(), "validation": set(), "test": set()}
        for assignment in data["assignments"]:
            groups[assignment["partition"]].add(assignment["group_id"])
        manifest["groups"] = {k: sorted(v) for k, v in groups.items()}
        counts = Counter(a["partition"] for a in data["assignments"])
        manifest["scenarios"] = {k: counts.get(k, 0) for k in groups}
    save_manifest(folder, manifest)


def read_error(folder: Path) -> DomainError:
    with pytest.raises(DomainError) as raised:
        read_split(folder)
    return raised.value


# --- publicar ---------------------------------------------------------------------------------


def test_the_split_is_published_in_a_folder_named_after_the_set_hash(tmp_path: Path) -> None:
    published, scenario_set = publish(tmp_path)
    expected = (
        tmp_path / "datos" / SPLITS / "SYNTHETIC_DEMO" / scenario_set.manifest.content_id[:16]
    )
    assert published.folder == expected
    assert sorted(p.name for p in published.folder.iterdir()) == ["manifiesto.json", "split.json"]


def test_the_split_file_follows_the_contract_and_is_frozen(tmp_path: Path) -> None:
    published, scenario_set = publish(tmp_path)
    split = parse_split(split_data(published.folder))
    assert split == published.split
    assert split.frozen is True
    assert split.split_id == f"split-{scenario_set.manifest.content_id[:16]}"
    assert split.seed == SEED
    assert len(split.assignments) == 20


def test_the_manifest_records_the_set_the_policy_and_the_counts(tmp_path: Path) -> None:
    published, scenario_set = publish(tmp_path)
    manifest = published.manifest
    assert manifest.schema_version == "1.0.0"
    assert (manifest.case_id, manifest.case_version) == ("SYNTHETIC_DEMO", "1.0.0")
    assert manifest.scenario_set_content_id == scenario_set.manifest.content_id
    assert (manifest.policy_id, manifest.provisional, manifest.seed) == (
        "family_holdout",
        True,
        SEED,
    )
    assert manifest.proportions == PROVISIONAL_POLICY.proportions
    assert manifest.created_at == NOW
    assert manifest.scenarios == {"train": 12, "validation": 4, "test": 4}
    assert {k: len(v) for k, v in manifest.groups.items()} == {
        "train": 3,
        "validation": 1,
        "test": 1,
    }
    raw = (published.folder / "split.json").read_bytes()
    assert manifest.files == {"split.json": sha256_bytes(raw)}


def test_the_groups_in_the_manifest_are_sorted_and_match_the_split(tmp_path: Path) -> None:
    published, _ = publish(tmp_path)
    for partition, groups in published.manifest.groups.items():
        assert groups == sorted(groups)
        found = {a.group_id for a in published.split.assignments if a.partition == partition}
        assert set(groups) == found


def test_an_approved_policy_is_recorded_as_not_provisional(tmp_path: Path) -> None:
    published, _ = publish(tmp_path, APPROVED)
    assert published.manifest.provisional is False
    assert published.manifest.policy_id == "mi_politica"
    assert published.manifest.proportions == APPROVED.proportions
    assert "provisionales" not in published.split.policy


def test_the_published_files_are_read_only(tmp_path: Path) -> None:
    published, _ = publish(tmp_path)
    for path in published.folder.iterdir():
        assert not os.access(path, os.W_OK)


def test_a_set_gets_one_split_only_so_the_test_is_reserved_once(tmp_path: Path) -> None:
    workspace, scenario_set = prepared(tmp_path)
    first = publish_split(workspace, scenario_set, PROVISIONAL_POLICY, SEED, clock=lambda: NOW)
    before = (first.folder / "split.json").read_bytes()
    for seed, policy in ((SEED, PROVISIONAL_POLICY), (SEED + 1, APPROVED)):
        with pytest.raises(DomainError) as raised:
            publish_split(workspace, scenario_set, policy, seed, clock=lambda: NOW)
        assert raised.value.code is ErrorCode.RUN_EXISTS
        assert "la prueba se reserva una sola vez" in raised.value.message
        assert raised.value.field == "scenarios"
    assert (first.folder / "split.json").read_bytes() == before


def test_another_set_gets_its_own_split(tmp_path: Path) -> None:
    workspace, scenario_set = prepared(tmp_path)
    first = publish_split(workspace, scenario_set, PROVISIONAL_POLICY, SEED, clock=lambda: NOW)
    other = read_scenario_set(publish_set(workspace, 5, seed=SEED + 1).folder)
    second = publish_split(workspace, other, PROVISIONAL_POLICY, SEED, clock=lambda: NOW)
    assert first.folder != second.folder
    assert first.folder.parent == second.folder.parent


def test_the_same_set_policy_and_seed_give_the_same_split_file_in_another_workspace(
    tmp_path: Path,
) -> None:
    first, _ = publish(tmp_path / "a")
    second, _ = publish(tmp_path / "b")
    assert (first.folder / "split.json").read_bytes() == (second.folder / "split.json").read_bytes()


def test_fewer_than_three_families_publish_nothing(tmp_path: Path) -> None:
    workspace, scenario_set = prepared(tmp_path, families=2)
    with pytest.raises(SplitInvalidError) as raised:
        publish_split(workspace, scenario_set, PROVISIONAL_POLICY, SEED, clock=lambda: NOW)
    assert raised.value.issues[0].rule_id == "SPLIT-C04"
    assert not (workspace / SPLITS).exists()


def test_an_unsafe_case_id_cannot_be_a_folder_name(tmp_path: Path) -> None:
    workspace, scenario_set = prepared(tmp_path)
    manifest = scenario_set.manifest.model_copy(update={"case_id": "../fuera"})
    unsafe = ScenarioSet(manifest, scenario_set.spec, scenario_set.scenarios)
    with pytest.raises(DomainError) as raised:
        publish_split(workspace, unsafe, PROVISIONAL_POLICY, SEED, clock=lambda: NOW)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not (workspace / SPLITS).exists()


def test_publishing_does_not_change_the_set(tmp_path: Path) -> None:
    workspace, scenario_set = prepared(tmp_path)
    before = scenario_set.manifest.model_dump_json()
    publish_split(workspace, scenario_set, PROVISIONAL_POLICY, SEED, clock=lambda: NOW)
    assert scenario_set.manifest.model_dump_json() == before


def test_the_clock_of_the_machine_is_used_by_default(tmp_path: Path) -> None:
    workspace, scenario_set = prepared(tmp_path)
    before = datetime.now(UTC)
    published = publish_split(workspace, scenario_set, PROVISIONAL_POLICY, SEED)
    assert before <= published.manifest.created_at <= datetime.now(UTC)


# --- leer -------------------------------------------------------------------------------------


def test_a_published_split_is_read_back_and_verified(tmp_path: Path) -> None:
    published, _ = publish(tmp_path)
    stored = read_split(published.folder)
    assert stored.manifest == published.manifest
    assert stored.split == published.split


def test_a_changed_split_file_is_detected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    path = folder / "split.json"
    path.write_bytes(path.read_bytes() + b" ")
    error = read_error(folder)
    assert error.code is ErrorCode.HASH_MISMATCH
    assert error.field == "split.json"


def test_a_missing_or_extra_file_is_detected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    (folder / "extra.txt").write_text("x", encoding="utf-8")
    assert read_error(folder).code is ErrorCode.HASH_MISMATCH
    (folder / "extra.txt").unlink()
    (folder / "split.json").unlink()
    assert read_error(folder).code is ErrorCode.HASH_MISMATCH


def test_a_missing_manifest_or_folder_is_reported(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    (folder / MANIFEST_FILE).unlink()
    assert read_error(folder).code is ErrorCode.INPUT_SCHEMA
    assert read_error(tmp_path / "no-existe").code is ErrorCode.INPUT_SCHEMA


def test_a_manifest_with_an_unknown_field_is_rejected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    manifest = manifest_of(folder)
    manifest["extra"] = 1
    save_manifest(folder, manifest)
    assert read_error(folder).code is ErrorCode.INPUT_SCHEMA


def test_a_link_inside_the_folder_is_not_followed(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    outside = tmp_path / "fuera.txt"
    outside.write_text("x", encoding="utf-8")
    try:
        (folder / "enlace.txt").symlink_to(outside)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    assert read_error(folder).code is ErrorCode.PATH_NOT_ALLOWED


def test_a_split_file_that_is_not_json_is_reported(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    raw = b"{no es json"
    writable(folder / "split.json").write_bytes(raw)
    manifest = manifest_of(folder)
    manifest["files"]["split.json"] = sha256_bytes(raw)
    save_manifest(folder, manifest)
    error = read_error(folder)
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert "no es JSON válido" in error.message


def test_a_split_file_over_the_limit_is_rejected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    raw = b" " * (module.MAX_SPLIT_BYTES + 1)
    writable(folder / "split.json").write_bytes(raw)
    manifest = manifest_of(folder)
    manifest["files"]["split.json"] = sha256_bytes(raw)
    save_manifest(folder, manifest)
    assert "demasiado grande" in read_error(folder).message


def test_a_split_file_exactly_at_the_limit_is_not_called_too_big(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    raw = b" " * module.MAX_SPLIT_BYTES
    writable(folder / "split.json").write_bytes(raw)
    manifest = manifest_of(folder)
    manifest["files"]["split.json"] = sha256_bytes(raw)
    save_manifest(folder, manifest)
    assert "demasiado grande" not in read_error(folder).message


def test_a_split_that_is_not_valid_is_reported_with_its_rule(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    data = split_data(folder)
    del data["policy"]
    put_split(folder, data)
    with pytest.raises(SplitInvalidError) as raised:
        read_split(folder)
    assert raised.value.issues[0].rule_id == "SPLIT-S01"


def test_a_group_in_two_partitions_is_rejected_even_with_matching_hashes(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    data = split_data(folder)
    data["assignments"][0]["partition"] = (
        "test" if data["assignments"][0]["partition"] != "test" else "train"
    )
    put_split(folder, data, fix_manifest=True)
    with pytest.raises(SplitInvalidError) as raised:
        read_split(folder)
    assert "SPLIT-C02" in [issue.rule_id for issue in raised.value.issues]


def test_a_split_that_is_not_frozen_is_rejected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    data = split_data(folder)
    data["frozen"] = False
    put_split(folder, data)
    with pytest.raises(SplitInvalidError) as raised:
        read_split(folder)
    assert [issue.rule_id for issue in raised.value.issues] == ["SPLIT-C05"]


def test_a_partition_without_groups_is_rejected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    data = split_data(folder)
    for assignment in data["assignments"]:
        assignment["partition"] = "train"
    put_split(folder, data, fix_manifest=True)
    with pytest.raises(SplitInvalidError) as raised:
        read_split(folder)
    assert {issue.rule_id for issue in raised.value.issues} == {"SPLIT-C04"}


def other_id(m: dict[str, Any]) -> None:
    m["split_id"] = "otro"


def other_seed(m: dict[str, Any]) -> None:
    m["seed"] += 1


def extra_group(m: dict[str, Any]) -> None:
    m["groups"]["test"].append("FAM_XX")


def extra_count(m: dict[str, Any]) -> None:
    m["scenarios"]["test"] += 1


def extra_file(m: dict[str, Any]) -> None:
    m["files"]["otro.json"] = "0" * 64


@pytest.mark.parametrize("change", [other_id, other_seed, extra_group, extra_count, extra_file])
def test_a_manifest_that_disagrees_with_the_split_is_rejected(
    tmp_path: Path, change: Callable[[dict[str, Any]], None]
) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    manifest = manifest_of(folder)
    change(manifest)
    save_manifest(folder, manifest)
    error = read_error(folder)
    assert error.code in (ErrorCode.INPUT_SCHEMA, ErrorCode.HASH_MISMATCH)


def test_a_manifest_that_disagrees_in_the_seed_says_so(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    manifest = manifest_of(folder)
    manifest["seed"] += 1
    save_manifest(folder, manifest)
    assert "no coincide con su manifiesto" in read_error(folder).message


def test_reading_does_not_modify_the_folder(tmp_path: Path) -> None:
    published, _ = publish(tmp_path)
    before = {p.name: p.read_bytes() for p in published.folder.iterdir()}
    read_split(published.folder)
    assert {p.name: p.read_bytes() for p in published.folder.iterdir()} == before


# --- validar contra el conjunto ---------------------------------------------------------------


def test_a_published_split_validates_against_its_set(tmp_path: Path) -> None:
    published, scenario_set = publish(tmp_path)
    validate_split(read_split(published.folder), scenario_set)


def test_the_split_of_another_set_does_not_validate(tmp_path: Path) -> None:
    published, _ = publish(tmp_path)
    other = read_scenario_set(publish_set(tmp_path / "datos", 5, seed=SEED + 1).folder)
    with pytest.raises(SplitInvalidError) as raised:
        validate_split(read_split(published.folder), other)
    fields = [issue.field for issue in raised.value.issues]
    assert fields[0] == "scenario_set_content_id"
    assert raised.value.issues[0].rule_id == "SPLIT-C01"


@pytest.mark.parametrize("name", ["case_id", "case_version"])
def test_a_split_of_another_case_does_not_validate(tmp_path: Path, name: str) -> None:
    published, scenario_set = publish(tmp_path)
    manifest = scenario_set.manifest.model_copy(update={name: "OTRO"})
    other = ScenarioSet(manifest, scenario_set.spec, scenario_set.scenarios)
    with pytest.raises(SplitInvalidError) as raised:
        validate_split(read_split(published.folder), other)
    assert name in [issue.field for issue in raised.value.issues]


def test_a_scenario_missing_from_the_split_does_not_validate(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    data = split_data(folder)
    missing = data["assignments"].pop()["scenario_id"]
    put_split(folder, data, fix_manifest=True)
    _, scenario_set = prepared(tmp_path / "otra")  # mismo contenido (misma semilla)
    with pytest.raises(SplitInvalidError) as raised:
        validate_split(read_split(folder), scenario_set)
    assert any(missing in issue.message for issue in raised.value.issues)


def test_all_the_rules_run_in_validate(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path)[0], tmp_path)
    data = split_data(folder)
    data["assignments"][0]["group_id"] = "OTRO"
    put_split(folder, data, fix_manifest=True)
    _, scenario_set = prepared(tmp_path / "otra")
    with pytest.raises(SplitInvalidError) as raised:
        validate_split(read_split(folder), scenario_set)
    assert "SPLIT-C03" in [issue.rule_id for issue in raised.value.issues]


def test_the_documented_constants_are_the_ones_in_the_code() -> None:
    assert module.MAX_SPLIT_BYTES == 8 * 1024 * 1024
    assert module.SET_HASH_CHARS == 16
    assert module.SPLIT_FILE == "split.json"
    assert MANIFEST_FILE == "manifiesto.json"
    assert SPLITS == "derivados/particiones"
