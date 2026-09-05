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


FIRMA = PLANTILLAS / "marca" / "firma-unal.png"

# El archivo que sirve la propia Universidad en la cabecera de su sitio de
# identidad. Si el hash cambia, alguien sustituyó la marca por otra cosa.
FIRMA_SHA = "fcccf86c380a961554663a04d92e50c30d8de99750591c9b029a58496b432f01"


def test_la_firma_se_publica_tal_cual_o_no_se_publica():
    """A mark is the one thing on this page that may not be approximated. Either
    the file the University serves travels byte for byte, or the masthead falls
    back to type — never a redrawing, never a rescaled copy."""
    if not (SITIO / "index.html").exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    publicada = SITIO / "marca" / "firma-unal.png"
    for pagina in _paginas():
        html = pagina.read_text(encoding="utf-8")
        if FIRMA.exists():
            assert 'src="marca/firma-unal.png"' in html, \
                f"{pagina.name} no muestra la firma que sí está en el repositorio"
        else:
            assert "marca/" not in html, \
                f"{pagina.name} pide una marca que no está en el repositorio"
    if FIRMA.exists():
        import hashlib

        assert publicada.exists(), "la firma no llegó a site/"
        assert publicada.read_bytes() == FIRMA.read_bytes(), "la firma se alteró"
        assert hashlib.sha256(FIRMA.read_bytes()).hexdigest() == FIRMA_SHA, \
            "el archivo ya no es el que sirve la Universidad"


def test_la_firma_no_se_deforma():
    """Its own proportions, declared in the markup: a mark stretched by a
    stylesheet is a mark misused, and `width`/`height` make the ratio checkable
    instead of a matter of trust."""
    if not FIRMA.exists():
        pytest.skip("sin marca instalada")
    import struct

    ancho, alto = struct.unpack(">II", FIRMA.read_bytes()[16:24])
    if not (SITIO / "index.html").exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    html = (SITIO / "index.html").read_text(encoding="utf-8")
    m = re.search(r'class="firma"[^>]*width="(\d+)" height="(\d+)"', html)
    assert m, "la firma no declara sus dimensiones"
    assert (int(m[1]), int(m[2])) == (ancho, alto), \
        f"declara {m[1]}×{m[2]} y el archivo es {ancho}×{alto}"
    css = (SITIO / "estilo.css").read_text(encoding="utf-8")
    assert re.search(r"\.marca-sitio \.firma\{[^}]*width:auto", css), \
        "la altura fija sin `width:auto` deforma la marca"


def test_la_marca_blanca_va_sobre_fondo_de_color():
    """The firma exists in one colour. On white it is invisible; the masthead
    must be the coloured ground the University itself gives it."""
    if not FIRMA.exists():
        pytest.skip("sin marca instalada")
    css = (SITIO / "estilo.css").read_text(encoding="utf-8")
    barra = re.search(r"\.barra\{([^}]*)\}", css)
    assert barra and "var(--un-verde-oscuro)" in barra[1], \
        "la cabecera dejó de ser el fondo de color que la firma blanca necesita"
