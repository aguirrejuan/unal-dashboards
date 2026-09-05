"""pic-etl — extract, build, verify."""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import yaml
from sqlalchemy import select

import re
from datetime import date

from pic_etl.extract import acuerdos, anexo1, anexo2, informes, texto_pdf
from pic_etl.load.loader import (
    cargar_extracciones,
    cargar_referencia,
    materializar_grano,
    sha256_de,
)
from pic_etl.models import Extraction
from pic_etl.schema import tables as T
from pic_etl.schema.dialect import crear_engine, crear_esquema

RAIZ = Path(__file__).resolve().parent.parent
EXTRACCIONES = RAIZ / "extractions"
REFERENCIA = RAIZ / "pic_etl" / "reference"


def _corpus(base: Path) -> dict[str, Path]:
    """Locate the two structured sources. The corpus directory name is stored in
    Unicode NFD on this filesystem, so it is globbed rather than spelled."""
    def uno(patron: str) -> Path:
        hits = glob.glob(str(base / patron))
        if not hits:
            raise SystemExit(f"no encuentro {patron} bajo {base}")
        return Path(hits[0])

    return {
        "ANEXO1_PIC": uno("*/Pic_Info-2/Anexo 1*.docx"),
        "ANEXO2_PIC": uno("*/Pic_Info-2/Anexo 2*.xlsx"),
    }


def _cuartiles() -> dict[str, str]:
    datos = yaml.safe_load((REFERENCIA / "ciclo.yaml").read_text(encoding="utf-8"))
    return {r["notacion"]: r["cuartil_id"] for r in datos["cuartil_prioridad"]}


def _rubros() -> dict[str, str]:
    """Spending-line name → id, folded. A name the reference does not declare
    fails the extraction rather than inventing a line (I9)."""
    from pic_etl.load.aliases import normalizar

    datos = yaml.safe_load((REFERENCIA / "rubro.yaml").read_text(encoding="utf-8"))
    return {normalizar(r["nombre"]): r["rubro_id"] for r in datos["rubro"]}


def cmd_extract(args: argparse.Namespace) -> int:
    """Parse the sources into reviewable YAML. This is the step a person reads
    before anything reaches a database."""
    rutas = _corpus(Path(args.source))
    EXTRACCIONES.mkdir(exist_ok=True)

    salidas: dict[str, object] = {}

    # The twelve Acuerdos: metadata parses deterministically, and the ETC
    # distribution tables have a fixed shape. Figures buried in free prose are
    # left out rather than guessed at.
    for ruta in sorted(Path(args.source).glob("*/PIC-Info_/Acuerdo*.pdf")):
        m = re.match(r"Acuerdo (\d{3}) de (\d{4})", ruta.name)
        documento_id = f"ACU_CSU_{m[1]}_{m[2]}"
        ext = acuerdos.extraer(
            ruta, documento_id, sha256_de(ruta),
            fecha_asercion=date.fromisoformat(
                texto_pdf.metadata(ruta)["fecha"]),
        )
        if ext is not None:
            salidas[documento_id] = ext

    # The MEN report: its tables exist only in the raw OLE stream.
    informe = next(Path(args.source).glob("*/Pic_Info-3/Informe PIC*.doc"), None)
    if informe is not None:
        ext = informes.extraer(informe, sha256_de(informe))
        if ext is not None:
            salidas[informes.DOCUMENTO_ID] = ext

    cualitativo = next(Path(args.source).glob("*/Pic_Info-3/PDF Reader*.doc"), None)
    if cualitativo is not None:
        ext = informes.extraer_cualitativo(cualitativo, sha256_de(cualitativo))
        if ext is not None:
            salidas[informes.DOCUMENTO_CUALITATIVO] = ext

    salidas |= {
        "ANEXO1_PIC": anexo1.extraer(
            rutas["ANEXO1_PIC"], sha256_de(rutas["ANEXO1_PIC"]),
            cuartiles=_cuartiles(), rubros=_rubros()
        ),
        "ANEXO2_PIC": anexo2.extraer(rutas["ANEXO2_PIC"], sha256_de(rutas["ANEXO2_PIC"])),
    }
    _snapshots(rutas, Path(args.source))

    for nombre, ext in salidas.items():
        destino = EXTRACCIONES / f"{nombre.lower()}.yaml"
        destino.write_text(
            yaml.safe_dump(
                yaml.safe_load(ext.model_dump_json()),
                allow_unicode=True, sort_keys=False, width=200,
            ),
            encoding="utf-8",
        )
        print(f"  {destino.relative_to(RAIZ)}  {len(ext.filas)} filas")
    return 0


