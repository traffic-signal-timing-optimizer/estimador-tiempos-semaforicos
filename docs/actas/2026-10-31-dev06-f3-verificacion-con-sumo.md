# Acta 2026-10-31: DEV06 · F3 (verificación con SUMO y conciliación de la cohorte)

- **Tipo:** fase F3 de DEV06 (HU04; P0, tamaño M). Dependencias: F0, F1 y F2 de DEV06; corredor de SUMO de DEV00.
- **Autorización:** el Product Owner confirmó los dos cambios del perfil sintético (sin buses en Los Frutales y sin tráfico en las vías de servicio M10, M18 y M19) y pidió ejecutar F3 («ejecuta F3»). La inspección de cierre de esta fase está más abajo.
- **Alcance de la fase:** verificar con SUMO real la carpeta de entradas de F2 (QA07), conciliar la cohorte con los viajes de SUMO por identificador (QA25, decisión D20), comprobar la seguridad de nombres, rutas y archivos (QA10) y que los originales quedan intactos. Datos sintéticos. No toca código del modelo. No calcula métricas (demora, colas): eso es de DEV19.

## Qué se construyó

| Archivo | Qué contiene |
|---|---|
| `src/semaforo/simulacion/reconcile.py` | `reconcile_run` (concilia la cohorte con una corrida publicada), `reconcile` (con un `tripinfo.xml` suelto) y `reconciliation_csv` (la tabla de cohorte) |
| `src/semaforo/caso/json_input.py` | Se separa `read_text_file` (lectura segura de texto: sin enlaces, con límite de tamaño, UTF-8); `read_json` la reutiliza sin cambiar sus mensajes |
| `tests/unit/test_reconcile.py` | 51 pruebas de estados, planilla alterada, manifiesto y viajes inválidos |
| `tests/integration/test_prepared_run_sumo.py` | 18 pruebas con SUMO real (QA07, QA25 y nombres con caracteres especiales) |
| `tests/security/test_dev06_inputs.py` | 33 pruebas de seguridad de las entradas (QA10) |
| `tests/prepared_inputs.py` | El ejemplo de dos movimientos, movido desde `test_prepare.py` para que lo usen las pruebas de F2 y F3 |

### Cómo concilia

Cada vehículo pedido queda en uno de tres estados:

| Estado | Cuándo |
|---|---|
| `finished` (terminado) | SUMO escribió su viaje con `arrival` mayor o igual que 0 |
| `unfinished` (sin terminar) | SUMO escribió su viaje, pero `arrival` es negativo: seguía en la red al terminar |
| `not_inserted` (no entró) | SUMO no escribió viaje: nunca entró a la red |

- Los vehículos de calentamiento quedan registrados pero no cuentan en la cohorte.
- **El número pedido se conserva** (QA25): terminados + sin terminar + no entraron = pedidos, en total y por movimiento y clase. Ningún vehículo se excluye sin registro.
- `reconcile_run` rechaza, antes de conciliar: una corrida que no terminó bien (`failed`), una corrida alterada y una corrida hecha con otras entradas (compara la huella real de cada archivo de la carpeta con la que registró la corrida; un archivo de más, de menos o cambiado se rechaza).
- Antes de usar la planilla `cohorte.csv`, se comprueba contra su huella y contra los totales del manifiesto (vehículos, cohorte, y calentamiento y medición por movimiento y clase).
- Un viaje de un vehículo que no se pidió, un viaje repetido, un XML con declaraciones peligrosas o truncado, y un archivo demasiado grande se rechazan con un error claro.
- La tabla `reconciliation_csv` (evidencia de QA25) usa el formato de las planillas del equipo (`;`, BOM, fin de línea de Windows, identificadores como texto). Se abrió con Excel: 1781 filas por 8 columnas, identificadores como texto y números como números.

## Verificación con SUMO

**QA07 (ejecutar y comprobar archivos y versiones).** Con el ejemplo de dos movimientos y con el caso real:

