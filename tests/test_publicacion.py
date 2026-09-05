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


def test_el_sitio_generado_lleva_los_datos_dentro():
    sitio = RAIZ / "site" / "index.html"
    if not sitio.exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    html = sitio.read_text(encoding="utf-8")
    carga = json.loads(
        re.search(r'id="carga" type="application/json">(.*?)</script>', html, re.S)[1]
    )
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
        re.search(r'id="presets-json" type="application/json">(.*?)</script>',
                  consulta.read_text(encoding="utf-8"), re.S)[1]
    )
    assert len(presets) >= 19
    assert all(p["sql"] and p["id"] for p in presets)
