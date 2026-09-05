"""The model-assisted transcription step, as a LangGraph state machine.

Why a graph and not a function call. The valuable structure here is a loop and a
gate, not a chain: the model reads a page, the result is validated against the
same Pydantic contract the loader enforces, and a failure goes back to the model
with the error rather than to a person. Bounded retries, one page at a time,
and a checkpoint after each — so a run that dies on page seven of nine resumes
instead of paying for the first six again.

Why it stops at YAML. The graph writes a *proposal* under
`extractions/propuestas/`. It never writes `extractions/`, and `pic-etl build`
cannot see it. A person reads the proposal against the page image and promotes
it. That boundary is what lets a model contribute without costing the pipeline
its determinism: the model's output becomes a reviewed, committed, hashed
artifact, and everything downstream of it is a pure function of files in git.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field, ValidationError

from pic_etl.models import Extraction, Fila

from . import paginas, prompt

MODELO = "claude-opus-4-5-20251101"
REINTENTOS = 2


class Lote(BaseModel):
    """What the model returns for one page.

    A wrapper rather than a bare list: a discriminated union needs a named field
    to hang a tool schema off, and `omitido` gives the model somewhere to say
    «vi una cifra y no la transcribí, por esto» instead of silently dropping it.
    """

    filas: list[Fila] = Field(default_factory=list)
    omitido: list[str] = Field(
        default_factory=list,
        description="Cifras vistas y no transcritas, con el motivo.",
    )


class Estado(TypedDict, total=False):
    """Two row buckets, deliberately.

    A single accumulating list cannot express a retry: the rows to discard are
    exactly the ones the failed attempt produced, and those are not identifiable
    after the fact — a row that cited the wrong page does not carry the right
    page's prefix to filter on. `borrador` holds the attempt in hand and is
    overwritten wholesale; `confirmadas` only ever grows, one accepted page at
    a time.
    """

    documento_id: str
    titulo: str
    tipo: str
    ruta: str
    sha256: str
    prompt: str
    pendientes: list[int]        # pages not yet read
    pagina: int                  # the page in hand
    intento: int
    error: str | None
    borrador: list               # rows from the current attempt
    confirmadas: list            # rows from pages already accepted
    omitido: Annotated[list, lambda a, b: a + b]
    diario: Annotated[list, lambda a, b: a + b]


@dataclass
class Contexto:
    """Everything the nodes need that is not state: the model and the images."""

    modelo: Any
    imagenes: dict[int, paginas.Pagina] = field(default_factory=dict)


def _modelo(nombre: str = MODELO, temperatura: float = 0.0):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "falta ANTHROPIC_API_KEY. La transcripción es el único paso que "
            "necesita red; `build`, `verify` y `publish` no."
        )
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=nombre, temperature=temperatura,
                         max_tokens=8000).with_structured_output(Lote)


# --------------------------------------------------------------------- nodos

def preparar(estado: Estado, ctx: Contexto) -> dict:
    ruta = Path(estado["ruta"])
    numeros = estado.get("pendientes") or [p for p in range(1, paginas.contar(ruta) + 1)]
    ctx.imagenes = {p.numero: p for p in paginas.render(ruta, numeros)}
    return {"pendientes": numeros, "intento": 0, "error": None,
            "borrador": [], "confirmadas": [],
            "diario": [f"{len(numeros)} páginas renderizadas a {paginas.DPI} dpi"]}


def transcribir(estado: Estado, ctx: Contexto) -> dict:
    pagina = estado["pendientes"][0]
    imagen = ctx.imagenes[pagina]
    aviso = ""
    if estado.get("error"):
        aviso = (f"\n\nEl intento anterior no validó:\n{estado['error']}\n"
                 f"Corrige sólo lo que el error señala. Si la cifra no se puede "
                 f"transcribir correctamente, omítela y explícalo en `omitido`.")

    mensaje = {"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": imagen.data_url}},
        {"type": "text", "text": (
            f"{estado['prompt']}\n"
            f"Esta es la página {pagina}. Usa exactamente «p.{pagina}» al "
            f"empezar cada `ubicacion`.{aviso}")},
    ]}
    lote: Lote = ctx.modelo.invoke([mensaje])
    return {"pagina": pagina,
            "borrador": [f.model_dump(mode="json") for f in lote.filas],
            "omitido": [f"p.{pagina}: {o}" for o in lote.omitido],
            "diario": [f"p.{pagina}: {len(lote.filas)} filas, "
                       f"{len(lote.omitido)} omitidas"]}


def validar(estado: Estado) -> dict:
    """The contract the loader enforces, applied before a person reads anything.

    Cheap here, expensive later: a row that fails validation at build time is
    found after someone has already approved it.
    """
    problemas: list[str] = []
    pagina = estado["pagina"]
    borrador = estado.get("borrador") or []
    for i, fila in enumerate(borrador):
        if not str(fila.get("ubicacion", "")).startswith(f"p.{pagina}"):
            problemas.append(
                f"fila {i}: `ubicacion` es {fila.get('ubicacion')!r}; "
                f"debe empezar por «p.{pagina}»")
    # A page with no figures on it is a fine answer, so an empty draft is not an
    # error. `Extraction` rejects an empty row list, which is right for a whole
    # document and wrong for one page of it.
    if borrador:
        try:
            Extraction(documento_id=estado["documento_id"],
                       fuente_sha256=estado["sha256"],
                       fecha_asercion=date.today(), filas=borrador)
        except ValidationError as e:
            problemas.extend(_legible(e))
    return {"error": "\n".join(problemas[:12]) or None}


def _legible(e: ValidationError) -> list[str]:
    """Pydantic's own rendering is for programmers; the model needs the fix."""
    return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in e.errors()][:12]


