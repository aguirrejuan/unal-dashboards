"""The icon set, against the rules it was built to.

Guía Web B5 of the Universidad Nacional specifies a 32 × 32 grid, lines only,
no fills, and a 1 px stroke. Those are checkable, and an icon that quietly drifts
off the grid is exactly the kind of thing nobody notices until a designer does.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLAS = RAIZ / "pic_etl" / "plantillas"
SPRITE = PLANTILLAS / "iconos.svg"
SITIO = RAIZ / "site"
SVG = "{http://www.w3.org/2000/svg}"


@pytest.fixture(scope="module")
def simbolos() -> dict[str, ET.Element]:
    raiz = ET.parse(SPRITE).getroot()
    return {s.get("id"): s for s in raiz.iter(f"{SVG}symbol")}


def test_el_conjunto_no_esta_vacio(simbolos):
    assert len(simbolos) >= 12


def test_todo_icono_vive_en_la_reticula_de_32(simbolos):
    for nombre, s in simbolos.items():
        assert s.get("viewBox") == "0 0 32 32", f"{nombre} se salió de la retícula"


def test_todo_icono_es_de_linea_y_sin_relleno(simbolos):
    """«sólo con líneas […] y sin rellenos». The one exception is an arrowhead,
    which is a filled triangle because a 1 px outline of one is a smudge."""
    for nombre, s in simbolos.items():
        for el in s.iter():
            relleno = el.get("fill")
            if relleno is not None:
                assert relleno in ("none", "currentColor"), \
                    f"{nombre} usa un color propio: {relleno}"
            grosor = el.get("stroke-width")
            if grosor is not None:
                assert grosor == "1", f"{nombre} usa un trazo de {grosor}"


def test_el_trazo_no_escala(simbolos):
    """A 1 px line is 1 px only if it refuses to scale with the viewBox; without
    this the grid's own unit changes with the rendered size."""
    for nombre, s in simbolos.items():
        grupos = [g for g in s.iter(f"{SVG}g")]
        assert grupos, f"{nombre} no agrupa su trazo"
        assert all(g.get("vector-effect") == "non-scaling-stroke" for g in grupos), \
            f"{nombre} deja escalar el trazo"


def _paginas() -> list[Path]:
    return sorted(SITIO.glob("*.html"))


def test_todo_icono_referido_existe():
    """A `<use>` pointing at nothing renders nothing, silently."""
    if not (SITIO / "index.html").exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    for pagina in _paginas():
        html = pagina.read_text(encoding="utf-8")
        definidos = set(re.findall(r'<symbol id="(ico-[\w-]+)"', html))
        usados = set(re.findall(r'href="#(ico-[\w-]+)"', html))
        assert usados, f"{pagina.name} no usa ningún ícono"
        assert usados <= definidos, \
            f"{pagina.name} referencia íconos inexistentes: {usados - definidos}"


def test_cada_tipo_de_documento_del_corpus_tiene_icono():
    """Seven types in the register; a type without a mark falls back to nothing,
    and a column of six icons and one gap reads as a bug."""
    if not (SITIO / "datos.js").exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    carga = json.loads((SITIO / "datos.js").read_text(encoding="utf-8")
                       .removeprefix("window.CARGA=").rstrip(";"))
    tipos = {d["tipo"] for d in carga["datos"]["v_corpus"]}
    comun = (SITIO / "comun.js").read_text(encoding="utf-8")
    mapeados = set(re.findall(r"(\w+):'[\w-]+'",
                              re.search(r"TIPO_ICONO = \{(.+?)\};", comun,
                                        re.S).group(1)))
    assert tipos <= mapeados, f"tipos sin ícono: {tipos - mapeados}"


def test_no_se_publica_una_marca_que_no_se_tiene():
    """The escudo is a registered mark whose use needs Unimedios' approval. The
    page must never ship a placeholder for it, nor request a file that is not
    there — a 404 in every visitor's console for a mark we were not given."""
    if not (SITIO / "index.html").exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    escudo = PLANTILLAS / "marca" / "escudo.svg"
    for pagina in _paginas():
        html = pagina.read_text(encoding="utf-8")
        if escudo.exists():
            assert 'src="marca/escudo.svg"' in html
        else:
            assert "marca/escudo" not in html, \
                f"{pagina.name} pide un escudo que no está en el repositorio"
