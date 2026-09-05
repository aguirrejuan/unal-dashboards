"""Invariants I1–I15, plus the re-transcription check.

Each returns a list of failures. An empty list is a pass. These run against a
built database; the negative cases — proving each constraint *fires* — live in
tests/, because a suite that only ever sees good data proves nothing.
"""

from __future__ import annotations

import glob
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import openpyxl
import yaml
from sqlalchemy import Engine, text

from pic_etl.extract.docx_tablas import leer_tablas

# COP below a centavo is not a disagreement between documents: Anexo 2 stores
# IEEE doubles, so a Decimal sum of its components differs from its own stored
# total in the last few digits. Anything larger is a real discrepancy.
TOLERANCIA = Decimal("0.01")


@dataclass
class Falla:
    invariante: str
    detalle: str


def _q(engine: Engine, sql: str) -> list:
    with engine.connect() as c:
        return c.execute(text(sql)).fetchall()


def i1_un_preferido_por_grano(engine: Engine) -> list[Falla]:
    filas = _q(engine, """
        SELECT vista_id, medida_id, ciclo_id, unidad_id, periodo_id, count(*) n
        FROM disposicion_grano
        GROUP BY vista_id, medida_id, ciclo_id, unidad_id, periodo_id HAVING n > 1
    """)
    return [Falla("I1", f"{r.medida_id}/{r.unidad_id} resuelve a {r.n} declaraciones")
            for r in filas]


def i2_rollup_excluye_al_ancestro(engine: Engine) -> list[Falla]:
    """`WHERE sede_id = :x` includes the sede's own row; the closure with
    distancia > 0 does not. v1 returned 41 + 25 = 66 for Medellín."""
    filas = _q(engine, """
        SELECT ancestro_id FROM v_unidad_descendientes
        WHERE ancestro_id = descendiente_id
    """)
    return [Falla("I2", f"{r.ancestro_id} es descendiente de sí mismo") for r in filas]


def i3_stocks_no_suman_en_tiempo(engine: Engine) -> list[Falla]:
    filas = _q(engine, """
        SELECT medida_id FROM medida
        WHERE tipo_agregacion = 'STOCK' AND aditiva_tiempo <> 0
    """)
    return [Falla("I3", f"{r.medida_id} es STOCK y se declara aditiva en el tiempo")
            for r in filas]


def i5_toda_fila_cita_su_fuente(engine: Engine) -> list[Falla]:
    tablas = ("declaracion", "proyecto", "asignacion", "cobertura_territorial",
              "presupuesto_rubro", "cargo_creado", "compromiso")
    fallas = []
    for t in tablas:
        n = _q(engine, f"""
            SELECT count(*) n FROM {t}
            WHERE documento_id IS NULL OR trim(ubicacion) = ''
        """)[0].n
        if n:
            fallas.append(Falla("I5", f"{t}: {n} filas sin documento o ubicación"))
    return fallas


def i6_corpus_y_citados(engine: Engine) -> list[Falla]:
    filas = _q(engine, """
        SELECT documento_id, estado FROM documento
        WHERE (estado = 'EN_CORPUS' AND (ruta_archivo IS NULL OR soporte IS NULL))
           OR (estado <> 'EN_CORPUS' AND ruta_archivo IS NOT NULL)
    """)
    return [Falla("I6", f"{r.documento_id} ({r.estado}) incumple ruta/soporte")
            for r in filas]


def i9_claves_foraneas_activas(engine: Engine) -> list[Falla]:
    with engine.connect() as c:
        if engine.dialect.name == "sqlite":
            if not c.exec_driver_sql("PRAGMA foreign_keys").scalar():
                return [Falla("I9", "PRAGMA foreign_keys está en OFF")]
            rotas = c.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            return [Falla("I9", f"referencia rota en {r[0]}") for r in rotas]
    return []


def i10_sin_puente_no_hay_cruce(engine: Engine) -> list[Falla]:
    """rubro_mapping holds only real mappings. Empty means a cross-generation
    query returns nothing, which is the correct answer until someone curates it
    — an empty result is honest, a joined one would be invented."""
    filas = _q(engine, """
        SELECT m.rubro_origen FROM rubro_mapping m
        JOIN rubro a ON a.rubro_id = m.rubro_origen
        JOIN rubro b ON b.rubro_id = m.rubro_destino
        WHERE a.generacion = b.generacion
    """)
    return [Falla("I10", f"mapeo intra-generación en {r.rubro_origen}") for r in filas]


def i12_jerarquia_sin_ciclos(engine: Engine) -> list[Falla]:
    filas = _q(engine, """
        SELECT a.ancestro_id FROM unidad_rollup a
        JOIN unidad_rollup b
          ON b.ancestro_id = a.descendiente_id AND b.descendiente_id = a.ancestro_id
        WHERE a.distancia > 0 AND b.distancia > 0
    """)
    return [Falla("I12", f"ciclo en la jerarquía vía {r.ancestro_id}") for r in filas]


def i13_rubro_hereda_generacion(engine: Engine) -> list[Falla]:
    filas = _q(engine, """
        SELECT h.rubro_id FROM rubro h JOIN rubro p ON p.rubro_id = h.padre_id
        WHERE h.generacion <> p.generacion
    """)
    return [Falla("I13", f"{r.rubro_id} no comparte generación con su padre") for r in filas]


