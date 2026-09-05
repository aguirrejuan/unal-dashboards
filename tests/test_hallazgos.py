"""The register must not claim more than the data proves.

Each VERIFICADO finding carries a query. If the query stops running, or stops
returning what the finding says, the claim on the dashboard has gone stale.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from pic_etl.load.loader import cargar_extracciones, cargar_referencia, materializar_grano


@pytest.fixture
def construido(engine, extracciones):
    with engine.begin() as conn:
        cargar_referencia(conn)
        cargar_extracciones(conn, extracciones)
        materializar_grano(conn)
    return engine


def _hallazgos(engine, estado="VERIFICADO"):
    with engine.connect() as c:
        return c.execute(text(
            "SELECT hallazgo_id, titulo, verificacion FROM hallazgo "
            "WHERE estado = :e ORDER BY hallazgo_id"), {"e": estado}).mappings().all()


def test_toda_consulta_de_verificacion_corre(construido):
    filas = _hallazgos(construido)
    assert len(filas) >= 19, "la prueba no probaría nada con un registro vacío"
    with construido.connect() as c:
        for h in filas:
            resultado = c.execute(text(h["verificacion"])).fetchall()
            assert resultado, f"{h['hallazgo_id']} no devuelve nada"


def test_un_hallazgo_pendiente_no_puede_afirmar_prueba(construido):
    """A CHECK enforces it, but the register is hand-edited, so assert it too."""
    with construido.connect() as c:
        mal = c.execute(text(
            "SELECT hallazgo_id FROM hallazgo "
            "WHERE (estado = 'VERIFICADO') <> (verificacion IS NOT NULL)")).fetchall()
    assert mal == []


@pytest.mark.parametrize(("hallazgo", "esperado"), [
    ("E6", -689),        # Tabla 5 nets -689; the report headlines -1 168
    ("E1", 68505589464), # column N, which reconciles to nothing
    ("D6", 419),         # rezago seats projected across the nine sedes
    ("V2", 0),           # La Paz has no funding rows at all
])
def test_las_cifras_del_registro_siguen_siendo_ciertas(construido, hallazgo, esperado):
    with construido.connect() as c:
        sql = c.execute(text("SELECT verificacion FROM hallazgo WHERE hallazgo_id = :h"),
                        {"h": hallazgo}).scalar()
        assert c.execute(text(sql)).scalar() == esperado
