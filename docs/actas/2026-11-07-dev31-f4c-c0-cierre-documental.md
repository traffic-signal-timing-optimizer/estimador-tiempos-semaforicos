Escrito para: el Product Owner y el equipo técnico.

# DEV31 F4c C0: cierre documental de decisiones y comprobaciones

- **Fecha de cierre de C0:** 2026-11-07 (Lima).
- **Fecha de esta acta:** 2026-11-07 (Lima).
- **Alcance:** reconstruye el cierre de C0 a partir de `documentacion/CONTEXTO.md`, sección 10, y del plan aprobado `docs/actas/2026-11-07-dev31-plan-correcciones-auditoria.md`. Esta redacción no repite consultas a PostgreSQL ni pruebas de red; distingue lo registrado de lo aún no comprobado.
- **Historia:** HU15; tarea DEV31 F4c C0.

## Resultado registrado de C0

1. **C0.1, decisiones:** el PO aprobó D1 a D14. Aceptó D15 como riesgo: los roles del proyecto conservan el permiso público `CONNECT` a otras bases del servidor. La aceptación no autoriza leerlas ni modificarlas.
2. **C0.2, configuración de red:** se leyeron `postgresql.conf`, `postgresql.auto.conf`, `pg_hba.conf` y la configuración del servicio. Se registró `listen_addresses='*'` y reglas de `pg_hba.conf` limitadas a `127.0.0.1` y `::1`. Posteriormente `SHOW hba_file` respondió, pero el rol `semaforo_lectura` no pudo consultar `pg_hba_file_rules`. **La confirmación en vivo de las reglas con un rol autorizado sigue pendiente y es opcional para el cierre de C0.**
3. **C0.3, aislamiento:** se registró rechazo de conexiones dirigidas a `192.168.1.36`, a dos direcciones IPv6 globales y al nombre del equipo; `localhost` alcanzó la autenticación. Se registró ausencia de reglas de entrada del firewall para 5432. Estas pruebas corresponden a ese momento y no garantizan el estado futuro de la red.
4. **C0.4, otros clientes:** el PO confirmó que Power BI y Python se conectan por `localhost`.
5. **C0.5, rol del panel:** el PO creó `semaforo_panel` como `postgres`. Se registró que el rol autentica, carece de privilegios de administrador y pertenencias y aún no puede conectar a `semaforo`; su acceso solo a vistas aprobadas corresponde a C2.6. El archivo SQL temporal usado para crearlo se eliminó. Esta acta no contiene credenciales.

## Pendientes separados de C0

- **C0.2 en vivo:** comprobar `pg_hba_file_rules` con un rol autorizado y registrar el resultado; no se interpreta la lectura de archivos como confirmación de las reglas instaladas.
- **C0.6 / D4:** cambiar `listen_addresses` a `localhost` y reiniciar el servicio solo con orden expresa del PO. El plan aprobado lo dejó sin etapa ejecutada.
- **D15:** riesgo aceptado por el PO mientras la laptop mantenga el uso y la red declarados. Si cambian esas condiciones, se revisa la decisión.

**Cierre:** C0 quedó cerrada el 2026-11-07 con la limitación de C0.2 registrada. C1 se cerró después; C2 no ha empezado. No se cambió la configuración ni la base al redactar esta acta.
