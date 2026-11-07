"""Las decisiones sobre archivos excluidos, como archivos publicados (DEV31 F4c, C1.5).

La decisión no vive solo en la base: es una carpeta de ``datos/`` con su acta, ligada a la ruta y a
la huella del archivo excluido, para que sobreviva a una reconstrucción.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from semaforo.bd.carga.decisiones import (
    DECISIONS,
    Decision,
    DecisionIndex,
    decision_unit,
    publish_decision,
    read_decision,
)
from semaforo.bd.carga.modelo import CargaError
from semaforo.dominio.errors import DomainError, ErrorCode
from workspace_tools import tamper

MOMENT = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
ACTA = "docs/actas/decision.md"
EXCLUDED = "ejecuciones/RUN-DEV00/manifest.json"
HASH = hashlib.sha256(b"manifiesto de DEV00").hexdigest()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repo"
    (repository / "docs" / "actas").mkdir(parents=True)
    text = "Acta de la decisión de prueba.\n"
    (repository / ACTA).write_bytes(text.encode())
    return repository, hashlib.sha256(text.encode()).hexdigest()


def _decision(acta_sha256: str, **changes: object) -> Decision:
    values: dict[str, object] = {
        "decision_id": "decision-1",
        "decision": "accepted_risk",
        "ruta": EXCLUDED,
        "huella": HASH,
        "motivo": "Recepción de DEV00 sin escenario: nunca será cargable.",
        "acta": ACTA,
        "acta_sha256": acta_sha256,
        "commit_codigo": None,
        "responsable": "PO",
        "decidido_en": MOMENT,
    }
    return Decision.model_validate({**values, **changes})


def test_a_published_decision_is_read_back_with_its_file_fingerprint(tmp_path: Path) -> None:
    _, acta_sha = _repository(tmp_path)
    workspace = tmp_path / "datos"
    folder = publish_decision(workspace, _decision(acta_sha))
    assert folder == f"{DECISIONS}/decision-1"
    decision, digest = read_decision(workspace, folder)
    assert (decision.ruta, decision.huella, decision.decision) == (EXCLUDED, HASH, "accepted_risk")
    assert len(digest) == 64


def test_a_decision_is_never_overwritten(tmp_path: Path) -> None:
    _, acta_sha = _repository(tmp_path)
    workspace = tmp_path / "datos"
    publish_decision(workspace, _decision(acta_sha))
    with pytest.raises(FileExistsError):
        publish_decision(workspace, _decision(acta_sha))


def test_a_decision_file_that_changed_is_refused(tmp_path: Path) -> None:
    _, acta_sha = _repository(tmp_path)
    workspace = tmp_path / "datos"
    folder = publish_decision(workspace, _decision(acta_sha))
    tamper(workspace / folder / "decision.json")
    with pytest.raises(DomainError):
        read_decision(workspace, folder)


def test_a_decision_must_match_its_folder_and_use_a_relative_path(tmp_path: Path) -> None:
    _, acta_sha = _repository(tmp_path)
    workspace = tmp_path / "datos"
    folder = publish_decision(workspace, _decision(acta_sha, ruta="../fuera/manifest.json"))
    with pytest.raises(CargaError) as outside:
        read_decision(workspace, folder)
    assert outside.value.code is ErrorCode.PATH_NOT_ALLOWED
    other = publish_decision(workspace, _decision(acta_sha, decision_id="decision-2"))
    moved = workspace / DECISIONS / "decision-3"
    (workspace / other).rename(moved)
    with pytest.raises(CargaError):
        read_decision(workspace, f"{DECISIONS}/decision-3")


def test_a_decision_needs_a_valid_fingerprint_and_a_known_kind() -> None:
    with pytest.raises(ValidationError):
        _decision("a" * 64, huella="no-es-una-huella")
    with pytest.raises(ValidationError):
        _decision("a" * 64, decision="ignorar")
    with pytest.raises(ValidationError):
        _decision("a" * 64, motivo="")


def test_the_unit_carries_the_three_files_and_needs_the_repository_and_the_unchanged_minutes(
    tmp_path: Path,
) -> None:
    repository, acta_sha = _repository(tmp_path)
    workspace = tmp_path / "datos"
    folder = publish_decision(workspace, _decision(acta_sha))
    decision, unit = decision_unit(workspace, repository, folder)
    assert unit.key == "decision:decision-1"
    assert [f.relative for f in unit.files] == [
        f"{folder}/manifiesto.json",
        f"{folder}/decision.json",
        ACTA,
    ]
    assert decision.decision_id == "decision-1"
    with pytest.raises(CargaError):
        decision_unit(workspace, None, folder)
    (repository / ACTA).write_text("Acta cambiada.\n", encoding="utf-8")
    with pytest.raises(CargaError) as changed:
        decision_unit(workspace, repository, folder)
    assert changed.value.code is ErrorCode.HASH_MISMATCH


def test_a_decision_covers_the_file_only_with_the_same_path_and_fingerprint() -> None:
    covering = _decision("a" * 64)
    index = DecisionIndex({(f"datos:{EXCLUDED}", HASH): covering})
    assert index.covering(EXCLUDED, HASH) is covering
    assert index.covering(EXCLUDED, hashlib.sha256(b"el archivo cambio").hexdigest()) is None
    assert index.covering("ejecuciones/OTRA/manifest.json", HASH) is None


def test_the_json_of_a_decision_is_plain_and_has_no_machine_paths(tmp_path: Path) -> None:
    _, acta_sha = _repository(tmp_path)
    workspace = tmp_path / "datos"
    folder = publish_decision(workspace, _decision(acta_sha))
    text = (workspace / folder / "decision.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert json.loads(text)["ruta"] == EXCLUDED
