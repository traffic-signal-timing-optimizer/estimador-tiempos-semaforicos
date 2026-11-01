"""Medidas del equipo y de un proceso hijo (DEV07 F2, decisiones D6 y D19)."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from semaforo.simulacion import resources
from semaforo.simulacion.resources import (
    MemoryProbe,
    available_memory_bytes,
    free_disk_bytes,
    kib_field,
)

PYTHON = str(getattr(sys, "_base_executable", sys.executable))  # el real, no el lanzador
MIB = 1024 * 1024

MEMINFO = """MemTotal:       16000000 kB
MemFree:          500000 kB
MemAvailable:    9000000 kB
Buffers:           10000 kB
"""
STATUS = """Name:\tsumo
VmPeak:\t  300000 kB
VmHWM:\t   120000 kB
VmRSS:\t    90000 kB
"""


def test_the_free_disk_of_an_existing_folder_is_positive(tmp_path: Path) -> None:
    assert free_disk_bytes(tmp_path) > 0


def test_the_free_disk_of_a_folder_that_does_not_exist_uses_its_parent(tmp_path: Path) -> None:
    assert free_disk_bytes(tmp_path / "a" / "b" / "c") == pytest.approx(
        free_disk_bytes(tmp_path), rel=0.01
    )


def test_the_available_memory_of_this_computer_is_a_plausible_number() -> None:
    available = available_memory_bytes()
    assert available is not None
    assert 10 * MIB < available < 10**14


def test_a_line_of_proc_is_read_in_bytes() -> None:
    assert kib_field(MEMINFO, "MemAvailable") == 9_000_000 * 1024
    assert kib_field(STATUS, "VmHWM") == 120_000 * 1024


@pytest.mark.parametrize("name", ["Falta", "Mem", "MemAvail"])
def test_a_line_that_is_not_there_gives_none(name: str) -> None:
    assert kib_field(MEMINFO, name) is None


@pytest.mark.parametrize("text", ["MemAvailable: mucho kB", "MemAvailable:", "MemAvailable:   "])
def test_a_line_without_a_number_gives_none(text: str) -> None:
    assert kib_field(text, "MemAvailable") is None


def test_the_probe_measures_a_process_alive_and_after_it_ends(tmp_path: Path) -> None:
    script = tmp_path / "hijo.py"
    script.write_text(
        "import time\nmemory = bytearray(b'\\x01') * (100 * 1024 * 1024)\ntime.sleep(1.5)\n",
        encoding="utf-8",
    )
    process = subprocess.Popen([PYTHON, str(script)])  # noqa: S603
    probe = MemoryProbe(process.pid)
    try:
        time.sleep(1.0)
        alive = probe.peak_bytes()
        process.wait()
        after = probe.peak_bytes()
    finally:
        probe.close()
        probe.close()  # cerrar dos veces no hace daño
    assert alive is not None and alive > 90 * MIB
    assert after is not None and after >= alive


def test_the_probe_of_a_process_that_does_not_exist_gives_none() -> None:
    probe = MemoryProbe(2_147_000_000)
    try:
        assert probe.peak_bytes() is None
    finally:
        probe.close()


# --- otros sistemas: lo que no se puede medir se omite --------------------------------------


def test_without_proc_the_memory_cannot_be_measured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources.sys, "platform", "freebsd")
    monkeypatch.setattr(Path, "read_text", _missing)
    assert available_memory_bytes() is None
    probe = MemoryProbe(1)
    assert probe.peak_bytes() is None
    probe.close()


def test_with_proc_the_memory_is_read_and_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources.sys, "platform", "linux")
    texts = {"/proc/meminfo": MEMINFO, "/proc/7/status": STATUS}

    def fake_read(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
        key = self.as_posix()
        if key in texts:
            return texts[key]
        raise FileNotFoundError(key)

    monkeypatch.setattr(Path, "read_text", fake_read)
    assert available_memory_bytes() == 9_000_000 * 1024
    probe = MemoryProbe(7)
    assert probe.peak_bytes() == 120_000 * 1024
    texts.clear()  # el proceso terminó: /proc ya no existe, pero el máximo se recuerda
    assert probe.peak_bytes() == 120_000 * 1024


def _missing(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
    raise FileNotFoundError(self.as_posix())
