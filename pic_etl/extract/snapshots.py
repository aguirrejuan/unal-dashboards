"""Source tables rendered to HTML, with every cell addressable.

A citation says `Tabla 2, fila 9 'TOTAL', col 'Cupos'`. A link to a 300 KB
`.docx` makes the reader hunt for that themselves. A snapshot shows them the
row, with the cited cell marked — which is the difference between citing
evidence and showing it.

Cells carry both the canonical `ubicacion` and numeric row/column coordinates,
so a figure resolves even when the citation truncates a long label.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from pic_etl.extract.docx_tablas import leer_tablas

HOJA = "Registro_Proyectos_2025"


@dataclass(frozen=True)
class Snapshot:
    documento_id: str
    contenedor: str          # 'Tabla 2' | 'Registro_Proyectos_2025'
    titulo: str
    html: str


def _celda(texto: str, *, ubicacion: str, fila: int, col: int, encabezado: bool) -> str:
    etiqueta = "th" if encabezado else "td"
    return (
        f'<{etiqueta} data-ubicacion="{html.escape(ubicacion, quote=True)}"'
        f' data-fila="{fila}" data-col="{col}">{html.escape(texto)}</{etiqueta}>'
    )


def anexo1(ruta: Path, documento_id: str = "ANEXO1_PIC") -> list[Snapshot]:
    salidas: list[Snapshot] = []
    for tabla in leer_tablas(ruta):
        encabezado = tabla.encabezado
        filas_html = ["<tr>" + "".join(
            _celda(c, ubicacion=f"Tabla {tabla.indice}, encabezado, col {c!r}",
                   fila=0, col=j, encabezado=True)
            for j, c in enumerate(encabezado)) + "</tr>"]

        for n, fila in enumerate(tabla.datos, start=1):
            celdas = []
            for j, valor in enumerate(fila):
                columna = encabezado[j] if j < len(encabezado) else ""
                celdas.append(_celda(
                    valor,
                    ubicacion=tabla.ubicacion(n, fila[0], columna),
                    fila=n, col=j, encabezado=False,
                ))
            filas_html.append("<tr>" + "".join(celdas) + "</tr>")

        salidas.append(Snapshot(
            documento_id=documento_id,
            contenedor=f"Tabla {tabla.indice}",
            titulo=tabla.titulo,
            html="<table>" + "".join(filas_html) + "</table>",
        ))
    return salidas


def anexo2(ruta: Path, documento_id: str = "ANEXO2_PIC") -> list[Snapshot]:
    """Rows 9-18 of the only data sheet: the header row plus the nine projects.

    Row 3 is included as a caption because it carries `#REF!` where the SNIES
    code belongs (E13) — visible here even though no table models it.
    """
    hoja = openpyxl.load_workbook(ruta, data_only=True)[HOJA]
    columnas = [chr(c) for c in range(ord("A"), ord("V") + 1)]

    filas_html = []
    for fila in range(9, 19):
        celdas = []
        for j, col in enumerate(columnas):
            valor = hoja[f"{col}{fila}"].value
            texto = "" if valor is None else str(valor)
            celdas.append(_celda(
                re.sub(r"\s+", " ", texto)[:80],
                ubicacion=f"{HOJA}!{col}{fila}",
                fila=fila, col=j, encabezado=(fila == 9),
            ))
        filas_html.append("<tr>" + "".join(celdas) + "</tr>")

    snies = hoja["C3"].value
    return [Snapshot(
        documento_id=documento_id,
        contenedor=HOJA,
        titulo=f"{HOJA} · CÓDIGO SNIES IES = {snies!r} (E13)",
        html="<table>" + "".join(filas_html) + "</table>",
    )]


def pdf_paginas(ruta: Path, documento_id: str, paginas: set[int]) -> list[Snapshot]:
    """Cited pages of a prose document, rendered so the anchor can be marked.

    A table has cells to point at; a page of prose does not. So the page is kept
    as text and each cited line becomes an addressable element — the same
    "show me the row" the spreadsheet panels give, for a document that has no
    grid.
    """
    from pic_etl.extract import texto_pdf

    todas = texto_pdf.paginas(ruta)
    salidas: list[Snapshot] = []
    for n in sorted(paginas):
        if n < 1 or n > len(todas):
            continue
        lineas = [l.rstrip() for l in todas[n - 1].splitlines()]
        cuerpo = "".join(
            f'<div data-ubicacion="{html.escape(texto_pdf.ubicacion(n, l), quote=True)}"'
            f' data-fila="{i}" data-col="0">{html.escape(l) or "&nbsp;"}</div>'
            for i, l in enumerate(lineas) if l.strip()
        )
        salidas.append(Snapshot(
            documento_id=documento_id,
            contenedor=f"p.{n}",
            titulo=f"{documento_id} · página {n}",
            html=f'<pre class="pagina">{cuerpo}</pre>',
        ))
    return salidas


def informe(ruta: Path, documento_id: str) -> list[Snapshot]:
    """The .doc reports' tables, recovered from the raw stream and rendered.

    Worth seeing beside the figures precisely because no ordinary reader can:
    open these files in Word and the tables are there, convert them by any means
    and they collapse into a single run of digits.

    Two hazards. Embedded images leave byte runs that contain enough `\x07` to
    look like rows, so blocks are kept only when they read as text. And one
    logical table is split across blocks with only the first carrying column
    names, so rows are accumulated per section rather than emitted per block —
    otherwise the later block overwrites the earlier one.
    """
    from pic_etl.extract import informes

    def legible(fila: list[str]) -> bool:
        texto = " ".join(fila)
        if not texto:
            return False
        limpio = sum(c.isprintable() or c.isspace() for c in texto)
        return limpio / len(texto) > 0.95

    secciones: dict[str, tuple[list[str], list[list[str]]]] = {}
    ultimo: tuple[str, list[str]] | None = None

    for tabla in informes.tablas(ruta):
        filas = [f for f in tabla if legible(f)]
        if not filas:
            continue
        junta = " ".join(filas[0])
        es_encabezado = any(
            c.strip() in {"Fuente", "Valor", "Sede", "Ciclo"} for c in filas[0]
        )
        if es_encabezado:
            seccion = ("6" if "2026-1" in junta
                       else "3" if "Diferencia" in junta else "fuentes")
            encabezado, cuerpo = filas[0], filas[1:]
            ultimo = (seccion, encabezado)
        elif ultimo is not None:
            seccion, encabezado = ultimo
            cuerpo = filas
        else:
            continue
        actual = secciones.setdefault(seccion, (encabezado, []))
        actual[1].extend(cuerpo)

    salidas: list[Snapshot] = []
    for seccion, (encabezado, cuerpo) in secciones.items():
        contenedor = "Tabla de fuentes" if seccion == "fuentes" else f"§{seccion}"

        def ubic(etiqueta: str, columna: str, n: int) -> str:
            return (f"Tabla de fuentes, fila {etiqueta!r}, col {columna!r}"
                    if seccion == "fuentes"
                    else f"§{seccion}, fila {n} {etiqueta!r}, col {columna!r}")

        filas_html = ["<tr>" + "".join(
            _celda(c, ubicacion=f"{contenedor}, encabezado, col {c!r}",
                   fila=0, col=j, encabezado=True)
            for j, c in enumerate(encabezado)) + "</tr>"]
        for n, fila in enumerate(cuerpo, start=1):
            celdas = [
                _celda(valor,
                       ubicacion=ubic(fila[0],
                                      encabezado[j] if j < len(encabezado) else "", n),
                       fila=n, col=j, encabezado=False)
                for j, valor in enumerate(fila)
            ]
            filas_html.append("<tr>" + "".join(celdas) + "</tr>")

        salidas.append(Snapshot(
            documento_id=documento_id, contenedor=contenedor,
            titulo=f"{documento_id} · {contenedor}",
            html="<table>" + "".join(filas_html) + "</table>",
        ))
    return salidas


def escribir(snapshots: list[Snapshot], destino: Path) -> dict[str, str]:
    """Write one fragment per container and return an index keyed by container."""
    destino.mkdir(parents=True, exist_ok=True)
    indice: dict[str, str] = {}
    for s in snapshots:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", s.contenedor).strip("_")
        archivo = destino / s.documento_id / f"{slug}.html"
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(
            f"<!-- {s.documento_id} · {s.titulo} -->\n{s.html}\n", encoding="utf-8"
        )
        indice[f"{s.documento_id}|{s.contenedor}"] = str(
            archivo.relative_to(destino.parent)
        )
    (destino / "indice.json").write_text(
        json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return indice
