"""Vista de los datos: cobertura, cero y faltante, observado, corregido y excluido (DEV09 F3)."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from html_checks import Inspection, assert_safe_page
from quality_tools import KEYS, W1, period, publish_demo_quality, write_case
from semaforo.app.report_data_view import render_data
from semaforo.app.report_inputs import CaseInputs, DataInputs, load_data_inputs
from semaforo.datos.quality_report import (
    QualityData,
    QualityExclusion,
    QualityMissing,
    QualityRow,
)

NOW = datetime(2026, 11, 1, 14, 0, tzinfo=UTC)
W2 = ("2026-10-18T08:15:00-05:00", "2026-10-18T08:30:00-05:00")
START_1 = "2026-10-18 08:00 (-05:00)"
END_1 = "2026-10-18 08:15 (-05:00)"
START_2 = "2026-10-18 08:15 (-05:00)"
END_2 = "2026-10-18 08:30 (-05:00)"
ATTACKS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "'><svg onload=alert(1)>",
    "&lt;b&gt; &amp; &#60;",
    "</td></tr></table><h1>otro</h1>",
]
CHECK = "\N{HEAVY CHECK MARK}"
WARN = "\N{WARNING SIGN}"
CROSS = "\N{HEAVY MULTIPLICATION X}"
DASH = "\N{EN DASH}"


def inputs_of(
    tmp_path: Path,
    *,
    observed: list[str] | None = None,
    control: list[str] | None = None,
    limit: float | None = None,
) -> DataInputs:
    folder = publish_demo_quality(
        tmp_path / "calidad", tmp_path / "trabajo", observed=observed, control=control, limit=limit
    )
    return load_data_inputs(write_case(tmp_path / "caso"), folder)


def shown(inputs: DataInputs) -> Inspection:
    return assert_safe_page(render_data(inputs, NOW))


def with_quality(inputs: DataInputs, **changes: object) -> DataInputs:
    return DataInputs(case=inputs.case, quality=inputs.quality.model_copy(update=changes))


def with_summary(inputs: DataInputs, **changes: object) -> DataInputs:
    summary = inputs.quality.summary.model_copy(update=changes)
    return with_quality(inputs, summary=summary)


def with_rows(inputs: DataInputs, rows: list[QualityRow]) -> DataInputs:
    return with_quality(inputs, rows=rows)


def first_row(inputs: DataInputs, **changes: object) -> DataInputs:
    rows = list(inputs.quality.rows)
    rows[0] = rows[0].model_copy(update=changes)
    return with_rows(inputs, rows)


def full_window() -> tuple[list[str], list[str]]:
    observed = period("OBS1", "CAMARA", W1, [90, 5, 50, 0]) + period(
        "OBS2", "CAMARA", W2, [80, 4, 40, 1]
    )
    control = period("CTL1", "MANUAL", W1, [100, 0, 50, 0]) + period(
        "CTL2", "MANUAL", W2, [80, 4, 40, 1]
    )
    return observed, control


# --- el caso base de QA06 ---------------------------------------------------------------------


def test_the_summary_identifies_the_case_the_sources_and_the_limit(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    seen = shown(inputs)
    text = seen.visible_text
    assert "Informe de los datos: SYNTHETIC_DEMO (versión 1.0.0)" in text
    assert "Origen del casoSintético: datos de prueba, no son observaciones de Lima" in text
    assert "Periodos del conteo principalOBS" in text
    assert "Fuente del conteo de controlMANUAL" in text
    assert "Límite de error relativoSin límite fijado: no se excluyó ningún dato" in text
    assert "Reporte de calidad creado2026-11-01 09:00 (+00:00)" in text
    manifest = inputs.quality.manifest
    for digest in (manifest.case_sha256, manifest.observed_sha256, manifest.control_sha256):
        assert digest in text
    assert seen.tags["code"] == 3


def test_the_coverage_is_shown_in_seconds_percent_and_fraction(tmp_path: Path) -> None:
    text = shown(inputs_of(tmp_path)).visible_text
    assert f"Ventana de estudio{START_1} a {END_2} (declarada por quien preparó los datos)" in text
    assert "Duración de la ventana1800 s" in text
    assert "Segundos con datos900 s" in text
    assert "Cobertura50 % (fracción 0.5)" in text
    assert f"Mínimo de cobertura{DASH} Sin mínimo fijado" in text


def test_the_coverage_of_each_movement_and_the_gap_are_listed(tmp_path: Path) -> None:
    seen = shown(inputs_of(tmp_path))
    rows = seen.table("Cobertura de cada movimiento").rows
    assert rows == [
        ["N_S", "900", "50 %", f"{DASH} Sin mínimo fijado"],
        ["E_W", "900", "50 %", f"{DASH} Sin mínimo fijado"],
    ]
    assert seen.table("Huecos sin ninguna observación").rows == [[START_2, END_2]]


def test_the_windows_are_counted_by_type(tmp_path: Path) -> None:
    rows = shown(inputs_of(tmp_path)).table("Cuántas ventanas hay de cada tipo").rows
    assert rows == [
        ["Comparables con el control", "1"],
        ["Solo en el conteo principal", "0"],
        ["Solo en el conteo de control", "0"],
        ["No comparables (faltan datos)", "0"],
    ]


def test_observed_corrected_and_excluded_are_counted_and_nothing_is_corrected(
    tmp_path: Path,
) -> None:
    seen = shown(inputs_of(tmp_path))
    rows = seen.table("Qué pasó con cada comparación").rows
    assert [row[:2] for row in rows] == [
        ["Observados", "4"],
        ["Corregidos", "0"],
        ["Excluidos", "0"],
    ]
    assert "no se corrige ningún dato" in rows[1][2]


def test_the_comparison_shows_the_numbers_of_qa06_with_units_and_reasons(tmp_path: Path) -> None:
    seen = shown(inputs_of(tmp_path))
    table = seen.table("Filas de la comparación: 4")
    assert table.headers == [
        "Desde",
        "Hasta",
        "Movimiento",
        "Clase",
        "Observado (veh)",
        "Control (veh)",
        "Error absoluto (veh)",
        "Error relativo",
        "Estado",
        "Motivo",
        "Fuente del control",
    ]
    ok = f"{CHECK} comparable"
    assert table.rows == [
        [START_1, END_1, "N_S", "car", "90", "100", "-10", "0.100", ok, "—", "MANUAL"],
        [
            START_1,
            END_1,
            "N_S",
            "bus",
            "5",
            "0",
            "5",
            "no se calcula (control cero)",
            ok,
            "—",
            "MANUAL",
        ],
        [START_1, END_1, "E_W", "car", "50", "50", "0", "0.000", ok, "—", "MANUAL"],
        [
            START_1,
            END_1,
            "E_W",
            "bus",
            "0",
            "0",
            "0",
            "no se calcula (control cero)",
            ok,
            "—",
            "MANUAL",
        ],
    ]


def test_a_true_zero_is_written_as_zero_and_never_as_no_data(tmp_path: Path) -> None:
    seen = shown(inputs_of(tmp_path))
    zero_row = seen.table("Filas de la comparación: 4").rows[3]
    assert zero_row[4:7] == ["0", "0", "0"]
    assert "sin dato" not in seen.table("Filas de la comparación: 4").rows[3]
    assert "sin dato" not in seen.visible_text.split("«sin dato» significa")[0]


def test_the_comparison_note_explains_the_units_and_that_no_data_is_not_zero(
    tmp_path: Path,
) -> None:
    text = shown(inputs_of(tmp_path)).visible_text
    assert "vehículos por ventana" in text
    assert "0.1 es 10 %" in text
    assert "«sin dato» significa que el dato no existe: nunca es un cero." in text


def test_with_nothing_missing_and_nothing_excluded_it_says_so(tmp_path: Path) -> None:
    text = shown(inputs_of(tmp_path)).visible_text
    assert "No faltan filas en el conteo principal." in text
    assert "No se excluyó ningún conteo." in text
    assert "Un dato que falta no se trata como cero" in text


def test_the_footer_says_it_describes_the_quality_and_does_not_correct(tmp_path: Path) -> None:
    text = shown(inputs_of(tmp_path)).visible_text
    assert "Generado el 2026-11-01 14:00 UTC" in text
    assert "no los corrige" in text


def test_the_same_inputs_give_the_same_page(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    assert render_data(inputs, NOW) == render_data(inputs, NOW)


def test_the_time_of_the_footer_is_in_utc(tmp_path: Path) -> None:
    lima = datetime(2026, 11, 1, 9, 0, tzinfo=timezone(timedelta(hours=-5)))
    text = assert_safe_page(render_data(inputs_of(tmp_path), lima)).visible_text
    assert "Generado el 2026-11-01 14:00 UTC" in text


# --- con un límite de error: excluidos --------------------------------------------------------


def test_a_comparison_over_the_limit_is_excluded_and_its_cause_is_listed(tmp_path: Path) -> None:
    seen = shown(inputs_of(tmp_path, limit=0.05))
    assert "Límite de error relativo0.05 (fracción: 0.1 es 10 %)" in seen.visible_text
    states = seen.table("Qué pasó con cada comparación").rows
    assert [row[:2] for row in states] == [
        ["Observados", "3"],
        ["Corregidos", "0"],
        ["Excluidos", "1"],
    ]
    car = seen.table("Filas de la comparación: 4").rows[0]
    assert car[8] == f"{CROSS} excluido"
    assert "supera el límite 0.05" in car[9]
    [excluded] = seen.table("Conteos excluidos: 1").rows
    assert excluded[:5] == ["OBS", START_1, "N_S", "car", "0.1"]
    assert "supera el límite 0.05" in excluded[5]
    assert "No se excluyó ningún conteo." not in seen.visible_text


# --- ventanas incompletas, sin pareja, con huecos ---------------------------------------------


def test_a_period_with_a_missing_row_is_not_comparable_and_shows_no_numbers(tmp_path: Path) -> None:
    short = period("OBS", "CAMARA", W1, [1, 1, 1], KEYS[:3])
    inputs = inputs_of(tmp_path, observed=short, control=period("CTL", "MANUAL", W1, [1, 1, 1, 1]))
    seen = shown(inputs)
    [row] = seen.table("Filas de la comparación: 1").rows
    reason = str(inputs.quality.rows[0].status_reason)
    assert "E_W/bus" in reason
    assert row == [
        START_1,
        END_1,
        "toda la ventana",
        "—",
        "sin dato",
        "sin dato",
        "sin dato",
        "sin dato",
        f"{WARN} no comparable",
        reason,
        "MANUAL",
    ]
    assert seen.table("Cuántas ventanas hay de cada tipo").rows[3] == [
        "No comparables (faltan datos)",
        "1",
    ]
    assert seen.table("Qué pasó con cada comparación").rows[0][:2] == ["Observados", "0"]


def test_the_missing_combinations_are_listed(tmp_path: Path) -> None:
    short = period("OBS", "CAMARA", W1, [1, 1, 1], KEYS[:3])
    inputs = inputs_of(tmp_path, observed=short, control=period("CTL", "MANUAL", W1, [1, 1, 1, 1]))
    seen = shown(inputs)
    assert seen.table("Combinaciones que faltan: 1").rows == [["OBS", START_1, END_1, "E_W", "bus"]]
    assert "No faltan filas" not in seen.visible_text


def test_windows_that_exist_on_one_side_only_are_marked_without_a_pair(tmp_path: Path) -> None:
    inputs = inputs_of(
        tmp_path,
        observed=period("OBS", "CAMARA", W1, [1, 1, 1, 1]),
        control=period("CTL", "MANUAL", W2, [1, 1, 1, 1]),
    )
    seen = shown(inputs)
    rows = seen.table("Filas de la comparación: 2").rows
    assert [row[8] for row in rows] == [f"{WARN} sin pareja", f"{WARN} sin pareja"]
    assert all(row[4:8] == ["sin dato"] * 4 for row in rows)
    windows = seen.table("Cuántas ventanas hay de cada tipo").rows
    assert windows[0][1:] == ["0"]
    assert windows[1][1:] == ["1"]
    assert windows[2][1:] == ["1"]


def test_a_fully_covered_window_has_no_gaps(tmp_path: Path) -> None:
    observed, control = full_window()
    seen = shown(inputs_of(tmp_path, observed=observed, control=control))
    assert "Cobertura100 % (fracción 1)" in seen.visible_text
    assert "No hay huecos: toda la ventana tiene observaciones." in seen.visible_text
    assert all(t.caption != "Huecos sin ninguna observación" for t in seen.tables)
    assert seen.table("Cuántas ventanas hay de cada tipo").rows[0] == [
        "Comparables con el control",
        "2",
    ]


# --- cobertura: mínimo, ventana, solapes ------------------------------------------------------


@pytest.mark.parametrize(
    ("meets", "symbol", "label"),
    [
        (True, CHECK, "Cumple el mínimo"),
        (False, CROSS, "No llega al mínimo"),
        (None, DASH, "Sin mínimo fijado"),
    ],
)
def test_each_minimum_state_has_its_symbol_and_text(
    tmp_path: Path, meets: bool | None, symbol: str, label: str
) -> None:
    inputs = inputs_of(tmp_path)
    window = inputs.quality.summary.window.model_copy(update={"meets_minimum": meets})
    movements = [
        m.model_copy(update={"meets_minimum": meets}) for m in inputs.quality.summary.per_movement
    ]
    seen = shown(with_summary(inputs, window=window, per_movement=movements))
    assert f"Mínimo de cobertura{symbol} {label}" in seen.visible_text
    assert [row[3] for row in seen.table("Cobertura de cada movimiento").rows] == [
        f"{symbol} {label}"
    ] * 2


def test_a_window_deduced_from_the_data_says_so(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    window = inputs.quality.summary.window.model_copy(update={"declared": False})
    text = shown(with_summary(inputs, window=window)).visible_text
    assert "(deducida de los datos)" in text
    assert "declarada por quien" not in text


def test_overlapping_periods_and_periods_outside_the_window_are_listed(tmp_path: Path) -> None:
    inputs = with_summary(
        inputs_of(tmp_path), overlaps=[["P1", "P2"], ["P3", "P4"]], outside_window=["FUERA"]
    )
    seen = shown(inputs)
    assert "Periodos que se solapan:" in seen.visible_text
    assert "P1 y P2" in seen.visible_text
    assert "P3 y P4" in seen.visible_text
    assert "Periodos fuera de la ventana de estudio:" in seen.visible_text
    assert "FUERA" in seen.visible_text


def test_no_overlaps_and_nothing_outside_the_window_shows_neither_list(tmp_path: Path) -> None:
    text = shown(inputs_of(tmp_path)).visible_text
    assert "se solapan" not in text
    assert "fuera de la ventana" not in text


# --- horas ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instant", "shown_as"),
    [
        ("2026-10-18T08:00:00+00:00", "2026-10-18 08:00 (+00:00)"),
        ("2026-10-18T08:00:00-05:00", "2026-10-18 08:00 (-05:00)"),
        ("2026-10-18T08:00:00+05:30", "2026-10-18 08:00 (+05:30)"),
        ("2026-10-18T08:00:00", "2026-10-18 08:00 (sin zona horaria)"),
    ],
)
def test_an_instant_is_shown_with_its_local_time_and_offset(
    tmp_path: Path, instant: str, shown_as: str
) -> None:
    inputs = first_row(inputs_of(tmp_path), start=instant)
    assert shown(inputs).table("Filas de la comparación: 4").rows[0][0] == shown_as


# --- estados de fila y origen -----------------------------------------------------------------


def test_an_unknown_row_state_is_shown_as_it_is_with_a_neutral_symbol(tmp_path: Path) -> None:
    inputs = first_row(inputs_of(tmp_path), status="rara")
    assert shown(inputs).table("Filas de la comparación: 4").rows[0][8] == f"{DASH} rara"


def test_a_row_without_a_reason_or_a_source_shows_a_dash(tmp_path: Path) -> None:
    inputs = first_row(inputs_of(tmp_path), status_reason=None, control_source_id="")
    row = shown(inputs).table("Filas de la comparación: 4").rows[0]
    assert row[9] == "—"
    assert row[10] == "—"


def test_a_row_with_a_relative_error_but_a_reason_shows_the_error(tmp_path: Path) -> None:
    inputs = first_row(inputs_of(tmp_path), relative_error=0.25, relative_reason="x")
    assert shown(inputs).table("Filas de la comparación: 4").rows[0][7] == "0.250"


def test_a_row_without_error_and_without_reason_shows_no_data(tmp_path: Path) -> None:
    inputs = first_row(inputs_of(tmp_path), relative_error=None, relative_reason=None)
    assert shown(inputs).table("Filas de la comparación: 4").rows[0][7] == "sin dato"


def test_a_report_with_no_rows_still_renders(tmp_path: Path) -> None:
    seen = shown(with_rows(inputs_of(tmp_path), []))
    assert seen.table("Filas de la comparación: 0").rows == []
    assert "Fuente del conteo de control—" in seen.visible_text
    assert "Periodos del conteo principal—" in seen.visible_text


def test_a_real_case_origin_is_shown_in_words(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    report = inputs.case.report.model_copy(update={"origin": "field"})
    shown_inputs = DataInputs(
        case=CaseInputs(report=report, case=inputs.case.case), quality=inputs.quality
    )
    text = shown(shown_inputs).visible_text
    assert "Origen del casoReal: datos de campo" in text
    assert "Sintético" not in text


def test_an_unknown_origin_and_version_are_not_informed(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    report = inputs.case.report.model_copy(update={"origin": None, "case_version": None})
    changed = DataInputs(
        case=CaseInputs(report=report, case=inputs.case.case), quality=inputs.quality
    )
    text = shown(changed).visible_text
    assert "Origen del casoNo informado" in text
    assert "(versión No informado)" in text


# --- texto hostil (QA30) ----------------------------------------------------------------------


def hostile(inputs: DataInputs, attack: str) -> DataInputs:
    """Texto hostil en todos los campos libres que la vista muestra."""
    rows = [
        row.model_copy(
            update={
                "observation_id": attack,
                "control_source_id": attack,
                "movement_id": attack,
                "vehicle_class": attack,
                "status": attack,
                "status_reason": attack,
                "relative_reason": attack,
                "relative_error": None,
            }
        )
        for row in inputs.quality.rows
    ]
    summary = inputs.quality.summary.model_copy(
        update={
            "per_movement": [
                m.model_copy(update={"movement_id": attack})
                for m in inputs.quality.summary.per_movement
            ],
            "overlaps": [[attack, attack]],
            "outside_window": [attack],
            "missing": [
                QualityMissing(
                    observation_id=attack,
                    start=W1[0],
                    end=W1[1],
                    movement_id=attack,
                    vehicle_class=attack,
                )
            ],
            "exclusions": [
                QualityExclusion(
                    observation_id=attack,
                    start=W1[0],
                    end=W1[1],
                    movement_id=attack,
                    vehicle_class=attack,
                    relative_error=0.5,
                    reason=attack,
                )
            ],
        }
    )
    quality: QualityData = inputs.quality.model_copy(update={"rows": rows, "summary": summary})
    report = inputs.case.report.model_copy(update={"case_id": attack, "case_version": attack})
    return DataInputs(case=CaseInputs(report=report, case=inputs.case.case), quality=quality)


@pytest.mark.parametrize("attack", ATTACKS)
def test_hostile_text_in_every_free_field_stays_text(tmp_path: Path, attack: str) -> None:
    seen = shown(hostile(inputs_of(tmp_path), attack))
    assert seen.visible_text.count(attack) >= 20
    for tag in ("script", "img", "svg"):
        assert seen.tags[tag] == 0
    assert seen.tags["h1"] == 1


# --- detalles que no se veían en el caso base -------------------------------------------------


def test_a_coverage_that_is_not_round_keeps_two_decimals_in_the_percent(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    window = inputs.quality.summary.window.model_copy(update={"coverage": 1 / 3})
    text = shown(with_summary(inputs, window=window)).visible_text
    assert "Cobertura33.33 % (fracción 0.3333333333)" in text


def test_each_movement_row_has_its_own_numbers_and_minimum(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path)
    window = inputs.quality.summary.window.model_copy(update={"meets_minimum": True})
    movements = [
        inputs.quality.summary.per_movement[0].model_copy(
            update={"covered_s": 450.0, "coverage": 0.25, "meets_minimum": False}
        ),
        inputs.quality.summary.per_movement[1].model_copy(
            update={"covered_s": 1800.0, "coverage": 1.0, "meets_minimum": None}
        ),
    ]
    seen = shown(with_summary(inputs, window=window, per_movement=movements))
    assert seen.table("Cobertura de cada movimiento").rows == [
        ["N_S", "450", "25 %", f"{CROSS} No llega al mínimo"],
        ["E_W", "1800", "100 %", f"{DASH} Sin mínimo fijado"],
    ]


def test_a_window_type_that_is_not_in_the_summary_counts_zero(tmp_path: Path) -> None:
    inputs = with_summary(inputs_of(tmp_path), windows_by_status={})
    rows = shown(inputs).table("Cuántas ventanas hay de cada tipo").rows
    assert [row[1] for row in rows] == ["0", "0", "0", "0"]


def test_an_exclusion_without_a_period_shows_a_dash(tmp_path: Path) -> None:
    inputs = inputs_of(tmp_path, limit=0.05)
    exclusion = inputs.quality.summary.exclusions[0].model_copy(update={"observation_id": None})
    seen = shown(with_summary(inputs, exclusions=[exclusion]))
    assert seen.table("Conteos excluidos: 1").rows[0][0] == "—"


def test_the_numbers_are_aligned_to_the_right(tmp_path: Path) -> None:
    plain = render_data(inputs_of(tmp_path / "a"), NOW)
    assert plain.count('<td class="num">') == 4 + 4 + 3 + 16
    excluded = render_data(inputs_of(tmp_path / "b", limit=0.05), NOW)
    assert excluded.count('<td class="num">') == 4 + 4 + 3 + 16 + 1
