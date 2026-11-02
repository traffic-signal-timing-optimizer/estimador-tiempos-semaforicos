"""Conjunto de escenarios publicado, manifiesto y lectura verificada (DEV11 F4, D9 a D11)."""

import json
import os
import shutil
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from scenario_tools import FIXTURES, SEED, spec_data, the_case, the_spec
from semaforo.datos import scenario_set as module
from semaforo.datos.scenario_demand import ScenarioDemandError
from semaforo.datos.scenario_set import (
    MANIFEST_FILE,
    SCENARIO_SETS,
    PublishedSet,
    publish_scenario_set,
    read_scenario_set,
)
from semaforo.datos.scenarios import generate_scenarios
from semaforo.dominio.case import canonical_sha256, parse_case
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario_spec import SpecInvalidError, parse_spec
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.ids import content_id
from semaforo.trazabilidad.store import TrazabilidadError
from workspace_tools import writable

CLOCK = datetime(2026, 11, 2, 14, 0, 7, tzinfo=UTC)
FIRST = "FAM_PUNTA-V01-S01"
OTHER = "FAM_VALLE-V01-S01"


def publish(
    tmp_path: Path, data: dict[str, Any] | None = None, seed: int = SEED, when: datetime = CLOCK
) -> PublishedSet:
    return publish_scenario_set(
        tmp_path / "datos", the_case(), the_spec(data), seed, clock=lambda: when
    )


def editable_copy(published: PublishedSet, tmp_path: Path) -> Path:
    """Una copia de la carpeta publicada con los archivos editables, para estropearla."""
    target = tmp_path / "copia"
    shutil.copytree(published.folder, target)
    for path in [target, *target.rglob("*")]:
        writable(path)
    return target


def manifest_of(folder: Path) -> dict[str, Any]:
    return json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))


