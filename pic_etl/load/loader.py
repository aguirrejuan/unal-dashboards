"""Reference data and extractions into the database.

Append-only and idempotent (L1, L2). Every insert is ON CONFLICT DO NOTHING
against a natural key, so re-running a load produces zero new rows — enforced by
the key, not by the loader being careful. v1 had no such key: a second run
doubled the corpus while every invariant still passed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from pic_etl.load.aliases import Resolutor
from pic_etl.load.rollup import calcular_closure, orden_por_profundidad
from pic_etl.models import Extraction
from pic_etl.schema import tables as T

REFERENCIA = Path(__file__).resolve().parent.parent / "reference"


def _leer(nombre: str) -> dict:
    return yaml.safe_load((REFERENCIA / nombre).read_text(encoding="utf-8")) or {}


def insertar(conn: Connection, tabla: Table, filas: Sequence[Mapping]) -> int:
    """Insert, ignoring rows already present (L2).

    Keys are levelled across the batch first. A YAML row may legitimately omit
    an optional column, but an executemany needs every row to carry the same
    binds — a missing key is not the same as an explicit NULL, and SQLAlchemy
    rejects the ragged batch rather than guessing.
    """
    if not filas:
        return 0
    columnas = {c.name: c for c in tabla.columns}
    presentes = {k for fila in filas for k in fila if k in columnas}

    # Fill a missing key with the column's own default, not None: a Python-side
    # default only fires when the key is absent, so levelling with None would
    # silently defeat it — `rubro.mapeable` would arrive NULL against a NOT NULL.
    def _falta(nombre: str):
        col = columnas[nombre]
        defecto = getattr(col, "default", None)
        return defecto.arg if defecto is not None and defecto.is_scalar else None

    nivelado = [
        {k: fila[k] if k in fila else _falta(k) for k in presentes} for fila in filas
    ]

    hacer = sqlite_insert if conn.dialect.name == "sqlite" else pg_insert
    conn.execute(hacer(tabla).on_conflict_do_nothing(), nivelado)
    return len(nivelado)


def sha256_de(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


# Reference tables in dependency order. `sorted_tables` cannot be used alone:
# unidad_academica and rubro are self-referential, so a parent must be inserted
# before its children or the foreign key fails on the first child.
_VOCABULARIOS = [
    "tipo_unidad", "grupo_sede", "estado_ciclo", "definicion_medida",
    "tipo_documento", "emisor", "estado_documento", "soporte",
    "direccion_radicado", "generacion_rubro", "confianza_mapeo", "tipo_flujo",
    "momento_presupuestal", "estado_etapa", "tipo_cargo", "tipo_declaracion",
    "vista", "etapa",
]


def cargar_referencia(conn: Connection) -> dict[str, int]:
    """Load every curated dimension. I9: a load never creates a member, so all
    of this must be in place before a single extraction is read."""
    cuenta: dict[str, int] = {}

    vocab = _leer("vocabularios.yaml")
    for nombre in _VOCABULARIOS:
        cuenta[nombre] = insertar(conn, T.metadata.tables[nombre], vocab[nombre])

    geo = _leer("geografia.yaml")
    cuenta["departamento"] = insertar(conn, T.departamento, geo["departamento"])
    cuenta["municipio"] = insertar(conn, T.municipio, geo["municipio"])

    unidades = _leer("unidad_academica.yaml")["unidad_academica"]
    cuenta["unidad_academica"] = insertar(
        conn, T.unidad_academica, orden_por_profundidad(unidades)
    )
    cuenta["unidad_rollup"] = insertar(conn, T.unidad_rollup, calcular_closure(unidades))

    alias = _leer("unidad_alias.yaml")["unidad_alias"]
    cuenta["unidad_alias"] = insertar(
        conn, T.unidad_alias, Resolutor(alias).filas_para_carga(alias)
    )

    ciclos = _leer("ciclo.yaml")
    cuenta["programa"] = insertar(conn, T.programa, ciclos["programa"])
    cuenta["periodo"] = insertar(conn, T.periodo, _leer("periodo.yaml")["periodo"])
    cuenta["ciclo"] = insertar(conn, T.ciclo, ciclos["ciclo"])
    cuenta["cuartil_prioridad"] = insertar(conn, T.cuartil_prioridad, ciclos["cuartil_prioridad"])
    cuenta["fuente_financiacion"] = insertar(conn, T.fuente_financiacion, ciclos["fuente_financiacion"])

    medidas = _leer("medida.yaml")
    cuenta["medida"] = insertar(conn, T.medida, medidas["medida"])
    permitidas = [
        {"programa_id": prog, "medida_id": m}
        for prog, ms in medidas["programa_medida_permitida"].items()
        for m in ms
    ]
    cuenta["programa_medida_permitida"] = insertar(conn, T.programa_medida_permitida, permitidas)
    cuenta["poblacion"] = insertar(conn, T.poblacion, _leer("poblacion.yaml")["poblacion"])

    docs = _leer("documento.yaml")
    cuenta["documento"] = insertar(conn, T.documento, docs["documento"])
    cuenta["documento_cita"] = insertar(conn, T.documento_cita, docs["documento_cita"])
    cuenta["via_admision"] = insertar(conn, T.via_admision, ciclos["via_admision"])

    cuenta["hallazgo"] = insertar(conn, T.hallazgo, _leer("hallazgos.yaml")["hallazgo"])
    cuenta["lectura"] = insertar(conn, T.lectura, [
        dict(fila, orden=i) for i, fila in enumerate(_leer("lecturas.yaml")["lectura"], 1)
    ])

    rubros = _leer("rubro.yaml")
    # LINEA before SUBLINEA — self-referential, same reason as unidad_academica.
    ordenados = sorted(rubros["rubro"], key=lambda r: r["nivel"] != "LINEA")
    cuenta["rubro"] = insertar(conn, T.rubro, ordenados)
    cuenta["rubro_mapping"] = insertar(conn, T.rubro_mapping, rubros["rubro_mapping"])

    return cuenta


def _resolutor(conn: Connection) -> Resolutor:
    filas = conn.execute(
        select(T.unidad_alias.c.ambito, T.unidad_alias.c.literal, T.unidad_alias.c.unidad_id)
    ).mappings().all()
    return Resolutor(filas)


# Rows within a bucket all come from one code path, so their keys match and an
# executemany is safe. Stripping None keys would make them ragged and SQLAlchemy
# would reject the batch — a nullable column needs an explicit None, not an
# absent key.


def cargar_extracciones(conn: Connection, extracciones: Iterable[Extraction]) -> dict[str, int]:
    """Insert every transcribed row, in foreign-key order.

    Unit references arrive as the literal the document used and are resolved
    here (L5). An unmatched spelling raises rather than inventing a member (I9).
    """
    resolutor = _resolutor(conn)
    cubos: dict[str, list[dict]] = {
        k: [] for k in
        ("proyecto", "compromiso", "cargo_creado", "asignacion",
         "cobertura_territorial", "presupuesto_rubro", "declaracion")
    }
    agregados: list[tuple[str, str, str, list[str]]] = []

    for ext in extracciones:
        doc = ext.documento_id
        u = lambda lit: resolutor.resolver(lit, documento_id=doc)  # noqa: E731

        for f in ext.filas:
            base = {"documento_id": doc, "ubicacion": f.ubicacion}
            if f.tipo == "proyecto":
                cubos["proyecto"].append({**base, "proyecto_id": f.proyecto_id,
                    "ciclo_id": f.ciclo_id, "unidad_id": u(f.unidad),
                    "numero": f.numero, "nombre": f.nombre,
                    "linea_id": f.linea_id, "sublinea_id": f.sublinea_id})
            elif f.tipo == "compromiso":
                unidad = u(f.unidad)
                cubos["compromiso"].append({**base,
                    "compromiso_id": f"{f.proyecto_id}|{unidad}|{int(f.es_rezago)}"
                                     f"|{f.ciclo_origen_id or ''}",
                    "proyecto_id": f.proyecto_id, "unidad_id": unidad,
                    "cupos": f.cupos, "es_rezago": f.es_rezago,
                    "ciclo_origen_id": f.ciclo_origen_id})
            elif f.tipo == "cargo_creado":
                cubos["cargo_creado"].append({**base, "unidad_id": u(f.unidad),
                    "tipo": f.tipo_cargo, "cantidad": f.cantidad,
                    "cantidad_origen": f.cantidad_origen,
                    "costo_total": f.costo_total})
            elif f.tipo == "asignacion":
                cubos["asignacion"].append({**base,
                    "asignacion_id": f.asignacion_id, "unidad_id": u(f.unidad),
                    "ciclo_id": f.ciclo_id, "vigencia": f.vigencia,
                    "fuente_id": f.fuente_id, "tipo_flujo": f.tipo_flujo,
                    "momento": f.momento, "recurso": f.recurso, "monto": f.monto,
                    "monto_origen": f.monto_origen})
            elif f.tipo == "presupuesto_rubro":
                cubos["presupuesto_rubro"].append({**base,
                    "presupuesto_id": f.presupuesto_id, "ciclo_id": f.ciclo_id,
                    "rubro_id": f.rubro_id, "unidad_id": u(f.unidad),
                    "concepto": f.concepto, "cantidad": f.cantidad,
                    "monto": f.monto, "monto_origen": f.monto_origen})
            elif f.tipo == "cobertura_territorial":
                cubos["cobertura_territorial"].append({**base,
                    "ciclo_id": f.ciclo_id, "unidad_id": u(f.unidad),
                    "periodo_id": f.periodo_id, "cuartil_id": f.cuartil_id,
                    "via_id": f.via_id, "estudiantes": f.estudiantes})
            elif f.tipo == "declaracion":
                cubos["declaracion"].append({**base,
                    "tipo_declaracion": f.tipo_declaracion, "medida_id": f.medida_id,
                    "ciclo_id": f.ciclo_id, "unidad_id": u(f.unidad),
                    "periodo_id": f.periodo_id, "poblacion_id": f.poblacion_id,
                    "valor": f.valor, "valor_origen": f.valor_origen,
                    "fecha_asercion": ext.fecha_asercion})
                if f.componentes:
                    agregados.append((doc, f.ubicacion, f.medida_id, f.componentes))

    cuenta = {}
    for nombre in ("proyecto", "compromiso", "cargo_creado", "asignacion",
                   "cobertura_territorial", "presupuesto_rubro", "declaracion"):
        cuenta[nombre] = insertar(conn, T.metadata.tables[nombre], cubos[nombre])

    cuenta["es_agregado_de"] = _enlazar_agregados(conn, agregados)
    return cuenta


def _enlazar_agregados(conn: Connection,
                       agregados: Sequence[tuple[str, str, str, list[str]]]) -> int:
    """Turn "this total covers those cells" into es_agregado_de rows.

    Declarations carry a surrogate key assigned at insert, so the link is
    resolved afterwards through (documento_id, ubicacion, medida_id) — the
    natural key a reviewer can actually see in the source.
    """
    if not agregados:
        return 0
    indice: dict[tuple[str, str, str], int] = {
        (r.documento_id, r.ubicacion, r.medida_id): r.declaracion_id
        for r in conn.execute(select(
            T.declaracion.c.declaracion_id, T.declaracion.c.documento_id,
            T.declaracion.c.ubicacion, T.declaracion.c.medida_id))
    }
    filas: list[dict] = []
    for doc, ubic, medida, componentes in agregados:
        agregado = indice.get((doc, ubic, medida))
        if agregado is None:
            continue
        for comp in componentes:
            cid = indice.get((doc, comp, medida))
            if cid is not None and cid != agregado:
                filas.append({"agregado_id": agregado, "componente_id": cid})
    return insertar(conn, T.es_agregado_de, filas)


def materializar_grano(conn: Connection) -> dict[str, int]:
    """Decide, per viewpoint, which declaration a grain resolves to (I1).

    Where a grain holds exactly one declaration there is nothing to adjudicate.
    Where it holds several, an explicit disposition must choose; absent one, the
    grain resolves to **nothing** and is reported. Picking arbitrarily would be
    the one thing this schema exists to prevent.
    """
    from collections import defaultdict

    descartadas = {
        (d["documento_id"], d["ubicacion"], d["medida_id"])
        for d in _leer("disposicion.yaml")["disposicion"]
        if d.get("descartada")
    }

    por_grano: dict[tuple, list] = defaultdict(list)
    for r in conn.execute(select(
        T.declaracion.c.declaracion_id, T.declaracion.c.medida_id,
        T.declaracion.c.ciclo_id, T.declaracion.c.unidad_id,
        T.declaracion.c.periodo_id, T.declaracion.c.documento_id,
        T.declaracion.c.ubicacion, T.declaracion.c.valor,
    )):
        if (r.documento_id, r.ubicacion, r.medida_id) in descartadas:
            continue
        por_grano[(r.medida_id, r.ciclo_id, r.unidad_id, r.periodo_id)].append(r)

    vistas = [v[0] for v in conn.execute(select(T.vista.c.vista_id))]
    filas: list[dict] = []
    concordantes = conflictos = 0

    for (medida, ciclo, unidad, periodo), candidatos in por_grano.items():
        if len(candidatos) > 1:
            # Several documents stating the *same* number is corroboration, not
            # ambiguity: 1 818 appears in Tabla 1, Tabla 2 and Tabla 4. Every
            # statement stays stored; the grain resolves to the lowest id so a
            # rebuild is deterministic.
            if len({c.valor for c in candidatos}) > 1:
                conflictos += 1
                continue
            concordantes += 1
        elegido = min(candidatos, key=lambda c: c.declaracion_id)
        for vista in vistas:
            filas.append({"vista_id": vista, "medida_id": medida, "ciclo_id": ciclo,
                          "unidad_id": unidad, "periodo_id": periodo,
                          "declaracion_id": elegido.declaracion_id})

    insertar(conn, T.disposicion_grano, filas)
    return {
        "granos": len(por_grano),
        "resueltos": len(filas) // max(len(vistas), 1),
        "concordantes": concordantes,
        "en_conflicto": conflictos,
    }
