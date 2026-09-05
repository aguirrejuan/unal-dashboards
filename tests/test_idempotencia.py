"""L2 / I11 — re-running a load produces no new rows.

v1 had no natural key anywhere: a second run doubled the corpus and every
invariant still passed. This is the test that would have caught it.
"""

from __future__ import annotations

from sqlalchemy import func, select

from pic_etl.load.loader import cargar_extracciones, cargar_referencia
from pic_etl.schema import tables as T


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
