/* Shared helpers. Loaded after datos.js, before each page's own script.
   The payload arrives as a global so the browser caches it once for both
   pages instead of parsing an identical copy inlined in each. */

const $   = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = n => n === null || n === undefined || n === ''
  ? '' : Number(n).toLocaleString('es-CO', {maximumFractionDigits:1});

/** Pesos, abbreviated: the figures run to twelve digits and nobody reads those. */
const cop = n => {
  const v = Number(n);
  if (!isFinite(v)) return '';
  if (Math.abs(v) >= 1e12) return '$' + (v/1e12).toFixed(2) + ' B';
  if (Math.abs(v) >= 1e9)  return '$' + (v/1e9).toFixed(1) + ' mM';
  if (Math.abs(v) >= 1e6)  return '$' + (v/1e6).toFixed(1) + ' M';
  return '$' + fmt(v);
};

const CSSVAR = n => getComputedStyle(document.documentElement)
  .getPropertyValue(n).trim();

/* The institutional palette, in chart order. The dark green leads because the
   institutional green — Pantone 376, the University's signature — is too light
   to carry a thin bar on white; it takes second place, where it reads as the
   accent it is. The two greys are Pantone 425 and 421, not neutrals of my
   choosing. Series beyond the sixth get tints of 376, which is the only
   direction the palette extends without inventing a colour. */
const PALETA = ['#466b3f', '#94b43b', '#a61c31', '#565a5c', '#76232f', '#b1b2b0'];
const PALETA_LARGA = PALETA.concat(
  ['#6f8f4a', '#b9cd7c', '#c26a76', '#8b9093', '#a8bd5e', '#d5dfb7']);

/* On this site the alterno red means a divergence between documents — the two
   endings of the funnel, a finding of high impact. A series that merely lists
   cycles or document types must not spend it, or every page looks like an
   alarm. This ramp runs from 7743 C through 376 C and out into the two official
   greys: ordinal where the data is ordinal, and never alarming. */
const PALETA_SERIE = ['#466b3f', '#6f8f4a', '#94b43b', '#b9cd7c',
                      '#565a5c', '#8b9093', '#b1b2b0', '#d5dfb7'];

/** One Plotly layout for every chart, so the pages look like one document. */
function layout(extra = {}) {
  const tinta = CSSVAR('--tinta'), tenue = CSSVAR('--tenue'), linea = CSSVAR('--linea');
  const base = {
    paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
    font:{family:CSSVAR('--tipo') ||
          'ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif',
          size:12, color:tinta},
    margin:{l:10, r:18, t:14, b:44, pad:6},
    xaxis:{gridcolor:linea, zerolinecolor:linea, linecolor:linea,
           tickfont:{color:tenue, size:11.5},
           title:{font:{color:tenue, size:11.5}}, automargin:true},
    yaxis:{gridcolor:linea, zerolinecolor:linea, linecolor:linea,
           tickfont:{color:tenue, size:11.5},
           title:{font:{color:tenue, size:11.5}}, automargin:true},
    legend:{font:{color:tenue, size:11.5}, bgcolor:'rgba(0,0,0,0)'},
    hoverlabel:{bgcolor:CSSVAR('--panel'), bordercolor:linea,
                font:{color:tinta, size:12}},
    bargap:.3, bargroupgap:.12,
  };
  const fusion = {...base, ...extra};
  fusion.xaxis = {...base.xaxis, ...(extra.xaxis || {})};
  fusion.yaxis = {...base.yaxis, ...(extra.yaxis || {})};
  return fusion;
}

/* Plotly's toolbar is noise on a page meant to be read, not operated. */
if (window.Plotly) {
  const original = Plotly.newPlot;
  Plotly.newPlot = (el, data, lay, cfg) => original(el, data, lay,
    {displayModeBar:false, responsive:true, ...cfg});
}

/** Render a table. `cols` take {t: header, k: key} or {t, r: row => html}. */
function tabla(el, cols, filas, opts = {}) {
  const th = cols.map(c => `<th class="${c.num ? 'num' : ''}">${esc(c.t)}</th>`).join('');
  const tr = filas.map((f, i) => `<tr data-i="${i}">` + cols.map(c =>
    `<td class="${c.num ? 'num' : ''}">${c.r ? c.r(f) : esc(f[c.k])}</td>`
  ).join('') + '</tr>').join('');
  el.innerHTML = `<thead><tr>${th}</tr></thead><tbody>${tr}</tbody>`;
  if (opts.alSeleccionar) {
    el.classList.add('clic');
    el.querySelectorAll('tbody tr').forEach(tr => tr.onclick = () => {
      el.querySelectorAll('tr.sel').forEach(x => x.classList.remove('sel'));
      tr.classList.add('sel');
      opts.alSeleccionar(filas[+tr.dataset.i]);
    });
  }
}


/** A stored path (`extracted/PIC-Información/…`) becomes a URL into the copy of
    the corpus published beside the site. */
function rutaCorpus(ruta) {
  return 'corpus/' + String(ruta).split('/').slice(1).map(encodeURIComponent).join('/');
}

