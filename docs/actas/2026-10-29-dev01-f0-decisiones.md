# Acta 2026-10-29: DEV01 · F0 (decisiones)

- **Tipo:** registro de fase del plan de DEV01 (HU01, HU14; P0, tamaño S). Dependencia: DEV00, cerrada el 2026-10-29.
- **Autorización:** el Product Owner autorizó F0 («Empecemos con F0») y respondió las cuatro decisiones de abajo.
- **Código:** F0 no cambia código.

## Qué ya existe (verificado el 2026-10-29)

| Pedido de DEV01 | Estado | Evidencia |
|---|---|---|
| `pyproject.toml` | hecho | commit `3aa2ded` |
| Lock de dependencias | hecho | `uv.lock` |
| Entorno | hecho | `.venv` con Python 3.12.3, creado con uv 0.13.2 |
| Estructura de módulos | hecha y aprobada | acta `2026-10-19-estructura-y-herramientas.md` |
| Comando `doctor` | **falta** | sin referencias en `src/` |
| Instalar desde cero y registrar versiones | **falta** | no hay registro previo |
| `uv` disponible en el equipo | **parcial** | ver «Instalación de uv» |
| Instrucciones de instalación en `README.md` | **faltan** | `README.md` solo tiene el título |

## Decisiones

**1. Instalar uv en el equipo: sí.** Sin uv no se puede hacer la verificación de instalar desde cero.

**2. Umbrales de espacio libre y RAM: solo informar.** `doctor` muestra el espacio libre y la RAM sin fallar por ellos. Solo falla si falta algo indispensable: Python 3.12, SUMO ejecutable con versión legible o una carpeta de trabajo donde se pueda escribir. Los umbrales los fija el piloto, como pide la documentación (DEC05 y «pendiente del piloto»).

**3. Versión de SUMO: 1.27.1, con aviso.** Si `sumo --version` informa otra versión, `doctor` avisa pero no falla. La versión esperada se lee de una constante, no de la configuración del caso.

**4. RAM sin dependencias nuevas.** Se lee con la biblioteca estándar de Python en Windows. No se agrega `psutil` ni otra biblioteca sin aprobación.

## Instalación de uv

- Se instaló con `python -m pip install --user uv`. El paquete trae uv 0.13.6.
- Verificado: `python -m uv --version` responde `uv 0.13.6`.
- **Pendiente para F4:** el ejecutable `uv.exe` no quedó en el PATH del usuario, así que por ahora se usa como `python -m uv`. Antes de la verificación de instalar desde cero hay que dejar `uv` en el PATH y documentarlo en `README.md`.
- El `.venv` existente se creó con uv 0.13.2. No se recrea en F0; F4 registra la versión usada.

## Alcance de las fases siguientes (propuesta, sin aprobar)

| Fase | Qué se hace |
|---|---|
| F1 | Núcleo del diagnóstico en `app/`, con su formato de resultado y pruebas sin SUMO |
| F2 | Comprobaciones del equipo (carpeta de trabajo, espacio, sistema, CPU, RAM) y de SUMO (ejecutable y versión) con las funciones que ya existen en `simulacion/`, para respetar ADR01 |
| F3 | `cli/doctor.py` conectado a `python -m semaforo doctor`, con JSON por la salida estándar y los mismos códigos de salida que `case receive` |
| F4 | `README.md` con la instalación en Windows; instalación desde cero en una carpeta temporal; `doctor` en el equipo del PO; registro de versiones |
| F5 | Acta de cierre de DEV01, actualización de `CONTEXTO.md` y commits |

Cada fase necesita su OK del Product Owner.

## Verificación

- Sin cambios en el código ni en la documentación del investigador (`documentacion/`).
- La carpeta de SUMO del Product Owner no se modificó.
