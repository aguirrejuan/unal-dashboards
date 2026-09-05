"""The static site must carry the evidence chain intact.

Two silent failures are possible here and neither raises: a citation whose
container has no rendered source table, and a snapshot key that does not match
what the page looks up. Both leave the evidence panel empty while everything
else looks fine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from pic_etl.load.loader import cargar_extracciones, cargar_referencia, materializar_grano
from pic_etl.publish import recolectar

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def construido(engine, extracciones):
    with engine.begin() as conn:
        cargar_referencia(conn)
        cargar_extracciones(conn, extracciones)
        materializar_grano(conn)
    return engine


def test_las_vistas_publicadas_traen_filas(construido):
    datos = recolectar(construido)
    vacias = [v for v, filas in datos.items() if not filas]
    assert not vacias, f"vistas sin filas: {vacias}"


def test_toda_cifra_resuelve_a_su_tabla_fuente(construido):
    """The join the evidence panel makes: documento_id + contenedor."""
    indice = RAIZ / "build" / "fuentes" / "indice.json"
    if not indice.exists():
        pytest.skip("build/fuentes vacío; ejecute `pic-etl extract`")
    disponibles = set(json.loads(indice.read_text(encoding="utf-8")))

    with construido.connect() as c:
        # A transcribed scan is an image: there is no text to render as a
        # snapshot, so its evidence is the page itself and the site links to it.
        claves = {f"{r.documento_id}|{r.contenedor}" for r in c.execute(text("""
            SELECT p.documento_id, p.contenedor
            FROM v_procedencia p JOIN documento d ON d.documento_id = p.documento_id
            WHERE d.soporte <> 'TRANSCRITO'
        """))}

    faltan = claves - disponibles
    assert not faltan, f"contenedores citados sin instantánea: {faltan}"


def _carga() -> dict:
    """The payload the pages share, now a separate script so a browser fetches
    it once instead of parsing an identical copy inlined in each page."""
    datos = RAIZ / "site" / "datos.js"
    if not datos.exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    carga = json.loads(datos.read_text(encoding="utf-8")
                       .removeprefix("window.CARGA=").rstrip(";"))
    fuentes = json.loads((RAIZ / "site" / "fuentes.js").read_text(encoding="utf-8")
                         .removeprefix("window.FUENTES=").rstrip(";"))
    return {**carga, "fuentes": fuentes}


def test_las_cinco_paginas_existen_y_comparten_los_recursos():
    sitio = RAIZ / "site"
    if not sitio.exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    paginas = ("index.html", "proceso.html", "procedencia.html",
               "esquema.html", "consulta.html")
    for archivo in (*paginas, "estilo.css", "comun.js", "datos.js",
                    "fuentes.js", "pic.sqlite"):
        assert (sitio / archivo).exists(), f"falta {archivo}"
    # Every page must reach every other, or the nav is decoration.
    for pagina in paginas:
        html = (sitio / pagina).read_text(encoding="utf-8")
        for destino in paginas:
            assert f'href="{destino}"' in html, f"{pagina} no enlaza a {destino}"


def test_el_sitio_generado_lleva_los_datos_dentro():
    carga = _carga()
    assert carga["datos"]["v_procedencia"], "sin cifras rastreables"
    assert carga["fuentes"], "sin tablas fuente"
    # Every citation in the payload must find its snapshot in the same payload —
    # except a transcribed scan, which is a page image with no text to render.
    claves = {
        f"{f['documento_id']}|{f['contenedor']}"
        for f in carga["datos"]["v_procedencia"]
        if f.get("soporte") != "TRANSCRITO"
    }
    assert not claves - set(carga["fuentes"])


def test_las_consultas_precargadas_son_las_pruebas_del_registro():
    consulta = RAIZ / "site" / "consulta.html"
    if not consulta.exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    presets = json.loads(
        re.search(r'id="carga" type="application/json">(.*?)</script>',
                  consulta.read_text(encoding="utf-8"), re.S)[1]
    )
    assert len(presets) >= 19
    assert all(p["sql"] and p["id"] for p in presets)


def test_el_esquema_publicado_coincide_con_el_real():
    """The schema page reads the same MetaData the database is built from, so it
    cannot drift — this asserts that, rather than trusting it."""
    from pic_etl.schema.tables import metadata

    esq = _carga()["esquema"]
    assert {t["nombre"] for t in esq["tablas"]} == set(metadata.tables)
    assert esq["total_columnas"] == sum(len(t.columns) for t in metadata.tables.values())

    decl = next(t for t in esq["tablas"] if t["nombre"] == "declaracion")
    grano = {c["nombre"]: c for c in decl["columnas"]}
    # P5: no nullable grain column, which is what makes uniqueness enforceable.
    for columna in ("ciclo_id", "unidad_id", "periodo_id", "poblacion_id", "medida_id"):
        assert grano[columna]["nulo"] is False, f"{columna} admite nulos"
        assert grano[columna]["fk"], f"{columna} debería ser clave foránea"


def test_los_documentos_del_corpus_se_pueden_enlazar():
    """A citation is only evidence if the reader can reach the document."""
    carga = _carga()
    con_archivo = [d for d in carga["datos"]["v_corpus"] if d["ruta_archivo"]]
    assert len(con_archivo) == 23, "los 23 documentos del corpus deben tener ruta"
    for d in con_archivo:
        destino = RAIZ / "site" / "corpus" / "/".join(d["ruta_archivo"].split("/")[1:])
        assert destino.exists(), f"el enlace de {d['documento_id']} no resuelve"
