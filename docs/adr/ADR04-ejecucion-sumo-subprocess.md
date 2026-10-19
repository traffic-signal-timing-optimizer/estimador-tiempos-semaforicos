# ADR04: Ejecución de SUMO por subprocess

- **Estado:** Propuesta
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
