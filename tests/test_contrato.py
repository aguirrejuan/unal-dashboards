"""The Pydantic contract — what a hand-edited YAML file may and may not say."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from pic_etl.models import Extraction

HASH = "a" * 64
SOBRE = dict(documento_id="ANEXO1_PIC", fuente_sha256=HASH, fecha_asercion="2026-04-13")
FILA = dict(
    tipo="declaracion", medida_id="aumento_matriculados", ciclo_id="PIC_CO_2023",
    unidad="UNAL_TOTAL", periodo_id="2025-1", poblacion_id="MATRICULA_GLOBAL",
    valor="-681", valor_origen="-681",
    ubicacion="Tabla 5, fila 3 '2025-1S', col 'Aumento Matriculados'",
)


def _con(**cambios):
    return Extraction(**SOBRE, filas=[{**FILA, **cambios}])


def test_una_fila_valida_se_acepta():
    assert _con().filas[0].valor == Decimal("-681")


def test_una_clave_mal_escrita_falla():
    """The default would drop it silently — which is how a figure disappears
    from every view."""
    with pytest.raises(ValidationError, match="Extra inputs"):
        _con(medidaa_id="x")


@pytest.mark.parametrize("bruto", ["6.058.800.000", "31,5"])
def test_los_separadores_locales_se_rechazan(bruto):
    """`6.058.800.000` is six thousand million, not six. Normalising belongs to
    the parser; a separator arriving here means a hand edit slipped through."""
    with pytest.raises(ValidationError, match="separadores"):
        _con(valor=bruto)


def test_un_valor_no_numerico_se_rechaza():
    with pytest.raises(ValidationError):
        _con(valor="Bolsa")


def test_el_literal_es_obligatorio():
    with pytest.raises(ValidationError):
        _con(valor_origen="")


def test_la_ubicacion_es_obligatoria():
    with pytest.raises(ValidationError):
        _con(ubicacion="")


def test_un_hash_mal_formado_se_rechaza():
    with pytest.raises(ValidationError):
        Extraction(**{**SOBRE, "fuente_sha256": "nope"}, filas=[FILA])


def test_una_extraccion_vacia_se_rechaza():
    with pytest.raises(ValidationError):
        Extraction(**SOBRE, filas=[])


def test_una_fila_no_se_puede_mutar():
    """P1/L1 — an extraction is a transcription; nothing changes after parse."""
    with pytest.raises(ValidationError):
        _con().filas[0].valor = Decimal(1)


def test_los_decimales_sobreviven_intactos():
    """Column P holds `4895974740.75787`. A float would not survive the trip."""
    e = _con(valor="4895974740.75787", valor_origen="4895974740,75787")
    assert e.filas[0].valor == Decimal("4895974740.75787")