def _paginas_citadas(documento_id: str) -> set[int]:
    """Which pages of a document any committed extraction actually cites."""
    import yaml as _yaml

    paginas: set[int] = set()
    for archivo in EXTRACCIONES.glob("*.yaml"):
        datos = _yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}
        if datos.get("documento_id") != documento_id:
            continue
        for fila in datos.get("filas", []):
            m = re.match(r"p\.(\d+),", fila.get("ubicacion", ""))
            if m:
                paginas.add(int(m[1]))
    return paginas


def _snapshots(rutas: dict[str, Path], fuente: Path) -> int:
    """Render each source table to HTML. A citation names a cell; this shows it.

    Purely derived from the documents, so it is safe to re-run anywhere —
    unlike `extract`, which would overwrite reviewed extractions.
    """
    from pic_etl.extract import snapshots

    fragmentos = snapshots.anexo1(rutas["ANEXO1_PIC"]) + snapshots.anexo2(rutas["ANEXO2_PIC"])

    informe = next(fuente.glob("*/Pic_Info-3/Informe PIC*.doc"), None)
    if informe is not None:
        fragmentos += snapshots.informe(informe, "INFORME_MEN_2024_2025")
    cualitativo = next(fuente.glob("*/Pic_Info-3/PDF Reader*.doc"), None)
    if cualitativo is not None:
        fragmentos += snapshots.informe(cualitativo, "INFORME_CUALITATIVO")

    # Prose documents: render every page a citation points at.
    for ruta in sorted(fuente.glob("*/PIC-Info_/Acuerdo*.pdf")):
        m = re.match(r"Acuerdo (\d{3}) de (\d{4})", ruta.name)
        documento_id = f"ACU_CSU_{m[1]}_{m[2]}"
        citadas = _paginas_citadas(documento_id)
        if citadas:
            fragmentos += snapshots.pdf_paginas(ruta, documento_id, citadas)
    indice = snapshots.escribir(fragmentos, RAIZ / "build" / "fuentes")
    print(f"  build/fuentes  {len(indice)} tablas fuente")
    return len(indice)


def cmd_snapshots(args: argparse.Namespace) -> int:
    _snapshots(_corpus(Path(args.source)), Path(args.source))
    return 0


def _leer_extracciones() -> list[Extraction]:
    archivos = sorted(EXTRACCIONES.glob("*.yaml"))
    if not archivos:
        raise SystemExit("extractions/ está vacío; ejecute `pic-etl extract` primero")
    return [
        Extraction.model_validate(yaml.safe_load(a.read_text(encoding="utf-8")))
        for a in archivos
    ]


