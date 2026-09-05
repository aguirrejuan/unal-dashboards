"""The public site: the same views, rendered as static files.

Superset is a Flask application and GitHub Pages serves static files, so the two
cannot be one artifact. They are two renderings over one source of truth — these
views, this database file.

The panels are pre-rendered, so the page carries its argument even with
JavaScript disabled. `consulta.html` adds real SQL client-side over the same
`pic.sqlite` Superset reads.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

from sqlalchemy import Engine, text

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLAS = Path(__file__).resolve().parent / "plantillas"

VISTAS = (
    "v_corpus", "v_procedencia", "v_hallazgos", "v_embudo",
    "v_compromiso_ciclo", "v_dinero_fuente", "v_presupuesto",
)


def _filas(engine: Engine, vista: str) -> list[dict]:
    with engine.connect() as c:
        return [dict(r) for r in c.execute(text(f"SELECT * FROM {vista}")).mappings()]


def recolectar(engine: Engine) -> dict[str, list[dict]]:
    return {v: _filas(engine, v) for v in VISTAS}


def _snapshots(fuentes: Path) -> dict[str, str]:
    """Every rendered source table, keyed `documento|contenedor`, inlined so the
    evidence panel needs no second request.

    Keys come from the index `escribir` writes, never from the filenames: a
    filename is slugified (`Registro_Proyectos_2025` → `Registro_Proyectos_2025`
    is fine, but `Tabla 1` → `Tabla_1` is not reversible), and re-deriving the
    container from it silently breaks the join the evidence panel depends on.
    """
    indice_json = fuentes / "indice.json"
    if not indice_json.exists():
        raise SystemExit(
            f"falta {indice_json}; ejecute `pic-etl extract` antes de publicar"
        )
    indice = json.loads(indice_json.read_text(encoding="utf-8"))

    salida: dict[str, str] = {}
    for clave, ruta in indice.items():
        cuerpo = (fuentes.parent / ruta).read_text(encoding="utf-8")
        cuerpo = cuerpo[cuerpo.index("<table"):] if "<table" in cuerpo else cuerpo
        salida[clave] = cuerpo.strip()
    return salida


def publicar(engine: Engine, destino: Path, *, corpus: Path, fuentes: Path,
             db: Path) -> dict[str, int]:
    destino.mkdir(parents=True, exist_ok=True)
    datos = recolectar(engine)
    instantaneas = _snapshots(fuentes)

    carga = {
        "generado": date.today().isoformat(),
        "datos": datos,
        "fuentes": instantaneas,
    }
    (destino / "index.html").write_text(
        _pagina(carga), encoding="utf-8"
    )
    (destino / "consulta.html").write_text(
        _consulta(datos["v_hallazgos"]), encoding="utf-8"
    )

    shutil.copy2(db, destino / "pic.sqlite")
    corpus_destino = destino / "corpus"
    if corpus_destino.exists():
        shutil.rmtree(corpus_destino)
    shutil.copytree(corpus, corpus_destino)

    return {
        "vistas": len(datos),
        "filas": sum(len(v) for v in datos.values()),
        "fuentes": len(instantaneas),
    }


def _leer_plantilla(nombre: str) -> str:
    return (PLANTILLAS / nombre).read_text(encoding="utf-8")


def _pagina(carga: dict) -> str:
    return _leer_plantilla("index.html").replace(
        "/*__DATOS__*/", json.dumps(carga, ensure_ascii=False, default=str)
    )


def _consulta(hallazgos: list[dict]) -> str:
    presets = [
        {"id": h["hallazgo_id"], "titulo": h["titulo"], "sql": h["verificacion"]}
        for h in hallazgos if h.get("verificacion")
    ]
    return _leer_plantilla("consulta.html").replace(
        "/*__PRESETS__*/", json.dumps(presets, ensure_ascii=False)
    )
