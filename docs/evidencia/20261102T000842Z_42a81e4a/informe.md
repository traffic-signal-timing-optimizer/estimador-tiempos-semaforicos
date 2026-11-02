# Registro de ejecución de pruebas: 2026-11-02T00:08:42+00:00

Written for: el Product Owner y el equipo, para revisar el resultado de QA01 a QA10.

> Este registro es evidencia. **No completa las tablas de resultados del Sprint 1:** eso lo hace el Product Owner a partir de este registro.

- **Resultado de la puerta:** sin fallos críticos (0 críticos, 0 mayores)
- **Commit:** `42a81e4a712d3c55e8e60c11e92c840f22f97f15`
- **Comando:** `python -m pytest -q tests`
- **Datos de prueba:** 30 archivos, identificador `2383423ac2b3bd90…`

## Entorno

| Dato | Valor |
|---|---|
| python | 3.12.3 |
| sistema | Windows 11 |
| sumo | 1.27.1 |
| memoria_disponible_mib | 4389 |
| semaforo | 0.1.0 |
| pydantic | 2.14.1 |
| defusedxml | 0.7.1 |
| pytest | 9.1.1 |
| hypothesis | 6.170.3 |

## Totales de la suite

1920 pasan, 0 fallan, 0 con error, 12 se saltan.

## Resultado por caso

| QA | Tipo | Tarea | Pruebas clave | Pasan | Fallan | Saltadas | Estado |
|---|---|---|---|---|---|---|---|
| QA01 | Unitario | DEV02 | 9 | 9 | 0 | 0 | cumplido |
| QA02 | Unitario | DEV02 | 44 | 44 | 0 | 0 | cumplido |
| QA03 | Unitario | DEV04 | 3 | 3 | 0 | 0 | cumplido |
| QA04 | Integración | DEV04 | 16 | 16 | 0 | 0 | cumplido |
| QA05 | Unitario | DEV04 | 4 | 4 | 0 | 0 | cumplido |
| QA06 | Unitario | DEV05 | 5 | 5 | 0 | 0 | cumplido |
| QA07 | Integración | DEV06, DEV07 | 10 | 10 | 0 | 0 | cumplido |
| QA08 | Integración | DEV07 | 25 | 25 | 0 | 0 | cumplido |
| QA09 | Integración | DEV08 | 14 | 14 | 0 | 0 | cumplido |
| QA10 | Seguridad | DEV00, DEV06, DEV07 | 128 | 117 | 0 | 11 | cumplido con salvedad |

## Pruebas saltadas en toda la suite (declaradas)

| QA | Prueba | Motivo |
|---|---|---|
| QA10 | `tests/unit/test_case_file.py::test_a_symlink_is_not_followed` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |
| QA10 | `tests/unit/test_case_network.py::test_a_network_reached_through_a_symlink_is_path_not_allowed` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |
| QA10 | `tests/unit/test_case_report.py::test_a_case_file_that_is_a_symlink_is_path_not_allowed` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |
| QA10 | `tests/unit/test_counts.py::test_a_counts_file_that_is_a_symlink_is_not_followed` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |
| — | `tests/unit/test_job.py::test_without_process_groups_nothing_is_attached` | la prueba solo aplica fuera de Windows |
| QA10 | `tests/unit/test_json_input.py::test_a_link_is_not_followed` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |
| QA10 | `tests/unit/test_process_edges.py::test_a_folder_that_is_a_link_is_not_followed` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |
| QA10 | `tests/unit/test_reception.py::test_a_symlink_in_the_source_is_rejected` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |
| QA10 | `tests/unit/test_reconcile.py::test_a_sheet_that_is_a_link_is_refused` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |
| QA10 | `tests/unit/test_reconcile.py::test_a_tripinfo_that_is_a_link_is_refused` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |
| QA10 | `tests/unit/test_run_inputs.py::test_a_folder_that_is_a_link_is_refused` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |
| QA10 | `tests/unit/test_run_inputs.py::test_a_file_that_is_a_link_is_refused` | este equipo no permite crear enlaces simbólicos sin privilegios; se cubren al activar el Modo de desarrollador de Windows (o en un equipo que lo permita) |

## Fallos

Ninguno.

## Ensayo de sensibilidad

32 cambios a propósito: 32 detectados, 0 sobrevivieron.

## Resumen de lo que demuestra cada caso

- **QA01:** Caso válido aceptado; copias con ID repetido o referencia inexistente rechazadas con campo y motivo
- **QA02:** Sin doble conteo de solapes; los inválidos nunca se aceptan
- **QA03:** 90 autos y 10 buses en 900 s: 400 veh/h, proporciones 0.9 y 0.1, original intacto
- **QA04:** Campo ausente, duplicado, -1, clase desconocida y fecha inválida: errores identificables, ninguna aceptación silenciosa
- **QA05:** Un cero conserva volumen 0 y composición nula; un faltante no se vuelve cero
- **QA06:** Control 100/0 y observado 90/5: error absoluto 10 y 5, relativo 0.1 y nulo, cobertura exacta
- **QA07:** `succeeded` solo si proceso y salidas son válidos; versión registrada; originales intactos
- **QA08:** Red inválida y salida truncada: `failed` con motivo, sin métricas
- **QA09:** Mismas entradas y semilla: iguales dentro de tolerancia, horas fuera
- **QA10:** Rutas, entidades y límites bloqueados; sin shell ni comando inyectado