- La corrida termina con éxito (código de salida 0), con SUMO 1.27.1 registrado, y publica `tripinfo`, `statistics`, `summary`, el registro y las salidas estándar. Su manifiesto coincide con lo publicado.
- La simulación llega hasta el fin que declara el manifiesto de las entradas (1860 s en el ejemplo; 2100 s en el caso real), tomado de ahí al ejecutar.
- Cada archivo de entrada queda registrado con su huella, y esa huella es la del manifiesto de las entradas.
- **Los originales quedan intactos y de solo lectura:** mismas huellas y mismos archivos antes y después de la corrida.
- Dos corridas con las mismas entradas dan la misma conciliación.

**QA25 (conciliar los IDs).**

| Corrida del caso real | Fin | Pedidos | Terminados | Sin terminar | No entraron |
|---|---|---|---|---|---|
| Completa | 2100 s | 1338 | 1338 | 0 | 0 |
| Corta | 700 s | 1338 | 368 | 205 | 765 |

- En la corrida corta aparecen los tres estados y la suma sigue siendo 1338.
- Contando también los vehículos de calentamiento, la conciliación coincide con lo que reporta SUMO: 810 terminados, 205 sin terminar y 765 que no entraron (1780 menos 1015 insertados).
- La corrida completa no tuvo teletransportes ni choques. SUMO dio 4 avisos, heredados del programa original de la red, igual que en F2.
- Con el ejemplo de dos movimientos, una corrida corta de 250 s también deja los tres estados, y no se pierde ningún vehículo.

**QA10 (seguridad de nombres, rutas y archivos).** Se intentó colar texto peligroso por cada puerta de entrada; en todos los casos se rechaza antes de escribir, o lo escrito no cambia de estructura:

- Texto XML en las calles de una ruta (`"/><evil x="`), en la clase, forma, color y atributos de un tipo de vehículo, y valores infinitos o no numéricos.
- Opciones de SUMO que leen o escriben archivos (`tripinfo-output`, `net-file`, `output-prefix`, `save-configuration`, `log`, `end`, `seed` y otras 4): solo se admiten las dos de la lista.
- Nombre de escenario que salga de la carpeta (`../fuera`, `..`, `a/b`, `a\b`, `C:\Windows`, `/etc`, nombres ocultos, con espacios o con `;` y `&`): se rechaza y no se escribe nada en ningún lugar.
- Red con declaración de entidades o con la huella cambiada.
- Calle de ruta como `../../etc/passwd`.
- Identificadores de la planilla de la cohorte siempre como texto para la hoja de cálculo.
- **Nombres con caracteres de shell** (`&`, `(`, `)`, `;`, `^`, `'`, `$`, `%`, y la orden `mkdir pwned`) en la carpeta de entradas y en la de ejecuciones: la corrida se hace como con cualquier otro nombre y no se ejecuta ninguna orden (no aparece la carpeta `pwned`).
- XML de SUMO con DTD o entidades anidadas, truncado, con otra raíz, repetido o demasiado grande, y `tripinfo` o planilla que sean enlaces.

## Inspección de lo desarrollado

Se releyó todo contra las decisiones de F0 (D2, D13, D20) y contra HU04, se probó con el caso real y se revisó cada mutación que sobrevivió. Hallazgos y correcciones:

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | La función de conciliación aceptaba cualquier `tripinfo.xml`: se podía cruzar la cohorte con los viajes de otra corrida o de una corrida fallida | Nueva `reconcile_run`, que parte de la corrida publicada y rechaza las fallidas, las alteradas y las hechas con otras entradas |
| 2 | La primera versión de `reconcile_run` comparaba lo que dice el manifiesto con lo que registró la corrida, pero no miraba los archivos reales de la carpeta: un archivo cambiado después de la corrida pasaba. La detectó una prueba de alteración | Se compara la huella real de cada archivo de la carpeta con la que registró la corrida. Pruebas de archivo cambiado (manifiesto, configuración y planilla), sobrante y faltante |
| 3 | La regla de nombres seguros rechazaba los identificadores de vehículo, que llevan puntos (`N_S.cal.car.1`) | Regla propia para vehículos; movimiento y clase siguen sin puntos |
| 4 | Una celda de identificador con la comilla final faltante pasaba la revisión de formato y se leía con un carácter menos | Prueba nueva; la mutación ya se detecta |
| 5 | El conteo por estado de cada movimiento y clase no estaba verificado vehículo por vehículo, ni su orden | Prueba nueva que lo recalcula por separado y exige el orden |
| 6 | Código sobrante: la comprobación de enlace del `tripinfo` quedó dos veces al reordenar; un viaje repetido se envolvía dos veces en errores | Una sola comprobación; la lectura de viajes quedó en una función propia |
| 7 | El ejemplo de las pruebas estaba dentro de `test_prepare.py` y no se podía usar desde las pruebas con SUMO | Movido a `tests/prepared_inputs.py`; las pruebas de F2 siguen igual |

