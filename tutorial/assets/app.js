/* Telemetry tutorial: navigation, progress and the interactive panels.
   Plain JavaScript. Pages are static HTML, and this script fills in elements
   that carry a data-* attribute. Everything labelled "live" goes through
   server.py, which bridges to the lab. */

(function () {
  'use strict';

  const PAGES = [
    { id: 'start', href: 'index.html', title: 'Start here', group: 'Start' },
    { id: 'concepts', href: 'concepts.html', title: 'Traces, metrics and logs', group: 'Learn' },
    { id: 'lab1', href: 'lab1.html', title: 'Telemetry with no code', group: 'Lab 1: hands-off' },
    { id: 'code', href: 'instrumentation.html', title: 'The instrumentation code', group: 'Lab 2: SDK' },
    { id: 'error', href: 'incident-error.html', title: 'An unhandled error', group: 'Lab 2: incidents' },
    { id: 'latency', href: 'incident-latency.html', title: 'A latency spike', group: 'Lab 2: incidents' },
    { id: 'cross', href: 'incident-cross-service.html', title: 'A cross-service failure', group: 'Lab 2: incidents' },
    { id: 'sql', href: 'incident-slow-sql.html', title: 'A slow SQL query', group: 'Lab 2: incidents' },
    { id: 'timeout', href: 'incident-timeout.html', title: 'A timeout', group: 'Lab 2: incidents' },
    { id: 'cpu', href: 'incident-cpu.html', title: 'CPU saturation', group: 'Lab 2: incidents' },
    { id: 'queries', href: 'queries.html', title: 'Search query reference', group: 'Reference' },
    { id: 'gaps', href: 'gaps.html', title: 'What is missing, and fixes', group: 'Reference' },
  ];

  const SIGNOZ = 'http://signoz.localhost:8080';
  const STORE = 'telemetry-tutorial-v1';
  const SPAN_ARRIVAL_WAIT_MS = 8000;
  const SPAN_RETRY_WAIT_MS = 6000;
  const SPAN_RETRIES = 4;

  const pageId = document.body.dataset.page;
  let lab = null;

  /* ---------- small helpers ---------- */

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else if (value !== false && value != null) node.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child != null) node.append(child);
    }
    return node;
  }

  /* Like node.append, but flattens arrays and skips null, as el() does. */
  function add(node, ...children) {
    for (const child of children.flat(Infinity)) {
      if (child != null) node.append(child);
    }
  }

  function loadState() {
    try {
      return Object.assign({ done: {}, quiz: {}, fired: {} }, JSON.parse(localStorage.getItem(STORE) || '{}'));
    } catch (error) {
      return { done: {}, quiz: {}, fired: {} };
    }
  }

  function saveState(state) {
    try {
      localStorage.setItem(STORE, JSON.stringify(state));
    } catch (error) {
      /* Private browsing can refuse storage. Progress just won't persist. */
    }
  }

  const dataCache = {};
  function loadData(name) {
    if (!dataCache[name]) {
      dataCache[name] = fetch('data/' + name + '.json').then((response) => {
        if (!response.ok) throw new Error('could not load ' + name);
        return response.json();
      });
    }
    return dataCache[name];
  }

  async function getJSON(url, options) {
    const response = await fetch(url, options);
    const body = await response.json();
    return { status: response.status, body };
  }

  function formatDuration(ms) {
    if (ms >= 60000) return (ms / 1000).toFixed(1) + ' s';
    if (ms >= 1000) return (ms / 1000).toFixed(2) + ' s';
    if (ms >= 10) return ms.toFixed(0) + ' ms';
    if (ms >= 0.1) return ms.toFixed(1) + ' ms';
    return ms.toFixed(3) + ' ms';
  }

  function formatNumber(value) {
    if (typeof value !== 'number') return String(value);
    if (Math.abs(value) >= 1000) return Math.round(value).toLocaleString('en-US');
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
  }

  function httpChip(code) {
    const cls = code >= 500 ? 'c5' : code >= 400 ? 'c4' : 'c2';
    return el('span', { class: 'chip ' + cls, text: 'HTTP ' + code });
  }

  /* ---------- SigNoz links (format taken from the SigNoz UI's own URLs) ---------- */

  function compositeQuery(signal, expression) {
    return {
      queryType: 'builder',
      builder: {
        queryData: [{
          dataSource: signal,
          queryName: 'A',
          aggregateOperator: signal === 'logs' ? 'noop' : 'count',
          aggregateAttribute: { id: '----', dataType: '', key: '', type: '' },
          timeAggregation: 'rate',
          spaceAggregation: 'sum',
          filter: { expression },
          aggregations: [{ expression: 'count() ' }],
          functions: [],
          filters: { items: [], op: 'AND' },
          expression: 'A',
          disabled: false,
          stepInterval: null,
          having: { expression: '' },
          limit: null,
          orderBy: [{ columnName: 'timestamp', order: 'desc' }],
          groupBy: [],
          legend: '',
          reduceTo: 'avg',
          source: '',
        }],
        queryFormulas: [],
        queryTraceOperator: [],
      },
      promql: [{ name: 'A', query: '', legend: '', disabled: false }],
      clickhouse_sql: [{ name: 'A', legend: '', disabled: false, query: '' }],
      id: 'tutorial',
      unit: '',
    };
  }

  function explorerLink(signal, expression, relativeTime) {
    const path = signal === 'logs' ? '/logs/logs-explorer' : '/traces-explorer';
    const encoded = encodeURIComponent(encodeURIComponent(JSON.stringify(compositeQuery(signal, expression))));
    return SIGNOZ + path + '?relativeTime=' + relativeTime + '&compositeQuery=' + encoded;
  }

  /* Confirmed in the UI for k8s.pod.cpu.usage. Other metrics open the plain Explorer. */
  function cpuMetricLink() {
    const query = compositeQuery('metrics', "k8s.namespace.name = 'lab2'");
    Object.assign(query.builder.queryData[0], {
      aggregateOperator: 'avg',
      aggregateAttribute: { id: 'k8s.pod.cpu.usage--float64--Gauge--true', dataType: 'float64', key: 'k8s.pod.cpu.usage', type: 'Gauge', isColumn: true, isJSON: false },
      timeAggregation: 'avg',
      spaceAggregation: 'max',
      aggregations: [{ metricName: 'k8s.pod.cpu.usage', temporality: '', timeAggregation: 'avg', spaceAggregation: 'max', reduceTo: 'avg' }],
      orderBy: [],
      groupBy: [{ dataType: 'string', key: 'k8s.pod.name', type: 'tag', isColumn: false, isJSON: false, id: 'k8s.pod.name--string--tag--false' }],
      legend: '{{k8s.pod.name}}',
    });
    return SIGNOZ + '/metrics-explorer/explorer?relativeTime=6h&compositeQuery=' + encodeURIComponent(encodeURIComponent(JSON.stringify(query)));
  }

  function relativeTimeFor(minutes) {
    if (minutes <= 60) return '1h';
    if (minutes <= 1440) return '1d';
    return '1w';
  }

  /* ---------- sidebar and page end ---------- */

  function renderSidebar() {
    const state = loadState();
    const host = document.getElementById('sidebar');
    if (!host) return;
    host.textContent = '';
    const done = PAGES.filter((page) => state.done[page.id]).length;
    const groups = [...new Set(PAGES.map((page) => page.group))];
    add(host,
      el('a', { class: 'brand', href: 'index.html', text: 'Telemetry with SigNoz' }),
      el('p', { class: 'progress-text', text: done + ' of ' + PAGES.length + ' pages complete' }),
      el('div', { class: 'progress-bar', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': PAGES.length, 'aria-valuenow': done },
        el('span', { style: 'width:' + (100 * done / PAGES.length) + '%' })),
      groups.map((group) => [
        el('h2', { text: group }),
        el('ul', {}, PAGES.filter((page) => page.group === group).map((page) =>
          el('li', {}, el('a', { href: page.href, 'aria-current': page.id === pageId ? 'page' : null },
            el('span', { class: 'tick', 'aria-hidden': 'true', text: state.done[page.id] ? '✓' : '' }),
            el('span', { text: page.title }),
            state.done[page.id] ? el('span', { class: 'skip', text: ' (complete)' }) : null)))),
      ]),
      el('div', { class: 'lab-pill', id: 'lab-pill' }, el('strong', { text: 'Lab: checking' })),
    );
    renderLabPill();
  }

  function renderPageEnd() {
    const host = document.getElementById('page-end');
    if (!host) return;
    const index = PAGES.findIndex((page) => page.id === pageId);
    const previous = PAGES[index - 1];
    const next = PAGES[index + 1];
    host.textContent = '';
    const state = loadState();
    const toggle = el('button', {
      class: state.done[pageId] ? 'alt' : 'go',
      text: state.done[pageId] ? 'Completed. Mark as not done' : 'Mark this page complete',
      onclick: () => {
        const current = loadState();
        current.done[pageId] = !current.done[pageId];
        saveState(current);
        renderPageEnd();
        renderSidebar();
        renderPath();
      },
    });
    host.append(el('div', { class: 'row' },
      previous ? el('a', { class: 'alt', href: previous.href, text: '← ' + previous.title }) : el('span'),
      toggle,
      next ? el('a', { class: 'alt', href: next.href, text: next.title + ' →' }) : el('span')));
  }

  function renderPath() {
    const host = document.getElementById('path');
    if (!host) return;
    const state = loadState();
    host.textContent = '';
    host.className = 'path';
    PAGES.filter((page) => page.id !== 'start').forEach((page) => {
      host.append(el('a', { href: page.href },
        el('span', { class: 'kicker', text: page.group }),
        el('span', { class: 'title', text: page.title }),
        state.done[page.id] ? el('span', { class: 'state', text: '✓ Complete' }) : null));
    });
  }

  /* ---------- lab status ---------- */

  function liveAvailable() {
    return Boolean(lab && lab.app && lab.app.up);
  }

  function queriesAvailable() {
    return Boolean(lab && lab.signoz && lab.signoz.queries);
  }

  function renderLabPill() {
    const host = document.getElementById('lab-pill');
    if (!host) return;
    host.textContent = '';
    if (lab === null) {
      host.append(el('strong', { text: 'Lab: checking' }));
      return;
    }
    if (lab.bridge === false) {
      host.append(el('strong', { text: 'Tutorial server not running' }), 'Start it with: make tutorial');
      return;
    }
    add(host,
      el('strong', { text: 'Lab 2: ' + (lab.app.up ? 'up' : 'not running. Start it with: make lab2') }),
      el('strong', { text: 'SigNoz: ' + (lab.signoz.up ? 'up' : 'not reachable') }),
      lab.app.load && lab.app.load.running ? 'Load generator is running. Stop it when you finish.' : null,
    );
  }

  function renderBanner() {
    const main = document.getElementById('main');
    let banner = document.getElementById('lab-banner');
    const down = lab && (lab.bridge === false || !lab.app.up || !lab.signoz.up);
    if (!down) {
      if (banner) banner.remove();
      return;
    }
    if (!banner) {
      banner = el('div', { id: 'lab-banner', role: 'status' });
      main.prepend(banner);
    }
    banner.textContent = lab.bridge === false
      ? 'The tutorial server is not running, so live buttons and saved examples are unavailable. Start it with: make tutoriaerver.py'
      : 'Lab 2 or SigNoz is not reachable, so live buttons are off. Start them with: make up, then make lab2. Saved examples from real runs are still shown below.';
  }

  async function refreshLab() {
    try {
      const { body } = await getJSON('/live/status');
      lab = body;
    } catch (error) {
      lab = { bridge: false, app: { up: false }, signoz: { up: false } };
    }
    renderLabPill();
    renderBanner();
    document.dispatchEvent(new CustomEvent('labchange'));
  }

  /* ---------- waterfall from real spans ---------- */

  function isNoise(span) {
    return / http (send|receive)$/.test(span.name);
  }

  function startMs(span) {
    if (span.start_ns !== undefined) return span.start_ns / 1e6;
    const match = /^(.{19})(?:\.(\d+))?/.exec(span.start || '');
    if (!match) return 0;
    return Date.parse(match[1] + 'Z') + Number('0.' + (match[2] || '0')) * 1000;
  }

  function orderSpans(spans) {
    const byParent = new Map();
    const ids = new Set(spans.map((span) => span.span_id));
    spans.forEach((span) => {
      const key = ids.has(span.parent) ? span.parent : '';
      if (!byParent.has(key)) byParent.set(key, []);
      byParent.get(key).push(span);
    });
    const ordered = [];
    const walk = (key, depth) => {
      (byParent.get(key) || [])
        .sort((a, b) => startMs(a) - startMs(b))
        .forEach((span) => {
          ordered.push({ span, depth });
          walk(span.span_id, depth + 1);
        });
    };
    walk('', 0);
    return ordered;
  }

  function showTip(event, text) {
    let tip = document.getElementById('tip');
    if (!tip) {
      tip = el('div', { id: 'tip' });
      document.body.append(tip);
    }
    tip.textContent = text;
    tip.style.whiteSpace = 'pre-line';
    tip.style.display = 'block';
    const x = Math.min(event.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    const y = Math.min(event.clientY + 14, window.innerHeight - tip.offsetHeight - 8);
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }

  function hideTip() {
    const tip = document.getElementById('tip');
    if (tip) tip.style.display = 'none';
  }

  function renderWaterfall(spans, showNoise) {
    const ordered = orderSpans(spans).filter(({ span }) => showNoise || !isNoise(span));
    const seen = ordered.map(({ span }) => span);
    const start = Math.min(...seen.map(startMs));
    const end = Math.max(...seen.map((span) => startMs(span) + span.duration_nano / 1e6));
    const total = Math.max(end - start, 0.001);
    const box = el('div', { class: 'wf' });
    box.append(el('div', { class: 'wf-legend' },
      el('span', {}, el('span', { class: 'sw', style: 'background:var(--series-1)' }), 'frontend'),
      el('span', {}, el('span', { class: 'sw', style: 'background:var(--series-2)' }), 'backend'),
      el('span', { text: '! marks a span with status Error' })));
    ordered.forEach(({ span, depth }) => {
      const ms = span.duration_nano / 1e6;
      const left = 100 * (startMs(span) - start) / total;
      const width = 100 * ms / total;
      const failed = span.has_error || span.status === 'Error';
      const tip = [
        span.name,
        span.service + ', ' + span.kind + ' span',
        'Duration ' + formatDuration(ms) + ', starts at +' + formatDuration(startMs(span) - start),
        'Status ' + (span.status || 'Unset') + (span.http ? ', HTTP ' + span.http : ''),
      ].join('\n');
      box.append(el('div', {
        class: 'wf-row',
        onmousemove: (event) => showTip(event, tip),
        onmouseleave: hideTip,
      },
        el('div', { class: 'wf-name', style: 'padding-left:' + depth * 0.8 + 'rem', title: span.name },
          failed ? el('span', { class: 'wf-err', 'aria-label': 'Error', text: '! ' }) : null,
          span.name, ' ',
          el('span', { class: 'wf-svc', text: span.service })),
        el('div', { class: 'wf-track' },
          el('div', {
            class: 'wf-bar ' + (span.service === 'backend' ? 's2' : 's1'),
            style: 'left:' + left + '%;width:' + width + '%',
          })),
        el('div', { class: 'wf-dur', text: formatDuration(ms) })));
    });
    box.append(el('div', { class: 'wf-axis' },
      el('span'),
      el('div', { class: 'ticks' },
        el('span', { text: '0' }),
        el('span', { text: formatDuration(total / 2) }),
        el('span', { text: formatDuration(total) })),
      el('span')));
    return box;
  }

  function waterfallBlock(spans) {
    const holder = el('div');
    const noise = spans.filter(isNoise).length;
    let showNoise = false;
    const draw = () => {
      holder.textContent = '';
      holder.append(renderWaterfall(spans, showNoise));
    };
    draw();
    if (!noise) return holder;
    const toggle = el('label', { style: 'font-size:.82rem;color:var(--muted)' },
      el('input', {
        type: 'checkbox',
        onchange: (event) => {
          showNoise = event.target.checked;
          draw();
        },
      }),
      ' Show the ' + noise + ' zero-length ASGI send and receive spans');
    return el('div', {}, holder, toggle);
  }

  function logTable(logs) {
    if (!logs.length) return el('p', { class: 'meta', text: 'No logs carry this trace ID.' });
    return el('div', { class: 'table-scroll' }, el('table', {},
      el('thead', {}, el('tr', {}, ['Service', 'Severity', 'Message'].map((name) => el('th', { text: name })))),
      el('tbody', {}, logs.map((log) => el('tr', {},
        el('td', { text: log.service || '(blank)' }),
        el('td', { text: log.severity || '(blank)' }),
        el('td', { text: log.body }))))));
  }

  /* ---------- saved evidence ---------- */

  async function renderEvidence(host) {
    const name = host.dataset.evidence;
    try {
      const data = await loadData('evidence');
      const run = data.runs[name];
      const spans = run.spans.map((span) => ({ ...span }));
      host.classList.add('panel', 'wide');
      host.textContent = '';
      const realSpans = spans.filter((span) => !isNoise(span)).length;
      add(host,
        el('h4', { text: 'Saved run: ' + name }),
        el('p', { class: 'meta', style: 'color:var(--muted);font-size:.84rem;margin:.1rem 0 .5rem' },
          'Fired ' + run.fired_at + '. ', httpChip(run.http), ' in ' + formatNumber(run.wall_ms) + ' ms. ',
          realSpans + ' spans, plus ' + (spans.length - realSpans) + ' ASGI noise spans. Trace ', el('code', { text: run.trace_id })),
        waterfallBlock(spans),
        el('h4', { style: 'margin-top:.9rem', text: 'Logs with this trace ID' }),
        logTable(run.logs.slice(0, 6)),
        run.logs.length > 6 ? el('p', { class: 'meta', text: run.logs.length + '+ logs in total. First 6 shown.' }) : null,
        run.stack ? el('details', {},
          el('summary', { text: 'Last lines of the stack trace stored on the span' }),
          el('pre', {}, el('code', { text: run.stack.tail.join('\n') }))) : null,
        el('div', { class: 'row', style: 'margin-top:.6rem' },
          el('a', { class: 'alt', href: SIGNOZ + '/trace/' + run.trace_id, target: '_blank', rel: 'noopener', text: 'Open this trace in SigNoz' })),
      );
    } catch (error) {
      host.textContent = 'Saved example could not be loaded.';
    }
  }

  /* ---------- fire a scenario ---------- */

  function fireLabel(name) {
    return 'Fire ' + name;
  }

  function renderFire(host) {
    const name = host.dataset.fire;
    host.classList.add('panel');
    const params = JSON.parse(host.dataset.params || '{}');
    const button = el('button', { class: 'go', text: host.dataset.label || fireLabel(name) });
    const secondsInput = name === 'cpu_burn'
      ? el('input', { type: 'number', min: 1, max: 120, value: params.seconds || 60, 'aria-label': 'Seconds to burn' })
      : null;
    const output = el('div', { class: 'result', 'aria-live': 'polite' });
    const hint = el('span', { class: 'meta', style: 'color:var(--muted);font-size:.86rem' });
    const update = () => {
      button.disabled = !liveAvailable();
      hint.textContent = liveAvailable()
        ? (host.dataset.hint || '')
        : 'Live button off: the lab is not reachable.';
    };
    document.addEventListener('labchange', update);
    update();
    button.addEventListener('click', () => fire(name, secondsInput ? { ...params, seconds: Number(secondsInput.value) } : params, button, output));
    host.append(el('div', { class: 'row' },
      button,
      secondsInput ? el('label', { style: 'font-size:.9rem' }, 'Seconds ', secondsInput) : null,
      hint), output);
  }

  async function fire(name, params, button, output) {
    button.disabled = true;
    output.textContent = '';
    const started = Date.now();
    const progress = el('p', { class: 'meta', text: 'Running...' });
    output.append(progress);
    const ticker = setInterval(() => {
      progress.textContent = 'Running... ' + Math.round((Date.now() - started) / 1000) + ' s';
    }, 1000);
    try {
      const { body } = await getJSON('/live/scenario/' + name, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      clearInterval(ticker);
      output.textContent = '';
      if (!body.response || typeof body.response !== 'object') {
        output.append(el('p', { text: 'The lab did not answer: ' + (body.error || 'unknown error') }));
        return;
      }
      const state = loadState();
      state.fired[name] = Date.now();
      saveState(state);
      const traceId = body.response.trace_id;
      output.append(
        el('p', { class: 'meta' }, httpChip(body.http), ' in ' + formatNumber(body.wall_ms) + ' ms'),
        el('pre', {}, el('code', { text: JSON.stringify(body.response, null, 2) })));
      if (traceId) {
        output.append(
          el('div', { class: 'row', style: 'margin-top:.5rem' },
            el('a', { class: 'go', href: SIGNOZ + '/trace/' + traceId, target: '_blank', rel: 'noopener', text: 'Open trace in SigNoz' }),
            el('a', { class: 'alt', href: explorerLink('logs', "trace_id = '" + traceId + "'", '1h'), target: '_blank', rel: 'noopener', text: 'Logs for this trace' })),
          el('div', { class: 'spans-here' }));
        watchTrace(traceId, output.querySelector('.spans-here'));
      }
    } catch (error) {
      clearInterval(ticker);
      output.textContent = 'The request failed. The lab may be down.';
    } finally {
      button.disabled = !liveAvailable();
    }
  }

  async function watchTrace(traceId, host) {
    if (!queriesAvailable()) {
      host.append(el('p', { class: 'meta', text: 'SigNoz lookups are off, so spans cannot be shown here.' }));
      return;
    }
    const note = el('p', { class: 'meta', text: 'Waiting for spans. The SDK batches them and flushes every 5 seconds.' });
    host.append(note);
    await new Promise((resolve) => setTimeout(resolve, SPAN_ARRIVAL_WAIT_MS));
    let spanCount = -1;
    for (let attempt = 0; attempt < SPAN_RETRIES; attempt += 1) {
      try {
        const { status, body } = await getJSON('/live/trace/' + traceId);
        if (status === 200 && body.spans.length) {
          const stable = body.spans.length === spanCount;
          spanCount = body.spans.length;
          host.textContent = '';
          host.append(
            el('p', { class: 'meta', text: body.spans.length + ' spans and ' + body.logs.length + ' logs, read live from SigNoz just now.' }),
            waterfallBlock(body.spans),
            el('h4', { style: 'margin-top:.8rem;font-size:.92rem', text: 'Logs with this trace ID' }),
            logTable(body.logs.slice(0, 6)));
          if (stable) return;
        }
      } catch (error) {
        /* Keep trying until the attempts run out. */
      }
      await new Promise((resolve) => setTimeout(resolve, SPAN_RETRY_WAIT_MS));
    }
    if (spanCount < 0) {
      note.textContent = 'No spans yet. Use the SigNoz link above in a few seconds.';
    }
  }

  /* ---------- load generator ---------- */

  function renderLoad(host) {
    host.classList.add('panel');
    const rps = el('input', { type: 'number', min: 0.5, max: 20, step: 0.5, value: 5, 'aria-label': 'Requests per second' });
    const pct = el('input', { type: 'number', min: 0, max: 100, value: 10, 'aria-label': 'Error percentage' });
    const start = el('button', { class: 'go', text: 'Start load' });
    const stop = el('button', { class: 'alt', text: 'Stop load' });
    const status = el('p', { class: 'meta', style: 'color:var(--muted);font-size:.88rem;margin:.5rem 0 0', role: 'status' });
    const show = (load) => {
      status.textContent = load && load.running
        ? 'Running at ' + load.rps + ' requests/s with ' + load.error_pct + '% errors. Sent ' + load.sent + '. Please stop it when you finish.'
        : 'Stopped.';
    };
    const update = () => {
      start.disabled = !liveAvailable();
      stop.disabled = !liveAvailable();
      if (liveAvailable()) show(lab.app.load);
      else status.textContent = 'Live button off: the lab is not reachable.';
    };
    start.addEventListener('click', async () => {
      const { body } = await getJSON('/live/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rps: Number(rps.value), error_pct: Number(pct.value) }),
      });
      show(body);
      refreshLab();
    });
    stop.addEventListener('click', async () => {
      const { body } = await getJSON('/live/load', { method: 'DELETE' });
      show(body);
      refreshLab();
    });
    document.addEventListener('labchange', update);
    update();
    host.append(
      el('h4', { text: 'Background traffic' }),
      el('div', { class: 'row' },
        el('label', { style: 'font-size:.9rem' }, 'Requests/s ', rps),
        el('label', { style: 'font-size:.9rem' }, 'Error % ', pct),
        start, stop),
      status);
  }

  /* ---------- query cards ---------- */

  function verifiedBadge(item) {
    if (item.verified === 'ui') return el('span', { class: 'badge ui', text: 'Seen in SigNoz UI' });
    return el('span', { class: 'badge api', text: 'Query API only' });
  }

  function savedView(saved) {
    const box = el('div');
    if (saved.warnings && saved.warnings.length) {
      box.append(el('p', { class: 'meta', text: 'SigNoz warning: ' + saved.warnings[0].slice(0, 170) }));
    }
    if (saved.kind === 'rows') {
      if (saved.matched !== undefined) {
        box.append(el('p', { class: 'meta', text: formatNumber(saved.matched) + ' matched. Newest ' + saved.rows.length + ' shown.' }));
      }
      if (saved.rows.length) box.append(rowsTable(saved.rows));
    } else if (saved.kind === 'table') {
      box.append(scalarTable(saved.columns, saved.data));
    } else if (saved.kind === 'metric') {
      box.append(seriesTable(saved.series));
    }
    return box;
  }

  function rowsTable(rows) {
    const isSpan = rows[0] && 'duration_nano' in rows[0];
    const columns = isSpan
      ? [['Time (UTC)', (row) => (row.timestamp || '').slice(11, 19)], ['Service', (row) => row['service.name']], ['Span', (row) => row.name], ['Duration', (row) => formatDuration(row.duration_nano / 1e6)], ['HTTP', (row) => row.response_status_code || '']]
      : [['Time (UTC)', (row) => (row.timestamp || '').slice(11, 19)], ['Service', (row) => row.service], ['Severity', (row) => row.severity], ['Message', (row) => row.body]];
    return el('div', { class: 'table-scroll' }, el('table', {},
      el('thead', {}, el('tr', {}, columns.map(([title]) => el('th', { text: title })))),
      el('tbody', {}, rows.map((row) => el('tr', {}, columns.map(([, read]) => el('td', { text: read(row) })))))));
  }

  function columnTitle(name, labels, index) {
    return name.startsWith('__result') ? (labels[index] || 'Value') : name;
  }

  function formatCell(value, title) {
    if (typeof value === 'number' && /duration_nano/.test(title)) return formatDuration(value / 1e6);
    return formatNumber(value);
  }

  function scalarTable(columns, data, aggs) {
    const labels = aggs || [];
    let aggIndex = 0;
    const titles = columns.map((name) => (name.startsWith('__result') ? columnTitle(name, labels, aggIndex++) : name));
    return el('div', { class: 'table-scroll' }, el('table', {},
      el('thead', {}, el('tr', {}, titles.map((title) => el('th', { text: title })))),
      el('tbody', {}, data.map((row) => el('tr', {}, row.map((value, index) => el('td', { text: formatCell(value, titles[index]) })))))));
  }

  function seriesTable(series) {
    return el('div', { class: 'table-scroll' }, el('table', {},
      el('thead', {}, el('tr', {}, ['Series', 'Points', 'Peak', 'Peak at', 'Last'].map((name) => el('th', { text: name })))),
      el('tbody', {}, series.map((item) => el('tr', {},
        el('td', { text: Object.values(item.labels).join(', ') || '(all)' }),
        el('td', { text: item.points }),
        el('td', { text: formatNumber(item.peak) }),
        el('td', { text: item.peak_at || '' }),
        el('td', { text: formatNumber(item.last) }))))));
  }

  function liveView(item, payload) {
    const response = payload.result;
    const box = el('div');
    const minutes = payload.minutes;
    const windowText = minutes >= 1440 ? (minutes / 1440) + ' days' : minutes + ' minutes';
    if (!response || response.status !== 'success') {
      box.append(el('p', { text: 'SigNoz returned an error for this query.' }));
      return box;
    }
    const results = response.data.data.results;
    const first = results && results[0];
    box.append(el('p', { class: 'meta', text: 'Live result, last ' + windowText + '.' }));
    if (item.requestType === 'raw') {
      const rows = (first && first.rows) || [];
      if (!rows.length) {
        box.append(el('p', { text: 'No rows.' + (item.neg ? ' That is the expected result here.' : ' Try firing the scenario or starting load first.') }));
        return box;
      }
      if (item.signal === 'traces') {
        box.append(rowsTable(rows.map((row) => row.data)));
      } else {
        box.append(rowsTable(rows.map((row) => ({
          timestamp: row.timestamp,
          service: (row.data.resources_string || {})['service.name'] || '(blank)',
          severity: row.data.severity_text || '(blank)',
          body: (row.data.body || '').slice(0, 170),
        }))));
      }
    } else if (item.requestType === 'scalar') {
      if (!first || !first.data || !first.data.length) {
        box.append(el('p', { text: 'No rows.' }));
      } else {
        box.append(scalarTable(first.columns.map((column) => column.name), first.data.slice(0, 12), item.aggs));
      }
    } else {
      const series = [];
      ((first && first.aggregations) || []).forEach((aggregation) => {
        (aggregation.series || []).forEach((entry) => {
          const values = entry.values.slice().sort((a, b) => a.timestamp - b.timestamp);
          const peak = values.reduce((best, point) => (point.value > best.value ? point : best), values[0]);
          series.push({
            labels: Object.fromEntries((entry.labels || []).map((label) => [label.key.name, label.value])),
            points: values.length,
            peak: peak.value,
            peak_at: new Date(peak.timestamp).toISOString().slice(11, 16) + ' UTC',
            last: values[values.length - 1].value,
          });
        });
      });
      if (!series.length) box.append(el('p', { text: 'No data in this window. Try starting load first.' }));
      else box.append(seriesTable(series.sort((a, b) => b.peak - a.peak).slice(0, 8)));
    }
    return box;
  }

  function metricDescription(item) {
    const metric = item.metric;
    const parts = ['Metric: ' + metric.metricName];
    if (metric.timeAggregation) parts.push('time aggregation: ' + metric.timeAggregation);
    parts.push('space aggregation: ' + metric.spaceAggregation);
    if (item.expr) parts.push('where: ' + item.expr);
    if (item.by) parts.push('group by: ' + item.by.join(', '));
    return parts.join('  |  ');
  }

  function aggregateDescription(item) {
    const parts = [];
    if (item.expr) parts.push('Filter: ' + item.expr);
    parts.push('Aggregate: ' + item.aggs.join(', '));
    if (item.by) parts.push('Group by: ' + item.by.join(', '));
    return parts.join('  |  ');
  }

  function copyButton(text) {
    return el('button', {
      class: 'copy',
      text: 'Copy',
      onclick: async (event) => {
        try {
          await navigator.clipboard.writeText(text);
          event.target.textContent = 'Copied';
          setTimeout(() => { event.target.textContent = 'Copy'; }, 1200);
        } catch (error) {
          event.target.textContent = 'Press Cmd+C';
        }
      },
    });
  }

  function queryCard(item, compact) {
    const showText = item.metric ? metricDescription(item) : item.aggs ? aggregateDescription(item) : item.expr;
    const output = el('div', { class: 'result', 'aria-live': 'polite' });
    const run = el('button', { class: 'alt', text: 'Run live' });
    const runLive = async () => {
      run.disabled = true;
      output.textContent = 'Running...';
      try {
        const { status, body } = await getJSON('/live/query/' + item.id, { method: 'POST' });
        output.textContent = '';
        if (status === 200) output.append(liveView(item, body));
        else output.append(el('p', { text: 'Could not run this query: ' + (body.error || status) }));
      } catch (error) {
        output.textContent = 'The request failed. The lab may be down.';
      }
      run.disabled = !queriesAvailable();
    };
    run.addEventListener('click', runLive);
    const update = () => {
      run.disabled = !queriesAvailable();
      run.title = queriesAvailable() ? '' : 'Live button off: SigNoz is not reachable.';
    };
    document.addEventListener('labchange', update);
    update();
    const canLink = !item.metric && !item.aggs;
    const link = canLink
      ? el('a', { class: 'alt', href: explorerLink(item.signal, item.expr, relativeTimeFor(item.liveMinutes)), target: '_blank', rel: 'noopener', text: 'Open in SigNoz' })
      : el('a', { class: 'alt', href: item.id === 'm-cpu' ? cpuMetricLink() : SIGNOZ + (item.metric ? '/metrics-explorer/explorer' : '/traces-explorer'), target: '_blank', rel: 'noopener', text: item.id === 'm-cpu' ? 'Open in SigNoz' : item.metric ? 'Open Metrics Explorer' : 'Open Explorer' });
    return el('div', { class: 'panel query-card', 'data-search': (item.title + ' ' + showText + ' ' + item.group).toLowerCase() },
      el('h4', {}, item.title, ' ', verifiedBadge(item)),
      compact ? null : el('p', { class: 'why', text: item.why.replace(/`/g, '') }),
      el('div', { class: 'expr' }, el('span', { text: showText }), copyButton(item.metric || item.aggs ? showText : item.expr)),
      el('div', { class: 'row' }, run, link),
      output,
      el('details', {},
        el('summary', { text: 'Saved result from ' + item.savedWindow.start.slice(0, 16).replace('T', ' ') + ' to ' + item.savedWindow.end.slice(11, 16) + ' UTC' }),
        item.requestType === 'scalar' ? scalarTable(item.saved.columns, item.saved.data, item.aggs) : savedView(item.saved)));
  }

  async function renderQuery(host) {
    try {
      const data = await loadData('queries');
      const item = data.queries.find((query) => query.id === host.dataset.query);
      host.replaceWith(queryCard(item, false));
    } catch (error) {
      host.textContent = 'Saved query could not be loaded.';
    }
  }

  async function renderQueryIndex(host) {
    const data = await loadData('queries');
    const groups = [...new Set(data.queries.map((query) => query.group))];
    const search = el('input', { type: 'search', placeholder: 'Filter queries, for example sql, cpu or logs', 'aria-label': 'Filter queries' });
    const count = el('p', { class: 'meta', style: 'color:var(--muted);font-size:.84rem;margin:.3rem 0 0' });
    const cards = [];
    const body = el('div');
    groups.forEach((group) => {
      const section = el('section', { 'data-group': group });
      section.append(el('h3', { class: 'groupname', text: group }));
      data.queries.filter((query) => query.group === group).forEach((query) => {
        const card = queryCard(query, false);
        cards.push(card);
        section.append(card);
      });
      body.append(section);
    });
    const apply = () => {
      const term = search.value.trim().toLowerCase();
      let shown = 0;
      cards.forEach((card) => {
        const match = !term || card.dataset.search.includes(term);
        card.hidden = !match;
        if (match) shown += 1;
      });
      body.querySelectorAll('section').forEach((section) => {
        section.hidden = !section.querySelector('.query-card:not([hidden])');
      });
      count.textContent = shown + ' of ' + cards.length + ' queries';
    };
    search.addEventListener('input', apply);
    host.textContent = '';
    host.append(el('div', { class: 'filterbar' }, search, count), body);
    apply();
  }

  async function renderClickHouse(host) {
    const data = await loadData('clickhouse');
    const ids = host.dataset.ch ? host.dataset.ch.split(',') : null;
    const items = ids ? data.queries.filter((query) => ids.includes(query.id)) : data.queries;
    host.textContent = '';
    items.forEach((item) => {
      host.append(el('div', { class: 'panel' },
        el('h4', {}, item.title, ' ', el('span', { class: 'badge data', text: 'ClickHouse SQL' })),
        el('p', { class: 'why', text: item.why.replace(/`/g, '') }),
        el('details', {},
          el('summary', { text: 'Show the SQL' }),
          el('pre', { style: 'white-space:pre-wrap' }, el('code', { style: 'width:auto', text: item.sql }))),
        el('div', { class: 'result' }, item.result && item.result.rows.length
          ? el('div', { class: 'table-scroll' }, el('table', {},
            el('thead', {}, el('tr', {}, item.result.columns.map((name) => el('th', { text: name })))),
            el('tbody', {}, item.result.rows.slice(0, 20).map((row) => el('tr', {}, row.map((value) => el('td', { text: value })))))))
          : el('p', { text: 'No rows.' }))));
    });
  }

  /* ---------- CPU chart from raw samples ---------- */

  async function renderCpuChart(host) {
    const data = await loadData('clickhouse');
    const samples = data.queries.find((query) => query.id === 'c-cpu-samples').result.rows
      .map(([time, cores]) => ({ t: Date.parse(time.replace(' ', 'T') + 'Z'), label: time.slice(11, 19), cores: Number(cores) }));
    const bands = [
      { start: Date.parse('2026-11-04T23:11:10Z'), end: Date.parse('2026-11-04T23:12:40Z'), label: 'burn 1' },
      { start: Date.parse('2026-11-04T23:15:44Z'), end: Date.parse('2026-11-04T23:17:14Z'), label: 'burn 2' },
    ];
    const width = 760;
    const height = 260;
    const margin = { top: 16, right: 16, bottom: 28, left: 44 };
    const x0 = samples[0].t;
    const x1 = samples[samples.length - 1].t;
    const px = (t) => margin.left + (t - x0) / (x1 - x0) * (width - margin.left - margin.right);
    const py = (v) => height - margin.bottom - v / 1.2 * (height - margin.top - margin.bottom);
    const NS = 'http://www.w3.org/2000/svg';
    const svgEl = (tag, attrs, text) => {
      const node = document.createElementNS(NS, tag);
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      if (text !== undefined) node.textContent = text;
      return node;
    };
    const svg = svgEl('svg', { viewBox: '0 0 ' + width + ' ' + height, role: 'img', 'aria-label': 'CPU cores used by the backend pod over time. Two plateaus near one core during the burns.' });
    bands.forEach((band) => {
      svg.append(svgEl('rect', { class: 'band', x: px(band.start), y: margin.top, width: px(band.end) - px(band.start), height: height - margin.top - margin.bottom }));
      svg.append(svgEl('text', { class: 'band-label', x: px(band.start) + 5, y: margin.top + 13 }, band.label));
    });
    const axis = svgEl('g', { class: 'axis' });
    [0, 0.25, 0.5, 0.75, 1].forEach((tick) => {
      axis.append(svgEl('line', { class: 'grid', x1: margin.left, x2: width - margin.right, y1: py(tick), y2: py(tick) }));
      axis.append(svgEl('text', { x: margin.left - 8, y: py(tick) + 4, 'text-anchor': 'end' }, tick.toString()));
    });
    samples.filter((_, index) => index % 4 === 0).forEach((sample) => {
      axis.append(svgEl('text', { x: px(sample.t), y: height - 8, 'text-anchor': 'middle' }, sample.label.slice(0, 5)));
    });
    svg.append(axis);
    svg.append(svgEl('path', { class: 'line', d: samples.map((sample, index) => (index ? 'L' : 'M') + px(sample.t).toFixed(1) + ' ' + py(sample.cores).toFixed(1)).join(' ') }));
    const cross = svgEl('line', { class: 'cross', y1: margin.top, y2: height - margin.bottom, visibility: 'hidden' });
    const dot = svgEl('circle', { class: 'dot', r: 5, visibility: 'hidden' });
    svg.append(cross, dot);
    svg.addEventListener('mousemove', (event) => {
      const box = svg.getBoundingClientRect();
      const x = (event.clientX - box.left) / box.width * width;
      const nearest = samples.reduce((best, sample) => (Math.abs(px(sample.t) - x) < Math.abs(px(best.t) - x) ? sample : best), samples[0]);
      cross.setAttribute('x1', px(nearest.t));
      cross.setAttribute('x2', px(nearest.t));
      cross.setAttribute('visibility', 'visible');
      dot.setAttribute('cx', px(nearest.t));
      dot.setAttribute('cy', py(nearest.cores));
      dot.setAttribute('visibility', 'visible');
      showTip(event, nearest.label + ' UTC\n' + nearest.cores + ' cores');
    });
    svg.addEventListener('mouseleave', () => {
      cross.setAttribute('visibility', 'hidden');
      dot.setAttribute('visibility', 'hidden');
      hideTip();
    });
    host.classList.add('panel', 'chart', 'wide');
    host.textContent = '';
    host.append(
      el('h4', { text: 'Backend pod CPU, in cores' }),
      el('p', { class: 'why', text: 'Raw k8s.pod.cpu.usage samples, one every 30 seconds, read from ClickHouse. Shaded bands are the two 90-second burns.' }),
      svg,
      el('details', {},
        el('summary', { text: 'Show as a table' }),
        el('table', {},
          el('thead', {}, el('tr', {}, el('th', { text: 'Time (UTC)' }), el('th', { text: 'Cores' }))),
          el('tbody', {}, samples.map((sample) => el('tr', {}, el('td', { text: sample.label }), el('td', { text: sample.cores })))))));
  }

  /* ---------- quiz, images, code copy ---------- */

  function setupQuiz(host) {
    const id = host.dataset.quiz;
    const buttons = [...host.querySelectorAll('button')];
    const answer = el('p', { class: 'answer', role: 'status' });
    host.append(answer);
    const reveal = (index) => {
      const picked = buttons[index];
      const right = picked.dataset.right === 'true';
      buttons.forEach((button) => button.classList.remove('right', 'wrong'));
      picked.classList.add(right ? 'right' : 'wrong');
      answer.textContent = (right ? 'Correct. ' : 'Not quite. ') + picked.dataset.why;
    };
    buttons.forEach((button, index) => {
      button.addEventListener('click', () => {
        const state = loadState();
        state.quiz[id] = index;
        saveState(state);
        reveal(index);
      });
    });
    const saved = loadState().quiz[id];
    if (saved !== undefined && buttons[saved]) reveal(saved);
  }

  function setupZoom() {
    let dialog = null;
    document.querySelectorAll('figure.shot img').forEach((image) => {
      image.addEventListener('click', () => {
        if (!dialog) {
          dialog = el('dialog', { class: 'zoom' }, el('img', { alt: '' }));
          dialog.addEventListener('click', () => dialog.close());
          document.body.append(dialog);
        }
        const large = dialog.querySelector('img');
        large.src = image.src;
        large.alt = image.alt;
        dialog.showModal();
      });
    });
  }

  function setupCodeCopy() {
    document.querySelectorAll('figure.code').forEach((figure) => {
      const caption = figure.querySelector('figcaption');
      const code = figure.querySelector('pre code');
      if (!caption || !code) return;
      const text = [...code.childNodes].map((node) => {
        if (node.nodeType === Node.ELEMENT_NODE && node.classList.contains('ln')) return '';
        return node.textContent;
      }).join('');
      caption.append(copyButton(text));
    });
  }

  function setupResetButton() {
    const button = document.getElementById('reset-progress');
    if (!button) return;
    button.addEventListener('click', () => {
      localStorage.removeItem(STORE);
      location.reload();
    });
  }

  /* ---------- start ---------- */

  renderSidebar();
  renderPageEnd();
  renderPath();
  setupZoom();
  setupCodeCopy();
  setupResetButton();
  document.querySelectorAll('[data-quiz]').forEach(setupQuiz);
  document.querySelectorAll('[data-evidence]').forEach(renderEvidence);
  document.querySelectorAll('[data-fire]').forEach(renderFire);
  document.querySelectorAll('[data-load-panel]').forEach(renderLoad);
  document.querySelectorAll('[data-query]').forEach(renderQuery);
  document.querySelectorAll('[data-query-index]').forEach(renderQueryIndex);
  document.querySelectorAll('[data-ch]').forEach(renderClickHouse);
  document.querySelectorAll('[data-cpu-chart]').forEach(renderCpuChart);
  refreshLab();
  setInterval(refreshLab, 20000);
})();
