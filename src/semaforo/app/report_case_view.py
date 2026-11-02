"""Vista del caso: HTML estático con el origen, el estado de la validación y las restricciones.

DEV09 F2, decisión D6. «Caso muestra origen sintético/real, versión y restricciones» (diseño
técnico). Un caso inválido también se muestra: sus problemas son lo que la vista enseña.
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
from semaforo.app.report_inputs import CaseInputs
from semaforo.caso.case_report_models import (
    CaseReport,
    GroupLimits,
    Interval,
    NetworkStatus,
    ReportStatus,
    RuleOutcome,
    RuleStatus,
)
from semaforo.dominio.case import Case

__all__ = ["render_case"]

VALIDATION: dict[ReportStatus, tuple[Tone, str]] = {
    "valid": ("ok", "Válido"),
    "valid_with_warnings": ("warn", "Válido con avisos"),
    "invalid": ("bad", "Inválido"),
}
RULES: dict[RuleStatus, tuple[Tone, str]] = {
    "passed": ("ok", "Cumple"),
    "warning": ("warn", "Aviso"),
    "failed": ("bad", "No cumple"),
    "not_applicable": ("none", "No aplica"),
}
NETWORK: dict[NetworkStatus, tuple[Tone, str]] = {
    "not_declared": ("none", "No declarada"),
    "not_checked": ("warn", "No verificada"),
    "verified": ("ok", "Verificada"),
    "failed": ("bad", "Con fallos"),
}
ORIGINS = {
    "synthetic": "Sintético: datos de prueba, no son observaciones de Lima",
    "field": "Real: datos de campo",
}
REPRESENTATIONS = {
    "synthetic_fixture": "Caso de prueba sintético",
    "unverified": "Sin verificar",
    "calibrated": "Calibrado",
    "validated": "Validado",
}
PURPOSES = {"vehicle": "Vehicular", "pedestrian": "Peatonal"}
UNKNOWN = "No informado"
NONE_MARK = "—"
SIGNIFICANT_DIGITS = 10
NOT_REACHABLE = "No se puede alcanzar con los tramos del caso"
GLOSSARY = [
    ("Tick", "el paso mínimo, en segundos, con el que se miden los tiempos del semáforo"),
    ("Slot (tramo)", "una parte del ciclo en la que las luces mantienen un mismo estado"),
    ("Ciclo", "el tiempo que tarda el semáforo en completar toda su secuencia"),
    ("Grupo de verde", "los tramos que dan verde a los mismos movimientos"),
    ("Enlace", "cada conexión del semáforo que controla un movimiento en la red"),
]


def render_case(inputs: CaseInputs, generated_at: datetime) -> str:
    """La página del caso. ``generated_at`` se muestra en el pie."""
    report, case = inputs.report, inputs.case
    identity = _identity(report)
    sections = [
        _summary(report),
        _rules(report),
        *_limits(report, case),
        *_content(report, case),
        _glossary(),
    ]
    header = element("header", [heading(1, f"Informe del caso: {identity}")])
    main = element("main", sections)
    footer = element("footer", [_footer(generated_at)])
    return page(f"Informe del caso: {identity}", [header, main, footer])


def _identity(report: CaseReport) -> str:
    if report.case_id is None:
        return "caso sin identificar"
    return f"{report.case_id} (versión {report.case_version or UNKNOWN})"


def _number(value: float) -> str:
    return format(value, f".{SIGNIFICANT_DIGITS}g")


def _seconds(interval: Interval | None) -> str:
    if interval is None:
        return NOT_REACHABLE
    return f"{_number(interval.min)} a {_number(interval.max)} s"


def _summary(report: CaseReport) -> Html:
    tone, label = VALIDATION[report.status]
    network_tone, network_label = NETWORK[report.network]
    failed = [rule.rule_id for rule in report.rules if rule.status == "failed"]
    parts: list[Html] = []
    if report.status == "invalid":
        reason = (
            f"no cumple {len(failed)} regla(s): {', '.join(failed)}."
            if failed
            else "no se pudo leer."
        )
        alert = paragraph([f"Este caso no se puede usar: {reason}"])
        parts.append(element("div", [alert], {"class": "alerta"}))
    parts.append(heading(2, "Resumen", "resumen"))
    parts.append(
        definition_list(
            [
                ("Origen", _origin(report.origin)),
                ("Estado de la validación", status(tone, label)),
                ("Representación", _representation(report.representation_status)),
                ("Red del caso", status(network_tone, network_label)),
                ("Versión", report.case_version or UNKNOWN),
                ("Huella del caso", code(report.case_sha256) if report.case_sha256 else UNKNOWN),
            ]
        )
    )
    return element("section", parts)


def _origin(origin: str | None) -> str:
    return ORIGINS.get(origin or "", UNKNOWN)


def _representation(value: str | None) -> str:
    return REPRESENTATIONS.get(value or "", UNKNOWN)


def _rules(report: CaseReport) -> Html:
    counts = {state: sum(1 for rule in report.rules if rule.status == state) for state in RULES}
    summary = (
        f"{counts['passed']} cumplen, {counts['warning']} con aviso, "
        f"{counts['failed']} no cumplen, {counts['not_applicable']} no aplican."
    )
    rows = [_rule_row(rule) for rule in report.rules]
    return element(
        "section",
        [
            heading(2, "Reglas de validación", "reglas"),
            paragraph([summary]),
            table(
                "Resultado de cada regla del caso",
                ["Regla", "Qué comprueba", "Resultado", "Problemas"],
                rows,
            ),
        ],
    )


def _rule_row(rule: RuleOutcome) -> list[Html | str]:
    tone, label = RULES[rule.status]
    if rule.issues:
        problems: Html | str = bullet_list(
            [
                f"{issue.field}: {issue.message}" if issue.field else issue.message
                for issue in rule.issues
            ]
        )
    else:
        problems = NONE_MARK
    return [rule.rule_id, rule.title, status(tone, label), problems]


def _limits(report: CaseReport, case: Case | None) -> list[Html]:
    limits = report.limits
    if limits is None:
        return []
    purposes = {group.id: group.purpose for group in case.green_groups} if case else {}
    rows = [_group_row(group, purposes) for group in limits.green_groups]
    return [
        element(
            "section",
            [
                heading(2, "Límites del plan", "limites"),
                definition_list(
                    [
                        ("Paso del reloj (tick)", f"{_number(limits.tick_s)} s"),
                        ("Ciclo declarado", _seconds(limits.cycle_declared_s)),
                        ("Ciclo que se puede alcanzar", _seconds(limits.cycle_feasible_s)),
                        ("Tiempo fijo", f"{_number(limits.fixed_time_s)} s"),
                        ("Tramos de duración variable", str(limits.variable_slots)),
                    ]
                ),
                table(
                    "Verde de cada grupo",
                    ["Grupo", "Tipo", "Verde declarado", "Verde que se puede alcanzar"],
                    rows,
                    row_headers=True,
                ),
            ],
        )
    ]


def _group_row(group: GroupLimits, purposes: dict[str, str]) -> list[Html | str]:
    return [
        group.id,
        PURPOSES.get(purposes.get(group.id, ""), NONE_MARK),
        _seconds(group.declared_s),
        _seconds(group.reachable_s),
    ]


def _content(report: CaseReport, case: Case | None) -> list[Html]:
    if case is None:
        note = (
            "Los movimientos, las clases de vehículos y las restricciones no se muestran porque "
            "el caso no es válido: corrija los problemas de la tabla de reglas."
        )
        heading_ = heading(2, "Contenido del caso", "contenido")
        return [element("section", [heading_, paragraph([note], "nota")])]
    movements = [
        [
            movement.id,
            movement.approach_id,
            movement.tls_id,
            ", ".join(str(index) for index in movement.link_indices),
            f"{_number(movement.flow_domain_vph.min)} a {_number(movement.flow_domain_vph.max)}",
        ]
        for movement in case.movements
    ]
    evidence: Html | str
    if case.restrictions_evidence:
        evidence = bullet_list(list(case.restrictions_evidence))
    else:
        evidence = paragraph(["No hay evidencia de las restricciones registrada."], "nota")
    return [
        element(
            "section",
            [
                heading(2, "Movimientos", "movimientos"),
                table(
                    f"{len(case.movements)} movimientos del caso",
                    ["Movimiento", "Acceso", "Semáforo", "Enlaces", "Flujo permitido (veh/h)"],
                    movements,
                    row_headers=True,
                ),
            ],
        ),
        element(
            "section",
            [
                heading(2, "Clases de vehículos y frontera", "clases"),
                definition_list(
                    [
                        ("Clases de vehículos", ", ".join(case.vehicle_classes)),
                        ("Política de frontera", case.boundary_policy_id),
                    ]
                ),
            ],
        ),
        element("section", [heading(2, "Evidencia de las restricciones", "evidencia"), evidence]),
    ]


def _glossary() -> Html:
    return element(
        "section",
        [heading(2, "Qué significan estas palabras", "glosario"), definition_list(GLOSSARY)],
    )


def _footer(generated_at: datetime) -> Html:
    moment = generated_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return paragraph(
        [
            f"Generado el {moment} a partir del archivo del caso. «Válido» significa conforme "
            "al caso representado; no certifica seguridad para la operación vial.",
        ],
        "nota",
    )
