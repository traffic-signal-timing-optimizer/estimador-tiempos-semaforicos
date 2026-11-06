"""Réplica de una corrida: ¿dos corridas con las mismas entradas dan lo mismo? (DEV08 F3, D8 a D10).

QA09: «dos ejecuciones con mismos insumos y semilla; comparar hashes de entradas y resultados
normalizados; iguales dentro de tolerancia; timestamps excluidos de la comparación científica».

Reglas, archivo por archivo de ``outputs/``:

- **XML de SUMO** (``tripinfo.xml``, ``statistics.xml`` y cualquier otro ``.xml`` o ``.xml.gz``,
  como la FCD comprimida): se comparan elemento por elemento, en orden, con sus atributos y
  descomprimidos. Los comentarios no cuentan: allí escribe
  SUMO la hora de generación. En ``statistics.xml`` se omite el bloque ``performance`` (tiempos de
  reloj de la corrida). Un número con decimales es igual si la diferencia relativa o la absoluta
  no supera la tolerancia; lo demás (enteros, textos) debe ser idéntico.
- **Tablas y JSON de la corrida** (``cohorte_conciliada.csv``, ``conciliacion.json``,
  ``summary.json`` y lo demás): idénticos byte a byte.
- **Fuera de la comparación**: ``tiempos.json`` y los registros (``sumo.log``, ``sumo.stdout.txt``,
  ``sumo.stderr.txt``), que llevan horas y duraciones.

Las entradas deben tener las mismas huellas y la misma semilla. El veredicto es ``equivalent`` solo
si todo coincide; si no, ``different`` con los motivos. Un veredicto ``different`` no es un error:
es un resultado.
"""

import gzip
import math
import zlib
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Literal

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError, iterparse

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.runner import SimulacionError
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.manifest import RunManifest
from semaforo.trazabilidad.store import OUTPUTS, read_run

__all__ = [
    "EXCLUDED",
    "FileComparison",
    "ReplicaReport",
    "Tolerance",
    "compare_runs",
]

EXCLUDED = frozenset({"tiempos.json", "sumo.log", "sumo.stdout.txt", "sumo.stderr.txt"})
SKIPPED_ELEMENTS: dict[str, frozenset[str]] = {"statistics.xml": frozenset({"performance"})}
MAX_XML_BYTES = 512 * 1024 * 1024
DEFAULT_TOLERANCE = 1e-9

Rule = Literal["xml", "exact", "excluded"]


class Tolerance(FrozenModel):
    """Diferencia admitida entre dos números con decimales: relativa o absoluta."""

    relative: float = DEFAULT_TOLERANCE
    absolute: float = DEFAULT_TOLERANCE


class FileComparison(FrozenModel):
    """Un archivo de salida comparado. ``equal`` es ``None`` si quedó fuera de la comparación."""

    path: str
    rule: Rule
    equal: bool | None
    differing_values: int
    detail: str | None


