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
    "v_compromiso_ciclo", "v_dinero_fuente", "v_presupuesto", "v_etapas",
    "v_etapa_documento", "v_ciclo",
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
        # Pre-shaped for the coverage chart: pivoting in SQL keeps the page from
        # having to know how the two admission routes relate.
        "cuartiles": _cuartiles(engine),
        "esquema": esquema(engine),
        # The corpus is published under site/corpus/, so a stored path becomes a
        # link by dropping the directory it was read from.
        "raiz_corpus": corpus.name,
    }
    # Split, rather than inlined into each page: the payload is the same for
    # both and a browser should fetch it once. The rendered source tables are
    # the bulk of it and only the provenance page needs them, so they ship
    # separately and the panorama stays light.
    fuentes = carga.pop("fuentes")
    (destino / "datos.js").write_text(
        "window.CARGA=" + json.dumps(carga, ensure_ascii=False, default=str) + ";",
        encoding="utf-8")
    (destino / "fuentes.js").write_text(
        "window.FUENTES=" + json.dumps(fuentes, ensure_ascii=False) + ";",
        encoding="utf-8")

    paginas = ("index.html", "proceso.html", "procedencia.html", "esquema.html",
               "documento.html")
    for pagina in paginas:
        (destino / pagina).write_text(_leer_plantilla(pagina), encoding="utf-8")
    (destino / "consulta.html").write_text(
        _consulta(datos["v_hallazgos"]), encoding="utf-8")

    # Shared assets: one stylesheet and one helper module across every page, so
    # they read as one document rather than five.
    for recurso in ("estilo.css", "comun.js"):
        shutil.copy2(PLANTILLAS / recurso, destino / recurso)

    # The escudo, if a person has been given the right to publish it. Nothing
    # here fabricates the mark: the slot stays empty and the masthead falls back
    # to type, which is what the page has always shown.
    marca = PLANTILLAS / "marca"
    if marca.is_dir():
        shutil.copytree(marca, destino / "marca", dirs_exist_ok=True)

    shutil.copy2(db, destino / "pic.sqlite")
    corpus_destino = destino / "corpus"
    if corpus_destino.exists():
        shutil.rmtree(corpus_destino)
    shutil.copytree(corpus, corpus_destino)

    return {
        "paginas": len(paginas) + 1,
        "vistas": len(datos),
        "filas": sum(len(v) for v in datos.values()),
        "fuentes": len(instantaneas),
    }


def _leer_plantilla(nombre: str) -> str:
    """The page, with the icon sprite inlined.

    Inlined rather than fetched: an icon in the navigation that arrives after
    the first paint is a flicker, and one sprite per page costs less than a
    request that blocks it.
    """
    html = (PLANTILLAS / nombre).read_text(encoding="utf-8")
    sprite = (PLANTILLAS / "iconos.svg").read_text(encoding="utf-8")
    # Drop the guidance comment from what ships; it belongs in the repository.
    cuerpo = sprite[sprite.index("<svg "):]
    html = html.replace("<!--ICONOS-->", cuerpo.strip())

    # The escudo is emitted only when the file is present. An `onerror` handler
    # would hide it just as well, but it would also put a 404 in every visitor's
    # console for a mark the site was never given.
    escudo = PLANTILLAS / "marca" / "escudo.svg"
    return html.replace(
        "<!--ESCUDO-->",
        '<img class="escudo" src="marca/escudo.svg" alt="Universidad Nacional '
        'de Colombia">' if escudo.exists() else "")


# The layers of docs/pic-data-model-v2.md, so the schema page groups tables the
# way the specification talks about them rather than alphabetically.
_CAPAS = {
    "declaracion": "Declaraciones", "es_agregado_de": "Declaraciones",
    "declaracion_alcance": "Declaraciones", "declaracion_disposicion": "Declaraciones",
    "disposicion_grano": "Declaraciones", "criterio_cumplimiento": "Declaraciones",
    "proyecto": "Estructura", "proyecto_etapa": "Estructura", "compromiso": "Estructura",
    "cargo_creado": "Estructura", "cargo_provisto": "Estructura",
    "cobertura_territorial": "Estructura", "arrastre": "Estructura",
    "asignacion": "Estructura", "presupuesto_rubro": "Estructura",
    "documento": "Documentos", "documento_cita": "Documentos",
    "documento_ciclo": "Documentos", "radicado": "Documentos",
    "radicado_documento": "Documentos",
    "hallazgo": "Registro",
    "unidad_academica": "Dimensiones", "unidad_rollup": "Dimensiones",
    "unidad_alias": "Dimensiones",
}


def esquema(engine: Engine) -> dict:
    """The schema, as data: tables, columns, keys and how they connect.

    Read from the same MetaData the database is built from, so the page cannot
    drift from what was actually created.
    """
    from pic_etl.schema.tables import metadata

    with engine.connect() as c:
        filas = {
            t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar()
            for t in metadata.tables
        }

    entrantes: dict[str, set[str]] = {t: set() for t in metadata.tables}
    for tabla in metadata.tables.values():
        for fk in tabla.foreign_keys:
            destino = fk.column.table.name
            if destino != tabla.name:
                entrantes.setdefault(destino, set()).add(tabla.name)

    tablas = []
    for nombre, tabla in sorted(metadata.tables.items()):
        columnas = []
        for col in tabla.columns:
            fk = next(iter(col.foreign_keys), None)
            columnas.append({
                "nombre": col.name,
                "tipo": str(col.type).replace("VARCHAR", "TEXT"),
                "nulo": bool(col.nullable),
                "pk": bool(col.primary_key),
                "fk": fk.target_fullname if fk else None,
            })
        salientes = sorted({
            fk.column.table.name for fk in tabla.foreign_keys
            if fk.column.table.name != nombre
        })
        tablas.append({
            "nombre": nombre,
            "capa": _CAPAS.get(nombre, "Dimensiones"),
            "filas": filas.get(nombre, 0),
            "columnas": columnas,
            "referencia_a": salientes,
            "referida_por": sorted(entrantes.get(nombre, set())),
            "auto": any(fk.column.table.name == nombre for fk in tabla.foreign_keys),
        })
    return {
        "tablas": tablas,
        "total_columnas": sum(len(t["columnas"]) for t in tablas),
        "total_fks": sum(len(t["referencia_a"]) for t in tablas),
    }


def _cuartiles(engine: Engine) -> list[dict]:
    """Coverage by priority quartile and admission route.

    Every band is returned, including the one with no facts: a dimension member
    that never appears is not a measured zero, and a chart that silently omits
    it says the wrong thing.
    """
    with engine.connect() as c:
        return [dict(r) for r in c.execute(text("""
            SELECT q.cuartil_id, q.notacion, q.observado,
                   COALESCE(SUM(CASE WHEN ct.via_id='PEAMA'   THEN ct.estudiantes END), 0) AS peama,
                   COALESCE(SUM(CASE WHEN ct.via_id='REGULAR' THEN ct.estudiantes END), 0) AS regular
            FROM   cuartil_prioridad q
            LEFT   JOIN cobertura_territorial ct ON ct.cuartil_id = q.cuartil_id
            GROUP  BY q.cuartil_id, q.notacion, q.observado
            ORDER  BY q.cuartil_id
        """)).mappings()]


def _consulta(hallazgos: list[dict]) -> str:
    presets = [
        {"id": h["hallazgo_id"], "titulo": h["titulo"], "sql": h["verificacion"]}
        for h in hallazgos if h.get("verificacion")
    ]
    return _leer_plantilla("consulta.html").replace(
        "/*__PRESETS__*/", json.dumps(presets, ensure_ascii=False)
    )
