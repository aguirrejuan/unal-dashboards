from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import insert

from pic_etl.load.loader import cargar_referencia
from pic_etl.schema import tables as T
from pic_etl.schema.dialect import crear_engine, crear_esquema


@pytest.fixture
def engine(tmp_path):
    e = crear_engine(tmp_path / "prueba.sqlite", recrear=True)
    crear_esquema(e)
    return e


@pytest.fixture
def poblado(engine):
    """A database with every curated dimension in place, and nothing else."""
    with engine.begin() as conn:
        cargar_referencia(conn)
    return engine


def declaracion(**kw):
    base = dict(
        tipo_declaracion="TRANSCRIPCION", medida_id="compromiso",
        ciclo_id="PIC_CO_2023", unidad_id="BOGOTA", periodo_id="NA",
        poblacion_id="NA", valor=1, documento_id="ANEXO1_PIC",
        ubicacion="Tabla 1, fila 1 'x', col 'y'", valor_origen="1",
        fecha_asercion=date(2026, 4, 13),
    )
    return {**base, **kw}


def insertar_declaracion(engine, **kw):
    with engine.begin() as conn:
        conn.execute(insert(T.declaracion), declaracion(**kw))


@pytest.fixture
def extracciones():
    """The real extractions, if they have been generated."""
    import yaml

    from pic_etl.cli import EXTRACCIONES
    from pic_etl.models import Extraction

    archivos = sorted(EXTRACCIONES.glob("*.yaml"))
    if not archivos:
        pytest.skip("extractions/ vacío; ejecute `pic-etl extract`")
    return [Extraction.model_validate(yaml.safe_load(a.read_text(encoding="utf-8")))
            for a in archivos]
