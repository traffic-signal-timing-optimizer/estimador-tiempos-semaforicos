"""Lectura y validación del archivo de un caso (DEV02).

Lee el JSON del caso con límites de seguridad y lo valida con las reglas de
``semaforo.dominio.case`` y ``semaforo.dominio.case_rules``. No ejecuta nada del archivo: solo lo
interpreta como datos (diseño técnico, «Fronteras de confianza y controles»).

- CASE-S04: el archivo pesa 1 MiB como máximo. Se leen a lo sumo ``MAX_CASE_BYTES + 1`` bytes, así
  que un archivo enorme no se carga entero.
- El archivo es UTF-8, con o sin marca de orden de bytes (BOM): PowerShell 5.1 la escribe.
- Se rechazan NaN, infinito y claves repetidas, que JSON admitiría y harían ambiguo el caso.
- Un enlace simbólico o una unión no se sigue: PATH_NOT_ALLOWED.

``read_case`` lanza si el caso es inválido. ``validate_case`` (F3) devuelve siempre un
``CaseReport``: el caso inválido queda descrito en el reporte, y solo un archivo que no se puede
leer se describe con su motivo, también en el reporte.
"""

import json
from pathlib import Path
from typing import Any, NoReturn

from semaforo.caso.case_network import check_network, not_applicable_outcomes
from semaforo.caso.case_report_models import (
    REPORT_EXIT_CODES,
    CaseReport,
    GroupLimits,
    Interval,
    Limits,
    NetworkStatus,
    ReportStatus,
    RuleOutcome,
    RuleStatus,
    to_report_issues,
)
from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.dominio.case import (
    IDENTIFIER_RULE,
    SIZE_RULE,
    STRUCTURE_RULE,
    VERSION_RULE,
    Case,
    CaseInvalidError,
    CaseIssue,
    canonical_sha256,
    parse_case,
)
from semaforo.dominio.case_rules import (
    RULES,
    Window,
    accept_case,
    cycle_window,
    evaluate_rules,
    group_window,
)

__all__ = ["MAX_CASE_BYTES", "read_case", "validate_case"]

MAX_CASE_BYTES = 1024 * 1024
FIELD = "case"
UTF8_BOM = b"\xef\xbb\xbf"
STRUCTURE_TITLES = {
    STRUCTURE_RULE: "Contrato v1.0 completo: campos, tipos y números finitos",
    IDENTIFIER_RULE: "Identificadores válidos",
    VERSION_RULE: "Versión del caso con formato MAYOR.MENOR.PARCHE",
    SIZE_RULE: "Tamaño máximo del archivo",
}


class _RepeatedKeyError(ValueError):
    """Una clave aparece dos veces en el mismo objeto JSON."""


def _object_without_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _RepeatedKeyError(key)
        result[key] = value
    return result


def _reject_constant(name: str) -> NoReturn:
    """``json`` acepta NaN, Infinity y -Infinity por defecto; el caso no."""
    raise ValueError(name)


def _issue(message: str, rule_id: str = STRUCTURE_RULE) -> CaseInvalidError:
    return CaseInvalidError([CaseIssue(rule_id, None, message)])


def _size_issue() -> CaseIssue:
    return CaseIssue(SIZE_RULE, None, f"el archivo pesa más de {MAX_CASE_BYTES} bytes")


def _read_bytes(path: Path) -> bytes:
    if path.is_symlink() or path.is_junction():
        raise CasoError(
            ErrorCode.PATH_NOT_ALLOWED, "el archivo del caso es un enlace o una unión", FIELD
        )
    if not path.exists():
        raise CasoError(ErrorCode.INPUT_SCHEMA, "no existe el archivo del caso", FIELD)
    if not path.is_file():
        raise CasoError(ErrorCode.INPUT_SCHEMA, "la ruta del caso no es un archivo", FIELD)
    try:
        with path.open("rb") as handle:
            return handle.read(MAX_CASE_BYTES + 1)
    except OSError as error:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA,
            f"no se pudo leer el archivo del caso ({type(error).__name__})",
            FIELD,
        ) from error


