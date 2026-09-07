"""`pic-etl todo` — the whole deterministic chain in one command.

What matters is not that it runs, but that it refuses to finish when a step
fails. A pipeline that publishes anyway is worse than four separate commands,
because it looks like it checked.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
EXTRACCIONES = RAIZ / "extractions"


def _correr(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-c",
         "from pic_etl.cli import main; import sys; sys.exit(main(sys.argv[1:]))",
         *args],
        capture_output=True, text=True, cwd=cwd or RAIZ)


@pytest.mark.slow
def test_una_orden_reconstruye_todo(tmp_path):
    salida = _correr("--out", str(tmp_path / "pic.sqlite"), "todo")
    assert salida.returncode == 0, salida.stderr[-2000:]
    for paso in ("== extract", "== build", "== verify", "== publish"):
        assert paso in salida.stdout, f"no corrió {paso}"
    assert (tmp_path / "pic.sqlite").exists()


@pytest.mark.slow
def test_la_cadena_se_detiene_antes_de_publicar_si_verify_falla(tmp_path):
    """A source file that no longer matches its recorded hash means the
    extraction describes a document that no longer exists. Publishing that would
    put a figure on a public page with a citation that cannot be checked."""
    original = EXTRACCIONES / "res_men_016468_2025.yaml"
    guardado = original.read_text(encoding="utf-8")
    roto = guardado.replace(
        guardado.split("fuente_sha256: ")[1].split("\n")[0], "'" + "0" * 64 + "'")
    try:
        original.write_text(roto, encoding="utf-8")
        salida = _correr("--out", str(tmp_path / "pic.sqlite"), "todo")
    finally:
        original.write_text(guardado, encoding="utf-8")

    assert salida.returncode != 0, "la cadena terminó bien con verify roto"
    assert "fuentes_sin_cambios" in salida.stdout
    assert "se detiene" in salida.stdout
    assert "== publish" not in salida.stdout, "publicó pese a fallar verify"


def test_la_cadena_no_incluye_el_paso_que_necesita_red():
    """`todo` must run unattended on a machine with no credentials. Folding
    `transcribe` into it would also mean promoting a model's reading without a
    person, which is the one thing the YAML boundary exists to prevent."""
    fuente = (RAIZ / "pic_etl" / "cli.py").read_text(encoding="utf-8")
    cuerpo = fuente[fuente.index("def cmd_todo"):fuente.index("def cmd_verify")]
    assert "cmd_transcribe" not in cuerpo and "cmd_promote" not in cuerpo
    for paso in ("cmd_extract", "cmd_build", "cmd_verify", "cmd_publish"):
        assert paso in cuerpo, f"{paso} no está en la cadena"


def test_la_cadena_nombra_lo_que_espera_a_una_persona():
    """The honest part: a scan nobody has transcribed, or a proposal nobody has
    promoted, is work outstanding — and silence would read as completeness."""
    fuente = (RAIZ / "pic_etl" / "cli.py").read_text(encoding="utf-8")
    cuerpo = fuente[fuente.index("def cmd_todo"):fuente.index("def cmd_verify")]
    assert "propuesta sin promover" in cuerpo
    assert "escaneo sin transcripción" in cuerpo
