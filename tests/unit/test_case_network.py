"""Red declarada por el caso (DEV02, F3): CASE-N01 (ubicación y huella) y CASE-N02 (compatibilidad).

El caso de ejemplo no declara red. Estas pruebas le declaran una red pequeña, generada aquí, cuyos
carriles, aristas y semáforo son los que usa el caso de ejemplo.
"""

import gzip
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from semaforo.caso.case_report_models import CaseReport, RuleOutcome
from semaforo.caso.case_validation import validate_case

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "case.json"
CASE_DIR_NAME = "caso"
WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="las uniones (junctions) solo existen en Windows"
)


def net_xml(*, links: int = 2, tls: str = "DEMO_TLS") -> bytes:
    """Red con los carriles y aristas del caso de ejemplo y ``links`` enlaces del semáforo."""
    pairs = [("demo_N", "demo_S"), ("demo_E", "demo_W")]
    edges = [
        f'<edge id="{name}"><lane id="{name}_0" index="0" speed="13.9" length="50"/></edge>'
        for name in ("demo_N", "demo_E", "demo_S", "demo_W")
    ]
    connections: list[str] = []
    for index in range(links):
        origin, target = pairs[index % 2]
        connections.append(
            f'<connection from="{origin}" to="{target}" fromLane="0" toLane="0" '
            f'tl="{tls}" linkIndex="{index}"/>'
        )
    logic = (
        f'<tlLogic id="{tls}" type="static" programID="0" offset="0">'
        f'<phase duration="10" state="{"G" * links}"/></tlLogic>'
    )
    body = "\n".join([*edges, *connections, logic])
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<net version="1.16">\n{body}\n</net>\n'.encode()
    )


