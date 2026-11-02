"""Caso de uso del comando ``scenarios generate`` (DEV11 F4, decisión D12).

Lee el caso y la especificación, genera los escenarios con sus llegadas y publica el conjunto en
``<espacio de trabajo>/derivados/escenarios/<caso>/<fecha>_<huella>/`` sin sobrescribir nunca. Si el
caso o la especificación no son válidos, o la semilla no sirve, no se publica nada y se lanza un
error con su código de salida.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from semaforo.caso.case_validation import read_case
from semaforo.caso.json_input import read_json
from semaforo.datos.scenario_set import MANIFEST_FILE, publish_scenario_set
from semaforo.datos.scenarios import MAX_SEED
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.scenario_spec import accept_spec
from semaforo.trazabilidad.store import utc_now

__all__ = ["MAX_SEED", "ScenarioSetResult", "generate_scenario_set"]


class ScenarioSetResult(FrozenModel):
    """Resumen de un conjunto publicado. Las rutas son relativas al espacio de trabajo."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["published"] = "published"
    case_id: str
    spec_id: str
    seed: int
    content_id: str
    families: int
    scenarios: int
    vehicles: int
    folder: str
    manifest: str


def generate_scenario_set(
    workspace: Path, case_path: Path, spec_path: Path, seed: int, now: datetime | None = None
) -> ScenarioSetResult:
    """Genera y publica el conjunto de escenarios de ``spec_path`` sobre ``case_path``.

    Raises:
        DomainError: CasoError si un archivo no se puede leer (PATH_NOT_ALLOWED o INPUT_SCHEMA);
            CaseInvalidError, SpecInvalidError, ScenarioInvalidError o ScenarioDemandError
            (INPUT_SCHEMA) si el caso, la especificación, un escenario o el tamaño del conjunto no
            son válidos; PATH_NOT_ALLOWED si el identificador del caso no sirve como carpeta;
            RUN_EXISTS si ese conjunto ya existe.
    """
    case = read_case(case_path)
    spec = accept_spec(read_json(spec_path, "especificación"), case)
    moment = utc_now() if now is None else now
    published = publish_scenario_set(workspace, case, spec, seed, clock=lambda: moment)
    manifest = published.manifest
    return ScenarioSetResult(
        case_id=manifest.case_id,
        spec_id=manifest.spec_id,
        seed=manifest.seed,
        content_id=manifest.content_id,
        families=len(manifest.families),
        scenarios=len(manifest.scenarios),
        vehicles=sum(entry.vehicles for entry in manifest.scenarios),
        folder=published.folder.relative_to(workspace).as_posix(),
        manifest=(published.folder / MANIFEST_FILE).relative_to(workspace).as_posix(),
    )
