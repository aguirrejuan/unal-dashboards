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

const PALETA = ['#1c4e80', '#2d7dd2', '#68a5e0', '#a8c8ea', '#b4432f', '#1d7a4f'];

/** One Plotly layout for every chart, so the pages look like one document. */
function layout(extra = {}) {
  const tinta = CSSVAR('--tinta'), tenue = CSSVAR('--tenue'), linea = CSSVAR('--linea');
  const base = {
    paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
    font:{family:'ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif',
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


/** A stored path (`extracted/PIC-Información/…`) becomes a link into the copy
    of the corpus published beside the site. Documents that are only cited have
    no file, so they get no link rather than a broken one. */
function enlaceDoc(ruta, texto) {
  if (!ruta) return esc(texto || '');
  const partes = String(ruta).split('/');
  const destino = 'corpus/' + partes.slice(1).map(encodeURIComponent).join('/');
  return `<a class="doc-enlace" href="${destino}" target="_blank" rel="noopener"
             title="${esc(ruta)}">${esc(texto || partes[partes.length - 1])}</a>`;
}

/** Documents indexed by id, so any page can link a citation to its source. */
const DOCS = {};
if (window.CARGA && CARGA.datos && CARGA.datos.v_corpus) {
  CARGA.datos.v_corpus.forEach(d => { DOCS[d.documento_id] = d; });
}
const enlaceDocId = (id, texto) => {
  const d = DOCS[id];
  return d && d.ruta_archivo
    ? enlaceDoc(d.ruta_archivo, texto || id)
    : `<span title="citado, no disponible">${esc(texto || id)}</span>`;
};