class ReplicaReport(FrozenModel):
    """Reporte de réplica entre dos corridas (``replica.json``)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    created_at: datetime
    run_a: str
    run_b: str
    case_id: str
    case_version: str
    scenario_id: str | None
    seed_a: int | None
    seed_b: int | None
    inputs_equal: bool
    input_differences: list[str]
    tolerance: Tolerance
    files: list[FileComparison]
    verdict: Literal["equivalent", "different"]
    reasons: list[str]


class _Capped:
    """Un flujo que falla si se leen más de ``MAX_XML_BYTES`` (descomprimidos)."""

    def __init__(self, stream: BinaryIO | gzip.GzipFile, name: str) -> None:
        self._stream = stream
        self._name = name
        self._left = MAX_XML_BYTES

    def read(self, size: int = -1, /) -> bytes:
        chunk = self._stream.read(size)
        self._left -= len(chunk)
        if self._left < 0:
            raise SimulacionError(
                ErrorCode.OUTPUT_INVALID, "el XML supera el tope para compararlo", self._name
            )
        return chunk


def _rule(name: str) -> Rule:
    if name in EXCLUDED:
        return "excluded"
    return "xml" if name.endswith((".xml", ".xml.gz")) else "exact"


def _elements(path: Path, skipped: frozenset[str]) -> Generator[tuple[str, dict[str, str], str]]:
    """Cada elemento (etiqueta, atributos, texto) en orden, sin los bloques ``skipped``."""
    if path.stat().st_size > MAX_XML_BYTES:
        raise SimulacionError(
            ErrorCode.OUTPUT_INVALID, "el XML supera el tope para compararlo", path.name
        )
    inside = 0
    with path.open("rb") as raw:
        stream = gzip.GzipFile(fileobj=raw) if path.name.endswith(".gz") else raw
        for event, element in iterparse(
            _Capped(stream, path.name), events=("start", "end"), forbid_dtd=True
        ):
            tag = str(element.tag)
            if event == "start":
                if tag in skipped or inside:
                    inside += 1
                continue
            if inside:
                inside -= 1
                continue
            yield tag, dict(element.attrib), (element.text or "").strip()
            element.clear()


def _same_value(left: str, right: str, tolerance: Tolerance) -> bool:
    if left == right:
        return True
    try:
        x, y = float(left), float(right)
    except ValueError:
        return False
    return math.isclose(x, y, rel_tol=tolerance.relative, abs_tol=tolerance.absolute)


def _compare_xml(a: Path, b: Path, name: str, tolerance: Tolerance) -> tuple[bool, int, str | None]:
    skipped = SKIPPED_ELEMENTS.get(name, frozenset())
    differing = 0
    first: str | None = None
    left, right = _elements(a, skipped), _elements(b, skipped)
    try:
        # Con una sola raíz, un elemento de más siempre corre el orden y lo detecta la etiqueta;
        # strict=True cubre igual el caso de largos distintos.
        for index, (one, other) in enumerate(zip(left, right, strict=True), start=1):
            (tag_a, attrs_a, text_a), (tag_b, attrs_b, text_b) = one, other
            if tag_a != tag_b or set(attrs_a) != set(attrs_b):
                return (
                    False,
                    differing + 1,
                    first or f"elemento {index}: <{tag_a}> frente a <{tag_b}>",
                )
            for key in sorted(attrs_a):
                if not _same_value(attrs_a[key], attrs_b[key], tolerance):
                    differing += 1
                    values = f"{attrs_a[key]} frente a {attrs_b[key]}"
                    first = first or f"elemento {index} <{tag_a}> {key}: {values}"
            if not _same_value(text_a, text_b, tolerance):
                differing += 1
                first = first or f"elemento {index} <{tag_a}>: el texto cambia"
    except (ParseError, DefusedXmlException, OSError, EOFError, zlib.error) as error:
        # antes que ValueError: DefusedXmlException lo es
        return False, differing + 1, f"no se puede leer como XML ({type(error).__name__})"
    except ValueError:  # zip(strict=True): una corrida tiene más elementos que la otra
        return False, differing + 1, first or "una corrida tiene más elementos"
    finally:  # cierra los dos archivos aunque se corte antes del final (Windows los bloquea)
        left.close()
        right.close()
    return differing == 0, differing, first


def _compare_file(
    folder_a: Path, folder_b: Path, name: str, tolerance: Tolerance
) -> FileComparison:
    rule = _rule(name)
    path = f"{OUTPUTS}/{name}"
    if rule == "excluded":
        return FileComparison(path=path, rule=rule, equal=None, differing_values=0, detail=None)
    a, b = folder_a / OUTPUTS / name, folder_b / OUTPUTS / name
    if rule == "exact":
        equal = sha256_file(a) == sha256_file(b)
        detail = None if equal else "el contenido no es idéntico"
        return FileComparison(
            path=path, rule=rule, equal=equal, differing_values=0 if equal else 1, detail=detail
        )
    equal, differing, detail = _compare_xml(a, b, name, tolerance)
    return FileComparison(
        path=path, rule=rule, equal=equal, differing_values=differing, detail=detail
    )


def _outputs(manifest: RunManifest) -> set[str]:
    return {artifact.path.removeprefix(f"{OUTPUTS}/") for artifact in manifest.outputs}


def _checked(runs_root: Path, run_id: str) -> RunManifest:
    manifest = read_run(runs_root, run_id)  # integridad primero (QA29): una alterada no se compara
    if manifest.status != "succeeded":
        raise SimulacionError(
            ErrorCode.INPUT_SCHEMA,
            f"solo se comparan corridas exitosas y {run_id} está {manifest.status}",
            "run_id",
        )
    return manifest


def compare_runs(
    runs_root: Path,
    run_a: str,
    run_b: str,
    *,
    created_at: datetime,
    tolerance: Tolerance | None = None,
) -> ReplicaReport:
    """Compara las corridas ``run_a`` y ``run_b`` de ``runs_root`` y devuelve el reporte.

    Raises:
        DomainError: PATH_NOT_ALLOWED si un identificador no es seguro; INPUT_SCHEMA si una corrida
            no existe, no es exitosa o se pide comparar una corrida consigo misma; HASH_MISMATCH si
            una corrida fue alterada; OUTPUT_INVALID si un XML supera el tope.
    """
    if run_a == run_b:
        raise SimulacionError(
            ErrorCode.INPUT_SCHEMA, "una corrida no se compara consigo misma", "run_b"
        )
    tolerance = tolerance or Tolerance()
    a, b = _checked(runs_root, run_a), _checked(runs_root, run_b)
    reasons: list[str] = []
    inputs_a = {item.path: item.sha256 for item in a.inputs}
    inputs_b = {item.path: item.sha256 for item in b.inputs}
    input_differences = sorted(
        p for p in inputs_a.keys() | inputs_b.keys() if inputs_a.get(p) != inputs_b.get(p)
    )
    if input_differences:
        reasons.append(
            f"las entradas no son las mismas ({len(input_differences)} archivos distintos)"
        )
    if a.seed != b.seed:
        reasons.append(f"la semilla no es la misma ({a.seed} frente a {b.seed})")
    if (a.case_id, a.case_version, a.scenario_id) != (b.case_id, b.case_version, b.scenario_id):
        reasons.append("no son del mismo caso, versión y escenario")
    names_a, names_b = _outputs(a), _outputs(b)
    only = sorted((names_a ^ names_b) - EXCLUDED)
    if only:
        reasons.append(f"una corrida tiene salidas que la otra no: {', '.join(only)}")
    files = [
        _compare_file(runs_root / run_a, runs_root / run_b, name, tolerance)
        for name in sorted(names_a & names_b)
    ]
    reasons.extend(f"{item.path}: {item.detail}" for item in files if item.equal is False)
    return ReplicaReport(
        created_at=created_at,
        run_a=run_a,
        run_b=run_b,
        case_id=a.case_id,
        case_version=a.case_version,
        scenario_id=a.scenario_id,
        seed_a=a.seed,
        seed_b=b.seed,
        inputs_equal=not input_differences,
        input_differences=input_differences,
        tolerance=tolerance,
        files=files,
        verdict="different" if reasons else "equivalent",
        reasons=reasons,
    )
