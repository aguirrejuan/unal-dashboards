"""Every external asset the pages load must actually exist.

A pinned version that was never published returns 404, the library is undefined,
and the page dies at its first call — with no error visible on screen beyond a
blank panel. That is exactly what happened: `plotly.js@2.35.2` does not exist,
and the Node harness never noticed because it stubs Plotly.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLAS = RAIZ / "pic_etl" / "plantillas"

_URL = re.compile(r'<(?:script src|link[^>]*?href)="(https://[^"]+)"')


def _urls() -> list[tuple[str, str]]:
    return [
        (archivo.name, url)
        for archivo in sorted(PLANTILLAS.glob("*.html"))
        for url in _URL.findall(archivo.read_text(encoding="utf-8"))
        # A preconnect names a host and fetches nothing; HEAD on a bare origin
        # proves nothing about the asset the page actually loads.
        if urllib.parse.urlparse(url).path not in ("", "/")
    ]


def test_hay_recursos_externos_que_comprobar():
    assert _urls(), "la prueba no probaría nada sin URLs que revisar"


@pytest.mark.parametrize(("pagina", "url"), _urls())
def test_el_recurso_externo_existe(pagina: str, url: str):
    peticion = urllib.request.Request(url, method="HEAD",
                                      headers={"User-Agent": "pic-etl-tests"})
    try:
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            assert respuesta.status == 200
    except urllib.error.HTTPError as exc:
        pytest.fail(f"{pagina} carga {url} y devuelve {exc.code}")
    except urllib.error.URLError as exc:      # offline: not the page's fault
        pytest.skip(f"sin red: {exc.reason}")


def test_las_versiones_estan_fijadas():
    """An unpinned CDN URL changes under the page without warning.

    Google Fonts is the exception, and deliberately: its stylesheet is versioned
    by the `family` query, and pinning a file hash there would break the moment
    the service re-cuts the face.
    """
    sueltas = [(p, u) for p, u in _urls()
               if "fonts.googleapis.com" not in u
               and not re.search(r"/\d+\.\d+\.\d+/", u)]
    assert not sueltas, f"versiones sin fijar: {sueltas}"


def test_la_tipografia_declara_un_respaldo_local():
    """Ancízar is the institutional typeface and a registered mark: the page may
    prefer it when the reader has it installed, but must never ship it. What
    ships is an open humanist of near proportions, and the stack says so."""
    css = (PLANTILLAS / "estilo.css").read_text(encoding="utf-8")
    assert "Ancizar Sans" in css and "Source Sans 3" in css
    assert "@font-face" not in css, "no se distribuye la tipografía institucional"
