# ADR01: Monolito modular local

- **Estado:** Aceptada el 2026-11-08 (DEC09, por delegación del PO)
- **Tipo:** V/P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

## Decisión

Una sola distribución Python con módulos que exponen interfaces explícitas. SUMO es un proceso externo. Los límites internos se preservan sin convertir cada módulo en un servicio.

## Motivo

Un analista, procesamiento experimental en archivos locales y un equipo pequeño. Los microservicios añadirían despliegues y comunicación sin un requisito que los justifique.

## Alternativas descartadas

- Microservicios: despliegues y comunicación sin requisito que los justifique.
- Arquitectura hexagonal formal: no es compromiso del documento; el adaptador SUMO sí encapsula la dependencia.

## Impacto

Define la dirección de dependencia: interfaz → servicios de aplicación → reglas de dominio. Las reglas de dominio no importan la CLI ni lanzan procesos.

## Prueba de aceptación

`tests/unit/test_arquitectura.py`: comprueba las reglas de dependencia entre módulos y que los detectores fallan ante imports prohibidos, incluidos los relativos.

Aceptada por el Product Owner para su prueba de aceptación; adopción formal en DEC09.

## Precisiones de DEC09 (2026-11-08)

Análisis y motivo: `docs/actas/2026-11-08-dev31-f7-dec09.md`.

1. **Paquete `bd` y PostgreSQL.** El monolito suma el paquete `bd`. PostgreSQL es un servicio externo, igual que SUMO es un proceso externo: no convierte el programa en un sistema de servicios. La base depende del proyecto y nunca al revés: ningún módulo de cálculo importa `bd`, y `bd` no importa `app` ni `cli`. Lo comprueba `tests/unit/test_arquitectura.py`.
2. **Cómo crece.** El proyecto crece con más corridas y más cruces del mismo programa, no partiéndolo en servicios. El cruce es un dato (`caso_id`); ninguna regla del código depende de Frutales. Las corridas se pueden hacer en otra máquina, porque su manifiesto viaja con ellas y la base se carga después, verificando las huellas.
3. **Otra interfaz.** Un formulario o una API se agregaría junto a `cli`, llamando a `app`, sin tocar `dominio`. Requiere otro ADR y su modelo de amenazas (ver ADR02).
4. **Cuándo revisar esta decisión.** Si aparece un requisito real de varios usuarios a la vez, de ejecución coordinada entre máquinas o de un servicio en línea. Hoy ninguno existe.
