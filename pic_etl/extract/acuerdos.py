"""The twelve Acuerdos del Consejo Superior Universitario → extractions.

Two halves, deliberately separated:

* **Metadata parses deterministically.** The preamble is rigid — number, date,
  acta, title — so no model touches it. See `texto_pdf.metadata`.
* **Figures come from tables with a fixed shape.** `Crear … (N) cargos en
  equivalentes en tiempo completo … se distribuyen así:` is followed by a
  `Sede  N` table closed by `TOTAL`. That is regular enough to parse.

What a model would be needed for — figures embedded in free prose — is left
out rather than guessed at. Every row here is anchored to a page and a verbatim
phrase that `verify` re-checks against the document.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from pic_etl.extract import texto_pdf as T
from pic_etl.models import Asignacion, CargoCreado, Declaracion, Extraction

# Which cycle an Acuerdo's posts belong to, taken from the MEN resolution each
# one cites — a judgement, recorded here rather than buried in a regex.
CICLO_POR_ACUERDO = {
    "ACU_CSU_005_2024": "PIC_CO_2023",   # cita Res. 016202 de 2023
    "ACU_CSU_024_2025": "PIC_CO_2024",   # cita Res. 18433 de 2024
    "ACU_CSU_052_2025": "PIC_CO_2025",   # cita Res. 016468 de 2025
}

_DISTRIBUCION = re.compile(r"se distribuyen as[íi]\s*:", re.I)
_FILA = re.compile(r"^(.{3,45}?)\s+(\d{1,3}(?:[.,]\d)?)\s*$")
_TOTAL = re.compile(r"^TOTAL\s+(\d{1,4}(?:[.,]\d)?)\s*$", re.I)

# A label ending in a preposition or article is plainly unfinished — the rest of
# it sits on the far side of the number.
_COLGANDO = re.compile(r"\b(de|la|el|los|las|del|y|en)$", re.I)


def _incompleta(etiqueta: str) -> bool:
    return bool(_COLGANDO.search(etiqueta.strip()))


def _a_decimal(s: str) -> Decimal:
    return Decimal(s.replace(",", "."))


def tabla_etc(ruta: Path, documento_id: str) -> list:
    """The per-sede ETC distribution, plus its declared TOTAL as an AGREGADO.

    **The table can span a page break.** Acuerdo 024/2025 lists five sedes on
    one page and five on the next; reading only the first page gives 76 under a
    TOTAL of 191,5 and looks exactly like a document that does not add up. It
    does add up. Scanning stops at TOTAL, not at the page boundary.

    The total is never stored as a sede row. Keeping it separate is what lets
    I15 ask whether it equals its parts.
    """
    ciclo = CICLO_POR_ACUERDO.get(documento_id)
    if ciclo is None:
        return []

    # (page number, line) across the whole document, so a table may cross pages
    lineas: list[tuple[int, str]] = [
        (n, l.strip())
        for n, pagina in enumerate(T.paginas(ruta), 1)
        for l in pagina.splitlines()
    ]
    try:
        inicio = next(i for i, (_, l) in enumerate(lineas) if _DISTRIBUCION.search(l))
    except StopIteration:
        return []

    # A merged cell is centred vertically, so a long sede name is split *around*
    # its own number:
    #     Facultad Ciencias de la
    #                              25
    #     Vida
    # Read line by line, "25" belongs to nothing and "Vida" glues itself to the
    # next sede. So rows are assembled first, then the trailing fragment of a
    # split label is reattached.
    # (página, etiqueta reconstruida, número, ancla verbatim)
    # The anchor must be text that appears in the document exactly as written.
    # A reconstructed label like "Facultad Ciencias de la Vida 25" never does —
    # the source splits it around its own number — so the anchor is the line the
    # row actually came from.
    crudas: list[tuple[int, str, str, str]] = []
    total_fila: tuple[int, str] | None = None
    pendiente = ""

    for n_pagina, linea in lineas[inicio + 1: inicio + 90]:
        if not linea:
            continue
        if (total := _TOTAL.match(linea)) is not None:
            total_fila = (n_pagina, total[1])
            break
        if (fila := _FILA.match(linea)) is not None:
            etiqueta = T.normalizar(f"{pendiente} {fila[1]}").strip()
            crudas.append((n_pagina, etiqueta, fila[2], T.normalizar(linea)))
            pendiente = ""
        elif (solo := re.match(r"^(\d{1,3}(?:[.,]\d)?)$", linea)) is not None:
            # A bare number: anchor on the label line that preceded it.
            crudas.append((n_pagina, pendiente.strip(), solo[1],
                           T.normalizar(pendiente) or solo[1]))
            pendiente = ""
        elif len(linea) < 46:
            # Text with no number: either the start of a wrapped label, or the
            # tail of one that was split around its number.
            if crudas and not pendiente and crudas[-1][1] and _incompleta(crudas[-1][1]):
                n, etq, val, ancla = crudas[-1]
                crudas[-1] = (n, T.normalizar(f"{etq} {linea}"), val, ancla)
            else:
                pendiente = linea

    filas: list = []
    componentes: list[str] = []
    for n_pagina, etiqueta, valor, ancla in crudas:
        etiqueta = re.sub(r"^(?:CARGOS EN TIEMPO\s*)?COMPLETO\s+", "", etiqueta, flags=re.I)
        if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", etiqueta):
            continue
        ubic = T.ubicacion(n_pagina, ancla)
        componentes.append(ubic)
        # Two rows, deliberately. `cargo_creado` is the structural fact — this
        # document created these posts at this sede. The declaration is the
        # measured number, and it is what lets the TOTAL row link to its parts
        # through es_agregado_de, which links declarations to declarations. A
        # component sitting only in a structural table is invisible to I15.
        filas.append(CargoCreado(
            tipo="cargo_creado", unidad=etiqueta, tipo_cargo="DOCENTE_ETC",
            cantidad=_a_decimal(valor), cantidad_origen=valor, ubicacion=ubic,
        ))
        filas.append(Declaracion(
            tipo="declaracion", medida_id="cargos_creados", ciclo_id=ciclo,
            unidad=etiqueta, periodo_id="NA", poblacion_id="NA",
            valor=_a_decimal(valor), valor_origen=valor, ubicacion=ubic,
        ))

    if total_fila is not None:
        n_pagina, valor = total_fila
        filas.append(Declaracion(
            tipo="declaracion", tipo_declaracion="AGREGADO",
            medida_id="cargos_creados", ciclo_id=ciclo,
            unidad="UNAL_TOTAL", periodo_id="NA", poblacion_id="NA",
            valor=_a_decimal(valor), valor_origen=valor,
            ubicacion=T.ubicacion(n_pagina, f"TOTAL {valor}"),
            componentes=componentes,
        ))

    return filas


def extraer(ruta: Path, documento_id: str, sha256: str,
            fecha_asercion: date) -> Extraction | None:
    filas = (tabla_etc(ruta, documento_id) + montos(ruta, documento_id)
             + cargos_administrativos(ruta, documento_id))
    if not filas:
        return None
    return Extraction(
        documento_id=documento_id, fuente_sha256=sha256,
        fecha_asercion=fecha_asercion, filas=filas,
    )


# --- money -------------------------------------------------------------------
#
# Each entry says: which figures this Acuerdo states, and what they mean. Written
# out rather than inferred, because the meaning of an amount comes from the
# sentence around it and that is exactly what a regex cannot read. The anchors
# are verbatim, so `verify` re-checks every one against the document.

_MONTO = re.compile(r"\$\s?([\d][\d.]{6,})")

# Each spec captures the label **and** its amount in one match. An anchor plus
# an ordinal is not enough: "Palmira" and "Manizales" appear in every preamble
# long before the table that gives them a figure, so a positional rule silently
# reads the wrong number.
MONTOS: dict[str, dict] = {
    # E10 — four vigencias summing to 81.140.000.000 under a declared
    # "$81.480.000 millones", whose unit is also wrong.
    "ACU_CSU_016_2023": {
        "patron": r"(Primer|Segundo|Tercer|Cuarto) año \((\d{4})\)[^$]{0,120}\$\s?([\d.]{9,})",
        "ciclo": "PIC_CO_2023",
        "campos": ("orden", "vigencia", "monto"),
        "fuente": lambda g: "PIC_PROGRAMA" if g[1] == "2023" else "VIGENCIA_PROYECTADA",
        "unidad": lambda g: "UNAL_TOTAL",
        "vigencia": lambda g: int(g[1]),
    },
    # The act that approves the PIC for Palmira, Manizales and Bogotá, quoting
    # Res. 016202. States $11.386.578.188 — the same figure as Acuerdo 005/2024
    # and one peso above what Acuerdo 006/2024's three sedes sum to.
    "ACU_CSU_017_2023": {
        "patron": r"\$\s?(11\.386\.578\.188)",
        "ciclo": "PIC_CO_2023",
        "campos": ("monto",),
        "fuente": lambda g: "PIC_AMPLIACION",
        "unidad": lambda g: "UNAL_TOTAL",
        "vigencia": lambda g: 2023,
    },
    # The Medellín programme: $75.057.000.000 over three vigencias, which do
    # reconcile — 23.276 + 23.951 + 27.830.
    "ACU_CSU_018_2023": {
        "patron": r"(primer|segundo|tercer) año,?\s*\((\d{4})\)\s*\$\s?([\d.]{9,})",
        "ciclo": "PIC_CO_2023",
        "campos": ("orden", "vigencia", "monto"),
        "fuente": lambda g: "PIC_PROGRAMA" if g[1] == "2023" else "VIGENCIA_PROYECTADA",
        "unidad": lambda g: "Medellín",
        "vigencia": lambda g: int(g[1]),
    },
    # The same PIC programme stated as $11.386.578.188 here and $11.386.578.187
    # in Acuerdo 006/2024 — a one-peso divergence between two acts of the same
    # council, four months apart.
    "ACU_CSU_005_2024": {
        "patron": r"\$\s?(18\.120\.000\.000|23\.276\.000\.000|11\.386\.578\.188)",
        "ciclo": "PIC_CO_2023",
        "campos": ("monto",),
        "fuente": lambda g: {
            "18.120.000.000": "PIC_PROGRAMA",
            "23.276.000.000": "PIC_PROGRAMA",
            "11.386.578.188": "PIC_AMPLIACION",
        }[g[0]],
        "unidad": lambda g: {
            "18.120.000.000": "UNAL_TOTAL",     # SPN: Amazonía, Caribe, Orinoquía, Tumaco
            "23.276.000.000": "Medellín",
            "11.386.578.188": "UNAL_TOTAL",     # Palmira, Manizales y Bogotá
        }[g[0]],
        "vigencia": lambda g: 2024,
    },
    # Manizales + Palmira + Bogotá = $11.386.578.187, one peso below the
    # $11.386.578.188 Acuerdo 005/2024 states for the same programme.
    "ACU_CSU_006_2024": {
        "patron": r"(Manizales|Palmira|Bogotá)\s+\$\s?([\d.]{9,})",
        "ciclo": "PIC_CO_2023",
        "campos": ("unidad", "monto"),
        "fuente": lambda g: "PIC_PROGRAMA",
        "unidad": lambda g: g[0],
        "vigencia": lambda g: 2024,
    },
    # The PIC line of Res. 016468, primary-sourced in a text document.
    "ACU_CSU_052_2025": {
        "patron": r"\$\s?(9\.561\.136\.948|40\.796\.371\.737|4\.664\.016\.085|655\.841\.016)",
        "ciclo": "PIC_CO_2025",
        "campos": ("monto",),
        # Keyed on the whole amount: 40.796… and 4.664… share a first digit,
        # and a prefix rule silently merged them into one source.
        "fuente": lambda g: {
            "9.561.136.948":  "PIC_AMPLIACION",
            "40.796.371.737": "FORTALECIMIENTO",
            "4.664.016.085":  "BIENESTAR",
            "655.841.016":    "GESTION",
        }[g[0]],
        "unidad": lambda g: "UNAL_TOTAL",
        "vigencia": lambda g: 2025,
    },
    # Res. 18433, which this Acuerdo calls *inversión* while the scan places
    # UNAL under funcionamiento (E4).
    "ACU_CSU_024_2025": {
        "patron": r"\$\s?(24\.964\.619\.055|12\.565\.370\.407)",
        "ciclo": "PIC_CO_2024",
        "campos": ("monto",),
        "fuente": lambda g: "FORTALECIMIENTO" if g[0].startswith("24") else "CIERRE_BRECHAS",
        "unidad": lambda g: "UNAL_TOTAL",
        "vigencia": lambda g: 2024,
    },
}


def montos(ruta: Path, documento_id: str) -> list:
    """Amounts read together with the label that gives them meaning.

    Pages are searched whole, not line by line: a considerando wraps across
    four or five lines, so a label and its figure routinely sit on different
    ones.
    """
    spec = MONTOS.get(documento_id)
    if spec is None:
        return []

    patron = re.compile(spec["patron"])
    filas: list = []
    vistos: set[str] = set()
    for n_pagina, pagina in enumerate(T.paginas(ruta), 1):
        plano = T.normalizar(pagina)
        for m in patron.finditer(plano):
            grupos = m.groups()
            bruto = grupos[-1]
            unidad = spec["unidad"](grupos)
            fuente = spec["fuente"](grupos)
            clave = f"{fuente}|{unidad}|{spec['vigencia'](grupos)}"
            if clave in vistos:
                continue
            vistos.add(clave)
            filas.append(Asignacion(
                tipo="asignacion",
                asignacion_id=f"{documento_id}|{clave}",
                unidad=unidad, ciclo_id=spec["ciclo"],
                vigencia=spec["vigencia"](grupos),
                fuente_id=fuente, tipo_flujo="ADICION_BASE_RECURRENTE",
                momento="ASIGNADO",
                monto=Decimal(bruto.replace(".", "")),
                # Verbatim, spacing included: several documents write "$ 9.561…"
                # and a reconstructed "$9.561…" would fail its own check.
                monto_origen=re.search(r"\$\s?[\d.]{9,}", m.group(0))[0],
                # The anchor is the matched text itself, so it is verbatim by
                # construction and `verify` can always find it again.
                ubicacion=T.ubicacion(n_pagina, m.group(0)),
            ))
    return filas


# --- administrative posts ------------------------------------------------------
#
# Each of these Acuerdos states its own count in its title — "creando siete (7)
# cargos de carrera administrativa en cada una" — and repeats it in the article
# that creates them. The counts are read from the title, where the figure and the
# unit it applies to sit in one sentence; the per-sede split comes from the
# ARTÍCULO headings, which name one sede each.

CARGOS_ADMIN: dict[str, dict] = {
    # Seven posts in each of the four Sedes de Presencia Nacional.
    "ACU_CSU_004_2025": {"ciclo": "PIC_CO_2024", "por_sede": 7,
                         "sedes": ["Amazonía", "Orinoquía", "Caribe", "Tumaco"],
                         "ancla": "creando siete (7) cargos de carrera administrativa"},
    "ACU_CSU_006_2024": {"ciclo": "PIC_CO_2023", "por_sede": 4, "sedes": ["UNAL_TOTAL"],
                         "ancla": "se crean cuatro (4) cargos de Libre Nombramiento"},
    "ACU_CSU_013_2024": {"ciclo": "PIC_CO_2023", "por_sede": 3, "sedes": ["Manizales"],
                         "ancla": "creando tres (3) cargos de libre nombramiento"},
    "ACU_CSU_017_2024": {"ciclo": "PIC_CO_2023", "por_sede": 1, "sedes": ["Palmira"],
                         "ancla": "creando un (1) cargo de Técnico Administrativo"},
    # Two created against one suppressed: a net gain of one.
    "ACU_CSU_034_2025": {"ciclo": "PIC_CO_2025", "por_sede": 2, "sedes": ["Manizales"],
                         "ancla": "para crear dos (2) cargo"},
}


def cargos_administrativos(ruta: Path, documento_id: str) -> list:
    spec = CARGOS_ADMIN.get(documento_id)
    if spec is None:
        return []

    for n_pagina, pagina in enumerate(T.paginas(ruta), 1):
        plano = T.normalizar(pagina)
        if spec["ancla"] not in plano:
            continue
        ubic = T.ubicacion(n_pagina, spec["ancla"])
        return [
            CargoCreado(
                tipo="cargo_creado", unidad=sede, tipo_cargo="ADMINISTRATIVO",
                cantidad=Decimal(spec["por_sede"]),
                cantidad_origen=str(spec["por_sede"]), ubicacion=ubic,
            )
            for sede in spec["sedes"]
        ]
    return []
