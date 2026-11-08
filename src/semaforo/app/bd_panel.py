"""``bd panel``: publica el panel de resultados como una carpeta que se abre con doble clic (F5).

El panel es una **foto de la base**: se genera con un comando y no se conecta a nada al abrirlo. Las
cifras salen de las vistas aprobadas, leídas con ``semaforo_panel`` (``bd.panel_datos``), y las
comparaciones se calculan en ``panel_resumen``. Dos cosas no salen de la base, porque no están en
ella, y ninguna depende de un escenario:

- el avance del proyecto (``docs/panel/avance.toml``, versionado en git);
- el resultado de la última evidencia (``<datos>/reportes/bd/<fecha>/manifiesto.json``): solo su
  estado por sección y sus huellas, no sus conteos.

Cada ejecución publica una carpeta **nueva** ``<datos>/reportes/panel/<fecha>/`` de solo lectura,
con un manifiesto que lleva la huella de cada archivo. Nunca sobrescribe.
"""

import json
import os
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from semaforo.app.bd_evidencia import EvidenceReport
from semaforo.app.panel_resumen import comparisons, run_series
from semaforo.bd.carga.fuentes import children
from semaforo.bd.conexion import DATABASE
from semaforo.bd.ddl import PANEL_VIEWS
from semaforo.bd.panel_datos import QUEUE_BIN_S, read_panel_rows
from semaforo.dominio.base_model import FrozenModel
from semaforo.simulacion.herramientas import git_output
from semaforo.trazabilidad.fs import publish_files
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import utc_now

__all__ = ["PROGRESS_FILE", "PanelReport", "generate_panel", "read_progress"]

PROGRESS_FILE = "docs/panel/avance.toml"
REPORTS = ("reportes", "panel")
EVIDENCE = ("reportes", "bd")
WEB_FILES = ("index.html", "estilos.css", "app.js")
DATA_FILE = "datos.js"
MANIFEST_FILE = "manifiesto.json"
PHASE_STATES = frozenset({"hecho", "en_curso", "pendiente"})


