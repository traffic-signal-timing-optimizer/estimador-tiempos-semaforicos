"""Un caso y un reporte de calidad publicado, sintéticos, para las pruebas de las vistas (DEV09).

El caso es el del ejemplo (``tests/fixtures/case.json``, dos movimientos y dos clases). Los aforos
son los de QA06: en la ventana de 08:00 a 08:15, el movimiento N_S tiene 90 autos contra 100 del
control (error 10, relativo 0.1) y 5 buses contra 0 (control cero), y E_W tiene 50 autos contra 50
y 0 buses contra 0 (un cero verdadero). La ventana de estudio es de 30 minutos, así que la
cobertura es de 0.5.
"""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from semaforo.datos.coverage import assess_coverage, list_missing
from semaforo.datos.normalizer import prepare_counts
from semaforo.datos.quality import compare_files, find_exclusions
from semaforo.datos.quality_report import ReportInputs, publish_quality
from semaforo.dominio.case import Case, parse_case

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DEMO_CASE_TEXT = (FIXTURES / "case.json").read_text(encoding="utf-8")
HEADER = (
    "case_id,observation_id,source_id,origin,start,end,"
    "movement_id,vehicle_class,count,quality_state"
)
W1 = ("2026-10-18T08:00:00-05:00", "2026-10-18T08:15:00-05:00")
KEYS = [("N_S", "car"), ("N_S", "bus"), ("E_W", "car"), ("E_W", "bus")]
NOW = datetime(2026, 11, 1, 9, 0, 0, tzinfo=UTC)
LIMA = timezone(timedelta(hours=-5))


def _at(minute: int) -> datetime:
    return datetime(2026, 10, 18, 8, 0, tzinfo=LIMA) + timedelta(minutes=minute)


def period(
    observation: str,
    source: str,
    window: tuple[str, str],
    counts: list[int],
    keys: list[tuple[str, str]] | None = None,
) -> list[str]:
    pairs = list(zip(keys or KEYS, counts, strict=True))
    return [
        f"SYNTHETIC_DEMO,{observation},{source},synthetic,{window[0]},{window[1]},"
        f"{movement},{vclass},{count},observed"
        for (movement, vclass), count in pairs
    ]


def write_case(directory: Path, text: str = DEMO_CASE_TEXT) -> Path:
    """Escribe el caso del ejemplo (o ``text``) como ``case.json`` y devuelve su ruta."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "case.json"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def demo_case() -> Case:
    return parse_case(json.loads(DEMO_CASE_TEXT))


def publish_demo_quality(  # noqa: PLR0913  (una ayuda de pruebas con opciones por nombre)
    root: Path,
    work: Path,
    *,
    observed: list[str] | None = None,
    control: list[str] | None = None,
    limit: float | None = None,
    case: Case | None = None,
) -> Path:
    """Publica el reporte de calidad de QA06 (o de los conteos dados) y devuelve su carpeta."""
    case = demo_case() if case is None else case
    work.mkdir(parents=True, exist_ok=True)
    obs = work / "principal.csv"
    ctl = work / "control.csv"
    rows_observed = observed or period("OBS", "CAMARA", W1, [90, 5, 50, 0])
    rows_control = control or period("CTL", "MANUAL", W1, [100, 0, 50, 0])
    obs.write_text("\n".join([HEADER, *rows_observed]) + "\n", encoding="utf-8", newline="\n")
    ctl.write_text("\n".join([HEADER, *rows_control]) + "\n", encoding="utf-8", newline="\n")
    comparison = compare_files(obs, ctl, case)
    prepared = prepare_counts(obs, case)
    inputs = ReportInputs(
        comparison=comparison,
        coverage=assess_coverage(prepared, case, (_at(0), _at(30))),
        exclusions=find_exclusions(comparison, limit),
        missing=list_missing(prepared),
        case=case,
        max_relative_error=limit,
    )
    return publish_quality(root, inputs, NOW)