/** A link straight to the file. Use it only where the reader has asked for the
    original: a browser downloads .docx, .xlsx and .doc rather than showing
    them, so a bare link to one of those looks like a broken link. */
function enlaceArchivo(ruta, texto) {
  if (!ruta) return esc(texto || '');
  const partes = String(ruta).split('/');
  return `<a class="doc-enlace" href="${rutaCorpus(ruta)}" target="_blank" rel="noopener"
             title="${esc(ruta)}">${esc(texto || partes[partes.length - 1])}</a>`;
}

/** Documents indexed by id, so any page can link a citation to its source. */
const DOCS = {};
if (window.CARGA && CARGA.datos && CARGA.datos.v_corpus) {
  CARGA.datos.v_corpus.forEach(d => { DOCS[d.documento_id] = d; });
}
/** Every citation points at the in-site viewer rather than at the file. The
    viewer embeds a PDF and reproduces the tables of everything else, so a
    citation always opens something readable instead of starting a download.
    Documents that are only cited have no file but still have a page. */
const enlaceDocId = (id, texto) => {
  if (!DOCS[id]) return `<span title="citado, no disponible">${esc(texto || id)}</span>`;
  return `<a class="doc-enlace" href="documento.html?d=${encodeURIComponent(id)}"
             title="${esc(DOCS[id].titulo || id)}">${esc(texto || id)}</a>`;
};

/** A readable short name for a document id. Titles run to eighty characters and
    ids shout; «Acuerdo 024/2025» is what a reader would say out loud. */
function nombreCorto(id) {
  const m = String(id).match(/^(ACU_CSU|RES_MEN)_0*(\d+)_(\d{4})$/);
  if (m) return (m[1] === 'ACU_CSU' ? 'Acuerdo ' : 'Res. ') + m[2] + '/' + m[3];
  return {ANEXO1_PIC:'Anexo 1', ANEXO2_PIC:'Anexo 2',
          INFORME_MEN_2024_2025:'Informe al MEN',
          INFORME_CUALITATIVO:'Informe cualitativo',
          OFICIO_PIC_CO_ET:'Oficio remisorio',
          ORDEN_422447:'Orden 422447'}[id] || id;
}

/* ------------------------------------------------- ciclos, vigencias, cifras */

/** Cycles by id, so any figure can say which years it actually covers. */
const CICLOS = {};
if (window.CARGA && CARGA.datos && CARGA.datos.v_ciclo) {
  CARGA.datos.v_ciclo.forEach(c => { CICLOS[c.ciclo_id] = c; });
}

/** The sentence a reader needs when a figure labelled 2023 counts students who
    enrolled in 2025. A cycle carries three different years and confusing them
    is the single easiest mistake to make with this data. */
function explicaCiclo(id) {
  const c = CICLOS[id];
  if (!c) return id === 'TODOS' ? 'Sin ciclo: la cifra no se atribuye a ninguno.' : '';
  return `${c.programa_id.replace('_', '-')} ${c.anio_formulacion}: formulado en `
       + `${c.anio_formulacion}, se ejecuta entre ${c.periodo_ejec_desde} y `
       + `${c.periodo_ejec_hasta}. El año del nombre es el de la formulación, `
       + `no el de la matrícula.`;
}

/** The documents behind a set of `v_procedencia` rows, as links, most-cited
    first. A figure without its sources is an assertion; with them it is
    evidence, so every reported number on the site carries these. */
function fuentesDe(filas, tope = 4) {
  const cuenta = {};
  filas.forEach(f => { cuenta[f.documento_id] = (cuenta[f.documento_id] || 0) + 1; });
  const ids = Object.entries(cuenta).sort((a, b) => b[1] - a[1]).map(([id]) => id);
  const visibles = ids.slice(0, tope)
    .map(id => enlaceDocId(id, nombreCorto(id))).join(' · ');
  // Fourteen links turn a card into a directory. The rest are in the tooltip.
  return ids.length > tope
    ? `${visibles} <span class="mas">y ${ids.length - tope} más</span>`
    : visibles;
}

/** Where each figure sits, spelled out: «Anexo 1 · Tabla 2, fila 9 'TOTAL'». */
const citaDe = f => `${nombreCorto(f.documento_id)} · ${f.ubicacion}`;

/** A KPI card. `filas` are the `v_procedencia` rows the number came from; they
    become the hover explanation and the visible links under it. */
function cifra({v, et, pie, filas = [], ayuda = '', clase = ''}) {
  const ciclos = [...new Set(filas.map(f => f.ciclo_id).filter(c => c && c !== 'TODOS'))];
  const docs = [...new Set(filas.map(f => f.documento_id))];
  const titulo = [ayuda, ...ciclos.map(explicaCiclo),
                  docs.length ? 'Documentos: ' + docs.map(nombreCorto).join(', ') : '']
    .filter(Boolean).join('\n\n');
  return `<div class="kpi ${clase}"${titulo
      ? ` data-ayuda="${esc(titulo)}" tabindex="0"` : ''}>
    <b>${v}</b><span class="et">${esc(et)}${titulo ? '<i class="signo">?</i>' : ''}</span>
    ${pie ? `<span class="pie">${pie}</span>` : ''}
    ${filas.length ? `<span class="fuente-kpi">${fuentesDe(filas)}</span>` : ''}
  </div>`;
}

