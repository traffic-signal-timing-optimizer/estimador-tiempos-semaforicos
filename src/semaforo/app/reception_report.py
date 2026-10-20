"""Informes de una recepción (F8 de DEV00, ADR09).

- ``public_report``: informe público para ``docs/recepcion/``. Según ADR09 lleva solo la identidad
  de la copia y de la recepción, la versión de SUMO, la fecha, el estado propuesto y los archivos
  con sus hashes, con rutas relativas; además, la huella del manifiesto de la corrida base
  (ampliación aprobada tras F5). Ningún hallazgo de la red, la demanda o los resultados.
- ``findings_markdown``: detalle de los hallazgos (``hallazgos.md``), que queda en ``datos/``
  hasta que el Product Owner autorice publicarlo.
- ``qa23_csv`` y ``qa24_csv``: planillas de revisión para Excel, separadas por punto y coma
  (configuración regional es-PE) y en UTF-8 con BOM para que se vean las tildes. Los
  identificadores de SUMO van como fórmula de texto (``="…"``): Excel convertiría una arista como
  ``-1185174556`` en un número y la mostraría como ``-1.185E+09`` (medido con Excel 16). Al
  guardar, Excel escribe el texto sin la fórmula.
"""

import csv
import io
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from semaforo.app.reception_models import BaseRunRecord, IncompleteRun
from semaforo.caso.audit_models import SimulationAudit
from semaforo.caso.inventory_models import NetworkInventory
from semaforo.caso.movements import Movement
from semaforo.caso.reception_models import SnapshotManifest
from semaforo.simulacion.summary import SimulationSummary
from semaforo.trazabilidad.manifest import Artifact

CSV_DELIMITER = ";"
# Excel no admite textos de más de 255 caracteres dentro de una fórmula.
MAX_EXCEL_FORMULA_TEXT = 255
REVIEW_COLUMNS = ["Resultado (Correcto/Discrepancia)", "Nota"]
SIGNATURE_ROWS: list[list[str]] = [[], ["Revisado por:"], ["Fecha:"]]
CLASS_NAMES = {"passenger": "auto", "bus": "bus", "truck": "camión", "motorcycle": "moto"}
ROLE_NAMES = {
    "entry_config": "configuración de entrada",
    "input": "entrada",
    "view": "vista",
    "output": "salida",
    "script": "script",
    "unreferenced": "sin referenciar",
}
STATUS_NAMES = {
    "acceptable": "aceptable",
    "with_findings": "con hallazgos",
    "failed": "fallida",
}
# Rutas de un equipo: unidad de Windows, ruta UNC o carpeta de usuario.
MACHINE_PATH = re.compile(r"[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|[\\/](?:Users|home)[\\/]")


def find_machine_paths(text: str) -> list[str]:
    """Fragmentos de ``text`` que parecen rutas de un equipo concreto."""
    return [match.group(0) for match in MACHINE_PATH.finditer(text)]


def _number(value: float | None) -> str:
    return "" if value is None else f"{value:g}"


def _excel_text(identifier: str) -> str:
    """Celda que Excel muestra tal cual: ni número, ni fecha, ni fórmula ejecutada."""
    if len(identifier) > MAX_EXCEL_FORMULA_TEXT:
        return identifier
    return '="' + identifier.replace('"', '""') + '"'


