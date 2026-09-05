"""Reading tables out of a .docx with the standard library.

python-docx is not needed: Anexo 1's fourteen tables come out of
`word/document.xml` cleanly. Every one is captioned by the paragraph just above
it (`Tabla 7. Balance de compromisos PIC 2024.`), which gives a stable, human
verifiable `ubicacion` — `Tabla 7, fila 'Medellín', col 'Matriculados 2025-2'`
can be checked by anyone with the document open.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class Tabla:
    indice: int                 # 1-based, in document order
    titulo: str                 # the caption paragraph above it
    filas: tuple[tuple[str, ...], ...]

    @property
    def encabezado(self) -> tuple[str, ...]:
        return self.filas[0] if self.filas else ()

    @property
    def datos(self) -> tuple[tuple[str, ...], ...]:
        return self.filas[1:]

    def ubicacion(self, indice_fila: int, etiqueta: str, columna: str) -> str:
        """A coordinate a person can check with the document open.

        The row index is part of it because labels repeat: Tabla 14 names the
        same sublínea three times, and a label-only address would collide.
        """
        return f"Tabla {self.indice}, fila {indice_fila} {etiqueta!r}, col {columna!r}"


def _texto(elem: ET.Element) -> str:
    return "".join(t.text or "" for t in elem.iter(f"{W}t")).strip()


def _celda(celda: ET.Element) -> str:
    return " ".join(
        _texto(p) for p in celda.findall(f"{W}p") if _texto(p)
    ).strip()


def leer_tablas(ruta: Path) -> list[Tabla]:
    with zipfile.ZipFile(ruta) as z:
        cuerpo = ET.fromstring(z.read("word/document.xml")).find(f"{W}body")

    tablas: list[Tabla] = []
    anterior = ""
    for elem in cuerpo:
        if elem.tag == f"{W}p":
            if txt := _texto(elem):
                anterior = txt
        elif elem.tag == f"{W}tbl":
            filas = tuple(
                tuple(_celda(c) for c in tr.findall(f"{W}tc"))
                for tr in elem.findall(f"{W}tr")
            )
            tablas.append(Tabla(len(tablas) + 1, anterior, filas))
    return tablas
