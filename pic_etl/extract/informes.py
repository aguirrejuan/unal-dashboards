"""The MEN reports (.doc) → extractions.

These are OLE2 Word 97 files, and their tables survive nowhere else: `textutil`
flattens them to text in every output format it offers — txt, rtf, html and even
docx — turning a row into `Palmira24016518357465452167376+136`, which cannot be
split back apart without already knowing the answer.

The tables are intact in the underlying stream, where Word writes `\\x07` between
cells and `\\x07\\x07` between rows. Reading them there is not a trick: it is the
only place the structure still exists.

This is the document that carries the corpus's flagship divergences — 1 043
against Anexo 1's 1 161, and 1 836 against its 1 818.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from pic_etl.models import Declaracion, Extraction

SEPARADOR_CELDA = "\x07"
DOCUMENTO_ID = "INFORME_MEN_2024_2025"

# The Informe reports the consolidated position it puts to the Ministry, which
# includes La Paz — the very thing that separates 1 836 from Anexo 1's 1 818.
POBLACION = "CONSOLIDADO_LA_PAZ"

_TOTAL = re.compile(r"^totale?s?$", re.I)


def tablas(ruta: Path) -> list[list[list[str]]]:
    """Recover the tables from the raw stream."""
    crudo = ruta.read_bytes().decode("cp1252", errors="ignore")
    encontradas: list[list[list[str]]] = []
    for bloque in re.finditer(
        rf"(?:[^\x07]{{0,200}}{SEPARADOR_CELDA}){{4,}}", crudo
    ):
        filas = []
        for fila in bloque.group(0).split(SEPARADOR_CELDA * 2):
            celdas = [c.strip() for c in fila.split(SEPARADOR_CELDA)]
            celdas = [c for c in celdas if c]
            if len(celdas) >= 4:
                # A run of prose precedes the first header cell; keep the tail.
                celdas[0] = celdas[0].rsplit("\r", 1)[-1].strip()
                filas.append(celdas)
        # Two rows is enough: the qualitative report splits its source table
        # across blocks, and the row naming Res. 018433 sits alone in one of
        # them. Binary noise is rejected per row by `_texto_legible` instead.
        if len(filas) >= 2:
            encontradas.append(filas)
    return encontradas


def _entero(texto: str) -> int | None:
    limpio = texto.replace(".", "").replace("+", "").strip()
    if not re.fullmatch(r"-?\d+", limpio):
        return None            # '-' means not recorded, and is never a zero
    return int(limpio)


# §6 columns, in order after the sede name.
_COLUMNAS = (
    ("compromiso",        "NA"),
    ("cupos_ofertados",   "NA"),
    ("admitidos",         "NA"),
    ("primera_matricula", "2024-1"),
    ("primera_matricula", "2024-2"),
    ("primera_matricula", "2025-1"),
    ("primera_matricula", "2025-2"),
    ("primera_matricula", "2026-1"),
    ("matriculados",      "NA"),      # the row's own total, cumulative
    ("balance_cumplimiento", "NA"),   # NOT `rezago`: the sign is inverted
)


def balance_por_sede(filas: list[list[str]]) -> list:
    """§6 — sede × measure, with the table's own Total row kept as an AGREGADO.

    Three of its columns do not equal their parts: 2026-1, Total matriculados
    and Rezago each fall exactly 60 short. Storing the total separately is what
    turns that into a runnable test rather than a claim.
    """
    encabezado, *cuerpo = filas
    salida: list = []
    componentes: dict[int, list[str]] = {}

    for n_fila, fila in enumerate(cuerpo, 1):
        etiqueta = fila[0]
        es_total = bool(_TOTAL.match(etiqueta))
        for i, (medida, periodo) in enumerate(_COLUMNAS, start=1):
            if i >= len(fila):
                continue
            valor = _entero(fila[i])
            if valor is None:
                continue
            columna = encabezado[i] if i < len(encabezado) else str(i)
            ubic = f"§6, fila {n_fila} {etiqueta!r}, col {columna!r}"
            # §6 is a balance "con corte al 2026-1": its enrolment total is
            # cumulative across cycles, while its commitment is PIC 2023's.
            # Filing both under one cycle would put a cumulative figure and a
            # single-cycle one at the same grain.
            ciclo = "TODOS" if medida == "matriculados" else "PIC_CO_2023"
            if not es_total:
                componentes.setdefault(i, []).append(ubic)
            salida.append(Declaracion(
                tipo="declaracion",
                tipo_declaracion="AGREGADO" if es_total else "TRANSCRIPCION",
                medida_id=medida, ciclo_id=ciclo,
                unidad="UNAL_TOTAL" if es_total else etiqueta,
                periodo_id=periodo, poblacion_id=POBLACION,
                valor=Decimal(valor), valor_origen=fila[i], ubicacion=ubic,
                componentes=componentes.get(i, []) if es_total else [],
            ))
    return salida


def balance_consolidado(filas: list[list[str]]) -> list:
    """§3 — the headline table: 1 818 / 1 043 / −775, and a TOTAL of 2 284."""
    ciclos = {"PIC 2023": "PIC_CO_2023", "PIC 2024": "PIC_CO_2024"}
    medidas = ("compromiso", "matriculados", "rezago")
    salida: list = []
    for n_fila, fila in enumerate(filas[1:], 1):
        ciclo = next((v for k, v in ciclos.items() if fila[0].startswith(k)), "TODOS")
        for i, medida in enumerate(medidas, start=1):
            if i >= len(fila) or (valor := _entero(fila[i])) is None:
                continue
            salida.append(Declaracion(
                tipo="declaracion",
                tipo_declaracion="AGREGADO",
                medida_id=medida, ciclo_id=ciclo, unidad="UNAL_TOTAL",
                periodo_id="NA", poblacion_id=POBLACION,
                valor=Decimal(valor), valor_origen=fila[i],
                ubicacion=f"§3, fila {n_fila} {fila[0]!r}, col {filas[0][i]!r}",
            ))
    return salida


def extraer(ruta: Path, sha256: str,
            fecha_asercion: date = date(2026, 4, 15)) -> Extraction | None:
    filas: list = []
    for tabla in tablas(ruta):
        encabezado = " ".join(tabla[0]).lower()
        if "2026-1" in encabezado and "admitidos" in encabezado:
            filas += balance_por_sede(tabla)
        elif "compromiso" in encabezado and "diferencia" in encabezado:
            filas += balance_consolidado(tabla)
    if not filas:
        return None
    return Extraction(documento_id=DOCUMENTO_ID, fuente_sha256=sha256,
                      fecha_asercion=fecha_asercion, filas=filas)


# --- the qualitative report ---------------------------------------------------

DOCUMENTO_CUALITATIVO = "INFORME_CUALITATIVO"

# Which resolution each quoted amount is attributed to, and which vigencia it
# belongs to. L7: a figure quoted from another document is a claim by the
# quoting one, so every row here is a declaration against this report — never
# against the resolution it names.
_RESOLUCION = re.compile(r"^Res\.?\s*0?(\d{4,6})\s+de\s+(\d{4})", re.I)
_IMPORTE = re.compile(r"\$\s?([\d][\d.]{6,})")


def _texto_legible(celda: str) -> bool:
    """Reject the binary blocks that embedded images leave in the stream.

    Their bytes contain `\\x07` often enough to look like a table, so a run of
    cells is only believed when it reads as text.
    """
    if not celda:
        return False
    legibles = sum(c.isprintable() and (c.isascii() or c in "áéíóúñÁÉÍÓÚÑ¿¡°") for c in celda)
    return legibles / len(celda) > 0.9


def montos_citados(ruta: Path, fecha_asercion: date) -> list:
    """The `Fuente / Valor` table: four MEN resolutions and the amount this
    report attributes to each."""
    filas: list = []
    vistos: set[str] = set()
    for tabla in tablas(ruta):
        for fila in tabla:
            if not fila or not _texto_legible(fila[0]):
                continue
            m = _RESOLUCION.match(fila[0].strip())
            if m is None or len(fila) < 2:
                continue
            importe = _IMPORTE.search(fila[1])
            if importe is None:
                continue
            numero, anio = m[1].zfill(6), m[2]
            citada = f"RES_MEN_{numero}_{anio}"
            if citada in vistos:
                continue
            vistos.add(citada)
            filas.append(Declaracion(
                tipo="declaracion", medida_id="monto",
                ciclo_id=f"PIC_CO_{anio}" if anio in {"2023", "2024", "2025"} else "TODOS",
                unidad="UNAL_TOTAL", periodo_id="NA", poblacion_id="NA",
                valor=Decimal(importe[1].replace(".", "")),
                valor_origen=importe[0].strip(),
                ubicacion=f"Tabla de fuentes, fila {fila[0].strip()!r}, col 'Valor'",
                nota=f"cifra que este informe atribuye a {citada}",
            ))
    return filas


def extraer_cualitativo(ruta: Path, sha256: str,
                        fecha_asercion: date = date(2026, 4, 13)) -> Extraction | None:
    filas = montos_citados(ruta, fecha_asercion)
    if not filas:
        return None
    return Extraction(documento_id=DOCUMENTO_CUALITATIVO, fuente_sha256=sha256,
                      fecha_asercion=fecha_asercion, filas=filas)
