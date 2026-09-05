"""Run each page's own script against the real payload.

Not a browser — no layout, no rendering — but it executes every line the pages
run on load, with the actual data, and fails on a bad reference or a wrong
filter. That is worth having: a chart of teaching posts was silently counting
administrative ones and summing every figure twice, and nothing else caught it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SITIO = RAIZ / "site"

ARNES = r"""
const fs = require('fs');
global.window = global;
require(SITIO + '/datos.js');
require(SITIO + '/fuentes.js');

const cache = {};
const escrito = {};
const nodo = id => ({
  id,
  set innerHTML(v){ escrito[id] = String(v); }, get innerHTML(){ return escrito[id] || ''; },
  set textContent(v){ escrito[id] = String(v); }, get textContent(){ return escrito[id] || ''; },
  querySelectorAll: () => [], querySelector: () => null,
  insertAdjacentHTML(){}, classList:{add(){},remove(){}},
  addEventListener(){}, value:'', set oninput(f){}, set onclick(f){},
  appendChild(){}, closest: () => null, scrollIntoView(){},
  getAttribute: () => null, setAttribute(){}, getBoundingClientRect: () => ({
    top:0, left:0, right:0, bottom:0, width:0, height:0}),
  style:{}, dataset:{}, hidden:true,
});
global.document = {getElementById: id => (cache[id] ||= nodo(id)),
                   documentElement:{}, querySelectorAll: () => [],
                   querySelector: () => null,
                   createElement: etiqueta => nodo('<' + etiqueta + '>'),
                   addEventListener(){}, body: nodo('body')};
global.addEventListener = () => {};
global.innerWidth = 1440;
global.getComputedStyle = () => ({getPropertyValue: () => '#000'});
global.CSS = {escape: s => s};

const graficos = [];
global.Plotly = {newPlot: (el, data) => graficos.push({
  el, series: data.length,
  puntos: data.reduce((s, t) => s + (t.x ? t.x.length
    : t.labels ? t.labels.length : t.link ? t.link.value.length : 0), 0),
})};
global.mermaid = {initialize(){}, render: async () => ({svg: '<svg/>'})};

const comun = fs.readFileSync(SITIO + '/comun.js', 'utf8');
const html = fs.readFileSync(SITIO + '/' + PAGINA, 'utf8');
const guion = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');

