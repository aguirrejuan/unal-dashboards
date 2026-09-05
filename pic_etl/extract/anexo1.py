"""Anexo 1 → an extraction.

Deterministic: every value comes from a table cell whose coordinate is recorded,
so `verify` can re-open the document and check the transcription. No model is
involved, and none should be — an invented `ubicacion` would pass review and
fail nothing.

A table's own `Total` row never becomes a fact row. It is declared as an
AGREGADO naming its components, which turns "does the total equal the sum of its
parts?" into a runnable test (I15) rather than a double count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from pic_etl.extract.docx_tablas import Tabla, leer_tablas
from pic_etl.load.aliases import normalizar
from pic_etl.models import (
    CoberturaTerritorial,
    Declaracion,
    Extraction,
    PresupuestoRubro,
)

DOCUMENTO_ID = "ANEXO1_PIC"
_TOTAL = {"total", "totales"}


def es_total(literal: str) -> bool:
    return literal.strip().casefold() in _TOTAL


def parse_cop(texto: str) -> Decimal | None:
    """`$6.058.800.000` and `$ 610.851.317` → Decimal. Dots are thousands."""
    limpio = re.sub(r"[^\d,]", "", texto.replace(".", ""))
    if not limpio:
        return None
    return Decimal(limpio.replace(",", "."))


def parse_entero(texto: str) -> int | None:
    """`-38` → -38; `-`, `` and prose → None (not recorded, §7.2)."""
    t = texto.strip()
    if not re.fullmatch(r"-?\d+", t):
        return None
    return int(t)


def parse_periodo(texto: str) -> str:
    """`2024-1S`, `2025-2s` → `2024-1`, `2025-2`."""
    m = re.match(r"(\d{4})\s*-\s*(\d)", texto.strip())
    if not m:
        raise ValueError(f"no reconozco el periodo {texto!r}")
    return f"{m[1]}-{m[2]}"


@dataclass(frozen=True)
class Columna:
    indice: int
    medida_id: str
    periodo_id: str
    poblacion_id: str


# Which cycle each table speaks about, and what its measure columns mean. A
# cycle is labelled by its formulation year, never its result year, so this
# mapping is the one place that knowledge lives.
CUPOS = "PROYECTOS_APROBADOS"
TABLAS: dict[int, tuple[str, tuple[Columna, ...]]] = {
    1:  ("PIC_CO_2023", (Columna(1, "compromiso", "NA", "NA"),)),
    2:  ("PIC_CO_2023", (
            Columna(1, "compromiso", "NA", "NA"),
            Columna(2, "cupos_ofertados", "NA", "NA"),
            Columna(3, "matriculados", "2025-1", CUPOS),
            Columna(4, "rezago", "NA", CUPOS))),
    5:  ("PIC_CO_2023", ()),                    # per-period, handled separately
    # Col 3 is col 1 + col 2, so the three are different measures, not three
    # readings of one. Mapping them to a single `compromiso` made nine sedes
    # look like they held rival commitments.
    6:  ("PIC_CO_2024", (
            Columna(1, "compromiso", "NA", "NA"),
            Columna(2, "compromiso_rezago", "NA", "NA"),
            Columna(3, "compromiso_total", "NA", "NA"))),
    7:  ("PIC_CO_2024", (
            Columna(1, "compromiso", "NA", "NA"),
            Columna(2, "matriculados", "2025-2", CUPOS),
            Columna(3, "matriculados", "2026-1", CUPOS))),
    10: ("PIC_CO_2025", (Columna(1, "compromiso", "NA", "NA"),)),
    12: ("PIC_CO_2026", (Columna(1, "compromiso", "NA", "NA"),)),
}
CUARTIL = {3: "PIC_CO_2023", 8: "PIC_CO_2024"}
DINERO = {9: "PIC_CO_2024", 11: "PIC_CO_2025", 14: "PIC_ET_2026"}


def _medidas(tabla: Tabla, ciclo: str, columnas: tuple[Columna, ...]) -> list:
    filas: list = []
    for col in columnas:
        if col.indice >= len(tabla.encabezado):
            continue
        nombre_col = tabla.encabezado[col.indice]
        componentes: list[str] = []

        for n, fila in enumerate(tabla.datos, start=1):
            if len(fila) <= col.indice:
                continue
            etiqueta, bruto = fila[0], fila[col.indice]
            valor = parse_entero(bruto)
            if valor is None:            # '-' — not recorded, never a zero
                continue
            ubic = tabla.ubicacion(n, etiqueta, nombre_col)
            total = es_total(etiqueta)
            if not total:
                componentes.append(ubic)
            filas.append(
                Declaracion(
                    tipo="declaracion",
                    tipo_declaracion="AGREGADO" if total else "TRANSCRIPCION",
                    medida_id=col.medida_id,
                    ciclo_id=ciclo,
                    unidad=etiqueta,
                    periodo_id=col.periodo_id,
                    poblacion_id=col.poblacion_id,
                    valor=Decimal(valor),
                    valor_origen=bruto,
                    ubicacion=ubic,
                    componentes=componentes if total else [],
                )
            )
    return filas


def _balance(tabla: Tabla) -> list:
    """Tabla 4 — the same three figures as Tabla 2's total row, restated at PIC
    grain. Two declarations at one grain from two locations is not a bug: it is
    the case `disposicion_grano` exists to adjudicate (I1)."""
    columnas = (
        (1, "compromiso", "NA"),
        (2, "matriculados", "2025-1"),
        (3, "rezago", "NA"),
    )
    filas: list = []
    for n, fila in enumerate(tabla.datos, start=1):
        ciclo = f"PIC_CO_{fila[0].strip()}"
        for indice, medida, periodo in columnas:
            valor = parse_entero(fila[indice]) if len(fila) > indice else None
            if valor is None:
                continue
            filas.append(
                Declaracion(
                    tipo="declaracion",
                    medida_id=medida,
                    ciclo_id=ciclo,
                    unidad="UNAL_TOTAL",
                    periodo_id=periodo,
                    poblacion_id=CUPOS,
                    valor=Decimal(valor),
                    valor_origen=fila[indice],
                    ubicacion=tabla.ubicacion(n, fila[0], tabla.encabezado[indice]),
                )
            )
    return filas


def _periodos(tabla: Tabla, ciclo: str) -> list:
    """Tabla 5 — the four periods behind E6. They sum to −689; the report
    headlines −1 168, having dropped the two positive periods."""
    col = tabla.encabezado[1]
    return [
        Declaracion(
            tipo="declaracion",
            medida_id="aumento_matriculados",
            ciclo_id=ciclo,
            unidad="UNAL_TOTAL",
            periodo_id=parse_periodo(fila[0]),
            poblacion_id="MATRICULA_GLOBAL",
            valor=Decimal(parse_entero(fila[1])),
            valor_origen=fila[1],
            ubicacion=tabla.ubicacion(n, fila[0], col),
        )
        for n, fila in enumerate(tabla.datos, start=1)
        if len(fila) > 1 and parse_entero(fila[1]) is not None
    ]


def _cuartiles(tabla: Tabla, ciclo: str, notacion_a_id: dict[str, str]) -> list:
    filas: list = []
    for n, fila in enumerate(tabla.datos, start=1):
        if len(fila) < 4 or not fila[1]:
            continue
        cuartil = notacion_a_id.get(fila[1].strip())
        if cuartil is None:
            raise ValueError(f"cuartil no declarado: {fila[1]!r} (I9)")
        for indice, via in ((2, "PEAMA"), (3, "REGULAR")):
            estudiantes = parse_entero(fila[indice])
            if estudiantes is None:
                continue
            filas.append(
                CoberturaTerritorial(
                    tipo="cobertura_territorial",
                    ciclo_id=ciclo,
                    unidad=fila[0],
                    periodo_id="NA",
                    cuartil_id=cuartil,
                    via_id=via,
                    estudiantes=estudiantes,
                    ubicacion=tabla.ubicacion(n, fila[0], tabla.encabezado[indice]),
                )
            )
    return filas


def _dinero(tabla: Tabla, ciclo: str, rubros: dict[str, str]) -> list:
    """T09/T11/T14 mix single-cell group bands with three-cell data rows, so row
    shape decides the record type.

    These become budget lines, not declarations: their grain is the rubro, which
    `declaracion` has no column for. `Bolsa` appears where a headcount belongs —
    the money is real, the quantity is simply not recorded (§7.2), so it is NULL
    in the measure rather than a zero.
    """
    filas: list = []
    for n, fila in enumerate(tabla.datos, start=1):
        if len(fila) < 3 or not fila[2].strip():
            continue                              # a group band, not a datum
        sublinea, concepto, bruto = fila[0], fila[1], fila[2]
        monto = parse_cop(bruto)
        if monto is None:
            continue
        rubro_id = rubros.get(normalizar(sublinea))
        if rubro_id is None:
            raise ValueError(
                f"rubro no declarado: {sublinea[:60]!r} (I9 — añádalo a reference/rubro.yaml)"
            )
        cantidad = re.match(r"\s*(\d+)\b", concepto)
        filas.append(
            PresupuestoRubro(
                tipo="presupuesto_rubro",
                presupuesto_id=f"{ciclo}|T{tabla.indice:02d}|{n:02d}",
                ciclo_id=ciclo,
                rubro_id=rubro_id,
                unidad="UNAL_TOTAL",
                concepto=concepto[:200] or None,
                cantidad=Decimal(cantidad[1]) if cantidad else None,
                monto=monto,
                monto_origen=bruto,
                ubicacion=tabla.ubicacion(n, sublinea, tabla.encabezado[2]),
            )
        )
    return filas


def extraer(ruta: Path, sha256: str, *, cuartiles: dict[str, str],
            rubros: dict[str, str],
            fecha_asercion: date = date(2026, 4, 13)) -> Extraction:
    tablas = {t.indice: t for t in leer_tablas(ruta)}
    filas: list = []

    for indice, (ciclo, columnas) in TABLAS.items():
        if indice in tablas and columnas:
            filas += _medidas(tablas[indice], ciclo, columnas)
    if 4 in tablas:
        filas += _balance(tablas[4])
    if 5 in tablas:
        filas += _periodos(tablas[5], TABLAS[5][0])
    for indice, ciclo in CUARTIL.items():
        if indice in tablas:
            filas += _cuartiles(tablas[indice], ciclo, cuartiles)
    for indice, ciclo in DINERO.items():
        if indice in tablas:
            filas += _dinero(tablas[indice], ciclo, rubros)

    return Extraction(
        documento_id=DOCUMENTO_ID,
        fuente_sha256=sha256,
        fecha_asercion=fecha_asercion,
        filas=filas,
    )
