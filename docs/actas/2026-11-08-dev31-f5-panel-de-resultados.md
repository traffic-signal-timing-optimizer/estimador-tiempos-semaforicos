Escrito para: el Product Owner (revisión y aprobación de F5 de DEV31) y el equipo técnico.

# DEV31 F5: panel de resultados

- **Fecha:** 2026-11-08
- **Tarea:** DEV31 (HU15), fase F5 de la sección 13 de `docs/actas/2026-11-05-plan-base-de-datos.md`, después de F4c.
- **Orden del PO:** «ajusta el plan de F5 si es necesario. Ejecuta F5».
- **Modelo:** Opus 5.5. El plan pedía Sonnet; el PO eligió Opus para esta fase.
- **Commits:** código `d3927a1`, referencia `b970b4f`, esta acta en el commit siguiente. Sin push.
- **Estado: hecho y verificado, con dos pasos pendientes del PO:** aprobar las huellas para cambiar la base vigente (sección 5) y la revisión manual QA37 (sección 6). F5 no se cierra hasta entonces.

## 1. El plan se ajustó así

| Punto | Plan original | Ajuste y por qué |
|---|---|---|
| Fuente de datos | Vistas aprobadas | **Se mantiene (decisión delegada por el PO).** La foto JSON del prototipo no respeta el cegado por sí sola; leer archivos a mano duplicaría esa lógica. Pero las 10 vistas no alcanzaban para sustentar los datos de entrada: se agregaron **15 vistas**. Es un cambio de esquema, y por eso requiere candidata y aprobación |
| Páginas | Ocho | **Diez:** se agregan **Comparación con el plan actual** (lo que el PO y su asesor quieren ver) y **Evidencia** (ya prevista como vista transversal en el prototipo) |
| Series | Por decidir | **Todas las de SUMO** (130 corridas), separadas por etapa y protocolo. Las 3 de DEV00 aparecen como excluidas con su decisión |
| Ubicación del código | `documentacion/frontend/` (fuera de git) | **Versionado:** página en `src/semaforo/app/panel_web/`, avance y guía en `docs/panel/`. El prototipo del PO se tomó como base y no se tocó |
| Salida | `datos/reportes/panel/<fecha>/` | Se mantiene |

## 2. Qué quedó

**Comando:** `bd panel`. Publica una carpeta nueva de solo lectura que se abre con doble clic, sin servidor ni internet. Guía para mantenerlo: `docs/panel/LEEME.md`.

| Página | Qué responde |
|---|---|
| Inicio | Qué se investiga, lo que muestran los datos hasta ahora, avance por fase y estado de la evidencia |
| Caso | El cruce: tramos del semáforo, plan actual, movimientos y límites de lo modelado |
| Escenarios y protocolo | Los datos de entrada: demanda por acceso, movimiento y clase; tiempos; semillas; cómo se mide |
| Simulaciones | Las 130 corridas por serie; en cada una, la cola en el tiempo, sus accesos, sus movimientos y su procedencia |
| Comparación con el plan actual | Los tiempos de cada plan y cómo cambia la demora: con la misma semilla, entre finalistas y por acceso |
| Búsqueda | Los 21 planes probados, por qué se descartó cada uno y por qué no hubo referencia; Webster |
| Entrenamiento y Consultas | Vacías hoy, y lo dicen. Se llenan solas cuando DEV16 en adelante carguen datos |
| Evaluación final | **Reservada:** ninguna cifra hasta el hito de apertura. Solo muestra los hitos, que son públicos |
| Evidencia | Huellas y archivo de cada corrida, última comprobación, datos que faltan y exclusiones |

**Reglas para no decir más de lo que los datos permiten** (`app/panel_resumen.py`): solo se resta con la misma semilla; un par con incidentes se muestra pero no cuenta como válido; las series no mezclan protocolos; una réplica no cuenta dos veces; no hay inferencia estadística, y la página lo dice.

## 3. Lo que muestran los datos (para el asesor)

Con demanda sintética (5 340 veh/h) y un solo escenario:

- **El plan actual se comporta de dos maneras.** En 13 semillas: unos 104 s/veh cuando no hay atascos, y unos 210 s/veh en las 7 semillas con teletransportes o choques. El promedio solo (161 s/veh) no lo describe.
- **Comparación emparejada (solo 3 semillas de búsqueda):** el mejor plan elegible, `eef59d99` (ciclo 176 s), da −26,2 s/veh frente al plan actual, con solo 2 pares válidos. Por acceso es desigual: en la semilla 1002 baja 143 s/veh en Javier Prado este→oeste, pero sube 68 s/veh en oeste→este.
- **La búsqueda no eligió referencia:** ningún finalista fue elegible en todas sus semillas.
- **Webster no aplica:** da 106,6 s y el caso admite de 120 a 240 s.

**Esto no demuestra una mejora.** Es simulación con demanda supuesta y pocas semillas.

