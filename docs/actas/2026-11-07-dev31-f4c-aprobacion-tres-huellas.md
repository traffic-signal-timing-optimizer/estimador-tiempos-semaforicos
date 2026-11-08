Escrito para: el Product Owner y el equipo técnico (corrección de la puerta final de `bd reconstruir`).

# DEV31 F4c: la aprobación de la reconstrucción usa tres huellas

- **Fecha:** 2026-11-07
- **Tarea:** DEV31 (HU15), etapa C1.11 del plan de correcciones (`docs/actas/2026-11-07-dev31-plan-correcciones-auditoria.md`).
- **Commit:** `05e55b3` (crisroco, en `origin/main`).
- **Origen:** revisión del PO sobre la puerta final de `bd reconstruir`.

## El problema

`bd reconstruir preparar` calculaba tres huellas de la candidata: la versión del esquema, la huella de contenido (las filas) y la huella de reglas instaladas (permisos, políticas, disparadores, funciones, vistas e índices). Pero `bd reconstruir cambiar` solo recibía y comprobaba la huella de contenido.

Consecuencia: una candidata con permisos, políticas o disparadores cambiados, pero con las mismas filas, podía pasar P7 (antes del cambio de nombre) y P9 (después). El PO aprobaría una huella que no describe toda la base.

## Qué se cambió

- La aprobación son las **tres huellas** que dejó la preparación: versión del esquema, contenido y reglas. Se modela como `Approval` en `app/bd_reconstruir.py`.
- **P7** (antes de cambiar nombres) y **P9** (después) comparan las tres. Si una no coincide, se detiene y se dice cuál. En P9, además, se revierte el cambio de nombre.
- `bd reconstruir cambiar` pide ahora `--esquema-aprobado`, `--huella-aprobada` y `--reglas-aprobadas`. El resumen de `preparar` muestra las tres para copiarlas.

## Cómo se verificó

- Pruebas de reconstrucción: 14 de 14. Son 4 pruebas nuevas:
  - reglas distintas con las mismas filas, detenido en P7;
  - esquema distinto, detenido en P7;
  - contenido distinto con esquema y reglas correctos, detenido en P7;
  - un disparador desactivado durante el cambio de nombre, detectado en P9 y revertido.
- Ensayo de daño `dev31_c1.py` sobre la aprobación: cada una de las tres comprobaciones y la comprobación final se detecta. Antes de agregar la prueba de contenido, ese daño sobrevivía; por eso se agregó.
- Puerta de calidad completa: **5406 pruebas pasaron, 1 omitida** (la misma de siempre), contratos y verificaciones en verde, código de salida 0.

## Límites

- Esta corrección no cambia la base real. No se ejecutó `bd reconstruir` sobre `semaforo`; eso va en C2, con orden expresa del PO.
- El acta de C1 (`2026-11-07-dev31-f4c-c1-controles.md`) describe la aprobación con una sola huella. Esa descripción quedó superada por esta acta.
