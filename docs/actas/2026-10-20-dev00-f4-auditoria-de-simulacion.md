# Acta 2026-10-20: DEV00 · F4 (auditoría de rutas, demanda y comportamiento)

- **Tipo:** registro de fase del plan de DEV00 (HU04)
- **Fecha:** 2026-10-20
- **Autorización:** el Product Owner autorizó F4 («procede con F4») y aprobó dos cambios de alcance (ver abajo). Pidió no publicar todavía los commits.
- **Código y pruebas:** commit `2d23020`; corrección posterior en `610b6ae` (ver «Revisión posterior»).
- **Siguiente fase:** F5 (núcleo de trazabilidad), completada: ver `docs/actas/2026-10-20-dev00-f5-nucleo-de-trazabilidad.md`.

## Cambios de alcance aprobados

| Cambio | Fase | Motivo |
|---|---|---|
| Avisar si un archivo adicional declara programas semafóricos o detectores | F4 (hecho) | El inventario de F3 solo lee la red; un cambio de tiempos hecho en un archivo adicional pasaría inadvertido |
| Tabla de movimientos por carril, calculada desde las conexiones | F8 (pendiente) | QA23 pide revisar movimientos y giros por carril y clase; ninguna fase de F0 a F10 lo cubría |
| Contar los vehículos de cada flujo como SUMO y separar la carga de entrada por clase | F4 (hecho, `610b6ae`) | La estimación con decimales no coincidía con lo que SUMO carga, y la carga por carril mezclaba un carril exclusivo de bus |
| Comparar lo declarado con lo cargado y lo insertado, la espera para entrar y los teletransportes por causa; marcar la corrida si hay demanda no atendida | F6 (hecho, `5d9c1f5`) | En la corrida previa del Product Owner una parte de la demanda nunca entró a la red: esa demora no se debe al semáforo |

## Qué se implementó

| Módulo | Responsabilidad |
|---|---|
| `caso/audit.py` | `audit_simulation`: audita la simulación a partir del `.sumocfg`, sin ejecutar SUMO |
| `caso/audit_models.py` | `SimulationAudit` y sus partes (pydantic, `schema_version` 1.0.0) |
| `caso/xml_input.py` | lectura segura de XML (gzip con límite y `defusedxml`) y de atributos numéricos, compartida con el inventario de F3 |
| `caso/sumo_config.py` | `read_config_options`: todas las opciones del `.sumocfg` por sección |

## Qué registra y qué comprueba

- **Configuración (HU04):** todas las opciones del `.sumocfg` tal como están escritas; además, inicio, final, paso y semilla.
- **Comportamiento:** cada `vType` con su clase y sus parámetros declarados, y los atributos de salida de cada flujo (por ejemplo `departLane`).
- **Demanda:** cada flujo, vehículo y viaje con su tasa en veh/h, los vehículos que declara y la carga por arista de entrada y clase, con los carriles que admiten esa clase. Reconoce `perHour`, `vehsPerHour`, `period` (también `exp(…)`), `probability` y `number`. En los flujos de intervalo fijo cuenta como SUMO 1.27.1: techo(duración ÷ intervalo), con el final excluido (medido en nueve casos y fijado en `tests/integration/test_audit_sumo.py`); en los aleatorios da la media.
- **Rutas, por clase de vehículo:** que cada arista exista, que tenga algún carril para la clase y que haya una conexión permitida para la clase entre aristas consecutivas (permisos del carril de origen, del de destino y de la propia conexión).
- **Coherencia:** rutas y tipos usados sin definir, definidos sin usar, y demanda que empieza después del final o termina después de él.
- **Archivos adicionales:** programas semafóricos (`tlLogic`, `WAUT`), detectores y atributos `file=` con ruta absoluta.
- **Lo que no interpreta se dice:** distribuciones, `load-state` y cualquier otro elemento quedan como `NOT_AUDITED`, nunca se omiten en silencio.
- **Entradas que no se siguen:** absolutas, fuera de la carpeta o alcanzadas por un enlace o una unión. Cada caso tiene su propio motivo, y cada capa de defensa está probada por separado.

