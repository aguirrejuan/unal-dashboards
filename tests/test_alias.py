"""L5 — resolve aliases at load, never at source.

Anexo 1 spells one sede four ways inside a single document, and Anexo 2 calls
Sede Orinoquía "Sede Arauca" (C2).
"""

from __future__ import annotations

import pytest

from pic_etl.load.aliases import AliasAmbiguo, Resolutor, UnidadDesconocida

FILAS = [
    {"ambito": "GLOBAL", "literal": "Sede Amazonia", "unidad_id": "AMAZONIA"},
    {"ambito": "GLOBAL", "literal": "AMAZONÍA", "unidad_id": "AMAZONIA"},
    {"ambito": "ANEXO2_PIC", "literal": "Sede Arauca", "unidad_id": "ORINOQUIA"},
]


@pytest.mark.parametrize("literal", ["Sede Amazonia", "AMAZONÍA", "Amazonía", "amazonia"])
def test_las_variantes_de_grafia_convergen(literal):
    assert Resolutor(FILAS).resolver(literal, documento_id="ANEXO1_PIC") == "AMAZONIA"


def test_un_alias_de_documento_resuelve_en_su_documento():
    assert Resolutor(FILAS).resolver("Sede Arauca", documento_id="ANEXO2_PIC") == "ORINOQUIA"


def test_un_alias_de_documento_no_se_filtra_a_otro():
    """Elsewhere "Arauca" is a department, and reading it as Orinoquía would be
    a claim no document makes."""
    with pytest.raises(UnidadDesconocida):
        Resolutor(FILAS).resolver("Sede Arauca", documento_id="ANEXO1_PIC")


def test_una_grafia_desconocida_falla(poblado):
    """I9 — a load never invents a dimension member."""
    with pytest.raises(UnidadDesconocida):
        Resolutor(FILAS).resolver("Sede Quimbaya", documento_id="ANEXO1_PIC")


def test_un_pliegue_ambiguo_falla():
    ambiguo = [
        {"ambito": "GLOBAL", "literal": "La Paz", "unidad_id": "LA_PAZ"},
        {"ambito": "GLOBAL", "literal": "LA PAZ", "unidad_id": "BOGOTA"},
    ]
    with pytest.raises(AliasAmbiguo):
        Resolutor(ambiguo).resolver("la paz", documento_id="X")
