# PIC ETL — Design

**Plan Integral de Cobertura — extraction and load pipeline, revision 1**

Companion to `pic-data-model-v2.md`. That document says what the database must hold; this
one says how it gets filled. Section references of the form §7.1, and identifiers of the
form P2, L5, I11, E6, D1, C2, V8, all refer to the schema specification.

> Decisions here are settled unless a later revision says otherwise. The rationale is kept
> deliberately, so that Core-over-ORM and the no-authoring-in-the-database rule are not
> re-argued from scratch.

---

## Context

`pic-data-model-v2.md` specifies a ~30-table, assertion-based schema for the PIC corpus:
23 documents, 2023–2026, describing MEN's funding of enrolment expansion at UNAL. It
describes structure in generic DDL and names no storage engine.

This document specifies the pipeline that fills it: a recurrent Python process that reads
`extracted/PIC-Información/` and produces a SQLite database matching that schema, so a
dashboard can be built on it. The schema's distinguishing feature is that it stores **what
each document said, wrong or not**, with mandatory provenance, and resolves disagreement in
views rather than at load. The register in §7.1 lists 38 known inconsistencies that must
survive into the database rather than be corrected away.

Three properties drive every decision below:

- **P2 — no value without its claimant and its location.** Every row carries `documento_id`
  and `ubicacion`.
- **L2 / I11 — every load is idempotent.** Re-running produces zero new rows.
- **P1 / L1 — transcribe, never correct; append only.**

## Decisions taken

| Decision | Choice |
|---|---|
| Extraction boundary | A reviewed, git-committed YAML file per document, between parsing and loading |
| Review depth | Every extraction file read by a person before commit |
| Validation | **Pydantic v2** models are the contract for that YAML |
| Storage | **SQLAlchemy Core** (no ORM); SQLite now, Postgres plausible later |
| Migrations | None in Phase 1 — `build` drops and recreates |
| Phase 1 scope | The two structured sources only — Anexo 1 `.docx`, Anexo 2 `.xlsx` — but the *complete* DDL, reference data and invariant suite |

### Why Core rather than the ORM

Recorded because it is worth not re-arguing. **Engine portability lives in Core, not the
ORM** — `create_engine`, the dialects and SQL compilation are all Core; the ORM sits on top
and adds object mapping. Choosing Core costs nothing in portability.

It declines the object layer, which fits badly here on three counts. The ORM's central value
is the unit of work — tracking mutations and flushing them — but L1 forbids `UPDATE` against
`declaracion` entirely; nothing ever mutates. Relationship traversal (`declaracion.documento
.emisor`) is exactly the access §9 prohibits, since the BI role is granted views only. And
Pydantic already owns the object layer, so ORM classes would make each row's third
representation.

Not a one-way door: `registry.map_imperatively()` can add ORM classes onto the same
`MetaData` later if a Python service ever needs them.

**Alembic deferred, not rejected.** Migrations buy nothing while every build drops and
recreates the file. Add it the moment something exists that cannot afford to be dropped.

That last point has a consequence worth stating now: **nothing may be authored inside the
database.** A rebuild destroys anything that is. `declaracion_disposicion` — which
declaration each of UNAL, MEN and AUDITOR prefers, and why — is an editorial judgement, and
the temptation will be to record it with an `INSERT`. It must instead live in
`pic_etl/reference/disposicion.yaml` and be loaded like any other reference data. That keeps
rebuilds safe, and keeps the most contestable decisions in the corpus diffable and reviewed
alongside the extractions.

## Architecture

Two phases separated by an artifact a human has read.

```
extracted/PIC-Información/**          source corpus — read-only, never modified
        │
        │   pic-etl extract           Phase A: occasional, model-assisted later,
        ▼                                      always human-reviewed
extractions/*.yaml                    committed to git · Pydantic-validated · diffable
        │
        │   pic-etl build             Phase B: recurrent, offline, deterministic,
        ▼                                      no network, no API key
build/pic.sqlite
```

