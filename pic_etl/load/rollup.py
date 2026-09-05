"""The academic-unit closure, computed in Python.

v2 has this maintained by a trigger. The hierarchy is about thirty rows loaded
wholesale, so a walk here is simpler, testable without a database, and ports to
Postgres unchanged. Cycle detection (I12) happens in the same pass.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


class CicloEnJerarquia(ValueError):
    """A → B → A. Would make the closure infinite and every subtotal wrong."""


def calcular_closure(filas: Iterable[Mapping]) -> list[dict]:
    """Return every (ancestro, descendiente, distancia) pair, `distancia` 0 = self.

    Aggregation must go through this with `distancia > 0`. Never
    `WHERE sede_id = :x`, which includes the sede's own row and returned
    41 + 25 = 66 for Medellín in v1.
    """
    padre: dict[str, str | None] = {f["unidad_id"]: f.get("padre_id") for f in filas}

    pares: list[dict] = []
    for unidad in padre:
        pares.append({"ancestro_id": unidad, "descendiente_id": unidad, "distancia": 0})

        visto = {unidad}
        actual, distancia = padre[unidad], 1
        while actual is not None:
            if actual in visto:
                raise CicloEnJerarquia(
                    f"ciclo en unidad_academica alcanzando {actual!r} desde {unidad!r}"
                )
            if actual not in padre:
                raise ValueError(f"{unidad!r} cuelga de {actual!r}, que no existe")
            visto.add(actual)
            pares.append(
                {"ancestro_id": actual, "descendiente_id": unidad, "distancia": distancia}
            )
            actual, distancia = padre[actual], distancia + 1

    return pares


def orden_por_profundidad(filas: list[Mapping]) -> list[Mapping]:
    """Sort so a parent is always inserted before its children.

    `unidad_academica` and `rubro` are self-referential, so `sorted_tables`
    cannot help; a foreign key would fail on the first child.
    """
    por_id = {f["unidad_id"]: f for f in filas}

    def profundidad(f: Mapping) -> int:
        d, actual, visto = 0, f.get("padre_id"), set()
        while actual is not None:
            if actual in visto:
                raise CicloEnJerarquia(f"ciclo alcanzando {actual!r}")
            visto.add(actual)
            d += 1
            actual = por_id[actual].get("padre_id") if actual in por_id else None
        return d

    return sorted(filas, key=profundidad)
