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


def test_dos_construcciones_producen_el_mismo_archivo(tmp_path, extracciones):
    """Byte for byte, not just row for row.

    `Table.indexes` is a set, so `create_all` once emitted two `CREATE INDEX`
    statements in whatever order it happened to iterate. The data was identical
    and the file was not — which is enough to make every rebuild a fresh 748 KB
    blob in git, and enough to weaken a claim of determinism that is otherwise
    true. The database is committed, so this has to hold.
    """
    import hashlib

    from pic_etl.load.loader import cargar_extracciones, cargar_referencia, materializar_grano
    from pic_etl.schema.dialect import crear_engine, crear_esquema

    def construir(destino):
        engine = crear_engine(destino, recrear=True)
        crear_esquema(engine)
        with engine.begin() as conn:
            cargar_referencia(conn)
            cargar_extracciones(conn, extracciones)
            materializar_grano(conn)
        engine.dispose()
        return hashlib.sha256(destino.read_bytes()).hexdigest()

    assert construir(tmp_path / "a.sqlite") == construir(tmp_path / "b.sqlite")
