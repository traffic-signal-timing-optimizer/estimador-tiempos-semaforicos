# ADR04: Ejecución de SUMO por subprocess

- **Estado:** Aceptada el 2026-11-08 (DEC09, por delegación del PO)
- **Tipo:** P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

## Decisión

SUMO se ejecuta con `subprocess`, con lista de argumentos, sin shell y con un directorio aislado por corrida. La consulta no necesita TraCI. Si la instrumentación por lotes no obtiene los datos requeridos, se documentará un adaptador de medición separado antes de ampliar dependencias.

## Motivo

Evitar inyección de comandos y garantizar que cada corrida sea reproducible y aislada.

## Alternativas descartadas

- Ejecución mediante shell: riesgo de inyección; prohibido por la documentación.
- TraCI en la consulta: no es necesario, porque la consulta no ejecuta SUMO.

## Impacto

Solo el módulo `simulacion` lanza procesos. La regla queda verificada en `tests/unit/test_estructura.py`.

## Prueba de aceptación

QA07 (estado succeeded solo con salidas válidas), QA08 (red inválida y XML truncado producen failed sin métricas) y QA10 (rutas, DTD y metacaracteres bloqueados; sin shell).

## Precisiones de DEC09 (2026-11-08)

Análisis y motivo: `docs/actas/2026-11-08-dev31-f7-dec09.md`.

1. **La regla cubre las herramientas cortas.** `simulacion/herramientas.py` lanza `git`, `icacls`, `pg_dump` y `pg_restore` con lista fija de argumentos, sin consola y con tiempo máximo. Sigue siendo cierto que solo `simulacion` lanza procesos (`tests/unit/test_estructura.py`).
2. **Corridas en paralelo.** El documento 01 pedía empezar con una a la vez y ampliar tras medir. La búsqueda de DEV14 corre 4 a la vez como valor inicial y consulta los recursos antes de lanzar cada una (`referencias/evaluation.py`). DEV16 ajusta ese número midiendo memoria y disco.
3. **Sin TraCI.** Sigue sin usarse. Las salidas de medición se piden a SUMO por archivos (ADR11).
4. **Otra máquina.** El mismo adaptador sirve donde esté instalado SUMO. La versión queda en cada manifiesto: las corridas de una misma comparación deben usar la misma versión.
