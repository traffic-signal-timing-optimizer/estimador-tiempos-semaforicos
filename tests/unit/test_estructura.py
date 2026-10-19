"""Comprueba que el andamiaje del paquete coincide con la arquitectura de 01_Diseno_tecnico.md."""

import importlib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
PAQUETES = [
    "semaforo.app",
    "semaforo.cli",
    "semaforo.dominio",
    "semaforo.datos",
    "semaforo.caso",
    "semaforo.simulacion",
    "semaforo.referencias",
    "semaforo.aprendizaje",
    "semaforo.estimacion",
    "semaforo.evaluacion",
    "semaforo.trazabilidad",
]


@pytest.mark.parametrize("nombre", PAQUETES)
def test_paquete_existe_e_importa(nombre: str) -> None:
    modulo = importlib.import_module(nombre)
    assert modulo.__doc__, f"{nombre} debe documentar su responsabilidad"


def test_carpetas_de_pruebas_y_adr_existen() -> None:
    for carpeta in ["tests/unit", "tests/integration", "tests/e2e", "tests/security", "docs/adr"]:
        assert (RAIZ / carpeta).is_dir(), f"falta {carpeta}"


def test_solo_simulacion_importa_sumo_o_procesos() -> None:
    # Regla inamovible: solo el módulo de simulación accede a SUMO, TraCI y procesos.
    prohibidos = ("traci", "sumolib", "subprocess")
    fuentes = RAIZ / "src" / "semaforo"
    infractores: list[str] = []
    for archivo in fuentes.rglob("*.py"):
        if "simulacion" in archivo.relative_to(fuentes).parts:
            continue
        texto = archivo.read_text(encoding="utf-8")
        for nombre in prohibidos:
            if f"import {nombre}" in texto or f"from {nombre}" in texto:
                infractores.append(f"{archivo.relative_to(RAIZ)}: {nombre}")
    assert not infractores, "\n".join(infractores)