new Function(comun + '\n' + guion)();
console.log(JSON.stringify({graficos, escrito}));
"""


def _ejecutar(pagina: str) -> list[dict]:
    if shutil.which("node") is None:
        pytest.skip("node no está disponible")
    if not (SITIO / "datos.js").exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")

    guion = (f"const SITIO = {json.dumps(str(SITIO))};\n"
             f"const PAGINA = {json.dumps(pagina)};\n" + ARNES)
    salida = subprocess.run(["node", "-e", guion], capture_output=True, text=True)
    if salida.returncode != 0:
        pytest.fail(f"{pagina} falla al cargar:\n{salida.stderr.strip()[-1200:]}")
    return json.loads(salida.stdout.strip().splitlines()[-1])


def _graficos(pagina: str) -> list[dict]:
    return _ejecutar(pagina)["graficos"]


def _escrito(pagina: str) -> dict[str, str]:
    return _ejecutar(pagina)["escrito"]


def test_el_panorama_dibuja_todos_sus_graficos():
    graficos = {g["el"]: g for g in _graficos("index.html")}
    assert set(graficos) == {"embudo", "compromiso", "etc", "dinero", "cuartil",
                             "linea-tiempo", "pie-fuente", "pie-tipo", "corpus"}
    assert all(g["puntos"] > 0 for g in graficos.values()), "algún gráfico quedó vacío"


def test_el_proceso_dibuja_el_circuito_y_los_rubros():
    graficos = {g["el"]: g for g in _graficos("proceso.html")}
    assert set(graficos) == {"sankey", "rubros", "rubro-pie"}
    assert all(g["puntos"] > 0 for g in graficos.values())


@pytest.mark.parametrize("pagina", ["procedencia.html", "esquema.html"])
def test_las_paginas_sin_graficos_cargan(pagina: str):
    _ejecutar(pagina)


def test_el_grafico_de_etc_no_cuenta_dos_veces():
    """The per-sede posts and the AGREGADO totals share a measure name, so a
    filter on the measure alone doubles every figure and invents an extra bar."""
    if not (SITIO / "datos.js").exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    carga = json.loads((SITIO / "datos.js").read_text(encoding="utf-8")
                       .removeprefix("window.CARGA=").rstrip(";"))
    filas = [f for f in carga["datos"]["v_procedencia"]
             if f["origen"] == "cargo_creado" and f["medida"] == "cargos_creados"]
    assert len({f["unidad_id"] for f in filas}) == 10, "debería haber diez sedes"
    assert sum(f["valor"] for f in filas) == 394.5, "152 + 191,5 + 51"


def test_la_linea_de_tiempo_no_se_reduce_a_un_punto():
    """`documento.fecha` was populated for one document out of twenty-seven, so
    the timeline drew a single dot on an axis spanning one millisecond. It read
    as a broken chart, because it was one."""
    linea = next(g for g in _graficos("index.html") if g["el"] == "linea-tiempo")
    assert linea["puntos"] >= 20, "casi todos los documentos deben tener fecha"
    assert linea["series"] >= 4, "deben aparecer varios tipos de documento"


def test_cada_cifra_del_panorama_declara_sus_documentos():
    """Every reported number links to what asserts it. A KPI without a source is
    an assertion; the point of the site is that none of them are."""
    kpis = _escrito("index.html")["kpis"]
    tarjetas = kpis.split('<div class="kpi')
    assert len(tarjetas) == 7, "seis tarjetas"
    for tarjeta in tarjetas[1:]:
        assert 'class="fuente-kpi"' in tarjeta, "una cifra sin fuente"
        assert "documento.html?d=" in tarjeta, "el enlace no abre el visor"
        assert "data-ayuda=" in tarjeta, "una cifra sin explicación"


def test_el_proceso_atribuye_evidencia_a_las_etapas_documentadas():
    """`proyecto_etapa` is empty, so counting it marked all ten stages «sin
    evidencia» — which contradicted the rest of the site."""
    etapas = _escrito("proceso.html")["etapas"]
    assert etapas.count("sin evidencia") == 2, "sólo revisión y control están vacías"
    assert etapas.count("documento.html?d=") >= 20, \
        "cada etapa documentada enlaza sus fuentes"


def test_el_visor_muestra_los_documentos_que_el_navegador_no_puede_abrir():
    """A .docx link starts a download; nothing renders it. The viewer must offer
    what the pipeline pulled out instead — for Anexo 1, its fourteen tables."""
    if not (SITIO / "datos.js").exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    fuentes = json.loads((SITIO / "fuentes.js").read_text(encoding="utf-8")
                         .removeprefix("window.FUENTES=").rstrip(";"))
    ofimatica = {"ANEXO1_PIC": 14, "ANEXO2_PIC": 1,
                 "INFORME_MEN_2024_2025": 2, "INFORME_CUALITATIVO": 1}
    for doc, esperadas in ofimatica.items():
        tablas = [k for k in fuentes if k.startswith(doc + "|")]
        assert len(tablas) == esperadas, f"{doc}: {len(tablas)} tablas, se esperaban {esperadas}"


def test_ninguna_cita_enlaza_directamente_a_un_archivo_de_ofimatica():
    """Word and Excel files download rather than open, so a bare link to one
    looks broken. Citations go through the viewer; only the viewer itself and
    the scan panel offer the raw file."""
    for pagina in ("index.html", "proceso.html", "procedencia.html"):
        html = (SITIO / pagina).read_text(encoding="utf-8")
        assert "enlaceDoc(" not in html, f"{pagina} usa el enlace directo antiguo"
    comun = (SITIO / "comun.js").read_text(encoding="utf-8")
    assert "documento.html?d=" in comun, "enlaceDocId debe apuntar al visor"


def test_toda_explicacion_usa_el_globo_y_no_el_title_nativo():
    """The native tooltip waits a second, renders as a grey OS strip and gives
    no sign it exists. Every explanation on the site goes through `.globo`."""
    if not (SITIO / "datos.js").exists():
        pytest.skip("site/ vacío; ejecute `pic-etl publish`")
    for pagina in ("index.html", "proceso.html", "procedencia.html", "documento.html"):
        html = (SITIO / pagina).read_text(encoding="utf-8")
        assert 'title="${esc(' not in html, f"{pagina} todavía usa el title nativo"
    comun = (SITIO / "comun.js").read_text(encoding="utf-8")
    assert "class = 'globo'" in comun or "className = 'globo'" in comun