def cmd_build(args: argparse.Namespace) -> int:
    """Reference data, then extractions, in one transaction.

    A rebuild from scratch is the default: idempotency becomes structural rather
    than merely asserted, since the same corpus always yields the same database.
    """
    extracciones = _leer_extracciones()
    engine = crear_engine(args.out, recrear=not args.incremental)
    crear_esquema(engine)

    with engine.begin() as conn:
        ref = cargar_referencia(conn)
        hechos = cargar_extracciones(conn, extracciones)
        grano = materializar_grano(conn)

    print(f"  referencia   {sum(ref.values()):>6} filas / {len(ref)} tablas")
    for k, v in hechos.items():
        print(f"  {k:<22} {v:>6}")
    print(f"  granos {grano['granos']}, resueltos {grano['resueltos']}"
          f" (concordantes {grano['concordantes']}),"
          f" en conflicto sin adjudicar {grano['en_conflicto']}")
    print(f"  -> {args.out}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Render the same views as a static site for GitHub Pages."""
    from pic_etl.publish import publicar

    engine = crear_engine(args.out)
    n = publicar(
        engine,
        RAIZ / "site",
        corpus=Path(args.source),
        fuentes=RAIZ / "build" / "fuentes",
        db=Path(args.out),
    )
    for k, v in n.items():
        print(f"  {k:<10} {v:>6}")
    print(f"  -> {RAIZ / 'site'}")
    return 0


# ------------------------------------------------------ transcripción asistida

def _registro() -> dict:
    return yaml.safe_load((REFERENCIA / "documento.yaml").read_text(encoding="utf-8"))


def _documento(documento_id: str) -> dict:
    for d in _registro()["documento"]:
        if d["documento_id"] == documento_id:
            return d
    raise SystemExit(
        f"{documento_id} no está en documento.yaml. Para un archivo nuevo use "
        f"`--archivo RUTA --id ID --tipo TIPO --emisor EMISOR --titulo TITULO`."
    )


def _anotar_registro(fila: dict) -> None:
    """Append a document to the register, in the file, for a person to review.

    Written rather than inserted: the register is a committed reference file, so
    a new document arrives as a diff someone reads, like every other fact here.
    """
    destino = REFERENCIA / "documento.yaml"
    texto = destino.read_text(encoding="utf-8")
    if f"documento_id: {fila['documento_id']}\n" in texto:
        print(f"  {fila['documento_id']} ya estaba en el registro")
        return
    bloque = yaml.safe_dump([fila], allow_unicode=True, sort_keys=False, width=200)
    marca = "\ndocumento_cita:"
    if marca in texto:
        texto = texto.replace(marca, "\n" + bloque + marca, 1)
    else:
        texto = texto.rstrip() + "\n" + bloque
    destino.write_text(texto, encoding="utf-8")
    print(f"  registrado {fila['documento_id']} en documento.yaml")


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Read a scan with a vision model into a reviewable proposal.

    The only step that needs a network. It writes `extractions/propuestas/`,
    which `build` does not read: promoting the proposal is a separate, explicit
    act, and that is what keeps the load deterministic.
    """
    from pic_etl.extract.vision import grafo, revision

    if args.archivo:
        ruta = Path(args.archivo)
        if not (args.id and args.tipo and args.emisor and args.titulo):
            raise SystemExit("con --archivo hacen falta --id, --tipo, --emisor y --titulo")
        documento_id, tipo, titulo = args.id, args.tipo, args.titulo
        fila = {"documento_id": args.id, "tipo": args.tipo, "emisor": args.emisor,
                "titulo": args.titulo, "estado": "EN_CORPUS", "soporte": "TRANSCRITO",
                "ruta_archivo": str(ruta), "sha256": sha256_de(ruta)}
        if args.registrar:
            _anotar_registro(fila)
    else:
        doc = _documento(args.documento)
        ruta = RAIZ / doc["ruta_archivo"]
        if not ruta.exists():
            ruta = texto_pdf.ruta_de(doc["ruta_archivo"], RAIZ)
        documento_id, tipo, titulo = args.documento, doc["tipo"], doc["titulo"]

    sha = sha256_de(ruta)
    numeros = ([int(n) for n in args.paginas.split(",")] if args.paginas else None)
    print(f"  {documento_id}  {ruta.name}")

    extraccion, acta = grafo.transcribir_documento(
        documento_id, ruta, sha, titulo=titulo, tipo=tipo, paginas_=numeros)
    destino, acta_ruta = revision.escribir(extraccion, acta)

    for linea in acta["diario"]:
        print(f"    {linea}")
    for o in acta["omitido"]:
        print(f"    omitido — {o}")
    print(f"  -> {destino.relative_to(RAIZ)}  {len(extraccion.filas)} filas")
    print(f"  -> {acta_ruta.relative_to(RAIZ)}")

    _imprimir_diff(revision.comparar(documento_id))
    if args.promover:
        cmd_promote(args)
    return 0


def _imprimir_diff(d: dict) -> None:
    print(f"\n  frente a lo ya comprometido:"
          f"  {len(d['coincide'])} coinciden,"
          f" {len(d['sobra'])} nuevas, {len(d['falta'])} sin proponer")
    for c in d["sobra"]:
        print(f"    +  {c}")
    for c in d["falta"]:
        print(f"    −  {c}")


def cmd_review(args: argparse.Namespace) -> int:
    """The proposal against the committed transcription, figure by figure."""
    from pic_etl.extract.vision import revision

    _imprimir_diff(revision.comparar(args.documento))
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Move a reviewed proposal into `extractions/`, where the build sees it."""
    from pic_etl.extract.vision import revision

    documento = args.documento or args.id
    origen = revision.PROPUESTAS / f"{documento.lower()}.yaml"
    if not origen.exists():
        raise SystemExit(f"no hay propuesta para {documento}")
    # Validate once more against the contract: the file may have been edited by
    # hand between the proposal and this moment, which is the point of it.
    datos = yaml.safe_load(origen.read_text(encoding="utf-8"))
    ext = Extraction.model_validate(datos)

    destino = EXTRACCIONES / f"{documento.lower()}.yaml"
    destino.write_text(
        revision.CABECERA.replace("PROPUESTA — no la carga `pic-etl build`.",
                                  "Transcripción asistida por modelo, revisada y "
                                  "promovida.")
        + yaml.safe_dump(yaml.safe_load(ext.model_dump_json()),
                         allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8")
    origen.unlink()
    print(f"  {destino.relative_to(RAIZ)}  {len(ext.filas)} filas — "
          f"`pic-etl build` ya la carga")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from pic_etl.verify.invariants import ejecutar

    engine = crear_engine(args.out)
    fallos = ejecutar(engine, Path(args.source), EXTRACCIONES)
    return 1 if fallos else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pic-etl", description=__doc__)
    p.add_argument("--source", default=str(RAIZ / "extracted"),
                   help="raíz del corpus (por defecto: extracted/)")
    p.add_argument("--out", default=str(RAIZ / "build" / "pic.sqlite"))
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("extract", help="corpus -> extractions/*.yaml (revisable)")
    b = sub.add_parser("build", help="extractions/*.yaml -> base de datos")
    b.add_argument("--incremental", action="store_true",
                   help="no recrear; confiar en las claves naturales")
    sub.add_parser("verify", help="invariantes I1-I15 y re-transcripción")
    sub.add_parser("snapshots", help="tablas fuente -> build/fuentes/ (sin tocar extractions/)")
    sub.add_parser("publish", help="vistas -> site/ estático para GitHub Pages")

    t = sub.add_parser("transcribe",
                       help="escaneo -> propuesta revisable (usa un modelo de visión)")
    t.add_argument("--documento", help="documento_id ya registrado")
    t.add_argument("--archivo", help="PDF que aún no está en el registro")
    t.add_argument("--id"), t.add_argument("--tipo")
    t.add_argument("--emisor"), t.add_argument("--titulo")
    t.add_argument("--registrar", action="store_true",
                   help="con --archivo, anota el documento en documento.yaml")
    t.add_argument("--paginas", help="sólo estas páginas, p. ej. 2,3")
    t.add_argument("--promover", action="store_true",
                   help="tras revisar el diff, mover la propuesta a extractions/")

    r = sub.add_parser("review", help="propuesta frente a lo comprometido, cifra a cifra")
    r.add_argument("documento")

    m = sub.add_parser("promote", help="propuesta revisada -> extractions/")
    m.add_argument("documento")

    args = p.parse_args(argv)
    if args.cmd == "transcribe" and not (args.documento or args.archivo):
        raise SystemExit("indique --documento o --archivo")
    return {"extract": cmd_extract, "build": cmd_build, "snapshots": cmd_snapshots,
            "verify": cmd_verify, "publish": cmd_publish,
            "transcribe": cmd_transcribe, "review": cmd_review,
            "promote": cmd_promote}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