/* ---------------------------------------------------------------- globos */
/* The native `title` waits a second, renders as a grey OS strip, vanishes on
   the smallest movement, and gives no sign it exists at all. On a page whose
   whole argument is «hover anything and it explains itself», that is the same
   as having no explanation. One floating element, shown at once, styled like
   the rest of the site. */

const GLOBO = document.createElement('div');
GLOBO.className = 'globo';
GLOBO.hidden = true;
document.body.appendChild(GLOBO);

let anclaGlobo = null;

function colocarGlobo(el) {
  const texto = el.getAttribute('data-ayuda');
  if (!texto) return;
  anclaGlobo = el;
  GLOBO.innerHTML = texto.split('\n\n')
    .map(p => `<p>${esc(p).replace(/\n/g, '<br>')}</p>`).join('');
  GLOBO.hidden = false;

  const r = el.getBoundingClientRect();
  const g = GLOBO.getBoundingClientRect();
  const margen = 10;
  let x = r.left + r.width / 2 - g.width / 2;
  x = Math.max(margen, Math.min(x, window.innerWidth - g.width - margen));
  // Above the element when there is room, below when there is not.
  const arriba = r.top > g.height + margen;
  GLOBO.style.left = x + 'px';
  GLOBO.style.top = (arriba ? r.top - g.height - 8 : r.bottom + 8) + 'px';
  GLOBO.dataset.lado = arriba ? 'arriba' : 'abajo';
}

function ocultarGlobo() { GLOBO.hidden = true; anclaGlobo = null; }

document.addEventListener('mouseover', e => {
  const el = e.target.closest('[data-ayuda]');
  if (el === anclaGlobo) return;
  if (el) colocarGlobo(el); else if (anclaGlobo) ocultarGlobo();
});
document.addEventListener('focusin', e => {
  const el = e.target.closest('[data-ayuda]');
  if (el) colocarGlobo(el);
});
document.addEventListener('focusout', ocultarGlobo);
window.addEventListener('scroll', () => { if (anclaGlobo) colocarGlobo(anclaGlobo); },
                        {passive: true});
document.addEventListener('keydown', e => { if (e.key === 'Escape') ocultarGlobo(); });

/** Mark up anything that carries an explanation: attribute, cursor and a small
    sign that there is something to hover over. */
const conAyuda = (texto, html, etiqueta = '') => texto
  ? `<span class="ayuda" data-ayuda="${esc(texto)}" tabindex="0">${html}${
      etiqueta ? '<i class="signo">?</i>' : ''}</span>`
  : html;

/** An institutional icon, by name. See `iconos.svg` for the construction rules. */
const ico = (nombre, clase = 'ico') =>
  `<svg class="${clase}" aria-hidden="true"><use href="#ico-${nombre}"/></svg>`;

/** The icon for a document type. Seven types read faster as marks than as
    uppercase words repeated down a column. Anything unmapped gets no icon
    rather than a wrong one. */
const TIPO_ICONO = {ACUERDO:'acuerdo', RESOLUCION:'resolucion', ANEXO:'anexo',
                    INFORME:'informe', OFICIO:'oficio', SENTENCIA:'sentencia',
                    ORDEN:'orden'};
const icoTipo = tipo => TIPO_ICONO[tipo] ? ico(TIPO_ICONO[tipo], 'ico ico-tipo') : '';

/* ------------------------------------------------------------ confirmación */
/* Cuán confirmada está una cifra. No es un juicio sobre el documento: es un
   hecho sobre cómo llegó hasta aquí, y el lector merece verlo junto al número
   en lugar de tener que preguntarlo. */
const CONFIRMACION = {
  CORROBORADA: {
    pill:'ok', texto:'corroborada',
    ayuda:'Varios documentos declaran este mismo valor para el mismo grano. Es '
         +'la cifra mejor sostenida que ofrece el corpus.'},
  COMPROBADA: {
    pill:'pend', texto:'comprobada',
    ayuda:'Un documento la declara. En cada construcción se reabre el archivo '
         +'original y se compara el literal guardado contra su celda; si no '
         +'coincidiera, la publicación se detendría.'},
  SIN_COMPROBAR: {
    pill:'tenue', texto:'sin comprobar',
    ayuda:'El original es un escaneo sin capa de texto: no hay contra qué '
         +'comparar. La garantía es el hash del archivo más la lectura de una '
         +'persona, que es más débil, y por eso se dice.'},
  EN_CONFLICTO: {
    pill:'alto', texto:'en conflicto',
    ayuda:'Dos o más documentos declaran valores distintos para este mismo '
         +'grano y ninguno corrige al otro. El grano no se resuelve: la base '
         +'guarda las dos lecturas en lugar de elegir una.'},
};

/** The badge for a figure's confirmation state. */
const sello = estado => {
  const c = CONFIRMACION[estado];
  return c ? `<span class="pill ${c.pill}" data-ayuda="${esc(c.ayuda)}"
                    tabindex="0">${c.texto}</span>` : '';
};
