# Acta 2026-11-02: DEV19 · F1 (salidas de medición, ADR11)

- **Tipo:** fase F1 de DEV19 (HU12; HU13). Ejecutada seguida de F0, por pedido del Product Owner.
- **Decisiones que aplica:** D1 a D4 de `2026-11-02-dev19-f0-decisiones.md` y el ADR11.
- **Modelo:** Opus.
- **Datos:** sintéticos (red de demostración de dos movimientos).

## Qué se construyó

| Archivo | Cambio |
|---|---|
| `simulacion/prepare.py` | La carpeta de entradas lleva `zona_fcd.txt`: las calles de los carriles de entrada de los movimientos, sin repetir y en el orden del caso. El manifiesto pasa a 1.1.0, con `measurement_edges` y dos salidas requeridas más. Un carril que no está en la red se rechaza |
| `simulacion/run_inputs.py` | La comprobación previa exige que la zona del archivo sea la del manifiesto, y que no haya archivo sin zona declarada ni al revés. La corrida pasa la zona al corredor |
| `simulacion/runner.py` | Opción `zone_file`: pide a SUMO los viajes no iniciados y la FCD de la zona (`id`, `lane`, `speed`). La coherencia cuenta aparte los que no entraron: con zona, uno por cada vehículo que esperaba; sin zona, ninguno. Sin `fcd.xml`, la corrida es `failed` |
| `simulacion/tripinfo.py` | Cada viaje trae también `timeLoss`, `departDelay`, `waitingTime` y `waitingCount`. Si falta un atributo queda vacío: no se inventa un cero. `started` indica si el vehículo entró |
| `simulacion/reconcile.py` | Un viaje con `depart="-1"` es `not_inserted`, no `unfinished` |

Las carpetas de entradas 1.0.0 se siguen ejecutando como antes, sin FCD, y el corredor de DEV00 tampoco cambia sin zona: su comando es idéntico al anterior, comprobado argumento por argumento.

## Verificación

| Qué | Resultado |
|---|---|
| Pruebas nuevas | **59** (56 sin SUMO y 3 con SUMO real). Se ajustaron 4 pruebas anteriores que listaban los archivos y las salidas (ahora hay `zona_fcd.txt` y `fcd.xml`) |
| Suite completa | **4575 pasan, 1 se salta** (la que solo corre fuera de Windows). Formato, lint, tipos estrictos, 43 comprobaciones de contratos y archivos ocultos, sin observaciones |
| Con SUMO real | Demo normal: FCD con un paso por segundo hasta el fin (1860 pasos), solo carriles de la zona más los internos del cruce. Demo saturada (1200 veh/h, sin drenaje): 96 vehículos sin entrar, cada uno con su registro y su espera; la conciliación los deja como `not_inserted` y coincide con las cifras de SUMO. Carpeta 1.0.0: corre igual, sin FCD |
| Réplica (DEV08) | Dos corridas iguales siguen siendo «equivalentes»; ahora la comparación incluye `fcd.xml` |
| Mutaciones | **27 cambios a propósito, los 27 detectados a la primera** |

## Hallazgos

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | El acceso declarado en el caso (`approach_id`) no siempre es una calle de la red: en el ejemplo se llama «N» y la calle es `demo_N` | La zona se arma con la calle de los carriles, tomada de la red. El nombre del acceso se usa solo para agrupar los resultados |
| 2 | La comparación de réplicas ahora también compara la FCD | Es correcto: es una salida científica. Se actualizó la prueba |
| 3 | Una edición con `\n` dentro de una cadena se convirtió en un salto de línea real (la herramienta lo hace, como dice la nota guardada) | Se corrigió con un script que arma la barra invertida con `chr(92)` |

## Límites

- `fcd.xml` solo se comprueba que exista. Su lectura completa, con su tope y su validación, es de F3.
- La zona es la calle de entrada declarada en el caso (DEC04 pendiente).