Everything above the YAML line is best effort. Everything below it is pure and repeatable.
That line is what lets an LLM enter the pipeline in Phase 2 without costing determinism:
a model may help *write* an extraction, but never participates in a build.

The format is not an invention — `valor_origen` and `ubicacion` are demanded by L3 and L4
already. The file simply makes them reviewable before they reach a database.

## What the two Phase-1 parsers face

Both sources were inspected; neither is hostile, and one dependency turns out to be
unnecessary.

**Anexo 1 `.docx` — 14 top-level tables, every one captioned** in the paragraph immediately
before it (`Tabla 7. Balance de compromisos PIC 2024.`). That caption is a stable, human
verifiable `ubicacion`: `Tabla 7, fila 'Medellín', col 'Matriculados 2025-2'`.

| Table | Shape | Feeds |
|---|---|---|
| T01, T06, T07, T10, T12 | sede × cupos | `compromiso` — one per cycle |
| T02 | sede × compromiso, cupos, matriculados, rezago | `compromiso` + `declaracion`; the rezago derivation behind I7 / D6 |
| T03, T08 | 17 rows: sede × cuartil × programa especial / regular | `cobertura_territorial` |
| T04 | PIC × compromiso, matriculados, rezago | `declaracion` (AGREGADO) |
| T05 | periodo × aumento matriculados | **E6** |
| T09, T11 | sublínea × cantidad × valor | rubro distribution, pre-2025 generation |
| T13 | PTIUN project formulation | PIC-ET, prose cells |
| T14 | `Línea Estratégica N:` prefixed sublíneas | rubro distribution, V2025 generation — **V8** |

`python-docx` is **not needed**. Stdlib `zipfile` + `ElementTree` over `word/document.xml`
reads all 14 cleanly. One dependency saved.

Parser details that matter: T09/T11/T14 mix single-cell **group bands** (`Docentes y talento
humano…`) with three-cell data rows, so row shape decides the record type. And T09 carries
`'Bolsa'` where a quantity belongs — precisely the literal v2 §6 names as a `valor_origen`
example.

**Anexo 2 `.xlsx`** confirms three register items in the raw cells:

- **E1** — Bogotá row 15: `N = P = 3 908 727 040` exactly. Column N sums to `68 505 589 464`.
- **C2** — row 12 reads `Sede Arauca` with `departamento = Arauca`; it is Sede Orinoquía.
- **V2** — row 18 (La Paz) has `N`, `P` and `T` all empty.

Column P holds unrounded formula results (`4895974740.75787`). `valor_origen` must capture
the **cached raw value**, not the formatted display string, or the re-transcription test
will compare a rounded string against a full-precision float and fail on every row.

### Alias resolution is not optional

Anexo 1 spells the same sede four ways *within one document* — `Sede Amazonia` (T01),
`Amazonia` (T02), `AMAZONÍA` (T03), `Amazonía` (T06) — and Anexo 2 adds `Sede Arauca` for
Orinoquía. L5 says resolve aliases at load, never at source, so `unidad_alias` must be
populated as curated reference data before any parser runs, and an unmatched spelling must
**fail the load** rather than create a unit (I9).

## Repository setup

The whole review discipline above rests on extractions being diffable, so version control is
a prerequisite, not a convenience — at the time of writing this directory was not yet a git
repository. A `.gitignore` excludes `build/` and
`PIC-Información-20260902T000902Z-1-001.zip` (21 MB, redundant with `extracted/`).

Whether to commit `extracted/` itself is a judgement call: 22 MB is large for git, but the
corpus is the pipeline's input and `fuente_sha256` only means something if the bytes it
hashes are pinned somewhere. I would commit it — the corpus is fixed and small in file
count, and reproducibility is the point of the exercise.

## Module layout

