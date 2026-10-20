# Acta 2026-10-20: DEV00 · F5 (núcleo de trazabilidad)

- **Tipo:** registro de fase del plan de DEV00 (HU14). Adelanta parte de DEV08 (persistir trazabilidad).
- **Fecha:** 2026-10-20
- **Autorización:** el Product Owner autorizó F5 («ejecuta F5»).
- **Código y pruebas:** commit `f3c9bf2`.
- **Siguiente fase:** F6 (runner mínimo de SUMO), completada: ver `docs/actas/2026-10-20-dev00-f6-runner-de-sumo.md`. F6 acortó el nombre de la carpeta temporal (ver abajo).

## Qué se implementó

| Módulo | Responsabilidad |
|---|---|
| `trazabilidad/manifest.py` | DTO del contrato `run_manifest` (`RunManifest`, `Artifact`, `Error`) |
| `trazabilidad/store.py` | `RunWriter` (escritura temporal y publicación atómica) y `read_run` (lectura verificada) |
| `trazabilidad/paths.py` | validación única de rutas relativas, usada también por el manifiesto de recepción y `sumo_config` |
| `dominio/errors.py` | `ErrorCode` y `DomainError`, compartidos por todos los módulos; `CasoError` deriva de `DomainError` |

## Cómo funciona una ejecución

Sigue el diseño técnico, apartado «Integración y transacciones»:

1. **Al crearla:** se toma un lock exclusivo `.lock-<run_id>` y se crea la carpeta temporal `.tmp-<8 caracteres>` con un manifiesto provisional en estado `running`, que contiene el `run_id`. El nombre se acortó en F6 porque SUMO no abre rutas de más de 257 caracteres en Windows. Si la ejecución ya existe o se está escribiendo, se rechaza.
2. **Mientras se escribe:** las entradas se copian a `inputs/` con su hash (se comprueba que el origen no cambie durante la copia) y las salidas se escriben en `outputs/`.
3. **Al publicar:** se rechazan enlaces, entradas sin registrar y archivos sueltos. Se comprueba que las entradas no cambiaron, se calculan los hashes de las salidas, se valida el contrato y se escribe el manifiesto final. Después la carpeta se marca de solo lectura y se publica con un renombrado.
4. **Si algo falla antes de publicar:** la carpeta temporal queda incompleta, sigue marcada `running` y el lock se libera. Ninguna lectura la toma por una ejecución publicada.
5. **Al leer:** `read_run` exige que la carpeta tenga exactamente los archivos del manifiesto, con sus hashes, y que el manifiesto sea de esa ejecución.

## Decisiones tomadas en F5

1. **El esquema del DTO es idéntico al publicado.** Se comprobó que `schemas/run_manifest.schema.json` es el esquema del modelo de referencia más un título y la clave `$schema`. El DTO reproduce los campos en el mismo orden y añade esas dos cosas. Sus clases se documentan con comentarios, porque pydantic convertiría las docstrings en `description` y el esquema dejaría de coincidir.
2. **Reglas añadidas que no cambian el esquema:** el `run_id` debe servir como nombre de carpeta, `created_at` debe llevar zona horaria, las rutas de los artefactos son relativas a la carpeta de la ejecución, no se repiten artefactos y una ejecución `succeeded` no lleva error. Una prueba comprueba que el DTO rechaza todo lo que rechaza el modelo de referencia.
3. **Formato del `run_id`:** `<AAAAMMDDTHHMMSSZ>_<kind>_<8 hexadecimales aleatorios>`, ordenable por fecha y único.
4. **Disposición de la carpeta:** `manifest.json`, `inputs/` y `outputs/`. Las rutas del manifiesto son relativas a la carpeta, así que la ejecución es autocontenida. Todo lo que hay en `outputs/` se registra como salida.
5. **Códigos de error:** `ErrorCode` pasa a `dominio`, porque `trazabilidad` no debe depender de `caso`. Se añaden `OUTPUT_INVALID`, que figura en la lista de la documentación, y `RUN_EXISTS`, que no figura: una ejecución que ya existe o que otro proceso está escribiendo.
6. **Una sola validación de rutas** en `trazabilidad/paths.py`. Antes había una copia en el manifiesto de recepción.

## Evidencia de la puerta de salida

Las tres entradas reales de la copia inmutable de R0 se empaquetaron como ejecución en una carpeta temporal fuera del repositorio (estado `cancelled`, porque SUMO no se ejecuta hasta F6):

| Comprobación | Resultado |
|---|---|
| `snapshot_id` reconstruido con los hashes de las entradas de la ejecución | igual al de F2: la ejecución y la recepción quedan enlazadas por contenido |
| Lectura verificada | igual al manifiesto publicado |
| Restos | en la raíz solo queda la ejecución publicada: ni carpeta temporal ni lock |
| Alteración de un byte de una entrada | detectada (`HASH_MISMATCH`) |
| Copia de F2 | hash y fecha sin cambios |

## Verificación

- Pruebas: 339 pasan y 1 se salta de forma declarada (enlaces simbólicos sin privilegios). F5 añade 85.
- Las pruebas se escribieron y fallaron antes del código (módulos inexistentes). Al implementar, dos fallaron por defectos reales que se corrigieron: el esquema incluía las docstrings, y un `run_id` vacío se reemplazaba en silencio por uno generado.
- Veintinueve mutaciones del código fueron detectadas. Una sobrevivió al principio (la comprobación previa del destino al publicar, que en Windows también cubre el renombrado) y se cerró comprobando que, si se rechaza la publicación, la carpeta temporal sigue marcada `running`.
- `ruff`, formato y `pyright` estricto sin errores; el validador de contratos sigue en 43 comprobaciones.

## Limitaciones conocidas

- **Autenticidad:** `read_run` comprueba la coherencia entre la carpeta y su propio manifiesto. Quien pueda escribir en la carpeta puede rehacer ambos. ADR03 lo advierte: un hash guardado junto a un archivo modificable no acredita por sí solo autenticidad. La recepción de F7 deberá registrar el hash del manifiesto en su propio artefacto.
- **Lock tras una caída abrupta:** si el proceso muere sin ejecutar su limpieza, el lock queda y bloquea ese `run_id`. Como los `run_id` son únicos, no afecta a ejecuciones nuevas.
- **Carpetas incompletas:** las carpetas `.tmp-` que deja una caída no se borran solas. Se conservan como evidencia; listarlas o limpiarlas es trabajo posterior.
- La carpeta publicada es de solo lectura contra accidentes, no contra quien tenga permisos sobre ella.
