"""Every external asset the pages load must actually exist.

A pinned version that was never published returns 404, the library is undefined,
and the page dies at its first call — with no error visible on screen beyond a
blank panel. That is exactly what happened: `plotly.js@2.35.2` does not exist,
and the Node harness never noticed because it stubs Plotly.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLAS = RAIZ / "pic_etl" / "plantillas"

_URL = re.compile(r'<script src="(https://[^"]+)"')


def _urls() -> list[tuple[str, str]]:
    return [
        (archivo.name, url)
        for archivo in sorted(PLANTILLAS.glob("*.html"))
        for url in _URL.findall(archivo.read_text(encoding="utf-8"))
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
    """An unpinned CDN URL changes under the page without warning."""
    sueltas = [(p, u) for p, u in _urls()
               if not re.search(r"/\d+\.\d+\.\d+/", u)]
    assert not sueltas, f"versiones sin fijar: {sueltas}"
