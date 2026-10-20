# Acta 2026-10-19: DEV00 · F0 (decisiones y congelación de R0)

- **Tipo:** registro de fase del plan de DEV00 (HU04, HU14)
- **Fecha:** 2026-10-19, 19:28 (UTC−5)
- **Autorización:** el Product Owner dio el OK a F0 sin objeciones al plan; por la regla anunciada en el plan, se aplican las recomendaciones D1–D6.
- **Estado posterior:** F1 (fixture SUMO mínimo ejecutable) completada en el commit `5242cd3`. ADR09 aceptada el 2026-10-19 con las recomendaciones del Product Owner. F2 completada: ver `docs/actas/2026-10-19-dev00-f2-copia-inmutable.md`.
- **Siguiente fase:** F3 (inventario de red y semáforos), a la espera de la autorización expresa del Product Owner.

## Decisiones D1–D6

Se pueden cambiar en cualquier momento; el cambio afecta solo a las fases indicadas.

| # | Decisión | Aplica a |
|---|---|---|
| D1 | Los artefactos de recepción (manifiesto, inventario y auditoría) son JSON con `schema_version` 1.0.0, validados con DTO pydantic en `caso`, sin esquema público por ahora. Se registran como propuesta en `docs/adr/ADR09-artefactos-de-recepcion.md`. | F2, F3, F4, F7 |
| D2 | Configuración de entrada: `frutales_solo.sumocfg`. `osm.sumocfg` se registra como heredado (lo generó el asistente de OSM con viajes aleatorios; no se usa para Frutales). | F2, F6, F7 |
| D3 | Quien lanza SUMO es un runner mínimo en `simulacion/runner.py`, que adelanta el núcleo de DEV07. | F6 |
| D4 | Límites de la corrida base: 7200 s simulados y 900 s reales. Son provisionales, «pendiente del piloto». Se pasan como parámetros de línea de comandos y no modifican ningún archivo. | F6, F9 |
| D5 | Punto de entrada: CLI mínima `python -m semaforo case receive`, en lugar de un script suelto. | F7 |
| D6 | Dependencias nuevas: `pydantic` (pasa de desarrollo a ejecución) y `defusedxml`. Se ejecuta `pip-audit` al agregarlas. Corrección del 2026-10-19: ambas entran en F2 (el manifiesto usa DTO y el `.sumocfg` se lee con `defusedxml` desde F2). | F2 |

Reglas de identidad y ubicación que acompañan a D1:

- El identificador de contenido de una recepción se calcula con la configuración de entrada y los archivos que referencia. Las salidas de SUMO (`tripinfos`, `viajes`, `estadisticas`, `edgeData`) y los archivos no referenciados se registran con hash, pero no forman parte de la identidad. Así, volver a ejecutar la GUI no crea una versión nueva.
- Copia inmutable en `datos/originales/sumo/<id>/`, artefactos derivados en `datos/derivados/recepcion/<reception_id>/`, corridas en `datos/ejecuciones/<run_id>/` e informe versionado en `docs/recepcion/<reception_id>.md`. Cada recepción crea un `reception_id` nuevo y nunca se sobrescribe.

## Congelación de R0 (provisional)

R0 es una copia del estado actual de la simulación. Sirve para desarrollar y validar las herramientas de F1 a F9. **No es la recepción oficial**, que será R1 (F10), después de las modificaciones del Product Owner. Los cambios que se hagan en la carpeta original no afectan a F1–F9.

| Dato | Valor |
|---|---|
| Origen | carpeta de simulación del Product Owner, fuera del repositorio (con 21 archivos) |
| Destino | `datos/originales/sumo/R0-provisional/` (ignorada por git) |
| Contenido | 21 archivos, 1 287 069 bytes; sin subcarpetas ni enlaces simbólicos |
| Verificación | el original coincidía con la línea base de `tools/sumo` (21/21); la copia coincide con el original (21/21); el original no cambió durante la copia; `vigilar_sumo.ps1` dice «Sin cambios» antes y después |
| Protección | archivos en solo lectura; los hashes no cambiaron al marcarlos |

Implicación para fases posteriores: las copias que hagan F2 y F6 deben usar `shutil.copyfile` (sin atributos), para que los archivos de trabajo no hereden el solo lectura.

SHA-256, tamaño en bytes y archivo:

