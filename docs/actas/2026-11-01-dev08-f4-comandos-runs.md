# Acta 2026-11-01: DEV08 · F4 (comandos `runs verify` y `runs compare`)

Written for: el Product Owner y el equipo, para revisar cómo se revisan y comparan las corridas con un solo comando.

- **Tipo:** fase F4 de DEV08 (HU14). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisión que aplica:** D11 de F0.

## Qué se construyó

| Archivo | Qué cambia |
|---|---|
| `cli/main.py` | Grupo `runs` con `verify` y `compare` |
| `app/integrity.py` | `workspace_exit_code` y `trace_exit_code` |
| `app/replica.py` | Ofrece `Tolerance` a la interfaz (la interfaz no puede importar `simulacion`, ADR01) |
| `README.md` | Sección «Revisar y comparar corridas» |

## Los comandos

```
python -m semaforo runs verify [--workspace datos] [--run-id RUN_ID]
python -m semaforo runs compare --run-a RUN_ID --run-b RUN_ID [--workspace datos] [--tolerance 1e-9]
```

| Comando | Qué hace | Códigos de salida |
|---|---|---|
| `runs verify` | Revisa todas las carpetas publicadas de `datos/` (solo lee) | 0 nada alterado; **5** algo alterado |
| `runs verify --run-id` | La cadena de esa corrida | 0 completa; **5** un eslabón alterado; **3** falta o cambió un eslabón; 2 la corrida no existe |
| `runs compare` | Compara dos corridas y publica el reporte de réplica | **0** al registrarlo, sea `equivalent` o `different` (hay que leer `status`); 2 una corrida no existe, no es exitosa o es la misma; 5 una corrida está alterada o el reporte ya existe |

Por la salida estándar va solo el JSON (con `status` y `exit_code`); por la de error, un resumen para la persona: los conteos y cada carpeta alterada, los eslabones de la cadena, o el veredicto con sus motivos. `--tolerance` acepta solo números mayores que cero y se usa como diferencia relativa y absoluta.

Los códigos siguen el diseño técnico: 5 = fallo de integridad, 3 = artefacto o dependencia faltante, y 0 incluye un resultado de dominio registrado.

## Verificación

**Pruebas.** 30 nuevas (25 sin SUMO y 5 de punta a punta con SUMO real). Suite completa: **1863 pasan, 11 saltadas**. Formato, lint, tipos y contratos sin observaciones.

- **Sin SUMO:** cada código de salida de la revisión y de la cadena, JSON solo en la salida estándar, resumen para la persona, espacio por defecto `datos`, corrida inexistente, veredicto `equivalent` y `different` con código 0, tolerancia que llega a la comparación, tolerancia inválida, corridas obligatorias, errores con su código.
- **De punta a punta:** espacio íntegro (0), espacio con una corrida alterada (5), cadena completa de una corrida preparada, réplica `equivalent` publicada y revisada después como íntegra, comparación con una corrida alterada (5, sin publicar nada).
- **Con el `datos/` real** (solo lectura): `runs verify` da código 0 (10 íntegras y 3 desconocidas); `runs verify --run-id` de una corrida de DEV00 da su cadena completa hasta la copia de originales.

**Mutaciones.** 16 cambios a propósito; 14 aplicables (2 no coincidían con el texto formateado y se omitieron; los mensajes que tocaban están cubiertos por pruebas). **14 de 14 detectadas.**

## Hallazgos de la inspección

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | **La interfaz importaba `Tolerance` directo de `simulacion`**, lo que ADR01 prohíbe. Lo detectó la prueba de arquitectura | La interfaz la toma de `app/replica.py` |
| 2 | Mostrar la cadena de una corrida no tenía comando; F0 solo nombraba dos | Se resolvió dentro de `runs verify` con `--run-id`, sin agregar un comando nuevo |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
