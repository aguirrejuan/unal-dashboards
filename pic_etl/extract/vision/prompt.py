"""What the model is told, assembled from the reference files.

The vocabularies are not repeated here by hand. They are read from the same YAML
the loader reads, so a new `fuente_id` reaches the prompt the moment it reaches
the database, and the prompt cannot drift into offering the model an id that no
longer exists. That is the whole point of building the instruction instead of
writing it.
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

import yaml

REFERENCIA = Path(__file__).resolve().parents[2] / "reference"


def _leer(nombre: str) -> dict:
    return yaml.safe_load((REFERENCIA / nombre).read_text(encoding="utf-8")) or {}


def _ids(filas: list[dict], clave: str) -> list[str]:
    return sorted({str(f[clave]) for f in filas if f.get(clave) is not None})


def vocabularios() -> dict[str, list[str]]:
    """The closed sets a row may reference. Anything outside them is invented."""
    voc = _leer("vocabularios.yaml")
    ciclos = _leer("ciclo.yaml")
    return {
        "medida_id": _ids(_leer("medida.yaml")["medida"], "medida_id"),
        "ciclo_id": _ids(ciclos["ciclo"], "ciclo_id"),
        "periodo_id": _ids(_leer("periodo.yaml")["periodo"], "periodo_id"),
        "poblacion_id": _ids(_leer("poblacion.yaml")["poblacion"], "poblacion_id"),
        "fuente_id": _ids(ciclos["fuente_financiacion"], "fuente_id"),
        "via_id": _ids(ciclos["via_admision"], "via_id"),
        "cuartil_id": _ids(ciclos["cuartil_prioridad"], "cuartil_id"),
        "tipo_flujo": _ids(voc["tipo_flujo"], "tipo_flujo_id"),
        "momento": _ids(voc["momento_presupuestal"], "momento_presupuestal_id"),
        "tipo_cargo": _ids(voc["tipo_cargo"], "tipo_cargo_id"),
        "unidad": _ids(_leer("unidad_academica.yaml")["unidad_academica"], "unidad_id"),
        "rubro_id": _ids(_leer("rubro.yaml")["rubro"], "rubro_id"),
    }


INSTRUCCION = textwrap.dedent("""\
    Transcribe cifras de un documento oficial colombiano escaneado. No las
    interpretas ni las corriges: las copias.

    Reglas, en orden de importancia:

    1. Sólo transcribes lo que ves. Si una cifra está borrosa, incompleta o
       tapada, no la incluyes. Una fila omitida se nota y se corrige; una fila
       inventada se carga en una base de datos y nadie la vuelve a mirar.

    2. `*_origen` es el literal exacto, con los puntos y las comas del
       documento: "46.116.228.838", no 46116228838. El campo numérico lleva el
       valor ya parseado. Los dos deben corresponder.

    3. `ubicacion` dice dónde está la cifra, con esta forma:
       "p.N, <ancla>" donde el ancla es un fragmento textual corto que aparece
       junto a la cifra en esa página — el encabezado de la columna, el nombre
       de la fila, el rótulo de la sección. Ejemplo:
       "p.2, UNIDAD 225701, REC 10". Sin ubicación una cifra no es evidencia.

    4. Los identificadores salen de las listas cerradas que se te dan. Si
       ninguno encaja, omite la fila y dilo en `nota`. No inventes uno nuevo ni
       uses el más parecido.

    5. Si el documento afirma un total además de sus partes, transcribe las dos
       cosas: el total como `declaracion` con tipo_declaracion AGREGADO, y las
       partes como sus propias filas. Que el total no cuadre con las partes es
       un hallazgo, y sólo aparece si ambos están.

    6. Una resolución del Ministerio distribuye dinero: normalmente son filas
       `asignacion`. Un acuerdo del Consejo Superior crea cargos: normalmente
       son filas `cargo_creado`. No fuerces el resto.

    Devuelve únicamente las filas que hayas leído en las páginas que se te
    muestran.
    """)


def construir(documento_id: str, tipo: str, titulo: str) -> str:
    voc = vocabularios()
    listas = "\n".join(
        f"  {campo}: {', '.join(valores)}" for campo, valores in voc.items()
    )
    return (
        f"{INSTRUCCION}\n"
        f"Documento: {documento_id} — {titulo} (tipo {tipo}).\n\n"
        f"Identificadores permitidos:\n{listas}\n"
    )


def huella(texto: str) -> str:
    """The prompt's own hash, recorded beside a transcription.

    A transcription is only reproducible if what was asked is known. When the
    instruction changes, the hash changes, and the earlier proposals are
    visibly the product of a different question.
    """
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()
