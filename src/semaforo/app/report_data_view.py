"""Vista de los datos: cobertura, cero frente a faltante y observado, corregido y excluido.

DEV09 F3, decisiones D7 y D8. «Datos distingue cero/faltante, observado/corregido/excluido y
cobertura» (diseño técnico). Se arma solo con el reporte de calidad de DEV05 ya verificado: un cero
se escribe ``0`` y un dato que falta se escribe ``sin dato``, nunca ``0``.
"""

from datetime import UTC, datetime

from semaforo.app.html_page import (
    Html,
    Tone,
    bullet_list,
    code,
    definition_list,
    element,
    heading,
    page,
    paragraph,
    status,
    table,
)
from semaforo.app.report_case_view import ORIGINS, UNKNOWN
from semaforo.app.report_inputs import DataInputs
from semaforo.datos.quality_report import (
    QualityData,
    QualityRow,
    QualitySummary,
)

__all__ = ["render_data"]

NO_DATA = "sin dato"
WHOLE_WINDOW = "toda la ventana"
NONE_MARK = "—"
MINIMUM: dict[bool | None, tuple[Tone, str]] = {
    True: ("ok", "Cumple el mínimo"),
    False: ("bad", "No llega al mínimo"),
    None: ("none", "Sin mínimo fijado"),
}
WINDOW_STATUSES = {
    "comparable": "Comparables con el control",
    "only_observed": "Solo en el conteo principal",
    "only_control": "Solo en el conteo de control",
    "not_comparable": "No comparables (faltan datos)",
}
ROW_TONES: dict[str, Tone] = {
    "comparable": "ok",
    "excluido": "bad",
    "sin pareja": "warn",
    "no comparable": "warn",
}


def render_data(inputs: DataInputs, generated_at: datetime) -> str:
    """La página de los datos. ``generated_at`` se muestra en el pie."""
    case_report = inputs.case.report
    quality = inputs.quality
    identity = f"{case_report.case_id} (versión {case_report.case_version or UNKNOWN})"
    sections = [
        _summary(inputs),
        _coverage(quality.summary),
        _windows(quality.summary),
        _states(quality),
        _comparison(quality.rows),
        _missing(quality.summary),
        _exclusions(quality.summary),
    ]
    header = element("header", [heading(1, f"Informe de los datos: {identity}")])
    footer = element("footer", [_footer(generated_at)])
    return page(f"Informe de los datos: {identity}", [header, element("main", sections), footer])


def _number(value: float) -> str:
    return format(value, ".10g")


def _percent(fraction: float) -> str:
    return f"{_number(round(fraction * 100, 2))} %"


def _when(instant: str) -> str:
    """Un instante con su hora local y su desfase, por ejemplo ``2026-10-18 08:00 (-05:00)``."""
    parsed = datetime.fromisoformat(instant)
    offset = parsed.strftime("%z")
    shown = f"{offset[:3]}:{offset[3:]}" if offset else "sin zona horaria"
    return f"{parsed:%Y-%m-%d %H:%M} ({shown})"


def _count(value: int | None) -> str:
    return NO_DATA if value is None else str(value)


def _summary(inputs: DataInputs) -> Html:
    report, quality = inputs.case.report, inputs.quality
    manifest, summary = quality.manifest, quality.summary
    sources = sorted({row.control_source_id for row in quality.rows if row.control_source_id})
    observations = sorted({row.observation_id for row in quality.rows if row.observation_id})
    limit = (
        "Sin límite fijado: no se excluyó ningún dato"
        if summary.max_relative_error is None
        else f"{_number(summary.max_relative_error)} (fracción: 0.1 es 10 %)"
    )
    return element(
        "section",
        [
            heading(2, "Resumen", "resumen"),
            definition_list(
                [
                    ("Caso", f"{report.case_id} (versión {report.case_version or UNKNOWN})"),
                    ("Origen del caso", ORIGINS.get(report.origin or "", UNKNOWN)),
                    ("Huella del caso", code(str(report.case_sha256))),
                    ("Periodos del conteo principal", ", ".join(observations) or NONE_MARK),
                    ("Fuente del conteo de control", ", ".join(sources) or NONE_MARK),
                    ("Huella del conteo principal", code(summary.observed_sha256)),
                    ("Huella del conteo de control", code(summary.control_sha256)),
                    ("Límite de error relativo", limit),
                    ("Reporte de calidad creado", _when(manifest.created_at)),
                ]
            ),
            paragraph(
                [
                    "El reporte de calidad se comprobó con sus huellas y es del caso indicado. "
                    "Los números de este informe vienen de él y no se modificaron."
                ],
                "nota",
            ),
        ],
    )


def _coverage(summary: QualitySummary) -> Html:
    window = summary.window
    tone, label = MINIMUM[window.meets_minimum]
    how = "declarada por quien preparó los datos" if window.declared else "deducida de los datos"
    rows = [
        [
            movement.movement_id,
            _number(movement.covered_s),
            _percent(movement.coverage),
            status(*MINIMUM[movement.meets_minimum]),
        ]
        for movement in summary.per_movement
    ]
    parts: list[Html] = [
        heading(2, "Cobertura de la ventana de estudio", "cobertura"),
        definition_list(
            [
                ("Ventana de estudio", f"{_when(window.start)} a {_when(window.end)} ({how})"),
                ("Duración de la ventana", f"{_number(window.window_s)} s"),
                ("Segundos con datos", f"{_number(window.covered_s)} s"),
                ("Cobertura", f"{_percent(window.coverage)} (fracción {_number(window.coverage)})"),
                ("Mínimo de cobertura", status(tone, label)),
            ]
        ),
        table(
            "Cobertura de cada movimiento",
            ["Movimiento", "Segundos con datos", "Cobertura", "Mínimo"],
            rows,
            numeric=frozenset({1, 2}),
            row_headers=True,
        ),
    ]
    parts.append(_gaps(summary))
    return element("section", parts)


