"""The extraction contract.

One YAML file per source document, reviewed by a person and committed. These
models are what makes such a file safe to trust: they enforce, before a database
connection is even opened, the things the schema cannot reach.

Dimension references are carried as **literals**, exactly as the document spells
them, and resolved at load through the alias tables (L5). Anexo 1 spells one
sede four ways — `Sede Amazonia`, `Amazonia`, `AMAZONÍA`, `Amazonía` — and a
reviewer must see what was written, not a value someone already tidied.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

# frozen: an extraction is a transcription (P1/L1); nothing mutates after parse.
# extra="forbid": a mistyped key in a hand-edited file fails loudly instead of
# being dropped, which is precisely how a figure vanishes from every view.
_CONTRATO = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

Literal_ = Annotated[str, Field(min_length=1)]


class _Fila(BaseModel):
    model_config = _CONTRATO

    ubicacion: Literal_          # cell, table coordinate or paragraph anchor (L4)
    # A verbatim cell that carries meaning but no number. Tabla 9 writes 'Bolsa'
    # where a headcount belongs: the money is real, the quantity is not recorded
    # (§7.2, "unknown"). Keeping the word here loses nothing and corrupts no
    # measure.
    nota: str | None = None


def _a_decimal(v: object) -> Decimal:
    """Parse a value already in canonical form.

    Colombian sources write `6.058.800.000` and `31,5`; both are ambiguous to a
    naive parse. Normalising is the parser's job, so a separator arriving here
    means a hand-edited file slipped through and must fail rather than silently
    become a different number.
    """
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ValueError("un booleano no es una cantidad")
    if isinstance(v, int | float):
        return Decimal(str(v))
    s = str(v).strip()
    if "," in s or s.count(".") > 1:
        raise ValueError(
            f"{s!r} conserva separadores de miles o decimales locales; "
            "normalice en el extractor y deje el literal en valor_origen"
        )
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"{s!r} no es un número") from exc




class Declaracion(_Fila):
    """A measured number, transcribed or asserted about a set."""

    tipo: Literal["declaracion"]
    tipo_declaracion: Literal["TRANSCRIPCION", "AGREGADO"] = "TRANSCRIPCION"
    medida_id: Literal_

    # Grain — never Optional. Sentinels ('UNAL_TOTAL', 'TODOS', 'NA') stand in
    # where a dimension does not apply, so uniqueness is enforceable (P5).
    ciclo_id: Literal_
    unidad: Literal_             # literal spelling; resolved at load
    periodo_id: Literal_
    poblacion_id: Literal_

    valor: Decimal
    valor_origen: Literal_       # the literal, before parsing (L3)

    # An AGREGADO may name its components by their ubicacion; the loader turns
    # these into es_agregado_de rows, which makes "does the total equal the sum
    # of its parts?" a runnable test (I15) instead of an argument.
    componentes: list[str] = Field(default_factory=list)

    @field_validator("valor", mode="before")
    @classmethod
    def _v(cls, v: object) -> Decimal:
        return _a_decimal(v)


class Proyecto(_Fila):
    tipo: Literal["proyecto"]
    proyecto_id: Literal_
    ciclo_id: Literal_
    unidad: Literal_
    numero: int
    nombre: Literal_
    linea_id: str | None = None
    sublinea_id: str | None = None


class Compromiso(_Fila):
    tipo: Literal["compromiso"]
    proyecto_id: Literal_
    unidad: Literal_
    cupos: int
    es_rezago: bool = False
    ciclo_origen_id: str | None = None


class CargoCreado(_Fila):
    tipo: Literal["cargo_creado"]
    unidad: Literal_
    tipo_cargo: Literal_
    cantidad: Decimal            # Palmira: 31,5 ETC — fractional, so not an int
    cantidad_origen: Literal_
    costo_total: Decimal | None = None
    costo_origen: str | None = None

    @field_validator("cantidad", "costo_total", mode="before")
    @classmethod
    def _v(cls, v: object) -> Decimal | None:
        return None if v is None else _a_decimal(v)


class PresupuestoRubro(_Fila):
    """Money against a spending line. Kept out of `declaracion` because that
    grain has no rubro: four sublíneas would land on one row and read as four
    rival claims about one number."""

    tipo: Literal["presupuesto_rubro"]
    presupuesto_id: Literal_
    ciclo_id: Literal_
    rubro_id: Literal_
    unidad: Literal_
    concepto: str | None = None
    cantidad: Decimal | None = None      # None where the source writes 'Bolsa'
    monto: Decimal
    monto_origen: Literal_

    @field_validator("monto", "cantidad", mode="before")
    @classmethod
    def _v(cls, v: object) -> Decimal | None:
        return None if v is None else _a_decimal(v)


class Asignacion(_Fila):
    tipo: Literal["asignacion"]
    asignacion_id: Literal_
    unidad: Literal_
    ciclo_id: Literal_
    vigencia: int                # fiscal year — NOT the cycle year
    fuente_id: Literal_
    tipo_flujo: Literal_
    momento: Literal_
    recurso: str | None = None
    monto: Decimal
    monto_origen: Literal_

    @field_validator("monto", mode="before")
    @classmethod
    def _v(cls, v: object) -> Decimal:
        return _a_decimal(v)


class CoberturaTerritorial(_Fila):
    tipo: Literal["cobertura_territorial"]
    ciclo_id: Literal_
    unidad: Literal_
    periodo_id: Literal_
    cuartil_id: Literal_
    via_id: Literal_
    estudiantes: int


Fila = Annotated[
    Union[
        Declaracion,
        Proyecto,
        Compromiso,
        CargoCreado,
        Asignacion,
        CoberturaTerritorial,
        PresupuestoRubro,
    ],
    Field(discriminator="tipo"),
]


class Extraction(BaseModel):
    """One source document, transcribed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    documento_id: Literal_
    # Hash of the file this was read from. A changed source invalidates the
    # extraction, so the build fails rather than loading a transcription of a
    # document that no longer exists.
    fuente_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    fecha_asercion: date
    filas: list[Fila]

    @field_validator("filas")
    @classmethod
    def _no_vacio(cls, v: list) -> list:
        if not v:
            raise ValueError("una extracción sin filas no aporta nada; omita el archivo")
        return v
