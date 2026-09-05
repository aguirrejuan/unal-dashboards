"""Engine construction and the handful of things dialects disagree about."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text

from pic_etl.schema.tables import metadata


def crear_engine(destino: str | Path, *, recrear: bool = False) -> Engine:
    """Build an engine for `destino`, a path or a SQLAlchemy URL.

    `PRAGMA foreign_keys` defaults to **OFF** in SQLite, which would make I9
    ("no load creates a dimension member") a silent no-op — every FK typo would
    load happily and quietly detach a figure from its dimension. It is forced on
    for every connection here rather than left to callers to remember.
    """
    url = str(destino)
    if "://" not in url:
        ruta = Path(url)
        if recrear and ruta.exists():
            ruta.unlink()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+pysqlite:///{ruta}"

    engine = create_engine(url, future=True)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _forzar_fk(dbapi_connection, _record):  # noqa: ANN001
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def crear_esquema(engine: Engine) -> None:
    """Create every table, then the views."""
    metadata.create_all(engine)
    _crear_vistas(engine)


def fk_activas(engine: Engine) -> bool:
    """Whether the connection really enforces foreign keys — asserted by tests,
    because a silent OFF invalidates most of the invariant suite."""
    if engine.dialect.name != "sqlite":
        return True
    with engine.connect() as conn:
        return bool(conn.exec_driver_sql("PRAGMA foreign_keys").scalar())


# Views are the only surface the BI role is granted (§9). They are single-valued
# by construction: one row per (grain, vista).
#
# SQLite stores exact decimals as TEXT (see schema.types.Exacta), so views CAST
# for aggregation. That is a display concern; reconciliation runs in Python over
# Decimals, where the arithmetic is exact.
_VISTAS = [
    (
        "v_declaracion",
        """
        CREATE VIEW v_declaracion AS
        SELECT dg.vista_id,
               d.declaracion_id,
               d.medida_id,
               m.unidad_medida,
               m.tipo_agregacion,
               m.aditiva_tiempo,
               d.ciclo_id,
               c.programa_id,
               d.unidad_id,
               u.nombre        AS unidad,
               u.tipo          AS unidad_tipo,
               d.periodo_id,
               p.etiqueta_corta AS poblacion,
               p.incluye_la_paz,
               CAST(d.valor AS REAL) AS valor,
               d.valor_origen,
               d.documento_id,
               d.ubicacion,
               doc.estado      AS estado_fuente,
               doc.soporte
        FROM   disposicion_grano dg
        JOIN   declaracion  d   ON d.declaracion_id = dg.declaracion_id
        JOIN   medida       m   ON m.medida_id      = d.medida_id
        JOIN   ciclo        c   ON c.ciclo_id       = d.ciclo_id
        JOIN   unidad_academica u ON u.unidad_id    = d.unidad_id
        JOIN   periodo      pe  ON pe.periodo_id    = d.periodo_id
        JOIN   poblacion    p   ON p.poblacion_id   = d.poblacion_id
        JOIN   documento    doc ON doc.documento_id = d.documento_id
        """,
    ),
    (
        "v_matricula",
        """
        CREATE VIEW v_matricula AS
        SELECT * FROM v_declaracion WHERE medida_id = 'matriculados'
        """,
    ),
    (
        # I7: commitment totals exclude rezago.
        "v_compromiso",
        """
        CREATE VIEW v_compromiso AS
        SELECT pr.ciclo_id,
               co.unidad_id,
               u.nombre AS unidad,
               SUM(CASE WHEN co.es_rezago = 0 THEN co.cupos ELSE 0 END) AS cupos,
               SUM(CASE WHEN co.es_rezago = 1 THEN co.cupos ELSE 0 END) AS cupos_rezago,
               COUNT(*) AS filas
        FROM   compromiso co
        JOIN   proyecto pr ON pr.proyecto_id = co.proyecto_id
        JOIN   unidad_academica u ON u.unidad_id = co.unidad_id
        GROUP  BY pr.ciclo_id, co.unidad_id, u.nombre
        """,
    ),
    (
        # I2: aggregate only through the closure, never `WHERE sede_id = :x`,
        # which in v1 included the sede's own row and returned 41 + 25 = 66.
        "v_unidad_descendientes",
        """
        CREATE VIEW v_unidad_descendientes AS
        SELECT r.ancestro_id, r.descendiente_id, r.distancia,
               a.nombre AS ancestro, d.nombre AS descendiente
        FROM   unidad_rollup r
        JOIN   unidad_academica a ON a.unidad_id = r.ancestro_id
        JOIN   unidad_academica d ON d.unidad_id = r.descendiente_id
        WHERE  r.distancia > 0
        """,
    ),
    (
        # §7.2: a dimension member with no facts must be distinguishable from a
        # measured zero. A LEFT JOIN renders both as 0, so `observado` is exposed.
        "v_cobertura_cuartil",
        """
        CREATE VIEW v_cobertura_cuartil AS
        SELECT q.cuartil_id, q.notacion, q.observado,
               ct.ciclo_id, ct.unidad_id, ct.periodo_id, ct.via_id,
               ct.estudiantes, ct.documento_id, ct.ubicacion
        FROM   cuartil_prioridad q
        LEFT   JOIN cobertura_territorial ct ON ct.cuartil_id = q.cuartil_id
        """,
    ),
    (
        # The provenance hero: every measured figure in the database, whatever
        # table it lives in, normalised to one shape and joined to its document.
        # Every panel drills into this.
        "v_procedencia",
        """
        CREATE VIEW v_procedencia AS
        WITH hechos AS (
            SELECT 'declaracion' AS origen, medida_id AS medida, ciclo_id, unidad_id,
                   CAST(valor AS REAL) AS valor, valor_origen AS literal,
                   documento_id, ubicacion
            FROM   declaracion
            UNION ALL
            SELECT 'asignacion', 'monto', ciclo_id, unidad_id,
                   CAST(monto AS REAL), monto_origen, documento_id, ubicacion
            FROM   asignacion
            UNION ALL
            SELECT 'presupuesto_rubro', 'monto', ciclo_id, unidad_id,
                   CAST(monto AS REAL), monto_origen, documento_id, ubicacion
            FROM   presupuesto_rubro
            UNION ALL
            -- Posts created are facts with provenance like any other. Leaving
            -- them out made five documents read as unprocessed when their only
            -- figures had loaded correctly.
            SELECT 'cargo_creado',
                   CASE WHEN tipo = 'ADMINISTRATIVO' THEN 'cargos_administrativos'
                        ELSE 'cargos_creados' END,
                   'TODOS', unidad_id,
                   CAST(cantidad AS REAL), cantidad_origen, documento_id, ubicacion
            FROM   cargo_creado
            UNION ALL
            SELECT 'cobertura_territorial', 'estudiantes_cuartil', ciclo_id, unidad_id,
                   CAST(estudiantes AS REAL), CAST(estudiantes AS TEXT),
                   documento_id, ubicacion
            FROM   cobertura_territorial
        )
        SELECT h.origen, h.medida, h.ciclo_id, h.unidad_id,
               u.nombre AS unidad, h.valor, h.literal,
               h.documento_id, h.ubicacion,
               d.titulo AS documento, d.tipo AS documento_tipo,
               d.soporte, d.ruta_archivo,
               -- The container the citation lives in: a sheet name for a cell
               -- address, a table caption for a Word table. It is the key the
               -- evidence panel joins on, so it must match how the rendered
               -- source tables are named.
               CASE WHEN h.ubicacion LIKE '%!%'
                    THEN substr(h.ubicacion, 1, instr(h.ubicacion, '!') - 1)
                    WHEN h.ubicacion LIKE 'Tabla %,%' OR h.ubicacion LIKE 'p.%,%'
                      OR h.ubicacion LIKE '§%,%'
                      OR h.ubicacion LIKE 'Tabla de fuentes,%'
                    THEN substr(h.ubicacion, 1, instr(h.ubicacion, ',') - 1)
                    ELSE h.documento_id END AS contenedor
        FROM   hechos h
        JOIN   documento d ON d.documento_id = h.documento_id
        JOIN   unidad_academica u ON u.unidad_id = h.unidad_id
        """,
    ),
    (
        # The funnel, as a view rather than chart configuration — which is what
        # stops a BI tool computing it some other way.
        "v_embudo",
        """
        CREATE VIEW v_embudo AS
        SELECT d.ciclo_id,
               d.medida_id,
               CASE d.medida_id WHEN 'compromiso' THEN 1
                                WHEN 'cupos_ofertados' THEN 2
                                WHEN 'admitidos' THEN 3
                                WHEN 'matriculados' THEN 4 END AS paso,
               CAST(d.valor AS INT) AS valor,
               d.documento_id, d.ubicacion, d.valor_origen
        FROM   declaracion d
        WHERE  d.unidad_id = 'UNAL_TOTAL'
          AND  d.tipo_declaracion = 'AGREGADO'
          AND  d.medida_id IN ('compromiso','cupos_ofertados','admitidos','matriculados')
          AND  d.ubicacion LIKE 'Tabla 2%'
        """,
    ),
    (
        "v_compromiso_ciclo",
        """
        CREATE VIEW v_compromiso_ciclo AS
        SELECT d.unidad_id, u.nombre AS unidad, u.grupo,
               d.ciclo_id, c.anio_formulacion,
               CAST(d.valor AS INT) AS cupos,
               d.documento_id, d.ubicacion
        FROM   declaracion d
        JOIN   unidad_academica u ON u.unidad_id = d.unidad_id
        JOIN   ciclo c ON c.ciclo_id = d.ciclo_id
        WHERE  d.medida_id = 'compromiso' AND d.unidad_id <> 'UNAL_TOTAL'
        """,
    ),
    (
        "v_dinero_fuente",
        """
        CREATE VIEW v_dinero_fuente AS
        SELECT a.unidad_id, u.nombre AS unidad, a.ciclo_id, a.vigencia,
               a.fuente_id, f.nombre AS fuente, f.columna_xlsx,
               a.tipo_flujo, a.momento,
               CAST(a.monto AS REAL) AS monto, a.monto_origen,
               a.documento_id, a.ubicacion,
               -- E1: column N reconciles to no resolution, so it is shown but
               -- never silently summed into a headline.
               CASE WHEN a.fuente_id = 'BASE_2025' THEN 1 ELSE 0 END AS en_disputa
        FROM   asignacion a
        JOIN   unidad_academica u ON u.unidad_id = a.unidad_id
        JOIN   fuente_financiacion f ON f.fuente_id = a.fuente_id
        """,
    ),
    (
        "v_presupuesto",
        """
        CREATE VIEW v_presupuesto AS
        SELECT p.ciclo_id, c.programa_id,
               p.rubro_id, r.nombre AS rubro, r.generacion, r.nivel,
               padre.rubro_id AS linea_id, padre.nombre AS linea,
               p.concepto, CAST(p.cantidad AS REAL) AS cantidad,
               CAST(p.monto AS REAL) AS monto, p.monto_origen,
               p.documento_id, p.ubicacion
        FROM   presupuesto_rubro p
        JOIN   rubro r ON r.rubro_id = p.rubro_id
        LEFT   JOIN rubro padre ON padre.rubro_id = r.padre_id
        JOIN   ciclo c ON c.ciclo_id = p.ciclo_id
        """,
    ),
    (
        "v_hallazgos",
        """
        CREATE VIEW v_hallazgos AS
        SELECT h.hallazgo_id, h.clase, h.titulo, h.detalle, h.impacto,
               h.estado, h.verificacion,
               h.documento_id, h.ubicacion,
               d.titulo AS documento, d.soporte, d.estado AS documento_estado,
               CASE h.estado WHEN 'VERIFICADO' THEN 1 ELSE 0 END AS probado
        FROM   hallazgo h
        LEFT   JOIN documento d ON d.documento_id = h.documento_id
        """,
    ),
    (
        # The scope panel: what the corpus holds, what has been parsed, and what
        # is still waiting. Volunteered, not extracted under questioning.
        "v_corpus",
        """
        CREATE VIEW v_corpus AS
        SELECT d.documento_id, d.tipo, d.emisor, d.titulo,
               d.estado, d.soporte, d.ruta_archivo,
               COALESCE(f.cifras, 0) AS cifras,
               CASE WHEN COALESCE(f.cifras, 0) > 0    THEN 'PROCESADO'
                    WHEN d.estado <> 'EN_CORPUS'       THEN 'AUSENTE'
                    WHEN d.aporta_cifras = 0           THEN 'SIN_CIFRAS'
                    WHEN d.soporte = 'ESCANEO'         THEN 'PENDIENTE_VISION'
                    ELSE 'PENDIENTE' END AS avance
        FROM   documento d
        LEFT   JOIN (SELECT documento_id, count(*) AS cifras
                     FROM v_procedencia GROUP BY documento_id) f
               ON f.documento_id = d.documento_id
        """,
    ),
]


def _crear_vistas(engine: Engine) -> None:
    with engine.begin() as conn:
        for nombre, ddl in _VISTAS:
            conn.execute(text(f"DROP VIEW IF EXISTS {nombre}"))
            conn.execute(text(ddl))