def save_manifest(folder: Path, manifest: dict[str, Any]) -> None:
    writable(folder / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def rewrite(folder: Path, name: str, data: bytes) -> None:
    """Cambia un archivo y deja el manifiesto coherente con el cambio (huellas y contenido)."""
    writable(folder / name).write_bytes(data)
    manifest = manifest_of(folder)
    manifest["files"][name] = sha256_bytes(data)
    manifest["content_id"] = content_id(manifest["files"].items())
    if name == "spec.json":
        manifest["spec_sha256"] = manifest["files"][name]
    save_manifest(folder, manifest)


def scenario_file(folder: Path, scenario_id: str) -> dict[str, Any]:
    return json.loads((folder / "escenarios" / f"{scenario_id}.json").read_text(encoding="utf-8"))


def put_scenario(folder: Path, scenario_id: str, data: dict[str, Any]) -> None:
    rewrite(folder, f"escenarios/{scenario_id}.json", (json.dumps(data, indent=2) + "\n").encode())


def read_error(folder: Path) -> TrazabilidadError | DomainError:
    with pytest.raises(DomainError) as raised:
        read_scenario_set(folder)
    return raised.value


# --- publicar ---------------------------------------------------------------------------------


def test_the_set_is_published_in_a_new_folder_with_the_documented_files(tmp_path: Path) -> None:
    published = publish(tmp_path)
    folder = published.folder
    assert folder.parent == tmp_path / "datos" / SCENARIO_SETS / "SYNTHETIC_DEMO"
    names = sorted(
        path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()
    )
    expected = (
        ["manifiesto.json", "spec.json"]
        + [f"demanda/{i}.csv" for i in ids_of(published)]
        + [f"escenarios/{i}.json" for i in ids_of(published)]
    )
    assert names == sorted(expected)
    assert len(names) == 2 + 2 * 10


def ids_of(published: PublishedSet) -> list[str]:
    return [entry.scenario_id for entry in published.manifest.scenarios]


def test_the_folder_name_is_the_date_and_the_start_of_the_content_hash(tmp_path: Path) -> None:
    published = publish(tmp_path)
    assert published.folder.name == f"20261102T140007Z_{published.manifest.content_id[:8]}"


def test_the_folder_date_is_in_utc_whatever_the_clock_zone(tmp_path: Path) -> None:
    lima = datetime(2026, 11, 2, 9, 0, 7, tzinfo=timezone(timedelta(hours=-5)))
    published = publish(tmp_path, when=lima)
    assert published.folder.name.startswith("20261102T140007Z_")


def test_the_manifest_records_the_case_the_spec_and_the_seed(tmp_path: Path) -> None:
    published = publish(tmp_path)
    manifest = published.manifest
    spec = the_spec()
    assert manifest.schema_version == "1.0.0"
    assert (manifest.case_id, manifest.case_version) == ("SYNTHETIC_DEMO", "1.0.0")
    assert manifest.case_sha256 == canonical_sha256(the_case())
    assert (manifest.spec_id, manifest.origin, manifest.seed) == ("SPEC_DEMO", "synthetic", SEED)
    assert manifest.created_at == CLOCK
    spec_bytes = (published.folder / "spec.json").read_bytes()
    assert manifest.spec_sha256 == sha256_bytes(spec_bytes)
    assert spec_bytes == (spec.model_dump_json(indent=2) + "\n").encode()
    assert parse_spec(json.loads(spec_bytes)) == spec


def test_the_manifest_lists_every_file_but_itself_with_its_hash(tmp_path: Path) -> None:
    published = publish(tmp_path)
    files = published.manifest.files
    assert len(files) == 1 + 2 * 10
    assert MANIFEST_FILE not in files
    for name, digest in files.items():
        assert sha256_bytes((published.folder / name).read_bytes()) == digest
    assert published.manifest.content_id == content_id(files.items())


def test_the_manifest_traces_each_scenario_and_its_flows(tmp_path: Path) -> None:
    published = publish(tmp_path)
    members = generate_scenarios(the_spec(), the_case(), SEED)
    assert [e.scenario_id for e in published.manifest.scenarios] == [
        m.scenario.scenario_id for m in members
    ]
    for entry, member in zip(published.manifest.scenarios, members, strict=True):
        assert (entry.family_id, entry.variant, entry.repetition) == (
            member.family_id,
            member.variant,
            member.repetition,
        )
        assert entry.demand_seed == member.scenario.demand_seed
        assert entry.flows == member.flows
        assert entry.vehicles >= entry.measured > 0


def test_the_manifest_summarises_each_family_with_its_ranges(tmp_path: Path) -> None:
    published = publish(tmp_path)
    punta, valle = published.manifest.families
    spec = the_spec()
    assert (punta.family_id, punta.variants, punta.seeds) == ("FAM_PUNTA", 3, 2)
    assert (valle.family_id, valle.variants, valle.seeds) == ("FAM_VALLE", 2, 2)
    assert punta.demand == spec.families[0].demand
    assert valle.demand == spec.families[1].demand
    assert len(punta.scenario_ids) == 6
    assert valle.scenario_ids[0] == OTHER


def test_each_scenario_file_links_its_demand_file_by_hash(tmp_path: Path) -> None:
    published = publish(tmp_path)
    scenario = scenario_file(published.folder, FIRST)
    artifact = scenario["demand_artifact"]
    assert artifact["path"] == f"demanda/{FIRST}.csv"
    assert artifact["sha256"] == published.manifest.files[f"demanda/{FIRST}.csv"]
    assert scenario["group_id"] == "FAM_PUNTA"


def test_the_published_files_are_read_only(tmp_path: Path) -> None:
    published = publish(tmp_path)
    for path in published.folder.rglob("*"):
        if path.is_file():
            assert not os.access(path, os.W_OK)


def test_no_temporary_folder_is_left_behind(tmp_path: Path) -> None:
    published = publish(tmp_path)
    children = [path.name for path in published.folder.parent.iterdir()]
    assert children == [published.folder.name] or all(
        not name.startswith(".tmp-") for name in children
    )


def test_the_same_spec_and_seed_give_the_same_files_even_on_another_date(
    tmp_path: Path,
) -> None:
    first = publish(tmp_path)
    second = publish(tmp_path, when=CLOCK + timedelta(hours=5))
    assert first.folder != second.folder
    assert first.manifest.content_id == second.manifest.content_id
    assert first.manifest.files == second.manifest.files
    for name in first.manifest.files:
        assert (first.folder / name).read_bytes() == (second.folder / name).read_bytes()
    assert first.manifest.model_copy(update={"created_at": CLOCK}) == second.manifest.model_copy(
        update={"created_at": CLOCK}
    )


def test_another_seed_gives_other_content(tmp_path: Path) -> None:
    first = publish(tmp_path, seed=SEED)
    second = publish(tmp_path, seed=SEED + 1)
    assert first.manifest.content_id != second.manifest.content_id
    assert first.manifest.seed != second.manifest.seed


def test_the_same_set_on_the_same_second_is_not_overwritten(tmp_path: Path) -> None:
    first = publish(tmp_path)
    before = (first.folder / "spec.json").read_bytes()
    with pytest.raises(DomainError) as raised:
        publish(tmp_path)
    assert raised.value.code is ErrorCode.RUN_EXISTS
    assert "ya existe ese conjunto de escenarios" in raised.value.message
    assert (first.folder / "spec.json").read_bytes() == before


def test_an_unsafe_case_id_cannot_be_a_folder_name(tmp_path: Path) -> None:
    case_data = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
    case_data["case_id"] = "../fuera"
    data = spec_data()
    data["case_id"] = "../fuera"
    with pytest.raises(DomainError) as raised:
        publish_scenario_set(
            tmp_path / "datos", parse_case(case_data), the_spec(data), SEED, clock=lambda: CLOCK
        )
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert raised.value.field == "case_id"
    assert not (tmp_path / "datos").exists()


def test_an_invalid_spec_publishes_nothing(tmp_path: Path) -> None:
    data = spec_data()
    data["families"][0]["demand"][0]["flow_vph"] = {"min": 600, "max": 400}
    with pytest.raises(SpecInvalidError):
        publish(tmp_path, data)
    assert not (tmp_path / "datos").exists()


def test_a_failure_while_materializing_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fails(*_: object) -> None:
        raise ScenarioDemandError(ErrorCode.INPUT_SCHEMA, "demasiados vehículos")

    monkeypatch.setattr(module, "materialize_all", fails)
    with pytest.raises(ScenarioDemandError):
        publish(tmp_path)
    assert not (tmp_path / "datos").exists()


def test_publishing_does_not_change_the_case_or_the_spec(tmp_path: Path) -> None:
    case, spec = the_case(), the_spec()
    before = (case.model_dump_json(), spec.model_dump_json())
    publish_scenario_set(tmp_path / "datos", case, spec, SEED, clock=lambda: CLOCK)
    assert (case.model_dump_json(), spec.model_dump_json()) == before


# --- leer -------------------------------------------------------------------------------------


def test_a_published_set_is_read_back_and_verified(tmp_path: Path) -> None:
    published = publish(tmp_path)
    loaded = read_scenario_set(published.folder)
    assert loaded.manifest == published.manifest
    assert loaded.spec == the_spec()
    assert [s.scenario_id for s in loaded.scenarios] == ids_of(published)
    assert all(s.demand_artifact is not None for s in loaded.scenarios)
    assert loaded.scenarios[0].group_id == "FAM_PUNTA"


def test_the_read_scenarios_are_the_generated_ones_with_their_demand_linked(
    tmp_path: Path,
) -> None:
    published = publish(tmp_path)
    loaded = read_scenario_set(published.folder)
    members = generate_scenarios(the_spec(), the_case(), SEED)
    for scenario, member in zip(loaded.scenarios, members, strict=True):
        assert scenario.model_dump(exclude={"demand_artifact"}) == member.scenario.model_dump(
            exclude={"demand_artifact"}
        )


@pytest.mark.parametrize(
    "name",
    [f"escenarios/{FIRST}.json", f"demanda/{FIRST}.csv", "spec.json"],
)
def test_a_changed_file_is_detected(tmp_path: Path, name: str) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    path = folder / name
    path.write_bytes(path.read_bytes() + b" ")
    error = read_error(folder)
    assert error.code is ErrorCode.HASH_MISMATCH
    assert error.field == name


def test_a_missing_file_is_detected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    (folder / "demanda" / f"{FIRST}.csv").unlink()
    error = read_error(folder)
    assert error.code is ErrorCode.HASH_MISMATCH


def test_an_extra_file_is_detected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    (folder / "extra.txt").write_text("x", encoding="utf-8")
    error = read_error(folder)
    assert error.code is ErrorCode.HASH_MISMATCH
    assert error.field == "extra.txt"


def test_a_missing_manifest_is_reported(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    (folder / MANIFEST_FILE).unlink()
    assert read_error(folder).code is ErrorCode.INPUT_SCHEMA


def test_a_manifest_with_an_unknown_field_is_rejected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    manifest = manifest_of(folder)
    manifest["extra"] = 1
    save_manifest(folder, manifest)
    assert read_error(folder).code is ErrorCode.INPUT_SCHEMA


def test_a_folder_that_does_not_exist_is_reported(tmp_path: Path) -> None:
    assert read_error(tmp_path / "no-existe").code is ErrorCode.INPUT_SCHEMA


def test_a_link_inside_the_folder_is_not_followed(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    outside = tmp_path / "fuera.txt"
    outside.write_text("x", encoding="utf-8")
    try:
        (folder / "enlace.txt").symlink_to(outside)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    assert read_error(folder).code is ErrorCode.PATH_NOT_ALLOWED


def test_a_content_hash_that_does_not_match_the_files_is_detected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    manifest = manifest_of(folder)
    manifest["content_id"] = "0" * 64
    save_manifest(folder, manifest)
    error = read_error(folder)
    assert error.code is ErrorCode.HASH_MISMATCH
    assert "huella de contenido" in error.message


# --- alteraciones que dejan las huellas coherentes --------------------------------------------


def test_a_scenario_that_changes_group_does_not_match_its_entry(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    data = scenario_file(folder, FIRST)
    data["group_id"] = "FAM_VALLE"
    put_scenario(folder, FIRST, data)
    error = read_error(folder)
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert "no coincide con su entrada" in error.message


def test_a_scenario_that_changes_its_seed_does_not_match_its_entry(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    data = scenario_file(folder, FIRST)
    data["demand_seed"] += 1
    put_scenario(folder, FIRST, data)
    assert "no coincide con su entrada" in read_error(folder).message


def test_a_scenario_that_changes_a_flow_does_not_match_its_entry(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    data = scenario_file(folder, FIRST)
    data["request"]["demand"][0]["flow_vph"] += 1.0
    put_scenario(folder, FIRST, data)
    assert "no coincide con su entrada" in read_error(folder).message


def test_a_scenario_that_changes_its_origin_does_not_match_the_manifest(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    data = scenario_file(folder, FIRST)
    data["origin"] = "field_derived"
    data["request"]["origin"] = "field"
    put_scenario(folder, FIRST, data)
    assert "no coincide con su entrada" in read_error(folder).message


def test_a_scenario_that_is_not_valid_is_reported_with_its_rule(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    data = scenario_file(folder, FIRST)
    del data["request"]
    put_scenario(folder, FIRST, data)
    error = read_error(folder)
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert "SCEN-S01" in error.message
    assert error.field == f"escenarios/{FIRST}.json"


def test_a_scenario_file_that_is_not_json_is_reported(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    rewrite(folder, f"escenarios/{FIRST}.json", b"{no es json")
    error = read_error(folder)
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert "no es JSON válido" in error.message


def test_a_scenario_that_links_another_demand_file_is_rejected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    data = scenario_file(folder, FIRST)
    data["demand_artifact"]["path"] = f"demanda/{OTHER}.csv"
    put_scenario(folder, FIRST, data)
    assert "no enlaza su archivo de llegadas" in read_error(folder).message


def test_a_scenario_without_a_linked_demand_file_is_rejected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    data = scenario_file(folder, FIRST)
    data["demand_artifact"] = None
    put_scenario(folder, FIRST, data)
    assert "no enlaza su archivo de llegadas" in read_error(folder).message


def test_the_demand_of_another_scenario_is_rejected_even_with_matching_hashes(
    tmp_path: Path,
) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    other = (folder / "demanda" / f"{OTHER}.csv").read_bytes()
    data = scenario_file(folder, FIRST)
    data["demand_artifact"]["sha256"] = sha256_bytes(other)
    put_scenario(folder, FIRST, data)
    rewrite(folder, f"demanda/{FIRST}.csv", other)
    assert "no coincide con su entrada" in read_error(folder).message


def test_a_demand_file_with_a_movement_the_scenario_lacks_is_rejected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    bad = b"vehicle_id,movement_id,vehicle_class,depart_s,in_cohort\nX_Y.car.1,X_Y,car,1.0,true\n"
    data = scenario_file(folder, FIRST)
    data["demand_artifact"]["sha256"] = sha256_bytes(bad)
    put_scenario(folder, FIRST, data)
    rewrite(folder, f"demanda/{FIRST}.csv", bad)
    with pytest.raises(ScenarioDemandError) as raised:
        read_scenario_set(folder)
    assert "no tiene el movimiento «X_Y»" in raised.value.message


def test_a_changed_spec_does_not_match_its_manifest(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    spec = json.loads((folder / "spec.json").read_text(encoding="utf-8"))
    spec["spec_id"] = "OTRA"
    rewrite(folder, "spec.json", (json.dumps(spec, indent=2) + "\n").encode())
    error = read_error(folder)
    assert "la especificación no corresponde a su manifiesto" in error.message
    assert error.field == "spec.json"


def test_a_spec_that_is_not_valid_is_reported(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    rewrite(folder, "spec.json", b'{"schema_version": "1.0.0"}')
    error = read_error(folder)
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert "SPEC-S01" in error.message


def test_a_changed_family_summary_does_not_match_the_spec(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    manifest = manifest_of(folder)
    manifest["families"][0]["scenario_ids"].reverse()
    save_manifest(folder, manifest)
    error = read_error(folder)
    assert "las familias del manifiesto no corresponden" in error.message


def test_a_scenario_missing_from_the_manifest_entries_is_detected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    manifest = manifest_of(folder)
    manifest["scenarios"].pop()
    save_manifest(folder, manifest)
    assert "no corresponden a sus escenarios" in read_error(folder).message


def test_a_repeated_entry_in_the_manifest_is_detected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    manifest = manifest_of(folder)
    manifest["scenarios"].append(manifest["scenarios"][0])
    save_manifest(folder, manifest)
    assert "repetidos" in read_error(folder).message


def test_a_listed_file_that_belongs_to_no_scenario_is_detected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    (folder / "extra.txt").write_text("x", encoding="utf-8")
    manifest = manifest_of(folder)
    manifest["files"]["extra.txt"] = sha256_bytes(b"x")
    manifest["content_id"] = content_id(manifest["files"].items())
    save_manifest(folder, manifest)
    assert "no corresponden a sus escenarios" in read_error(folder).message


def test_an_entry_with_other_vehicle_counts_is_detected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    manifest = manifest_of(folder)
    manifest["scenarios"][0]["measured"] += 1
    save_manifest(folder, manifest)
    assert "no coincide con su entrada" in read_error(folder).message


def test_a_demand_file_that_is_too_big_is_rejected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    huge = b"x" * (module.MAX_DEMAND_BYTES + 1)
    rewrite(folder, f"demanda/{FIRST}.csv", huge)
    error = read_error(folder)
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert "demasiado grande" in error.message


def test_a_json_file_over_its_limit_is_rejected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    rewrite(folder, f"escenarios/{FIRST}.json", b" " * (module.MAX_JSON_FILE_BYTES + 1))
    assert "demasiado grande" in read_error(folder).message


def test_reading_does_not_modify_the_folder(tmp_path: Path) -> None:
    published = publish(tmp_path)
    before = {
        path.relative_to(published.folder).as_posix(): path.read_bytes()
        for path in published.folder.rglob("*")
        if path.is_file()
    }
    read_scenario_set(published.folder)
    after = {
        path.relative_to(published.folder).as_posix(): path.read_bytes()
        for path in published.folder.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_a_scenario_file_that_is_not_utf8_is_reported(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    rewrite(folder, f"escenarios/{FIRST}.json", bytes([0xFF, 0xFE]))
    error = read_error(folder)
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert "no es JSON válido" in error.message


# --- más alteraciones coherentes y bordes -----------------------------------------------------


@pytest.mark.parametrize(
    "case_id", ["a/b", "a" + chr(92) + "b", "a b", ".oculto", "-x", "a:b", "caso*", "ñ"]
)
def test_a_case_id_that_is_not_a_plain_folder_name_is_refused(tmp_path: Path, case_id: str) -> None:
    case_data = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
    case_data["case_id"] = case_id
    data = spec_data()
    data["case_id"] = case_id
    with pytest.raises(DomainError) as raised:
        publish_scenario_set(
            tmp_path / "datos", parse_case(case_data), the_spec(data), SEED, clock=lambda: CLOCK
        )
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not (tmp_path / "datos").exists()


@pytest.mark.parametrize("case_id", ["caso-001", "SYNTHETIC_DEMO", "caso.v2", "9"])
def test_a_plain_case_id_is_accepted(tmp_path: Path, case_id: str) -> None:
    case_data = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
    case_data["case_id"] = case_id
    data = spec_data()
    data["case_id"] = case_id
    published = publish_scenario_set(
        tmp_path / "datos", parse_case(case_data), the_spec(data), SEED, clock=lambda: CLOCK
    )
    assert published.folder.parent.name == case_id


@pytest.mark.parametrize(
    ("field", "value"),
    [("case_id", "OTRO"), ("case_version", "9.9.9"), ("origin", "field_derived")],
)
def test_a_spec_that_disagrees_with_the_manifest_in_any_field_is_detected(
    tmp_path: Path, field: str, value: str
) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    spec = json.loads((folder / "spec.json").read_text(encoding="utf-8"))
    spec[field] = value
    rewrite(folder, "spec.json", (json.dumps(spec, indent=2) + "\n").encode())
    assert "la especificación no corresponde a su manifiesto" in read_error(folder).message


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scenario_id", "FAM_PUNTA-V09-S09"),
        ("case_id", "OTRO"),
        ("case_version", "9.9.9"),
    ],
)
def test_a_scenario_that_disagrees_with_its_entry_in_any_field_is_detected(
    tmp_path: Path, field: str, value: str
) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    data = scenario_file(folder, FIRST)
    data[field] = value
    put_scenario(folder, FIRST, data)
    assert "no coincide con su entrada" in read_error(folder).message


def test_an_entry_with_another_total_of_vehicles_is_detected(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    manifest = manifest_of(folder)
    manifest["scenarios"][0]["vehicles"] += 1
    save_manifest(folder, manifest)
    assert "no coincide con su entrada" in read_error(folder).message


def test_a_json_file_exactly_at_its_limit_is_not_called_too_big(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    rewrite(folder, f"escenarios/{FIRST}.json", b" " * module.MAX_JSON_FILE_BYTES)
    assert "demasiado grande" not in read_error(folder).message


def test_a_demand_file_exactly_at_its_limit_is_not_called_too_big(tmp_path: Path) -> None:
    folder = editable_copy(publish(tmp_path), tmp_path)
    rewrite(folder, f"demanda/{FIRST}.csv", b"x" * module.MAX_DEMAND_BYTES)
    assert "demasiado grande" not in read_error(folder).message


def test_the_limits_of_the_files_are_the_documented_ones() -> None:
    assert module.MAX_JSON_FILE_BYTES == 1024 * 1024
    assert module.SHORT_HASH == 8
    assert MANIFEST_FILE == "manifiesto.json"
    assert SCENARIO_SETS == "derivados/escenarios"


def test_a_field_derived_spec_is_recorded_as_such_and_read_back(tmp_path: Path) -> None:
    data = spec_data()
    data["origin"] = "field_derived"
    published = publish(tmp_path, data)
    assert published.manifest.origin == "field_derived"
    loaded = read_scenario_set(published.folder)
    assert {s.origin for s in loaded.scenarios} == {"field_derived"}
    assert loaded.manifest.origin == "field_derived"


def test_the_warmup_vehicles_are_counted_apart_from_the_cohort(tmp_path: Path) -> None:
    data = spec_data()
    data["warmup_s"] = 60
    published = publish(tmp_path, data)
    for entry in published.manifest.scenarios:
        assert entry.vehicles > entry.measured > 0
    read_scenario_set(published.folder)
