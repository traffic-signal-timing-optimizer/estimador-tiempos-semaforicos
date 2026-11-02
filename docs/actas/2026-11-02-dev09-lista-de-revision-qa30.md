# DEV09: lista de revisión manual de las vistas (QA30)

QA30 pide que una persona abra los informes y revise que los estados sean claros, que el texto se vea como texto y que las tablas se lean. Esta lista es para que el Product Owner la haga con el navegador (unos 15 minutos). Lo automático ya está probado; esto es lo que solo se ve a ojo.

**Dónde están los informes de muestra:** carpeta `datos\revisiones\dev09\reportes\informes\` del proyecto (no se sube a GitHub). En cada carpeta, abra `index.html` con doble clic.

| Informe | Carpeta (dentro de `informes\`) |
|---|---|
| Caso real de Frutales | `caso\caso-001\20261102T051359Z_e1f97153` |
| Caso sintético válido | `caso\DEMO_VALIDO\20261102T051400Z_6388329c` |
| Caso con avisos | `caso\DEMO_AVISOS\20261102T051400Z_53e8e0e4` |
| Caso inválido | `caso\DEMO_INVALIDO\20261102T051401Z_9e74d88c` |
| Caso con texto hostil | `caso\DEMO_HOSTIL\20261102T051401Z_2c48a047` |
| Datos con una exclusión | `datos\DEMO_DATOS_EXCLUSION\20261102T051402Z_4401e690` |
| Datos completos | `datos\DEMO_DATOS_COMPLETOS\20261102T051402Z_b4917746` |
| Datos con filas que faltan | `datos\DEMO_DATOS_FALTANTES\20261102T051403Z_d9faaef0` |
| Datos sin pareja | `datos\DEMO_DATOS_SIN_PAREJA\20261102T051404Z_96cdd2b7` |

## Qué revisar

Marque cada punto con «Sí» o escriba qué no se entiende.

| # | Qué abrir | Qué debe ver | Resultado |
|---|---|---|---|
| 1 | Caso real de Frutales | Arriba, «Origen: Real: datos de campo» y «Representación: Sin verificar». El estado «Válido» con una marca ✔, la red «Verificada», 23 movimientos y un ciclo de 120 a 240 s | |
| 2 | Caso sintético válido | «Origen: Sintético: datos de prueba, no son observaciones de Lima» | |
| 3 | Caso con avisos | «Válido con avisos» con una marca ⚠ y, en la tabla de reglas, la regla CASE-C07 con su motivo | |
| 4 | Caso inválido | Un recuadro de alerta arriba que dice qué reglas no cumple; el estado «Inválido» con una marca ✖; **no** aparece la tabla de movimientos, solo una nota que explica por qué | |
| 5 | Caso con texto hostil | En «Evidencia de las restricciones» se ven, **como texto**, líneas como `<script>alert(...)</script>`. No aparece ninguna ventana emergente, y el texto `<h1>título falso</h1>` se ve como texto dentro de la lista, no como un título grande | |
| 6 | Cualquier informe del caso | Cada estado se entiende **sin mirar el color**: tiene un símbolo y una palabra (Cumple, Aviso, No cumple, No aplica) | |
| 7 | Cualquier informe del caso | Los números llevan su unidad (s, veh/h) y el glosario del final explica «tick», «slot», «ciclo», «grupo de verde» y «enlace» con palabras que usted entiende | |
| 8 | Datos con una exclusión | «Excluidos: 1», y una tabla «Conteos excluidos» con el error 0.1 y su causa. Esa fila aparece con ✖ «excluido» en la comparación | |
| 9 | Datos con una exclusión | En las filas de buses, el conteo de control es un cero verdadero y se escribe «0»; el error relativo dice «no se calcula (control cero)»; no hay ningún «sin dato» en esa tabla | |
| 10 | Datos con filas que faltan | En la comparación, la fila dice «sin dato» (no «0») y está la tabla «Combinaciones que faltan» | |
| 11 | Datos sin pareja | Dos filas con ⚠ «sin pareja» y «sin dato» en los números | |
| 12 | Datos completos | «Cobertura 100 %», «No hay huecos» | |
| 13 | Cualquier informe de datos | «Corregidos: 0» con la explicación de que en esta etapa no se corrige ningún dato | |
| 14 | Cualquiera | Con el navegador al 200 % de zoom o con la ventana angosta, las tablas se pueden desplazar a los lados y nada queda cortado | |
| 15 | Cualquiera | Si su Windows está en modo oscuro, el informe también se lee bien | |
| 16 | Cualquiera | Con el internet apagado, el informe se ve igual (no carga nada de fuera) | |

## Qué hacer con el resultado

- Si todos los puntos están en «Sí», QA30 queda **cumplido para las dos vistas de DEV09** (Caso y Datos). Las otras tres vistas (construcción, consulta y resultados) son de DEV21, así que QA30 completo se cierra allí.
- Si algo no se entiende o se ve mal, escriba el número del punto y qué vio: se corrige en una tarea aparte.
