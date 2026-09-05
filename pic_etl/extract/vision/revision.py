"""The gate between what a model proposed and what the database loads.

Nothing here calls a model. Its whole job is to make a proposal readable: write
it where the build cannot see it, and say exactly how it differs from the
transcription already committed — figure by figure, with the citation, so a
person compares two claims rather than two files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from pic_etl.models import Extraction

RAIZ = Path(__file__).resolve().parents[3]
EXTRACCIONES = RAIZ / "extractions"
PROPUESTAS = EXTRACCIONES / "propuestas"

CABECERA = """\
# PROPUESTA — no la carga `pic-etl build`.
#
# La escribió un modelo leyendo las imágenes de las páginas. Una persona la
# compara contra el documento y, si es correcta, la mueve a extractions/. Hasta
# entonces no existe para la base de datos.
#
# El acta de al lado (.acta.yaml) dice con qué modelo, con qué instrucción y de
# qué páginas salió, y qué cifras el modelo vio y decidió no transcribir.
"""


def _volcar(datos: object) -> str:
    return yaml.safe_dump(datos, allow_unicode=True, sort_keys=False, width=200)


def escribir(extraccion: Extraction, acta: dict) -> tuple[Path, Path]:
    PROPUESTAS.mkdir(parents=True, exist_ok=True)
    base = extraccion.documento_id.lower()
    destino = PROPUESTAS / f"{base}.yaml"
    destino.write_text(
        CABECERA + _volcar(yaml.safe_load(extraccion.model_dump_json())),
        encoding="utf-8")
    (PROPUESTAS / f"{base}.acta.yaml").write_text(_volcar(acta), encoding="utf-8")
    return destino, PROPUESTAS / f"{base}.acta.yaml"


@dataclass(frozen=True)
class Cifra:
    ubicacion: str
    tipo: str
    valor: str

    def __str__(self) -> str:
        return f"{self.valor:>22}  {self.tipo:<22} {self.ubicacion}"


def _cifras(datos: dict) -> set[Cifra]:
    campos = ("valor_origen", "monto_origen", "cantidad_origen")
    salida = set()
    for f in datos.get("filas", []):
        literal = next((str(f[c]) for c in campos if f.get(c) is not None), "")
        salida.add(Cifra(str(f.get("ubicacion", "")), str(f.get("tipo", "")), literal))
    return salida


def comparar(documento_id: str) -> dict[str, list[Cifra]]:
    """Proposal against committed transcription, in both directions.

    `falta` is the interesting side: a figure the committed file has and the
    model did not produce is either a reading the model missed or one a person
    got wrong, and both are worth knowing before promoting anything.
    """
    base = documento_id.lower()
    propuesta = PROPUESTAS / f"{base}.yaml"
    comprometida = EXTRACCIONES / f"{base}.yaml"
    if not propuesta.exists():
        raise FileNotFoundError(f"no hay propuesta para {documento_id}")

    nuevas = _cifras(yaml.safe_load(propuesta.read_text(encoding="utf-8")))
    viejas = (_cifras(yaml.safe_load(comprometida.read_text(encoding="utf-8")))
              if comprometida.exists() else set())
    return {
        "coincide": sorted(nuevas & viejas, key=str),
        "sobra": sorted(nuevas - viejas, key=str),   # only the proposal has it
        "falta": sorted(viejas - nuevas, key=str),   # only the committed file has it
    }
