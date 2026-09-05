"""The model-assisted step, exercised without a model.

The graph is worth testing precisely because the model is not: what must hold is
the control flow around it — that a bad row goes back for repair instead of
reaching a person, that repairs replace rather than accumulate, that a proposal
never lands where the build can see it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pic_etl.extract.vision import grafo, prompt, revision
from pic_etl.models import Extraction

RAIZ = Path(__file__).resolve().parent.parent
PDF = RAIZ / "extracted/PIC-Información/PIC-Info_/016468 01 AGO 2025.pdf"
SHA = "893d5345428a5d4c3389b2e80c3a356be1936da71a534e9b13bd7adc9a260d44"


def _fila(pagina: int = 2, monto: str = "46.116.228.838") -> dict:
    return {"tipo": "asignacion", "asignacion_id": "X|UNAL|REC_10",
            "unidad": "UNAL_TOTAL", "ciclo_id": "PIC_CO_2025", "vigencia": 2025,
            "fuente_id": "REC_10", "tipo_flujo": "ADICION_BASE_RECURRENTE",
            "momento": "ASIGNADO", "monto": monto.replace(".", ""),
            "monto_origen": monto, "ubicacion": f"p.{pagina}, UNIDAD 225701, REC 10"}


class ModeloFalso:
    """Returns what it is told to, and counts how often it was asked."""

    def __init__(self, respuestas: list[grafo.Lote]):
        self.respuestas = list(respuestas)
        self.llamadas = 0

    def invoke(self, _mensajes):
        self.llamadas += 1
        return self.respuestas.pop(0) if self.respuestas else grafo.Lote(filas=[])


def _correr(respuestas, paginas):
    modelo = ModeloFalso(respuestas)
    ext, acta = grafo.transcribir_documento(
        "RES_MEN_016468_2025", PDF, SHA, titulo="016468", tipo="RESOLUCION",
        paginas_=paginas, modelo=modelo)
    return ext, acta, modelo


@pytest.mark.skipif(not PDF.exists(), reason="corpus ausente")
def test_una_pagina_limpia_produce_una_propuesta_valida():
    ext, acta, modelo = _correr(
        [grafo.Lote(filas=[_fila(2)])], [2])
    assert modelo.llamadas == 1
    assert len(ext.filas) == 1
    assert ext.filas[0].monto_origen == "46.116.228.838"
    assert acta["prompt_sha256"] and acta["modelo"]


@pytest.mark.skipif(not PDF.exists(), reason="corpus ausente")
def test_una_ubicacion_de_otra_pagina_se_devuelve_al_modelo():
    """The one check a model reliably fails: citing page 2 while shown page 3.
    It must be repaired automatically, not surface to a reviewer."""
    ext, _, modelo = _correr(
        [grafo.Lote(filas=[_fila(9)]),          # cites the wrong page
         grafo.Lote(filas=[_fila(2)])],         # corrected
        [2])
    assert modelo.llamadas == 2, "el error debió volver al modelo"
    assert len(ext.filas) == 1, "la reparación reemplaza, no se acumula"
    assert ext.filas[0].ubicacion.startswith("p.2")


@pytest.mark.skipif(not PDF.exists(), reason="corpus ausente")
def test_el_reintento_esta_acotado():
    """A model that never corrects itself must stop costing money."""
    malas = [grafo.Lote(filas=[_fila(9)]) for _ in range(6)]
    _, acta, modelo = _correr(malas, [2])
    assert modelo.llamadas == grafo.REINTENTOS + 1
    assert acta["error_final"], "el acta debe decir que quedó en error"


@pytest.mark.skipif(not PDF.exists(), reason="corpus ausente")
def test_recorre_todas_las_paginas_pedidas():
    ext, _, modelo = _correr(
        [grafo.Lote(filas=[_fila(2)]), grafo.Lote(filas=[_fila(3, "9.561.136.948")])],
        [2, 3])
    assert modelo.llamadas == 2
    assert {f.ubicacion[:3] for f in ext.filas} == {"p.2", "p.3"}


def test_la_propuesta_no_la_ve_la_construccion(tmp_path, monkeypatch):
    """`build` globs extractions/*.yaml, not recursively. A proposal sitting in
    extractions/propuestas/ must be invisible to it — that is the whole gate."""
    from pic_etl import cli

    assert "propuestas" not in str(cli.EXTRACCIONES.glob("*.yaml"))
    vistos = {p.name for p in cli.EXTRACCIONES.glob("*.yaml")}
    assert vistos, "debe haber extracciones comprometidas"
    if revision.PROPUESTAS.exists():
        for p in revision.PROPUESTAS.glob("*.yaml"):
            assert p.name not in vistos


def test_el_prompt_ofrece_solo_identificadores_que_existen():
    """A prompt that lists an id the database rejects wastes a call and invites
    a row nobody can load. The lists are read from the same reference files."""
    voc = prompt.vocabularios()
    assert "REC_10" in voc["fuente_id"] and "PIC_CO_2025" in voc["ciclo_id"]
    texto = prompt.construir("X", "RESOLUCION", "t")
    for campo, valores in voc.items():
        assert valores, f"{campo} llegó vacío al prompt"
        assert valores[0] in texto
    assert prompt.huella(texto) != prompt.huella(texto + " ")


def test_la_comparacion_señala_lo_que_falta_y_lo_que_sobra(tmp_path, monkeypatch):
    monkeypatch.setattr(revision, "PROPUESTAS", tmp_path / "propuestas")
    monkeypatch.setattr(revision, "EXTRACCIONES", tmp_path)
    ext = Extraction.model_validate(
        {"documento_id": "RES_MEN_016468_2025", "fuente_sha256": SHA,
         "fecha_asercion": "2025-08-01", "filas": [_fila(2), _fila(3, "9.561.136.948")]})
    revision.escribir(ext, {"modelo": "falso"})
    (tmp_path / "res_men_016468_2025.yaml").write_text(
        yaml.safe_dump(yaml.safe_load(
            Extraction.model_validate(
                {"documento_id": "RES_MEN_016468_2025", "fuente_sha256": SHA,
                 "fecha_asercion": "2025-08-01",
                 "filas": [_fila(2), _fila(4, "1.234")]}).model_dump_json())),
        encoding="utf-8")
    d = revision.comparar("RES_MEN_016468_2025")
    assert len(d["coincide"]) == 1
    assert [c.valor for c in d["sobra"]] == ["9.561.136.948"]
    assert [c.valor for c in d["falta"]] == ["1.234"]


def test_de_la_propuesta_a_una_fila_en_la_base(poblado, tmp_path, monkeypatch):
    """The whole point of the step: a scan a model read becomes a queryable row.

    Every stage runs — graph, proposal, promotion, load — with only the model
    replaced. What it proves is that the promoted YAML is an ordinary extraction:
    the loader has no idea a model was involved, and that is the design.
    """
    from sqlalchemy import text

    from pic_etl.load.loader import cargar_extracciones

    monkeypatch.setattr(revision, "PROPUESTAS", tmp_path / "propuestas")
    monkeypatch.setattr(revision, "EXTRACCIONES", tmp_path)

    if not PDF.exists():
        pytest.skip("corpus ausente")
    ext, acta, _ = _correr([grafo.Lote(filas=[_fila(2)])], [2])
    propuesta, _acta = revision.escribir(ext, acta)

    # Promotion is just a validated copy into the directory the build reads.
    promovida = Extraction.model_validate(
        yaml.safe_load(propuesta.read_text(encoding="utf-8")))

    with poblado.begin() as conn:
        cuenta = cargar_extracciones(conn, [promovida])
    assert cuenta["asignacion"] == 1

    with poblado.connect() as c:
        fila = c.execute(text(
            "SELECT monto_origen, ubicacion, documento_id FROM asignacion")).one()
    assert fila.monto_origen == "46.116.228.838"
    assert fila.ubicacion == "p.2, UNIDAD 225701, REC 10"
    assert fila.documento_id == "RES_MEN_016468_2025"


def test_el_acta_deja_reproducible_la_transcripcion(tmp_path, monkeypatch):
    """A transcription is only auditable if what was asked is recorded: which
    model, which instruction, which pages, at what resolution."""
    monkeypatch.setattr(revision, "PROPUESTAS", tmp_path / "propuestas")
    if not PDF.exists():
        pytest.skip("corpus ausente")
    ext, acta, _ = _correr([grafo.Lote(filas=[_fila(2)])], [2])
    _, ruta = revision.escribir(ext, acta)
    guardada = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert guardada["modelo"] and len(guardada["prompt_sha256"]) == 64
    assert guardada["paginas"] == [2] and guardada["dpi"] == 200
    assert "generado" in guardada
