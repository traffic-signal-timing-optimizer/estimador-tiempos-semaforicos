"""Catálogo ejecutable de QA01 a QA10: qué pruebas demuestran cada resultado esperado (DEV10).

Cada entrada es ``"ruta/del/archivo.py"`` (todas sus pruebas) o ``"ruta/del/archivo.py::prefijo"``
(las pruebas cuyo nombre empieza con ese prefijo). Son las pruebas **clave**: las que afirman el
resultado esperado del caso de ``documentacion/matrices/pruebas.csv``. Hay muchas más pruebas
alrededor; estas son las que cuentan para decir que un QA se cumple.

Lo usan ``tests/unit/test_qa_catalog.py`` (vigila que el catálogo no se pudra) y
``scripts/evidencia.py`` (registro de ejecución).
"""

import ast
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

__all__ = ["CATALOG", "ROOT", "Qa", "list_tests", "resolve"]


@dataclass(frozen=True)
class Qa:
    """Un caso de la documentación y las pruebas que lo demuestran."""

    qa_id: str
    kind: str
    task: str
    summary: str
    key_tests: tuple[str, ...]


CATALOG: tuple[Qa, ...] = (
    Qa(
        "QA01",
        "Unitario",
        "DEV02",
        "Caso válido aceptado; copias con ID repetido o referencia inexistente rechazadas "
        "con campo y motivo",
        (
            "tests/unit/test_case_rules.py::test_the_reference_case_passes_every_rule",
            "tests/unit/test_case_rules.py::test_qa01_",
            "tests/unit/test_case_rules.py::test_a_group_with_a_repeated_slot_is_rejected",
            "tests/unit/test_case_file.py::test_the_consistency_rules_are_applied_to_the_file",
        ),
    ),
    Qa(
        "QA02",
        "Unitario",
        "DEV02",
        "Sin doble conteo de solapes; los inválidos nunca se aceptan",
        (
            "tests/unit/test_case_rules.py::test_qa02_",
            "tests/unit/test_case_rules.py::test_the_cycle_is_feasible_exactly_when",
            "tests/unit/test_case_rules.py::test_a_group_is_reachable_exactly_when",
        ),
    ),
    Qa(
        "QA03",
        "Unitario",
        "DEV04",
        "90 autos y 10 buses en 900 s: 400 veh/h, proporciones 0.9 y 0.1, original intacto",
        (
            "tests/unit/test_counts.py::test_the_fixture_normalizes_to_the_expected_flows",
            "tests/unit/test_counts.py::test_the_original_file_is_read_without_changing",
            "tests/unit/test_counts.py::test_the_fixture_round_trips",
        ),
    ),
    Qa(
        "QA04",
        "Integración",
        "DEV04",
        "Campo ausente, duplicado, -1, clase desconocida y fecha inválida: errores "
        "identificables, ninguna aceptación silenciosa",
        (
            "tests/unit/test_counts.py::test_qa04_",
            "tests/unit/test_counts.py::test_a_missing_column_in_the_header",
            "tests/unit/test_counts.py::test_an_empty_mandatory_field",
            "tests/unit/test_counts.py::test_a_duplicated_key",
            "tests/unit/test_counts.py::test_a_negative_count",
            "tests/unit/test_counts.py::test_an_unknown_vehicle_class",
            "tests/unit/test_counts.py::test_an_invalid_or_inverted_date",
            "tests/unit/test_counts.py::test_every_problem_is_reported",
        ),
    ),
    Qa(
        "QA05",
        "Unitario",
        "DEV04",
        "Un cero conserva volumen 0 y composición nula; un faltante no se vuelve cero",
        (
            "tests/unit/test_counts.py::test_an_observed_zero_keeps",
            "tests/unit/test_counts.py::test_a_missing_row_makes_the_period_incomplete",
            "tests/unit/test_counts.py::test_complete_and_incomplete_periods",
            "tests/unit/test_quality.py::test_a_missing_row_is_never_compared_as_a_zero",
        ),
    ),
    Qa(
        "QA06",
        "Unitario",
        "DEV05",
        "Control 100/0 y observado 90/5: error absoluto 10 y 5, relativo 0.1 y nulo, "
        "cobertura exacta",
        (
            "tests/unit/test_quality.py::test_qa06_",
            "tests/unit/test_quality_report.py::test_qa06_",
            "tests/unit/test_coverage.py::test_an_incomplete_period_is_not_covered",
            "tests/unit/test_coverage.py::test_a_fully_covered_window_has_coverage_one",
        ),
    ),
    Qa(
        "QA07",
        "Integración",
        "DEV06, DEV07",
        "`succeeded` solo si proceso y salidas son válidos; versión registrada; originales "
        "intactos",
        (
            "tests/integration/test_runner_sumo.py::test_a_base_run_of_the_fixture_succeeds",
            "tests/integration/test_runner_sumo.py::test_an_invalid_case_fails_with_a_reason",
            "tests/unit/test_runner.py::test_incoherent_outputs_are_invalid",
            "tests/integration/test_prepared_run_sumo.py::test_a_prepared_folder_runs",
            "tests/integration/test_prepared_run_sumo.py::test_the_run_records_the_hash",
            "tests/integration/test_prepared_run_sumo.py::test_the_original_inputs_stay_intact",
            "tests/integration/test_run_inputs_sumo.py::test_a_prepared_folder_runs_and_publishes",
        ),
    ),
    Qa(
        "QA08",
        "Integración",
        "DEV07",
        "Red inválida y salida truncada: `failed` con motivo, sin métricas",
        (
            "tests/integration/test_runner_sumo.py::test_an_invalid_case_fails_with_a_reason",
            "tests/integration/test_runner_sumo.py::test_incoherent_outputs_fail_without_metrics",
            "tests/integration/test_runner_sumo.py::test_a_run_over_the_wall_clock_limit",
            "tests/unit/test_runner.py::test_truncated_outputs_are_invalid",
            "tests/unit/test_runner.py::test_incoherent_outputs_are_invalid",
            "tests/unit/test_runner.py::test_missing_outputs_are_invalid",
            "tests/unit/test_runner.py::test_empty_but_well_formed_outputs_are_invalid",
            "tests/integration/test_run_control_sumo.py",
        ),
    ),
    Qa(
        "QA09",
        "Integración",
        "DEV08",
        "Mismas entradas y semilla: iguales dentro de tolerancia, horas fuera",
        (
            "tests/unit/test_replica.py::test_two_identical_runs_are_equivalent",
            "tests/unit/test_replica.py::test_the_generation_time_written_by_sumo",
            "tests/unit/test_replica.py::test_a_float_beyond_the_tolerance",
            "tests/unit/test_replica.py::test_a_different_structure",
            "tests/unit/test_replica.py::test_an_output_that_only_one_run_has",
            "tests/unit/test_replica.py::test_different_inputs_or_seeds",
            "tests/integration/test_replica_sumo.py",
        ),
    ),
    Qa(
        "QA10",
        "Seguridad",
        "DEV00, DEV06, DEV07",
        "Rutas, entidades y límites bloqueados; sin shell ni comando inyectado",
        (
            "tests/security/test_dev06_inputs.py",
            "tests/security/test_dev07_run.py",
            "tests/unit/test_paths.py",
            "tests/unit/test_bounded_read.py",
            "tests/unit/test_tripinfo.py::test_a_dtd_is_refused",
            "tests/unit/test_tripinfo.py::test_an_entity_bomb_is_refused",
            "tests/unit/test_tripinfo.py::test_the_limit_counts_the_decompressed_bytes",
            "tests/unit/test_reconcile.py::test_an_xml_with_a_dtd_is_refused",
            "tests/unit/test_audit.py::test_rejects_invalid_or_dangerous_route_files",
            "tests/unit/test_inventory.py::test_rejects_invalid_or_dangerous_nets",
            "tests/unit/test_sumo_config.py::test_option_reading_rejects_dangerous_xml",
            "tests/unit/test_sumo_config.py::test_rejects_invalid_or_dangerous_xml",
            "tests/unit/test_inventory.py::test_the_limit_applies_to_the_decompressed_size",
            "tests/unit/test_run_inputs.py::test_a_folder_that_is_a_link_is_refused",
            "tests/unit/test_run_inputs.py::test_a_file_that_is_a_link_is_refused",
            "tests/unit/test_process_edges.py::test_the_process_is_launched_without_a_shell",
            "tests/integration/test_prepared_run_sumo.py::test_names_with_shell_characters",
            "tests/unit/test_counts.py::test_a_counts_file_that_",
        ),
    ),
)


@cache
def list_tests(path: Path) -> list[str]:
    """Nombres de las pruebas (``test_*``) de un archivo, en el orden en que aparecen."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


@cache
def resolve(entry: str) -> list[str]:
    """Identificadores de pytest (``archivo::función``) que cubre una entrada del catálogo.

    Una entrada sin prefijo cubre el archivo entero (se devuelve su ruta). Devuelve una lista
    vacía si el archivo no existe o ninguna prueba empieza con el prefijo.
    """
    file_part, _, prefix = entry.partition("::")
    path = ROOT / file_part
    if not path.is_file():
        return []
    if not prefix:
        return [file_part] if list_tests(path) else []
    return [f"{file_part}::{name}" for name in list_tests(path) if name.startswith(prefix)]