```
pyproject.toml              uv-managed: sqlalchemy, pydantic, pyyaml, openpyxl, pytest
                            (no python-docx — stdlib zipfile+ElementTree suffices)
pic_etl/
  cli.py                    extract | build | verify | check
  models.py                 Pydantic v2 — the extraction contract
  schema/
    tables.py               one MetaData(); every Table() declared once
    dialect.py              partial indexes, generated columns, serial types per dialect
  reference/                curated seed data — hand-maintained YAML, not extracted
    unidad_academica.yaml   9 sedes + faculties + sentinels
    unidad_alias.yaml       every observed spelling → unidad_id (see below)
    medida.yaml             unit and STOCK/FLUJO per measure
    poblacion.yaml  periodo.yaml  ciclo.yaml  programa.yaml
    vista.yaml  etapa.yaml  cuartil.yaml
    documento.yaml          the 23-file register, plus CITADO documents
    disposicion.yaml        editorial judgements — never authored in the DB
  extract/
    anexo2.py               openpyxl → Extraction
    anexo1.py               docx tables → Extraction
    acuerdos.py             Phase 2 — 12 text-layer PDFs
    scans.py                Phase 3 — 6 scanned PDFs, vision
  load/
    loader.py               YAML → Pydantic → SQLAlchemy Core inserts
    rollup.py               unidad_rollup closure, computed in Python
    order.py                FK-respecting population order
  verify/
    retranscription.py      re-open the source; assert valor_origen still matches
    invariants.py           I1–I15 as runnable checks
tests/
  fixtures/                 hand-written good AND deliberately broken extractions
build/pic.sqlite            gitignored
```

## The Pydantic contract

This is the layer that makes a hand-reviewed YAML file safe to trust. It enforces what the
database cannot reach — before a connection is even opened.

```python
class Declaracion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tipo: Literal["declaracion"]
    tipo_declaracion: Literal["TRANSCRIPCION", "AGREGADO"]
    medida_id: str

    # grain — never Optional; sentinels stand in for "not applicable"
    ciclo_id: str
    unidad_id: str
    periodo_id: str
    poblacion_id: str

    valor: Decimal
    valor_origen: str = Field(min_length=1)
    ubicacion: str = Field(min_length=1)

Row = Annotated[Union[Declaracion, Proyecto, Compromiso, CargoCreado, Asignacion],
                Field(discriminator="tipo")]

class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documento_id: str
    fuente_sha256: str          # hash of the source file this was extracted from
    fecha_asercion: date
    filas: list[Row]
```

Four choices carry weight:

- **`extra="forbid"`** — a mistyped key in a hand-edited file fails loudly. The default
  would drop it silently, which is exactly how a figure disappears from every view.
- **`Decimal`, never `float`** — the corpus turns on whether `$68 505 589 464` reconciles
  to `$9 561 136 948`. Binary floats have no place in that argument.
- **`frozen=True`** — mirrors P1 and L1. An extraction is a transcription; nothing mutates
  it after parse.
- **No `Optional` on any grain field** — P5 enforced one layer earlier than the database.

`fuente_sha256` is what makes a stale extraction detectable: if the source file changes, the
build fails rather than loading a transcription of a document that no longer exists.

Pydantic and SQLAlchemy Core divide cleanly here precisely because there is no ORM. Pydantic
owns the input contract; SQLAlchemy owns storage. Nothing is modelled twice.

### A worked extraction, with real values

`extractions/anexo1-pic.yaml`, from Tabla 5 and Tabla 10:

