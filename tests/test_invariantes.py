"""Each invariant must *fire*. A suite that only sees good data proves nothing."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from pic_etl.schema import tables as T
from pic_etl.schema.dialect import fk_activas
from tests.conftest import declaracion


def test_i9_las_claves_foraneas_estan_activas(engine):
    """PRAGMA foreign_keys defaults to OFF; without it I9 is a silent no-op and
    most of the suite below would pass on a broken database."""
    assert fk_activas(engine)


def test_i9_una_medida_inexistente_falla(poblado):
    with pytest.raises(IntegrityError), poblado.begin() as conn:
        conn.execute(insert(T.declaracion), declaracion(medida_id="matriculadoss"))


def test_i1_un_solo_preferido_por_grano(poblado):
    """The grain key holds one row per viewpoint. v1's index could not exist at
    all, because its grain columns were nullable and NULL ≠ NULL."""
    fila = dict(vista_id="UNAL", medida_id="compromiso", ciclo_id="PIC_CO_2023",
                unidad_id="BOGOTA", periodo_id="NA", declaracion_id=1)
    with poblado.begin() as conn:
        conn.execute(insert(T.declaracion), declaracion())
        conn.execute(insert(T.disposicion_grano), fila)
    with pytest.raises(IntegrityError), poblado.begin() as conn:
        conn.execute(insert(T.disposicion_grano), {**fila, "declaracion_id": 1})


def test_p5_ninguna_columna_de_grano_admite_nulos(poblado):
    """Sentinels, not NULL. This is what makes uniqueness enforceable."""
    with poblado.connect() as c:
        cols = {r[1]: r[3] for r in c.execute(text("PRAGMA table_info(declaracion)"))}
    for grano in ("ciclo_id", "unidad_id", "periodo_id", "poblacion_id", "medida_id"):
        assert cols[grano] == 1, f"{grano} admite NULL"


def test_i2_el_rollup_excluye_al_propio_ancestro(poblado):
    """`WHERE sede_id = :x` returned 41 + 25 = 66 for Medellín in v1."""
    with poblado.connect() as c:
        propios = c.execute(text(
            "SELECT count(*) FROM v_unidad_descendientes "
            "WHERE ancestro_id = descendiente_id")).scalar()
        medellin = c.execute(text(
            "SELECT count(*) FROM unidad_rollup "
            "WHERE ancestro_id='MEDELLIN' AND distancia > 0")).scalar()
    assert propios == 0
    assert medellin >= 1, "la prueba necesita al menos un descendiente real"


def test_i12_se_rechaza_un_ciclo_en_la_jerarquia():
    from pic_etl.load.rollup import CicloEnJerarquia, calcular_closure

    with pytest.raises(CicloEnJerarquia):
        calcular_closure([{"unidad_id": "A", "padre_id": "B"},
                          {"unidad_id": "B", "padre_id": "A"}])


def test_i3_un_stock_no_puede_declararse_aditivo_en_el_tiempo(poblado):
    with pytest.raises(IntegrityError), poblado.begin() as conn:
        conn.execute(insert(T.medida), dict(
            medida_id="x", nombre="x", unidad_medida="PERSONAS",
            tipo_agregacion="STOCK", aditiva_unidad=True, aditiva_tiempo=True))


def test_i6_un_documento_citado_no_lleva_ruta(poblado):
    with pytest.raises(IntegrityError), poblado.begin() as conn:
        conn.execute(insert(T.documento), dict(
            documento_id="X", tipo="ACUERDO", emisor="UNAL_CSU", estado="CITADO",
            ruta_archivo="/algo", soporte=None))


def test_i8_el_arrastre_no_es_reflexivo(poblado):
    with pytest.raises(IntegrityError), poblado.begin() as conn:
        conn.execute(insert(T.arrastre), dict(
            ciclo_origen_id="PIC_CO_2023", ciclo_destino_id="PIC_CO_2023",
            vigencia=2024, documento_id="ANEXO1_PIC", ubicacion="x"))


def test_seccion_3_2_una_sede_debe_ser_una_sede(poblado):
    """v2 writes `FOREIGN KEY (sede_id, 'SEDE')`, which is not legal SQL: a
    literal cannot appear in a foreign-key column list. SQLite accepts that DDL
    and then rejects every insert. A generated column enforces the real rule."""
    with pytest.raises(IntegrityError), poblado.begin() as conn:
        conn.execute(insert(T.unidad_academica), dict(
            unidad_id="NUEVA", nombre="Nueva", tipo="FACULTAD",
            padre_id="UNAL_TOTAL", sede_id="UNAL_TOTAL",
            valido_desde=date(2025, 1, 1)))


def test_i11_una_declaracion_repetida_no_se_duplica(poblado):
    from pic_etl.load.loader import insertar

    with poblado.begin() as conn:
        for _ in range(2):
            insertar(conn, T.declaracion, [declaracion()])
        n = conn.execute(text("SELECT count(*) FROM declaracion")).scalar()
    assert n == 1
