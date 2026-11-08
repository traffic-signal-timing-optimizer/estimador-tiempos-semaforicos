# ADR12: Base de evidencia en PostgreSQL y panel estático

- **Estado:** Aceptada el 2026-11-08 (el PO aprobó el diseño el 2026-11-05 en DEV31 F0 y cada fase después; este registro la formaliza en F7)
- **Tipo:** P (equipo)
- **Fecha de registro:** 2026-11-08
- **Fuente:** `docs/actas/2026-11-05-plan-base-de-datos.md`, `docs/actas/2026-11-05-dev31-f0-planificacion-y-diseno.md` y `docs/actas/2026-11-07-dev31-plan-correcciones-auditoria.md`

## Decisión

Una base **PostgreSQL local** (`semaforo`) consolida las entradas, los resultados y la evidencia del procedimiento. Un **panel HTML estático** la muestra sin servidor. Los **archivos publicados con huella siguen siendo el original**: la base es su copia de consulta, se regenera desde ellos y ningún proceso de cálculo la lee.

Principios (B1 a B12 de F0):

| # | Principio |
|---|---|
| B1 | Los archivos son la fuente y la base se regenera desde ellos, con la misma huella de contenido |
| B2 | Solo se agregan filas: la base rechaza modificar o borrar evidencia. Las dos excepciones están declaradas (`control.cargas`, `control.conflictos`) |
| B3 | Cada fila sabe de qué archivo y de qué carga viene |
| B4 | La prueba final se oculta con seguridad por filas hasta su apertura |
| B5 | Lo que es de prueba se decide al cargar, por la partición y la etapa de la semilla |
| B6 | Las unidades van en el nombre de la columna |
| B7 | Cero no es faltante: vacío significa que no hay dato |
| B8 | Todo lleva `caso_id`; nada nombra a un cruce |
| B9 | Claves naturales: cargar dos veces no duplica, y una clave con otra huella se rechaza y se registra |
| B10 | Las métricas se copian de los archivos, nunca se recalculan de otra forma |
| B11 | Fuera de la base: el FCD crudo, los videos y los registros completos de SUMO |
| B12 | El panel y las consultas leen vistas, no tablas |

Controles que agregó la auditoría de noviembre (F4c):

- **Tres huellas:** versión del esquema, contenido y reglas instaladas. La referencia está en git (`docs/bd/huellas.json`).
- **Candado compartido y lectura en una sola foto** para verificar y conciliar: una carga en curso da *no concluyente*, no un falso resultado.
- **Reconstrucción segura** (`bd reconstruir`, P0 a P9): la base nueva se valida con otro nombre y el PO aprueba las tres huellas antes del cambio. Si falla, se revierte. La anterior no se borra sola.
- **Exclusiones verificables** (`bd decidir`): archivos con ruta y huella, que sobreviven a una reconstrucción.
- **Respaldos con ficha**, restaurados y comprobados (`bd respaldar`, `bd probar-respaldo`).

## Motivo

La tesis debe responder cómo se sabe que el procedimiento fue honesto, no solo qué números salieron: que la prueba no se miró antes, que las alternativas se compararon en las mismas condiciones y que nada se borró ni se cambió después. Con cientos de corridas y miles de filas, responderlo leyendo archivos sueltos no es viable.

PostgreSQL ya estaba instalado (17.9). Da tipos estrictos, permisos por usuario, seguridad por filas y bloqueo de cambios en la propia base.

## Alternativas descartadas

- **SQLite:** sin usuarios ni permisos, quien abre el archivo puede cambiarlo. Migrar después significaría adaptar y volver a probar el cargador, las consultas y las pruebas.
- **Solo archivos, sin base:** no permite consultar en un solo lugar ni aplicar el cegado con permisos.
- **La base como original:** en una base se puede cambiar un número sin dejar rastro. En archivos con huella guardada en git, no.
- **Que los cálculos lean la base:** obligaría a volver a probar todo lo ya construido y uniría el cálculo a un servicio. Hoy la base puede fallar sin que se pierda nada.
- **Panel con servidor:** no hay requisito; sumaría superficie de ataque (ADR02).

## Impacto

- **Código:** paquete `bd`, y los comandos `bd iniciar`, `cargar`, `metricas`, `conciliar`, `verificar`, `regenerar`, `hito`, `decidir`, `evidencia`, `panel`, `respaldar`, `ficha`, `probar-respaldo` y `reconstruir`.
- **Esquema:** una sola fuente, `docs/bd/esquema.toml`. De ahí salen el diccionario, el SQL y los gráficos. Son 57 tablas, 880 columnas, 117 relaciones y 26 vistas.
- **Pruebas:** la puerta completa necesita PostgreSQL encendido. Si está apagado, falla: no se salta.
- **Amenazas nuevas:** alterar filas, espiar la prueba desde el panel, filtrar contraseñas e inyectar texto en el panel. Sus controles están en `docs/arquitectura/arquitectura-tecnica.md`.

## Límites y riesgos aceptados

- **El administrador de la laptop puede saltarse los permisos.** La protección es que el cambio deja rastro, no que sea imposible.
- **D4 pendiente:** `listen_addresses` sigue en `*` y QA34 queda parcial. El riesgo lo aceptó el PO (D15) mientras la laptop siga con el uso declarado: una sola persona, en red cerrada. `pg_hba.conf` solo admite 127.0.0.1 y ::1. **Si cambian la red o el uso, se aplica D4.**
- **Prueba inestable de reconstrucción:** falla a veces (acta de F6). Aceptada como pendiente por el PO. Se resuelve antes del próximo cambio real de base o del cierre de DEV31.
- **La prueba a escala de DEV16** (carga completa y conciliación incremental) se hace con DEV16. Hasta entonces, los tiempos a esa escala son estimados.

## Cómo crece

- **Más corridas:** la cola por acceso se guarda como arreglo (de 669 MB a 137 MB al cambiarlo). F0 estimó unos 2 GB para DEV16 y unos 6 GB para todo el proyecto.
- **Más cruces:** cada caso es un dato; el esquema no cambia.
- **Corridas hechas en otra máquina:** se copian los archivos y se cargan verificando sus huellas. `control.entornos` registra dónde corrió cada una, en local o en cualquier nube.
- **Otras herramientas de consulta (por ejemplo, Power BI):** pueden leer con un rol de solo vistas, igual que el panel. Requiere revisar el cegado de esa conexión.
- **Panel con servidor:** usaría las mismas vistas y el mismo rol. Requiere otro ADR.

## Prueba de aceptación

QA32 a QA37 (`documentacion/matrices/pruebas.csv`). Estado en `docs/actas/2026-11-08-dev31-f6-cierre-tecnico.md`, sección 2.

## Dónde verlo

- Arquitectura técnica: `docs/arquitectura/arquitectura-tecnica.md`
- Arquitectura de solución: `docs/arquitectura/arquitectura-de-solucion.md`
- Modelo de datos con todas las columnas: `docs/arquitectura/modelo-de-datos.md` y `docs/bd/diccionario.md`