```yaml
documento_id: ANEXO1_PIC
fuente_sha256: "…"
fecha_asercion: 2026-04-13
filas:
  # Tabla 5 — the four periods behind E6. Sum is -689; the report claims -1 168.
  - tipo: declaracion
    tipo_declaracion: TRANSCRIPCION
    medida_id: aumento_matriculados      # FLUJO, so summing across periodo is legal
    ciclo_id: PIC_CO_2023
    unidad_id: UNAL_TOTAL                # sentinel — the table has no sede column
    periodo_id: "2025-1"
    poblacion_id: MATRICULA_GLOBAL
    valor: -681
    valor_origen: "-681"
    ubicacion: "Tabla 5, fila '2025-1S', col 'Aumento Matriculados'"

  # Tabla 10 — compromiso is structural, not a declaracion
  - tipo: compromiso
    proyecto_id: PIC_CO_2025_P09
    unidad_id: LA_PAZ                    # resolved from the literal 'La Paz'
    cupos: 24
    es_rezago: false
    ubicacion: "Tabla 10, fila 'La Paz', col 'Compromiso nuevos cupos'"

  # The table's own 'Total' row is an AGREGADO, never a compromiso row
  - tipo: declaracion
    tipo_declaracion: AGREGADO
    medida_id: compromiso
    ciclo_id: PIC_CO_2025
    unidad_id: UNAL_TOTAL
    periodo_id: NA
    poblacion_id: NA
    valor: 200
    valor_origen: "200"
    ubicacion: "Tabla 10, fila 'Total', col 'Compromiso nuevos cupos'"
    es_agregado_de_ubicaciones:          # resolved to declaracion_ids at load
      - "Tabla 10, fila 'Amazonía', col 'Compromiso nuevos cupos'"
      # … the other eight sedes
```

Three things this settles. A table's **`Total` row never becomes a fact row** — it is an
`AGREGADO` linked by `es_agregado_de`, which turns I15 into a runnable test instead of a
double count. Sentinels carry the grain where a table has no such column, per P5. And
`aumento_matriculados` is declared `FLUJO`, distinct from the `STOCK` measure `matriculados`
of §3.4 — Tabla 5 is legitimately summable, Tabla 7 is not.

The Anexo 2 equivalent uses cell addresses: `ubicacion: "Registro_Proyectos_2025!N15"`,
`valor_origen: "3908727040"`.

## Storage layer

One `MetaData()` in `schema/tables.py`. `schema/dialect.py` holds the constructs no
abstraction makes portable.

**A verified defect in v2 §3.2.** The spec writes:

```sql
FOREIGN KEY (sede_id, 'SEDE') REFERENCES unidad_academica (unidad_id, tipo)
```

A literal is not legal in a foreign-key column list. SQLite *accepts the DDL* and then
rejects every insert with `IntegrityError: FOREIGN KEY constraint failed` — tested against
SQLite 3.50.4. The working form is a generated column, which I verified enforces exactly
the intended rule (it rejects `FCV → MED` until `MED` exists with `tipo='SEDE'`):

```python
Column("k_sede", Text, Computed("'SEDE'", persisted=False)),
ForeignKeyConstraint(["sede_id", "k_sede"], ["unidad_academica.unidad_id",
                                             "unidad_academica.tipo"]),
```

**Other divergences to handle in `dialect.py`:**

| Construct | SQLite | Postgres |
|---|---|---|
| `BIGSERIAL` | `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL` |
| Partial unique index | `sqlite_where=` | `postgresql_where=` |
| Generated column | `Computed(..., persisted=False)` | `Computed(..., persisted=True)` |
| `CHECK` with subquery | **prohibited** — must become a load-time test | allowed |

**`PRAGMA foreign_keys = ON` defaults to OFF in SQLite.** Invariant I9 — "no load creates a
dimension member" — is silently a no-op without it. Set it on every connection via a
`connect` event listener, not by hoping a caller remembers.

**`unidad_rollup` is computed in Python, not by a trigger.** The hierarchy is roughly thirty
rows loaded wholesale; a recursive walk in `load/rollup.py` is simpler than a recursive
trigger, easier to test, and ports to Postgres unchanged. Cycle detection (I12) happens in
the same walk.

## Loader