def _parse_json(content: bytes) -> object:
    """Contenido del JSON, o ``CaseInvalidError`` si no se puede interpretar."""
    try:
        text = content.removeprefix(UTF8_BOM).decode("utf-8")
    except UnicodeDecodeError:
        raise _issue("el archivo no está en UTF-8") from None
    try:
        return json.loads(
            text, object_pairs_hook=_object_without_repeats, parse_constant=_reject_constant
        )
    except _RepeatedKeyError as error:
        raise _issue(f"la clave {error.args[0]!r} aparece más de una vez en un objeto") from None
    except json.JSONDecodeError as error:
        raise _issue(
            f"el archivo no es JSON válido (línea {error.lineno}, columna {error.colno}): "
            f"{error.msg}"
        ) from None
    except RecursionError:
        raise _issue("el JSON está demasiado anidado") from None
    except ValueError as error:
        raise _issue(
            f"el archivo contiene {error.args[0]}, que JSON permite pero el caso no"
        ) from None


def read_case(path: Path) -> Case:
    """Lee y valida el archivo del caso.

    Raises:
        CasoError: PATH_NOT_ALLOWED si la ruta es un enlace o una unión; INPUT_SCHEMA si no existe,
            no es un archivo o no se puede leer.
        CaseInvalidError: si el archivo supera ``MAX_CASE_BYTES`` (CASE-S04), no es JSON o UTF-8
            válido, no cumple el contrato (CASE-S01 a S03) o es incoherente (CASE-C01 a C13).
    """
    content = _read_bytes(path)
    if len(content) > MAX_CASE_BYTES:
        raise CaseInvalidError([_size_issue()])
    return accept_case(_parse_json(content))


def validate_case(path: Path) -> CaseReport:
    """Valida el archivo del caso y su red, y devuelve el reporte. No lanza por un caso inválido.

    Solo un archivo que no se puede leer (ausente, no es un archivo, enlace o unión) se describe
    con su motivo en ``error``; el reporte se produce igual, con estado ``invalid``.
    """
    try:
        content = _read_bytes(path)
    except CasoError as error:
        return _unreadable_report(error)
    case, issues, reached = _structure(content)
    network, network_status, network_error = _network_check(case, path.parent)
    rules = [
        *_structure_outcomes(issues, reached),
        *_consistency_outcomes(case),
        *network,
    ]
    status, exit_code = _verdict(rules, network_error)
    return CaseReport(
        case_id=None if case is None else case.case_id,
        case_version=None if case is None else case.case_version,
        origin=None if case is None else case.origin,
        representation_status=None if case is None else case.representation_status,
        case_sha256=None if case is None else canonical_sha256(case),
        status=status,
        exit_code=exit_code,
        network=network_status,
        limits=None if case is None else _limits(case),
        error=None,
        rules=rules,
    )


def _structure(content: bytes) -> tuple[Case | None, list[CaseIssue], bool]:
    """El caso, si su estructura es válida; sus problemas; y si se llegó al contrato v1.0."""
    if len(content) > MAX_CASE_BYTES:
        return None, [_size_issue()], False
    try:
        data = _parse_json(content)
    except CaseInvalidError as error:
        return None, list(error.issues), False
    try:
        return parse_case(data), [], True
    except CaseInvalidError as error:
        return None, list(error.issues), True


