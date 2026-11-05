"""Reexpresar la identidad de una búsqueda de la versión 1.0.0 como la 2.0.0 (A01, sin SUMO).

Datos sintéticos: la búsqueda de demostración de ``search_tools``. Las comprobaciones con corridas
reales están en ``tests/integration/test_search_sumo.py``.
"""

from pathlib import Path
from typing import Any, cast

from search_tools import SUMO_VERSION, new_search
from semaforo.referencias.evaluation import JOURNAL_VERSION, identity_digest, search_identity
from semaforo.referencias.evidence import EvidenceReport, reexpress_identity


def identities(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    search = new_search(tmp_path)
    new = search_identity(search.setup, search.candidates, SUMO_VERSION)
    old = {k: v for k, v in new.items() if k != "inputs"} | {"journal_version": "1.0.0"}
    return old, new


def test_a_version_1_identity_becomes_the_version_2_one_with_the_proven_fingerprints(
    tmp_path: Path,
) -> None:
    old, new = identities(tmp_path)
    assert "inputs" not in old
    again = reexpress_identity(old, cast("dict[str, Any]", new["inputs"]))
    assert again == new
    assert identity_digest(again) == identity_digest(new)
    assert again["journal_version"] == JOURNAL_VERSION


def test_reexpressing_keeps_every_other_field_and_replaces_old_fingerprints(
    tmp_path: Path,
) -> None:
    old, new = identities(tmp_path)
    fingerprints = {"case_sha256": "a" * 64, "sumo_version": "9.9.9"}
    again = reexpress_identity({**old, "inputs": {"viejo": 1}}, fingerprints)
    assert again["inputs"] == fingerprints
    assert {k: v for k, v in again.items() if k not in ("inputs", "journal_version")} == {
        k: v for k, v in new.items() if k not in ("inputs", "journal_version")
    }


def test_the_identity_digest_changes_with_the_fingerprints(tmp_path: Path) -> None:
    old, _ = identities(tmp_path)
    one = reexpress_identity(old, {"case_sha256": "a" * 64})
    other = reexpress_identity(old, {"case_sha256": "b" * 64})
    assert identity_digest(one) != identity_digest(other)
    assert len(identity_digest(one)) == 16


def test_a_report_with_problems_is_not_ok_and_says_so_in_its_json() -> None:
    report = EvidenceReport(
        label_id="label-x",
        search_run_id="search-x",
        identity_version="1.0.0",
        runs=2,
        input_folders=2,
        sumo_version="1.27.1",
        fingerprints={},
        expected_identity={},
        expected_search_run_id="search-y",
        expected_label_id="label-y",
        stored_ids_match=None,
        recomputed=0,
        problems=("algo no cuadra",),
    )
    assert not report.ok
    data = report.to_json()
    assert data["ok"] is False
    assert data["problems"] == ["algo no cuadra"]
    assert data["stored_ids_match"] is None
