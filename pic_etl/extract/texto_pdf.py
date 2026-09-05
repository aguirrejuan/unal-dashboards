"""Text and page-anchored citations for prose documents.

A spreadsheet cell has an address; a paragraph does not. So a citation into
prose carries a **verbatim anchor** — a distinctive phrase from the document —
and `verify` checks two things: that the anchor still appears on that page, and
that the transcribed literal appears near it. An invented citation fails both.

The twelve Acuerdos are Chrome prints of UNAL's Régimen Legal system and carry
browser header and footer chrome on every page. That chrome includes a printed-on
date (`12/3/26`) which is the day someone pressed print, not the document's date,
and it must be stripped before any date parsing runs.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Header/footer the browser adds; none of it belongs to the document.
_CHROME = (
    re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2},\s+\d{1,2}:\d{2}\s*$"),
    re.compile(r"Sección Contenido - Universidad Nacional de Colombia"),
    re.compile(r"^\s*https?://\S+\s*$"),
    re.compile(r"^\s*\d+/\d+\s*$"),
)


def _limpiar(texto: str) -> str:
    return "\n".join(
        l for l in texto.splitlines() if not any(p.search(l) for p in _CHROME)
    )


def paginas(ruta: Path) -> list[str]:
    """Page text, chrome removed, 1-indexed by list position + 1."""
    salida = subprocess.run(
        ["pdftotext", "-layout", str(ruta), "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [_limpiar(p) for p in salida.split("\f")]


def texto(ruta: Path) -> str:
    return "\n".join(paginas(ruta))


def normalizar(s: str) -> str:
    """Collapse whitespace, so an anchor survives pdftotext's column padding."""
    return " ".join(s.split())


def ubicacion(pagina: int, ancla: str) -> str:
    return f"p.{pagina}, «{normalizar(ancla)[:70]}»"


def leer_ubicacion(ubic: str) -> tuple[int, str] | None:
    m = re.match(r"p\.(\d+), «(.+)»$", ubic)
    return (int(m[1]), m[2]) if m else None


def comprobar(paginas_texto: list[str], ubic: str, literal: str) -> str | None:
    """Return a complaint if the citation no longer holds, else None."""
    partes = leer_ubicacion(ubic)
    if partes is None:
        return f"{ubic}: no sé leer esta cita"
    pagina, ancla = partes
    if pagina < 1 or pagina > len(paginas_texto):
        return f"{ubic}: la página no existe (el documento tiene {len(paginas_texto)})"

    cuerpo = normalizar(paginas_texto[pagina - 1])
    if ancla not in cuerpo:
        return f"{ubic}: el ancla ya no aparece en la página {pagina}"
    if normalizar(literal) not in cuerpo:
        return f"{ubic}: la página no contiene {literal!r}"
    return None


# --- deterministic metadata -------------------------------------------------
# The Acuerdos share a rigid preamble, so this needs no model at all.

_FECHA = re.compile(r"FECHA DE EXPEDICI[ÓO]N:\s*(\d{2})/(\d{2})/(\d{4})")
_VIGENCIA = re.compile(r"FECHA DE ENTRADA EN VIGENCIA:\s*(\d{2})/(\d{2})/(\d{4})")
_NUMERO = re.compile(r"ACUERDO\s+(\d{1,3})\s+DE\s+(\d{4})", re.I)
_ACTA = re.compile(r"\(\s*Acta\s+([^)]+)\)")


def metadata(ruta: Path) -> dict:
    t = texto(ruta)
    fecha = _FECHA.search(t)
    numero = _NUMERO.search(t)
    acta = _ACTA.search(t)
    # The title is the quoted block between the acta line and the council
    # header. Quote style varies — some use curly, some straight — so it is
    # located by position rather than by punctuation.
    titulo = re.search(
        r"\(\s*Acta[^)]*\)\s*[\u201c\"]?(.{40,}?)[\u201d\"]?\s*EL CONSEJO SUPERIOR",
        t, re.S,
    )
    return {
        "numero": numero[1].zfill(3) if numero else None,
        "anio": int(numero[2]) if numero else None,
        "fecha": f"{fecha[3]}-{fecha[2]}-{fecha[1]}" if fecha else None,
        "vigencia_desde": (
            lambda m: f"{m[3]}-{m[2]}-{m[1]}" if m else None
        )(_VIGENCIA.search(t)),
        "acta": normalizar(acta[1]) if acta else None,
        "titulo": normalizar(titulo[1]).strip('"\u201c\u201d ')[:300] if titulo else None,
    }