class PanelReport(FrozenModel):
    """El panel publicado: qué base se usó, cuánto muestra y dónde quedó."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["published"] = "published"
    generated_at: str
    database: str
    version_esquema: str | None
    huella_contenido: str | None
    commit: str | None
    repository_clean: bool | None
    folder: str
    counts: dict[str, int]
    warnings: list[str]
    files: dict[str, str]


def read_progress(repository: Path) -> tuple[dict[str, Any], list[str]]:
    """El avance del proyecto y los avisos: un acta que no existe se dice, no se oculta."""
    path = repository / PROGRESS_FILE
    warnings: list[str] = []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        return {"proyecto": {}, "fases": [], "accesos": {}}, [
            f"sin avance del proyecto: {type(error).__name__}"
        ]
    phases: list[dict[str, Any]] = []
    for phase in raw.get("fase", []):
        if phase.get("estado") not in PHASE_STATES:
            warnings.append(f"estado desconocido en {phase.get('id')}: {phase.get('estado')}")
        acta = phase.get("acta")
        if acta and not (repository / str(acta)).is_file():
            warnings.append(f"no existe el acta de {phase.get('id')}: {acta}")
        phases.append(dict(phase))
    return {
        "proyecto": dict(raw.get("proyecto", {})),
        "fases": phases,
        "accesos": dict(raw.get("accesos", {})),
    }, warnings


def _latest_evidence(
    workspace: Path, base: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    folders = children(workspace.joinpath(*EVIDENCE))
    manifests = [folder / MANIFEST_FILE for folder in folders if (folder / MANIFEST_FILE).is_file()]
    if not manifests:
        return None, ["no hay evidencia publicada: corra bd evidencia"]
    try:
        report = EvidenceReport.model_validate_json(manifests[-1].read_bytes())
    except (OSError, ValidationError):
        return None, [f"la evidencia {manifests[-1].parent.name} no se puede leer"]
    same = report.version_esquema == base.get(
        "version_esquema"
    ) and report.content_sha256 == base.get("huella_contenido")
    found = {
        "carpeta": report.folder,
        "fecha": report.generated_at,
        "estado": report.status,
        "codigo": report.exit_code,
        "version_esquema": report.version_esquema,
        "huella_contenido": report.content_sha256,
        "huella_reglas": report.rules_sha256,
        "commit": report.commit,
        "de_esta_base": same,
        "secciones": [{"nombre": item.name, "estado": item.state} for item in report.sections],
    }
    warnings = [] if same else ["la última evidencia es de otra versión de la base"]
    return found, warnings


def _merged_runs(rows: dict[str, Any]) -> list[dict[str, Any]]:
    origin = {str(row["run_id"]): row for row in rows["procedencia"]}
    return [{**origin.get(str(run["run_id"]), {}), **run} for run in rows["corridas"]]


def _links(repository: Path, workspace: Path, final: Path) -> dict[str, str | None]:
    """Cómo llegar desde el panel a los archivos, siempre como ruta relativa."""

    def relative(target: Path) -> str | None:
        try:
            return Path(os.path.relpath(target.resolve(), final.resolve())).as_posix()
        except ValueError:  # otra unidad de disco: no hay ruta relativa
            return None

    return {"datos": relative(workspace), "repositorio": relative(repository)}


def _web_file(name: str) -> bytes:
    return resources.files("semaforo.app").joinpath("panel_web", name).read_bytes()


def generate_panel(
    workspace: Path, repository: Path, *, database: str | None = None
) -> PanelReport:
    """Genera y publica el panel de ``database`` (por defecto, la base del servicio).

    Raises:
        BdError: si el rol del panel no se puede conectar o a la base le faltan las vistas.
        FileExistsError: si ya se publicó un panel con el mismo nombre (el mismo segundo).
    """
    rows = read_panel_rows(database)
    base: dict[str, Any] = rows["base"][0] if rows["base"] else {}
    progress, warnings = read_progress(repository)
    evidence, evidence_warnings = _latest_evidence(workspace, base)
    runs = _merged_runs(rows)
    now = utc_now()
    name = f"{now:%Y%m%dT%H%M%SZ}"
    final = workspace.joinpath(*REPORTS, name)
    status_output = git_output(repository, "status", "--porcelain", "--untracked-files=no")
    commit = git_output(repository, "rev-parse", "HEAD")
    data: dict[str, Any] = {
        **{
            key: value
            for key, value in rows.items()
            if key not in ("corridas", "procedencia", "base")
        },
        "schema_version": "1.0.0",
        "generado_en": now.isoformat(),
        "commit": commit,
        "base": base,
        "evidencia": evidence,
        "avance": progress,
        "corridas": runs,
        "series": run_series(runs),
        "comparaciones": comparisons(
            rows["busquedas"],
            rows["candidatos"],
            rows["candidato_semillas"],
            runs,
            rows["planes"],
        ),
        "cola_intervalo_s": QUEUE_BIN_S,
        "enlaces": _links(repository, workspace, final),
    }
    payload = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    contents = {file: _web_file(file) for file in WEB_FILES}
    contents[DATA_FILE] = f"window.PANEL_DATA = {payload};\n".encode()
    report = PanelReport(
        generated_at=now.isoformat(),
        database=database or DATABASE,
        version_esquema=base.get("version_esquema"),
        huella_contenido=base.get("huella_contenido"),
        commit=commit,
        repository_clean=None if status_output is None else status_output == "",
        folder="/".join((*REPORTS, name)),
        counts={
            "corridas": len(runs),
            "planes": len(rows["planes"]),
            "escenarios": len(rows["escenarios"]),
            "busquedas": len(rows["busquedas"]),
            "exclusiones": len(rows["exclusiones"]),
            "vistas": len(PANEL_VIEWS),
        },
        warnings=[*warnings, *evidence_warnings],
        files={file: sha256_bytes(raw) for file, raw in sorted(contents.items())},
    )
    contents[MANIFEST_FILE] = report.model_dump_json(indent=2).encode()
    publish_files(final, contents)
    return report