def _csv(rows: Iterable[Sequence[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def _classes(classes: Sequence[str]) -> str:
    return ", ".join(CLASS_NAMES.get(vclass, vclass) for vclass in classes) or "ninguna"


def qa23_csv(movements: Sequence[Movement]) -> bytes:
    """Planilla QA23: un movimiento por fila (carril de entrada y salida, giro y clases)."""
    header = [
        "ID",
        "Semáforo",
        "Enlace",
        "Desde (arista)",
        "Carril desde",
        "Hacia (arista)",
        "Carril hacia",
        "Giro",
        "Clases de la demanda que pueden usarlo",
        *REVIEW_COLUMNS,
    ]
    rows = [
        [
            f"QA23-{movement.id}",
            _excel_text(movement.tls_id),
            str(movement.link_index),
            _excel_text(movement.from_edge),
            str(movement.from_lane),
            _excel_text(movement.to_edge),
            str(movement.to_lane),
            movement.direction,
            _classes(movement.classes),
            "",
            "",
        ]
        for movement in movements
    ]
    return _csv([header, *rows, *SIGNATURE_ROWS])


def qa24_csv(
    inventory: NetworkInventory, movements: Sequence[Movement], audit: SimulationAudit
) -> bytes:
    """Planilla QA24: cada fase de cada programa con los movimientos en verde y en amarillo."""
    by_link: dict[tuple[str, int], list[str]] = {}
    for movement in movements:
        by_link.setdefault((movement.tls_id, movement.link_index), []).append(movement.id)
    header = [
        "ID",
        "Semáforo",
        "Programa",
        "Tipo",
        "Activo",
        "Fase",
        "Duración (s)",
        "minDur (s)",
        "maxDur (s)",
        "Verde para",
        "Amarillo para",
        *REVIEW_COLUMNS,
    ]
    rows: list[list[str]] = [header]
    for number, tls in enumerate(inventory.traffic_lights, start=1):
        for program in tls.programs:
            prefix = f"QA24-S{number}-{program.program_id}"
            active = "sí" if program.program_id == tls.active_program_id else "no"
            for phase in program.phases:

                def lit(signals: str, state: str = phase.state, tls_id: str = tls.id) -> str:
                    ids = [
                        movement
                        for index, signal in enumerate(state)
                        if signal in signals
                        for movement in by_link.get((tls_id, index), [])
                    ]
                    return " ".join(ids) or "-"

                rows.append(
                    [
                        f"{prefix}-F{phase.index:02d}",
                        _excel_text(tls.id),
                        _excel_text(program.program_id),
                        program.type,
                        active,
                        str(phase.index),
                        _number(phase.duration_s),
                        _number(phase.min_dur_s),
                        _number(phase.max_dur_s),
                        lit("Gg"),
                        lit("y"),
                        "",
                        "",
                    ]
                )
            cycle = sum(phase.duration_s for phase in program.phases)
            offset = f"desfase {_number(program.offset_s)} s"
            rows.append(
                [
                    f"{prefix}-CICLO",
                    _excel_text(tls.id),
                    _excel_text(program.program_id),
                    program.type,
                    active,
                    "ciclo",
                    _number(cycle),
                    "",
                    "",
                    offset,
                    "",
                    "",
                    "",
                ]
            )
    rows.extend([[], ["ID", "Elemento a revisar", "Dato de la simulación", *REVIEW_COLUMNS]])
    rows.extend(_general_rows(inventory, audit))
    return _csv([*rows, *SIGNATURE_ROWS])


def _general_rows(inventory: NetworkInventory, audit: SimulationAudit) -> list[list[str]]:
    detectors = any(finding.code == "ADDITIONAL_DETECTOR" for finding in audit.findings)
    actuated = any(
        program.type == "actuated" for tls in inventory.traffic_lights for program in tls.programs
    )
    rows = [
        [
            "QA24-PEATONES",
            "Pasos peatonales semaforizados del cruce real (DEC03)",
            "compárelos con los enlaces de la planilla QA23",
            "",
            "",
        ],
        [
            "QA24-FRONTERA",
            "Semáforos vecinos que quedan fuera del caso (DEC04)",
            f"{len(inventory.traffic_lights)} semáforo(s) en la red",
            "",
            "",
        ],
    ]
    if actuated:
        detail = (
            "hay detectores en archivos adicionales" if detectors else "sin detectores declarados"
        )
        rows.append(
            ["QA24-DETECTORES", "Detectores que controlan el programa actuado", detail, "", ""]
        )
    return rows


def findings_markdown(  # noqa: PLR0913  (todos son de solo palabra clave)
    *,
    reception_id: str,
    inventory: NetworkInventory | None,
    movements: Sequence[Movement] | None,
    audit: SimulationAudit,
    summary: SimulationSummary | None,
    incomplete_runs: Sequence[IncompleteRun],
) -> str:
    """Detalle privado de los hallazgos de una recepción (``hallazgos.md``)."""
    lines = [
        f"# Hallazgos de la recepción {reception_id}",
        "",
        "> Privado (ADR09): queda en `datos/` y no se publica sin autorización del Product Owner.",
        "> Los hallazgos son observaciones, no errores declarados.",
        "",
        "## Inventario de la red",
        "",
    ]
    if inventory is None:
        lines.append("No se pudo leer la red.")
    else:
        lines.extend(
            f"- `{f.code}` semáforo `{f.tls_id}`"
            + ("" if f.phase_index is None else f", fase {f.phase_index}")
            + f": {f.message}"
            for f in inventory.findings
        )
        if not inventory.findings:
            lines.append("Sin hallazgos.")
    if movements:
        unusable = [movement.id for movement in movements if not movement.classes]
        lines.extend(
            [
                "",
                f"Movimientos semafóricos que ninguna clase de la demanda puede usar: "
                f"{len(unusable)} de {len(movements)}"
                + (f" ({', '.join(unusable)})." if unusable else "."),
                "Suelen llevar a vías de servicio, ciclovías o veredas. Revíselos en QA23.",
            ]
        )
    lines.extend(["", "## Auditoría de rutas, demanda y comportamiento", ""])
    lines.extend(
        f"- `{f.code}` `{f.subject}` ({f.source or '-'}): {f.message}" for f in audit.findings
    )
    if not audit.findings:
        lines.append("Sin hallazgos.")
    lines.extend(["", "## Corrida base", ""])
    if summary is None:
        lines.append("La corrida base falló: no hay métricas. Ver su manifiesto y sus registros.")
    else:
        lines.extend(
            [
                "| Dato | Valor |",
                "|---|---|",
                f"| Final simulado (s) | {_number(summary.simulated_end_s)} |",
                f"| Vehículos declarados | {_number(summary.declared_vehicles)} |",
                f"| Cargados | {summary.vehicles_loaded} |",
                f"| Insertados | {summary.vehicles_inserted} |",
                f"| Esperando para entrar al final | {summary.vehicles_waiting} |",
                f"| En la red al final | {summary.vehicles_running} |",
                f"| Viajes terminados | {summary.trips_finished} |",
                f"| Demora media de salida (s) | {_number(summary.mean_depart_delay_s)} |",
                f"| Teletransportes | {summary.teleports_total} |",
                f"| Colisiones | {summary.collisions} |",
                f"| Avisos de SUMO | {summary.sumo_warnings} |",
                f"| Demanda no atendida | {'sí' if summary.demand_unmet else 'no'} |",
                "",
            ]
        )
        lines.extend(f"- `{f.code}`: {f.message}" for f in summary.findings)
    lines.extend(["", "## Ejecuciones incompletas", ""])
    lines.extend(
        f"- `{run.folder}`: ejecución `{run.run_id or 'desconocida'}`" for run in incomplete_runs
    )
    if not incomplete_runs:
        lines.append("Ninguna.")
    lines.extend(
        [
            "",
            "## Revisión QA23 y QA24",
            "",
            "Abra `revision_qa23.csv` y `revision_qa24.csv` con Excel. En cada fila escriba",
            "`Correcto` o `Discrepancia` y, si hay diferencia, una nota breve. Al final, su nombre",
            "y la fecha. Compare con la red abierta en netedit (el editor de redes de SUMO) sobre",
            "una copia, nunca sobre la carpeta original, y sin guardar cambios.",
            "",
        ]
    )
    return "\n".join(lines)


def public_report(  # noqa: PLR0913  (todos son de solo palabra clave)
    *,
    reception_id: str,
    created_at: datetime,
    sumo_version: str | None,
    proposed_status: str,
    snapshot: SnapshotManifest,
    run: BaseRunRecord,
    artifacts: Sequence[Artifact],
) -> str:
    """Informe público de la recepción, con el contenido que permite ADR09."""
    lines = [
        f"# Recepción {reception_id}",
        "",
        "Informe generado por `python -m semaforo case receive` (DEV00). Según ADR09 solo",
        "contiene la identidad de la copia, los archivos con sus hashes y el estado propuesto;",
        "los hallazgos detallados quedan fuera del repositorio hasta que el Product Owner",
        "autorice publicarlos.",
        "",
        "| Dato | Valor |",
        "|---|---|",
        f"| Recepción | `{reception_id}` |",
        f"| Fecha (UTC) | {created_at.astimezone(UTC):%Y-%m-%d %H:%M:%S} |",
        f"| Copia (`snapshot_id`) | `{snapshot.snapshot_id}` |",
        f"| Configuración de entrada | `{snapshot.entry_config}` |",
        f"| Versión de SUMO | {sumo_version or 'desconocida'} |",
        f"| Estado propuesto | {STATUS_NAMES.get(proposed_status, proposed_status)}"
        " (pendiente de validación del Product Owner) |",
        f"| Corrida base | `{run.run_id}` ({run.status}) |",
        f"| Huella del manifiesto de la corrida base | `{run.manifest_sha256}` |",
        "",
        "## Archivos de la simulación",
        "",
        "| Archivo | Rol | En la identidad | SHA-256 |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| `{record.path}` | {ROLE_NAMES.get(record.role, record.role)} | "
        f"{'sí' if record.in_snapshot else 'no'} | "
        f"{'`' + record.sha256 + '`' if record.sha256 else 'ilegible'} |"
        for record in snapshot.files
    )
    lines.extend(
        [
            "",
            "## Artefactos de la recepción (en `datos/`, no versionados)",
            "",
            "| Artefacto | SHA-256 |",
            "|---|---|",
        ]
    )
    lines.extend(f"| `{artifact.path}` | `{artifact.sha256}` |" for artifact in artifacts)
    lines.append("")
    return "\n".join(lines)
