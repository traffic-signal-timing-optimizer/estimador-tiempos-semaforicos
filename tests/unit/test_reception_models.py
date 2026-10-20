"""Pruebas del manifiesto de la copia de entrada de una recepción."""

from typing import Any

import pytest
from pydantic import ValidationError

from semaforo.caso.reception_models import FileRecord, Finding, MissingDependency, SnapshotManifest
from semaforo.trazabilidad.ids import content_id

HASH_1 = "1" * 64
HASH_2 = "2" * 64


def _record(
    path: str = "a.xml",
    role: str = "input",
    sha256: str | None = HASH_1,
    *,
    in_snapshot: bool = True,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "path": path,
        "role": role,
        "size_bytes": 10,
        "sha256": sha256,
        "in_snapshot": in_snapshot,
        "unreadable_reason": reason,
    }


def _manifest(**changes: object) -> dict[str, Any]:
    files = [
        _record("entry.sumocfg", "entry_config", HASH_1),
        _record("net.xml", "input", HASH_2),
        _record("tripinfo.xml", "output", None, in_snapshot=False, reason="PermissionError"),
    ]
    data: dict[str, Any] = {
        "snapshot_id": content_id([("entry.sumocfg", HASH_1), ("net.xml", HASH_2)]),
        "entry_config": "entry.sumocfg",
        "identity_files": ["entry.sumocfg", "net.xml"],
        "files": files,
        "missing_dependencies": [],
        "findings": [],
    }
    data.update(changes)
    return data


def test_a_valid_manifest_round_trips_through_json() -> None:
    manifest = SnapshotManifest.model_validate(_manifest())
    again = SnapshotManifest.model_validate_json(manifest.model_dump_json())
    assert again == manifest
    assert manifest.schema_version == "1.0.0"


def test_manifest_accepts_missing_dependencies_and_findings() -> None:
    manifest = SnapshotManifest.model_validate(
        _manifest(
            missing_dependencies=[
                {
                    "path": "x.xml",
                    "section": "input",
                    "option": "route-files",
                    "reason": "not_found",
                }
            ],
            findings=[
                {
                    "code": "ABSOLUTE_PATH",
                    "section": "output",
                    "option": "tripinfo-output",
                    "path": "Q:\\salida\\t.xml",
                    "message": "ruta absoluta",
                }
            ],
        )
    )
    assert manifest.missing_dependencies == [
        MissingDependency(path="x.xml", section="input", option="route-files", reason="not_found")
    ]
    assert isinstance(manifest.findings[0], Finding)


@pytest.mark.parametrize(
    "path", ["/abs.xml", "C:\\x.xml", "C:x.xml", "../out.xml", "a/../b.xml", "", "a\\b.xml", "a\tb"]
)
def test_file_paths_must_be_relative_posix(path: str) -> None:
    with pytest.raises(ValidationError):
        FileRecord.model_validate(_record(path))


def test_manifest_rejects_an_id_that_does_not_match_the_hashes() -> None:
    with pytest.raises(ValidationError, match="snapshot_id"):
        SnapshotManifest.model_validate(_manifest(snapshot_id="0" * 64))


def test_manifest_rejects_duplicated_or_unsorted_files() -> None:
    files = _manifest()["files"]
    with pytest.raises(ValidationError, match="ordenad"):
        SnapshotManifest.model_validate(_manifest(files=list(reversed(files))))
    with pytest.raises(ValidationError, match="duplicad"):
        SnapshotManifest.model_validate(_manifest(files=[*files, files[0]]))


def test_identity_files_must_exist_and_be_inputs() -> None:
    with pytest.raises(ValidationError, match="identity_files"):
        SnapshotManifest.model_validate(_manifest(identity_files=["entry.sumocfg", "absent.xml"]))
    with pytest.raises(ValidationError, match="identity_files"):
        SnapshotManifest.model_validate(
            _manifest(identity_files=["entry.sumocfg", "net.xml", "tripinfo.xml"])
        )


def test_the_entry_config_must_be_part_of_the_identity() -> None:
    with pytest.raises(ValidationError, match="entry_config"):
        SnapshotManifest.model_validate(_manifest(entry_config="net.xml"))


def test_an_unreadable_file_needs_a_reason_and_cannot_be_in_the_snapshot() -> None:
    with pytest.raises(ValidationError, match="unreadable_reason"):
        FileRecord.model_validate(_record(sha256=None, in_snapshot=False, reason=None))
    with pytest.raises(ValidationError, match="in_snapshot"):
        FileRecord.model_validate(_record(sha256=None, in_snapshot=True, reason="x"))


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SnapshotManifest.model_validate(_manifest(extra_field=1))


def test_models_are_immutable() -> None:
    manifest = SnapshotManifest.model_validate(_manifest())
    with pytest.raises(ValidationError):
        manifest.entry_config = "otro.sumocfg"
