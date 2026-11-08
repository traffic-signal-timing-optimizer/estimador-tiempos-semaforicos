Escrito para: el Product Owner (aprobación del cambio) y el equipo técnico (para repetir la comparación).

# Plan actual con las semillas de los finalistas (2001 a 2013)

- **Fecha:** 2026-11-08
- **Tarea:** cambio aparte de DEV31 F5, autorizado por el PO («sí publícalo»).
- **Motivo:** el plan actual no fue finalista en la búsqueda publicada, así que no tenía corridas con las semillas 2001 a 2013. Sin ellas no se podía restar frente a los finalistas, que es la pregunta del asesor.
- **Scripts:** `scripts/publica_plan_actual_finalistas.py` (publica las corridas y sus métricas en `datos/`). Una prueba previa en `D:\tmp\plan_actual_finalistas\` dio las mismas cifras.
- **Esquema:** no cambió (`sql-afadf606c1a2065b`). Sí cambió el contenido de la base: 13 corridas nuevas.

## Qué se publicó

- 13 corridas de SUMO del plan vigente (programa `20261031T041338Z_63437585`, ciclo 206 s), semillas 2001 a 2013, escenario ESC-SINT-001, protocolo `CASO001_DEV14_PILOTO` (el mismo de los finalistas).
- Entradas, corridas y métricas en `datos/derivados/entradas/`, `datos/ejecuciones/` y `datos/derivados/metricas/`.
- Cargadas con `bd cargar --preliminar --sueltas`: 13 cargadas, 140 ya estaban, 0 pendientes. Quedan como **diagnóstico** con su protocolo de métricas. Ninguna búsqueda ni corrida existente cambió.

## Resultados (las mismas 13 semillas)

| Plan | Ciclo | Corridas con atascos (teletransportes) | Corridas con choques | Corridas válidas | Demora media (s/veh) | Rango (s/veh) | Cola media (veh) | Detenciones por vehículo |
|---|---|---|---|---|---|---|---|---|
| **Plan actual** | 206 s | **9 de 13** | 0 | 4 | 101,6 | 97,4 a 105,3 | 86,9 | 1,2 |
| `eef59d99` | 176 s | **2 de 13** | 0 | 11 | **76,6** | 75,0 a 77,5 | **56,0** | 1,1 |
| `965408b3` | 221 s | **0 de 13** | 0 | 12 | 131,7 | 124,9 a 137,8 | 103,5 | 1,4 |
| `ced3ae82` | 143 s | 9 de 13 | **4 de 13** | 4 | 93,2 | 89,9 a 96,2 | 76,0 | 1,3 |

*Corrida válida: sin atascos ni choques, con demora medida. Cada columna usa solo sus corridas válidas.*

**Comparación pareada** (misma semilla, dos planes válidos):

| Finalista frente al plan actual | Pares válidos | Semillas | Diferencia media (s/veh) |
|---|---|---|---|
| `eef59d99` | 2 | 2008, 2012 | **−23,8** (menos espera) |
| `965408b3` | 4 | 2001, 2008, 2009, 2012 | **+27,2** (más espera) |
| `ced3ae82` | 1 | 2001 | −6,5 (menos espera) |

**Lectura:**
- No hay ningún finalista que sea mejor que el plan actual en todo. El plan actual tiene el peor balance de atascos junto con `ced3ae82`.
- `eef59d99` tiene la mejor combinación de demora y estabilidad, pero con solo 2 pares válidos la diferencia no es concluyente.
- `965408b3` no se atasca nunca, pero tarda más cuando el plan actual sí funciona.
- Con demanda sintética y 13 semillas, esto orienta el análisis. No reemplaza la prueba final.

## Cambios en el panel

- La comparación separa las corridas del plan actual con las semillas de finalistas (protocolo del finalista) de las de diagnóstico (protocolo DEV19). Antes se habrían mezclado.
- La sección de finalistas usa el plan actual con sus semillas, y agrega la tabla de diferencias por semilla.
- Hallazgo nuevo en Inicio con las cifras del plan actual en esas semillas.
- Pruebas: `tests/unit/test_panel_resumen.py` (+2 pruebas de separación y de pares).

## Pendientes

- Confirmar el commit de la referencia de huellas (`docs/bd/huellas.json`), porque la base cambió de contenido.
- Regenerar la evidencia y el panel sobre el repositorio limpio.
- Decidir si estas corridas se incluyen en la prueba final o se quedan como comparación de desarrollo.