def _structure_outcomes(issues: list[CaseIssue], reached: bool) -> list[RuleOutcome]:
    """CASE-S01 a S04. Un fallo de JSON deja sin aplicar las reglas que no llegaron a correr."""
    outcomes: list[RuleOutcome] = []
    for rule_id, title in STRUCTURE_TITLES.items():
        own = [issue for issue in issues if issue.rule_id == rule_id]
        status: RuleStatus
        if own:
            status = "failed"
        elif rule_id == SIZE_RULE or reached:
            status = "passed"
        else:
            status = "not_applicable"
        outcomes.append(
            RuleOutcome(
                rule_id=rule_id,
                title=title,
                status=status,
                issues=to_report_issues(own),
            )
        )
    return outcomes


def _consistency_outcomes(case: Case | None) -> list[RuleOutcome]:
    """CASE-C01 a C13; sin estructura válida no hay nada que revisar y quedan sin aplicar."""
    if case is None:
        return [
            RuleOutcome(rule_id=rule.rule_id, title=rule.title, status="not_applicable", issues=[])
            for rule in RULES
        ]
    return [
        RuleOutcome(
            rule_id=result.rule_id,
            title=result.title,
            status=result.status,
            issues=to_report_issues(result.issues),
        )
        for result in evaluate_rules(case)
    ]


def _network_check(
    case: Case | None, case_dir: Path
) -> tuple[list[RuleOutcome], NetworkStatus, ErrorCode | None]:
    """CASE-N01 y N02, el estado de la red y el error más grave de la verificación."""
    if case is None:
        return not_applicable_outcomes(), "not_checked", None
    if case.network is None:
        return not_applicable_outcomes(), "not_declared", None
    check = check_network(case.network, case, case_dir)
    failed = any(outcome.status == "failed" for outcome in check.outcomes)
    return check.outcomes, "failed" if failed else "verified", check.error


def _verdict(rules: list[RuleOutcome], network_error: ErrorCode | None) -> tuple[ReportStatus, int]:
    """Estado y código de salida: 0 sin fallos; con fallos, el de la red o el de caso inválido.

    El código de red (5 o 3) prevalece sobre el de caso inválido (2): un archivo de red alterado
    importa más que un error de consistencia del caso.
    """
    if not any(rule.status == "failed" for rule in rules):
        warned = any(rule.status == "warning" for rule in rules)
        return ("valid_with_warnings" if warned else "valid"), 0
    code = network_error or ErrorCode.INPUT_SCHEMA
    return "invalid", REPORT_EXIT_CODES[code]


def _limits(case: Case) -> Limits:
    """Límites efectivos: el ciclo factible y el verde alcanzable de cada grupo (F2)."""
    fixed = [slot for slot in case.slots if slot.kind == "fixed"]
    groups = [
        GroupLimits(
            id=group.id,
            declared_s=Interval(min=group.min_s, max=group.max_s),
            reachable_s=_interval(group_window(case, index)),
        )
        for index, group in enumerate(case.green_groups)
    ]
    return Limits(
        tick_s=case.tick_s,
        cycle_declared_s=Interval(min=case.cycle_s.min, max=case.cycle_s.max),
        cycle_feasible_s=_interval(cycle_window(case)),
        fixed_time_s=sum(slot.min_s for slot in fixed),
        variable_slots=len(case.slots) - len(fixed),
        green_groups=groups,
    )


def _interval(window: Window | None) -> Interval | None:
    return None if window is None else Interval(min=window.min, max=window.max)


def _unreadable_report(error: CasoError) -> CaseReport:
    """Reporte de un archivo que no se pudo leer: todas las reglas sin aplicar y el motivo."""
    rules = [
        *(
            RuleOutcome(rule_id=rule_id, title=title, status="not_applicable", issues=[])
            for rule_id, title in STRUCTURE_TITLES.items()
        ),
        *_consistency_outcomes(None),
        *not_applicable_outcomes(),
    ]
    return CaseReport(
        case_id=None,
        case_version=None,
        origin=None,
        representation_status=None,
        case_sha256=None,
        status="invalid",
        exit_code=REPORT_EXIT_CODES[error.code],
        network="not_checked",
        limits=None,
        error=error.message,
        rules=rules,
    )
