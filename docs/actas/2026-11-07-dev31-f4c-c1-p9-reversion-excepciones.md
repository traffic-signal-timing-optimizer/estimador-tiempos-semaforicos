Escrito para: el Product Owner y el equipo técnico.

# DEV31 F4c C1.11: reversión cuando falla la verificación P9

- **Fecha:** 2026-11-07 (Lima).
- **Historia:** HU15.
- **Orden del PO:** «Ejecuta la corrección» tras revisar el fallo de P9.
- **Alcance:** `src/semaforo/app/bd_reconstruir.py` y `tests/integration/test_bd_reconstruccion.py`.

## Problema y corrección

Después de cambiar los nombres en P8, `switch_database` revertía el cambio si P9 encontraba una huella distinta. Si `verify()` lanzaba una excepción, la función salía antes de intentar la reversión.

Ahora ambos fallos siguen el mismo camino. Se intenta devolver la base anterior a su nombre y se informa «P9 detenida» solo cuando la reversión termina. Si la reversión también falla, se levanta un error que incluye la causa original, la falla de reversión y los tres nombres de base para comprobar su estado. No se afirma que la base anterior haya sido restaurada en ese caso.

## Pruebas y resultados

1. Dos pruebas nuevas provocaron primero el defecto: **2 fallaron** antes del cambio. Una fuerza una excepción de `verify()` después de P8. La otra hace fallar también la reversión.
2. Con la corrección, ambas pasaron: **2/2** en bases temporales `semaforo_pruebas_*`. La primera comprobó que la base anterior vuelve a su nombre, que la candidata permanece y que no queda la base anterior con nombre temporal. La segunda comprobó el error explícito de estado por verificar y los tres nombres.
3. `scripts/check.ps1` terminó con código 0. Ruff, formato y Pyright sin observaciones. Esquema al día: 56 tablas, 871 columnas y 113 relaciones. **5408 pruebas pasaron, 1 se omitió** (11 min 41 s). Contratos **43/43**. No había procesos SUMO o Python activos antes de la puerta; se midieron **3,18 GB** de memoria libre.

## Límite y siguiente paso

La prueba usa bases temporales. No se cambió la base real `semaforo` ni se ejecutó la reconstrucción de C2. P0 a P9 de C2 y la aprobación D11 siguen sujetos a la orden y a las puertas del plan.
