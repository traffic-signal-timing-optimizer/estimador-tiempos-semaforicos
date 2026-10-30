"""Verificación de la red que declara el caso: CASE-N01 y CASE-N02 (DEV02, F3).

Solo se aplica si el caso declara su red (``network``). La red es un archivo externo y no
confiable: CASE-N01 la busca dentro de la carpeta del caso, sin rutas absolutas, sin ``..`` ni
enlaces, y compara su SHA-256 con la huella declarada. CASE-N02 usa el inventario de DEV00 para
comprobar que los semáforos, enlaces, carriles de entrada y aristas de salida de los movimientos
existan en la red, y que cada estado tenga tantas señales como enlaces tiene su semáforo.

Los enlaces se comparan solo por su número máximo (``link_count`` del inventario): un hueco en la
numeración de SUMO no se detecta aquí.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from semaforo.caso.case_report_models import RuleOutcome, to_report_issues
from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.inventory import MAX_NET_BYTES, NET_ROOTS, read_network_inventory
from semaforo.caso.xml_input import parse_root
from semaforo.dominio.case import Artifact, Case, CaseIssue, Movement, State, cap_issues

__all__ = ["NetworkCheck", "check_network", "not_applicable_outcomes"]

INTEGRITY_RULE = "CASE-N01"
COMPATIBILITY_RULE = "CASE-N02"
NETWORK_TITLES = {
    INTEGRITY_RULE: "Red declarada: existe, dentro de la carpeta del caso y con su huella",
    COMPATIBILITY_RULE: "Movimientos y estados compatibles con la red",
}
FIELD = "network"
HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class NetworkCheck:
    """Resultado de CASE-N01 y N02, y el código de la falla de integridad de la red, si la hay.

    El código decide el código de salida del reporte: PATH_NOT_ALLOWED o HASH_MISMATCH (5) y
    DEPENDENCY_MISSING (3). Una falla de N02, o una red ilegible, no lleva código: el reporte la
    trata como caso inválido (2).
    """

    outcomes: list[RuleOutcome]
    error: ErrorCode | None


def not_applicable_outcomes() -> list[RuleOutcome]:
    """CASE-N01 y N02 sin aplicar, porque el caso no declara red o no se pudo leer su estructura."""
    return [
        RuleOutcome(rule_id=rule_id, title=title, status="not_applicable", issues=[])
        for rule_id, title in NETWORK_TITLES.items()
    ]


def check_network(artifact: Artifact, case: Case, case_dir: Path) -> NetworkCheck:
    """Verifica la red declarada por ``case``, ubicada en ``case_dir``.

    Si CASE-N01 falla, CASE-N02 no se puede comprobar y queda sin aplicar.
    """
    try:
        path = _verified_file(artifact, case_dir)
    except CasoError as error:
        issues = [CaseIssue(INTEGRITY_RULE, FIELD, error.message)]
        return NetworkCheck(
            [
                _outcome(INTEGRITY_RULE, issues),
                RuleOutcome(
                    rule_id=COMPATIBILITY_RULE,
                    title=NETWORK_TITLES[COMPATIBILITY_RULE],
                    status="not_applicable",
                    issues=[],
                ),
            ],
            error.code,
        )
    try:
        issues = _compatibility_issues(case, path)
    except CasoError as error:
        issues = [CaseIssue(COMPATIBILITY_RULE, FIELD, error.message)]
    outcomes = [_outcome(INTEGRITY_RULE, []), _outcome(COMPATIBILITY_RULE, issues)]
    return NetworkCheck(outcomes, None)


def _outcome(rule_id: str, issues: list[CaseIssue]) -> RuleOutcome:
    capped = cap_issues(issues)
    return RuleOutcome(
        rule_id=rule_id,
        title=NETWORK_TITLES[rule_id],
        status="failed" if capped else "passed",
        issues=to_report_issues(capped),
    )


def _verified_file(artifact: Artifact, case_dir: Path) -> Path:
    """La red declarada, si existe, está dentro de la carpeta del caso y tiene la huella esperada.

    Raises:
        CasoError: PATH_NOT_ALLOWED si la ruta es absoluta, sube de carpeta o pasa por un enlace;
            DEPENDENCY_MISSING si no existe; HASH_MISMATCH si su huella no coincide.
    """
    path = _inside_case_folder(artifact.path, case_dir)
    if path is None:
        raise CasoError(
            ErrorCode.PATH_NOT_ALLOWED,
            "la red debe estar dentro de la carpeta del caso: sin rutas absolutas, sin '..' "
            "ni enlaces",
            FIELD,
        )
    if not path.is_file():
        raise CasoError(
            ErrorCode.DEPENDENCY_MISSING, f"no existe la red declarada ({artifact.path})", FIELD
        )
    if _sha256_of(path) != artifact.sha256:
        raise CasoError(
            ErrorCode.HASH_MISMATCH,
            "la huella SHA-256 de la red no coincide con la declarada",
            FIELD,
        )
    return path


def _inside_case_folder(relative: str, case_dir: Path) -> Path | None:
    """La ruta dentro de ``case_dir``, o None si es absoluta, sube de carpeta o pasa por un enlace.

    Se interpreta con reglas de Windows, que admiten ``/`` y ``\\``; así una ruta como ``/x`` o
    ``C:x`` se rechaza en cualquier sistema.
    """
    pure = PureWindowsPath(relative)
    if not pure.parts or pure.anchor or ".." in pure.parts:
        return None
    current = case_dir
    for part in pure.parts:
        current = current / part
        if current.is_symlink() or current.is_junction():
            return None
    return current


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as error:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA,
            f"no se pudo leer la red declarada ({type(error).__name__})",
            FIELD,
        ) from error
    return digest.hexdigest()


def _compatibility_issues(case: Case, path: Path) -> list[CaseIssue]:
    """Problemas de CASE-N02: lo que los movimientos y los estados piden y la red no tiene."""
    links = {tls.id: tls.link_count for tls in read_network_inventory(path).traffic_lights}
    lanes, edges = _lanes_and_edges(path)
    issues: list[CaseIssue] = []
    for index, movement in enumerate(case.movements):
        issues.extend(_movement_issues(index, movement, links, lanes, edges))
    for index, slot in enumerate(case.slots):
        for position, state in enumerate(slot.states):
            issues.extend(_state_issues(f"slots[{index}].states[{position}]", state, links))
    return issues


def _movement_issues(
    index: int,
    movement: Movement,
    links: dict[str, int],
    lanes: frozenset[str],
    edges: frozenset[str],
) -> list[CaseIssue]:
    base = f"movements[{index}]"
    count = links.get(movement.tls_id)
    issues: list[CaseIssue] = []
    if count is None:
        issues.append(_missing_tls(f"{base}.tls_id", movement.tls_id))
    for position, link in enumerate(movement.link_indices):
        if count is not None and not 0 <= link < count:
            issues.append(
                CaseIssue(
                    COMPATIBILITY_RULE,
                    f"{base}.link_indices[{position}]",
                    f"el enlace {link} no existe: el semáforo {movement.tls_id!r} tiene "
                    f"{count} enlaces",
                )
            )
    for position, lane in enumerate(movement.incoming_lanes):
        if lane not in lanes:
            issues.append(_missing(f"{base}.incoming_lanes[{position}]", "carril", lane))
    for position, edge in enumerate(movement.outgoing_edges):
        if edge not in edges:
            issues.append(_missing(f"{base}.outgoing_edges[{position}]", "arista", edge))
    return issues


def _state_issues(field: str, state: State, links: dict[str, int]) -> list[CaseIssue]:
    count = links.get(state.tls_id)
    if count is None:
        return [_missing_tls(f"{field}.tls_id", state.tls_id)]
    if len(state.state) != count:
        return [
            CaseIssue(
                COMPATIBILITY_RULE,
                f"{field}.state",
                f"tiene {len(state.state)} señales y el semáforo {state.tls_id!r} tiene "
                f"{count} enlaces",
            )
        ]
    return []


def _missing_tls(field: str, tls_id: str) -> CaseIssue:
    return CaseIssue(COMPATIBILITY_RULE, field, f"el semáforo {tls_id!r} no existe en la red")


def _missing(field: str, kind: str, name: str) -> CaseIssue:
    return CaseIssue(COMPATIBILITY_RULE, field, f"el {kind} {name!r} no existe en la red")


def _lanes_and_edges(path: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Identificadores de los carriles y de las aristas de la red."""
    root = parse_root(path, MAX_NET_BYTES, NET_ROOTS, "red")
    edges = root.findall("edge")
    lanes = {
        lane_id
        for edge in edges
        for lane in edge.findall("lane")
        if (lane_id := lane.get("id")) is not None
    }
    edge_ids = {edge_id for edge in edges if (edge_id := edge.get("id")) is not None}
    return frozenset(lanes), frozenset(edge_ids)
