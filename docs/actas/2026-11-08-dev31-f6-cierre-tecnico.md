Escrito para: el Product Owner (cierre técnico de F6 de DEV31) y el equipo técnico.

# DEV31 F6: ensayos de daño, inspección y cierre técnico

- **Fecha:** 2026-11-08
- **Tarea:** DEV31 (HU15), fase F6 de la sección 13 de `docs/actas/2026-11-05-plan-base-de-datos.md`: ensayos de daño, inspección contra la documentación y acta de cierre técnico.
- **Orden del PO:** «ok arranca F6». El ensayo a escala de DEV16 queda para cuando se ejecute DEV16 (decisión del PO).
- **Modelo:** Haiku 5.5, según el plan.
- **Estado:** cerrada en lo técnico, con un pendiente aceptado por el PO (sección 5).

## 1. Ensayos de daño

Se corrieron los siete guiones de `scripts/mutaciones/` sobre el código final, uno tras otro. Cada uno rompe una regla, corre las pruebas que deben notarlo y restaura el archivo.

| Guion | Resultado | Nota |
|---|---|---|
| `dev31_esquema.py` | 14 de 14 | Igual que en F1 |
| `dev31_f2.py` | 17 de 17 | Igual que en F2 |
| `dev31_f3.py` | 23 de 23 | Primera corrida: 21 de 23. Ver abajo |
| `dev31_f4.py` | 13 de 13 | Igual que en F4 |
| `dev31_c1.py` | 26 de 26 | El acta de C1 registró 23. El guion tiene hoy 26 daños: se agregaron después y los 26 se detectan |
| `dev31_c3.py` | 23 de 23 | Igual que en C3 |
| `dev31_f5.py` | 29 de 29 | Igual que en F5 |

**Total: 145 de 145 detectados.**

**Dos casos del ensayo de F3 en la primera corrida:**
- **Un daño no aplicó** («se abre la prueba sin modelo congelado»): el texto que buscaba ya no existía porque la regla cambió. Se actualizó al texto actual.
- **Un daño sobrevivió** («la vista no aplica el cegado a quien consulta»). Era **equivalente**: la vista se crea con `security_invoker = true`, pero `03_seguridad.sql` la cambia a `false` justo después, así que quitar esa línea no cambia la base real. El daño se sustituyó por uno que sí altera el comportamiento: quitar el filtro que oculta los escenarios cegados del panel («la vista del panel no filtra los escenarios cegados»). Se detecta. La corrección del guion está sin commit (ver sección 7).

## 2. Inspección contra los criterios QA32 a QA37

Criterios del plan de la base, sección 7. Estado a la fecha de este acta:

| Criterio | Qué comprueba | Estado | Evidencia |
|---|---|---|---|
| QA32 | Carpeta alterada no se carga; cargar dos veces no duplica | **Cumple** | Pruebas de carga con SUMO (`tests/integration/test_bd_carga_sumo.py`) y daños de F3 sobre el cargador (23 de 23) |
| QA33 | La base coincide con los archivos: conteos y demora recalculada | **Cumple** | Pruebas de conciliación (`test_bd_conciliacion_sumo.py`) y daños de F4 (13 de 13). Acta de F4 |
| QA34 | Seguridad: el panel no modifica; la base rechaza cambios de evidencia; sin contraseñas en el repositorio; solo conexiones desde la laptop; texto malicioso se muestra como texto | **Parcial** | Cumple: el panel solo lee vistas, la base rechaza cambios y borrados de evidencia (pruebas de seguridad), no hay contraseñas en el repositorio y el texto se escapa (pruebas del panel). **No cumple:** `listen_addresses = '*'`, o sea, el servicio acepta conexiones de la red. Lo aceptó el PO (riesgo D15, acta de C0). Las reglas de `pg_hba.conf` solo admiten 127.0.0.1 y ::1 según la lectura de C0.2 |
| QA35 | Cegado: antes de la apertura, ninguna consulta del panel ni de desarrollo devuelve datos de prueba | **Cumple con reserva** | Barrido de cegado y pruebas de reglas. Daño de F5 y de F3 sobre el filtro de cegado: detectados. La base real aún no tiene una prueba cerrada, así que ahí solo se verifican permisos (acta de F5) |
| QA36 | Borrar y regenerar da la misma huella; el respaldo se restaura | **Cumple con reserva** | Pruebas de respaldos y de reconstrucción (`test_bd_respaldos.py`, `test_bd_reconstruccion.py`). Reserva: la prueba inestable de la sección 5 |
| QA37 | Revisión manual: una persona no técnica entiende el panel | **Cumple** | Revisión del PO sobre el panel (acta de F5): «ya se revisó el panel está bien» |