**Límite más importante:** el plan actual nunca se simuló con las semillas de los finalistas (2001 a 2013). El panel los muestra lado a lado y avisa que no se pueden restar. Para una comparación de verdad habría que correr esas 13 simulaciones. Queda a decisión del PO.

## 4. Hallazgos durante F5

1. **Fuga de cegado corregida:** `control.conflictos` mostraba al lector la ruta de un archivo de una prueba cerrada, el mismo tipo de fuga que C2 cerró en otras tablas. La auditoría no la vio: apareció al ampliar el barrido. La tabla ahora está cegada (`archivo_incidencia`).
2. **Rol del panel en otra laptop:** dependía de un guion temporal. Ahora lo crea `bd iniciar`, y el manual está al día. **No se ha probado una instalación desde cero en otra laptop.**
3. **La huella de reglas no vigilaba los atributos del rol del panel** (sus permisos sobre tablas y vistas sí). Ahora sí (`reglas-2`). Una referencia con otro algoritmo de reglas da «no concluyente». La referencia de la base vigente se volvió a medir con el algoritmo nuevo: mismo contenido (`9980fa13…`), distinta huella de reglas (`b970b4f`).
4. **Tabla errada en un acta anterior:** `2026-11-02-plan-dev14.md` dice que `282567283#5` es el acceso «desde el sur». La geometría de la red muestra que entra de **norte a sur**. El supuesto de demanda está bien. No se editó esa acta; el nombre correcto está en `docs/panel/avance.toml`.
5. **Mirar el panel en el navegador detectó errores que las pruebas no veían:** una vista repetía tramos y alargaba las barras, y un plan no elegible con un solo par encabezaba la lista. Están corregidos.

## 5. Base candidata: requiere la aprobación del PO

El esquema cambió, así que la base vigente **no se tocó**. La candidata `semaforo_candidata_20261108182658` pasó P0 a P5 y P7. P6 pasó en bases desechables, en la puerta completa con este mismo esquema.

| Referencia | Valor a aprobar |
|---|---|
| Versión del esquema | `sql-afadf606c1a2065b` |
| Huella de contenido | `9980fa130cc294af764f764c31320153d58edac0b073cefd5568b4982a33a9f2` (**la misma de la base vigente:** ninguna fila cambió) |
| Huella de reglas | `008f66d8965fa3fc65dff9090e3f9a4a0fac4b548be3aff2693720cdffb3fbc6` |

Respaldo de la candidata, restaurado con la misma huella: `D:\respaldos\semaforo\sql-afadf606c1a2065b\20261108T183350Z.dump`.

**Al aprobar se ejecuta:** `bd reconstruir cambiar` con esos tres valores (P8 y P9). Después, `bd evidencia`, `bd panel` y el commit de `docs/bd/huellas.json`. La base vigente queda como `semaforo_anterior_20261108_f5`, sin borrarse.

## 6. Cómo se verificó

- **Puerta completa:** 5507 pruebas pasaron, 1 omitida (la de siempre), 43 de 43 contratos, 57 tablas, 880 columnas y 117 relaciones. La corrida fue previa al commit `d3927a1`, con el mismo código.
- **Ensayo de daño** `scripts/mutaciones/dev31_f5.py`: **29 de 29** detectados. Incluye quitar el filtro de cegado de las vistas nuevas, una por una. Corrió antes de los últimos cambios de roles, que tienen sus propias pruebas.
- **Cegado:** con una prueba cerrada en la base, ninguna marca llega a las vistas ni al archivo publicado; al abrirla, aparecen. Barrido sobre la candidata: correcto; el panel abre 25 de 84 relaciones. La base real no tiene una prueba cerrada, así que ahí solo se comprueban permisos.
- **Texto hostil:** las diez páginas se ejecutan con Node con una etiqueta inyectada en cada campo; ninguna la convierte en HTML. Esas pruebas se saltan sin Node.
- **Navegador:** las diez páginas se abrieron con Edge sin ventana (a 1400 px) y la Comparación también a 620 px, y se revisaron las imágenes. La política de contenido permite su propio código y bloquea el resto. El detalle de una corrida se probó simulando un clic.

**No se probó:** navegación real con teclado, los selectores con clics reales, otro navegador ni un celular real.

**QA37 pendiente:** la revisión manual la hace el PO. El panel para revisar es `datos/reportes/panel/20261108T183439Z/index.html`, generado desde la candidata. Avisa que su última evidencia es de otra versión de la base, y es correcto: la evidencia se repite después del cambio.

## 7. Pendientes

- Aprobación de las tres huellas (sección 5) y QA37 (sección 6).
- D12: después de verificar F5, decidir si se borran `semaforo_anterior_20261108_c2` y, tras el cambio, `semaforo_anterior_20261108_f5`.
- Decidir si se simula el plan actual con las semillas de los finalistas (sección 3).
- Causa de la prueba inestable de reversión de P9 (el PO la dejó para el final).
- Push, a pedido.