- Population order derived from `MetaData.sorted_tables`, so FK order is not hand-maintained.
- Idempotency by natural key, per L2: `INSERT … ON CONFLICT DO NOTHING`, which SQLAlchemy
  expresses for both dialects. The `UNIQUE` constraints of §5 and §6 are the mechanism; the
  loader is not trusted to be careful.
- One transaction per build. A failed invariant rolls back rather than leaving a half-corpus.
- `build` recreates the database from scratch by default, which makes idempotency structural
  rather than merely asserted: the same corpus always yields the same database.

## Re-transcription test

For grid sources the loader can prove an extraction still matches its origin. `verify/
retranscription.py` re-opens the `.xlsx`, resolves `ubicacion` back to a cell, and asserts
the cell's literal still equals `valor_origen`. A mismatch fails the build and names the
cell.

This is only possible because `ubicacion` is a real address. It is the reason an LLM must
never be allowed near a grid: a fabricated cell reference would pass review and fail nothing.

For scans, no such check exists — `fuente_sha256` is the substitute.

## Tests

Positive tests are the easy half. The suite must prove each constraint **fires**, using the
known v1 failures as its specification:

| Test | Proves |
|---|---|
| Load the same extraction twice; assert row counts identical | L2 / I11 — v1 doubled the corpus while every invariant passed |
| Insert two preferred declarations at one grain; assert `IntegrityError` | I1 — v1's index could not exist, because `NULL ≠ NULL` |
| Assert every grain column is `NOT NULL` in the reflected schema | P5, structurally |
| Sum a sede via `sede_id = :x`; assert it differs from the `distancia > 0` rollup | I2 — v1 returned 41 + 25 = 66 for Medellín |
| Insert `A→B→A` in the hierarchy; assert rejection | I12 |
| Sum a `STOCK` measure across `periodo` in a view; assert unavailable | I3 |
| Corrupt a `valor_origen` in a fixture; assert the build fails | re-transcription |
| Feed a fixture with an unknown `medida_id`; assert load failure, not silent drop | L6 |
| Feed a fixture with a misspelled key; assert Pydantic rejects it | `extra="forbid"` |

`tests/fixtures/` therefore holds deliberately broken extractions as first-class artifacts.

## Reference data

Dimension members are **curated, not extracted** — I9 requires that no load create one.
They live as hand-maintained YAML under `pic_etl/reference/`, loaded before any extraction.
This is where the sentinels of §3.1 (`UNAL_TOTAL`, `TODOS`, `NA`) are defined, and where the
9 sedes, 4 admission routes, the `medida` units and STOCK/FLUJO flags, and the document
register are written down.

Two of §10's blocking prerequisites land here rather than in code:

- **FCV's `tipo` and validity range** must be decided to write `unidad_academica` at all.
  It is the one prerequisite that genuinely blocks loading; the others block charts.
- **`rubro_mapping` stays empty.** Under I10 that correctly makes cross-generation queries
  return nothing. Empty is the designed state, not an omission.

`departamento` and `municipio` may be seeded from Anexo 2's hidden `Listas` sheet, which
carries an authoritative department/municipio list and a línea estratégica vocabulary. v2
§3.7 lists both tables as "referenced but never defined".

## What follows Phase 1

Not in scope now, but the shape is settled, and one finding narrows the later work usefully.

The 12 `Acuerdo *.pdf` are Chrome prints of UNAL's Régimen Legal system and share a rigid
preamble — `FECHA DE EXPEDICIÓN`, `FECHA DE ENTRADA EN VIGENCIA`, `ACUERDO NNN DE YYYY`,
`(Acta N del …)`, a quoted title, then `CONSIDERANDO` and `QUE, …` clauses. So the
`documento` rows — number, date, title — parse **deterministically, with no model at all**.
Only figures embedded in sentences need model help. That splits Phase 2 into a cheap,
testable half and a reviewed half.

One trap: every page carries a printed-on date in its header (`12/3/26`). It is the day
someone pressed print, not the document's date, and it must be stripped before any date
parsing runs.

