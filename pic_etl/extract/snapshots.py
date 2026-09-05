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