## Mutaciones

Se cambió a propósito el código (condiciones, límites, claves, formatos) para comprobar que las pruebas fallan.

- **Primera pasada** (49 cambios sobre la conciliación y la lectura segura): sobrevivieron 10.
- **Después de agregar pruebas** (4 se omiten porque el texto ya no existe o la misma comprobación aparece dos veces): de 45 aplicadas, 40 detectadas y 5 sobreviven, todas justificadas.
- **Más de diez cambios sobre `reconcile_run` y la comparación de archivos**, hechos aparte y repetidos tras las correcciones del hallazgo 2: todos detectados.

| Sobrevive | Por qué se acepta |
|---|---|
| Largo mínimo de la celda `="…"` | Equivalente: una celda más corta ya falla por el formato |
| No deshacer las comillas dobles de un identificador | Equivalente: un identificador con comillas se rechaza por sus caracteres de todos modos |
| Leer `en_cohorte` como «distinto de no» en vez de «igual a sí» | Equivalente: cualquier otro valor ya se rechazó antes |
| Comprobación de enlace en el lector de texto y en el `tripinfo` | No se puede probar en este equipo: no permite crear enlaces simbólicos sin privilegios. Las pruebas existen y se saltan aquí; ocurre igual con los de F2 |
| Leer el archivo completo en vez de solo hasta el límite | Equivalente en el resultado: el archivo grande igual se rechaza después; solo cambia cuánta memoria se gasta. Igual que en F2 |

## Limitaciones y decisiones

1. **La tabla de cohorte no se publica sola.** D20 pedía una función mínima. `reconciliation_csv` produce los bytes de la tabla y queda a cargo de quien llame guardarla (DEV07 al ejecutar, DEV19 al medir). No se guarda dentro de la carpeta de la corrida, que es de solo lectura y la crea el corredor.
2. **Un vehículo que SUMO cargó pero no insertó** no tiene viaje, así que queda como «no entró». El corredor lo cuenta aparte (`vehicles_waiting`) y la conciliación coincide con él.
3. **Sigue pendiente para DEV07:** el corredor de DEV00 usa hoy su propio fin de simulación (7200 s por defecto). La verificación lo reemplaza con el del manifiesto, y DEV07 debe hacer lo mismo.

## Qué queda abierto

- **Para el Product Owner:** lo de F2 sigue igual: los límites del área de estudio (DEC04, de los que dependen las rutas del caso real), los tipos de vehículo provisionales y los umbrales de DEC05. Los dos cambios del perfil sintético quedaron confirmados.
- **Del plan:** F4, cierre de DEV06 con la tabla de cumplimiento de HU04.

## Estado del repositorio

- Archivos nuevos: `reconcile.py`, `tests/prepared_inputs.py` y las tres pruebas de la tabla de arriba; cambian `json_input.py` (se separa `read_text_file`) y `test_prepare.py` (el ejemplo pasa a `prepared_inputs.py`). Autor `crisroco`, sin línea de coautoría.
- Suite completa: 1434 pruebas pasan y 7 se saltan (los enlaces simbólicos, que este equipo no permite). Formato, lint y tipos sin observaciones. Antes eran 1334 y 5: 102 pruebas nuevas.
- `origin/main` sigue en `9fb7944`. Siguen sin subir los commits de DEV04, DEV05 y DEV06 F0, F1 y F2, más el de esta fase. No se ha hecho push: se sube cuando lo pida el Product Owner.
