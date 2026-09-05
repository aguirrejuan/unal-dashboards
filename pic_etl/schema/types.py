"""Column types that survive the trip to SQLite without becoming floats."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, Text
from sqlalchemy.types import TypeDecorator


class Exacta(TypeDecorator):
    """A NUMERIC that keeps every digit.

    SQLite has no decimal type: a NUMERIC column stores REAL, so
    ``4895974740.75787`` comes back changed and ``$68 505 589 464`` stops
    reconciling to the peso. This stores the digits as TEXT there and returns a
    ``Decimal``, so what was transcribed is what is read back. Postgres has a
    real NUMERIC and uses it.

    Aggregation in SQLite views therefore needs ``CAST(valor AS REAL)``; that is
    for display. Reconciliation (I15) runs in Python over these Decimals, where
    the arithmetic is exact.
    """

    cache_ok = True
    impl = Numeric

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(Text())
        return dialect.type_descriptor(Numeric(asdecimal=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return str(value) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))
