"""The corpus figures the dashboard will be judged on."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from pic_etl.load.loader import cargar_extracciones, materializar_grano


@pytest.fixture
def construido(poblado, extracciones):
    with poblado.begin() as conn:
        cargar_extracciones(conn, extracciones)
        materializar_grano(conn)
    return poblado


def _uno(engine, sql):
    with engine.connect() as c:
        return c.execute(text(sql)).scalar()


def test_e6_los_periodos_suman_menos_689(construido):
    """Tabla 5 nets −689. The report headlines −1 168, having dropped the two
    positive periods. Both figures must survive into the database."""
    total = _uno(construido, """
        SELECT sum(CAST(valor AS REAL)) FROM declaracion
        WHERE medida_id = 'aumento_matriculados'
    """)
    assert total == -689


def test_e1_la_columna_n_suma_68_505_589_464(construido):
    total = _uno(construido, """
        SELECT sum(CAST(monto AS REAL)) FROM asignacion WHERE fuente_id = 'BASE_2025'
    """)
    assert Decimal(str(total)) == Decimal("68505589464")


def test_e1_bogota_repite_su_indexacion_como_base(construido):
    """N15 = P15 exactly — a column that reconciles to nothing."""
    with construido.connect() as c:
        n, p = (c.execute(text(
            "SELECT monto FROM asignacion WHERE ubicacion = :u"),
            {"u": f"Registro_Proyectos_2025!{col}15"}).scalar() for col in ("N", "P"))
    assert Decimal(n) == Decimal(p)


def test_el_embudo_de_pic_2023_se_conserva(construido):
    """1 818 comprometidos → 1 848 ofertados → 1 161 matriculados."""
    def total(medida):
        return _uno(construido, f"""
            SELECT CAST(valor AS REAL) FROM declaracion
            WHERE medida_id = '{medida}' AND unidad_id = 'UNAL_TOTAL'
              AND ciclo_id = 'PIC_CO_2023' AND tipo_declaracion = 'AGREGADO'
            LIMIT 1
        """)
    assert total("compromiso") == 1818
    assert total("cupos_ofertados") == 1848
    assert total("matriculados") == 1161


def test_c2_sede_arauca_se_carga_como_orinoquia(construido):
    unidad = _uno(construido, """
        SELECT unidad_id FROM proyecto WHERE nombre LIKE '%Sede Arauca%'
    """)
    assert unidad == "ORINOQUIA"


def test_v2_la_paz_no_tiene_financiacion(construido):
    """Absence, not a zero. A row that is not there and a measured 0 mean
    different things (§7.2)."""
    n = _uno(construido, """
        SELECT count(*) FROM asignacion WHERE unidad_id = 'LA_PAZ'
    """)
    assert n == 0


def test_v4_el_cuartil_no_observado_no_tiene_hechos(construido):
    """A dimension member with no facts must stay distinguishable from a zero,
    which is what `observado` is for."""
    with construido.connect() as c:
        assert c.execute(text(
            "SELECT observado FROM cuartil_prioridad WHERE cuartil_id='C2'")).scalar() == 0
        assert c.execute(text(
            "SELECT count(*) FROM cobertura_territorial WHERE cuartil_id='C2'")).scalar() == 0


def test_la_vista_devuelve_una_fila_por_grano_y_vista(construido):
    """v1's view returned both 1 161 and 1 043 through the sanctioned path and
    SUM produced 2 204."""
    duplicados = _uno(construido, """
        SELECT count(*) FROM (
          SELECT vista_id, medida_id, ciclo_id, unidad_id, periodo_id
          FROM v_declaracion
          GROUP BY 1,2,3,4,5 HAVING count(*) > 1)
    """)
    assert duplicados == 0
