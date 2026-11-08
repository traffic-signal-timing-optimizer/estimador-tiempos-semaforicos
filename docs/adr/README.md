# Registro de decisiones de arquitectura (ADR)

Los ADR01 a ADR08 provienen de `documentacion/documentos/01_Diseno_tecnico.md` y conservan su número. Del ADR09 en adelante son decisiones de este equipo, aceptadas o pendientes del Product Owner. Las aprobaciones y los registros de fase están en `docs/actas/`.

| ID | Título | Tipo | Estado | Próximo paso |
|---|---|---|---|---|
| [ADR01](ADR01-monolito-modular-local.md) | Monolito modular local | V/P | Propuesta; prueba aceptada | Registrar la adopción (DEC09) |
| [ADR02](ADR02-cli-y-reportes-html.md) | CLI y reportes HTML estáticos | P | Propuesta | Decidir (DEC09) |
| [ADR03](ADR03-persistencia-por-artefactos.md) | Persistencia por artefactos inmutables | V/P | Propuesta | Decidir (DEC09) |
| [ADR04](ADR04-ejecucion-sumo-subprocess.md) | Ejecución de SUMO por subprocess | P | Propuesta | Decidir (DEC09) |
| [ADR05](ADR05-xgboost-y-mediana.md) | XGBoost como candidato y mediana | V/P | Propuesta | Decidir (DEC09) |
| [ADR06](ADR06-correccion-determinista.md) | Corrección determinista acotada | P | Propuesta | Decidir (DEC09) |
| [ADR07](ADR07-prueba-final-separada.md) | Prueba final separada | V/P | Propuesta | Decidir (DEC09) |
| [ADR08](ADR08-formato-de-modelos.md) | Formato de modelos sin deserialización insegura | P | Propuesta | Decidir (DEC09) |
| [ADR09](ADR09-artefactos-de-recepcion.md) | Artefactos de recepción (manifiesto, inventario y auditoría) | P (equipo) | Aceptada (2026-10-19) | Implementada en F2 a F9 de DEV00 |
| [ADR10](ADR10-firma-de-validate-case.md) | Firma de la validación del caso: `validate_case(ruta)` | P (equipo) | Aceptada (2026-10-30) | Implementada en F3 de DEV02 |
| [ADR11](ADR11-salidas-de-medicion.md) | Salidas de medición de las corridas preparadas (FCD en la zona y no iniciados) | P (equipo) | Aceptada (2026-11-02, por delegación del PO); enmendada en DEV19 F5 (zona = aproximación modelada) | Implementada en DEV19 |

Estados posibles: Propuesta, Aceptada, Rechazada, Sustituida.

**Alcance posterior al registro inicial:** el PO aprobó HU15/DEV31 y PostgreSQL local el 2026-11-05. ADR02 y ADR03 contienen notas de alcance que impiden interpretar sus frases originales como una prohibición vigente de la base. ADR12 y la aceptación formal de ADR01–ADR08 (DEC09) siguen pendientes de DEV31 F7; esta nota no cambia el estado «Propuesta» de esas ocho ADR.
