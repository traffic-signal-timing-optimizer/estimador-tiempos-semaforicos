Escrito para: el Product Owner (revisión del cambio) y el equipo técnico (F5 a F8 de DEV31).

# DEV31: la cola se guarda como un arreglo por acceso

- **Fecha:** 2026-11-07
- **Tarea:** DEV31 (historia HU15), cambio de diseño pedido en la revisión de F4. Orden de fases: sección 13 de `docs/actas/2026-11-05-plan-base-de-datos.md`.
- **Aprobación del PO:** 2026-11-07, «de acuerdo, guárdalo como un arreglo por acceso» (pregunta 2 del acta de F4).
- **Estado:** hecho y comprobado. **Sin subir a GitHub**; el commit lo hace crisroco en este mismo trabajo.
- **Modelo:** Haiku 5.5 (el PO cambió el modelo de la sesión). **Complejidad:** media. **Riesgo:** bajo-medio (se reconstruye la base; no hay datos que se pierdan, porque todo sale de los archivos). **Esfuerzo:** una sesión.

## Qué cambió y por qué

En F4 se midió que la cola segundo a segundo pesaba 4 veces más de lo estimado: cada paso era una fila con dos textos largos repetidos. El PO aprobó guardarla de otra forma.

| Antes (F4) | Ahora |
|---|---|
| Una fila por corrida, acceso y segundo (`simulacion.cola_segundo`, 1 911 000 filas) | Una fila por corrida y acceso (`simulacion.cola_por_acceso`, 910 filas). Cada fila guarda un arreglo con un número por segundo |
| Los momentos de los pasos se repetían en cada fila | Los momentos y su marca de ventana van **una vez por corrida**, en `simulacion.resultados_corrida` (`pasos_cola_s` y `pasos_en_ventana`) |
| Ninguna regla comprobaba que una serie estuviera completa | Disparador `simulacion.validar_cola()`: cada arreglo debe tener un valor por cada paso de su corrida; si no, se rechaza con código SM006 |
| `vistas.cola_por_segundo` leía la tabla | La vista sigue mostrando **una fila por corrida, acceso y paso**, como antes. El panel y las consultas no cambian |

**Tamaño medido con las 130 corridas:**

| | Antes | Ahora |
|---|---|---|
| Tabla de la cola | 536 MB (1 911 000 filas) | 1,3 MB (910 filas) |
| Base completa | 669 MB | 137 MB |

Medido con la base nueva: la cola (`cola_por_acceso`) pesa 1,3 MB y `resultados_corrida` (que ya incluye los pasos) pesa 1,3 MB. Los 1,9 MB de F4 fueron una medición de la alternativa con tablas temporales, y la forma real que quedó aquí pesa del mismo orden; la cifra que vale es la de la tabla de arriba.

## Decisiones de diseño tomadas aquí

1. **La cola depende de `resultados_corrida`**, además de `corridas` (que el diseño exige para toda tabla con `run_id`). Así el cargador escribe primero la corrida y sus pasos, y el disparador puede comprobar la longitud.
2. **El acta F0 no se reescribe.** Su catálogo sigue diciendo `cola_segundo`; el cambio de nombre queda registrado en `scripts/bd_esquema.py` (`RENAMED_SINCE_F0`), con referencia a esta acta.
3. **La conciliación cuenta en las tablas y no en la vista.** La cuenta del cargador (`semaforo_carga`) no lee el esquema `vistas` (eso es intencional: solo lectura para quien consulta). La prueba de carga sí comprueba que la vista muestre cada paso, usando la cuenta de administración.
4. **Sin migración.** Como en F3, el diseño nuevo tiene su propia versión de esquema (`sql-d405569d4d1daf46`) y la base se reconstruye desde los archivos.

## Qué se hizo con la base

1. Respaldo de la base F4: `D:\respaldos\semaforo\20261107T132416Z.dump` (14 MB), con su `.sha256`. El respaldo de F4 `20261106T231427Z.dump` sigue ahí.
2. La base `semaforo` de F4 se renombró a `semaforo_f4_anterior` (sin tocar sus datos) y se creó `semaforo` nueva en el mismo espacio de tablas, con los mismos permisos, como dueño `semaforo_admin`. No se usó la cuenta `postgres`.
3. Se aplicó el esquema nuevo.
4. `bd cargar --preliminar --sueltas`: **137 unidades cargadas, 0 rechazadas, 0 pendientes**; las 3 corridas de DEV00 siguen como no cargables (conflicto pendiente, igual que en F4). Huella de contenido nueva: `545063407b83f6d365647ecba9c14d32844be383de454d75877ae856fcb7d5a7`.
5. **`bd conciliar` (QA33):** 2 615 archivos, 130 corridas recalculadas, **0 diferencias**.
6. **`bd verificar --regenerar` (QA36):** la base regenerada desde los archivos da la misma huella. 268 archivos raíz revisados, 0 cambiaron. `docs/bd/huellas.json` regenerado (ADR03).
7. Se borró `semaforo_f4_anterior` (ya no sirve; hay dos respaldos verificados de ese estado). Las demás bases del servidor no se tocaron (`tickers_report_db` y `trading_predict` incluidas).

## Pruebas

- **Nuevas:** una que comprueba que la vista `vistas.cola_por_segundo` muestra exactamente un paso por cada valor de los arreglos, y otra que comprueba que una cola con un valor de menos se rechaza con SM006 (con datos reales de SUMO).
- **Actualizadas:** la conciliación (`_check_series`) cuenta por arreglos; la prueba de carga cuenta la tabla nueva.
- **Puerta de calidad** (`scripts/check.ps1`): ruff y formato limpios; pyright sin errores; esquema y diccionario al día; pruebas: ver la sección de cierre al final de este acta.

## Lo que sigue igual (no cambió con este arreglo)

- Tres accesos de la zona no tienen vehículos de la cohorte (`1185174556`, `1436359637#0`, `563085958`): su cola está en `cola_por_acceso`, pero no en `resultados_acceso`. Sigue para F7 (diseño).
- Las 3 corridas de DEV00 quedan como conflicto pendiente. El comando para marcar «riesgo aceptado» se propone para F6.
- Quien solo lee ve los nombres de los escenarios de prueba, pero ninguno de sus datos (parte del diseño de F1).

## Qué sigue

- **F5 (panel estático, Sonnet):** no se ejecuta sin tu orden. Ahora el panel lee `vistas.cola_por_segundo`, que no cambió.
- Pendiente de tu revisión: el acta de F4 (`docs/actas/2026-11-06-dev31-f4-carga-de-lo-existente.md`) y este cambio.
- La confirmación de `docs/bd/huellas.json` en git va en el commit de este cambio. El push sigue siendo a tu pedido.
