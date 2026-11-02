# Acta 2026-11-01: DEV09 · F2 (piezas de HTML y vista del caso)

- **Tipo:** fase F2 de DEV09 (HU01). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D2, D3, D6, D9, D10 y D11 de F0.
- **Datos:** sintéticos, y el caso-001 real solo para leerlo.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/app/html_page.py` | Piezas para armar HTML sin inyección: `escape`, `element`, `table`, `status`, `page`… |
| `src/semaforo/app/report_case_view.py` | `render_case`: la página del caso |
| `src/semaforo/app/reports.py` | `publish_case_report` y `read_report`: publicación con manifiesto y lectura verificada |
| `tests/html_checks.py` | Comprobaciones comunes de un informe, leído como lo leería un navegador (también para F3 y F4) |
| `tests/unit/test_html_page.py`, `test_report_case_view.py`, `test_reports.py` | 94, 52 y 30 pruebas |

## Cómo está hecho

**Piezas de HTML.** Todo texto común (`str`) se escapa. Solo un fragmento `Html` entra tal cual, y solo `html_page.py` crea `Html` (una prueba lo comprueba en todo `src/`). Solo se aceptan unas pocas etiquetas y atributos, y cada valor debe cumplir su formato: no hay `script`, atributos de eventos, imágenes ni recursos externos, y los únicos enlaces apuntan a anclas de la misma página. Los caracteres de control y los de dirección de texto (que pueden esconder o invertir lo que se lee) se reemplazan. La página lleva una política de contenido que no permite scripts ni recursos de fuera. Cada estado lleva un símbolo y un texto además del color (✔ Cumple, ⚠ Aviso, ✖ No cumple, – No aplica).

**Vista del caso.** Muestra el origen en palabras («Sintético: datos de prueba, no son observaciones de Lima» o «Real: datos de campo»), el estado de la validación, la representación, la red, la huella; las 19 reglas con su resultado y sus problemas; los límites del plan (ciclo, tiempo fijo y verde de cada grupo); los movimientos con su flujo permitido en veh/h; las clases de vehículos y la frontera; la evidencia de las restricciones (o el aviso de que no hay); y un glosario con las palabras del proyecto. Un caso inválido muestra una alerta con las reglas que no cumple y no enseña los movimientos, solo el motivo.

**Publicación.** `datos/reportes/informes/caso/<id-del-caso>/<fecha>_<huella>/` con `index.html` y `manifiesto.json` (tipo, fecha en UTC, huella del caso y huella de la página). Nunca se sobrescribe, y si el identificador del caso no sirve como nombre de carpeta, se usa `sin-identificar`.

## Verificación

- **Pruebas:** 176 nuevas. Suite completa: **2165 pasan, 1 se salta**. Formato, lint, tipos y contratos sin observaciones.
- **Mutaciones:** 110 cambios a propósito, de a uno. **98 se detectaron en la primera pasada y 12 no.** Los 12 eran huecos reales: un enlace sin almohadilla, valores libres para `charset` y `name`, el símbolo de «No cumple», «Aviso» y «Con fallos», los índices de enlaces, el conteo de tramos variables, la huella sin formato de código, y tres detalles de la publicación (la hora en UTC dos veces y las tildes en el manifiesto). Se cerraron con pruebas y los 110 quedan detectados.
- **Caso real (solo lectura):** el caso-001 se muestra completo: origen «Real», representación «Sin verificar», red verificada, 19 reglas, ciclo de 120 a 240 s, tiempo fijo de 24 s, 5 grupos de verde y 23 movimientos.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | **Los identificadores del caso admiten cualquier carácter visible**, incluidos `<`, `>` y `"` (solo se rechazan los de control y los invisibles). Un ID como `<script>…` es un caso válido | El escape no es una precaución de más: es la protección real. Hay pruebas con texto hostil en el ID, la frontera, las clases y el acceso. El nombre de la carpeta del informe se limita a letras, números, punto, guion y guion bajo |
| 2 | Las reglas de la validación (de DEV02) usan palabras como «tick» y «slot» | El informe agrega un glosario en palabras simples, sin cambiar las reglas |
| 3 | Mi ayuda de pruebas (`html_checks.py`) tenía una comprobación que fallaba con texto inocente: confundía el texto «javascript:» dentro de una celda con un enlace peligroso | Ahora revisa solo los valores de los atributos |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría.