**Lo que sí quedó fuera de QA34:** el servicio sigue escuchando en toda la red. El PO lo aceptó en C0 (D15) bajo la condición de que la laptop mantenga el uso declarado: solo el PO entra a la base y la aplicación es la única que se conecta, en una red cerrada. El cambio a `localhost` (D4) está aprobado, pero espera una orden expresa del PO para aplicarse.

## 3. Inspección de la documentación contra el código

Se revisaron los comandos que documentan el manual de instalación (`docs/manuales/instalacion-en-otra-laptop.md`) y la guía del panel (`docs/panel/LEEME.md`). Todos existen en el código: `bd iniciar`, `cargar`, `conciliar`, `verificar`, `regenerar`, `respaldar`, `probar-respaldo`, `reconstruir`, `evidencia` y `panel`.

**Diferencias que quedan para F7 (documentación final):**
- `documentacion/CONTEXTO.md`, la línea de DEV31/HU15, dice «C3 y F5–F8 siguen pendientes». Está desactualizada: C3 y F5 están cerradas. Se corrige en esta entrega (sección 7).
- Los documentos 01 a 03 aún dicen que no hay base de datos. Eso lo corrige F7, según el plan.
- El número de corridas aparece con dos cifras: 133 en el plan (corridas existentes) y 130 series en el panel. Hay que aclarar la diferencia en F7 y no dejarla como está. Las tablas de la base son 57, con 880 columnas y 117 relaciones (acta de F5).

## 4. Cambios de F6

- `scripts/mutaciones/dev31_f3.py`: se actualizaron los dos daños de la sección 1. No se cambió código de `src/`.
- Ningún archivo de `src/` ni de `tests/` quedó modificado. El diagnóstico temporal de la sección 5 se borró antes de cerrar.

## 5. Pendiente aceptado: prueba inestable de reconstrucción

**Qué pasa:** en 20 corridas seguidas de `tests/integration/test_bd_reconstruccion.py`, tres fallaron:
- Corrida 4: `test_if_the_second_rename_fails_the_first_is_reverted` («no lanzó el error esperado»).
- Corridas 15 y 20: `test_an_error_while_verifying_P9_restores_the_previous_base` (se detuvo en P8, no en P9).

**Qué se sabe:** en las tres fallas la operación se detuvo en P8, antes del cambio de nombre. El paso P8 revisa que nadie esté conectado a la base antes de intercambiar los nombres. Un diagnóstico de 25 repeticiones no reprodujo ninguna detención. Hipótesis sin confirmar: una conexión de la preparación que sigue listada un instante después de cerrarse.

**Por qué no bloquea:** el fallo se produjo en la prueba, no en un cambio real de base. Cuando la operación se detiene, no cambia nada, así que no hay daño de datos. Solo una base aprobada por el PO se cambia de nombre, y el PO es el único que entra a la base en una red cerrada.

**Decisión del PO:** queda como pendiente. Se resuelve antes de cualquier cambio real de base posterior o antes del cierre de DEV31, lo que ocurra primero.

## 6. Puerta completa de calidad

Resultado de `scripts/check.ps1` sobre el código de esta entrega (corrida iniciada a las 16:38):

- ruff (estilo): sin errores. Formato: 515 archivos ya formateados.
- pyright (tipos, modo estricto): 0 errores, 0 advertencias.
- Esquema: 57 tablas aprobadas (coinciden con el acta de F0), 0 propuestas, 880 columnas, 117 relaciones. Diccionario y SQL generado al día.
- pytest: **5509 pasaron, 1 omitida** (la de siempre). Duración: 14 minutos 38 segundos.
- Contratos de referencia: **43 de 43**, estado «passed».
- Ningún archivo de código oculto para git.
- ruff en `uv.lock` y en pre-commit: ambos 0.17.1.

**Resultado: todas las verificaciones pasaron.**

## 7. Commits y documentación de seguimiento

- Commit de F6: script de F3 corregido y esta acta. Autor: crisroco. Sin push, porque no se pidió.
- `documentacion/CONTEXTO.md` (no versionado): se actualiza la línea de DEV31 y se agrega la bitácora de F6.
- No se incluyen en el commit `docs/auditorias/` ni `.claude/`, que no son de esta fase.

## 8. Pendientes

- **Prueba inestable de reconstrucción** (sección 5): aceptada como pendiente por el PO.
- **D4:** cambiar `listen_addresses` a `localhost`. Orden expresa del PO.
- **D12:** no borrar `semaforo_anterior_20261108_c2` ni `semaforo_anterior_20261108_f5` hasta que el asesor haya visto el panel.
- **Ensayo de escala de DEV16** (carga completa y conciliación incremental): cuando se ejecute DEV16.
- **F7** (documentación final, Opus): solo con orden expresa del PO.
