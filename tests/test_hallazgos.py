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


# --------------------------------------------------------------------- lecturas

def _lecturas(conexion):
    from sqlalchemy import text

    return conexion.execute(text(
        "SELECT lectura_id, cuerpo, consulta FROM lectura ORDER BY orden")
    ).mappings().all()


def _valores(conexion, lectura):
    from sqlalchemy import text

    return conexion.execute(text(lectura["consulta"])).one()


def test_toda_lectura_trae_una_consulta_que_corre(construido):
    """A takeaway states a number and names the query that produced it. If the
    query stops running, the page publishes a claim nobody can check."""
    with construido.connect() as c:
        lecturas = _lecturas(c)
        assert len(lecturas) >= 6
        for l in lecturas:
            valores = _valores(c, l)
            assert valores, f"{l['lectura_id']} no devuelve nada"
            assert all(v is not None for v in valores), \
                f"{l['lectura_id']} devuelve nulos"
            l["cuerpo"].format(*valores)   # levanta si faltan valores


def test_las_lecturas_siguen_diciendo_la_verdad(construido):
    """The point of writing them as queries: when the corpus grows and a reading
    stops holding, the build fails instead of publishing a stale claim.

    Change one of these deliberately when the data changes — do not loosen it.
    """
    esperado = {
        "L1": (1818, 1848, 1809, 1161, 648, 35.8),
        "L2": (1836, 579),
        "L3": (2025, 60.0),
        "L4": (3, "(0.586,0.649]"),
        "L5": (312, 428, 72.9),
        "L6": (8, 2, 8),
    }
    with construido.connect() as c:
        obtenido = {l["lectura_id"]: tuple(_valores(c, l)) for l in _lecturas(c)}
    assert obtenido == esperado


def test_la_caida_de_admision_a_matricula_es_la_mayor_del_embudo(construido):
    """L1 claims it is «la única pérdida grande de la cadena». That is an
    assertion about the shape of the funnel, not just about one number, and it
    is the sort of thing that quietly stops being true."""
    from sqlalchemy import text

    with construido.connect() as c:
        pasos = c.execute(text(
            "SELECT paso, valor FROM v_embudo WHERE grupo = 'FLUJO' "
            "UNION ALL SELECT paso, valor FROM v_embudo WHERE paso = 4 "
            "ORDER BY paso")).all()
    caidas = [pasos[i - 1][1] - pasos[i][1] for i in range(1, len(pasos))]
    assert max(caidas) == pasos[-2][1] - pasos[-1][1], \
        "la mayor caída dejó de ser la de admitidos a matriculados"
    assert max(caidas) > 10 * max(abs(c) for c in caidas[:-1]), \
        "las otras variaciones dejaron de ser pequeñas frente a ella"
