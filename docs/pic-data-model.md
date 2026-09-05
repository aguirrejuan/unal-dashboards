# PIC Data Model

**Plan Integral de Cobertura — build specification**

A schema for a corpus that contradicts itself. Its central commitment: the database
records *what each document said*, and a separate, visible policy layer decides what a
chart shows. Nothing is corrected on the way in.

> SQL below is written in generic DDL to describe structure. No storage engine is
> implied or recommended here.

---

## Contents

1. [Principles](#1-principles)
2. [Three layers](#2-three-layers)
3. [Reference tables](#3-reference-tables)
4. [The process, as data](#4-the-process-as-data)
5. [Primary facts](#5-primary-facts)
6. [The assertion layer](#6-the-assertion-layer)
7. [The inconsistency model](#7-the-inconsistency-model)
8. [Invariants](#8-invariants)
9. [Load discipline](#9-load-discipline)
10. [Decisions this schema defers](#10-decisions-this-schema-defers)

---

## 1. Principles

| # | Rule |
|---|------|
| **R1** | **Transcribe, never correct.** Load rejects nothing. A figure believed to be wrong is stored with the same fidelity as one believed right, and labelled. |
| **R2** | **A value is never stored without its claimant.** Every measured number carries the document that asserted it and the location within that document. |
| **R3** | **Disagreement is data.** Where two documents differ, both rows persist. Resolution is a view, not an edit. |
| **R4** | **Dimensions are declared, not derived.** No load job may create a dimension member. A band with no observations still exists as a row. |
| **R5** | **Absence has three meanings** — unknown, not-applicable, and measured-zero — and they are never collapsed. |
| **R6** | **Grain is explicit.** Every measured row records the level it was reported at. Summing across levels is prevented, not discouraged. |

---

## 2. Three layers

| Layer | Holds | Mutability | Read by |
|---|---|---|---|
| Reference | dimensions, process definition, document register | curated by hand | everything |
| Primary facts | transcriptions of structured or authoritative sources — acuerdo tables, the Anexo 2 rows | append; corrections are new rows | views |
| Assertions | every aggregate figure claimed by a narrative document | **append-only** | resolution views only |

### Why primary facts and assertions are separate

Acuerdo 024/2025 states 191.5 ETC in a table with a per-sede breakdown. That is
*primary*: unambiguous, one value, one source.

The Informe Cualitativo's claim that "the PIC created 191.5 posts" is an *assertion*
about an aggregate — and it is contestable, because the corpus contains three ETC
acuerdos totalling 394.5.

Both are true statements about different things. Keeping them in separate layers is what
stops the second from overwriting the first.

---

## 3. Reference tables

### 3.1 Academic units — one hierarchy, not two

Sedes and the sub-units that receive their own allocations live in one table. Facultad de
Ciencias de la Vida appears in Acuerdo 024/2025 as an allocation unit alongside Medellín,
while enrolment reports treat Medellín as a single number — so facts must be able to
attach at either level without the model pretending they are interchangeable.

```sql
CREATE TABLE unidad_academica (
  unidad_id       TEXT PRIMARY KEY,   -- 'MEDELLIN', 'MEDELLIN_FCV'
  nombre          TEXT NOT NULL,
  tipo            TEXT NOT NULL,      -- SEDE | FACULTAD | UNIDAD_DOCENCIA
  padre_id        TEXT REFERENCES unidad_academica,
  sede_id         TEXT NOT NULL REFERENCES unidad_academica,
  grupo           TEXT,               -- SPN | ANDINA | OTRA
  departamento_id TEXT REFERENCES departamento,
  municipio_id    TEXT REFERENCES municipio
);
-- 9 sede rows (sede_id = unidad_id, padre_id NULL) + FCV + SPN teaching units

CREATE TABLE unidad_alias (           -- "Sede Arauca" in Anexo 2 = Orinoquía
  alias        TEXT NOT NULL,
  unidad_id    TEXT NOT NULL REFERENCES unidad_academica,
  documento_id TEXT NOT NULL REFERENCES documento,
  PRIMARY KEY (alias, documento_id)
);
```

### 3.2 Cycles and periods

```sql
CREATE TABLE ciclo (
  ciclo_id           TEXT PRIMARY KEY,  -- 'PIC_CO_2023', 'PIC_ET_2026'
  modalidad          TEXT NOT NULL,     -- CO | ET
  anio_formulacion   INT  NOT NULL,
  periodo_ejec_desde TEXT REFERENCES periodo,
  periodo_ejec_hasta TEXT REFERENCES periodo,
  estado             TEXT NOT NULL      -- ASIGNADO|FORMULADO|EN_EJECUCION|CERRADO
);

CREATE TABLE periodo (
  periodo_id    TEXT PRIMARY KEY,       -- '2024-1' … '2028-1'
  anio          INT  NOT NULL,
  semestre      INT  NOT NULL,
  orden         INT  NOT NULL,          -- for interval arithmetic
  es_proyectado BOOLEAN NOT NULL DEFAULT FALSE
);
```

`periodo_ejec_desde/hasta` encode the structural lag: **a cycle's label is its formulation
year, never its result year.** PIC-CO 2023 runs 2024-1 → 2025-1; PIC-CO 2026 runs
2027-2 → 2028-1.

### 3.3 Documents and radicados

A document row exists whether or not the file does. This is what makes "what are we
missing?" a query rather than institutional memory.

```sql
CREATE TABLE documento (
  documento_id TEXT PRIMARY KEY,
  tipo         TEXT NOT NULL,  -- NORMA|RESOLUCION|ACUERDO|OFICIO|INFORME|ANEXO|ACTA
  emisor       TEXT NOT NULL,  -- CONGRESO|MEN|UNAL_CSU|UNAL_RECTORIA
  numero       TEXT,
  fecha        DATE,
  titulo       TEXT,
  estado       TEXT NOT NULL,  -- EN_CORPUS | CITADO | NUNCA_PRODUCIDO
  soporte      TEXT,           -- TEXTO | ESCANEO   (NULL when not held)
  ruta_archivo TEXT,
  CHECK (estado <> 'EN_CORPUS' OR ruta_archivo IS NOT NULL),
  CHECK (estado =  'EN_CORPUS' OR ruta_archivo IS NULL)
);

CREATE TABLE radicado (
  radicado_id  TEXT PRIMARY KEY,   -- '2025-EE-151874'
  documento_id TEXT REFERENCES documento,
  direccion    TEXT NOT NULL,      -- MEN_A_UNAL | UNAL_A_MEN
  fecha        DATE
);
```

`soporte = 'ESCANEO'` is load-bearing: it marks the five MEN resolutions whose figures are
currently known only second-hand. A dashboard tile can therefore report what share of the
financial layer rests on un-transcribed scans.

### 3.4 Rubros — two generations, an incomplete bridge

```sql
CREATE TABLE rubro (
  rubro_id   TEXT PRIMARY KEY,
  generacion TEXT NOT NULL,   -- PRE_2025 (14 líneas) | V2025 (6 líneas)
  nivel      TEXT NOT NULL,   -- LINEA | SUBLINEA
  padre_id   TEXT REFERENCES rubro,
  nombre     TEXT NOT NULL
);

CREATE TABLE rubro_mapping (  -- starts EMPTY. Populated by hand, or not at all.
  rubro_origen  TEXT REFERENCES rubro,
  rubro_destino TEXT REFERENCES rubro,
  confianza     TEXT NOT NULL,   -- EXACTA | PARCIAL | SIN_MAPEO
  nota          TEXT,
  PRIMARY KEY (rubro_origen, rubro_destino)
);
```

Any query spanning the 2024→2025 boundary must join through `rubro_mapping`. Where no row
exists, the query returns nothing rather than mis-bucketing — **an empty chart is a
correct answer to a question the corpus cannot support.**

### 3.5 Priority quartiles — declaring the band that never appears

```sql
CREATE TABLE cuartil_prioridad (
  cuartil_id TEXT PRIMARY KEY,
  notacion   TEXT NOT NULL,       -- '(0.649,0.711]'
  limite_inf NUMERIC NOT NULL,
  limite_sup NUMERIC NOT NULL,
  observado  BOOLEAN NOT NULL     -- FALSE for (0.586,0.649]
);
```

Four rows are declared; three are observed. Build this dimension from the facts instead and
the missing band vanishes silently — the exact failure mode this table exists to prevent.
The same discipline applies to `fuente_financiacion`, where three of six sources have no
rows anywhere.

---

## 4. The process, as data

Seven stages, of which the corpus documents three. `ocurrencia` exists because stages
repeat: PIC 2024 was formulated, observed by MEN, and formulated again.

```sql
CREATE TABLE etapa (
  etapa_id          TEXT PRIMARY KEY,   -- E01 … E07
  orden             INT  NOT NULL UNIQUE,
  nombre            TEXT NOT NULL,
  actor             TEXT NOT NULL,
  doc_tipo_esperado TEXT
);

CREATE TABLE ciclo_etapa (
  ciclo_id     TEXT NOT NULL REFERENCES ciclo,
  etapa_id     TEXT NOT NULL REFERENCES etapa,
  ocurrencia   INT  NOT NULL DEFAULT 1,
  fecha        DATE,
  estado       TEXT NOT NULL,  -- COMPLETADA|OBSERVADA|RECHAZADA|PENDIENTE|NO_APLICA
  documento_id TEXT REFERENCES documento,
  radicado_id  TEXT REFERENCES radicado,
  nota         TEXT,
  PRIMARY KEY (ciclo_id, etapa_id, ocurrencia)
);
```

### The seven stages

| Stage | Actor | Expected document | In corpus |
|---|---|---|---|
| E01 Asignación | MEN · Hacienda · DNP | Resolución de distribución | ✅ 5 (all scans) |
| E02 Formulación | UNAL → MEN | Oficio de formulación | ❌ cited only |
| E03 Revisión · mesa técnica | MEN ↔ UNAL | Observaciones + acta | ❌ cited only |
| E04 Autorización interna | CNF → CNCA → CSU | Acuerdo del CSU | ✅ 12 |
| E05 Ejecución | sedes, 1–2 yrs later | convocatorias · hiring | ❌ aggregates only |
| E06 Reporte | UNAL → MEN, on request | Oficio + anexos | ✅ 5 |
| E07 Arrastre | automatic | *none* | ⬤ implicit |

Corpus completeness falls out of a join to `documento.estado`. So does cycle-time:
`E01.fecha → E05.fecha` is the money-to-student lag, per cycle, without anyone having to
explain it in prose.

---

## 5. Primary facts

Transcriptions of structured sources. One value, one claimant, no contest.

### 5.1 Projects — funding sources go long, not wide

```sql
CREATE TABLE proyecto (
  proyecto_id   TEXT PRIMARY KEY,
  ciclo_id      TEXT NOT NULL REFERENCES ciclo,
  unidad_id     TEXT NOT NULL REFERENCES unidad_academica,
  numero        INT,
  nombre        TEXT,
  linea_id      TEXT REFERENCES rubro,
  sublinea_id   TEXT REFERENCES rubro,   -- NULL for all 9: never filled in
  fecha_inicio  DATE,
  fecha_fin     DATE,                    -- 'Indefinido' in source → NULL
  riesgos       TEXT,
  observaciones TEXT
);

CREATE TABLE proyecto_financiacion (
  proyecto_id TEXT NOT NULL REFERENCES proyecto,
  fuente_id   TEXT NOT NULL REFERENCES fuente_financiacion,
  monto       NUMERIC,                   -- NULL = not recorded, never 0
  PRIMARY KEY (proyecto_id, fuente_id)
);
```

The source spreadsheet is wide — six funding columns, three of them empty in every row.
Long format turns "which sources were never used?" into a query and keeps the empty three
as declared dimension members rather than dead columns. **La Paz simply has no rows here.**

### 5.2 Commitments — where the 419 is contained

```sql
CREATE TABLE compromiso (
  compromiso_id   TEXT PRIMARY KEY,
  ciclo_id        TEXT NOT NULL REFERENCES ciclo,
  unidad_id       TEXT NOT NULL REFERENCES unidad_academica,
  cupos           INT  NOT NULL,
  es_rezago       BOOLEAN NOT NULL DEFAULT FALSE,
  ciclo_origen_id TEXT REFERENCES ciclo,
  CHECK (es_rezago = FALSE OR ciclo_origen_id IS NOT NULL)
);
```

> **The double-count, structurally prevented.**
> PIC 2024 committed 179 new seats *plus* 419 to clear the 2023 backlog. Those 419 are
> already inside the 1 818 of PIC 2023. Summing the source table's "Total" column across
> cycles yields 2 416 instead of 1 997 and counts 419 students twice.
>
> The rule is `SUM(cupos) WHERE NOT es_rezago`, and `ciclo_origen_id` keeps the
> re-commitment traceable rather than deleted.

### 5.3 Posts, budget lines, carry-forward, territorial coverage

```sql
CREATE TABLE cargo_creado (          -- from the Acuerdo tables
  documento_id TEXT NOT NULL REFERENCES documento,
  unidad_id    TEXT NOT NULL REFERENCES unidad_academica,
  tipo         TEXT NOT NULL,   -- DOCENTE_ETC | ADMIN_CARRERA | ADMIN_LNR | TECNICO
  cantidad     NUMERIC NOT NULL,-- NUMERIC: Palmira receives 31,5 ETC
  costo_total  NUMERIC,
  PRIMARY KEY (documento_id, unidad_id, tipo)
);

CREATE TABLE presupuesto_rubro (
  ciclo_id      TEXT NOT NULL REFERENCES ciclo,
  rubro_id      TEXT NOT NULL REFERENCES rubro,
  concepto      TEXT NOT NULL,
  cantidad      NUMERIC,        -- NULL where the source says "Bolsa"
  unidad_medida TEXT,
  monto         NUMERIC NOT NULL,
  PRIMARY KEY (ciclo_id, rubro_id, concepto)
);

CREATE TABLE arrastre (
  ciclo_origen_id  TEXT NOT NULL REFERENCES ciclo,
  ciclo_destino_id TEXT NOT NULL REFERENCES ciclo,
  cupos_rezago     INT,
  monto_saldo      NUMERIC,
  PRIMARY KEY (ciclo_origen_id, ciclo_destino_id)
);

CREATE TABLE cobertura_territorial (
  ciclo_id    TEXT NOT NULL REFERENCES ciclo,
  unidad_id   TEXT NOT NULL REFERENCES unidad_academica,
  cuartil_id  TEXT NOT NULL REFERENCES cuartil_prioridad,
  via_tipo    TEXT NOT NULL,   -- ESPECIAL | REGULAR
  estudiantes INT  NOT NULL,
  PRIMARY KEY (ciclo_id, unidad_id, cuartil_id, via_tipo)
);
```

`cantidad NUMERIC` rather than `INT` is not fussiness: Acuerdo 024/2025 assigns Palmira
31,5 equivalentes de tiempo completo, and the corpus total is 394.5.

---

## 6. The assertion layer

Every aggregate figure claimed by a narrative document lands here, and nowhere else.
**This table is append-only.**

```sql
CREATE TABLE asercion (
  asercion_id     BIGSERIAL PRIMARY KEY,
  medida          TEXT NOT NULL,  -- matriculados|admitidos|cupos_ofertados
                                  -- |compromiso|monto|cargos

  -- grain: any subset may be NULL; nivel_reportado says which was intended
  ciclo_id        TEXT REFERENCES ciclo,
  unidad_id       TEXT REFERENCES unidad_academica,
  periodo_id      TEXT REFERENCES periodo,
  nivel_reportado TEXT NOT NULL,  -- UNIDAD | SEDE | UNIVERSIDAD

  valor           NUMERIC NOT NULL,

  -- provenance
  documento_id    TEXT NOT NULL REFERENCES documento,
  ubicacion       TEXT,           -- 'Tabla 2' | 'Anexo 2!T10' | 'p.4 ¶3'
  valor_origen    TEXT,           -- the literal source string, pre-parsing

  -- semantics: what population was actually counted
  poblacion       TEXT NOT NULL,  -- '8 proyectos aprobados'
                                  -- 'consolidado incl. La Paz'
                                  -- 'matrícula global SNIES'
  base_medicion   TEXT,           -- ADMITIDOS | MATRICULADOS (for seat measures)

  -- disposition
  es_preferida    BOOLEAN NOT NULL DEFAULT FALSE,
  descartada      BOOLEAN NOT NULL DEFAULT FALSE,
  motivo_descarte TEXT,
  reemplaza_a     BIGINT REFERENCES asercion,
  CHECK (descartada = FALSE OR motivo_descarte IS NOT NULL),
  CHECK (NOT (es_preferida AND descartada))
);
```

> **Why `poblacion` is mandatory.**
> 1 161 and 1 043 are not two readings of one quantity. Anexo 1 counts first-time enrolment
> across the eight approved projects; the Informe MEN counts a consolidation that includes
> La Paz, which carried no 2023 commitment at all. Both are correct for what they measure.
>
> A schema storing only `valor` renders them comparable, which they are not. Making
> `poblacion` `NOT NULL` forces whoever loads a figure to state what was counted — and if
> they cannot tell from the document, that is itself a finding.

### 6.1 Conflicts as first-class records

```sql
CREATE TABLE conflicto (
  conflicto_id TEXT PRIMARY KEY,
  clase        TEXT NOT NULL,   -- ERROR | DIVERGENCIA | VACIO
  medida       TEXT,
  titulo       TEXT NOT NULL,
  descripcion  TEXT NOT NULL,
  estado       TEXT NOT NULL,   -- ABIERTO|RESUELTO|AMBOS_VALIDOS|IRRESOLUBLE
  impacto      TEXT NOT NULL,   -- ALTO|MEDIO|BAJO
  resolucion   TEXT,
  resuelto_por TEXT,
  resuelto_en  DATE
);

CREATE TABLE conflicto_asercion (
  conflicto_id TEXT   NOT NULL REFERENCES conflicto,
  asercion_id  BIGINT NOT NULL REFERENCES asercion,
  PRIMARY KEY (conflicto_id, asercion_id)
);
```

This pair is what a discrepancy panel reads. A conflict with `estado = 'AMBOS_VALIDOS'` is
not a defect awaiting cleanup — it is a permanent property of the corpus, and the dashboard
should present it as such.

### 6.2 Resolution views

```sql
CREATE VIEW v_matricula AS
SELECT a.ciclo_id, a.unidad_id, a.periodo_id, a.nivel_reportado,
       a.valor AS matriculados, a.poblacion, a.base_medicion,
       a.documento_id, d.estado AS estado_fuente, d.soporte
FROM   asercion a JOIN documento d ON d.documento_id = a.documento_id
WHERE  a.medida = 'matriculados'
  AND  a.es_preferida AND NOT a.descartada;
```

One view per measure. **Every chart reads views; nothing reads `asercion` directly.**
Changing which source is canonical is one flag update, not forty chart edits — and because
`poblacion` and `soporte` ride along, any tile can display what it is actually showing and
how well-sourced it is.

---

## 7. The inconsistency model

Twenty-two known inconsistencies fall into three classes that require genuinely different
handling. **Conflating them is the most likely way this model fails.**

| Class | Definition | Disposition | Dashboard |
|---|---|---|---|
| **Error** | Two statements cannot both hold under any reading — arithmetic fails, or metadata contradicts content | one assertion becomes `es_preferida`; the other `descartada` with a reason | flagged until resolved, then hidden |
| **Divergence** | Statements differ because they count different populations, scopes or grains. Both are true | no winner. The view is parameterised by `poblacion` / `base_medicion` | a permanent basis selector |
| **Gap** | No statement exists | encoded per the absence rules below | completeness metric, never zero |

> **The distribution matters.** Of the twenty-two, **four are errors, seven are divergences
> and eleven are gaps.** This is *not* a data-cleanup project. Most of what looks like bad
> data is two institutions measuring different things on purpose, and the model's job is to
> carry both rather than adjudicate.

### 7.1 Absence has three meanings

| Situation | Encode as | Example in this corpus |
|---|---|---|
| Unknown / not recorded | `NULL` | sub-línea, blank in all 9 projects |
| Not applicable by design | **row absent** | PIC-ET has no cupos and will not until 2027 |
| Recorded and genuinely zero | `0` | regular admissions from Amazonía's catchment, three periods running |
| Dimension member with no facts | row in dimension, none in fact | quartile `(0.586,0.649]`; three unused funding sources |
| Source document absent | `documento.estado='CITADO'` | Res. 08596/2023 · Acuerdo 011/2025 |

The third and fourth rows are the dangerous pair. **Amazonía's zero is a finding** — the
sede's own catchment produced no regular admissions, which is the argument for PAET and
PEAMA existing. **A missing quartile band is not a finding, it is a hole.** A `LEFT JOIN`
that renders both as `0` destroys the difference.

### 7.2 Every known inconsistency, and the mechanism that carries it

| # | Inconsistency | Class | Carried by |
|---|---|---|---|
| 1 | Enrolment 1 161 / 1 043 / −1 168 | Div | `asercion.poblacion` |
| 2 | Commitment 1 818 vs 1 836 | Err | `asercion.descartada` |
| 3 | Admin posts 50 vs 28 vs 37 | Err | `cargo_creado` vs `asercion` |
| 4 | Money $68.5 mM vs $9.56 mM | Div | `fuente_financiacion` + `poblacion` |
| 5 | ETC 191.5 headlined vs 394.5 created | Div | `cargo_creado` vs `asercion` |
| 6 | Two documents named "Anexo 2" | Err | `documento_id` + `emisor` |
| 7 | "Sede Arauca" vs Orinoquía | Err | `unidad_alias` |
| 8 | PAET vs PIC-ET name collision | — | `via_admision` vs `ciclo.modalidad` |
| 9 | Res. 08596/2023 absent | Gap | `documento.estado='CITADO'` |
| 10 | Acuerdo 011/2025 absent | Gap | `documento.estado='CITADO'` |
| 11 | La Paz has no funding | Gap | no `proyecto_financiacion` rows |
| 12 | Sub-línea blank everywhere | Gap | `proyecto.sublinea_id NULL` |
| 13 | Quartile band never appears | Gap | `cuartil.observado=FALSE` |
| 14 | Three funding columns empty | Gap | declared dimension, no facts |
| 15 | Stages 02, 03, 05 undocumented | Gap | `ciclo_etapa.documento_id NULL` |
| 16 | Anexo 2 filename says 2023–24, content 2025 | Err | `documento.titulo` vs `ciclo_id` |
| 17 | Oficio `XXX` placeholder, year mismatch | Err | `conflicto`, impacto ALTO |
| 18 | Pic_Info-3 not in the Oficio's enumeration | Gap | separate `ciclo_etapa` occurrence |
| 19 | FCV reported at two grains | Div | `nivel_reportado` |
| 20 | 419 rezago seats double-countable | Div | `compromiso.es_rezago` |
| 21 | 1 161 / 1 043 count different populations | Div | `asercion.poblacion` |
| 22 | Two rubro generations, no bridge | Gap | `rubro_mapping` (empty) |

---

## 8. Invariants

Enforced by the database or by a test that runs on every load — not by convention, and not
by a note in a document.

| # | Invariant |
|---|---|
| **R1** | **At most one preferred assertion** per `(medida, ciclo_id, unidad_id, periodo_id, poblacion, base_medicion)`. A unique partial index on `es_preferida`. |
| **R2** | **No aggregate crosses `nivel_reportado`.** Summing a `UNIDAD` row with a `SEDE` row double-counts FCV inside Medellín. |
| **R3** | **Commitment totals exclude rezago.** `SUM(cupos) WHERE NOT es_rezago` is the only sanctioned expression; anything else counts 419 students twice. |
| **R4** | **Every assertion cites a document.** `documento_id NOT NULL`, with no orphan permitted. |
| **R5** | **Held documents have a path; cited ones do not.** Enforced by the paired CHECK on `documento`. |
| **R6** | **Carry-forward points forward only.** `ciclo_origen.anio_formulacion < ciclo_destino.anio_formulacion`. This keeps the lineage acyclic and recursive queries terminating. |
| **R7** | **No load job creates a dimension member.** An unrecognised sede, rubro or quartile fails the load rather than silently extending the vocabulary. |
| **R8** | **Cross-generation rubro queries join through `rubro_mapping`** and return nothing where no mapping exists. |
| **R9** | **Nothing but a view reads `asercion`.** Direct access permits `SUM(1161, 1043)`, which is the single most damaging query available against this model. |

> **R9 is the one that will be violated.** It is the only invariant a database cannot
> enforce on its own. Whatever the serving arrangement, `asercion` should not be reachable
> by whoever builds charts — expose the views and nothing else. Every other rule here fails
> loudly; this one fails as a plausible-looking number.

---

## 9. Load discipline

| # | Rule |
|---|---|
| **R1** | **Append only.** No `UPDATE` against `asercion`. A correction is a new row with `reemplaza_a` set; the original stays readable. |
| **R2** | **Retain the literal.** `valor_origen` keeps the source string before parsing — `"31,5"`, `"Indefinido"`, `"Bolsa"`. Parsing is lossy and sometimes wrong. |
| **R3** | **Locate everything.** `ubicacion` records table number, sheet cell or paragraph. Drill-through is only as good as this field. |
| **R4** | **Resolve aliases at load, never at source.** `"Sede Arauca"` maps through `unidad_alias`; the spreadsheet is never rewritten. |
| **R5** | **State the population or fail.** `poblacion` is `NOT NULL`. A figure whose counted population cannot be determined from its document does not get loaded — it gets filed as a question. |
| **R6** | **Mark second-hand figures.** Any amount quoted by a report about a scanned resolution is an assertion against the *report*, not against the resolution. Attributing it to the resolution implies a transcription nobody has performed. |

> **Consequence of R6.** Until the five scanned resolutions are transcribed, every peso
> attributed to Resolución 016202, 018433, 018970, 016468 or 019862 is sourced to a
> narrative report quoting it. `documento.soporte = 'ESCANEO'` makes that visible, and a
> completeness tile can state plainly what proportion of the financial layer has no primary
> source.

---

## 10. Decisions this schema defers

The model is designed to hold these open rather than force them, but each must be answered
before a default view can be published.

| Decision | What it sets | Blocks |
|---|---|---|
| Canonical enrolment population | `v_matricula.es_preferida` | every seat chart |
| Default `base_medicion` | admitidos vs matriculados | every balance, and the MEN position |
| Whether $68.5 mM and $9.56 mM are one measure | `fuente_financiacion` semantics | every money chart |
| Whether FCV is a unit or part of Medellín | `unidad_academica.tipo` | Medellín's totals |
| Whether to transcribe the five scans | `documento.soporte` | primary sourcing of all financial figures |
| Scope: UNAL alone, or 12 IES | whether `ies` becomes a dimension | the shape of every key |

---

*Specification derived from the 23-file PIC corpus, 2023–2026. Companion to the PIC Corpus
Taxonomy.*
