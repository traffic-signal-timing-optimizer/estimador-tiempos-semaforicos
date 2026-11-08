# Registro de decisiones de arquitectura (ADR)

Los ADR01 a ADR08 provienen de `documentacion/documentos/01_Diseno_tecnico.md` y conservan su número. Del ADR09 en adelante son decisiones de este equipo, aceptadas o pendientes del Product Owner. Las aprobaciones y los registros de fase están en `docs/actas/`.

| ID | Título | Tipo | Estado | Próximo paso |
|---|---|---|---|---|
| [ADR01](ADR01-monolito-modular-local.md) | Monolito modular local | V/P | Aceptada (2026-11-08, DEC09) | Implementada; vigila `test_arquitectura.py` |
| [ADR02](ADR02-cli-y-reportes-html.md) | CLI y reportes HTML estáticos | P | Aceptada (2026-11-08, DEC09) | Informes en DEV09 y panel en DEV31; resto de vistas en DEV21 |
| [ADR03](ADR03-persistencia-por-artefactos.md) | Persistencia por artefactos inmutables | V/P | Aceptada (2026-11-08, DEC09) | Implementada; exportación en DEV21 y DEV27 |
| [ADR04](ADR04-ejecucion-sumo-subprocess.md) | Ejecución de SUMO por subprocess | P | Aceptada (2026-11-08, DEC09) | Implementada; vigila `test_estructura.py` |
| [ADR05](ADR05-xgboost-y-mediana.md) | XGBoost como candidato y mediana | V/P | Aceptada (2026-11-08, DEC09) | Se implementa en DEV16 |
| [ADR06](ADR06-correccion-determinista.md) | Corrección determinista acotada | P | Aceptada (2026-11-08, DEC09) | Implementada en DEV13 |
| [ADR07](ADR07-prueba-final-separada.md) | Prueba final separada | V/P | Aceptada (2026-11-08, DEC09) | Implementada; falta la parte de QA15 con modelo (DEV16) |
| [ADR08](ADR08-formato-de-modelos.md) | Formato de modelos sin deserialización insegura | P | Aceptada (2026-11-08, DEC09) | Se implementa en DEV17 |
| [ADR09](ADR09-artefactos-de-recepcion.md) | Artefactos de recepción (manifiesto, inventario y auditoría) | P (equipo) | Aceptada (2026-10-19) | Implementada en F2 a F9 de DEV00 |
| [ADR10](ADR10-firma-de-validate-case.md) | Firma de la validación del caso: `validate_case(ruta)` | P (equipo) | Aceptada (2026-10-30) | Implementada en F3 de DEV02 |
| [ADR11](ADR11-salidas-de-medicion.md) | Salidas de medición de las corridas preparadas (FCD en la zona y no iniciados) | P (equipo) | Aceptada (2026-11-02, por delegación del PO); enmendada en DEV19 F5 (zona = aproximación modelada) | Implementada en DEV19 |
| [ADR12](ADR12-base-de-evidencia-postgresql.md) | Base de evidencia en PostgreSQL y panel estático | P (equipo) | Aceptada (2026-11-08; aprobada por el PO en DEV31 F0) | Implementada en DEV31 |

Estados posibles: Propuesta, Aceptada, Rechazada, Sustituida.

**Aceptación de las propuestas (DEC09):** el PO delegó la decisión el 2026-11-08 y ADR01 a ADR08 quedaron aceptadas, cada una con sus precisiones al final del archivo. El análisis está en `docs/actas/2026-11-08-dev31-f7-dec09.md`. Una decisión aceptada se cambia con otro ADR que la sustituya, no editándola en silencio.
