"""L2 / I11 — re-running a load produces no new rows.

v1 had no natural key anywhere: a second run doubled the corpus and every
invariant still passed. This is the test that would have caught it.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from pic_etl.load.loader import cargar_extracciones, cargar_referencia
from pic_etl.schema import tables as T

RAIZ = Path(__file__).resolve().parent.parent


def _conteos(engine):
    with engine.connect() as c:
        return {
            t.name: c.execute(select(func.count()).select_from(t)).scalar()
            for t in T.metadata.sorted_tables
        }


def test_referencia_es_idempotente(engine):
    with engine.begin() as conn:
        cargar_referencia(conn)
    primera = _conteos(engine)

    with engine.begin() as conn:
        cargar_referencia(conn)
    assert _conteos(engine) == primera


def test_extracciones_son_idempotentes(poblado, extracciones):
    with poblado.begin() as conn:
        cargar_extracciones(conn, extracciones)
    primera = _conteos(poblado)
    assert primera["declaracion"] > 0, "la prueba no probaría nada sobre datos vacíos"

    with poblado.begin() as conn:
        cargar_extracciones(conn, extracciones)
    assert _conteos(poblado) == primera


def test_dos_construcciones_producen_el_mismo_archivo(tmp_path):
    """Byte for byte, and — this is the part that matters — across processes.

    `Table.indexes` is a set whose iteration order follows object identity, so
    it is stable within one interpreter and varies between them. An in-process
    version of this test passed while `pic-etl build` was still producing a
    different file on every invocation: it could not see the bug it was written
    for. Two subprocesses can.
    """
    import hashlib
    import subprocess
    import sys

    guion = (
        "from pic_etl.cli import main; import sys; "
        "sys.exit(main(['--out', sys.argv[1], 'build']))"
    )
    huellas = []
    for nombre in ("a.sqlite", "b.sqlite"):
        destino = tmp_path / nombre
        salida = subprocess.run([sys.executable, "-c", guion, str(destino)],
                                capture_output=True, text=True, cwd=RAIZ)
        assert salida.returncode == 0, salida.stderr[-2000:]
        huellas.append(hashlib.sha256(destino.read_bytes()).hexdigest())
    assert huellas[0] == huellas[1], "dos construcciones dan archivos distintos"