```
5c17e317484b518d79152382d7fa376237c841bb710ac48010889ea4fb994e0c       573  build.bat
278a3da0dfa137450a504cecc5c1ad09d791566121e46d3903576ccabdbc591a      1422  edgeData.xml
74562fc3216bcfe3eaa7b43d898eaf2ea784cbd00ad4cfacd465b61565db4b09      2133  estadisticas.xml
311384ee8009460649ddb1df04f18f9b9f9921005f4495736d4fb0df0a378858       881  frutales_solo.rou - copia.xml
3e3b929477bbf6d1e4411a7586d5446f0c0ff46e9e50f1435fecf7c61843d369      3092  frutales_solo.rou.xml
305b5d960a6ddf4d5e905dc246c2db7b4e562d6aba43ebdc578fe635d38d9e51       593  frutales_solo.sumocfg
85cd59a1f2d0766619508293236ac912547cef690744b441409c5a24b2166896     67835  osm.net.xml.gz
8b81602a27bf97a58e8fb707744e000465563db4cf25f37db42e8f79e47dd8bb      1106  osm.netccfg
fc9e2c31ff03d311eced2c8bd211585b3a156ad53b910eadf9a68aa0423041a7      1405  osm.ogcfg
eb383fd981492a2035de5d16bbb489cafcfc11239ed605d9ab52b7a4c5f6e2b0     28970  osm.passenger.trips.xml
5bff68767306ab4bdb82fc634e2641476524a0f8a3c8cea5acef083012461dfc      7057  osm.poly.xml.gz
0ad0e927f662b2eb079867b3a3a26adec609b09e8ee9cfeaf12b18cab09c37e9       764  osm.polycfg
9f3c199231aecdfd0d68c0169b544e2f836d48bc9f2767abda6e0c50c360b408      1150  osm.sumocfg
51d96963d903cbf3bf0d9e7718593c5dc76e5abc023a9821c101c9b4cc214734        93  osm.view.xml
0b280858202092056772ef480f3aba97419df1a80c818d1698d9addcb531c218     43525  osm_bbox.osm.xml.gz
1ab2e2ad2adef42353c9a4ede9d2f611008dd471cb3e6b4ec936d53303e5d49d       393  output.add.xml
3477f82c8510cd9143c011ecb1d2f565df426ebb419a78efbbe3af19f47be8af        23  run.bat
c241ef31273b61fbcbfef5229e5dfb0e4f53363032e5f7cc25ba33951dfae6b2      1422  stats.xml
c65b092ff339e8fa2a91febab9cead687c8ee06256ec5af14c8485a34d090a04     25471  tripinfos.xml
c89dd436acf84bace0207134c5b19cd8e1c6d3933bff43cf225b4d94854f1acc   1098856  viajes.xml
12ca0974bf42b41bdc1aca05042f71da2708c9b531ab2539208ba76c73aa357e       305  vista_buses.xml
```

## Entorno registrado

| Elemento | Valor |
|---|---|
| SUMO | 1.27.1 (`sumo.exe`, `netconvert.exe` y `sumo-gui.exe` en `C:\Program Files (x86)\Eclipse\Sumo\bin`) |
| Compilación | Windows-10.0.17763 AMD64, MSVC 19.29.30133.0, Release |
| Python | 3.12.3 |
| Equipo | AMD Ryzen 9 4900HS (8 núcleos, 16 hilos), 15,4 GB de RAM |
| Sistema operativo | Windows 11 Pro 10.0.26200, 64 bits |
| Disco D: | 428,8 GB libres de 488,5 GB |

Opciones comprobadas en `sumo --help` (16 de 16 disponibles): `--end`, `--begin`, `--seed`, `--step-length`, `--net-file`, `--route-files`, `--additional-files`, `--configuration-file`, `--tripinfo-output`, `--tripinfo-output.write-unfinished`, `--statistic-output`, `--duration-log.statistics`, `--no-step-log`, `--time-to-teleport`, `--ignore-route-errors` y `--no-warnings`.

Textos oficiales relevantes:

- `--tripinfo-output.write-unfinished`: «Write tripinfo output for vehicles which have not arrived at simulation end». Sirve para los viajes inconclusos del protocolo.
- `--time-to-teleport`: «Specify how long a vehicle may wait until being teleported, defaults to 300…».
- `--end`: «Defines the end time in seconds; The simulation ends at this time».

## Observaciones

- **`SUMO_HOME` está definida dos veces:** a nivel de usuario (`C:\Program Files (x86)\Eclipse\Sumo`) y de máquina (con barra final, `...\Sumo\`). La sesión usa la de usuario. El código debe normalizar la ruta con `pathlib` y no concatenar cadenas.

## Pendientes de verificación

- Comportamiento de `--end` cuando no se indica: se confirma en F6 y F9.
- Orden de `linkIndex` que genera `netconvert` a partir de archivos planos: se confirma en F1.
- Programa activo cuando un semáforo tiene varios programas: se confirma en F3 y F6.
