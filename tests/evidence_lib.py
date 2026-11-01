"""Registro de ejecución de pruebas: qué se corrió, con qué y qué resultó (DEV10 F4, D3 a D5).

La documentación exige que cada ejecución de pruebas conserve «comando, fecha, entorno, commit,
fixture, resultado y log», que los fallos se clasifiquen por severidad y se vinculen a tareas, y que
no se escriba «aprobado» en las tablas del Sprint 1 sin evidencia archivada. Este módulo arma ese
registro a partir del resultado de pytest (``--junitxml``) y del catálogo ``tests/qa_catalog.py``.
``scripts/evidencia.py`` lo ejecuta.

Severidad (decisión D5): **crítico** = falla una prueba clave de un QA (bloquea la puerta de F1);
**mayor** = falla otra prueba, o se salta una prueba clave sin declarar el motivo.
"""

import hashlib
import platform
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import parse

from qa_catalog import CATALOG, ROOT, Qa, resolve
from semaforo.dominio.base_model import FrozenModel
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.ids import content_id

Outcome = Literal["passed", "failed", "skipped", "error"]
Severity = Literal["crítico", "mayor"]
QaStatus = Literal["cumplido", "cumplido con salvedad", "no cumplido"]

# Saltos que se aceptan y se declaran: dependen del equipo o del sistema, no del código.
DECLARED_SKIPS: Mapping[str, str] = {
    "no permite crear enlaces simbólicos": (
        "este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el "
        "Modo de desarrollador de Windows (o en un equipo que lo permita)"
    ),
    "el grupo de procesos es de Windows": "la prueba solo aplica en Windows",
    "en Windows sí hay grupo": "la prueba solo aplica fuera de Windows",
    "las uniones solo existen en Windows": "la prueba solo aplica en Windows",
}
PACKAGES = ("semaforo", "pydantic", "defusedxml", "pytest", "hypothesis")


class Result(FrozenModel):
    """Resultado de una prueba, tal como lo informó pytest."""

    file: str
    name: str
    outcome: Outcome
    message: str | None


class SkipRecord(FrozenModel):
    test: str
    reason: str
    declared: bool
    note: str | None


class FailureRecord(FrozenModel):
    test: str
    severity: Severity
    task: str
    message: str | None


class QaOutcome(FrozenModel):
    qa_id: str
    kind: str
    task: str
    summary: str
    key_tests: int
    passed: int
    failed: int
    skipped: int
    status: QaStatus
    skips: list[SkipRecord]
    failures: list[FailureRecord]


class Totals(FrozenModel):
    passed: int
    failed: int
    skipped: int
    errors: int


class Gate(FrozenModel):
    critical_failures: int
    major_findings: int
    result: Literal["sin fallos críticos", "con fallos críticos"]


