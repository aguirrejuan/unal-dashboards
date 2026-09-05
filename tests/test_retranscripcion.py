"""The check that an extraction still matches the document it came from.

Only possible because `ubicacion` is a real address — a cell or a table
coordinate. That is exactly why a model must never touch a grid: an invented
cell reference would pass human review and fail nothing here.
"""

from __future__ import annotations

import html
import re
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
            # Any addressable element, not only table cells: a page of prose is
            # rendered as lines, and those carry citations too.
            d = dict(attrs)
            if "data-ubicacion" in d:
                self.ubicaciones.add(d["data-ubicacion"])

    disponibles: set[str] = set()
    for archivo in fuentes.rglob("*.html"):
        p = Celdas()
        p.feed(archivo.read_text(encoding="utf-8"))
        disponibles |= p.ubicaciones

    with cargado.connect() as c:
        citas = [(r[0], r[1]) for r in c.execute(text(
            "SELECT DISTINCT ubicacion, documento_id FROM v_procedencia"))]

    # A grid citation names one cell, so it must match exactly. A prose citation
    # names a verbatim phrase on a page, and the page is rendered as lines — so
    # the right relation there is containment, not equality.
    # Filenames are slugified (`p.2` → `p_2`), and a considerando wraps across
    # several source lines, so the comparison is against the page's whole text.
    texto_por_pagina: dict[str, str] = {}
    for archivo in fuentes.rglob("p_*.html"):
        plano = re.sub(r"<[^>]+>", " ", archivo.read_text(encoding="utf-8"))
        plano = html.unescape(plano)
        clave = f"{archivo.parent.name}|{archivo.stem.replace('_', '.')}"
        texto_por_pagina[clave] = " ".join(plano.split())

    with cargado.connect() as c:
        transcritos = {r[0] for r in c.execute(text(
            "SELECT documento_id FROM documento WHERE soporte = 'TRANSCRITO'"))}

    sin_resolver = []
    for u, documento in citas:
        if u in disponibles or documento in transcritos:
            # A scanned page has no text to render as a snapshot; its evidence
            # is the page image, which the site links to directly.
            continue
        m = re.match(r"p\.(\d+), «(.+)»$", u)
        if m and " ".join(m[2].split()) in texto_por_pagina.get(
                f"{documento}|p.{m[1]}", ""):
            continue
        sin_resolver.append(u)

    assert not sin_resolver, f"{len(sin_resolver)} citas sin celda: {sin_resolver[:3]}"


def test_un_hash_de_fuente_desactualizado_falla(cargado, tmp_path):
    """The only guard the transcribed scans have, so it must actually run.

    It was declared in the contract and stored on every extraction, but nothing
    compared it against the file until a question about determinism exposed
    that the check did not exist.
    """
    from pic_etl.verify.invariants import fuentes_sin_cambios

    assert fuentes_sin_cambios(cargado, RAIZ / "extractions") == []

    # An extraction that describes a file the corpus no longer contains
    falso = tmp_path / "res_men_016468_2025.yaml"
    original = (RAIZ / "extractions" / "res_men_016468_2025.yaml").read_text(encoding="utf-8")
    falso.write_text(re.sub(r"fuente_sha256: '?[0-9a-f]{64}'?",
                            "fuente_sha256: '" + "0" * 64 + "'",
                            original), encoding="utf-8")

    fallas = fuentes_sin_cambios(cargado, tmp_path)
    assert len(fallas) == 1
    assert "el archivo cambió" in fallas[0].detalle


def test_los_escaneos_no_se_dan_por_comprobados(cargado):
    """A transcribed scan has no text layer, so its figures cannot be re-read.
    The suite must report that exposure rather than let `ok` imply otherwise."""
    from pic_etl.verify.invariants import cifras_sin_comprobacion_automatica

    limites = cifras_sin_comprobacion_automatica(cargado)
    assert limites, "los escaneos transcritos deben declararse como no comprobables"
    assert all("sin comprobación automática" in f.detalle for f in limites)
