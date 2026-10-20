# Fixture SUMO mínimo ejecutable

Red sintética para probar la recepción y el runner de SUMO sin depender de la simulación de Frutales, que sigue cambiando. **No representa Frutales** ni ninguna geometría real. Generada con SUMO 1.27.1 (DEV00, fase F1).

## Contenido

```
demo/
  demo.nod.xml  demo.edg.xml  demo.con.xml  demo.tll.xml   entradas de netconvert
  demo.net.xml                                              red generada
  demo.rou.xml  demo.sumocfg                                demanda y configuración
invalid/
  truncated_net/    red cortada a la mitad
  missing_edge/     ruta con una arista que no existe
  absolute_output/  salida con ruta absoluta (no ejecutar)
```

Las salidas de una corrida (`tripinfo.xml`, `statistics.xml`) no se versionan. `tests/unit/test_sumo_fixture.py` falla si aparecen en `demo/`.

## Coherencia con los fixtures contractuales

| Fixture contractual | Dónde se refleja |
|---|---|
| `case.json`: `DEMO_TLS`, movimientos N_S y E_W, `link_indices` 0 y 1, 6 slots, `tick_s` 1 | `demo.tll.xml` (estados), `demo.con.xml` (`linkIndex`), `demo.sumocfg` (paso de 1 s) |
| `response.json`: plan de 30, 3, 1, 22, 3 y 1 s (ciclo de 60 s) | `demo.tll.xml` |
| `aforos.csv` y `expected_normalization.json`: 900 s, N_S 90 car y 10 bus, E_W 50 car (400 y 200 veh/h) | `demo.rou.xml` (flujos con `number`) |
| `run_manifest.json`: semilla 301 | `demo.sumocfg` |

## Regenerar la red

Desde `tests/fixtures/sumo/demo`, en PowerShell:

```powershell
& "$env:SUMO_HOME\bin\netconvert.exe" --node-files demo.nod.xml --edge-files demo.edg.xml `
    --connection-files demo.con.xml --tllogic-files demo.tll.xml --output-file demo.net.xml
```

`netconvert` escribe un comentario inicial con la fecha y las opciones, así que dos regeneraciones nunca son idénticas byte a byte. Se comparan sin ese comentario:

```python
import pathlib
import re


def normalize(path: str) -> str:
    text = pathlib.Path(path).read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", text, count=1, flags=re.S).replace("\r\n", "\n").strip()
```

Los índices `linkIndex` (N_S = 0, E_W = 1) los fija `demo.con.xml`; no dependen del orden que elija `netconvert`.

## Ejecutar

Siempre sobre una **copia**: SUMO escribe las salidas junto al `.sumocfg`.

```powershell
Copy-Item -Recurse tests\fixtures\sumo\demo $env:TEMP\demo-run
& "$env:SUMO_HOME\bin\sumo.exe" -c "$env:TEMP\demo-run\demo.sumocfg"
```

Resultado esperado con SUMO 1.27.1:

- Código de salida 0.
- 150 viajes terminados: `N_S_car` 90, `N_S_bus` 10 y `E_W_car` 50.
- `vehicles`: 150 cargados, 150 insertados, 0 en ejecución, 0 esperando. Sin teleports ni colisiones.
- La simulación termina sola en el segundo 916.
- Dos corridas con la misma semilla producen el mismo `tripinfo.xml` (sin el comentario inicial).

## Variantes defectuosas

| Carpeta | Defecto | Comportamiento con SUMO 1.27.1 |
|---|---|---|
| `invalid/truncated_net` | La red está cortada a la mitad, con el XML sin cerrar. | Código 1, `Error: equal sign expected`, sin archivos de salida. |
| `invalid/missing_edge` | La ruta `N_S` usa `demo_X`, que no existe en la red. | Código 1, `The edge 'demo_X' within the route 'N_S' is not known`. Deja `tripinfo.xml` y `statistics.xml` vacíos pero bien formados. |
| `invalid/absolute_output` | `tripinfo-output` apunta a `Q:\salida-absoluta\tripinfo.xml`. | **No ejecutar con SUMO.** Se detecta de forma estática (hallazgo de la recepción en F2). La ruta apunta a un directorio que no existe. |

## Comportamiento de SUMO observado (condiciona el runner de F6)

1. **Las rutas relativas del `.sumocfg` se resuelven respecto a su carpeta**, no al directorio de trabajo. Ejecutar sobre la carpeta original escribiría las salidas dentro de ella. El runner debe ejecutar siempre sobre una copia aislada.
2. **Una corrida fallida puede dejar salidas existentes, vacías y con XML bien formado** (caso `missing_edge`). Que el archivo exista y sea XML válido no prueba el éxito. El éxito exige código de salida 0 y contenido coherente: `vehicles` en `statistics.xml` y viajes consistentes con los vehículos insertados.
3. **La ejecución es determinista**: misma semilla, mismo `tripinfo.xml` una vez descartado el comentario inicial, que incluye la configuración.

## Verificación automática

`tests/unit/test_sumo_fixture.py` comprueba la coherencia con los fixtures contractuales y que cada variante está rota como se documenta. No ejecuta SUMO. La ejecución real de este fixture se cubrirá con las pruebas del runner (F6).