def make_case(
    folder: Path,
    *,
    net: bytes | None = None,
    net_path: str = "red.net.xml",
    sha: str | None = None,
    change: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    """Escribe una red (si ``net`` no es None) y un caso que la declara; devuelve el caso."""
    target = folder / net_path
    if net is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(net)
    digest = sha if sha is not None else hashlib.sha256(target.read_bytes()).hexdigest()
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["network"] = {"artifact_id": "red", "path": net_path, "sha256": digest}
    if change is not None:
        change(data)
    case = folder / "case.json"
    case.write_text(json.dumps(data), encoding="utf-8")
    return case


def rule(report: CaseReport, rule_id: str) -> RuleOutcome:
    return next(item for item in report.rules if item.rule_id == rule_id)


def fields(outcome: RuleOutcome) -> set[str | None]:
    return {issue.field for issue in outcome.issues}


def test_a_network_that_matches_its_fingerprint_is_verified(tmp_path: Path) -> None:
    report = validate_case(make_case(tmp_path, net=net_xml()))
    assert (report.status, report.exit_code, report.network) == ("valid", 0, "verified")
    assert rule(report, "CASE-N01").status == "passed"
    assert rule(report, "CASE-N02").status == "passed"


def test_a_compressed_network_is_verified_by_its_own_bytes(tmp_path: Path) -> None:
    report = validate_case(
        make_case(tmp_path, net=gzip.compress(net_xml()), net_path="red.net.xml.gz")
    )
    assert report.network == "verified"


def test_a_network_in_a_subfolder_is_verified(tmp_path: Path) -> None:
    report = validate_case(make_case(tmp_path, net=net_xml(), net_path="redes/frutales.net.xml"))
    assert report.network == "verified"


def test_a_missing_network_is_dependency_missing_and_n02_is_not_applied(tmp_path: Path) -> None:
    report = validate_case(make_case(tmp_path, sha="0" * 64))
    assert (report.status, report.exit_code, report.network) == ("invalid", 3, "failed")
    n01 = rule(report, "CASE-N01")
    assert n01.status == "failed"
    assert "no existe la red declarada" in n01.issues[0].message
    assert rule(report, "CASE-N02").status == "not_applicable"


def test_a_network_path_that_is_a_folder_is_missing(tmp_path: Path) -> None:
    (tmp_path / "red.net.xml").mkdir()
    report = validate_case(make_case(tmp_path, net=None, sha="0" * 64))
    assert (report.exit_code, report.network) == (3, "failed")
    assert "no existe la red declarada" in rule(report, "CASE-N01").issues[0].message


def test_a_network_with_another_fingerprint_is_hash_mismatch(tmp_path: Path) -> None:
    report = validate_case(make_case(tmp_path, net=net_xml(), sha="0" * 64))
    assert (report.exit_code, report.network) == (5, "failed")
    assert "no coincide" in rule(report, "CASE-N01").issues[0].message
    assert rule(report, "CASE-N02").status == "not_applicable"


@pytest.mark.parametrize(
    "unsafe",
    [
        "../red.net.xml",
        "redes/../../red.net.xml",
        "/red.net.xml",
        "\\red.net.xml",
        "C:red.net.xml",
        "C:/red.net.xml",
        "\\\\servidor\\red.net.xml",
        "",
    ],
)
def test_a_network_outside_the_case_folder_is_path_not_allowed(tmp_path: Path, unsafe: str) -> None:
    folder = tmp_path / CASE_DIR_NAME
    folder.mkdir()
    write_outside = tmp_path / "red.net.xml"
    write_outside.write_bytes(net_xml())
    case = make_case(folder, net=None, net_path=unsafe, sha=hashlib.sha256(net_xml()).hexdigest())
    report = validate_case(case)
    assert (report.exit_code, report.network) == (5, "failed")
    assert "dentro de la carpeta del caso" in rule(report, "CASE-N01").issues[0].message


def test_a_network_reached_through_a_symlink_is_path_not_allowed(tmp_path: Path) -> None:
    real = tmp_path / "real"
    folder = tmp_path / CASE_DIR_NAME
    real.mkdir()
    folder.mkdir()
    make_case(real, net=net_xml())
    try:
        os.symlink(real, folder / "enlace", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    case = make_case(
        folder, net=None, net_path="enlace/red.net.xml", sha=hashlib.sha256(net_xml()).hexdigest()
    )
    report = validate_case(case)
    assert report.exit_code == 5
    assert rule(report, "CASE-N01").status == "failed"


@WINDOWS_ONLY
def test_a_network_reached_through_a_junction_is_path_not_allowed(tmp_path: Path) -> None:
    real = tmp_path / "real"
    folder = tmp_path / CASE_DIR_NAME
    real.mkdir()
    folder.mkdir()
    make_case(real, net=net_xml())
    subprocess.run(  # noqa: S603
        ["cmd.exe", "/c", "mklink", "/J", str(folder / "union"), str(real)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    try:
        case = make_case(
            folder,
            net=None,
            net_path="union/red.net.xml",
            sha=hashlib.sha256(net_xml()).hexdigest(),
        )
        report = validate_case(case)
        assert report.exit_code == 5
        assert rule(report, "CASE-N01").status == "failed"
    finally:
        (folder / "union").rmdir()


def test_the_number_of_links_is_the_highest_link_index_plus_one(tmp_path: Path) -> None:
    """Con un hueco en la numeración (0 y 2), el semáforo tiene 3 enlaces, no 2 conexiones."""
    gap = net_xml(links=2).decode().replace('linkIndex="1"', 'linkIndex="2"')
    report = validate_case(make_case(tmp_path, net=gap.encode()))
    n02 = rule(report, "CASE-N02")
    assert "tiene 2 señales y el semáforo 'DEMO_TLS' tiene 3 enlaces" in n02.issues[0].message


def test_a_movement_with_an_unknown_traffic_light_is_reported(tmp_path: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        data["movements"][0]["tls_id"] = "OTRO"

    report = validate_case(make_case(tmp_path, net=net_xml(), change=change))
    n02 = rule(report, "CASE-N02")
    assert (report.exit_code, report.network) == (2, "failed")
    assert n02.status == "failed"
    assert "movements[0].tls_id" in fields(n02)
    assert "'OTRO' no existe en la red" in n02.issues[0].message


def test_a_link_index_beyond_the_network_is_reported(tmp_path: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        data["movements"][1]["link_indices"] = [5]

    report = validate_case(make_case(tmp_path, net=net_xml(), change=change))
    assert "movements[1].link_indices[0]" in fields(rule(report, "CASE-N02"))
    assert report.exit_code == 2


def test_a_negative_link_index_is_reported_as_missing(tmp_path: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        data["movements"][0]["link_indices"] = [-1]

    report = validate_case(make_case(tmp_path, net=net_xml(), change=change))
    assert "movements[0].link_indices[0]" in fields(rule(report, "CASE-N02"))


def test_an_incoming_lane_missing_from_the_network_is_reported(tmp_path: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        data["movements"][0]["incoming_lanes"] = ["demo_X_0"]

    report = validate_case(make_case(tmp_path, net=net_xml(), change=change))
    n02 = rule(report, "CASE-N02")
    assert "movements[0].incoming_lanes[0]" in fields(n02)
    assert "'demo_X_0' no existe en la red" in n02.issues[0].message


def test_an_outgoing_edge_missing_from_the_network_is_reported(tmp_path: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        data["movements"][1]["outgoing_edges"] = ["demo_Z"]

    report = validate_case(make_case(tmp_path, net=net_xml(), change=change))
    assert "movements[1].outgoing_edges[0]" in fields(rule(report, "CASE-N02"))


def test_a_state_with_the_wrong_number_of_signals_is_reported(tmp_path: Path) -> None:
    report = validate_case(make_case(tmp_path, net=net_xml(links=3)))
    n02 = rule(report, "CASE-N02")
    assert n02.status == "failed"
    assert "slots[0].states[0].state" in fields(n02)
    assert "tiene 2 señales y el semáforo 'DEMO_TLS' tiene 3 enlaces" in n02.issues[0].message


def test_a_network_without_the_declared_traffic_light_reports_it_everywhere(tmp_path: Path) -> None:
    report = validate_case(make_case(tmp_path, net=net_xml(tls="OTRO")))
    assert {"movements[0].tls_id", "slots[0].states[0].tls_id"} <= fields(rule(report, "CASE-N02"))


def test_an_unreadable_network_is_input_schema(tmp_path: Path) -> None:
    report = validate_case(make_case(tmp_path, net=b"<otra/>"))
    n02 = rule(report, "CASE-N02")
    assert (report.exit_code, report.network) == (2, "failed")
    assert "la raíz <otra> no es la esperada" in n02.issues[0].message


def test_without_a_declared_network_the_network_rules_are_not_applicable(tmp_path: Path) -> None:
    case = tmp_path / "case.json"
    case.write_bytes(FIXTURE.read_bytes())
    report = validate_case(case)
    assert report.network == "not_declared"
    assert [rule(report, rule_id).status for rule_id in ("CASE-N01", "CASE-N02")] == [
        "not_applicable",
        "not_applicable",
    ]


def test_the_network_outcome_has_no_issues_when_it_passes(tmp_path: Path) -> None:
    report = validate_case(make_case(tmp_path, net=net_xml()))
    assert all(not rule(report, rule_id).issues for rule_id in ("CASE-N01", "CASE-N02"))
