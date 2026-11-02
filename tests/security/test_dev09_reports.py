"""Seguridad de los informes HTML (DEV09 F4; QA30, parte automática).

QA30: «Cinco vistas con errores y texto HTML inyectado. Abrir reportes y revisar campos y unidades.
Estados claros; texto escapado; sin ejecución de contenido; tabla legible». DEV09 entrega dos de
las cinco vistas. Aquí se prueba, con la herramienta ya ejecutada como un proceso aparte, lo que se
puede comprobar sin una persona: nada se ejecuta, nada sale de la carpeta de informes y los
archivos hostiles no tumban el programa. La lectura visual la hace el Product Owner.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from html_checks import assert_safe_page
from quality_tools import DEMO_CASE_TEXT, W1, publish_demo_quality, write_case
from semaforo.caso.case_validation import MAX_CASE_BYTES

ATTACKS = [
    "<script>alert(document.cookie)</script>",
    "<img src=x onerror=alert(1)>",
    "<svg onload=alert(1)>",
    "<iframe src=javascript:alert(1)></iframe>",
    "<a href=javascript:alert(1)>pulse</a>",
    "<meta http-equiv=refresh content=0;url=https://example.com>",
    "<style>body{display:none}</style>",
    "</td></tr></table><h1>otro título</h1>",
]


def cli(tmp_path: Path, *arguments: str) -> tuple[int, dict[str, object]]:
    result = subprocess.run(  # noqa: S603  (intérprete actual y argumentos fijos)
        [sys.executable, "-m", "semaforo", *arguments, "--workspace", "datos"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ),
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def case_with(**changes: object) -> str:
    data = json.loads(DEMO_CASE_TEXT)
    data.update(changes)
    return json.dumps(data)


def page_of(tmp_path: Path, data: dict[str, object]) -> str:
    return (tmp_path / "datos" / str(data["index"])).read_text(encoding="utf-8")


def published_files(tmp_path: Path) -> list[str]:
    root = tmp_path / "datos"
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


# --- texto inyectado en el caso ---------------------------------------------------------------


@pytest.mark.parametrize("attack", ATTACKS)
def test_html_in_the_identifiers_and_restrictions_of_the_case_is_shown_as_text(
    tmp_path: Path, attack: str
) -> None:
    text = case_with(
        case_id=attack,
        boundary_policy_id=attack,
        restrictions_evidence=["FICTICIO: prueba", attack],
    )
    code, data = cli(tmp_path, "report", "case", "--case", str(write_case(tmp_path / "c", text)))
    assert code == 0
    page = page_of(tmp_path, data)
    seen = assert_safe_page(page)
    assert attack in seen.visible_text
    assert "<script" not in page
    assert seen.tags["img"] == 0
    assert str(data["folder"]).startswith("reportes/informes/caso/sin-identificar/")


def test_text_direction_controls_and_control_characters_do_not_reach_the_page(
    tmp_path: Path,
) -> None:
    hidden = "antes\N{RIGHT-TO-LEFT OVERRIDE}después\N{LEFT-TO-RIGHT ISOLATE}x\u0007y\u0000z"
    text = case_with(restrictions_evidence=["FICTICIO: prueba", hidden])
    code, data = cli(tmp_path, "report", "case", "--case", str(write_case(tmp_path / "c", text)))
    assert code == 0
    page = page_of(tmp_path, data)
    for char in ("\N{RIGHT-TO-LEFT OVERRIDE}", "\N{LEFT-TO-RIGHT ISOLATE}", "\x07", "\x00"):
        assert char not in page
    cleaned = "antes\N{REPLACEMENT CHARACTER}después\N{REPLACEMENT CHARACTER}x"
    cleaned += "\N{REPLACEMENT CHARACTER}y\N{REPLACEMENT CHARACTER}z"
    assert cleaned in assert_safe_page(page).visible_text


def test_a_page_never_points_outside_itself(tmp_path: Path) -> None:
    text = case_with(case_id=ATTACKS[3], restrictions_evidence=[ATTACKS[4]])
    code, data = cli(tmp_path, "report", "case", "--case", str(write_case(tmp_path / "c", text)))
    assert code == 0
    seen = assert_safe_page(page_of(tmp_path, data))
    assert all(value.startswith("#") for value in seen.values("a", "href"))
    assert "src" not in {name for _, name, _ in seen.attributes}


# --- texto inyectado en los datos -------------------------------------------------------------


def test_html_in_the_sources_and_periods_of_the_data_is_shown_as_text(tmp_path: Path) -> None:
    case = write_case(tmp_path / "caso")
    attack_period = "<script>alert(1)</script>"
    attack_source = "<img src=x onerror=alert(1)>"
    rows = [
        f"SYNTHETIC_DEMO,{attack_period},{attack_source},synthetic,{W1[0]},{W1[1]},"
        f"{movement},{vclass},{count},observed"
        for movement, vclass, count in (
            ("N_S", "car", 90),
            ("N_S", "bus", 5),
            ("E_W", "car", 50),
            ("E_W", "bus", 0),
        )
    ]
    control = [row.replace(attack_period, "CTL").replace(attack_source, "MANUAL") for row in rows]
    quality = publish_demo_quality(
        tmp_path / "calidad", tmp_path / "trabajo", observed=rows, control=control
    )
    code, data = cli(
        tmp_path, "report", "data", "--case", str(case), "--quality-report", str(quality)
    )
    assert code == 0
    page = page_of(tmp_path, data)
    seen = assert_safe_page(page)
    assert attack_period in seen.visible_text
    assert "<script" not in page
    assert seen.tags["img"] == 0


# --- archivos que no deben tumbar el programa -------------------------------------------------


def test_a_case_file_over_the_size_limit_gets_a_report_and_is_not_read_whole(
    tmp_path: Path,
) -> None:
    big = tmp_path / "c" / "case.json"
    big.parent.mkdir()
    big.write_text('{"x": "' + "a" * (MAX_CASE_BYTES + 10) + '"}', encoding="utf-8")
    code, data = cli(tmp_path, "report", "case", "--case", str(big))
    assert code == 0
    assert data["case_status"] == "invalid"
    seen = assert_safe_page(page_of(tmp_path, data))
    assert "Inválido" in seen.visible_text


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="vacio"),
        pytest.param(b"\xff\xfe\x00\x00 no es texto", id="no-es-texto"),
        pytest.param(b'{"a": 1, "a": 2}', id="clave-repetida"),
        pytest.param(b"[" * 100000, id="muy-anidado"),
        pytest.param(b'{"case_id": NaN}', id="nan"),
        pytest.param(b"\xef\xbb\xbf{}", id="con-marca-bom"),
    ],
)
def test_hostile_case_files_get_a_report_and_do_not_crash_the_program(
    tmp_path: Path, content: bytes
) -> None:
    path = tmp_path / "c" / "case.json"
    path.parent.mkdir()
    path.write_bytes(content)
    code, data = cli(tmp_path, "report", "case", "--case", str(path))
    assert code == 0
    assert data["case_status"] == "invalid"
    assert_safe_page(page_of(tmp_path, data))


# --- confinamiento ----------------------------------------------------------------------------


def test_everything_written_stays_inside_the_reports_folder(tmp_path: Path) -> None:
    code, data = cli(
        tmp_path,
        "report",
        "case",
        "--case",
        str(write_case(tmp_path / "c", case_with(case_id="../../fuera"))),
    )
    assert code == 0
    files = published_files(tmp_path)
    assert files
    assert all(name.startswith("reportes/informes/caso/sin-identificar/") for name in files)
    assert str(data["folder"]).count("..") == 0
    assert not (tmp_path / "fuera").exists()
    assert not (tmp_path.parent / "fuera").exists()


def test_a_published_page_is_read_only_and_a_second_run_does_not_touch_it(tmp_path: Path) -> None:
    case = write_case(tmp_path / "c")
    code, first = cli(tmp_path, "report", "case", "--case", str(case))
    assert code == 0
    before = (tmp_path / "datos" / str(first["index"])).read_bytes()
    code, second = cli(tmp_path, "report", "case", "--case", str(case))
    assert code in {0, 5}
    assert (tmp_path / "datos" / str(first["index"])).read_bytes() == before
    if code == 0:
        assert second["folder"] != first["folder"]
