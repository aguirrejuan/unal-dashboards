"""Anexo 2 → an extraction.

Purely deterministic. `ubicacion` is a real cell address
(`Registro_Proyectos_2025!N15`), which is what makes the re-transcription check
possible — and is exactly why a model must never touch a grid: a fabricated cell
reference would pass review and fail nothing.

`valor_origen` keeps the **cached raw value**, not the formatted display string.
Column P holds unrounded formula results such as `4895974740.75787`; comparing a
rounded string against those would fail on every row.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl

from pic_etl.models import Asignacion, Declaracion, Extraction, Proyecto

DOCUMENTO_ID = "ANEXO2_PIC"
HOJA = "Registro_Proyectos_2025"
FILA_ENCABEZADO = 9
FILAS_DATOS = range(10, 19)
CICLO = "PIC_CO_2025"

# Column → funding source. The sheet is the provenance for `columna_xlsx`.
FUENTES = {
    "N": ("BASE_2025", "ADICION_BASE_RECURRENTE"),
    "O": ("SALDOS", "SALDO"),
    "P": ("INDEXACION", "INDEXACION"),
    "Q": ("MATRICULA", "OTRA"),
    "R": ("PROPIOS", "OTRA"),
    "S": ("OTRAS", "OTRA"),
}
COLUMNA_SUMA = "T"


def _celda(hoja, columna: str, fila: int):
    return hoja[f"{columna}{fila}"].value


def ubicacion(columna: str, fila: int) -> str:
    return f"{HOJA}!{columna}{fila}"


def extraer(ruta: Path, sha256: str, *,
            fecha_asercion: date = date(2026, 4, 13)) -> Extraction:
    libro = openpyxl.load_workbook(ruta, data_only=True)
    hoja = libro[HOJA]
    filas: list = []

    for fila in FILAS_DATOS:
        numero = _celda(hoja, "A", fila)
        nombre = _celda(hoja, "B", fila)
        if numero is None or nombre is None:
            continue

        proyecto_id = f"{CICLO}_P{int(numero):02d}"
        # The project name carries the sede: "Aumento de la cobertura en la
        # Sede Amazonia". Row 12 says "Sede Arauca", which is Sede Orinoquía
        # (C2) — resolved at load through a document-scoped alias, not here.
        literal_unidad = str(nombre).split(" en la ", 1)[-1].strip()

        filas.append(
            Proyecto(
                tipo="proyecto",
                proyecto_id=proyecto_id,
                ciclo_id=CICLO,
                unidad=literal_unidad,
                numero=int(numero),
                nombre=str(nombre),
                ubicacion=ubicacion("B", fila),
            )
        )

        for columna, (fuente, flujo) in FUENTES.items():
            bruto = _celda(hoja, columna, fila)
            if bruto is None or isinstance(bruto, str):
                # V2: La Paz has no funding at all; V5: three source columns are
                # empty in every row. An absent row means "not recorded" and is
                # not the same as a measured zero (§7.2).
                continue
            filas.append(
                Asignacion(
                    tipo="asignacion",
                    asignacion_id=f"{proyecto_id}_{fuente}",
                    unidad=literal_unidad,
                    ciclo_id=CICLO,
                    # Fiscal year, not the cycle year. PIC 2025 money is a 2025
                    # addition to the recurrent base; the cycle executes in 2026-2.
                    vigencia=2025,
                    fuente_id=fuente,
                    tipo_flujo=flujo,
                    momento="ASIGNADO",
                    monto=Decimal(str(bruto)),
                    monto_origen=str(bruto),
                    ubicacion=ubicacion(columna, fila),
                )
            )

        suma = _celda(hoja, COLUMNA_SUMA, fila)
        if suma is not None and not isinstance(suma, str):
            filas.append(
                Declaracion(
                    tipo="declaracion",
                    tipo_declaracion="AGREGADO",
                    medida_id="monto",
                    ciclo_id=CICLO,
                    unidad=literal_unidad,
                    periodo_id="NA",
                    poblacion_id="NA",
                    valor=Decimal(str(suma)),
                    valor_origen=str(suma),
                    ubicacion=ubicacion(COLUMNA_SUMA, fila),
                    componentes=[
                        ubicacion(c, fila)
                        for c in FUENTES
                        if _celda(hoja, c, fila) is not None
                        and not isinstance(_celda(hoja, c, fila), str)
                    ],
                )
            )

    return Extraction(
        documento_id=DOCUMENTO_ID,
        fuente_sha256=sha256,
        fecha_asercion=fecha_asercion,
        filas=filas,
    )
