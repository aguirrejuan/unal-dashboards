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
const nodo = id => ({
  id,
  set innerHTML(v){}, get innerHTML(){ return ''; },
  set textContent(v){}, get textContent(){ return ''; },
  querySelectorAll: () => [], querySelector: () => null,
  insertAdjacentHTML(){}, classList:{add(){},remove(){}},
  addEventListener(){}, value:'', set oninput(f){}, set onclick(f){},
});
global.document = {getElementById: id => (cache[id] ||= nodo(id)),
                   documentElement:{}, querySelectorAll: () => []};
global.getComputedStyle = () => ({getPropertyValue: () => '#000'});
global.CSS = {escape: s => s};

const graficos = [];
global.Plotly = {newPlot: (el, data) => graficos.push({
  el, series: data.length,
  puntos: data.reduce((s, t) => s + (t.x ? t.x.length : 0), 0),
})};

const comun = fs.readFileSync(SITIO + '/comun.js', 'utf8');
const html = fs.readFileSync(SITIO + '/' + PAGINA, 'utf8');
const guion = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');

new Function(comun + '\n' + guion)();
console.log(JSON.stringify(graficos));
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


def test_el_panorama_dibuja_todos_sus_graficos():
    graficos = {g["el"]: g for g in _ejecutar("index.html")}
    assert set(graficos) == {"embudo", "compromiso", "etc", "dinero", "cuartil", "corpus"}
    assert all(g["puntos"] > 0 for g in graficos.values()), "algún gráfico quedó vacío"


def test_la_pagina_de_procedencia_carga():
    _ejecutar("procedencia.html")


def test_el_grafico_de_etc_no_cuenta_dos_veces():
    """The per-sede posts and the AGREGADO totals share a measure name, so a
    filter on the measure alone doubles every figure and invents an extra bar."""
    carga = json.loads((SITIO / "datos.js").read_text(encoding="utf-8")
                       .removeprefix("window.CARGA=").rstrip(";"))
    filas = [f for f in carga["datos"]["v_procedencia"]
             if f["origen"] == "cargo_creado" and f["medida"] == "cargos_creados"]
    assert len({f["unidad_id"] for f in filas}) == 10, "debería haber diez sedes"
    assert sum(f["valor"] for f in filas) == 394.5, "152 + 191,5 + 51"
