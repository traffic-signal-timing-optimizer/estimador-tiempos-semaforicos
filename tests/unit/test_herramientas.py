"""Herramientas cortas del sistema que usa la base (DEV31 F3)."""

import sys
from pathlib import Path

from semaforo.simulacion.herramientas import git_output, run_tool


def test_a_program_that_does_not_exist_gives_no_result() -> None:
    assert run_tool(["programa-que-no-existe-xyz"], timeout_s=5) is None


def test_a_tool_returns_its_code_and_what_it_wrote() -> None:
    result = run_tool([sys.executable, "-c", "print('hola'); raise SystemExit(3)"], timeout_s=30)
    assert result is not None
    assert (result.returncode, result.stdout.strip()) == (3, "hola")


def test_a_tool_that_takes_too_long_gives_no_result() -> None:
    assert run_tool([sys.executable, "-c", "import time; time.sleep(5)"], timeout_s=0.5) is None


def test_git_outside_a_repository_says_nothing(tmp_path: Path) -> None:
    assert git_output(tmp_path, "rev-parse", "HEAD") is None