| Phase | Sources | Method |
|---|---|---|
| 2 | 12 Acuerdos | rule-based metadata + model-assisted figures |
| 3 | 6 scanned PDFs, 50 pages | vision; §10 records the 5 resolutions as already transcribed, but that work lives in a prior session's context, not on disk |
| 4 | 2 `.doc` reports, `Oficio_PIC-CO-ET.docx` | `textutil` text + model-assisted figures |

## Verification

```
uv run pic-etl build --source extracted/PIC-Información --out build/pic.sqlite
uv run pic-etl verify --db build/pic.sqlite      # I1–I15 + re-transcription
uv run pytest
```

Then, by hand:

1. Run `build` twice; `sqlite3 build/pic.sqlite 'SELECT count(*) FROM declaracion'` is equal
   both times.
2. `PRAGMA foreign_key_check` returns no rows.
3. Query `v_matricula` for a grain with a known divergence; confirm **one row per vista**,
   not two — the v1 bug that returned `1 161` and `1 043` and summed them to `2 204`.
4. Confirm a document with `estado='CITADO'` has no `ruta_archivo` and no facts, and that
   Acuerdo 011/2025 (V1) is present as cited-but-absent.
5. Confirm the Anexo 2 `#REF!` in `C3` (E13) loaded as a recorded value rather than crashing
   the parse or being silently skipped.

---

*Phase 1 of four. Sources: Anexo 1 `.docx` and Anexo 2 `.xlsx`; the
complete DDL, reference data and invariant suite.*

---

## Found while building

Implementation contradicted the specification in five places. Each is fixed in
code; each is a defect in `pic-data-model-v2.md` that a reader of that document
alone would walk into.

| # | Where | What | Fix |
|---|---|---|---|
| 1 | §3.2 | `FOREIGN KEY (sede_id, 'SEDE')` — a literal is not legal in a foreign-key column list. SQLite accepts the DDL and rejects **every** insert | generated column holding the constant |
| 2 | §3.1 vs §3.2 | The sentinel row §3.1 prescribes (`UNAL_TOTAL`, tipo `UNIVERSIDAD`, its own sede) **cannot satisfy** §3.2's key. The two sections contradict each other | the generated column resolves to `'UNIVERSIDAD'` for the sentinel and `'SEDE'` for everything else |
| 3 | §5 | Money has no companion to `valor_origen`, so L3 is unmet and no money figure can be checked against its source | `monto_origen` on `asignacion`, `cantidad_origen` on `cargo_creado` |
| 4 | §6 | `declaracion` has no rubro, so Tabla 9's four sublíneas land on one grain and read as four rival claims about one number | `presupuesto_rubro`, the table §0 item 18 already implies |
| 5 | §3.8 | The quartile bands were unstated. The real ones are `[0.287,0.586]`, `(0.586,0.649]`, `(0.649,0.711]`, `(0.711,0.985]` — note the first opens with a square bracket | transcribed verbatim; V4 confirmed, `(0.586,0.649]` appears nowhere |

Two further decisions the specification left open:

**Sedes are hierarchy roots, and `UNAL_TOTAL` sits beside the hierarchy rather
than above it.** This follows from §3.2's own CHECK, and it means university
totals are *declared by a document*, never summed up from sedes — the schema
expression of "never let the tool compute a grand total."

**Agreement is not ambiguity.** `compromiso 1 818` appears in Tabla 1, Tabla 2
and Tabla 4. Treating that as three rival claims needing adjudication would be
wrong; the loader records it as corroboration and resolves the grain
deterministically. Only differing values at one grain are a conflict.

### Known gap

**E13 is not captured.** Anexo 2's `C3` holds `#REF!` where the institution's
SNIES code belongs. It sits in the sheet's header block, not in a data row, and
it is a broken *identifier* rather than a measure — no current table has a place
for it. Recording it properly needs somewhere to hold a document's own header
assertions. It is listed here rather than forced into a shape that fits.
