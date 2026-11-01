"""Un espacio de trabajo completo y sintético para las pruebas de trazabilidad (DEV08).

Arma ``datos/`` con un caso, su programa derivado y una carpeta de entradas publicada, en las
mismas carpetas que usa la herramienta, para que una corrida se pueda seguir hacia atrás.
"""

import os
import shutil
import stat
from pathlib import Path

from prepared_inputs import MOMENT, request_for
from semaforo.app.integrity import CASES, INPUT_FOLDERS, PROGRAMS
from semaforo.simulacion.prepare import publish_inputs


def build_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Espacio de trabajo y su carpeta de entradas publicada."""
    workspace = tmp_path / "datos"
    request = request_for(tmp_path)
    case = request.case
    case_dir = workspace / CASES / case.case_id
    case_dir.mkdir(parents=True)
    (case_dir / "case.json").write_text(case.model_dump_json(indent=2), encoding="utf-8")
    for network in request.case_dir.iterdir():
        shutil.copyfile(network, case_dir / network.name)
    programs = workspace / PROGRAMS / case.case_id
    programs.mkdir(parents=True)
    shutil.copytree(request.program_dir, programs / request.program_dir.name)
    inputs = publish_inputs(workspace / INPUT_FOLDERS, request, MOMENT)
    return workspace, inputs


def writable(path: Path) -> Path:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    return path


def tamper(path: Path) -> None:
    """Cambia un archivo publicado (de solo lectura) agregándole un comentario al final."""
    writable(path).write_bytes(path.read_bytes() + b"\n<!-- cambio -->\n")