class EvidenceReport(FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    generated_at: str
    command: list[str]
    commit: str
    dirty: bool
    environment: dict[str, str]
    fixtures_files: int
    fixtures_id: str
    totals: Totals
    qa: list[QaOutcome]
    other_failures: list[FailureRecord]
    undeclared_skips: list[SkipRecord]
    sensitivity: dict[str, int] | None
    gate: Gate


# --- lectura de pytest ------------------------------------------------------------------------


def _outcome(case: Element) -> tuple[Outcome, str | None]:
    for child in case:
        if child.tag == "failure":
            return "failed", child.get("message")
        if child.tag == "error":
            return "error", child.get("message")
        if child.tag == "skipped":
            return "skipped", child.get("message")
    return "passed", None


def parse_junit(path: Path) -> list[Result]:
    """Resultados de un archivo ``--junitxml`` de pytest (pruebas de módulo, sin clases)."""
    results: list[Result] = []
    for case in parse(path).getroot().iter("testcase"):  # type: ignore[union-attr]
        classname = case.get("classname", "")
        name = case.get("name", "").partition("[")[0]
        outcome, message = _outcome(case)
        file = classname.replace(".", "/") + ".py"
        results.append(Result(file=file, name=name, outcome=outcome, message=message))
    return results


def _in_catalog(qa: Qa, result: Result) -> bool:
    for entry in qa.key_tests:
        for item in resolve(entry):
            path, _, function = item.partition("::")
            if path == result.file and (not function or function == result.name):
                return True
    return False


def _skip(qa_test: str, reason: str) -> SkipRecord:
    for pattern, note in DECLARED_SKIPS.items():
        if pattern in reason:
            return SkipRecord(test=qa_test, reason=reason, declared=True, note=note)
    return SkipRecord(test=qa_test, reason=reason, declared=False, note=None)


def scrub(text: str, extra: Iterable[str] = ()) -> str:
    """Quita de ``text`` las rutas de esta máquina (carpeta del proyecto, usuario, temporales)."""
    roots = {str(ROOT), str(Path.home()), tempfile.gettempdir(), *extra}
    cleaned = text
    for root in sorted((r for r in roots if r), key=len, reverse=True):
        for variant in {root, root.replace("\\", "/"), root.replace("\\", "\\\\")}:
            cleaned = cleaned.replace(variant, "<equipo>")
    return cleaned


def classify(  # noqa: PLR0913  (cada dato es un campo distinto del registro)
    results: Sequence[Result],
    *,
    generated_at: str,
    command: list[str],
    commit: str,
    dirty: bool,
    environment: dict[str, str],
    fixtures: tuple[int, str],
    sensitivity: dict[str, int] | None,
    catalog: Sequence[Qa] = CATALOG,
) -> EvidenceReport:
    """Arma el registro: resultado por QA, fallos con severidad y tarea, y la puerta de F1."""
    outcomes: list[QaOutcome] = []
    key_ids: set[tuple[str, str]] = set()
    for qa in catalog:
        mine = [r for r in results if _in_catalog(qa, r)]
        key_ids |= {(r.file, r.name) for r in mine}
        skips = [
            _skip(f"{r.file}::{r.name}", scrub(r.message or "sin motivo"))
            for r in mine
            if r.outcome == "skipped"
        ]
        failures = [
            FailureRecord(
                test=f"{r.file}::{r.name}",
                severity="crítico",
                task=qa.task,
                message=None if r.message is None else scrub(r.message)[:300],
            )
            for r in mine
            if r.outcome in ("failed", "error")
        ]
        status: QaStatus
        if failures or any(not s.declared for s in skips):
            status = "no cumplido"
        elif skips:
            status = "cumplido con salvedad"
        else:
            status = "cumplido"
        counts = Counter(r.outcome for r in mine)
        outcomes.append(
            QaOutcome(
                qa_id=qa.qa_id,
                kind=qa.kind,
                task=qa.task,
                summary=qa.summary,
                key_tests=len(mine),
                passed=counts["passed"],
                failed=counts["failed"] + counts["error"],
                skipped=counts["skipped"],
                status=status,
                skips=skips,
                failures=failures,
            )
        )
    others = [
        FailureRecord(
            test=f"{r.file}::{r.name}",
            severity="mayor",
            task="la del módulo que prueba",
            message=None if r.message is None else scrub(r.message)[:300],
        )
        for r in results
        if r.outcome in ("failed", "error") and (r.file, r.name) not in key_ids
    ]
    undeclared = [skip for qa in outcomes for skip in qa.skips if not skip.declared]
    critical = sum(len(qa.failures) for qa in outcomes)
    major = len(others) + len(undeclared)
    return EvidenceReport(
        generated_at=generated_at,
        command=command,
        commit=commit,
        dirty=dirty,
        environment=environment,
        fixtures_files=fixtures[0],
        fixtures_id=fixtures[1],
        totals=Totals(
            passed=sum(1 for r in results if r.outcome == "passed"),
            failed=sum(1 for r in results if r.outcome == "failed"),
            skipped=sum(1 for r in results if r.outcome == "skipped"),
            errors=sum(1 for r in results if r.outcome == "error"),
        ),
        qa=outcomes,
        other_failures=others,
        undeclared_skips=undeclared,
        sensitivity=sensitivity,
        gate=Gate(
            critical_failures=critical,
            major_findings=major,
            result="con fallos críticos" if critical else "sin fallos críticos",
        ),
    )


# --- entorno, commit y datos de prueba --------------------------------------------------------


def fixtures_digest(root: Path = ROOT / "tests" / "fixtures") -> tuple[int, str]:
    """Cantidad de archivos de prueba y su identificador por contenido."""
    entries = [
        (path.relative_to(root).as_posix(), sha256_file(path))
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]
    return len(entries), content_id(entries)


def git_state() -> tuple[str, bool]:
    """Commit actual y si hay cambios sin guardar (se ignora lo que el registro mismo escribe)."""
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", ".", ":(exclude)docs/evidencia"],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    return sha, bool(status.strip())


def environment_facts(
    sumo_version_text: str | None, available_memory: int | None
) -> dict[str, str]:
    """Datos del entorno que importan para repetir la ejecución. Sin rutas de la máquina."""
    facts = {
        "python": platform.python_version(),
        "sistema": f"{platform.system()} {platform.release()}",
        "sumo": sumo_version_text or "no encontrado",
        "memoria_disponible_mib": "no medida"
        if available_memory is None
        else str(available_memory // (1024 * 1024)),
    }
    for package in PACKAGES:
        try:
            facts[package] = version(package)
        except PackageNotFoundError:
            facts[package] = "no instalado"
    return facts


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def command_text() -> list[str]:
    """El comando equivalente, sin la ruta del intérprete."""
    return ["python", "-m", "pytest", "-q", "tests"]


def python_executable() -> str:
    return sys.executable


# --- informe para la persona ------------------------------------------------------------------


def render_markdown(report: EvidenceReport) -> str:
    """Informe legible de la ejecución. No escribe «aprobado» en ninguna tabla del Sprint 1."""
    lines = [
        f"# Registro de ejecución de pruebas: {report.generated_at}",
        "",
        "Written for: el Product Owner y el equipo, para revisar el resultado de QA01 a QA10.",
        "",
        "> Este registro es evidencia. **No completa las tablas de resultados del Sprint 1:** "
        "eso lo hace el Product Owner a partir de este registro.",
        "",
        f"- **Resultado de la puerta:** {report.gate.result} "
        f"({report.gate.critical_failures} críticos, {report.gate.major_findings} mayores)",
        f"- **Commit:** `{report.commit}`" + (" (con cambios sin guardar)" if report.dirty else ""),
        f"- **Comando:** `{' '.join(report.command)}`",
        f"- **Datos de prueba:** {report.fixtures_files} archivos, identificador "
        f"`{report.fixtures_id[:16]}…`",
        "",
        "## Entorno",
        "",
        "| Dato | Valor |",
        "|---|---|",
        *[f"| {key} | {value} |" for key, value in report.environment.items()],
        "",
        "## Totales de la suite",
        "",
        f"{report.totals.passed} pasan, {report.totals.failed} fallan, "
        f"{report.totals.errors} con error, {report.totals.skipped} se saltan.",
        "",
        "## Resultado por caso",
        "",
        "| QA | Tipo | Tarea | Pruebas clave | Pasan | Fallan | Saltadas | Estado |",
        "|---|---|---|---|---|---|---|---|",
        *[
            f"| {q.qa_id} | {q.kind} | {q.task} | {q.key_tests} | {q.passed} | {q.failed} | "
            f"{q.skipped} | {q.status} |"
            for q in report.qa
        ],
    ]
    declared = [(q.qa_id, s) for q in report.qa for s in q.skips if s.declared]
    lines += ["", "## Pruebas saltadas (declaradas)", ""]
    if declared:
        lines += ["| QA | Prueba | Motivo |", "|---|---|---|"]
        lines += [f"| {qa_id} | `{s.test}` | {s.note} |" for qa_id, s in declared]
    else:
        lines.append("Ninguna.")
    lines += ["", "## Fallos", ""]
    failures = [f for q in report.qa for f in q.failures] + report.other_failures
    if failures:
        lines += ["| Severidad | Prueba | Tarea | Mensaje |", "|---|---|---|---|"]
        lines += [f"| {f.severity} | `{f.test}` | {f.task} | {f.message or ''} |" for f in failures]
    else:
        lines.append("Ninguno.")
    if report.undeclared_skips:
        lines += ["", "## Saltos sin declarar (mayor)", ""]
        lines += [f"- `{s.test}`: {s.reason}" for s in report.undeclared_skips]
    lines += ["", "## Ensayo de sensibilidad", ""]
    if report.sensitivity is None:
        lines.append("No se ejecutó en esta corrida.")
    else:
        s = report.sensitivity
        lines.append(
            f"{s['ensayados']} cambios a propósito: {s['detectados']} detectados, "
            f"{s['sobrevivieron']} sobrevivieron."
        )
    lines += ["", "## Resumen de lo que demuestra cada caso", ""]
    lines += [f"- **{q.qa_id}:** {q.summary}" for q in report.qa]
    return "\n".join(lines) + "\n"
