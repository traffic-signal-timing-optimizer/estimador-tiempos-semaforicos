Escrito para: el Product Owner (revisión de F2) y el equipo técnico (F3 a F8 de DEV31).

# DEV31 F2: FCD comprimida, código y equipo en el manifiesto, y métricas publicadas

- **Fecha:** 2026-11-06
- **Tarea:** DEV31 (historia propuesta HU15). Orden de fases: sección 13 de `docs/actas/2026-11-05-plan-base-de-datos.md`.
- **Estado:** hecho y **pendiente de tu revisión**. Cambia el código de las corridas nuevas (`src/`). No toca `datos/` (siguen las 133 corridas, sin carpeta `derivados/metricas`) ni `documentacion/`. Sin PostgreSQL.
- **Modelo:** Sonnet.
- **Complejidad:** media. **Riesgo:** medio (toca el corredor de SUMO y la réplica de DEV08). **Esfuerzo:** una sesión.

## Qué cambia para una corrida nueva

| Antes | Ahora |
|---|---|
| La FCD (archivo de posiciones de los vehículos) se publicaba como `fcd.xml` y pesaba el 92 % de la corrida | Se publica como `fcd.xml.gz`, con la misma información. SUMO sigue escribiendo `fcd.xml`; al terminar, el corredor la comprime y borra la original |
| El manifiesto anotaba solo SUMO, Python y el sistema operativo | Anota además el commit del código, si el código tenía cambios sin confirmar, el procesador, los núcleos, la memoria y la ubicación (local o nube) |
| Las métricas se calculaban al vuelo y se perdían | `publish_run_metrics` las publica una vez en `datos/derivados/metricas/<caso>/<run_id>/` (`metricas.json` y `manifiesto.json`), con la cola paso a paso |

## Medido con el caso real (caso-001)

La verificación corrió fuera de `datos/` (en `D:/tmp`, ya borrado) y solo leyó los insumos.

| Medida | Resultado |
|---|---|
| Una corrida existente (`20261103T162914Z_simulation_0e3bf866`), FCD sin comprimir | 39,0 MiB → 0,93 MiB comprimida (**2,4 %**) |
| Esa FCD leída de las dos formas | Los 2 100 pasos salen idénticos; mismo tiempo de lectura (2,7 s) |
| Una corrida nueva con SUMO real | Exitosa, 8,5 s. Salidas: **1,58 MiB** en total (la FCD comprimida, 0,58 MiB) |
| Sus métricas | Calculadas en 1,3 s. `metricas.json`: **395 KiB** (1 338 vehículos, 2 100 pasos de cola, 7 accesos). `manifiesto.json`: 0,74 KiB |
| Cola en la ventana de medición | 900 pasos contados de 900 esperados; cola media 86,5 vehículos |
| Releída | Igual a la publicada; la revisión del espacio de trabajo dice «íntegra» para la corrida y para sus métricas |

**Lo que anotó el manifiesto en esta laptop:** commit `19865b9…`, código con cambios sin confirmar (era cierto: F2 estaba sin commitear), procesador AMD Ryzen 9 4900HS con Radeon Graphics, 16 núcleos, 15,4 GB de memoria y ubicación local.

**Peso por corrida nueva:** unos 2,0 MiB (1,6 de salidas más 0,4 de métricas), frente a 22,8 MB de media antes: unas 11 veces menos. Para las 4 692 corridas de DEV16, alrededor de **9 GB en vez de 107 GB**. Es una estimación con una sola corrida nueva; se confirma en F4 con las 133.

## Cómo se verificó

- **Puerta de calidad completa:** `ruff` y `pyright` limpios; **5 235 pruebas pasan** (1 omitida, solo para sistemas que no son Windows); contratos **43/43**; ningún archivo de código oculto a git.
- **Pruebas nuevas:** 15 del equipo y el código, 9 de la compresión, 21 de las métricas publicadas, 5 de la cola paso a paso, 4 de la réplica con FCD comprimida y 1 de SUMO real que recorre todo (corrida, FCD comprimida, equipo, métricas publicadas y releídas).
- **Ensayo de daño a propósito:** 17 roturas del código, **17 detectadas**. La primera vez una sobrevivió (la memoria total podía ser la disponible sin que ninguna prueba lo notara); se agregó la prueba y ahora se detecta. El guion está en la carpeta de trabajo de la sesión (`f2_danio.py`) y deja cada archivo como estaba (se comprueba por su huella).

## Archivos

| Archivo | Cambio |
|---|---|
| `src/semaforo/simulacion/runner.py` | `compress_fcd` (gzip determinista, sin fecha ni nombre), `fcd_file` (la comprimida si está, si no la sin comprimir) y el equipo en el manifiesto |
| `src/semaforo/simulacion/environment.py` (nuevo) | Commit, cambios sin confirmar, procesador, núcleos, memoria y ubicación. Sin red, sin nombre del equipo, sin rutas |
| `src/semaforo/simulacion/resources.py` | Memoria total del equipo |
| `src/semaforo/simulacion/replica.py` | La réplica compara los `.xml.gz` como XML descomprimido y con tolerancia, con tope de tamaño descomprimido |
| `src/semaforo/evaluacion/metrics.py` | Cola paso a paso (`QueueSeries`); las medias salen de los mismos conteos |
| `src/semaforo/evaluacion/run_metrics.py` | Lee la FCD en cualquiera de las dos formas. Versión de las métricas 2.0.0 → **2.1.0** |
| `src/semaforo/evaluacion/published_metrics.py` (nuevo) | Publica y vuelve a leer verificadas las métricas de una corrida |
| `src/semaforo/app/integrity.py` | La revisión del espacio de trabajo cubre `derivados/metricas` |
| `docs/adr/ADR11-salidas-de-medicion.md` | Enmienda: la FCD se publica comprimida |
| `docs/bd/esquema.toml` y `docs/bd/diccionario.md` | Ver «Cambios al diseño de la base» |

