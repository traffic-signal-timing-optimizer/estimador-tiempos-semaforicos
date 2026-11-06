"""La FCD de la zona se publica comprimida (DEV31 F2): el 92 % del peso de una corrida."""

import gzip
import shutil
from pathlib import Path

import pytest

from semaforo.simulacion.runner import (
    FCD,
    FCD_GZ,
    SimulacionError,
    compress_fcd,
    fcd_file,
    summarize_outputs,
)
from semaforo.trazabilidad.hashing import sha256_file

STEPS = 300
FCD_TEXT = (
    "<fcd-export>"
    + "".join(
        f'<timestep time="{second}.00"><vehicle id="a{second % 7}" speed="0.00" lane="demo_N_0"/>'
        "</timestep>"
        for second in range(STEPS)
    )
    + "</fcd-export>"
)

STATISTICS = """<statistics>
    <vehicles loaded="1" inserted="1" running="0" waiting="0"/>
    <teleports total="0" jam="0" yield="0" wrongLane="0"/>
</statistics>
"""
TRIPINFO = '<tripinfos><tripinfo id="a" depart="1.00" arrival="9.00"/></tripinfos>'


def outputs_with_fcd(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / FCD).write_text(FCD_TEXT, encoding="utf-8")
    return folder


def test_compressing_replaces_the_xml_with_a_gz_that_holds_the_same_text(tmp_path: Path) -> None:
    folder = outputs_with_fcd(tmp_path / "outputs")
    compress_fcd(folder)
    assert not (folder / FCD).exists()
    assert not (folder / f"{FCD_GZ}.part").exists()
    with gzip.open(folder / FCD_GZ, "rt", encoding="utf-8") as stream:
        assert stream.read() == FCD_TEXT


def test_the_compressed_fcd_is_much_smaller(tmp_path: Path) -> None:
    folder = outputs_with_fcd(tmp_path / "outputs")
    before = (folder / FCD).stat().st_size
    compress_fcd(folder)
    assert (folder / FCD_GZ).stat().st_size < before / 5


def test_the_same_fcd_always_gives_the_same_bytes(tmp_path: Path) -> None:
    """Sin fecha ni nombre dentro del archivo: la huella y la réplica no dependen de cuándo."""
    first = outputs_with_fcd(tmp_path / "uno")
    second = outputs_with_fcd(tmp_path / "dos")
    compress_fcd(first)
    compress_fcd(second)
    assert sha256_file(first / FCD_GZ) == sha256_file(second / FCD_GZ)
    assert (first / FCD_GZ).read_bytes()[4:8] == b"\x00\x00\x00\x00"  # fecha en cero


def test_without_a_fcd_there_is_nothing_to_do(tmp_path: Path) -> None:
    folder = tmp_path / "outputs"
    folder.mkdir()
    compress_fcd(folder)
    assert list(folder.iterdir()) == []


def test_if_it_cannot_be_written_the_original_is_kept_and_nothing_is_left_half_done(
    tmp_path: Path,
) -> None:
    folder = outputs_with_fcd(tmp_path / "outputs")
    (folder / FCD_GZ).mkdir()  # el destino ya es otra cosa: no se puede reemplazar
    with pytest.raises(OSError):  # el tipo exacto depende del sistema operativo
        compress_fcd(folder)
    assert (folder / FCD).read_text(encoding="utf-8") == FCD_TEXT
    assert not (folder / f"{FCD_GZ}.part").exists()


def test_if_the_original_cannot_be_deleted_the_fcd_is_not_left_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = outputs_with_fcd(tmp_path / "outputs")
    original = Path.unlink

    def refuse_the_xml(self: Path, missing_ok: bool = False) -> None:
        if self.name == FCD:
            raise PermissionError("no se puede borrar")
        original(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", refuse_the_xml)
    with pytest.raises(PermissionError):
        compress_fcd(folder)
    monkeypatch.undo()
    assert sorted(item.name for item in folder.iterdir()) == [FCD]
    assert (folder / FCD).read_text(encoding="utf-8") == FCD_TEXT


def test_the_reader_prefers_the_compressed_fcd_and_accepts_the_old_one(tmp_path: Path) -> None:
    folder = outputs_with_fcd(tmp_path / "outputs")
    assert fcd_file(folder) == folder / FCD
    shutil.copy(folder / FCD, folder / "otra.xml")
    compress_fcd(folder)
    assert fcd_file(folder) == folder / FCD_GZ
    (folder / FCD_GZ).unlink()
    assert fcd_file(folder) is None


def test_a_measured_run_with_a_compressed_fcd_is_coherent(tmp_path: Path) -> None:
    folder = outputs_with_fcd(tmp_path / "outputs")
    (folder / "statistics.xml").write_text(STATISTICS, encoding="utf-8")
    (folder / "tripinfo.xml").write_text(TRIPINFO, encoding="utf-8")
    compress_fcd(folder)
    summary = summarize_outputs(folder, None, measured=True)
    assert summary.trips_finished == 1


def test_a_measured_run_without_any_fcd_is_invalid(tmp_path: Path) -> None:
    folder = tmp_path / "outputs"
    folder.mkdir()
    (folder / "statistics.xml").write_text(STATISTICS, encoding="utf-8")
    (folder / "tripinfo.xml").write_text(TRIPINFO, encoding="utf-8")
    with pytest.raises(SimulacionError, match=r"falta fcd\.xml"):
        summarize_outputs(folder, None, measured=True)