## Evidencia de la puerta de salida (copia inmutable de R0)

Según ADR09, el detalle (demanda, rutas y cargas de Frutales) queda en `datos/derivados/recepcion/f4-pruebas/auditoria_R0.json`, ignorado por git. Lo verificable sin revelarlo:

| Comprobación | Resultado |
|---|---|
| Vehículos declarados | coinciden con los que SUMO cargó en la corrida previa del Product Owner (`estadisticas.xml` de R0) |
| Viabilidad de las rutas por clase | coincide con el análisis independiente hecho antes de programar: todas viables |
| Copia de F2 | hash y fecha de sus archivos sin cambios |
| Determinismo | dos auditorías producen el mismo JSON |
| Rutas absolutas en el JSON | ninguna |
| Tiempo | menos de 0,1 s |

La configuración de R0 no fija `end`: confirma que el runner de F6 debe pasar el límite de D4 por línea de comandos.

## Verificación

- Pruebas: 245 pasan y 1 se salta de forma declarada (enlaces simbólicos sin privilegios). F4 añade 36.
- **Desviación del procedimiento:** las pruebas de la auditoría se escribieron antes del código, pero no se ejecutaron en rojo antes de implementarlo. Para compensarlo, la verificación por mutaciones fue más amplia: 29 mutaciones del código, todas detectadas. Ocho sobrevivieron al principio y se cerraron con pruebas nuevas: carriles solo de bus en origen y destino, demanda que empieza justo al final, aristas internas en una ruta, opciones sin valor y el motivo de cada entrada no seguida (incluida una unión real de Windows).
- La refactorización de `xml_input.py` se hizo con las 35 pruebas de F3 en verde antes y después.
- `ruff`, formato y `pyright` estricto sin errores; el validador de contratos sigue en 43 comprobaciones.

## Limitaciones conocidas

- La conexión se comprueba por arista y clase: no se simula el cambio de carril dentro de una arista ni la elección del carril de salida.
- En los viajes (`trip`, o flujos con `from` y `to`) solo se comprueba que los extremos existan y admitan la clase; la ruta la calcula SUMO.
- Los vehículos declarados no son los insertados: SUMO puede insertar menos si la red se satura o la simulación termina antes. Lo comparará el runner de F6 (cambio de alcance aprobado).
- De los detectores solo se avisa: no se interpreta su posición ni su periodo.
- Un tiempo del `.sumocfg` escrito en formato `h:m:s` queda vacío en el resumen; su texto se conserva en las opciones.
- La versión de SUMO no se registra aquí, sino en el runner de F6.

## Revisión posterior (2026-10-20)

Al revisar el impacto de las limitaciones, el Product Owner aprobó dos correcciones (commit `610b6ae`):

1. **Conteo de vehículos.** La auditoría estimaba los vehículos de un flujo con decimales, y en R0 la cifra no coincidía con la que SUMO cargó en la corrida previa del Product Owner. Se midió la regla de SUMO 1.27.1 en nueve flujos: emite techo(duración ÷ intervalo), con el final excluido. Ahora la auditoría cuenta igual, con un redondeo previo a 9 decimales para que un error de coma flotante no sume un vehículo, y coincide con SUMO. Ocho de esos casos quedan fijados en una prueba que ejecuta SUMO.
2. **Carga de entrada por clase.** La carga se separa por clase de vehículo y cuenta solo los carriles que admiten la clase. Antes, un carril exclusivo de bus contaba también para los autos.

Esta vez las pruebas sí fallaron antes del cambio. Las 35 mutaciones aplicadas se detectan; dos sobrevivieron al principio (un flujo aleatorio con media entera y dos flujos de la misma clase por la misma entrada) y se cerraron con pruebas. Quedan 254 pruebas que pasan y 1 que se salta de forma declarada.