## Cambios al diseño de la base

1. **Una columna nueva en `control.entornos`: `codigo_modificado`** (verdadero o falso). Sin ella, un commit anotado con el código a medio cambiar parecería describir todo el código. Pasa de 870 a **871 columnas**; el resto del esquema no cambia.
2. **Las fuentes que esperaban F2 ya existen:** `resultados_acceso`, `resultados_movimiento` y `cola_segundo` salen de `metricas.json`, y `vehiculos` y `resultados_corrida` completan sus columnas de métricas. Para las 133 corridas anteriores no hay `metricas.json`: el cargador las calcula con `evaluate_run` al cargarlas (F4).
3. **`cola_segundo`:** la serie incluye todos los pasos de la FCD, no solo los de la ventana. La columna `en_ventana` marca los que cuentan para el resumen. Con el caso real, 2 100 pasos de los que 900 cuentan. Un paso que la FCD no trae no tiene fila (nunca un cero inventado).
4. **Los nombres del manifiesto son en inglés** (`cloud`, `cpu_cores`…) y la base los traduce: `cloud` es `nube` en `ubicacion`.

## Si algún día corres en una nube

Funciona con cualquier proveedor. Antes de lanzar la simulación en ese servidor, define estas variables de entorno (en Windows: `$env:SEMAFORO_UBICACION = "nube"` en la ventana de PowerShell donde vas a correr):

| Variable | Qué dice | Ejemplo |
|---|---|---|
| `SEMAFORO_UBICACION` | `nube` o `local`. Sin ella se supone `local` | `nube` |
| `SEMAFORO_NUBE_PROVEEDOR` | Quién presta el servidor | `Microsoft Azure` |
| `SEMAFORO_NUBE_TIPO_MAQUINA` | El tipo de servidor que contrataste | `Standard_D4s_v5` |
| `SEMAFORO_NUBE_REGION` | Dónde está | `brazilsouth` |

En Linux, el programa además reconoce solo algunas nubes por el fabricante que declara el equipo (Amazon, Google, DigitalOcean, Hetzner, Alibaba, OpenStack). En Windows hay que declararlo. Si no declaras nada y corres en una nube, quedaría anotado «local»: por eso conviene declararlo siempre.

## Lo que se encontró al inspeccionar

1. **La réplica de DEV08 habría perdido su tolerancia.** Comparaba como XML solo lo que termina en `.xml` y todo lo demás «byte a byte». Con la FCD comprimida, dos corridas iguales salvo un decimal de más habrían salido «distintas». Corregido, con 4 pruebas (igual dentro de la tolerancia, distinta fuera, archivo roto y bomba de compresión).
2. **El borrado de la FCD original podía dejar dos copias.** Lo descubrió la verificación real: una copia de solo lectura no se podía borrar y quedaban las dos. Ahora, si no se puede borrar, se quita también la comprimida y todo queda como estaba (prueba nueva).
3. **`codigo_modificado` solo mira los archivos que git sigue.** Un archivo nuevo que aún no se agregó a git no cuenta. Es un límite, no un fallo; evita marcar «modificado» por carpetas como `.claude/` o `docs/auditorias/`.
4. **Ningún comando publica las métricas todavía.** La función está lista, probada y verificada con SUMO real, pero hoy nadie la llama en el flujo normal. Dos opciones, para decidir al planificar F3: que la llame DEV16 después de cada corrida, o que `bd cargar` publique las que falten (en carpetas nuevas de `derivados/metricas`, sin tocar lo existente). Mi recomendación es la segunda para las 133 corridas y la primera para las nuevas.
5. **Las 133 corridas existentes no se tocaron.** Siguen con `fcd.xml` y sin `metricas.json`; el lector acepta las dos formas.
6. **`ADR03` (guardar en git las huellas de lo publicado) no entra en F2.** La sección 13 del plan no lo asigna a ninguna fase. Propongo hacerlo en F3, como parte de `bd verificar` y `bd exportar`. Pregunta 2.
7. **El manifiesto de la corrida no cambia de contrato.** `environment` ya era un diccionario libre de textos; los contratos siguen en 43/43.

## Documentación que cambiará en F7

`documentacion/` no menciona `fcd.xml` (solo `CONTEXTO.md` y las actas). En F7 habrá que describir en el documento 01 la FCD comprimida, el registro del equipo y `metricas.json` como artefacto publicado; el acta de F1 queda con sus cifras de entonces (870 columnas).

## Lo que pido al PO

1. ¿Apruebas F2?
2. ¿Hago `ADR03` (huellas en git) dentro de F3?
3. ¿Quién llama a la publicación de métricas: DEV16 para las nuevas y `bd cargar` para las 133 (mi recomendación), o solo `bd cargar`?
4. ¿Ejecuto F3 (PostgreSQL y cargador)? Es de complejidad media-alta y recomiendo **Opus**. Antes de tocar PostgreSQL te daré los pasos exactos para restringirlo a la laptop.
