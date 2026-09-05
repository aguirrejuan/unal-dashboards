# PIC Data Model — v2

**Plan Integral de Cobertura — build specification, revision 2**

Supersedes `pic-data-model.md` (v1), which is retained for diff. This revision incorporates
four independent adversarial reviews — domain/policy, data modelling, BI serving, and a
forensic evidence audit that transcribed the five scanned MEN resolutions for the first
time.

> SQL is generic DDL describing structure. No storage engine is implied.

---

## Contents

- [§0 What changed from v1](#0-what-changed-from-v1)
- [§1 Principles](#1-principles)
- [§2 Architecture — one declaration store](#2-architecture--one-declaration-store)
- [§3 Reference tables](#3-reference-tables)
- [§4 The process, as data](#4-the-process-as-data)
- [§5 Structural facts](#5-structural-facts)
- [§6 Declarations, disposition and views](#6-declarations-disposition-and-views)
- [§7 The inconsistency model](#7-the-inconsistency-model)
- [§8 Invariants](#8-invariants)
- [§9 Load discipline](#9-load-discipline)
- [§10 Blocking prerequisites](#10-blocking-prerequisites)
- [Appendix — review provenance](#appendix--review-provenance)

---

## 0. What changed from v1

| # | v1 defect | Severity | v2 resolution |
|---|---|---|---|
| 1 | `asercion` had nullable grain columns; the R1 unique index **cannot exist** (NULL ≠ NULL), so two `es_preferida` rows reach the sanctioned view and `SUM` returns 2 204 | **Critical** | Grain columns `NOT NULL` with sentinel dimension members; views single-valued by construction |
| 2 | `nivel_reportado` was claimed to prevent the FCV double-count. It does not — it is an unconstrained label, and `sede_id = unidad_id` puts Medellín inside its own descendant set | **Critical** | `unidad_rollup` closure table; aggregates only through `distancia > 0`; CHECK binding level to `tipo` |
| 3 | No idempotency key anywhere. Re-running a loader doubles the corpus and **every v1 invariant still passes** | **Critical** | Natural-key `UNIQUE` on every fact table and on `declaracion` |
| 4 | `poblacion TEXT NOT NULL` — a free string as the load-bearing key column, contradicting v1's own R4/R7 | **High** | `poblacion` becomes a declared dimension with structured attributes; literal retained beside it |
| 5 | §6.2 said "one flag update"; §9/R1 said "no `UPDATE` against `asercion`" — a direct self-contradiction | **High** | Disposition moves to a temporal `declaracion_disposicion`, keyed **per vista** (UNAL / MEN / AUDITOR) |
| 6 | R2 ("never stored without its claimant") enforced on `asercion` only — 5 of 7 fact tables had no `documento_id` | **High** | `documento_id` + `ubicacion` mandatory on every fact table |
| 7 | `asercion` had no unit column: `191.5 ETC + 1 161 people + 9.56e9 pesos` was a legal sum | **High** | `medida` dimension carries `unidad_medida`, `tipo_agregacion`, `aditiva` |
| 8 | `matriculados` is a **stock**; nothing prevented summing across `periodo` | **High** | `tipo_agregacion ∈ {STOCK, FLUJO}`; stock measures un-summable across time in views |
| 9 | Money modelled as per-cycle amounts; no `vigencia`. Art. 124 money is added to the **recurrent operating base** | **High** | `vigencia`, `tipo_flujo` and `momento` on all money facts, distinct from `ciclo_id` |
| 10 | `ciclo` treated as the process instance; PIC 2023 was 8 separately-approved projects | **High** | Project grain for `compromiso` and `proyecto_etapa`; `declaracion_alcance` makes 1 161 vs 1 043 a computable set difference |
| 11 | PIC-CO and PIC-ET as two values of one enum; `compromiso.cupos NOT NULL` made an ET commitment impossible | **Medium** | `programa` above `ciclo`, with `programa_medida_permitida` failing invalid measures at load |
| 12 | Primary/assertion split drawn on document **genre**, not grain — two sources of truth for the same number | **Medium** | One declaration store; `tipo_declaracion` + `es_agregado_de` makes "does the total equal its parts?" runnable |
| 13 | `cobertura_territorial` could not store the Amazonía-across-three-periods example v1 used to justify its own rule | **Medium** | `periodo_id` added to the key |
| 14 | `sede_id` unvalidated; could contradict `padre_id`. No cycle prevention on `padre_id` or `rubro.padre_id` | **Medium** | Composite FK on `(sede_id,'SEDE')`; CHECKs; closure table maintained by trigger |
| 15 | `via_admision`, `fuente_financiacion`, `departamento`, `municipio` referenced by FK but **never defined** | **Medium** | Defined in §3 |
| 16 | `rubro_mapping` rows with `confianza='SIN_MAPEO'` mis-bucket on a naive JOIN | **Low** | Moved to an attribute of `rubro`; the bridge holds only real mappings |
| 17 | `es_rezago` and `arrastre` redundant and able to disagree | **Low** | `cupos_rezago` derived as a view; `arrastre` keeps money only |
| 18 | `presupuesto_rubro` PK on free-text `concepto` | **Low** | Surrogate PK + `concepto_id` FK + literal |
| 19 | R9 ("nothing but a view reads `asercion`") stated as an invariant | **Low** | Restated as a **process control** — grants, an owner SLA, and a published-chart test |
| 20 | Orden 422447 excluded as unrelated | **Correction** | Its p.3 activity report cites PIC by name; it enters `documento` as `UNAL_RECTORIA` |

### Findings from the evidence audit that change the data itself

The five MEN resolutions had never been transcribed. Doing so revealed that **three of six
report-quoted resolution amounts are wrong**, and settled the largest open question.

| Finding | Detail |
|---|---|
| **$9 561 136 948 is now primary-sourced** | Res. 016468, p.2, UNIDAD 225701: UNAL total **$55 677 365 786** = REC 10 `46 116 228 838` + REC 11 **`9 561 136 948`**. Acuerdo 052/2025 labels that line *"AMPLIACIÓN DE COBERTURA - PIC"* |
| **Anexo 2 column N is corrupted, not a different measure** | $68 505 589 464 reconciles to no resolution or tranche. Bogotá's N = P exactly; Palmira's "Indexación" cell holds the verbatim un-indexed 2023 allocation. **Reclassified Error, impacto ALTO** — v1 had it as a Divergence |
| Res. 019862 misquoted | Report says $2 313 166 700; scan says **$2 738 054 656** |
| Res. 016468 misquoted | Report says $46 115 857 101; matches neither the total nor either component |
| Res. 18433 mis-described | Acuerdo 024/2025 calls it *inversión*; the scan places UNAL under **FUNCIONAMIENTO** — material, since art. 124 is a funcionamiento mechanism |
| "Res. 08596 de 2023" does not exist | It is **Resolución 8596 del 27 de mayo de 2024**, and its content is transcribed in Acuerdo 024/2025 — so it was never a gap |

---

## 1. Principles

| # | Rule | Change |
|---|---|---|
| **P1** | **Transcribe, never correct.** Load rejects nothing on grounds of implausibility. | — |
| **P2** | **No value without its claimant and its location.** Every fact row carries `documento_id` and `ubicacion`. | widened to all tables |
| **P3** | **Disagreement is data.** Both rows persist. Resolution is a disposition record, not an edit. | — |
| **P4** | **Every categorical is a declared dimension with an FK.** No free-text enum anywhere in a key or a filter. | strengthened |
| **P5** | **No nullable grain column.** Absence at a grain is a sentinel member, not `NULL`. | new |
| **P6** | **Every measure declares its unit and its aggregation type.** Stocks are not summable across time. | new |
| **P7** | **Every load is idempotent.** Re-running produces no new rows. | new |
| **P8** | **Editorial decisions are versioned and attributed to a viewpoint.** There is no global "correct" value. | new |

---

## 2. Architecture — one declaration store

v1 split "primary facts" from "assertions" by document genre. That split was unprincipled:
Anexo 2 cell `T10` is legitimately both, an Acuerdo's own "Total: 191,5" line is both, and
v1's own inconsistency table conceded the problem twice.

v2 keeps **structural** tables (things that are relationships, not measurements) and routes
**every number** through one store, typed by a `medida` dimension.

| Layer | Holds | Mutability |
|---|---|---|
| Reference | dimensions, process definition, document register | curated, versioned |
| Structural | `proyecto`, `unidad_academica`, `arrastre`, `cargo_creado` — relationships and their attributes | append + natural key |
| `declaracion` | **every measured number**, transcribed or aggregate | append-only, idempotent |
| `declaracion_disposicion` | which declaration each viewpoint prefers, over time | append-only, temporal |
| Views | single-valued, per measure, per vista | derived |

`tipo_declaracion ∈ {TRANSCRIPCION, AGREGADO}` distinguishes a figure copied from a source
table from a figure asserted about a set. `es_agregado_de` links an aggregate to its
components — which makes *"does the claimed 191.5 equal the sum of its parts?"* a runnable
test rather than an argument.

---

## 3. Reference tables

### 3.1 Sentinel members — the fix for nullable grain

Every dimension carries an explicit "all" or "not applicable" member. Facts never store
`NULL` in a grain column.

```sql
-- e.g. in unidad_academica
INSERT INTO unidad_academica (unidad_id, nombre, tipo, padre_id, sede_id) VALUES
  ('UNAL_TOTAL', 'Universidad Nacional (agregado)', 'UNIVERSIDAD', NULL, 'UNAL_TOTAL');
-- likewise ciclo('TODOS'), periodo('NA'), etc.
```

This is what makes uniqueness enforceable and stops a sede filter silently dropping
university-level rows.

### 3.2 Academic units — validated hierarchy plus closure

```sql
CREATE TABLE unidad_academica (
  unidad_id       TEXT PRIMARY KEY,
  nombre          TEXT NOT NULL,
  tipo            TEXT NOT NULL REFERENCES tipo_unidad,   -- UNIVERSIDAD|SEDE|FACULTAD|UNIDAD_DOCENCIA
  padre_id        TEXT REFERENCES unidad_academica,
  sede_id         TEXT NOT NULL,
  grupo           TEXT REFERENCES grupo_sede,             -- SPN|ANDINA|OTRA
  departamento_id TEXT REFERENCES departamento,
  municipio_id    TEXT REFERENCES municipio,
  valido_desde    DATE NOT NULL,
  valido_hasta    DATE,                                   -- FCV: part of Medellín pre-2025
  UNIQUE (unidad_id, tipo),
  FOREIGN KEY (sede_id, 'SEDE') REFERENCES unidad_academica (unidad_id, tipo),
  CHECK ((padre_id IS NULL) = (sede_id = unidad_id))
);

-- transitive closure, maintained by trigger; distancia 0 = self
CREATE TABLE unidad_rollup (
  ancestro_id     TEXT NOT NULL REFERENCES unidad_academica,
  descendiente_id TEXT NOT NULL REFERENCES unidad_academica,
  distancia       INT  NOT NULL,
  PRIMARY KEY (ancestro_id, descendiente_id)
);
```

**Aggregation rule.** A sede total is `JOIN unidad_rollup ON ancestro_id = :sede AND
distancia > 0`. Never `WHERE sede_id = :sede`, which in v1 included the sede's own row and
returned 41 + 25 = 66 for Medellín.

`valido_desde`/`valido_hasta` exist because FCV's status is a **type-2 change**, not a
one-off decision: it was part of Medellín in 2023 and an allocation unit in 2025. Resolving
it as a single `tipo` retroactively rewrites the 2023 grain.

### 3.3 Programme, cycle, vigencia, period

```sql
CREATE TABLE programa (
  programa_id  TEXT PRIMARY KEY,          -- 'PIC_CO' | 'PIC_ET'
  nombre       TEXT NOT NULL,
  instrumento  TEXT,                      -- creating act
  contraparte  TEXT                       -- UNAL sedes | secretarías + IE
);

CREATE TABLE programa_medida_permitida (   -- an ET 'cupos' row fails at load, not at render
  programa_id TEXT NOT NULL REFERENCES programa,
  medida_id   TEXT NOT NULL REFERENCES medida,
  PRIMARY KEY (programa_id, medida_id)
);

CREATE TABLE ciclo (
  ciclo_id           TEXT PRIMARY KEY,     -- 'PIC_CO_2023' … 'PIC_ET_2026'
  programa_id        TEXT NOT NULL REFERENCES programa,
  anio_formulacion   INT  NOT NULL,
  periodo_ejec_desde TEXT NOT NULL REFERENCES periodo,
  periodo_ejec_hasta TEXT NOT NULL REFERENCES periodo,
  estado             TEXT NOT NULL REFERENCES estado_ciclo
);

CREATE TABLE periodo (
  periodo_id    TEXT PRIMARY KEY,          -- '2024-1' … '2028-1', plus 'NA'
  anio          INT, semestre INT,
  orden         INT NOT NULL,
  es_proyectado BOOLEAN NOT NULL DEFAULT FALSE
);
```

There is deliberately **no column named `anio`** exposed in any view. A user who drags
"year" onto an axis sees PIC 2025 at zero and reads it as non-execution, when in fact it
does not execute until 2026-2.

### 3.4 The measure dimension — units and aggregation

```sql
CREATE TABLE medida (
  medida_id       TEXT PRIMARY KEY,    -- matriculados|admitidos|cupos_ofertados
                                       -- |compromiso|monto|cargos_creados|cargos_provistos
  nombre          TEXT NOT NULL,
  unidad_medida   TEXT NOT NULL,       -- PERSONAS | CUPOS | COP | ETC | CARGOS
  tipo_agregacion TEXT NOT NULL,       -- STOCK | FLUJO
  aditiva_unidad  BOOLEAN NOT NULL,    -- may it sum across unidad_academica?
  aditiva_tiempo  BOOLEAN NOT NULL     -- may it sum across periodo?  STOCK ⇒ FALSE
);
```

`matriculados` is a **stock**: a student enrolled in 2024-1 is still enrolled in 2024-2.
Summing across periods doubles the cohort — a query as damaging as the one v1 warned about,
and v1 left it unguarded. Enrolment against a seat target must be modelled as a **flow**
(`primera_matricula`).

### 3.5 Population — a dimension, not a sentence

```sql
CREATE TABLE poblacion (
  poblacion_id     TEXT PRIMARY KEY,
  etiqueta_corta   TEXT NOT NULL,       -- for the UI slicer
  definicion       TEXT NOT NULL REFERENCES definicion_medida,
                                        -- PRIMERA_MATRICULA|MATRICULA_GLOBAL
                                        -- |MATRICULA_EFECTIVA|PRIMER_CURSO_SNIES|ADMITIDOS
  incluye_la_paz   BOOLEAN NOT NULL,
  alcance_proyecto TEXT,                -- '8 proyectos aprobados' | 'consolidado'
  fecha_corte      DATE,
  orden            INT NOT NULL
);
```

This is the change that makes the divergence machinery work. In v1 the question that
*explains* 1 161 vs 1 043 — "which figures include La Paz?" — required `LIKE '%La Paz%'`.
Here it is a boolean column, and the UI slicer is a stable ten-row dimension rather than
`SELECT DISTINCT` over drifting prose.

### 3.6 Documents, radicados and citation

```sql
CREATE TABLE documento (
  documento_id TEXT PRIMARY KEY,
  tipo         TEXT NOT NULL REFERENCES tipo_documento,
  emisor       TEXT NOT NULL REFERENCES emisor,
  numero       TEXT, fecha DATE, titulo TEXT,
  estado       TEXT NOT NULL REFERENCES estado_documento,  -- EN_CORPUS|CITADO|NUNCA_PRODUCIDO
  soporte      TEXT REFERENCES soporte,                    -- TEXTO|ESCANEO|TRANSCRITO
  ruta_archivo TEXT,
  CHECK (estado <> 'EN_CORPUS' OR (ruta_archivo IS NOT NULL AND soporte IS NOT NULL)),
  CHECK (estado =  'EN_CORPUS' OR  ruta_archivo IS NULL)
);

CREATE TABLE documento_cita (      -- which document asserts the existence of which
  citante_id TEXT NOT NULL REFERENCES documento,
  citado_id  TEXT NOT NULL REFERENCES documento,
  ubicacion  TEXT,
  PRIMARY KEY (citante_id, citado_id),
  CHECK (citante_id <> citado_id)
);

CREATE TABLE documento_ciclo (     -- an Acuerdo may serve several cycles
  documento_id TEXT NOT NULL REFERENCES documento,
  ciclo_id     TEXT NOT NULL REFERENCES ciclo,
  PRIMARY KEY (documento_id, ciclo_id)
);

CREATE TABLE radicado (
  radicado_id  TEXT PRIMARY KEY,
  direccion    TEXT NOT NULL REFERENCES direccion_radicado,
  fecha        DATE
);
CREATE TABLE radicado_documento (  -- a radicado bundles documents; v1 inverted this
  radicado_id  TEXT NOT NULL REFERENCES radicado,
  documento_id TEXT NOT NULL REFERENCES documento,
  PRIMARY KEY (radicado_id, documento_id)
);
```

`soporte = 'TRANSCRITO'` is new: the five scans have now been read, and that is a different
state from both `ESCANEO` and `TEXTO`. `documento_cita` makes *"which held figures depend on
an untranscribed scan?"* a query — in v1 it was prose.

### 3.7 Rubros, admission routes, funding sources

```sql
CREATE TABLE rubro (
  rubro_id    TEXT PRIMARY KEY,
  generacion  TEXT NOT NULL REFERENCES generacion_rubro,  -- PRE_2025 | V2025
  nivel       TEXT NOT NULL,                              -- LINEA | SUBLINEA
  padre_id    TEXT REFERENCES rubro,
  nombre      TEXT NOT NULL,
  mapeable    BOOLEAN NOT NULL DEFAULT TRUE   -- was confianza='SIN_MAPEO', a bridge row
);

CREATE TABLE rubro_mapping (        -- holds ONLY real mappings; empty until curated
  rubro_origen  TEXT REFERENCES rubro,
  rubro_destino TEXT REFERENCES rubro,
  confianza     TEXT NOT NULL REFERENCES confianza_mapeo,  -- EXACTA | PARCIAL
  PRIMARY KEY (rubro_origen, rubro_destino)
);

CREATE TABLE via_admision (         -- referenced but never defined in v1
  via_id      TEXT PRIMARY KEY,     -- REGULAR | PEAMA | PAET | PTIUN
  nombre      TEXT NOT NULL,
  programa_id TEXT NOT NULL REFERENCES programa,
  acuerdo_id  TEXT REFERENCES documento
);

CREATE TABLE fuente_financiacion ( -- referenced but never defined in v1
  fuente_id    TEXT PRIMARY KEY,
  nombre       TEXT NOT NULL,
  tipo_flujo   TEXT NOT NULL REFERENCES tipo_flujo,
  columna_xlsx TEXT               -- provenance to the Anexo 2 column
);
```

Moving `SIN_MAPEO` out of the bridge matters: as a row it mis-buckets on a naive `JOIN`
unless every query remembers to exclude it.

### 3.8 Quartiles

```sql
CREATE TABLE cuartil_prioridad (
  cuartil_id TEXT PRIMARY KEY,
  notacion   TEXT NOT NULL,
  limite_inf NUMERIC NOT NULL, limite_sup NUMERIC NOT NULL,
  observado  BOOLEAN NOT NULL     -- FALSE for (0.586,0.649]
);
```

Unchanged from v1 — all three reviews cleared this pattern.

---

## 4. The process, as data

v1's seven stages were broadly real but under-specified at the two points that decide
outcomes. v2 splits them.

| Stage | Actor | Change from v1 |
|---|---|---|
| E01 Asignación | MEN + MinHacienda DGPPN | **DNP removed** — it has no role in a *funcionamiento* transfer |
| **E02 Ejecución presupuestal** | MinHacienda / UNAL | **New.** Adición, SIIF registration, CDP/RP, giro. v1 jumped from signature to spending as if money moved on signature |
| E03 Formulación | UNAL → MEN | now at **project** grain |
| E04 Revisión · mesa técnica | MEN ↔ UNAL | — |
| E05 Autorización interna | CNF → CNCA → CSU | — |
| **E06 Convocatoria** | DNA + sedes | **Split out of v1's E05.** inscritos → admitidos |
| **E07 Vinculación** | sedes | **Split out.** concurso docente → `cargo_provisto`; 12–24 months |
| **E08 Matrícula** | sedes | **Split out.** This is where the 1 809 → 1 161 drop lives |
| E09 Reporte | UNAL → MEN | — |
| **E10 Control** | Contraloría / supervisión | **New.** The stage that ultimately adjudicates these divergences |

`arrastre` is **no longer a stage**. It is a relation, already modelled by its own table;
having it in both places invited contradiction.

```sql
CREATE TABLE proyecto_etapa (      -- was ciclo_etapa; PIC 2023 was 8 separate approvals
  proyecto_id  TEXT NOT NULL REFERENCES proyecto,
  etapa_id     TEXT NOT NULL REFERENCES etapa,
  ocurrencia   INT  NOT NULL DEFAULT 1,
  fecha        DATE,
  estado       TEXT NOT NULL REFERENCES estado_etapa,
  documento_id TEXT REFERENCES documento,
  radicado_id  TEXT REFERENCES radicado,
  PRIMARY KEY (proyecto_id, etapa_id, ocurrencia)
);
```

---

## 5. Structural facts

Every table below carries `documento_id` and `ubicacion` — v1 had them on `asercion` only,
which killed drill-through on precisely the numbers that reach a dashboard.

```sql
CREATE TABLE proyecto (
  proyecto_id   TEXT PRIMARY KEY,
  ciclo_id      TEXT NOT NULL REFERENCES ciclo,
  unidad_id     TEXT NOT NULL REFERENCES unidad_academica,
  numero        INT  NOT NULL,
  nombre        TEXT NOT NULL,
  linea_id      TEXT REFERENCES rubro,
  sublinea_id   TEXT REFERENCES rubro,
  documento_id  TEXT NOT NULL REFERENCES documento,
  ubicacion     TEXT NOT NULL,
  UNIQUE (ciclo_id, numero)                        -- idempotency
);

CREATE TABLE compromiso (          -- project grain, not cycle grain
  compromiso_id   TEXT PRIMARY KEY,
  proyecto_id     TEXT NOT NULL REFERENCES proyecto,
  unidad_id       TEXT NOT NULL REFERENCES unidad_academica,
  cupos           INT  NOT NULL,
  es_rezago       BOOLEAN NOT NULL DEFAULT FALSE,
  ciclo_origen_id TEXT REFERENCES ciclo,
  documento_id    TEXT NOT NULL REFERENCES documento,
  ubicacion       TEXT NOT NULL,
  CHECK (es_rezago = FALSE OR ciclo_origen_id IS NOT NULL),
  UNIQUE (proyecto_id, unidad_id, es_rezago, ciclo_origen_id)
);

CREATE TABLE cargo_creado (
  documento_id TEXT NOT NULL REFERENCES documento,
  unidad_id    TEXT NOT NULL REFERENCES unidad_academica,
  tipo         TEXT NOT NULL REFERENCES tipo_cargo,
  cantidad     NUMERIC NOT NULL,        -- Palmira: 31,5 ETC
  costo_total  NUMERIC,
  ubicacion    TEXT NOT NULL,
  PRIMARY KEY (documento_id, unidad_id, tipo)
);

CREATE TABLE cargo_provisto (      -- new: created ≠ filled; concurso runs 12–24 months
  unidad_id  TEXT NOT NULL REFERENCES unidad_academica,
  tipo       TEXT NOT NULL REFERENCES tipo_cargo,
  periodo_id TEXT NOT NULL REFERENCES periodo,
  cantidad   NUMERIC NOT NULL,
  documento_id TEXT NOT NULL REFERENCES documento,
  ubicacion  TEXT NOT NULL,
  PRIMARY KEY (unidad_id, tipo, periodo_id)
);

CREATE TABLE cobertura_territorial (
  ciclo_id    TEXT NOT NULL REFERENCES ciclo,
  unidad_id   TEXT NOT NULL REFERENCES unidad_academica,
  periodo_id  TEXT NOT NULL REFERENCES periodo,   -- v1 omitted this and could not store
  cuartil_id  TEXT NOT NULL REFERENCES cuartil_prioridad,
  via_id      TEXT NOT NULL REFERENCES via_admision,
  estudiantes INT  NOT NULL,
  documento_id TEXT NOT NULL REFERENCES documento,
  ubicacion   TEXT NOT NULL,
  PRIMARY KEY (ciclo_id, unidad_id, periodo_id, cuartil_id, via_id)
);

CREATE TABLE arrastre (            -- money only; cupos_rezago now derived
  ciclo_origen_id  TEXT NOT NULL REFERENCES ciclo,
  ciclo_destino_id TEXT NOT NULL REFERENCES ciclo,
  monto_saldo      NUMERIC,
  vigencia         INT NOT NULL,
  documento_id     TEXT NOT NULL REFERENCES documento,
  ubicacion        TEXT NOT NULL,
  PRIMARY KEY (ciclo_origen_id, ciclo_destino_id, vigencia)
);
```

### Money carries a vigencia, a flow type and a moment

```sql
CREATE TABLE asignacion (
  asignacion_id TEXT PRIMARY KEY,
  documento_id  TEXT NOT NULL REFERENCES documento,
  ubicacion     TEXT NOT NULL,
  unidad_id     TEXT NOT NULL REFERENCES unidad_academica,
  ciclo_id      TEXT NOT NULL REFERENCES ciclo,     -- may be the 'TODOS' sentinel
  vigencia      INT  NOT NULL,                      -- fiscal year — NOT the cycle year
  fuente_id     TEXT NOT NULL REFERENCES fuente_financiacion,
  tipo_flujo    TEXT NOT NULL REFERENCES tipo_flujo,
                -- ADICION_BASE_RECURRENTE | POR_UNA_VEZ | VIGENCIA_FUTURA | SALDO
  momento       TEXT NOT NULL REFERENCES momento_presupuestal,
                -- ASIGNADO | INCORPORADO | COMPROMETIDO | GIRADO
  recurso       TEXT,                               -- 'REC 10' | 'REC 11'
  monto         NUMERIC NOT NULL,
  UNIQUE (documento_id, ubicacion, unidad_id, vigencia, fuente_id, momento)
);
```

`vigencia` separate from `ciclo_id` is the fix for v1's most consequential modelling gap.
Art. 124 money is added to the **recurrent** operating base: once granted it persists and is
indexed forward. v1 could not answer *"how much PIC money does UNAL have in 2026?"*, which
is the only budget question that exists.

`momento` exists because assignment is not disbursement. UNAL's real operational grievance
is usually the gap between `ASIGNADO` and `GIRADO`, and v1 could not express it.

---

## 6. Declarations, disposition and views

```sql
CREATE TABLE declaracion (
  declaracion_id   BIGSERIAL PRIMARY KEY,
  tipo_declaracion TEXT NOT NULL REFERENCES tipo_declaracion,  -- TRANSCRIPCION | AGREGADO
  medida_id        TEXT NOT NULL REFERENCES medida,

  -- grain: all NOT NULL, sentinels where a dimension does not apply
  ciclo_id     TEXT NOT NULL REFERENCES ciclo,
  unidad_id    TEXT NOT NULL REFERENCES unidad_academica,
  periodo_id   TEXT NOT NULL REFERENCES periodo,
  poblacion_id TEXT NOT NULL REFERENCES poblacion,

  valor        NUMERIC NOT NULL,

  documento_id  TEXT NOT NULL REFERENCES documento,
  ubicacion     TEXT NOT NULL,
  valor_origen  TEXT,                    -- '31,5' | 'Bolsa' | 'Indefinido'
  fecha_asercion DATE NOT NULL,          -- when the claim was made, for restatement series

  UNIQUE (documento_id, ubicacion, medida_id,
          ciclo_id, unidad_id, periodo_id, poblacion_id)   -- idempotency
);

CREATE TABLE es_agregado_de (     -- makes "total = sum of parts?" a runnable test
  agregado_id  BIGINT NOT NULL REFERENCES declaracion,
  componente_id BIGINT NOT NULL REFERENCES declaracion,
  PRIMARY KEY (agregado_id, componente_id)
);

CREATE TABLE declaracion_alcance (  -- which projects a figure covers
  declaracion_id BIGINT NOT NULL REFERENCES declaracion,
  proyecto_id    TEXT   NOT NULL REFERENCES proyecto,
  PRIMARY KEY (declaracion_id, proyecto_id)
);
```

`declaracion_alcance` turns the corpus's flagship divergence into arithmetic: 1 161 covers
the eight approved projects, 1 043 covers a consolidation including La Paz. In v1 that was a
prose string; here it is a computable set difference.

### Disposition — per viewpoint, over time

```sql
CREATE TABLE vista (
  vista_id TEXT PRIMARY KEY        -- UNAL | MEN | AUDITOR
);

CREATE TABLE declaracion_disposicion (
  vista_id       TEXT   NOT NULL REFERENCES vista,
  declaracion_id BIGINT NOT NULL REFERENCES declaracion,
  es_preferida   BOOLEAN NOT NULL,
  descartada     BOOLEAN NOT NULL DEFAULT FALSE,
  motivo         TEXT,
  valido_desde   DATE NOT NULL,
  valido_hasta   DATE,
  CHECK (NOT (es_preferida AND descartada)),
  CHECK (descartada = FALSE OR motivo IS NOT NULL)
);
```

v1's single global `es_preferida` meant the database could hold only **one** reading of the
corpus. In a live negotiation you need two complete, internally consistent readings —
UNAL's and MEN's — renderable side by side.

### Compliance criteria — the thing actually in dispute

```sql
CREATE TABLE criterio_cumplimiento (
  criterio_id       TEXT PRIMARY KEY,
  numerador_medida  TEXT NOT NULL REFERENCES medida,   -- admitidos | matriculados
  denominador_medida TEXT NOT NULL REFERENCES medida,  -- compromiso
  sostenido_por     TEXT NOT NULL REFERENCES vista,
  fundamento_documento_id TEXT REFERENCES documento    -- T-437/2020, T-356/2020
);
```

UNAL and MEN do not disagree about how many people enrolled. They disagree about **what
counts as compliance**. v1 put `base_medicion` on the assertion, as if it were a property of
the number. It is a property of the grading rule — and the grading rule is the actual
subject of this corpus.

### Views — single-valued by construction

```sql
CREATE VIEW v_matricula AS
SELECT d.ciclo_id, d.unidad_id, d.periodo_id,
       p.etiqueta_corta AS poblacion, p.incluye_la_paz,
       d.valor AS matriculados,
       d.documento_id, doc.estado AS estado_fuente, doc.soporte,
       v.vista_id
FROM   declaracion d
JOIN   declaracion_disposicion dd ON dd.declaracion_id = d.declaracion_id
                                 AND dd.valido_hasta IS NULL
                                 AND dd.es_preferida
JOIN   vista v      ON v.vista_id = dd.vista_id
JOIN   poblacion p  ON p.poblacion_id = d.poblacion_id
JOIN   documento doc ON doc.documento_id = d.documento_id
WHERE  d.medida_id = 'matriculados';
```

**One row per `(grain, vista)`.** v1's view returned both 1 161 and 1 043 because
`poblacion` sat inside the uniqueness key but outside the view's filter — so `SUM` returned
2 204 through the sanctioned path. Enforced by:

```sql
CREATE UNIQUE INDEX ux_disp_preferida
  ON declaracion_disposicion (vista_id, declaracion_id)
  WHERE es_preferida AND valido_hasta IS NULL;

-- and, on the declaration side, one preferred per grain per vista:
CREATE UNIQUE INDEX ux_pref_grano ON ( /* materialized helper */
  vista_id, medida_id, ciclo_id, unidad_id, periodo_id )
  WHERE es_preferida AND valido_hasta IS NULL;
```

Note `poblacion_id` is **not** in the second index. Choosing a population *is* the editorial
decision; permitting one preferred row per population is what re-creates the v1 bug.

---

## 7. The inconsistency model

### Four classes, not three

v1 classed "two documents named Anexo 2" as an Error and "PAET vs PIC-ET" as unclassified,
though they are the same phenomenon. v2 separates naming from arithmetic.

| Class | Definition | Disposition |
|---|---|---|
| **ERROR** | Cannot hold under any reading — arithmetic or transcription fails | one preferred, other `descartada` with motivo |
| **DIVERGENCIA** | Different populations, scopes or grains. Both true | no winner; parameterised by `poblacion_id` per `vista` |
| **COLISIÓN** | Same name, different referents | resolved by surrogate key + alias table |
| **VACÍO** | Nothing recorded | encoded per §7.2; never zero |

### 7.1 Register — 38 items

**Errors — arithmetic or transcription fails (17)**

| # | Item | Note |
|---|---|---|
| E1 | **Anexo 2 col N $68.5 mM vs $9.56 mM** | *v1 had this as Divergence.* Column N reconciles to no resolution; Bogotá N = P exactly; Palmira's "Indexación" holds the un-indexed 2023 figure. **impacto ALTO** |
| E2 | Informe Cualitativo: Res. 019862 = $2 313 166 700 | scan says **$2 738 054 656** |
| E3 | Informe Cualitativo: Res. 016468 = $46 115 857 101 | scan says UNAL total **$55 677 365 786**; matches neither component |
| E4 | Acuerdo 024/2025 calls Res. 18433 *inversión* | scan places UNAL under **FUNCIONAMIENTO** |
| E5 | "Res. 08596 de 2023" | is **Res. 8596 del 27 may 2024**; *v1 wrongly listed this as a gap* |
| E6 | −1 168 shortfall | Tabla 5 nets **−689**; 1 168 discards the two positive periods |
| E7 | Informe MEN §6 column sums 1 180, prints 1 120 | consistent 60-unit gap across three columns |
| E8 | Headline 2 284 vs table 2 257 | 1 043 + 94 + 1 120 |
| E9 | "PIC 2024 → 1 241 matriculados" | 94 + 1 120 = 1 214 |
| E10 | Acuerdo 016/2023 total 81 480 millones | components sum to **81 140** |
| E11 | Admin posts 50 claimed | Acuerdo 004/2025 creates 28; all acuerdos net 37 |
| E12 | Matriz figures for 016202 and 018970 | each **1 peso** off |
| E13 | Anexo 2 `C3 = '#REF!'` | the SNIES code identifying the institution is a broken reference |
| E14 | Anexo 2 col H = `Ampliación_Territorial` ×9 | Anexo 1 T9 spends the same money on *Docentes* and *Bienestar* |
| E15 | Anexo 2 filename says 2023–24 | sheet and columns are 2025 |
| E16 | Oficio `N.1.002.04-XXX-2025` | unfilled placeholder, 2025 suffix, 2026 date |
| E17 | Res. 018433 is the only resolution naming "PIC" | tracing money to the programme rests on one document |

**Divergences — both true, different scope (8)**

| # | Item | Carried by |
|---|---|---|
| D1 | Enrolment 1 161 vs 1 043 | `poblacion.incluye_la_paz` + `declaracion_alcance` |
| D2 | **Commitment 1 818 vs 1 836** | *v1 had this as Error.* 1 836 = 1 818 + La Paz 18 |
| D3 | 2026-1: 1 189 (Anexo 1) vs 1 120 / 1 180 (MEN §6) | three-way; interacts with E7 |
| D4 | ETC 191.5 headlined vs 394.5 created | `es_agregado_de` |
| D5 | FCV reported at two grains | `unidad_rollup` + validity range |
| D6 | 419 rezago seats | `compromiso.es_rezago` |
| D7 | admitidos vs matriculados | `criterio_cumplimiento`, not a data conflict |
| D8 | Anexo 2 col N/O/P internally duplicated | see E1; the sub-columns diverge from their headers |

**Collisions — same name, different referent (5)**

| # | Item |
|---|---|
| C1 | Two documents called **"Anexo 2"** — UNAL's spreadsheet, MEN's template |
| C2 | **"Sede Arauca"** (Anexo 2) = Sede Orinoquía |
| C3 | **PAET** (route, PIC-CO) vs **PIC-ET** (programme) |
| C4 | **"Sedes de Frontera"** — Res. 016202 names *five*, incl. "Insular"; all else says four SPN |
| C5 | `medida` "matriculados" — primera vs global vs efectiva vs SNIES primer curso |

**Gaps — nothing recorded (8)**

| # | Item |
|---|---|
| V1 | Acuerdo 011/2025 (creates PTIUN) absent |
| V2 | La Paz has no funding rows |
| V3 | Anexo 2 cols C, J, K, U, V blank in all 9 rows — *v1 listed only sub-línea* |
| V4 | Quartile band `(0.586,0.649]` never appears |
| V5 | Three funding-source columns empty |
| V6 | Stages E03, E04, E06–E08 undocumented |
| V7 | Two rubro generations, no bridge — **plus a third** unbridged vocabulary (`Área del Conocimiento`, 8 legacy vs 11 ISCED) |
| V8 | Anexo 1 T14 never says which PIC-ET line belongs to which vigencia |

**Anomalies worth recording but not classifying (1)**

- PIC 2025 (T10) and PIC 2026 (T12) commitment tables are **byte-identical** distributions.

### 7.2 Absence has four meanings

| Situation | Encode as | Example |
|---|---|---|
| Unknown / not recorded | `NULL` in a **measure**, never a grain | sub-línea |
| Not applicable by design | row absent + `programa_medida_permitida` | PIC-ET has no cupos |
| Recorded and genuinely zero | `0` | Amazonía regular admissions, three periods |
| Dimension member with no facts | dimension row, no fact rows | quartile `(0.586,0.649]` |
| Source document absent | `documento.estado='CITADO'` | Acuerdo 011/2025 |

The third and fourth remain the dangerous pair, and a `LEFT JOIN` still renders both as `0`.
Views must expose `observado` so a chart can style "sin observaciones" distinctly from zero.

---

## 8. Invariants

Every one below is enforceable by the database or by a load-time test. v1's R9 was neither
and has been demoted to §9.

| # | Invariant | Mechanism |
|---|---|---|
| **I1** | One preferred declaration per `(vista, medida, ciclo, unidad, periodo)` | unique partial index; **no nullable columns in the key** |
| **I2** | No aggregate crosses a rollup boundary | `unidad_rollup` with `distancia > 0`; never `WHERE sede_id = :x` |
| **I3** | Stocks never sum across `periodo` | `medida.aditiva_tiempo = FALSE` enforced in views |
| **I4** | Measures never sum across units of measure | `medida.unidad_medida` |
| **I5** | Every fact row cites a document and a location | `documento_id`, `ubicacion` `NOT NULL` on all fact tables |
| **I6** | Held documents have a path and a soporte; cited ones have neither | paired CHECK |
| **I7** | Commitment totals exclude rezago | `SUM(cupos) WHERE NOT es_rezago` |
| **I8** | Carry-forward is acyclic | `ciclo_origen.anio ≤ ciclo_destino.anio` **and** `origen <> destino` — v1's strict `<` forbade a legitimate CO 2026 → ET 2026 transfer |
| **I9** | No load creates a dimension member | FK violations fail the load |
| **I10** | Cross-generation rubro queries return nothing without a mapping | `rubro_mapping` holds only real mappings |
| **I11** | Every load is idempotent | natural-key `UNIQUE` on every fact table |
| **I12** | No hierarchy cycles | closure-table trigger rejects `A→B→A` on `unidad_academica` and `rubro` |
| **I13** | `rubro.padre_id` shares its child's `generacion` | CHECK |
| **I14** | A measure invalid for its programme fails at load | `programa_medida_permitida` |
| **I15** | An aggregate's components, where declared, sum to it | scheduled test over `es_agregado_de`; a failure is a finding, not an error |

---

## 9. Load discipline

| # | Rule |
|---|---|
| **L1** | **Append only.** No `UPDATE` against `declaracion`. Disposition changes are new rows in `declaracion_disposicion` — resolving v1's §6.2 / §9.R1 contradiction. |
| **L2** | **Idempotent.** Re-running a loader produces zero new rows. Enforced by natural key, not by convention. |
| **L3** | **Retain the literal.** `valor_origen` before parsing. |
| **L4** | **Locate everything.** `ubicacion` to table, cell or paragraph. |
| **L5** | **Resolve aliases at load, never at source.** |
| **L6** | **Every categorical resolves to a dimension member or the load fails.** A typo in `medida_id` must not silently remove a figure from every view. |
| **L7** | **A figure quoted from a scan is a declaration against the quoting report, never against the scan.** Vindicated: of six report-quoted resolution amounts, three are wrong and two are off by a peso. |

### R9 restated as a process control

"Nothing but a view reads the declaration store" is not enforceable in a self-serve BI tool,
where a dataset owner reaches everything the connection reaches. It is a **process**:

1. DB grants on views only; the BI role cannot see base tables
2. A named owner who adds views on request within days — **the SLA is the actual control**
3. A scheduled test asserting every published chart's dataset is on the approved list

Without (2), the first unmet need becomes an untraceable spreadsheet circulating by email.

---

## 10. Blocking prerequisites

v1 listed these as deferred decisions. Three are now **blocking** — the evidence audit
showed the corpus cannot support the affected charts until they are resolved.

| Prerequisite | Status | Blocks |
|---|---|---|
| **Transcribe the five MEN resolutions** | ✅ **done** — and it found E1–E5, E12 | was blocking the entire financial layer |
| **Resolve Anexo 2 column N** | 🔴 **blocking** | every money chart. Currently untraceable; treat $9 561 136 948 as preferred on primary support |
| **Decide FCV's grain and its validity range** | 🔴 **blocking** | all sede totals and subtotals |
| **Curate `rubro_mapping`** | 🔴 **blocking** | money-by-rubro across cycles — the first chart a ministry will ask for |
| Choose canonical `poblacion` per vista | 🟡 | every seat chart; two vistas may legitimately differ |
| Define the sourcing-tile denominator | 🟡 | v1 promised a percentage with no defined denominator |
| Scope: UNAL alone or 12 IES | 🟡 | note the "−1 168 MEN global" figure is a **national** number sitting beside UNAL figures with no discriminator — an active bug, not a deferred decision |

### Presentation notes carried from the serving review

- **Show the funnel, not a toggle.** `comprometidos 1 818 → ofertados 1 848 → admitidos
  1 809 → matriculados 1 161`, drop-offs annotated. This presents UNAL's position and MEN's
  simultaneously. A toggle presents them as competing truths and reads as evasion.
- Where a selector is genuinely needed, label it by **scope** — "8 proyectos aprobados
  (1 161)" vs "consolidado incl. La Paz (1 043)" — never by source.
- **No column named `año` in any view.** Two named axes: *Ciclo PIC* (labelled with its
  execution window) and *Periodo académico*. Default: all cycles, **no** period filter.
- **Never let the tool compute a grand total.** Supply totals as authored measures filtered
  to one rollup level.
- Persist an **"N declarations excluded by current filters"** counter on every page.

---

## Appendix — review provenance

This revision incorporates four independent adversarial reviews of v1, run in parallel with
no knowledge of each other.

| Lens | Principal contribution |
|---|---|
| Domain / policy | The missing `vigencia` and recurrent-base category error; project-not-cycle grain; per-vista preference; `criterio_cumplimiento`; stock-vs-flow; missing entities |
| Data modelling | The NULL ≠ NULL uniqueness failure; `nivel_reportado` defeat via `sede_id = unidad_id`; absent idempotency keys; six self-contradictions; the genre-not-grain critique |
| BI serving | The view returning two rows through the sanctioned path; nullable-grain filter disappearance; the funnel-over-toggle presentation; money-by-rubro unshippable |
| Evidence audit | Transcribed the five scans; primary-sourced $9 561 136 948; showed column N reconciles to nothing; found E2–E4, E6–E10, E12–E14, C4, V7 |

**Cleared under attack by two or more reviews:** `documento.estado`/`soporte` with paired
CHECKs · document-scoped `unidad_alias` · `cuartil_prioridad.observado` ·
`cantidad NUMERIC` for fractional ETC · `valor_origen` literal retention · long-format
funding · load rule L7.

---

*Derived from the 23-file PIC corpus, 2023–2026, plus first transcription of the five
scanned MEN resolutions. Companion to the PIC Corpus Taxonomy.*
