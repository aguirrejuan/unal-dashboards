"""The PIC schema, declared once.

Implements `docs/pic-data-model-v2.md`. SQLAlchemy Core only — no ORM; see
`docs/pic-etl-design.md` for why. Every categorical is a table with a foreign
key (P4), every grain column is NOT NULL with a sentinel member standing in for
"not applicable" (P5), and every fact table carries `documento_id` + `ubicacion`
(P2) and a natural key (P7/I11).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    and_,
)

from pic_etl.schema.types import Exacta

metadata = MetaData()

#: BIGSERIAL in Postgres, INTEGER PRIMARY KEY in SQLite.
_Serial = BigInteger().with_variant(Integer, "sqlite")


def vocabulario(nombre: str, *extra: Column) -> Table:
    """A controlled vocabulary table: id plus label.

    P4 — no free-text enum ever appears in a key or a filter, so a typo fails
    the load (L6) instead of quietly removing a figure from every view.
    """
    return Table(
        nombre,
        metadata,
        Column(f"{nombre}_id", Text, primary_key=True),
        Column("nombre", Text, nullable=False),
        *extra,
    )


# ---------------------------------------------------------------- vocabularies

tipo_unidad = vocabulario("tipo_unidad")               # UNIVERSIDAD|SEDE|FACULTAD|...
grupo_sede = vocabulario("grupo_sede")                 # SPN|ANDINA|OTRA
estado_ciclo = vocabulario("estado_ciclo")
definicion_medida = vocabulario("definicion_medida")   # PRIMERA_MATRICULA|...
tipo_documento = vocabulario("tipo_documento")
emisor = vocabulario("emisor")
estado_documento = vocabulario("estado_documento")     # EN_CORPUS|CITADO|NUNCA_PRODUCIDO
soporte = vocabulario("soporte")                       # TEXTO|ESCANEO|TRANSCRITO
direccion_radicado = vocabulario("direccion_radicado")
generacion_rubro = vocabulario("generacion_rubro")     # PRE_2025|V2025
confianza_mapeo = vocabulario("confianza_mapeo")       # EXACTA|PARCIAL
tipo_flujo = vocabulario("tipo_flujo")
momento_presupuestal = vocabulario("momento_presupuestal")
estado_etapa = vocabulario("estado_etapa")
tipo_cargo = vocabulario("tipo_cargo")
tipo_declaracion = vocabulario("tipo_declaracion")     # TRANSCRIPCION|AGREGADO
vista = vocabulario("vista")                           # UNAL|MEN|AUDITOR

etapa = vocabulario(
    "etapa",
    Column("orden", Integer, nullable=False),
    Column("actor", Text),
)

# ------------------------------------------------------------------- geography

departamento = vocabulario("departamento")

municipio = Table(
    "municipio",
    metadata,
    Column("municipio_id", Text, primary_key=True),
    Column("nombre", Text, nullable=False),
    Column("departamento_id", Text, ForeignKey("departamento.departamento_id"), nullable=False),
)

# -------------------------------------------------------------- academic units

unidad_academica = Table(
    "unidad_academica",
    metadata,
    Column("unidad_id", Text, primary_key=True),
    Column("nombre", Text, nullable=False),
    Column("tipo", Text, ForeignKey("tipo_unidad.tipo_unidad_id"), nullable=False),
    Column("padre_id", Text, ForeignKey("unidad_academica.unidad_id")),
    Column("sede_id", Text, nullable=False),
    Column("grupo", Text, ForeignKey("grupo_sede.grupo_sede_id")),
    Column("departamento_id", Text, ForeignKey("departamento.departamento_id")),
    Column("municipio_id", Text, ForeignKey("municipio.municipio_id")),
    Column("valido_desde", Date, nullable=False),
    # FCV is a type-2 change: part of Medellín in 2023, an allocation unit in
    # 2025. Resolving it as a single `tipo` would rewrite the 2023 grain.
    Column("valido_hasta", Date),
    # §3.2's `FOREIGN KEY (sede_id, 'SEDE')` is not legal SQL — a literal cannot
    # appear in a foreign-key column list. SQLite accepts that DDL and then
    # rejects every insert. The constant lives in a generated column instead.
    #
    # It is not the bare constant 'SEDE' either: §3.1's own sentinel row
    # ('UNAL_TOTAL', tipo UNIVERSIDAD, sede_id itself) could never satisfy that,
    # so the spec's two sections contradict each other. The column encodes what
    # kind of row this one's sede must be — a sede for everything real, itself
    # for the university-level sentinel.
    Column(
        "k_sede",
        Text,
        Computed("CASE WHEN tipo = 'UNIVERSIDAD' THEN 'UNIVERSIDAD' ELSE 'SEDE' END",
                 persisted=False),
    ),
    UniqueConstraint("unidad_id", "tipo", name="uq_unidad_tipo"),
    ForeignKeyConstraint(
        ["sede_id", "k_sede"],
        ["unidad_academica.unidad_id", "unidad_academica.tipo"],
        name="fk_sede_es_una_sede",
    ),
    # Roots are their own sede. Sedes are roots; UNAL_TOTAL is a sentinel beside
    # the hierarchy, not above it — university figures are declared, never summed
    # up from sedes.
    CheckConstraint(
        "(padre_id IS NULL) = (sede_id = unidad_id)",
        name="ck_raiz_es_su_propia_sede",
    ),
)

unidad_rollup = Table(
    "unidad_rollup",
    metadata,
    Column("ancestro_id", Text, ForeignKey("unidad_academica.unidad_id"), primary_key=True),
    Column("descendiente_id", Text, ForeignKey("unidad_academica.unidad_id"), primary_key=True),
    Column("distancia", Integer, nullable=False),
    CheckConstraint("distancia >= 0", name="ck_distancia_no_negativa"),
)

unidad_alias = Table(
    "unidad_alias",
    metadata,
    # 'GLOBAL', or a documento_id when a spelling means something only in one
    # document — Anexo 2's "Sede Arauca" is Sede Orinoquía (C2).
    Column("ambito", Text, primary_key=True),
    # Every spelling is kept, so the table is an audit record of how the corpus
    # writes each unit, not merely a lookup.
    Column("literal", Text, primary_key=True),
    # Accent- and case-folded. Resolution tries the exact literal first, then
    # this; a fold that reaches two different units is a genuine conflict and
    # fails the load rather than picking one.
    Column("literal_norm", Text, nullable=False),
    Column("unidad_id", Text, ForeignKey("unidad_academica.unidad_id"), nullable=False),
)

Index("ix_alias_norm", unidad_alias.c.ambito, unidad_alias.c.literal_norm)

# ----------------------------------------------------- programme, cycle, period

programa = Table(
    "programa",
    metadata,
    Column("programa_id", Text, primary_key=True),      # PIC_CO | PIC_ET
    Column("nombre", Text, nullable=False),
    Column("instrumento", Text),
    Column("contraparte", Text),
)

periodo = Table(
    "periodo",
    metadata,
    Column("periodo_id", Text, primary_key=True),        # '2024-1' … plus 'NA'
    Column("anio", Integer),
    Column("semestre", Integer),
    Column("orden", Integer, nullable=False),
    Column("es_proyectado", Boolean, nullable=False, default=False),
)

ciclo = Table(
    "ciclo",
    metadata,
    Column("ciclo_id", Text, primary_key=True),          # 'PIC_CO_2023' … plus 'TODOS'
    Column("programa_id", Text, ForeignKey("programa.programa_id"), nullable=False),
    Column("anio_formulacion", Integer, nullable=False),
    Column("periodo_ejec_desde", Text, ForeignKey("periodo.periodo_id"), nullable=False),
    Column("periodo_ejec_hasta", Text, ForeignKey("periodo.periodo_id"), nullable=False),
    Column("estado", Text, ForeignKey("estado_ciclo.estado_ciclo_id"), nullable=False),
)

# --------------------------------------------------------- measures, population

medida = Table(
    "medida",
    metadata,
    Column("medida_id", Text, primary_key=True),
    Column("nombre", Text, nullable=False),
    Column("unidad_medida", Text, nullable=False),       # PERSONAS|CUPOS|COP|ETC|CARGOS
    Column("tipo_agregacion", Text, nullable=False),     # STOCK|FLUJO
    Column("aditiva_unidad", Boolean, nullable=False),
    Column("aditiva_tiempo", Boolean, nullable=False),
    CheckConstraint("tipo_agregacion IN ('STOCK','FLUJO')", name="ck_tipo_agregacion"),
    # A stock is never summable across time: a student enrolled in 2024-1 is
    # still enrolled in 2024-2, so summing periods doubles the cohort.
    CheckConstraint(
        "tipo_agregacion <> 'STOCK' OR aditiva_tiempo = 0",
        name="ck_stock_no_suma_en_tiempo",
    ),
)

programa_medida_permitida = Table(
    "programa_medida_permitida",
    metadata,
    Column("programa_id", Text, ForeignKey("programa.programa_id"), primary_key=True),
    Column("medida_id", Text, ForeignKey("medida.medida_id"), primary_key=True),
)

poblacion = Table(
    "poblacion",
    metadata,
    Column("poblacion_id", Text, primary_key=True),
    Column("etiqueta_corta", Text, nullable=False),
    Column("definicion", Text, ForeignKey("definicion_medida.definicion_medida_id"), nullable=False),
    Column("incluye_la_paz", Boolean, nullable=False),
    Column("alcance_proyecto", Text),
    Column("fecha_corte", Date),
    Column("orden", Integer, nullable=False),
)

cuartil_prioridad = Table(
    "cuartil_prioridad",
    metadata,
    Column("cuartil_id", Text, primary_key=True),
    Column("notacion", Text, nullable=False),
    Column("limite_inf", Exacta, nullable=False),
    Column("limite_sup", Exacta, nullable=False),
    # FALSE for (0.586,0.649], which never appears — a dimension member with no
    # facts, which a LEFT JOIN would otherwise render as 0 (§7.2).
    Column("observado", Boolean, nullable=False),
)

# -------------------------------------------------------------------- documents

documento = Table(
    "documento",
    metadata,
    Column("documento_id", Text, primary_key=True),
    Column("tipo", Text, ForeignKey("tipo_documento.tipo_documento_id"), nullable=False),
    Column("emisor", Text, ForeignKey("emisor.emisor_id"), nullable=False),
    Column("numero", Text),
    Column("fecha", Date),
    Column("titulo", Text),
    Column("estado", Text, ForeignKey("estado_documento.estado_documento_id"), nullable=False),
    Column("soporte", Text, ForeignKey("soporte.soporte_id")),
    Column("ruta_archivo", Text),
    Column("sha256", Text),
    # I6: held documents have a path and a soporte; cited ones have neither.
    CheckConstraint(
        "estado <> 'EN_CORPUS' OR (ruta_archivo IS NOT NULL AND soporte IS NOT NULL)",
        name="ck_en_corpus_tiene_ruta",
    ),
    CheckConstraint(
        "estado = 'EN_CORPUS' OR ruta_archivo IS NULL",
        name="ck_citado_no_tiene_ruta",
    ),
)

documento_cita = Table(
    "documento_cita",
    metadata,
    Column("citante_id", Text, ForeignKey("documento.documento_id"), primary_key=True),
    Column("citado_id", Text, ForeignKey("documento.documento_id"), primary_key=True),
    Column("ubicacion", Text),
    CheckConstraint("citante_id <> citado_id", name="ck_no_se_cita_a_si_mismo"),
)

documento_ciclo = Table(
    "documento_ciclo",
    metadata,
    Column("documento_id", Text, ForeignKey("documento.documento_id"), primary_key=True),
    Column("ciclo_id", Text, ForeignKey("ciclo.ciclo_id"), primary_key=True),
)

radicado = Table(
    "radicado",
    metadata,
    Column("radicado_id", Text, primary_key=True),
    Column("direccion", Text, ForeignKey("direccion_radicado.direccion_radicado_id"), nullable=False),
    Column("fecha", Date),
)

radicado_documento = Table(
    "radicado_documento",
    metadata,
    Column("radicado_id", Text, ForeignKey("radicado.radicado_id"), primary_key=True),
    Column("documento_id", Text, ForeignKey("documento.documento_id"), primary_key=True),
)

# ------------------------------------------------ rubros, routes, funding sources

rubro = Table(
    "rubro",
    metadata,
    Column("rubro_id", Text, primary_key=True),
    Column("generacion", Text, ForeignKey("generacion_rubro.generacion_rubro_id"), nullable=False),
    Column("nivel", Text, nullable=False),               # LINEA | SUBLINEA
    Column("padre_id", Text, ForeignKey("rubro.rubro_id")),
    Column("nombre", Text, nullable=False),
    # Was `confianza='SIN_MAPEO'` as a bridge row, which mis-buckets on a naive
    # JOIN unless every query remembers to exclude it.
    Column("mapeable", Boolean, nullable=False, default=True),
    CheckConstraint("nivel IN ('LINEA','SUBLINEA')", name="ck_nivel_rubro"),
    CheckConstraint("nivel <> 'LINEA' OR padre_id IS NULL", name="ck_linea_sin_padre"),
)

rubro_mapping = Table(
    "rubro_mapping",
    metadata,
    Column("rubro_origen", Text, ForeignKey("rubro.rubro_id"), primary_key=True),
    Column("rubro_destino", Text, ForeignKey("rubro.rubro_id"), primary_key=True),
    Column("confianza", Text, ForeignKey("confianza_mapeo.confianza_mapeo_id"), nullable=False),
)

via_admision = Table(
    "via_admision",
    metadata,
    Column("via_id", Text, primary_key=True),            # REGULAR|PEAMA|PAET|PTIUN
    Column("nombre", Text, nullable=False),
    Column("programa_id", Text, ForeignKey("programa.programa_id"), nullable=False),
    Column("acuerdo_id", Text, ForeignKey("documento.documento_id")),
)

fuente_financiacion = Table(
    "fuente_financiacion",
    metadata,
    Column("fuente_id", Text, primary_key=True),
    Column("nombre", Text, nullable=False),
    Column("tipo_flujo", Text, ForeignKey("tipo_flujo.tipo_flujo_id"), nullable=False),
    Column("columna_xlsx", Text),
)

# ------------------------------------------------------------ structural facts
#
# Every table below carries `documento_id` and `ubicacion` (P2) and a natural
# key (I11). v1 had provenance on the assertion table alone, which killed
# drill-through on exactly the numbers that reach a dashboard.

proyecto = Table(
    "proyecto",
    metadata,
    Column("proyecto_id", Text, primary_key=True),
    Column("ciclo_id", Text, ForeignKey("ciclo.ciclo_id"), nullable=False),
    Column("unidad_id", Text, ForeignKey("unidad_academica.unidad_id"), nullable=False),
    Column("numero", Integer, nullable=False),
    Column("nombre", Text, nullable=False),
    Column("linea_id", Text, ForeignKey("rubro.rubro_id")),
    Column("sublinea_id", Text, ForeignKey("rubro.rubro_id")),
    Column("documento_id", Text, ForeignKey("documento.documento_id"), nullable=False),
    Column("ubicacion", Text, nullable=False),
    UniqueConstraint("ciclo_id", "numero", name="uq_proyecto_ciclo_numero"),
)

proyecto_etapa = Table(
    "proyecto_etapa",
    metadata,
    Column("proyecto_id", Text, ForeignKey("proyecto.proyecto_id"), primary_key=True),
    Column("etapa_id", Text, ForeignKey("etapa.etapa_id"), primary_key=True),
    Column("ocurrencia", Integer, primary_key=True, default=1),
    Column("fecha", Date),
    Column("estado", Text, ForeignKey("estado_etapa.estado_etapa_id"), nullable=False),
    Column("documento_id", Text, ForeignKey("documento.documento_id")),
    Column("radicado_id", Text, ForeignKey("radicado.radicado_id")),
)

compromiso = Table(
    "compromiso",
    metadata,
    Column("compromiso_id", Text, primary_key=True),
    Column("proyecto_id", Text, ForeignKey("proyecto.proyecto_id"), nullable=False),
    Column("unidad_id", Text, ForeignKey("unidad_academica.unidad_id"), nullable=False),
    Column("cupos", Integer, nullable=False),
    Column("es_rezago", Boolean, nullable=False, default=False),
    Column("ciclo_origen_id", Text, ForeignKey("ciclo.ciclo_id")),
    Column("documento_id", Text, ForeignKey("documento.documento_id"), nullable=False),
    Column("ubicacion", Text, nullable=False),
    CheckConstraint(
        "es_rezago = 0 OR ciclo_origen_id IS NOT NULL",
        name="ck_rezago_tiene_origen",
    ),
    UniqueConstraint(
        "proyecto_id", "unidad_id", "es_rezago", "ciclo_origen_id",
        name="uq_compromiso_natural",
    ),
)

cargo_creado = Table(
    "cargo_creado",
    metadata,
    Column("documento_id", Text, ForeignKey("documento.documento_id"), primary_key=True),
    Column("unidad_id", Text, ForeignKey("unidad_academica.unidad_id"), primary_key=True),
    Column("tipo", Text, ForeignKey("tipo_cargo.tipo_cargo_id"), primary_key=True),
    Column("cantidad", Exacta, nullable=False),          # Palmira: 31,5 ETC
    Column("cantidad_origen", Text, nullable=False),
    Column("costo_total", Exacta),
    Column("ubicacion", Text, nullable=False),
)

cargo_provisto = Table(
    "cargo_provisto",
    metadata,
    Column("unidad_id", Text, ForeignKey("unidad_academica.unidad_id"), primary_key=True),
    Column("tipo", Text, ForeignKey("tipo_cargo.tipo_cargo_id"), primary_key=True),
    Column("periodo_id", Text, ForeignKey("periodo.periodo_id"), primary_key=True),
    Column("cantidad", Exacta, nullable=False),
    Column("documento_id", Text, ForeignKey("documento.documento_id"), nullable=False),
    Column("ubicacion", Text, nullable=False),
)

cobertura_territorial = Table(
    "cobertura_territorial",
    metadata,
    Column("ciclo_id", Text, ForeignKey("ciclo.ciclo_id"), primary_key=True),
    Column("unidad_id", Text, ForeignKey("unidad_academica.unidad_id"), primary_key=True),
    Column("periodo_id", Text, ForeignKey("periodo.periodo_id"), primary_key=True),
    Column("cuartil_id", Text, ForeignKey("cuartil_prioridad.cuartil_id"), primary_key=True),
    Column("via_id", Text, ForeignKey("via_admision.via_id"), primary_key=True),
    Column("estudiantes", Integer, nullable=False),
    Column("documento_id", Text, ForeignKey("documento.documento_id"), nullable=False),
    Column("ubicacion", Text, nullable=False),
)

arrastre = Table(
    "arrastre",
    metadata,
    Column("ciclo_origen_id", Text, ForeignKey("ciclo.ciclo_id"), primary_key=True),
    Column("ciclo_destino_id", Text, ForeignKey("ciclo.ciclo_id"), primary_key=True),
    Column("vigencia", Integer, primary_key=True),
    Column("monto_saldo", Exacta),
    Column("documento_id", Text, ForeignKey("documento.documento_id"), nullable=False),
    Column("ubicacion", Text, nullable=False),
    # I8: carry-forward is acyclic. v1's strict `<` forbade a legitimate
    # CO 2026 → ET 2026 transfer.
    CheckConstraint("ciclo_origen_id <> ciclo_destino_id", name="ck_arrastre_no_reflexivo"),
)

asignacion = Table(
    "asignacion",
    metadata,
    Column("asignacion_id", Text, primary_key=True),
    Column("documento_id", Text, ForeignKey("documento.documento_id"), nullable=False),
    Column("ubicacion", Text, nullable=False),
    Column("unidad_id", Text, ForeignKey("unidad_academica.unidad_id"), nullable=False),
    Column("ciclo_id", Text, ForeignKey("ciclo.ciclo_id"), nullable=False),
    # Fiscal year, NOT the cycle year. Art. 124 money is added to the recurrent
    # operating base: once granted it persists and is indexed forward. Without
    # this, "how much PIC money does UNAL have in 2026?" is unanswerable.
    Column("vigencia", Integer, nullable=False),
    Column("fuente_id", Text, ForeignKey("fuente_financiacion.fuente_id"), nullable=False),
    Column("tipo_flujo", Text, ForeignKey("tipo_flujo.tipo_flujo_id"), nullable=False),
    # Assignment is not disbursement; the operational grievance is usually the
    # gap between ASIGNADO and GIRADO.
    Column("momento", Text, ForeignKey("momento_presupuestal.momento_presupuestal_id"), nullable=False),
    Column("recurso", Text),                             # 'REC 10' | 'REC 11'
    Column("monto", Exacta, nullable=False),
    # L3: retain the literal. v2 §5 gives money no companion to `valor_origen`,
    # so a figure could not be checked against its source — which is exactly
    # what the re-transcription test needs.
    Column("monto_origen", Text, nullable=False),
    UniqueConstraint(
        "documento_id", "ubicacion", "unidad_id", "vigencia", "fuente_id", "momento",
        name="uq_asignacion_natural",
    ),
)

presupuesto_rubro = Table(
    "presupuesto_rubro",
    metadata,
    # Money against a spending line. This cannot ride on `declaracion`: that
    # grain has no rubro, so four different sublíneas would collapse onto one
    # row and read as four competing claims about the same number.
    Column("presupuesto_id", Text, primary_key=True),
    Column("ciclo_id", Text, ForeignKey("ciclo.ciclo_id"), nullable=False),
    Column("rubro_id", Text, ForeignKey("rubro.rubro_id"), nullable=False),
    Column("unidad_id", Text, ForeignKey("unidad_academica.unidad_id"), nullable=False),
    # v1 keyed this on the free-text concepto. The literal is kept beside a
    # surrogate key instead.
    Column("concepto", Text),
    Column("cantidad", Exacta),          # NULL where the source writes 'Bolsa'
    Column("monto", Exacta, nullable=False),
    Column("monto_origen", Text, nullable=False),
    Column("documento_id", Text, ForeignKey("documento.documento_id"), nullable=False),
    Column("ubicacion", Text, nullable=False),
    UniqueConstraint("documento_id", "ubicacion", name="uq_presupuesto_natural"),
)

# ------------------------------------------------------------------ declarations

declaracion = Table(
    "declaracion",
    metadata,
    Column("declaracion_id", _Serial, primary_key=True, autoincrement=True),
    Column("tipo_declaracion", Text, ForeignKey("tipo_declaracion.tipo_declaracion_id"), nullable=False),
    Column("medida_id", Text, ForeignKey("medida.medida_id"), nullable=False),
    # Grain: all NOT NULL. Sentinels stand in where a dimension does not apply,
    # which is what makes the uniqueness index able to exist at all (NULL ≠ NULL)
    # and stops a sede filter silently dropping university-level rows.
    Column("ciclo_id", Text, ForeignKey("ciclo.ciclo_id"), nullable=False),
    Column("unidad_id", Text, ForeignKey("unidad_academica.unidad_id"), nullable=False),
    Column("periodo_id", Text, ForeignKey("periodo.periodo_id"), nullable=False),
    Column("poblacion_id", Text, ForeignKey("poblacion.poblacion_id"), nullable=False),
    Column("valor", Exacta, nullable=False),
    Column("documento_id", Text, ForeignKey("documento.documento_id"), nullable=False),
    Column("ubicacion", Text, nullable=False),
    Column("valor_origen", Text, nullable=False),        # '31,5' | 'Bolsa' | 'Indefinido'
    Column("fecha_asercion", Date, nullable=False),
    UniqueConstraint(
        "documento_id", "ubicacion", "medida_id",
        "ciclo_id", "unidad_id", "periodo_id", "poblacion_id",
        name="uq_declaracion_natural",
    ),
)

es_agregado_de = Table(
    "es_agregado_de",
    metadata,
    Column("agregado_id", _Serial, ForeignKey("declaracion.declaracion_id"), primary_key=True),
    Column("componente_id", _Serial, ForeignKey("declaracion.declaracion_id"), primary_key=True),
    CheckConstraint("agregado_id <> componente_id", name="ck_agregado_no_reflexivo"),
)

declaracion_alcance = Table(
    "declaracion_alcance",
    metadata,
    Column("declaracion_id", _Serial, ForeignKey("declaracion.declaracion_id"), primary_key=True),
    Column("proyecto_id", Text, ForeignKey("proyecto.proyecto_id"), primary_key=True),
)

declaracion_disposicion = Table(
    "declaracion_disposicion",
    metadata,
    Column("disposicion_id", _Serial, primary_key=True, autoincrement=True),
    Column("vista_id", Text, ForeignKey("vista.vista_id"), nullable=False),
    Column("declaracion_id", _Serial, ForeignKey("declaracion.declaracion_id"), nullable=False),
    Column("es_preferida", Boolean, nullable=False),
    Column("descartada", Boolean, nullable=False, default=False),
    Column("motivo", Text),
    Column("valido_desde", Date, nullable=False),
    Column("valido_hasta", Date),
    CheckConstraint("NOT (es_preferida AND descartada)", name="ck_no_preferida_y_descartada"),
    CheckConstraint("descartada = 0 OR motivo IS NOT NULL", name="ck_descarte_motivado"),
)

# I1's second half. A partial unique index cannot span two tables, so the
# currently-preferred grain is materialised here by the loader — v2 §6 calls for
# exactly this helper. `poblacion_id` is deliberately absent: choosing a
# population *is* the editorial decision, and allowing one preferred row per
# population is what let v1 return both 1 161 and 1 043 and sum them to 2 204.
disposicion_grano = Table(
    "disposicion_grano",
    metadata,
    Column("vista_id", Text, ForeignKey("vista.vista_id"), primary_key=True),
    Column("medida_id", Text, ForeignKey("medida.medida_id"), primary_key=True),
    Column("ciclo_id", Text, ForeignKey("ciclo.ciclo_id"), primary_key=True),
    Column("unidad_id", Text, ForeignKey("unidad_academica.unidad_id"), primary_key=True),
    Column("periodo_id", Text, ForeignKey("periodo.periodo_id"), primary_key=True),
    Column("declaracion_id", _Serial, ForeignKey("declaracion.declaracion_id"), nullable=False),
)

criterio_cumplimiento = Table(
    "criterio_cumplimiento",
    metadata,
    Column("criterio_id", Text, primary_key=True),
    Column("numerador_medida", Text, ForeignKey("medida.medida_id"), nullable=False),
    Column("denominador_medida", Text, ForeignKey("medida.medida_id"), nullable=False),
    Column("sostenido_por", Text, ForeignKey("vista.vista_id"), nullable=False),
    Column("fundamento_documento_id", Text, ForeignKey("documento.documento_id")),
)

# --------------------------------------------------------------- the register

hallazgo = Table(
    "hallazgo",
    metadata,
    # §7.1 as rows rather than prose, so the register can be queried and charted.
    Column("hallazgo_id", Text, primary_key=True),
    Column("clase", Text, nullable=False),   # ERROR|DIVERGENCIA|COLISION|VACIO|ANOMALIA
    Column("titulo", Text, nullable=False),
    Column("detalle", Text),
    Column("impacto", Text, nullable=False),                  # ALTO|MEDIO|BAJO
    Column("documento_id", Text, ForeignKey("documento.documento_id")),
    Column("ubicacion", Text),
    # The honest column. VERIFICADO means the loaded data demonstrates it and
    # `verificacion` holds the query that proves it; the rest wait on documents
    # Phase 1 has not parsed, and saying so is the point.
    Column("estado", Text, nullable=False),
    Column("verificacion", Text),
    CheckConstraint(
        "clase IN ('ERROR','DIVERGENCIA','COLISION','VACIO','ANOMALIA')",
        name="ck_clase_hallazgo",
    ),
    CheckConstraint("impacto IN ('ALTO','MEDIO','BAJO')", name="ck_impacto_hallazgo"),
    # A verified finding must carry its proof; an unverified one must not claim one.
    CheckConstraint(
        "(estado = 'VERIFICADO') = (verificacion IS NOT NULL)",
        name="ck_verificado_trae_consulta",
    ),
)

# ------------------------------------------------------------- partial indexes
#
# Supported by SQLite since 3.8 and by Postgres; the WHERE clause is passed
# under a dialect-specific keyword, so both are given.

_preferida_vigente = and_(
    declaracion_disposicion.c.es_preferida,
    declaracion_disposicion.c.valido_hasta.is_(None),
)

Index(
    "ux_disp_preferida",
    declaracion_disposicion.c.vista_id,
    declaracion_disposicion.c.declaracion_id,
    unique=True,
    sqlite_where=_preferida_vigente,
    postgresql_where=_preferida_vigente,
)

Index("ix_declaracion_medida", declaracion.c.medida_id)
Index("ix_declaracion_unidad", declaracion.c.unidad_id)
Index("ix_rollup_ancestro", unidad_rollup.c.ancestro_id, unidad_rollup.c.distancia)
