# Acta 2026-10-20: DEV00 · F3 (inventario de red y semáforos)

- **Tipo:** registro de fase del plan de DEV00 (HU04)
- **Fecha:** 2026-10-20
- **Autorización:** el Product Owner autorizó F3 («ejecuta F3») tras la revisión posterior de F2.
- **Código y pruebas:** commit `8e3b987`.
- **Siguiente fase:** F4 (auditoría de rutas, demanda y comportamiento), a la espera de la autorización expresa del Product Owner.

## Qué se implementó

| Módulo | Responsabilidad |
|---|---|
| `caso/inventory.py` | `read_network_inventory`: lee una red `.net.xml` o `.net.xml.gz` y devuelve su inventario |
| `caso/inventory_models.py` | `NetworkInventory`, `NetworkCounts`, `TlsInventory`, `TlsProgram`, `Phase` e `InventoryFinding` (pydantic, `schema_version` 1.0.0) |
| `caso/base_model.py` | `FrozenModel`: configuración común de los modelos de `caso`, extraída de `reception_models.py` |

La función recibe la ruta de la red. Localizarla a partir del `net-file` del `.sumocfg` y guardar el inventario en `datos/derivados/recepcion/<reception_id>/` es trabajo del servicio de F7.

## Decisiones tomadas en F3

1. **Conteos con totales e internos por separado.** SUMO crea aristas, carriles y conexiones internos dentro de cada cruce, y los totales los incluyen. El inventario da `edges_total` y `edges_internal` (igual para carriles y conexiones), para que nadie confunda 611 aristas del archivo con las aristas viales.
2. **Los hallazgos son observaciones, no veredictos.** Códigos: `PHASE_DURATION_BELOW_MIN`, `PHASE_DURATION_ABOVE_MAX`, `STATE_LENGTH_MISMATCH`, `MULTIPLE_PROGRAMS` y `TLS_WITHOUT_PROGRAM`. Qué hacer con ellos lo decide el Product Owner con el especialista de tránsito (QA24). Las fases se numeran desde 0, en el orden del archivo.
3. **Programa activo con varios programas: el último del archivo.** Pendiente de F0, medido con SUMO 1.27.1 sobre una copia del fixture con dos programas para el mismo semáforo. Con `demo` primero y `alt` después corre `alt`; con el orden invertido corre `demo`, así que no depende del orden alfabético. Lo fija `tests/integration/test_inventory_sumo.py`, que ejecuta SUMO y se salta si no está instalado. El inventario lo expone como `active_program_id`. No refleja cambios de programa durante la simulación (TraCI o archivos adicionales).
4. **`link_count` es el mayor `linkIndex` más uno**, no el número de conexiones: un enlace puede tener varias conexiones.
5. **La compresión se detecta por el contenido, no por el nombre**, y el tamaño descomprimido tiene un límite provisional de 64 MiB, pendiente del piloto. La red de Frutales ocupa 0,5 MB descomprimida. El límite protege contra bombas de compresión (QA10): la lectura nunca pasa de `límite + 1` bytes.
6. **Todo error es `CasoError` con `INPUT_SCHEMA`** y solo lleva el nombre del archivo, nunca su ruta: archivo ilegible, truncado o corrupto, XML con DTD o entidades, raíz que no es una red, valores no numéricos o no finitos y atributos obligatorios ausentes.

## Evidencia de la puerta de salida (red de Frutales, copia de F2)

Según ADR09, el detalle de la red (conteos, fases y hallazgos) queda en `datos/derivados/recepcion/f3-pruebas/inventario_R0.json`, ignorado por git, hasta que el Product Owner lo revise y autorice publicarlo. Lo verificable sin revelarlo:

| Comprobación | Resultado |
|---|---|
| Hash de la red | igual a la línea base; igual antes y después de leerla |
| Conteos | coinciden con un conteo independiente (solo biblioteca estándar) y con las cifras que se habían medido al leer la simulación |
| Enlaces del semáforo | el inventario da el mismo número que las conexiones con `tl` contadas aparte |
| Determinismo | dos lecturas producen el mismo JSON |
| Rutas absolutas en el JSON | ninguna |
| Tiempo de lectura | menos de 0,1 s |

## Verificación

- Pruebas: 209 pasan y 1 se salta de forma declarada (enlaces simbólicos sin privilegios). F3 añade 35, entre ellas la que ejecuta SUMO.
- Las pruebas se escribieron antes del código (fallaron por módulo inexistente).
- Trece mutaciones del código (programa activo, límites de `minDur` y `maxDur`, conteo de enlaces, aristas internas, límite de tamaño, DTD, valores no finitos, detección de compresión, entre otras) fueron detectadas. Dos sobrevivieron al principio y se cerraron con pruebas: `duration` igual a `maxDur` y el límite de tamaño exacto.
- `ruff`, formato y `pyright` estricto sin errores; el validador de contratos sigue en 43 comprobaciones.

## Limitaciones conocidas

- Solo se lee la red. Los programas semafóricos que se definan en archivos adicionales o por TraCI, y los detectores, no aparecen. El `.sumocfg` de Frutales no carga archivos adicionales.
- El inventario no describe la geometría ni los movimientos por carril: eso es de `caso/network_map.py` (DEV03).
- La cantidad de nodos que une un semáforo agrupado (DEC02) no figura en la red; su identificador sigue el formato que netconvert da a los nodos unidos, y el número real se confirma en netedit.
- Los enlaces con `linkIndex2` (cruces peatonales) no se tratan de forma especial.