def i14_medida_permitida_por_programa(engine: Engine) -> list[Falla]:
    filas = _q(engine, """
        SELECT DISTINCT d.medida_id, c.programa_id
        FROM declaracion d
        JOIN ciclo c ON c.ciclo_id = d.ciclo_id
        LEFT JOIN programa_medida_permitida p
               ON p.programa_id = c.programa_id AND p.medida_id = d.medida_id
        WHERE p.medida_id IS NULL AND c.ciclo_id <> 'TODOS'
    """)
    return [Falla("I14", f"{r.medida_id} no está permitida en {r.programa_id}")
            for r in filas]


def i15_agregados_igualan_sus_partes(engine: Engine) -> list[Falla]:
    """A failure here is a finding about the corpus, not a bug in the loader."""
    filas = _q(engine, """
        SELECT a.declaracion_id, a.ubicacion, a.valor AS declarado,
               (SELECT group_concat(c.valor) FROM es_agregado_de e
                  JOIN declaracion c ON c.declaracion_id = e.componente_id
                 WHERE e.agregado_id = a.declaracion_id) AS partes
        FROM declaracion a
        WHERE a.tipo_declaracion = 'AGREGADO'
    """)
    fallas = []
    for r in filas:
        if not r.partes:
            continue
        suma = sum(Decimal(v) for v in r.partes.split(","))
        if abs(suma - Decimal(r.declarado)) > TOLERANCIA:
            fallas.append(Falla("I15",
                f"{r.ubicacion}: declarado {r.declarado}, partes suman {suma}"))
    return fallas


def retranscripcion(engine: Engine, corpus: Path, extracciones: Path) -> list[Falla]:
    """Re-open the sources and check every transcription still matches.

    Driven by `v_procedencia`, so it covers **every** fact table rather than the
    two it once knew about. That gap is not hypothetical: a shadowed loop
    variable once wrote 68 cobertura rows citing row numbers that did not exist,
    and a check scoped to two tables saw nothing wrong.

    Only possible because `ubicacion` is a real address — which is why a model
    must never touch a grid: an invented cell reference would pass review and
    fail nothing.
    """
    fallas: list[Falla] = []

    xlsx = glob.glob(str(corpus / "*/Pic_Info-2/Anexo 2*.xlsx"))
    docx = glob.glob(str(corpus / "*/Pic_Info-2/Anexo 1*.docx"))
    if not xlsx or not docx:
        return [Falla("retranscripción", "no encuentro las fuentes bajo el corpus")]

    hoja = openpyxl.load_workbook(xlsx[0], data_only=True)["Registro_Proyectos_2025"]
    tablas = {t.indice: t for t in leer_tablas(Path(docx[0]))}

    for r in _q(engine, "SELECT ubicacion, literal, documento_id FROM v_procedencia"):
        if "!" in r.ubicacion:                      # a spreadsheet cell
            celda = r.ubicacion.split("!", 1)[1]
            actual = hoja[celda].value
            if str(actual) != r.literal:
                fallas.append(Falla("retranscripción",
                    f"{r.ubicacion}: la hoja dice {actual!r}, la base {r.literal!r}"))
            continue

        # 'Tabla 7, fila 5 'Medellín', col 'Matriculados 2025-2''
        m = re.match(r"Tabla (\d+), fila (\d+) ", r.ubicacion)
        if not m:
            fallas.append(Falla("retranscripción", f"{r.ubicacion}: no sé leer esta cita"))
            continue
        indice, n_fila = int(m[1]), int(m[2])
        columna = r.ubicacion.rsplit("col ", 1)[1].strip("'")
        tabla = tablas.get(indice)
        if tabla is None or n_fila > len(tabla.datos):
            fallas.append(Falla("retranscripción", f"{r.ubicacion}: ya no existe"))
            continue
        fila = tabla.datos[n_fila - 1]
        try:
            col = tabla.encabezado.index(columna)
        except ValueError:
            fallas.append(Falla("retranscripción", f"{r.ubicacion}: columna ausente"))
            continue
        actual = fila[col] if col < len(fila) else None
        if actual != r.literal:
            fallas.append(Falla("retranscripción",
                f"{r.ubicacion}: el documento dice {actual!r}, la base {r.literal!r}"))
    return fallas


COMPROBACIONES: list[Callable] = [
    i1_un_preferido_por_grano, i2_rollup_excluye_al_ancestro,
    i3_stocks_no_suman_en_tiempo, i5_toda_fila_cita_su_fuente,
    i6_corpus_y_citados, i9_claves_foraneas_activas,
    i10_sin_puente_no_hay_cruce, i12_jerarquia_sin_ciclos,
    i13_rubro_hereda_generacion, i14_medida_permitida_por_programa,
    i15_agregados_igualan_sus_partes,
]


def ejecutar(engine: Engine, corpus: Path, extracciones: Path) -> list[Falla]:
    fallas: list[Falla] = []
    for comprobar in COMPROBACIONES:
        resultado = comprobar(engine)
        estado = f"{len(resultado)} fallas" if resultado else "ok"
        print(f"  {comprobar.__name__:38} {estado}")
        fallas += resultado

    r = retranscripcion(engine, corpus, extracciones)
    print(f"  {'retranscripción':38} {f'{len(r)} fallas' if r else 'ok'}")
    fallas += r

    if fallas:
        print()
        for f in fallas[:20]:
            print(f"  [{f.invariante}] {f.detalle}")
    return fallas
