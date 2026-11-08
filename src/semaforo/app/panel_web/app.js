/* Panel de resultados (DEV31 F5). No pide nada a la red: solo muestra lo que trae datos.js.
 *
 * Cada página es una función pura (datos y estado entran, texto sale) y todo valor que viene de los
 * datos pasa por esc() antes de ser HTML. Por eso las páginas se pueden probar sin navegador
 * (tests/integration/test_bd_panel.py) con un texto hostil en cada campo. */
(function (root) {
  'use strict';

  const ROUTES = [
    ['inicio', 'Inicio'], ['caso', 'Caso'], ['escenarios', 'Escenarios y protocolo'],
    ['simulaciones', 'Simulaciones'], ['comparacion', 'Comparación con el plan actual'],
    ['busqueda', 'Búsqueda'], ['entrenamiento', 'Entrenamiento'], ['consultas', 'Consultas'],
    ['evaluacion', 'Evaluación final'], ['evidencia', 'Evidencia']
  ];
  const WORDS = {
    search: 'Búsqueda', finalists: 'Finalistas', diagnostic: 'Diagnóstico', final: 'Prueba final',
    succeeded: 'Terminó', failed: 'Falló', cancelled: 'Cancelada', complete: 'Completa',
    censored: 'Censurada', empty: 'Sin datos', incomplete: 'Incompleta', synthetic: 'Sintético',
    field: 'De campo', current_plan: 'Plan actual', sampled: 'Muestreado', draft: 'Borrador',
    frozen: 'Congelado', no_reference: 'Sin referencia', selected: 'Con referencia',
    no_eligible_finalist: 'ningún finalista cumplió las condiciones en todas sus semillas',
    no_candidates: 'no hubo planes que probar', not_applicable: 'No aplicable', applicable: 'Aplicable',
    teleports: 'teletransportes', collisions: 'choques', zone_incomplete: 'zona incompleta',
    cohort_incomplete: 'cohorte incompleta', unverified: 'Sin verificar', verified: 'Verificado',
    finished: 'Terminó', unfinished: 'Sin terminar', not_inserted: 'No entró',
    accepted_risk: 'Riesgo aceptado', discarded: 'Descartado', kept_existing: 'Se conservó lo existente',
    new_version: 'Versión nueva', not_loadable: 'No se puede cargar', ok: 'Coincide', difiere: 'Difiere',
    no_concluyente: 'No concluyente', verificar: 'Verificación contra git', red: 'Red',
    conciliar: 'Base contra archivos', cobertura: 'Cobertura', barrido: 'Barrido de cegado',
    respaldo: 'Respaldo restaurado', hecho: 'Hecho', en_curso: 'En curso', pendiente: 'Pendiente',
    protocol_frozen: 'Protocolo congelado', split_frozen: 'Partición congelada',
    model_frozen: 'Modelo congelado', test_opened: 'Prueba abierta', variable: 'Verde ajustable',
    fixed: 'Fijo', train: 'Entrenamiento', validation: 'Validación', test: 'Prueba'
  };
  const GOOD = new Set(['succeeded', 'complete', 'ok', 'hecho', 'finished', 'frozen', 'selected']);
  const WARN = new Set(['censored', 'en_curso', 'no_concluyente', 'draft', 'incomplete', 'unverified', 'no_reference']);
  const BAD = new Set(['failed', 'difiere', 'not_loadable']);

  const esc = (v) => String(v === null || v === undefined ? '' : v).replace(/[&<>"'`]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' }[c]));
  const word = (v) => (v === null || v === undefined ? '—' : (Object.prototype.hasOwnProperty.call(WORDS, v) ? WORDS[v] : String(v)));
  const NF = (d) => new Intl.NumberFormat('es-PE', { maximumFractionDigits: d, minimumFractionDigits: d });
  const num = (v, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? NF(d).format(v) : '—');
  const int = (v) => num(v, 0);
  const signed = (v, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? (v > 0 ? '+' : '') + NF(d).format(v) : '—');
  const short = (id) => esc(String(id === null || id === undefined ? '—' : id).slice(0, 8));
  const date = (v) => (v ? esc(String(v).slice(0, 10)) : '—');
  const yes = (v) => (v === true ? 'Sí' : v === false ? 'No' : '—');
  const pill = (state, text) => {
    const kind = GOOD.has(state) ? 'ok' : WARN.has(state) ? 'warn' : BAD.has(state) ? 'bad' : '';
    return `<span class="pill ${kind}">${esc(text === undefined ? word(state) : text)}</span>`;
  };
  const list = (v) => (Array.isArray(v) ? v : []);
  const head = (title, sub) => `<div class="page-head"><h1>${esc(title)}</h1><p>${esc(sub)}</p></div>`;
  const notice = (html, amber) => `<div class="notice${amber ? ' amber' : ''}">${html}</div>`;
  const metric = (label, value, unit, note) => `<div class="card"><div class="metric-label">${esc(label)}</div><div class="metric-number">${esc(value)} <span class="metric-unit">${esc(unit || '')}</span></div><div class="metric-note">${esc(note || '')}</div></div>`;
  const empty = (title, body, extra) => `<div class="empty ${extra || ''}"><h2>${esc(title)}</h2><p>${esc(body)}</p></div>`;

  /* Una tabla: columnas [título, función de la fila que ya devuelve HTML, ¿numérica?]. */
  function table(columns, rows, opts) {
    const o = opts || {};
    const heads = columns.map((c) => `<th scope="col"${c[2] ? ' class="num"' : ''}>${esc(c[0])}</th>`).join('');
    const body = rows.map((row) => {
      const cells = columns.map((c) => `<td${c[2] ? ' class="num"' : ''}>${c[1](row)}</td>`).join('');
      return `<tr${o.rowClass && o.rowClass(row) ? ` class="${o.rowClass(row)}"` : ''}>${cells}</tr>`;
    }).join('');
    const caption = o.caption ? `<caption>${esc(o.caption)}</caption>` : '';
    return `<div class="table-wrap"><table>${caption}<thead><tr>${heads}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function dl(pairs) {
    return `<dl class="datos">${pairs.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
  }

  function fileLink(data, rootName, path) {
    if (!path) return '—';
    const base = (data.enlaces || {})[rootName];
    const shown = `<span class="id">${esc(path)}</span>`;
    if (!base) return shown;
    const parts = String(path).split('/').map(encodeURIComponent).join('/');
    return `<a href="${esc(base)}/${esc(parts)}" rel="noopener">${shown}</a>`;
  }

  /* --- gráficos en SVG: sin estilos en línea, con su título y siempre con una tabla al lado ---- */

  function niceMax(value) {
    if (!(value > 0)) return 1;
    const power = Math.pow(10, Math.floor(Math.log10(value)));
    for (const step of [1, 2, 2.5, 5, 10]) if (step * power >= value) return step * power;
    return 10 * power;
  }

  /* Una fila por grupo y un punto por semilla; el punto con incidentes es un rombo hueco. */
  function stripPlot(rows, unit, label) {
    const width = 960; const left = 210; const right = 24; const rowH = 34; const top = 8;
    const all = rows.flatMap((r) => r.dots.map((d) => d.v)).filter((v) => typeof v === 'number');
    const max = niceMax(all.length ? Math.max(...all) : 1);
    const x = (v) => left + (v / max) * (width - left - right);
    const height = top + rows.length * rowH + 30;
    const ticks = [0, 0.2, 0.4, 0.6, 0.8, 1].map((t) => t * max);
    let out = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)}">`;
    ticks.forEach((t) => {
      out += `<line class="eje" x1="${x(t).toFixed(1)}" x2="${x(t).toFixed(1)}" y1="${top}" y2="${height - 24}"/>`;
      out += `<text x="${x(t).toFixed(1)}" y="${height - 8}" text-anchor="middle">${num(t, 0)}</text>`;
    });
    rows.forEach((r, i) => {
      const y = top + i * rowH + rowH / 2;
      out += `<text x="${left - 10}" y="${y + 4}" text-anchor="end">${esc(r.label)}</text>`;
      r.dots.forEach((d) => {
        if (typeof d.v !== 'number') return;
        const cx = x(d.v).toFixed(1);
        const title = `<title>${esc(d.title)}</title>`;
        out += d.bad
          ? `<path class="incidente" d="M${cx} ${y - 6} L${(+cx + 6).toFixed(1)} ${y} L${cx} ${y + 6} L${(+cx - 6).toFixed(1)} ${y} Z">${title}</path>`
          : `<circle class="punto" cx="${cx}" cy="${y}" r="4.5">${title}</circle>`;
      });
    });
    out += '</svg>';
    return `<div class="chart">${out}<div class="legend"><span>● sin incidentes</span><span>◇ con teletransportes o choques</span><span>Eje: ${esc(unit)}</span></div></div>`;
  }

  /* Diferencia frente a una referencia: a la izquierda del cero, menos que la referencia. */
  function divergingBars(rows, unit, label) {
    const width = 960; const left = 210; const right = 90; const rowH = 26; const top = 6;
    const max = niceMax(Math.max(1, ...rows.map((r) => Math.abs(r.v))));
    const mid = left + (width - left - right) / 2;
    const scale = (width - left - right) / 2 / max;
    const height = top + rows.length * rowH + 28;
    let out = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)}">`;
    rows.forEach((r, i) => {
      const y = top + i * rowH;
      const w = Math.abs(r.v) * scale;
      const x = r.v < 0 ? mid - w : mid;
      out += `<text x="${left - 10}" y="${y + 16}" text-anchor="end">${esc(r.label)}</text>`;
      out += `<rect class="${r.v < 0 ? 'barra-menos' : 'barra-mas'}" x="${x.toFixed(1)}" y="${y + 4}" width="${w.toFixed(1)}" height="16"><title>${esc(r.title)}</title></rect>`;
      out += `<text x="${(r.v < 0 ? x - 6 : x + w + 6).toFixed(1)}" y="${y + 16}" text-anchor="${r.v < 0 ? 'end' : 'start'}">${signed(r.v)}</text>`;
    });
    out += `<line class="cero" x1="${mid}" x2="${mid}" y1="${top}" y2="${height - 24}"/>`;
    out += `<text x="${mid}" y="${height - 8}" text-anchor="middle">0 = igual que el plan actual</text></svg>`;
    return `<div class="chart">${out}<div class="legend"><span>Barra a la izquierda: menos demora que el plan actual</span><span>Barra a la derecha: más demora</span><span>Unidad: ${esc(unit)}</span></div></div>`;
  }

  function lineChart(xs, flags, lines, label) {
    const width = 960; const height = 300; const left = 56; const right = 18; const top = 12; const bottom = 34;
    const vals = lines.flatMap((l) => l.values).filter((v) => typeof v === 'number');
    const yMax = niceMax(vals.length ? Math.max(...vals) : 1);
    const xMax = xs.length ? Math.max(...xs) : 1;
    const x = (v) => left + (v / (xMax || 1)) * (width - left - right);
    const y = (v) => height - bottom - (v / yMax) * (height - top - bottom);
    let out = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)}">`;
    const inside = xs.filter((_, i) => flags[i]);
    if (inside.length) {
      out += `<rect class="ventana" x="${x(Math.min(...inside)).toFixed(1)}" y="${top}" width="${(x(Math.max(...inside)) - x(Math.min(...inside))).toFixed(1)}" height="${height - top - bottom}"/>`;
    }
    [0, 0.2, 0.4, 0.6, 0.8, 1].forEach((t) => {
      const value = t * yMax;
      out += `<line class="eje" x1="${left}" x2="${width - right}" y1="${y(value).toFixed(1)}" y2="${y(value).toFixed(1)}"/>`;
      out += `<text x="${left - 6}" y="${(y(value) + 4).toFixed(1)}" text-anchor="end">${num(value, 0)}</text>`;
    });
    [0, 0.25, 0.5, 0.75, 1].forEach((t) => {
      out += `<text x="${x(t * xMax).toFixed(1)}" y="${height - 12}" text-anchor="middle">${num((t * xMax) / 60, 0)} min</text>`;
    });
    lines.forEach((l, i) => {
      const pts = l.values.map((v, j) => (typeof v === 'number' ? `${x(xs[j]).toFixed(1)},${y(v).toFixed(1)}` : '')).filter(Boolean).join(' ');
      out += `<polyline class="${i === 0 ? 'linea' : 'linea2'}" points="${pts}"><title>${esc(l.label)}</title></polyline>`;
    });
    out += '</svg>';
    const legend = lines.map((l, i) => `<span>${i === 0 ? '━' : '╍'} ${esc(l.label)}</span>`).join('');
    return `<div class="chart">${out}<div class="legend">${legend}<span>Zona sombreada: ventana de medición</span></div></div>`;
  }

  function stackBars(rows, tramos, label) {
    const width = 960; const left = 210; const right = 60; const rowH = 28; const top = 6;
    const max = Math.max(1, ...rows.map((r) => r.total));
    const scale = (width - left - right) / max;
    const height = top + rows.length * rowH + 6;
    let out = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)}">`;
    rows.forEach((r, i) => {
      const y = top + i * rowH;
      let cursor = left;
      out += `<text x="${left - 10}" y="${y + 16}" text-anchor="end">${esc(r.label)}</text>`;
      let green = 0;
      tramos.forEach((t) => {
        const v = r.parts[t.tramo_id];
        if (typeof v !== 'number') return;
        const w = v * scale;
        const kind = t.tipo === 'variable' ? `v${green++ % 4}` : 'fijo';
        out += `<rect class="${kind}" x="${cursor.toFixed(1)}" y="${y + 3}" width="${w.toFixed(1)}" height="20"><title>${esc(t.tramo_id)}: ${num(v, 0)} s</title></rect>`;
        if (t.tipo === 'variable' && w > 24) out += `<text class="claro" x="${(cursor + w / 2).toFixed(1)}" y="${y + 18}" text-anchor="middle">${num(v, 0)}</text>`;
        cursor += w;
      });
      out += `<text x="${(cursor + 6).toFixed(1)}" y="${y + 18}">${num(r.total, 0)} s</text>`;
    });
    return `<div class="chart">${out}</svg></div>`;
  }

  /* --- ayudas de datos ---------------------------------------------------------------------- */

  function byKey(rows, key) {
    const found = new Map();
    list(rows).forEach((row) => {
      const k = row[key];
      if (!found.has(k)) found.set(k, []);
      found.get(k).push(row);
    });
    return found;
  }
  const runOf = (data, id) => list(data.corridas).find((r) => r.run_id === id);
  const planOf = (data, id) => list(data.planes).find((p) => p.plan_id === id);
  /* El nombre de un acceso si el proyecto lo declara; siempre con su identificador en la red. */
  const accessName = (data, id) => {
    const names = (data.avance || {}).accesos || {};
    const name = Object.prototype.hasOwnProperty.call(names, id) ? names[id] : null;
    return name ? `${esc(name)} <span class="id">${esc(id)}</span>` : `<span class="id">${esc(id)}</span>`;
  };
  const observed = (data) => list(data.planes).find((p) => p.es_plan_observado);
  const problems = (map) => {
    const text = Object.entries(map || {}).map(([k, v]) => `${esc(word(k))} (${esc(v)})`);
    return text.length ? text.join(', ') : 'ninguno';
  };
  const planLabel = (plan) => `Plan ${String(plan.plan_id).slice(0, 8)} · ${num(plan.ciclo_s, 0)} s`;
  const incident = (r) => Boolean(r.teletransportes_total || r.choques);
  const hasSynthetic = (data) => list(data.corridas).some((r) => r.origen_demanda === 'synthetic');

  /* --- páginas ------------------------------------------------------------------------------- */

  function syntheticNotice(data) {
    return hasSynthetic(data)
      ? notice('<b>Demanda sintética.</b> Los vehículos de estas simulaciones salen de un perfil supuesto, no de aforos reales. Sirven para probar el procedimiento: <b>no demuestran una mejora en el tránsito real</b>.', true)
      : '';
  }

  function findings(data) {
    const comparison = list(data.comparaciones)[0];
    if (!comparison) return '';
    const items = [];
    const base = comparison.plan_observado_diagnostico;
    const withFinalistSeeds = comparison.plan_observado_finalistas;
    if (withFinalistSeeds && withFinalistSeeds.corridas) {
      items.push(`<li><b>Plan actual con las semillas de los finalistas (${esc(withFinalistSeeds.corridas)} semillas):</b> ${esc(withFinalistSeeds.con_incidentes)} con atascos o choques (teletransportes o choques). Sin ellos, la demora media es ${num(withFinalistSeeds.demora_sin_incidentes.media)} s/veh.</li>`);
    }
    if (base && base.corridas) {
      items.push(`<li><b>Plan actual, ${esc(base.corridas)} semillas de diagnóstico:</b> demora de ${num(base.demora.minimo)} a ${num(base.demora.maximo)} s/veh. En ${esc(base.con_incidentes)} semillas hubo vehículos atascados (teletransportes o choques): con ellos la media es ${num(base.demora_con_incidentes.media)} s/veh, sin ellos ${num(base.demora_sin_incidentes.media)} s/veh. Por eso un solo promedio no lo describe bien.</li>`);
    }
    const paired = list(comparison.emparejada);
    const eligible = paired.filter((p) => p.elegible);
    const best = eligible.find((p) => p.pares_validos > 0);
    items.push(`<li><b>Búsqueda:</b> se probaron ${esc(paired.length)} planes además del actual; ${esc(eligible.length)} fueron elegibles. ${comparison.plan_observado_elegible === false ? 'El plan actual tampoco fue elegible: tuvo incidentes en al menos una semilla.' : ''}</li>`);
    if (best) {
      items.push(`<li><b>Mayor diferencia entre los elegibles:</b> ${esc(planLabel(best))}, ${signed(best.diferencia_valida.media)} s/veh frente al plan actual (${signed(best.diferencia_valida_pct, 0)} %), con solo ${esc(best.pares_validos)} pares válidos. Es una señal para seguir investigando, no un resultado final.</li>`);
    }
    const search = list(data.busquedas).find((b) => b.busqueda_id === comparison.busqueda_id);
    if (search) {
      items.push(`<li><b>Resultado de la búsqueda:</b> ${esc(word(search.estado_seleccion))}${search.motivo_sin_referencia ? ` (${esc(word(search.motivo_sin_referencia))})` : ''}.</li>`);
    }
    if (comparison.semillas_finalistas.length && !comparison.finalistas_con_mismas_semillas) {
      items.push('<li><b>Límite importante:</b> el plan actual no se simuló con las semillas de los finalistas, así que esa comparación no es emparejada.</li>');
    }
    return `<h2 class="sec">Lo que muestran los datos hasta ahora</h2><div class="card"><ul>${items.join('')}</ul></div>`;
  }

  function pageInicio(data) {
    const project = (data.avance || {}).proyecto || {};
    const fases = list((data.avance || {}).fases);
    const runs = list(data.corridas);
    const trained = new Set(list(data.metricas_modelos).map((m) => m.entrenamiento_id)).size;
    const evidence = data.evidencia;
    const phase = (f) => `<li><b>${esc(f.id)}</b><span>${pill(f.estado)}</span><span>${esc(f.titulo)}${f.sirve_para ? `<br><small>${esc(f.sirve_para)}</small>` : ''}${f.fecha ? ` <small>· ${esc(f.fecha)}</small>` : ''}</span></li>`;
    const done = fases.filter((f) => f.estado === 'hecho');
    const open = fases.filter((f) => f.estado !== 'hecho');
    return head(project.titulo || 'Panel de resultados', project.objetivo || 'Resultados y datos de entrada del estimador.')
      + syntheticNotice(data)
      + `<div class="grid cols-4">${metric('Simulaciones en la base', int(runs.length), 'corridas', 'SUMO, con métricas calculadas')}${metric('Planes de semáforo probados', int(list(data.planes).length), 'planes', 'Incluye el plan actual')}${metric('Escenarios de demanda', int(list(data.escenarios).length), '', 'Visibles en esta foto')}${metric('Modelos entrenados', int(trained), '', trained ? 'Ver Entrenamiento' : 'El entrenamiento aún no empieza')}</div>`
      + findings(data)
      + (project.alcance ? `<h2 class="sec">Qué se investiga</h2><div class="card"><p>${esc(project.alcance)}</p></div>` : '')
      + `<h2 class="sec">Avance del proyecto</h2><p class="cap">Cada fase hecha tiene su acta en el repositorio. Las pendientes producirán las cifras que hoy aparecen vacías.</p><details><summary>${esc(done.length)} fases hechas</summary><ul class="fases">${done.map(phase).join('')}</ul></details><ul class="fases">${open.map(phase).join('')}</ul>`
      + `<h2 class="sec">Estado de la evidencia</h2><div class="card"><p>${evidence ? `Última comprobación: ${date(evidence.fecha)}, ${pill(evidence.estado)}${evidence.de_esta_base ? '' : ' <b>Es de otra versión de la base.</b>'}. Ver la página Evidencia.` : 'Todavía no hay evidencia publicada para esta base.'}</p></div>`;
  }

  function pageCaso(data) {
    const casos = list(data.casos);
    if (!casos.length) return head('Caso', 'El cruce que se estudia.') + empty('Sin caso', 'La base no tiene ningún caso cargado.');
    return head('Caso', 'El cruce que se estudia: sus movimientos, los tramos del semáforo y el plan que tiene hoy.')
      + casos.map((caso) => {
        const sameCase = (r) => r.caso_id === caso.caso_id && r.caso_version === caso.caso_version;
        const movimientos = list(data.movimientos).filter(sameCase);
        const tramos = list(data.tramos).filter(sameCase);
        const plan = list(data.planes).find((p) => sameCase(p) && p.es_plan_observado);
        const limits = list(caso.evidencia_restricciones);
        return dl([
          ['Caso', `<span class="id">${esc(caso.caso_id)}</span> versión ${esc(caso.caso_version)}`],
          ['Descripción', esc(caso.descripcion)],
          ['Origen de la red', esc(word(caso.origen))],
          ['Representación', pill(caso.estado_representacion)],
          ['Ciclo permitido', `${num(caso.ciclo_min_s, 0)} a ${num(caso.ciclo_max_s, 0)} s`],
          ['Clases de vehículo', esc(list(caso.clases).join(', '))],
          ['Archivo', `${fileLink(data, 'datos', caso.archivo)}<br><span class="id">${esc(caso.archivo_sha256)}</span>`],
          ['Red de SUMO', `<span class="id">${esc(caso.red_ruta)}</span><br><span class="id">${esc(caso.red_sha256)}</span>`]
        ])
        + (limits.length ? `<h2 class="sec">Límites de lo que se modeló</h2><div class="card"><ul>${limits.map((l) => `<li>${esc(l)}</li>`).join('')}</ul></div>` : '')
        + '<h2 class="sec">Plan actual y tramos del semáforo</h2>'
        + (plan
          ? `<p class="cap">Plan observado: ciclo de ${num(plan.ciclo_s, 0)} s. Fuente: ${esc(plan.fuente_observada)}. Variación durante el día: ${esc(plan.variacion_horaria)}. Confirmado por: ${esc(plan.confirmado_por)}.</p>`
          : '<p class="cap">Este caso no tiene plan observado.</p>')
        + table([
          ['Tramo', (t) => esc(t.tramo_id)],
          ['Tipo', (t) => esc(word(t.tipo))],
          ['Plan actual (s)', (t) => num(plan && plan.duraciones_s ? plan.duraciones_s[t.tramo_id] : null, 0), true],
          ['Mínimo (s)', (t) => num(t.minimo_s, 0), true],
          ['Máximo (s)', (t) => num(t.maximo_s, 0), true],
          ['Grupos de verde', (t) => esc(list(t.grupos).map((g) => `${g.grupo_id} (${num(g.minimo_s, 0)} a ${num(g.maximo_s, 0)} s)`).join(', ') || '—')]
        ], tramos)
        + `<h2 class="sec">Movimientos <small>(${esc(movimientos.length)})</small></h2>`
        + table([
          ['Movimiento', (m) => esc(m.movimiento_id)],
          ['Acceso', (m) => accessName(data, m.acceso)],
          ['Carriles de entrada', (m) => `<span class="id">${esc(list(m.carriles_entrada).join(', '))}</span>`],
          ['Flujo mínimo (veh/h)', (m) => num(m.flujo_min_vph, 0), true],
          ['Flujo máximo (veh/h)', (m) => num(m.flujo_max_vph, 0), true]
        ], movimientos);
      }).join('');
  }

  function pageEscenarios(data) {
    const zones = byKey(data.zonas, 'escenario_id');
    const demand = byKey(data.demanda, 'escenario_id');
    const scenarios = list(data.escenarios);
    const movements = new Map(list(data.movimientos).map((m) => [m.movimiento_id, m]));
    const blocks = scenarios.map((e) => {
      const rows = demand.get(e.escenario_id) || [];
      const totals = new Map();
      rows.forEach((d) => totals.set(d.movimiento_id, (totals.get(d.movimiento_id) || 0) + d.flujo_vph * d.proporcion));
      const total = [...totals.values()].reduce((a, b) => a + b, 0);
      const byAccess = new Map();
      totals.forEach((v, m) => { const a = (movements.get(m) || {}).acceso || '—'; byAccess.set(a, (byAccess.get(a) || 0) + v); });
      const classes = [...new Set(rows.map((d) => d.clase_id))];
      const zone = (zones.get(e.escenario_id) || [])[0] || {};
      const pivot = [...totals.keys()].map((m) => ({ movimiento_id: m, total: totals.get(m), acceso: (movements.get(m) || {}).acceso, filas: rows.filter((d) => d.movimiento_id === m) }));
      return `<h2 class="sec"><span class="id">${esc(e.escenario_id)}</span> ${e.preliminar ? pill('draft', 'Preliminar') : ''} ${pill(e.origen === 'synthetic' ? 'draft' : '', word(e.origen))}</h2>`
        + (e.preliminar ? notice('<b>Preliminar:</b> este escenario se escribió a mano y no pertenece a ninguna partición. Sirve para desarrollar; nunca entrará a la prueba final.', true) : '')
        + `<div class="grid cols-3">${metric('Demanda total', int(total), 'veh/h', e.origen === 'synthetic' ? 'Supuesta, no medida' : 'Medida')}${metric('Medición', num(e.medicion_s / 60, 0), 'min', `Calentamiento ${num(e.calentamiento_s / 60, 0)} min; vaciado hasta ${num(e.vaciado_max_s / 60, 0)} min`)}${metric('Zona', word(zone.zona), '', zone.particion_id ? `Partición ${zone.particion_id}` : 'Sin partición')}</div>`
        + dl([
          ['Observación', `${date(e.inicio_observacion)} a ${date(e.fin_observacion)}`],
          ['Fuentes', esc(list(e.fuentes).join(', '))],
          ['Frontera', esc(e.politica_frontera)],
          ['Semilla de demanda', esc(e.semilla_demanda)],
          ['Archivo', `${fileLink(data, 'datos', e.archivo)}<br><span class="id">${esc(e.archivo_sha256)}</span>`]
        ])
        + '<h3 class="sub">Demanda por acceso</h3>'
        + table([['Acceso', (r) => accessName(data, r[0])], ['Veh/h', (r) => int(r[1]), true], ['Parte del total', (r) => `${num(total ? (100 * r[1]) / total : null, 1)} %`, true]], [...byAccess.entries()])
        + `<details><summary>Demanda por movimiento y clase (${esc(pivot.length)} movimientos)</summary>`
        + table([
          ['Movimiento', (p) => esc(p.movimiento_id)],
          ['Acceso', (p) => accessName(data, p.acceso || '—')],
          ['Total (veh/h)', (p) => num(p.total, 0), true],
          ...classes.map((c) => [`${c} (veh/h)`, (p) => { const row = p.filas.find((f) => f.clase_id === c); return row ? num(row.flujo_vph * row.proporcion, 1) : '—'; }, true])
        ], pivot)
        + '</details>';
    }).join('');
    const protocols = table([
      ['Protocolo', (p) => `<span class="id">${esc(p.protocolo_id)}</span>`],
      ['Estado', (p) => pill(p.estado)],
      ['Umbral de cola (m/s)', (p) => num(p.umbral_cola_mps, 2), true],
      ['Muestreo (s)', (p) => num(p.muestreo_cola_s, 0), true],
      ['Carriles medidos', (p) => int(list(p.carriles_zona).length), true],
      ['Presupuesto', (p) => int(p.presupuesto_busqueda), true],
      ['Semillas de búsqueda', (p) => esc(list(p.semillas_busqueda).join(', ') || '—')],
      ['Semillas de finalistas', (p) => esc(list(p.semillas_finalistas).join(', ') || '—')]
    ], list(data.protocolos));
    const definitions = list(data.protocolos).map((p) => `<details><summary><span class="id">${esc(p.protocolo_id)}</span>: definición completa</summary><div class="card"><p>${esc(p.definicion_metrica)}</p></div></details>`).join('');
    return head('Escenarios y protocolo', 'Los datos de entrada: qué vehículos entran a la simulación y con qué reglas se mide.')
      + (scenarios.length ? blocks : empty('Sin escenarios', 'No hay escenarios visibles en esta foto.'))
      + '<h2 class="sec">Protocolos de medición</h2><p class="cap">El protocolo fija cómo se mide. Dos protocolos con distintos carriles dan colas distintas: por eso las series no se mezclan. Las semillas de la prueba final están reservadas y no aparecen.</p>'
      + protocols + definitions;
  }

  function seriesLabel(s) { return `${word(s.etapa)}${s.protocolo ? ` · ${s.protocolo}` : ''}`; }

  function runDetail(data, id) {
    const run = runOf(data, id);
    if (!run) return '';
    const accesses = list(data.accesos).filter((a) => a.run_id === id);
    const moves = list(data.resultados_movimiento).filter((m) => m.run_id === id);
    const queue = (data.cola || {})[id];
    let chart = '<p class="cap">Esta corrida no tiene serie de cola.</p>';
    if (queue) {
      const names = Object.keys(queue.accesos).sort();
      const total = queue.desde_s.map((_, i) => names.reduce((sum, a) => sum + (queue.accesos[a][i] || 0), 0));
      chart = lineChart(queue.desde_s, queue.en_ventana, [{ label: 'Cola total de la zona (veh)', values: total }], `Cola total de la corrida ${id}`)
        + `<details><summary>Cola por acceso, cada ${esc(data.cola_intervalo_s)} s</summary>`
        + table([
          ['Desde (min)', (i) => num(queue.desde_s[i] / 60, 0), true],
          ['Total', (i) => num(total[i], 1), true],
          ...names.map((a) => [(((data.avance || {}).accesos || {})[a]) || a, (i) => num(queue.accesos[a][i], 1), true])
        ], queue.desde_s.map((_, i) => i)) + '</details>';
    }
    return `<div class="detalle" id="detalle"><h2 class="sec">Corrida <span class="id">${esc(id)}</span></h2>`
      + dl([
        ['Etapa', esc(word(run.etapa))],
        ['Estado', pill(run.estado)],
        ['Semilla', esc(run.semilla_sumo)],
        ['Plan', run.plan_id ? `<span class="id">${esc(run.plan_id)}</span> (ciclo ${num(run.ciclo_s, 0)} s)` : '—'],
        ['Protocolo de medición', `<span class="id">${esc(run.protocolo_metricas_id || '—')}</span>`],
        ['Demora media', `${num(run.demora_media_s)} s/veh, ${pill(run.estado_demora)}${run.cota_inf_demora_s != null ? ` (mínimo ${num(run.cota_inf_demora_s)} s/veh)` : ''}`],
        ['Cola media y máxima', `${num(run.cola_media_veh)} y ${int(run.cola_maxima_veh)} veh, ${pill(run.estado_cola)}`],
        ['Detenciones por vehículo', `${num(run.detenciones_media, 2)}, ${pill(run.estado_detenciones)}`],
        ['Cohorte', `${int(run.cohorte_solicitada)} pedidos, ${int(run.cohorte_terminada)} terminaron, ${int(run.cohorte_sin_terminar)} sin terminar, ${int(run.cohorte_no_insertada)} no entraron`],
        ['Teletransportes y choques', `${int(run.teletransportes_total)} y ${int(run.choques)}`],
        ['SUMO y commit', `${esc(run.version_sumo || '—')}, <span class="id">${esc(run.commit_codigo || 'sin commit')}</span>`],
        ['Manifiesto', `${fileLink(data, 'datos', run.manifiesto)}<br><span class="id">${esc(run.manifiesto_sha256)}</span>`],
        ['Métricas', `${fileLink(data, 'datos', run.metricas)}<br><span class="id">${esc(run.metricas_sha256 || '—')}</span>`]
      ])
      + '<h3 class="sub">Cola en el tiempo</h3>' + chart
      + '<h3 class="sub">Por acceso</h3>'
      + table([
        ['Acceso', (a) => accessName(data, a.acceso)],
        ['Cohorte', (a) => (a.con_cohorte ? 'Sí' : pill('draft', 'Sin cohorte'))],
        ['Demora (s/veh)', (a) => num(a.demora_media_s), true],
        ['Cola media (veh)', (a) => num(a.cola_media_veh), true],
        ['Cola máx. (veh)', (a) => int(a.cola_maxima_veh), true],
        ['Detenciones/veh', (a) => num(a.detenciones_media, 2), true],
        ['Terminaron', (a) => int(a.terminados), true]
      ], accesses)
      + `<details><summary>Por movimiento (${esc(moves.length)})</summary>`
      + table([
        ['Movimiento', (m) => esc(m.movimiento_id)],
        ['Pedidos', (m) => int(m.solicitados), true],
        ['Terminaron', (m) => int(m.terminados), true],
        ['Demora (s/veh)', (m) => num(m.demora_media_s), true],
        ['Estado', (m) => pill(m.estado_demora)]
      ], moves) + '</details></div>';
  }

  function pageSimulaciones(data, state) {
    const series = list(data.series);
    const selected = series.find((s) => s.id === state.serie);
    const runs = list(data.corridas).filter((r) => !selected
      || (r.etapa === selected.etapa && (r.protocolo_metricas_id || r.protocolo_id || '') === (selected.protocolo || '')));
    const options = ['<option value="">Todas las series</option>'].concat(series.map((s) => `<option value="${esc(s.id)}"${s.id === state.serie ? ' selected' : ''}>${esc(seriesLabel(s))} (${esc(s.corridas)})</option>`));
    return head('Simulaciones', 'Todas las corridas de SUMO que están en la base, separadas por serie. Cada serie usa una sola forma de medir.')
      + syntheticNotice(data)
      + table([
        ['Serie', (s) => esc(word(s.etapa))],
        ['Protocolo', (s) => `<span class="id">${esc(s.protocolo || '—')}</span>`],
        ['Corridas', (s) => int(s.corridas), true],
        ['Planes', (s) => int(s.planes), true],
        ['Semillas', (s) => int(list(s.semillas).length), true],
        ['Con demora completa', (s) => int(s.demora_completa), true],
        ['Con teletransportes', (s) => int(s.con_teletransportes), true],
        ['Con choques', (s) => int(s.con_choques), true],
        ['Demora mín.–máx. (s/veh)', (s) => `${num(s.demora.minimo)} – ${num(s.demora.maximo)}`, true]
      ], series)
      + `<h2 class="sec">Corridas <small>(${esc(runs.length)})</small></h2><div class="controls"><label>Serie <select data-filtro="serie">${options.join('')}</select></label></div>`
      + table([
        ['Corrida', (r) => `<button type="button" class="link-btn corto" data-run="${esc(r.run_id)}">${short(String(r.run_id).split('_').pop())}</button>`],
        ['Etapa', (r) => esc(word(r.etapa))],
        ['Semilla', (r) => esc(r.semilla_sumo), true],
        ['Ciclo (s)', (r) => num(r.ciclo_s, 0), true],
        ['Estado', (r) => pill(r.estado)],
        ['Demora (s/veh)', (r) => num(r.demora_media_s), true],
        ['Estado demora', (r) => pill(r.estado_demora)],
        ['Cola media (veh)', (r) => num(r.cola_media_veh), true],
        ['Detenciones/veh', (r) => num(r.detenciones_media, 2), true],
        ['Teletr.', (r) => int(r.teletransportes_total), true],
        ['Choques', (r) => int(r.choques), true]
      ], runs, { rowClass: (r) => (r.run_id === state.run ? 'ref' : '') })
      + (state.run ? runDetail(data, state.run) : '<p class="cap">Elija una corrida para ver su cola en el tiempo, sus accesos, sus movimientos y de dónde sale.</p>');
  }

  function greensSection(data, comparison) {
    const tramos = list(data.tramos).filter((t) => t.caso_id === (observed(data) || {}).caso_id);
    const current = planOf(data, comparison.plan_observado_id);
    const finalists = list(comparison.finalistas).map((f) => planOf(data, f.plan_id)).filter(Boolean);
    const paired = list(comparison.emparejada).map((p) => planOf(data, p.plan_id)).filter(Boolean);
    const rows = [current, ...finalists].filter(Boolean).map((p) => ({ label: p === current ? `Plan actual · ${num(p.ciclo_s, 0)} s` : planLabel(p), parts: p.duraciones_s, total: p.ciclo_s }));
    const variable = tramos.filter((t) => t.tipo === 'variable');
    const all = [current, ...paired].filter(Boolean);
    return '<h2 class="sec">1. Los tiempos del semáforo</h2><p class="cap">Cada barra es un ciclo completo; cada color, un tramo. Los números son los segundos de verde que se pueden ajustar; los tramos sin número son fijos (ámbar y todo rojo). Los límites de cada tramo están en la página Caso.</p>'
      + stackBars(rows, tramos, 'Duración de los tramos del plan actual y de los finalistas')
      + `<details><summary>Verdes de los ${esc(all.length)} planes probados</summary>`
      + table([
        ['Plan', (p) => (p === current ? '<b>Plan actual</b>' : `<span class="corto">${short(p.plan_id)}</span>`)],
        ['Ciclo (s)', (p) => num(p.ciclo_s, 0), true],
        ...variable.map((t) => [`${t.tramo_id} (s)`, (p) => num(p.duraciones_s[t.tramo_id], 0), true])
      ], all, { rowClass: (p) => (p === current ? 'ref' : '') }) + '</details>';
  }

  const eligibleFirst = (plans) => [...plans].sort((a, b) => Number(Boolean(b.elegible)) - Number(Boolean(a.elegible)));

  function pairedSection(comparison) {
    const plans = eligibleFirst(list(comparison.emparejada));
    const usable = plans.filter((p) => p.pares_validos > 0);
    const chart = usable.length
      ? divergingBars(usable.map((p) => ({ label: `${String(p.plan_id).slice(0, 8)} · ${p.elegible ? 'elegible' : 'no elegible'} · ${p.pares_validos} ${p.pares_validos === 1 ? 'par' : 'pares'}`, v: p.diferencia_valida.media, title: planLabel(p) })), 's/veh', 'Diferencia de demora de cada plan frente al plan actual, con la misma semilla')
      : notice('Ningún plan tiene pares válidos con el plan actual.', true);
    const detail = plans.map((p) => `<details><summary><span class="corto">${short(p.plan_id)}</span>: semilla por semilla</summary>`
      + table([
        ['Semilla', (s) => esc(s.semilla), true],
        ['Demora del plan (s/veh)', (s) => num(s.demora_s), true],
        ['Demora del plan actual (s/veh)', (s) => num(s.demora_actual_s), true],
        ['Diferencia (s/veh)', (s) => `<span class="${s.diferencia_s < 0 ? 'menos' : 'mas'}">${signed(s.diferencia_s)}</span>`, true],
        ['¿Par válido?', (s) => (s.valida ? 'Sí' : pill('draft', 'No'))],
        ['Incidentes del plan', (s) => esc(list(s.problemas).map(word).join(', ') || 'ninguno')],
        ['Incidentes del plan actual', (s) => esc(list(s.problemas_actual).map(word).join(', ') || 'ninguno')]
      ], list(p.por_semilla)) + '</details>').join('');
    return `<h2 class="sec">2. Con las mismas semillas: búsqueda (${esc(list(comparison.semillas_busqueda).join(', '))})</h2>`
      + `<p class="cap">Aquí sí se puede restar: mismo escenario, misma demanda, misma semilla. Un <b>par válido</b> no tiene incidentes en ninguno de los dos planes. Son pocas semillas: muestra una tendencia, no una conclusión.${comparison.plan_observado_elegible === false ? ` El plan actual no fue elegible (${problems(comparison.plan_observado_problemas)}), así que algunas de sus semillas no sirven de comparación.` : ''}</p>`
      + chart
      + table([
        ['Plan', (p) => `<span class="corto">${short(p.plan_id)}</span>`],
        ['Ciclo (s)', (p) => num(p.ciclo_s, 0), true],
        ['¿Elegible?', (p) => (p.elegible ? pill('ok', 'Sí') : pill('draft', 'No'))],
        ['Pares válidos', (p) => int(p.pares_validos), true],
        ['Diferencia media (s/veh)', (p) => `<span class="${p.diferencia_valida.media < 0 ? 'menos' : 'mas'}">${signed(p.diferencia_valida.media)}</span>`, true],
        ['Diferencia (%)', (p) => signed(p.diferencia_valida_pct, 0), true],
        ['Rango (s/veh)', (p) => (p.diferencia_valida.n ? `${signed(p.diferencia_valida.minimo)} a ${signed(p.diferencia_valida.maximo)}` : '—'), true],
        ['Pares medidos', (p) => int(p.pares_medidos), true],
        ['Motivos', (p) => problems(p.problemas)]
      ], plans)
      + `<details><summary>Detalle semilla por semilla de cada plan</summary>${detail}</details>`;
  }

  function finalistsSection(comparison) {
    const base = comparison.plan_observado_finalistas || comparison.plan_observado_diagnostico;
    const dots = (group) => list(group.por_semilla).map((s) => ({ v: s.demora_media_s, bad: Boolean(s.teletransportes || s.choques), title: `Semilla ${s.semilla}: ${num(s.demora_media_s)} s/veh` }));
    const rows = [{ label: 'Plan actual (mismas semillas)', dots: dots(base) }, ...list(comparison.finalistas).map((f) => ({ label: planLabel(f), dots: dots(f.grupo) }))];
    const statRow = (name, group, extra) => ({ name, group, extra });
    const stats = [statRow('Plan actual (mismas semillas)', base, null), ...list(comparison.finalistas).map((f) => statRow(planLabel(f), f.grupo, f))];
    const pairs = list(comparison.finalistas).map((f) => ({ f, p: f.pares_con_plan_actual })).filter((x) => x.p);
    const pairSummary = pairs.length ? '<h3 class="sub">Diferencia con el plan actual, semilla por semilla</h3><p class="cap">Solo cuentan las semillas en que ambos planes llegaron sin atascos ni choques, con demora medida. Negativo = menos espera que el plan actual.</p>'
      + table([
        ['Plan', (x) => `<span class="id">${esc(x.f.plan_id.slice(0, 8))}</span> · ciclo ${num(x.f.ciclo_s, 0)} s`],
        ['Pares válidos', (x) => int(x.p.pares_validos), true],
        ['Diferencia media (s/veh)', (x) => `<span class="${x.p.diferencia_valida.media < 0 ? 'menos' : 'mas'}">${signed(x.p.diferencia_valida.media)}</span>`, true],
        ['Semillas', (x) => esc(x.p.por_semilla.filter((s) => s.valida).map((s) => s.semilla).join(', ') || '—')]
      ], pairs)
      + pairs.map((x) => `<details><summary><span class="id">${esc(x.f.plan_id.slice(0, 8))}</span>: semilla por semilla</summary>`
        + table([
          ['Semilla', (s) => esc(s.semilla), true],
          ['Demora del finalista (s/veh)', (s) => num(s.demora_s), true],
          ['Demora del plan actual (s/veh)', (s) => num(s.demora_actual_s), true],
          ['Diferencia (s/veh)', (s) => `<span class="${s.diferencia_s < 0 ? 'menos' : 'mas'}">${signed(s.diferencia_s)}</span>`, true],
          ['¿Par válido?', (s) => (s.valida ? 'Sí' : pill('draft', 'No'))]
        ], x.p.por_semilla) + '</details>').join('') : '';
    if (!list(comparison.finalistas).length) return '';
    return '<h2 class="sec">3. Más semillas: finalistas y plan actual</h2>'
      + (comparison.finalistas_con_mismas_semillas ? '' : notice(`<b>No es una comparación emparejada.</b> Los finalistas corrieron con las semillas ${esc(list(comparison.semillas_finalistas).join(', '))}; el plan actual, con otras (${esc(list(base.por_semilla).map((s) => s.semilla).join(', '))}). Se pueden mirar lado a lado, pero no restar. Para compararlos de verdad hay que simular el plan actual con las semillas de los finalistas.`, true))
      + stripPlot(rows, 's/veh', 'Demora por semilla del plan actual y de cada finalista')
      + pairSummary
      + table([
        ['Plan', (r) => esc(r.name)],
        ['Semillas', (r) => int(r.group.corridas), true],
        ['Con incidentes', (r) => int(r.group.con_incidentes), true],
        ['Sin demora completa', (r) => int(r.group.sin_demora), true],
        ['Mediana (s/veh)', (r) => num(r.group.demora.mediana), true],
        ['Media (s/veh)', (r) => num(r.group.demora.media), true],
        ['Mín.–máx. (s/veh)', (r) => `${num(r.group.demora.minimo)} – ${num(r.group.demora.maximo)}`, true],
        ['Media sin incidentes (s/veh)', (r) => num(r.group.demora_sin_incidentes.media), true],
        ['¿Elegible?', (r) => (r.extra ? (r.extra.elegible ? pill('ok', 'Sí') : pill('draft', 'No')) : '—')],
        ['Motivos', (r) => (r.extra ? problems(r.extra.problemas) : '—')]
      ], stats, { rowClass: (r) => (r.extra ? '' : 'ref') });
  }

  function accessSection(data, comparison, state) {
    const plans = eligibleFirst(list(comparison.emparejada)).filter((p) => p.pares_medidos > 0);
    if (!plans.length) return '';
    const plan = plans.find((p) => p.plan_id === state.planAcceso) || plans[0];
    const seeds = list(plan.por_semilla).filter((s) => s.run_id && s.run_id_actual);
    const seed = seeds.find((s) => String(s.semilla) === String(state.semillaAcceso)) || seeds.find((s) => s.valida) || seeds[0];
    if (!seed) return '';
    const mine = list(data.accesos).filter((a) => a.run_id === seed.run_id);
    const theirs = new Map(list(data.accesos).filter((a) => a.run_id === seed.run_id_actual).map((a) => [a.acceso, a]));
    return '<h2 class="sec">4. Por acceso</h2><p class="cap">Dónde gana y dónde pierde cada plan, con la misma semilla. Un acceso sin cohorte tiene cola pero no demora: ningún vehículo de los estudiados pasa por él.</p>'
      + `<div class="controls"><label>Plan <select data-filtro="planAcceso">${plans.map((p) => `<option value="${esc(p.plan_id)}"${p === plan ? ' selected' : ''}>${esc(planLabel(p))}</option>`).join('')}</select></label>`
      + `<label>Semilla <select data-filtro="semillaAcceso">${seeds.map((s) => `<option value="${esc(s.semilla)}"${s === seed ? ' selected' : ''}>${esc(s.semilla)}${s.valida ? '' : ' (con incidentes)'}</option>`).join('')}</select></label></div>`
      + table([
        ['Acceso', (a) => accessName(data, a.acceso)],
        ['Cohorte', (a) => (a.con_cohorte ? 'Sí' : pill('draft', 'Sin cohorte'))],
        ['Demora del plan (s/veh)', (a) => num(a.demora_media_s), true],
        ['Demora plan actual (s/veh)', (a) => num((theirs.get(a.acceso) || {}).demora_media_s), true],
        ['Diferencia (s/veh)', (a) => { const o = theirs.get(a.acceso) || {}; const d = (a.demora_media_s != null && o.demora_media_s != null) ? a.demora_media_s - o.demora_media_s : null; return `<span class="${d < 0 ? 'menos' : 'mas'}">${signed(d)}</span>`; }, true],
        ['Cola del plan (veh)', (a) => num(a.cola_media_veh), true],
        ['Cola plan actual (veh)', (a) => num((theirs.get(a.acceso) || {}).cola_media_veh), true]
      ], mine);
  }

  function pageComparacion(data, state) {
    const comparisons = list(data.comparaciones);
    if (!comparisons.length) return head('Comparación con el plan actual', 'Cómo cambia la demora al cambiar los tiempos del semáforo.') + empty('Sin comparación', 'Hace falta un plan observado y una búsqueda.');
    return head('Comparación con el plan actual', '¿Qué pasa con la espera de los vehículos si se cambian los tiempos del semáforo?')
      + syntheticNotice(data)
      + notice('<b>Cómo leer esta página:</b> son diferencias observadas en simulación, sin prueba estadística. La comparación que decide la tesis es la evaluación final, que todavía no se hace.')
      + comparisons.map((c) => greensSection(data, c) + pairedSection(c) + finalistsSection(c) + accessSection(data, c, state)).join('');
  }

  function pageBusqueda(data) {
    const searches = list(data.busquedas);
    if (!searches.length) return head('Búsqueda', 'La búsqueda de un buen plan por simulación.') + empty('Sin búsquedas', 'Todavía no hay búsquedas en la base.');
    return head('Búsqueda', 'Para cada escenario se prueban muchos planes en SUMO y se elige uno de referencia, que después sirve para entrenar el modelo.')
      + searches.map((b) => {
        const candidates = list(data.candidatos).filter((c) => c.busqueda_id === b.busqueda_id);
        const reasons = (b.motivos_descarte || {}).search || {};
        const inel = reasons.ineligible || {};
        return `<h2 class="sec"><span class="id">${esc(b.busqueda_id)}</span></h2>`
          + `<div class="grid cols-4">${metric('Planes evaluados', int(b.candidatos), '', `Presupuesto ${int(b.presupuesto)}`)}${metric('Elegibles en la búsqueda', int(b.elegibles_busqueda), '', '')}${metric('Elegibles entre finalistas', int(b.elegibles_finalistas), '', `De ${int(b.finalistas)} finalistas`)}${metric('Simulaciones', int(b.simulaciones), 'corridas', '')}</div>`
          + notice(`<b>Resultado:</b> ${esc(word(b.estado_seleccion))}${b.motivo_sin_referencia ? `: ${esc(word(b.motivo_sin_referencia))}` : ''}.${b.plan_ganador_id ? ` Plan elegido: <span class="id">${esc(b.plan_ganador_id)}</span>.` : ''}`, b.estado_seleccion === 'no_reference')
          + (Object.keys(inel).length ? `<p class="cap">Motivos de descarte en la búsqueda: ${problems(inel)}. Un plan puede tener varios.</p>` : '')
          + table([
            ['Plan', (c) => `<span class="corto">${short(c.plan_id)}</span>`],
            ['Origen', (c) => esc(word(c.origen))],
            ['Ciclo (s)', (c) => num(c.ciclo_s, 0), true],
            ['¿Elegible?', (c) => (c.elegible_busqueda ? pill('ok', 'Sí') : pill('draft', 'No'))],
            ['Puesto', (c) => int(c.posicion_busqueda), true],
            ['Puntaje: demora (s/veh)', (c) => num(c.puntaje_busqueda_s), true],
            ['Cola (veh)', (c) => num(c.cola_media_busqueda_veh), true],
            ['Motivos', (c) => problems(c.problemas_busqueda)],
            ['¿Finalista?', (c) => yes(c.finalista)],
            ['¿Elegible final?', (c) => yes(c.elegible_finalistas)],
            ['Motivos en finalistas', (c) => (c.finalista ? problems(c.problemas_finalistas) : '—')]
          ], candidates, { rowClass: (c) => (c.origen === 'current_plan' ? 'ref' : '') });
      }).join('')
      + '<h2 class="sec">Comparadores</h2><p class="cap">Webster es la fórmula clásica para calcular tiempos de semáforo. Se usa solo cuando sus supuestos se cumplen.</p>'
      + table([
        ['Escenario', (k) => `<span class="id">${esc(k.escenario_id)}</span>`],
        ['Webster', (k) => pill(k.webster_estado === 'not_applicable' ? 'draft' : '', word(k.webster_estado))],
        ['Ciclo calculado (s)', (k) => num(k.webster_ciclo_s, 1), true],
        ['Y crítico', (k) => num(k.y_critico, 3), true],
        ['Saturación (veh/h/carril)', (k) => num(k.saturacion_vph_carril, 0), true],
        ['¿Provisional?', (k) => yes(k.provisional)],
        ['Motivo', (k) => esc(list(k.webster_problemas).map((p) => p.message).join('; ') || '—')]
      ], list(data.comparadores));
  }

  function pageEntrenamiento(data) {
    const metrics = list(data.metricas_modelos);
    const labels = list(data.etiquetas);
    const intro = head('Entrenamiento', 'Cómo aprende el modelo a proponer tiempos, y cómo cambian sus versiones.');
    if (!metrics.length && !labels.length) {
      return intro + empty('Todavía no hay modelos entrenados', 'El entrenamiento empieza cuando exista el corpus de escenarios sintéticos con sus etiquetas. Aquí aparecerán las etiquetas usadas, la comparación entre la mediana y XGBoost, y el error en entrenamiento y validación.');
    }
    return intro
      + `<h2 class="sec">Etiquetas de entrenamiento <small>(${esc(labels.length)})</small></h2>`
      + (labels.length ? table([
        ['Etiqueta', (e) => `<span class="id">${esc(e.etiqueta_id)}</span>`],
        ['Escenario', (e) => `<span class="id">${esc(e.escenario_id)}</span>`],
        ['Partición', (e) => esc(e.particion_id)],
        ['Uso', (e) => esc(word(e.asignacion))],
        ['Plan', (e) => `<span class="corto">${short(e.plan_id)}</span>`]
      ], labels) : '<p class="cap">Sin etiquetas con referencia.</p>')
      + `<h2 class="sec">Métricas de los modelos <small>(${esc(metrics.length)})</small></h2>`
      + (metrics.length ? table([
        ['Entrenamiento', (m) => `<span class="id">${esc(m.entrenamiento_id)}</span>`],
        ['Algoritmo', (m) => esc(m.algoritmo)],
        ['Métrica', (m) => esc(m.metrica)],
        ['Alcance', (m) => esc(m.alcance)],
        ['Unidad', (m) => esc(m.unidad)],
        ['Entrenamiento', (m) => num(m.valor_entrenamiento, 3), true],
        ['Validación', (m) => num(m.valor_validacion, 3), true]
      ], metrics) : '<p class="cap">Sin métricas todavía.</p>');
  }

  function pageConsultas(data) {
    const queries = list(data.consultas);
    const intro = head('Consultas', 'Qué propone el modelo cuando se le pregunta, qué corrigen las reglas y cuánto tarda.');
    if (!queries.length) return intro + empty('Todavía no hay consultas', 'Aparecerán cuando exista un modelo empaquetado: la entrada, la propuesta original, las reglas aplicadas y el tiempo de cálculo.');
    return intro + table([
      ['Consulta', (q) => `<span class="id">${esc(q.request_id)}</span>`],
      ['Modelo', (q) => `<span class="id">${esc(q.modelo_id || '—')}</span>`],
      ['Escenario', (q) => `<span class="id">${esc(q.escenario_id || '—')}</span>`],
      ['Estado', (q) => esc(word(q.estado))],
      ['Plan', (q) => `<span class="corto">${short(q.plan_id)}</span>`],
      ['Reglas incumplidas', (q) => int(q.reglas_incumplidas), true],
      ['Códigos', (q) => esc(list(q.codigos).join(', ') || '—')]
    ], queries);
  }

  function hitosTable(hitos) {
    return `<h2 class="sec">Hitos del procedimiento <small>(${esc(hitos.length)})</small></h2><p class="cap">La prueba final solo se abre después de congelar, en este orden, el protocolo, la partición y el modelo. Cada hito tiene su acta.</p>`
      + (hitos.length ? table([
        ['Hito', (h) => esc(word(h.tipo))],
        ['Fecha', (h) => date(h.registrado_en)],
        ['Objeto', (h) => `<span class="id">${esc(h.protocolo_id || h.particion_id || h.modelo_id || h.experimento_id || '—')}</span>`],
        ['Responsable', (h) => esc(h.responsable)],
        ['Acta', (h) => `<span class="id">${esc(h.acta)}</span>`]
      ], hitos) : '<div class="card"><p>Todavía no se ha congelado nada.</p></div>');
  }

  function pageEvaluacion(data) {
    const indicators = list(data.indicadores);
    const hitos = list(data.hitos);
    const intro = head('Evaluación final', 'La comparación que decide la tesis: el modelo frente al plan actual, Webster y la búsqueda de referencia.');
    if (!indicators.length) {
      return intro + empty('Reservada: sin resultados visibles', 'La prueba final se abre una sola vez, con un acta, cuando el modelo ya esté congelado. Hasta entonces esta página no muestra ninguna cifra, plan ni corrida de esa prueba. La propia base de datos se lo impide al panel.', 'reservada') + hitosTable(hitos);
    }
    return intro + table([
      ['Indicador', (i) => esc(i.indicador)],
      ['Métrica', (i) => esc(i.metrica)],
      ['Comparación', (i) => esc(`${i.alternativa_a || ''} frente a ${i.alternativa_b || ''}`)],
      ['Alcance', (i) => esc(i.alcance)],
      ['Valor', (i) => num(i.valor, 3), true],
      ['Unidad', (i) => esc(i.unidad)],
      ['Intervalo', (i) => (i.ic_inferior != null ? `${num(i.ic_inferior, 3)} a ${num(i.ic_superior, 3)} (${num(100 * i.ic_nivel, 0)} %)` : '—'), true],
      ['n', (i) => int(i.denominador), true],
      ['Faltantes', (i) => int(i.faltantes), true]
    ], indicators) + hitosTable(hitos);
  }

  function pageEvidencia(data) {
    const base = data.base || {};
    const evidence = data.evidencia;
    const runs = list(data.corridas);
    const accesses = list(data.accesos);
    const noCohort = accesses.filter((a) => !a.con_cohorte);
    const noDelay = runs.filter((r) => r.demora_media_s == null);
    const noZone = runs.filter((r) => r.zona_disponible === false);
    return head('Evidencia', 'De dónde sale cada cifra y cómo comprobarla. Todo lo que este panel muestra se puede seguir hasta un archivo con su huella.')
      + '<h2 class="sec">Esta foto</h2>'
      + dl([
        ['Generada', esc(data.generado_en)],
        ['Commit del código', `<span class="id">${esc(data.commit || 'sin commit')}</span>`],
        ['Versión del esquema', `<span class="id">${esc(base.version_esquema)}</span>`],
        ['Última carga', `<span class="id">${esc(base.ultima_carga_id)}</span>, ${pill(base.ultima_carga_estado === 'completed' ? 'ok' : 'draft', base.ultima_carga_estado === 'completed' ? 'Completa' : word(base.ultima_carga_estado))}`],
        ['Huella del contenido', `<span class="id">${esc(base.huella_contenido)}</span>`],
        ['Conflictos pendientes', int(base.conflictos_pendientes)],
        ['Archivos de alcance desconocido', `${int(base.archivos_alcance_desconocido)} <small>(no se pudieron ligar a un escenario: quedan ocultos por seguridad)</small>`]
      ])
      + '<h2 class="sec">Última comprobación de la base</h2>'
      + (evidence
        ? `<p class="cap">Carpeta <span class="id">${esc(evidence.carpeta)}</span>, ${date(evidence.fecha)}, código ${esc(evidence.codigo)}.</p>`
          + (evidence.de_esta_base ? '' : notice('<b>Esta comprobación es de otra versión de la base.</b> Hay que volver a correr <span class="id">bd evidencia</span>.', true))
          + table([['Comprobación', (s) => esc(word(s.nombre))], ['Resultado', (s) => pill(s.estado)]], list(evidence.secciones))
        : notice('Todavía no hay evidencia publicada para esta base.', true))
      + `<h2 class="sec">Datos que faltan <small>(ausente nunca es cero)</small></h2><div class="grid cols-3">${metric('Corridas sin demora medida', int(noDelay.length), '', 'Censurada o sin datos: se conoce un mínimo o nada')}${metric('Filas de acceso sin cohorte', int(noCohort.length), '', 'Una por corrida y acceso: tienen cola, pero no demora')}${metric('Corridas sin zona de medición', int(noZone.length), '', 'Sin cola, sin detenciones')}</div>`
      + `<h2 class="sec">Archivos excluidos con decisión <small>(${esc(list(data.exclusiones).length)})</small></h2><p class="cap">No se pudieron cargar. No se ocultan: quedan registrados con su decisión.</p>`
      + table([
        ['Archivo', (x) => `<span class="id">${esc(x.archivo)}</span>`],
        ['Motivo', (x) => esc(x.detalle)],
        ['Decisión', (x) => esc(word(x.decision))],
        ['Quién', (x) => esc(x.decidido_por)],
        ['Fecha', (x) => date(x.decidido_en)],
        ['Huella', (x) => `<span class="id">${esc(x.archivo_sha256)}</span>`]
      ], list(data.exclusiones))
      + `<h2 class="sec">Procedencia de cada corrida <small>(${esc(runs.length)})</small></h2><p class="cap">Un commit vacío (—) significa que la corrida es anterior a que el proyecto lo registrara en cada corrida; sus archivos sí tienen huella.</p>`
      + table([
        ['Corrida', (r) => `<span class="id">${esc(r.run_id)}</span>`],
        ['Protocolo', (r) => `<span class="id">${esc(r.protocolo_metricas_id || '—')}</span>`],
        ['SUMO', (r) => esc(r.version_sumo || '—')],
        ['Commit', (r) => `<span class="corto">${short(r.commit_codigo)}</span>`],
        ['Manifiesto', (r) => fileLink(data, 'datos', r.manifiesto)],
        ['Huella del manifiesto', (r) => `<span class="id">${esc(r.manifiesto_sha256)}</span>`],
        ['Huella de las métricas', (r) => `<span class="id">${esc(r.metricas_sha256 || '—')}</span>`]
      ], runs);
  }

  const PAGES = {
    inicio: pageInicio, caso: pageCaso, escenarios: pageEscenarios, simulaciones: pageSimulaciones,
    comparacion: pageComparacion, busqueda: pageBusqueda, entrenamiento: pageEntrenamiento,
    consultas: pageConsultas, evaluacion: pageEvaluacion, evidencia: pageEvidencia
  };

  function render(route, data, state) {
    return (PAGES[route] || pageInicio)(data, state || {});
  }

  /* --- navegador ------------------------------------------------------------------------------ */

  function start(data) {
    const state = { serie: '', run: null, planAcceso: null, semillaAcceso: null };
    const $ = (s) => document.querySelector(s);
    const current = () => {
      const hash = location.hash.replace('#', '');
      return ROUTES.some((r) => r[0] === hash) ? hash : 'inicio';
    };
    const nav = () => {
      const route = current();
      $('#nav').innerHTML = ROUTES.map(([id, label]) => `<button type="button" class="nav-link${id === route ? ' active' : ''}" data-route="${id}"${id === route ? ' aria-current="page"' : ''}>${esc(label)}</button>`).join('');
      $('#crumb-current').textContent = (ROUTES.find((r) => r[0] === route) || [])[1] || '';
    };
    const draw = (focus) => {
      nav();
      $('#app').innerHTML = render(current(), data, state);
      if (focus) { window.scrollTo(0, 0); $('#contenido').focus({ preventScroll: true }); }
    };
    const project = (data.avance || {}).proyecto || {};
    $('#brand-sub').textContent = project.corto || '';
    $('#foot-date').textContent = `Generada ${String(data.generado_en || '').slice(0, 10)}`;
    $('#cutoff').textContent = `Foto de la base · ${String(data.generado_en || '').slice(0, 10)}`;
    $('#pie').textContent = 'Foto estática de la base de datos: no se conecta a nada y no cambia sola. Para actualizarla se genera de nuevo.';
    document.title = project.corto ? `Panel · ${project.corto}` : 'Panel de resultados';
    document.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      if (button.dataset.route) { location.hash = button.dataset.route; }
      if (button.dataset.run) {
        state.run = button.dataset.run;
        draw(false);
        const detail = document.getElementById('detalle');
        if (detail) detail.scrollIntoView();
      }
      if (button.id === 'help-btn') $('#help').showModal();
    });
    document.addEventListener('change', (event) => {
      const name = event.target.dataset ? event.target.dataset.filtro : null;
      if (!name) return;
      state[name] = event.target.value;
      if (name === 'serie') state.run = null;
      if (name === 'planAcceso') state.semillaAcceso = null;
      draw(false);
    });
    window.addEventListener('hashchange', () => draw(true));
    draw(false);
  }

  if (typeof document !== 'undefined' && root.PANEL_DATA) start(root.PANEL_DATA);
  if (typeof module !== 'undefined') module.exports = { render, esc, ROUTES };
})(typeof window !== 'undefined' ? window : globalThis);
