"""Réplica con SUMO real (QA09 en DEV07): mismas entradas y semilla, mismos resultados.

Compara las huellas de las entradas y de los resultados normalizados. Quedan fuera de la
comparación científica las horas y las duraciones: `tiempos.json`, `sumo.log` y `statistics.xml`
(que trae el tiempo que tardó SUMO).

Hallazgo de F5: SUMO escribe en la segunda línea de cada XML un comentario con la hora
(`<!-- generated on ... -->`), así que la huella cruda de `tripinfo.xml` nunca coincide entre dos
corridas. Hay que normalizar quitando ese comentario antes de comparar. El reporte formal de
réplica, con esa normalización, es de DEV08; aquí queda la evidencia de que, normalizadas, las
corridas que publica DEV07 son iguales.
"""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.simulacion.prepare import publish_inputs
from semaforo.simulacion.run_inputs import CONCILIATION_SUMMARY, CONCILIATION_TABLE, run_inputs
from semaforo.simulacion.runner import TIMING
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.manifest import RunManifest

pytestmark = pytest.mark.sumo

SCIENTIFIC = ("tripinfo.xml", CONCILIATION_TABLE, CONCILIATION_SUMMARY)  # sin horas ni duraciones


def clock() -> datetime:
    return datetime(2026, 11, 1, 18, 0, tzinfo=UTC)


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


@pytest.fixture
def folder(tmp_path: Path) -> Iterator[Path]:
    yield publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    remove_tree(tmp_path / "entradas")


GENERATED_ON = b"<!-- generated on "


def normalized_sha256(path: Path) -> str:
    """Huella del XML sin la línea del comentario con la hora de generación."""
    lines = [line for line in path.read_bytes().splitlines() if not line.startswith(GENERATED_ON)]
    return hashlib.sha256(b"\n".join(lines)).hexdigest()


def hashes(manifest: RunManifest, names: tuple[str, ...]) -> dict[str, str]:
    return {a.path: a.sha256 for a in manifest.outputs if a.path.removeprefix("outputs/") in names}


def test_two_runs_of_the_same_inputs_have_the_same_inputs_and_results(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    first = run_inputs(folder, runs, sumo=sumo_binary, clock=clock).manifest
    second = run_inputs(folder, runs, sumo=sumo_binary, clock=clock).manifest
    assert (first.status, second.status) == ("succeeded", "succeeded")
    assert first.run_id != second.run_id
    assert [(a.path, a.sha256) for a in first.inputs] == [(a.path, a.sha256) for a in second.inputs]
    assert (first.seed, first.scenario_id) == (second.seed, second.scenario_id)
    # lo que no lleva hora: la tabla de la cohorte y los conteos son idénticos tal cual
    plain = (CONCILIATION_TABLE, CONCILIATION_SUMMARY)
    assert set(hashes(first, plain)) == {f"outputs/{name}" for name in plain}
    assert hashes(first, plain) == hashes(second, plain)
    # el tripinfo es idéntico una vez quitado el comentario con la hora de SUMO
    a = runs / first.run_id / "outputs" / "tripinfo.xml"
    b = runs / second.run_id / "outputs" / "tripinfo.xml"
    assert normalized_sha256(a) == normalized_sha256(b)


def test_the_raw_tripinfo_differs_only_by_the_generation_time(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    first = run_inputs(folder, runs, sumo=sumo_binary, clock=clock).manifest
    second = run_inputs(folder, runs, sumo=sumo_binary, clock=clock).manifest
    lines = [
        (runs / run.run_id / "outputs" / "tripinfo.xml").read_bytes().splitlines()
        for run in (first, second)
    ]
    differing = [(x, y) for x, y in zip(*lines, strict=True) if x != y]
    assert len(lines[0]) == len(lines[1])
    assert len(differing) == 1
    assert all(line.startswith(GENERATED_ON) for line in differing[0])


def test_the_times_of_a_run_are_not_part_of_the_scientific_comparison(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_inputs(folder, runs, sumo=sumo_binary, clock=clock).manifest
    assert f"outputs/{TIMING}" in {a.path for a in result.outputs}
    assert TIMING not in SCIENTIFIC  # la comparación nunca depende de cuánto tardó
