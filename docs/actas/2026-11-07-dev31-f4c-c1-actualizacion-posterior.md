Escrito para: el Product Owner y el equipo técnico.

# DEV31 F4c C1: actualización posterior al cierre original

- **Fecha:** 2026-11-07 (Lima).
- **Historia:** HU15.
- **Acta original:** `docs/actas/2026-11-07-dev31-f4c-c1-controles.md`.

El acta original registra correctamente el corte inicial de C1: 137 unidades cargadas de 140 publicadas, tres exclusiones pendientes y código de salida 5. Se conserva byte a byte porque su huella está registrada como artefacto de la base `semaforo`.

## Avances posteriores

1. El PO aplicó D7 mediante tres decisiones verificables «riesgo aceptado», una por cada corrida de DEV00. La conciliación posterior registró 143 unidades publicadas: 140 cargadas y 3 con decisión, código 0. El commit `ad04c8c` actualizó `docs/bd/huellas.json` a la carga `20261107T230813Z_9cd9f1e2`, con 2625 artefactos. Estas cifras vienen de la bitácora y de la verificación anterior; no reemplazan el corte original.
2. `docs/actas/2026-11-07-dev31-f4c-aprobacion-tres-huellas.md` registra que P7 y P9 comparan versión del esquema, huella de contenido y huella de reglas.
3. `docs/actas/2026-11-07-dev31-f4c-c1-p9-reversion-excepciones.md` registra la reversión cuando `verify()` lanza una excepción después de P8. Su puerta completa pasó con 5408 pruebas, una omitida y 43/43 contratos.

## Comprobación al iniciar C2

Una edición del acta original en el commit `3b4ddf3` hizo fallar P0: `bd verificar` informó un archivo raíz cambiado, precisamente el acta C1. Se restauraron sus bytes desde `a52123a`, sin tocar la base real. P0 volvió a pasar: 272 archivos raíz revisados, 0 cambiados; contenido `da4c33599f5668a3753cca70e193bf6fab98cbef302af53b9ca3b95e5b1ed0e0` y reglas `6e0eed086f3025847af5ae487be0cbc7b8e4b930dfc3fc6aadf16f0a0d76e257`, referencia de Git coincidente. Esta acta complementaria es nueva y no sustituye el archivo registrado por huella.