def avanzar(estado: Estado) -> dict:
    """Accept the page in hand and move on.

    Rows are kept even when the last attempt still failed: a reviewer reading
    the proposal beside the page is better placed to fix one row than the model
    is on a third try, and the acta records that it ended in error.
    """
    return {"confirmadas": estado.get("confirmadas", []) + (estado.get("borrador") or []),
            "borrador": [],
            "pendientes": estado["pendientes"][1:],
            "intento": 0}


def reintentar(estado: Estado) -> dict:
    """Ask again. `borrador` is overwritten by the next call, so nothing to
    clean up — which is the reason the two buckets exist."""
    return {"intento": estado["intento"] + 1}


def _tras_validar(estado: Estado) -> Literal["reintentar", "avanzar"]:
    if estado.get("error") and estado["intento"] < REINTENTOS:
        return "reintentar"
    return "avanzar"


def _tras_avanzar(estado: Estado) -> Literal["transcribir", "fin"]:
    return "transcribir" if estado["pendientes"] else "fin"


# --------------------------------------------------------------------- grafo

def construir(modelo=None):
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    ctx = Contexto(modelo=modelo if modelo is not None else _modelo())
    g = StateGraph(Estado)
    g.add_node("preparar", lambda e: preparar(e, ctx))
    g.add_node("transcribir", lambda e: transcribir(e, ctx))
    g.add_node("validar", validar)
    g.add_node("reintentar", reintentar)
    g.add_node("avanzar", avanzar)

    g.add_edge(START, "preparar")
    g.add_edge("preparar", "transcribir")
    g.add_edge("transcribir", "validar")
    g.add_conditional_edges("validar", _tras_validar,
                            {"reintentar": "reintentar", "avanzar": "avanzar"})
    g.add_edge("reintentar", "transcribir")
    g.add_conditional_edges("avanzar", _tras_avanzar,
                            {"transcribir": "transcribir", "fin": END})
    return g.compile(checkpointer=MemorySaver())


def transcribir_documento(documento_id: str, ruta: Path, sha256: str, *,
                          titulo: str, tipo: str, paginas_: list[int] | None = None,
                          modelo=None) -> tuple[Extraction, dict]:
    """Run the graph and return the proposal plus how it was produced."""
    texto = prompt.construir(documento_id, tipo, titulo)
    grafo = construir(modelo)
    inicio = datetime.now(timezone.utc)
    final = grafo.invoke(
        {"documento_id": documento_id, "titulo": titulo, "tipo": tipo,
         "ruta": str(ruta), "sha256": sha256, "prompt": texto,
         "pendientes": paginas_ or [], "borrador": [], "confirmadas": [],
         "omitido": [], "diario": []},
        config={"configurable": {"thread_id": documento_id},
                "recursion_limit": 200},
    )
    filas = final["confirmadas"]
    extraccion = Extraction(
        documento_id=documento_id, fuente_sha256=sha256,
        fecha_asercion=date.today(), filas=filas,
    )
    acta = {
        "modelo": MODELO,
        "prompt_sha256": prompt.huella(texto),
        "paginas": sorted({int(str(f["ubicacion"]).split(",")[0][2:])
                           for f in filas}),
        "dpi": paginas.DPI,
        "generado": inicio.isoformat(timespec="seconds"),
        "omitido": final.get("omitido", []),
        "diario": final.get("diario", []),
        "error_final": final.get("error"),
    }
    return extraccion, acta