def _gaps(summary: QualitySummary) -> Html:
    parts: list[Html] = []
    if summary.gaps:
        rows = [[_when(gap.start), _when(gap.end)] for gap in summary.gaps]
        parts.append(table("Huecos sin ninguna observación", ["Desde", "Hasta"], rows))
    else:
        parts.append(paragraph(["No hay huecos: toda la ventana tiene observaciones."], "nota"))
    if summary.overlaps:
        pairs = [" y ".join(pair) for pair in summary.overlaps]
        parts.append(paragraph(["Periodos que se solapan:"]))
        parts.append(bullet_list(pairs))
    if summary.outside_window:
        parts.append(paragraph(["Periodos fuera de la ventana de estudio:"]))
        parts.append(bullet_list(list(summary.outside_window)))
    return element("div", parts)


def _windows(summary: QualitySummary) -> Html:
    rows = [
        [label, str(summary.windows_by_status.get(key, 0))]
        for key, label in WINDOW_STATUSES.items()
    ]
    return element(
        "section",
        [
            heading(2, "Ventanas de observación", "ventanas"),
            table(
                "Cuántas ventanas hay de cada tipo",
                ["Tipo de ventana", "Cantidad"],
                rows,
                numeric=frozenset({1}),
                row_headers=True,
            ),
        ],
    )


def _states(quality: QualityData) -> Html:
    counts = {state: 0 for state in ROW_TONES}
    for row in quality.rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    rows: list[list[Html | str]] = [
        [
            "Observados",
            str(counts["comparable"]),
            "Conteos del conteo principal comparados con el control y usables.",
        ],
        [
            "Corregidos",
            "0",
            "En esta etapa no se corrige ningún dato: lo que falta se informa y no se inventa.",
        ],
        [
            "Excluidos",
            str(counts["excluido"]),
            "Conteos que superan el límite de error relativo. Cada uno tiene su causa abajo.",
        ],
    ]
    return element(
        "section",
        [
            heading(2, "Observados, corregidos y excluidos", "estados"),
            table(
                "Qué pasó con cada comparación",
                ["Estado", "Cantidad", "Qué significa"],
                rows,
                numeric=frozenset({1}),
                row_headers=True,
            ),
        ],
    )


def _comparison(rows: list[QualityRow]) -> Html:
    body = [_row(row) for row in rows]
    return element(
        "section",
        [
            heading(2, "Comparación con el conteo de control", "comparacion"),
            paragraph(
                [
                    "Los conteos van en vehículos por ventana; el error absoluto, en vehículos; "
                    "el error relativo, como fracción del control (0.1 es 10 %). "
                    f"«{NO_DATA}» significa que el dato no existe: nunca es un cero."
                ],
                "nota",
            ),
            table(
                f"Filas de la comparación: {len(rows)}",
                [
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
                ],
                body,
                numeric=frozenset({4, 5, 6, 7}),
            ),
        ],
    )


def _row(row: QualityRow) -> list[Html | str]:
    tone = ROW_TONES.get(row.status, "none")
    if row.relative_error is not None:
        relative = f"{row.relative_error:.3f}"
    elif row.relative_reason is not None:
        relative = f"no se calcula ({row.relative_reason})"
    else:
        relative = NO_DATA
    return [
        _when(row.start),
        _when(row.end),
        row.movement_id or WHOLE_WINDOW,
        row.vehicle_class or NONE_MARK,
        _count(row.observed),
        _count(row.control),
        _count(row.absolute_error),
        relative,
        status(tone, row.status),
        row.status_reason or NONE_MARK,
        row.control_source_id or NONE_MARK,
    ]


def _missing(summary: QualitySummary) -> Html:
    if summary.missing:
        rows = [
            [m.observation_id, _when(m.start), _when(m.end), m.movement_id, m.vehicle_class]
            for m in summary.missing
        ]
        content: Html = table(
            f"Combinaciones que faltan: {len(rows)}",
            ["Periodo", "Desde", "Hasta", "Movimiento", "Clase"],
            rows,
        )
    else:
        content = paragraph(["No faltan filas en el conteo principal."], "nota")
    return element(
        "section",
        [
            heading(2, "Datos que faltan", "faltantes"),
            paragraph(["Un dato que falta no se trata como cero: el periodo queda incompleto."]),
            content,
        ],
    )


def _exclusions(summary: QualitySummary) -> Html:
    if summary.exclusions:
        rows = [
            [
                e.observation_id or NONE_MARK,
                _when(e.start),
                e.movement_id,
                e.vehicle_class,
                _number(e.relative_error),
                e.reason,
            ]
            for e in summary.exclusions
        ]
        content: Html = table(
            f"Conteos excluidos: {len(rows)}",
            ["Periodo", "Desde", "Movimiento", "Clase", "Error relativo", "Causa"],
            rows,
            numeric=frozenset({4}),
        )
    else:
        content = paragraph(["No se excluyó ningún conteo."], "nota")
    return element("section", [heading(2, "Exclusiones y su causa", "exclusiones"), content])


def _footer(generated_at: datetime) -> Html:
    moment = generated_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return paragraph(
        [
            f"Generado el {moment} a partir de un reporte de calidad verificado. Este informe "
            "describe la calidad de los aforos; no los corrige."
        ],
        "nota",
    )
