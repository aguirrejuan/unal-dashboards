"""Resolving the many spellings of one unit (L5)."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping


class UnidadDesconocida(KeyError):
    """A spelling no alias covers. I9 — a load never invents a dimension member,
    so this fails the build instead of quietly detaching a figure."""


class AliasAmbiguo(ValueError):
    """One folded spelling reaching two different units."""


def normalizar(s: str) -> str:
    """Fold case, accents and whitespace.

    Anexo 1 writes `Amazonia`, `Amazonía` and `AMAZONÍA` for one sede; folding
    collapses them. It does **not** collapse `Sede Arauca` onto Orinoquía —
    that is a claim about the world and needs an explicit, document-scoped row.
    """
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.casefold().split())


class Resolutor:
    def __init__(self, filas: Iterable[Mapping]) -> None:
        self._exacto: dict[tuple[str, str], str] = {}
        self._plegado: dict[tuple[str, str], set[str]] = {}
        for f in filas:
            ambito, literal, unidad = f["ambito"], f["literal"], f["unidad_id"]
            self._exacto[(ambito, literal)] = unidad
            self._plegado.setdefault((ambito, normalizar(literal)), set()).add(unidad)

    def resolver(self, literal: str, *, documento_id: str) -> str:
        """Document-scoped first, then global; exact spelling before folded."""
        for clave in (
            (documento_id, literal),
            ("GLOBAL", literal),
        ):
            if clave in self._exacto:
                return self._exacto[clave]

        for ambito in (documento_id, "GLOBAL"):
            candidatos = self._plegado.get((ambito, normalizar(literal)))
            if not candidatos:
                continue
            if len(candidatos) > 1:
                raise AliasAmbiguo(
                    f"{literal!r} en {documento_id} pliega a {sorted(candidatos)}"
                )
            return next(iter(candidatos))

        raise UnidadDesconocida(
            f"{literal!r} (documento {documento_id}) no coincide con ningún alias; "
            "añádalo a reference/unidad_alias.yaml"
        )

    def filas_para_carga(self, filas: Iterable[Mapping]) -> list[dict]:
        return [
            {
                "ambito": f["ambito"],
                "literal": f["literal"],
                "literal_norm": normalizar(f["literal"]),
                "unidad_id": f["unidad_id"],
            }
            for f in filas
        ]
