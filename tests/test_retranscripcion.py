"""The check that an extraction still matches the document it came from.

Only possible because `ubicacion` is a real address — a cell or a table
coordinate. That is exactly why a model must never touch a grid: an invented
cell reference would pass human review and fail nothing here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from pic_etl.load.loader import cargar_extracciones
from pic_etl.verify.invariants import retranscripcion

RAIZ = Path(__file__).resolve().parent.parent
CORPUS = RAIZ / "extracted"


@pytest.fixture
def cargado(poblado, extracciones):
    with poblado.begin() as conn:
        cargar_extracciones(conn, extracciones)
    return poblado


def test_una_extraccion_fiel_pasa(cargado):
    assert retranscripcion(cargado, CORPUS, RAIZ / "extractions") == []


def test_un_literal_alterado_falla(cargado):
    """Change one transcribed figure and the source stops agreeing."""
    with cargado.begin() as conn:
        conn.execute(text(
            "UPDATE asignacion SET monto_origen = '999' "
            "WHERE ubicacion = 'Registro_Proyectos_2025!N15'"))

    fallas = retranscripcion(cargado, CORPUS, RAIZ / "extractions")
    assert len(fallas) == 1
    assert "N15" in fallas[0].detalle


def test_una_ubicacion_inventada_falla(cargado):
    """A cell reference nobody can check is the failure mode this guards."""
    with cargado.begin() as conn:
        conn.execute(
            text("UPDATE declaracion SET ubicacion = :u WHERE declaracion_id = "
                 "(SELECT min(declaracion_id) FROM declaracion "
                 " WHERE documento_id = 'ANEXO1_PIC')"),
            {"u": "Tabla 99, fila 1 'inventada', col 'Compromiso'"},
        )

    fallas = retranscripcion(cargado, CORPUS, RAIZ / "extractions")
    assert any("ya no existe" in f.detalle for f in fallas)


def test_cubre_todas_las_tablas_de_hechos(cargado):
    """The check is driven by v_procedencia, not a hand-listed pair of tables.

    A shadowed loop variable once wrote 68 cobertura rows citing row numbers
    that did not exist, and a check scoped to `declaracion` and `asignacion`
    saw nothing wrong. This asserts the blind spot is closed.
    """
    with cargado.begin() as conn:
        conn.execute(text(
            "UPDATE cobertura_territorial SET ubicacion = "
            "\"Tabla 3, fila 258 'AMAZONÍA', col 'Estudiantes regulares de estos municipios'\" "
            "WHERE rowid = (SELECT min(rowid) FROM cobertura_territorial)"))

    fallas = retranscripcion(cargado, CORPUS, RAIZ / "extractions")
    assert any("fila 258" in f.detalle for f in fallas), \
        "la re-transcripción no cubre cobertura_territorial"


def test_toda_cita_resuelve_contra_un_snapshot(cargado):
    """Evidence, not just citation: every figure must point at a cell that
    exists in a rendered source table."""
    from html.parser import HTMLParser

    fuentes = RAIZ / "build" / "fuentes"
    if not fuentes.exists():
        pytest.skip("build/fuentes vacío; ejecute `pic-etl extract`")

    class Celdas(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ubicaciones: set[str] = set()

        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            if tag in ("td", "th") and "data-ubicacion" in d:
                self.ubicaciones.add(d["data-ubicacion"])

    disponibles: set[str] = set()
    for archivo in fuentes.rglob("*.html"):
        p = Celdas()
        p.feed(archivo.read_text(encoding="utf-8"))
        disponibles |= p.ubicaciones

    with cargado.connect() as c:
        citas = [r[0] for r in c.execute(text("SELECT DISTINCT ubicacion FROM v_procedencia"))]

    sin_resolver = [u for u in citas if u not in disponibles]
    assert not sin_resolver, f"{len(sin_resolver)} citas sin celda: {sin_resolver[:3]}"
