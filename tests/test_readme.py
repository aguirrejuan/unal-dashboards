"""The README's numbers, checked against the database.

It claimed «2 procesados» and «242 cifras» long after twenty documents and 428
figures were loaded, and nothing could have caught it. A README is documentation
the way a caption is: it goes stale silently, and the only cure is to make the
claims checkable.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
README = RAIZ / "README.md"
BASE = RAIZ / "build" / "pic.sqlite"


@pytest.fixture(scope="module")
def texto() -> str:
    # Written «1 630» for a reader; compared as 1630.
    return README.read_text(encoding="utf-8").replace(" ", " ")


@pytest.fixture(scope="module")
def base():
    if not BASE.exists():
        pytest.skip("build/pic.sqlite ausente; ejecute `pic-etl build`")
    con = sqlite3.connect(BASE)
    yield lambda sql: con.execute(sql).fetchone()[0]
    con.close()


def _afirma(texto: str, patron: str) -> int:
    """The number the README states in the sentence matching `patron`."""
    m = re.search(patron, texto)
    assert m, f"el README ya no dice nada que encaje con {patron!r}"
    return int(m[1].replace(" ", "").replace(".", ""))


def test_las_cifras_del_readme_son_las_de_la_base(texto, base):
    assert _afirma(texto, r"([\d ]+) cifras, cada una rastreable") == \
        base("SELECT count(*) FROM v_procedencia")
    assert _afirma(texto, r"\*\*([\d ]+) procesados\*\*") == \
        base("SELECT count(*) FROM v_corpus WHERE avance = 'PROCESADO'")
    assert _afirma(texto, r"\*\*([\d ]+) leídos\*\*") == \
        base("SELECT count(*) FROM v_corpus WHERE avance = 'SIN_CIFRAS'")
    assert _afirma(texto, r"\*\*([\d ]+) citados\*\*") == \
        base("SELECT count(*) FROM v_corpus WHERE avance = 'AUSENTE'")
    assert _afirma(texto, r"De los ([\d ]+) documentos del registro") == \
        base("SELECT count(*) FROM v_corpus")


def test_el_esquema_que_anuncia_el_readme_es_el_real(texto, base):
    assert _afirma(texto, r"([\d ]+) tablas, \d+ vistas") == \
        base("SELECT count(*) FROM sqlite_master WHERE type = 'table'")
    assert _afirma(texto, r"\d+ tablas, ([\d ]+) vistas") == \
        base("SELECT count(*) FROM sqlite_master WHERE type = 'view'")
    assert _afirma(texto, r"Las ([\d ]+) tablas, sus columnas") == \
        base("SELECT count(*) FROM sqlite_master WHERE type = 'table'")

    tablas = [n for (n,) in sqlite3.connect(BASE).execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")]
    filas = sum(base(f'SELECT count(*) FROM "{t}"') for t in tablas)
    assert _afirma(texto, r"\d+ vistas, ([\d ]+) filas") == filas


def test_los_hallazgos_que_anuncia_el_readme_estan_en_el_registro(texto, base):
    assert _afirma(texto, r"([\d ]+) entradas en el registro") == \
        base("SELECT count(*) FROM hallazgo")
    assert _afirma(texto, r"([\d ]+) con una consulta que las demuestra") == \
        base("SELECT count(*) FROM hallazgo WHERE estado = 'VERIFICADO'")
    assert "Ocho de las diez etapas" in texto
    assert base("SELECT count(*) FROM v_etapas WHERE cifras > 0") == 8, \
        "el README dice «ocho de las diez etapas»"


def test_lo_que_el_readme_promete_del_sitio_existe(texto):
    sitio = RAIZ / "site"
    if not (sitio / "index.html").exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    for pagina in ("index", "proceso", "procedencia", "esquema", "consulta",
                   "documento"):
        assert (sitio / f"{pagina}.html").exists(), f"falta site/{pagina}.html"

    import json
    fuentes = json.loads((sitio / "fuentes.js").read_text(encoding="utf-8")
                         .removeprefix("window.FUENTES=").rstrip(";"))
    assert _afirma(texto, r"([\d ]+) tablas fuente reproducidas") == len(fuentes)
    assert texto.startswith("# PIC") and "Veintitrés archivos" in texto
    corpus = [p for p in (sitio / "corpus").rglob("*") if p.is_file()]
    assert len(corpus) == 23, "el README dice «veintitrés archivos»"


def test_los_comandos_del_readme_existen(texto):
    from pic_etl.cli import main

    ordenes = set(re.findall(r"pic-etl (\w+)", texto))
    with pytest.raises(SystemExit):
        main(["--help"])
    conocidos = {"extract", "build", "verify", "publish", "snapshots",
                 "transcribe", "review", "promote"}
    assert ordenes <= conocidos, f"el README inventa órdenes: {ordenes - conocidos}"
