/* Telemetry tutorial: navigation, progress and the interactive panels.
   Plain JavaScript. Pages are static HTML, and this script fills in elements
   that carry a data-* attribute. Everything labelled "live" goes through
   server.py, which bridges to the lab. */

(function () {
  'use strict';

  const PAGES = [
    { id: 'start', href: 'index.html', title: 'Start here', group: 'Start' },
    { id: 'lab1', href: 'lab1.html', title: 'Telemetry with no code', group: 'Lab 1: hands-off' },
    { id: 'concepts', href: 'concepts.html', title: 'Traces, metrics and logs', group: 'Lab 1: hands-off' },
    { id: 'error', href: 'incident-error.html', title: 'An unhandled error', group: 'Lab 1: hands-off' },
    { id: 'latency', href: 'incident-latency.html', title: 'A latency spike', group: 'Lab 1: hands-off' },
    { id: 'cross', href: 'incident-cross-service.html', title: 'A cross-service failure', group: 'Lab 1: hands-off' },
    { id: 'sql', href: 'incident-slow-sql.html', title: 'A slow SQL query', group: 'Lab 1: hands-off' },
    { id: 'timeout', href: 'incident-timeout.html', title: 'A timeout', group: 'Lab 1: hands-off' },
    { id: 'cpu', href: 'incident-cpu.html', title: 'CPU saturation', group: 'Lab 1: hands-off' },
    { id: 'lab1-review', href: 'lab1-review.html', title: 'What hands-off gets you', group: 'Lab 1: hands-off' },
    { id: 'dimensions', href: 'dimensions.html', title: 'Dimensions and granularity', group: 'Lab 2: custom dimensions' },
    { id: 'code', href: 'instrumentation.html', title: 'The instrumentation code', group: 'Lab 2: custom dimensions' },
    { id: 'slowitem', href: 'incident-slow-item.html', title: 'Only one product is slow', group: 'Lab 2: custom dimensions' },
    { id: 'freeorders', href: 'incident-free-orders.html', title: 'Revenue dropped with no errors', group: 'Lab 2: custom dimensions' },
    { id: 'cachemiss', href: 'incident-cache-miss.html', title: 'Slow for no visible reason', group: 'Lab 2: custom dimensions' },
    { id: 'traceid', href: 'incident-trace-id.html', title: 'A customer quotes a trace ID', group: 'Lab 2: custom dimensions' },
    { id: 'lab3', href: 'lab3.html', title: 'What Kubernetes tells you', group: 'Lab 3: Kubernetes' },
    { id: 'throttling', href: 'incident-throttling.html', title: 'Slow, then restarted', group: 'Lab 3: Kubernetes' },
    { id: 'oom', href: 'incident-oom.html', title: 'A container that disappears', group: 'Lab 3: Kubernetes' },
    { id: 'liveness', href: 'incident-liveness.html', title: 'A failing health check', group: 'Lab 3: Kubernetes' },
    { id: 'node', href: 'incident-node.html', title: 'Is it the pod or the node?', group: 'Lab 3: Kubernetes' },
    { id: 'apiserver', href: 'incident-apiserver.html', title: 'The API server', group: 'Lab 3: Kubernetes' },
    { id: 'lab3-collection', href: 'lab3-collection.html', title: "How it's collected, and what it costs", group: 'Lab 3: Kubernetes' },
    { id: 'lab4', href: 'lab4.html', title: 'Alerts that reach you', group: 'Lab 4: alerts' },
    { id: 'lab5', href: 'lab5.html', title: 'Look inside Postgres', group: 'Lab 5: Postgres (optional)' },
    { id: 'lockwait', href: 'incident-lock-wait.html', title: 'An order that waits', group: 'Lab 5: Postgres (optional)' },
    { id: 'deadlock', href: 'incident-deadlock.html', title: 'An order that gets cancelled', group: 'Lab 5: Postgres (optional)' },
    { id: 'missingindex', href: 'incident-missing-index.html', title: 'A query that reads everything', group: 'Lab 5: Postgres (optional)' },
    { id: 'connections', href: 'incident-connections.html', title: 'Out of connections', group: 'Lab 5: Postgres (optional)' },
    { id: 'lab6', href: 'lab6.html', title: 'Connect an AI agent', group: 'Lab 6: AI analysis' },
    { id: 'ai-ask', href: 'ai-ask.html', title: 'Ask it questions', group: 'Lab 6: AI analysis' },
    { id: 'ai-alerts', href: 'ai-alerts.html', title: 'Investigate alerts by itself', group: 'Lab 6: AI analysis' },
    { id: 'ai-measured', href: 'ai-measured.html', title: 'How good is it?', group: 'Lab 6: AI analysis' },
    { id: 'queries', href: 'queries.html', title: 'Search query reference', group: 'Reference' },
    { id: 'setup', href: 'setup.html', title: 'How SigNoz is configured', group: 'Reference' },
    { id: 'automate', href: 'automate.html', title: 'Automate it', group: 'Reference' },
    { id: 'gaps', href: 'gaps.html', title: 'What is missing, and fixes', group: 'Reference' },
  ];

  const SIGNOZ = 'http://signoz.localhost:8080';
  const STORE = 'telemetry-tutorial-v1';
  const LAB_NAMES = { lab1: 'Lab 1', lab2: 'Lab 2', lab3: 'Lab 3', lab5: 'Lab 5', lab6: 'Lab 6' };
  const LAB_START = { lab1: 'make up', lab2: 'make lab2', lab3: 'make lab3', lab5: 'make lab5' };
  /* The banner only mentions these. Lab 5 is optional, and Lab 6 has nothing to fire. */
  const REQUIRED_LABS = ['lab1', 'lab2', 'lab3'];
  const LAB_FRONTEND = { lab1: 'lab1-frontend', lab2: 'frontend', lab3: 'lab3-workload', lab5: 'lab5-app' };
  const SPAN_ARRIVAL_WAIT_MS = 2000;
  const SPAN_RETRY_WAIT_MS = 3000;
  const SPAN_RETRIES = 8;
  const TRACE_SEARCH_POLL_MS = 2000;
  const TRACE_SEARCH_LIMIT_MS = 60000;

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

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
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
  function cpuMetricLink(expression) {
    const query = compositeQuery('metrics', expression);
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
      },
    });
    host.append(el('div', { class: 'row' },
      previous ? el('a', { class: 'alt', href: previous.href, text: '← ' + previous.title }) : el('span'),
      toggle,
      next ? el('a', { class: 'alt', href: next.href, text: next.title + ' →' }) : el('span')));
  }

  /* ---------- lab status ---------- */

  function labUp(labId) {
    return Boolean(lab && lab.labs && lab.labs[labId] && lab.labs[labId].up);
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
    const running = Object.keys(LAB_NAMES).filter((labId) => labUp(labId) && lab.labs[labId].load && lab.labs[labId].load.running);
    add(host,
      Object.keys(LAB_START).map((labId) => el('strong', {
        text: LAB_NAMES[labId] + ': ' + (labUp(labId) ? 'up' : (REQUIRED_LABS.includes(labId) ? '' : 'optional, ') + 'not running. Start it with: ' + LAB_START[labId]),
      })),
      el('strong', { text: 'SigNoz: ' + (lab.signoz.up ? 'up' : 'not reachable') }),
      running.length ? 'Load generator is running in ' + running.map((labId) => LAB_NAMES[labId]).join(' and ') + '. Stop it when you finish.' : null,
    );
  }

  function bannerText() {
    if (lab.bridge === false) {
      return 'The tutorial server is not running, so live buttons and saved examples are unavailable. Start it with: make tutorial';
    }
    const parts = REQUIRED_LABS.map((labId) => (labUp(labId)
      ? LAB_NAMES[labId] + ' is up.'
      : LAB_NAMES[labId] + ' is not running, so its live buttons are off. Start it with: ' + LAB_START[labId] + '.'));
    parts.push(lab.signoz.up ? 'SigNoz is up.' : 'SigNoz is not reachable, so searches and trace lookups are off. Start it with: make up.');
    parts.push('Saved examples from real runs are still shown below.');
    return parts.join(' ');
  }

  function renderBanner() {
    const main = document.getElementById('main');
    let banner = document.getElementById('lab-banner');
    const down = lab && (lab.bridge === false || REQUIRED_LABS.some((labId) => !labUp(labId)) || !lab.signoz.up);
    if (!down) {
      if (banner) banner.remove();
      return;
    }
    if (!banner) {
      banner = el('div', { id: 'lab-banner', role: 'status' });
      main.prepend(banner);
    }
    /* make up deploys only Lab 1, so the later labs being absent is normal, not a fault. */
    const onlyLaterLabs = lab.bridge !== false && labUp('lab1') && lab.signoz.up;
    banner.classList.toggle('info', onlyLaterLabs);
    banner.textContent = bannerText();
  }

  async function refreshLab() {
    try {
      const { body } = await getJSON('/live/status');
      lab = body;
    } catch (error) {
      lab = { bridge: false, labs: {}, signoz: { up: false } };
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

  function isBackend(span) {
    return /backend$/.test(span.service || '');
  }

  /* Custom dimensions, which only Lab 2's spans have. */
  function spanNote(span) {
    const parts = [];
    if (span.order_item) parts.push('order.item=' + span.order_item);
    if (span.order_item && span.order_total !== undefined && span.order_total !== null) parts.push('order.total=' + span.order_total);
    if (span.order_coupon) parts.push('order.coupon=' + span.order_coupon);
    if (span.cache_hit !== undefined && span.cache_hit !== null) parts.push('cache.hit=' + span.cache_hit);
    return parts.join(' ');
  }

  function renderWaterfall(spans, showNoise) {
    const ordered = orderSpans(spans).filter(({ span }) => showNoise || !isNoise(span));
    const seen = ordered.map(({ span }) => span);
    const start = Math.min(...seen.map(startMs));
    const end = Math.max(...seen.map((span) => startMs(span) + span.duration_nano / 1e6));
    const total = Math.max(end - start, 0.001);
    const box = el('div', { class: 'wf' });
    box.append(el('div', { class: 'wf-legend' },
      [...new Set(seen.map((span) => span.service))].sort().reverse().map((service) => el('span', {},
        el('span', { class: 'sw', style: 'background:var(--series-' + (isBackend({ service }) ? 2 : 1) + ')' }), service)),
      el('span', { text: '! marks a span with status Error' })));
    ordered.forEach(({ span, depth }) => {
      const ms = span.duration_nano / 1e6;
      const left = 100 * (startMs(span) - start) / total;
      const width = 100 * ms / total;
      const failed = span.has_error || span.status === 'Error';
      const note = spanNote(span);
      const tip = [
        span.name,
        span.service + ', ' + span.kind + ' span',
        'Duration ' + formatDuration(ms) + ', starts at +' + formatDuration(startMs(span) - start),
        'Status ' + (span.status || 'Unset') + (span.http ? ', HTTP ' + span.http : ''),
        span.sql ? 'db.statement: ' + span.sql : null,
        note || null,
      ].filter(Boolean).join('\n');
      box.append(el('div', {
        class: 'wf-row',
        onmousemove: (event) => showTip(event, tip),
        onmouseleave: hideTip,
      },
        el('div', { class: 'wf-name', style: 'padding-left:' + depth * 0.8 + 'rem', title: span.name },
          failed ? el('span', { class: 'wf-err', 'aria-label': 'Error', text: '! ' }) : null,
          span.name, ' ',
          el('span', { class: 'wf-svc', text: span.service }),
          note ? el('span', { class: 'wf-note', text: note }) : null),
        el('div', { class: 'wf-track' },
          el('div', {
            class: 'wf-bar ' + (isBackend(span) ? 's2' : 's1'),
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
    const withAttrs = logs.some((log) => log.attrs && Object.keys(log.attrs).length);
    const attrText = (log) => Object.entries(log.attrs || {}).map(([key, value]) => key + '=' + value).join(' ');
    return el('div', { class: 'table-scroll' }, el('table', {},
      el('thead', {}, el('tr', {}, ['Service', 'Severity', 'Message', withAttrs ? 'Attributes from extra=' : null].filter(Boolean).map((name) => el('th', { text: name })))),
      el('tbody', {}, logs.map((log) => el('tr', {},
        el('td', { text: log.service || '(blank)' }),
        el('td', { text: log.severity || '(blank)' }),
        el('td', { text: log.body }),
        withAttrs ? el('td', { text: attrText(log) }) : null)))));
  }

  /* ---------- saved evidence ---------- */

  async function renderEvidence(host) {
    const name = host.dataset.evidence;
    try {
      const data = await loadData('evidence');
      const run = data.runs[name];
      const spans = run.spans.map((span) => ({ ...span }));
      const logs = host.dataset.logs ? run.logs.filter((log) => log.body.includes(host.dataset.logs)) : run.logs;
      const limit = Number(host.dataset.logLimit || 6);
      host.classList.add('panel', 'wide');
      host.textContent = '';
      const realSpans = spans.filter((span) => !isNoise(span)).length;
      add(host,
        el('h4', { text: 'Saved run: ' + run.scenario + ' in ' + LAB_NAMES[run.lab] }),
        el('p', { class: 'meta', style: 'color:var(--muted);font-size:.84rem;margin:.1rem 0 .5rem' },
          'Fired ' + run.fired_at + '. ', httpChip(run.http), ' in ' + formatNumber(run.wall_ms) + ' ms. ',
          realSpans + ' spans, plus ' + (spans.length - realSpans) + ' ASGI noise spans. Trace ', el('code', { text: run.trace_id })),
        waterfallBlock(spans),
        el('h4', { style: 'margin-top:.9rem', text: host.dataset.logs ? 'Logs with this trace ID, showing "' + host.dataset.logs + '"' : 'Logs with this trace ID' }),
        logTable(logs.slice(0, limit)),
        logs.length > limit ? el('p', { class: 'meta', text: logs.length + ' logs in total. First ' + limit + ' shown.' }) : null,
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

  function renderFire(host) {
    const name = host.dataset.fire;
    const labId = host.dataset.lab || 'lab1';
    host.classList.add('panel');
    const params = JSON.parse(host.dataset.params || '{}');
    const button = el('button', { class: 'go', text: host.dataset.label || 'Fire ' + name + ' in ' + LAB_NAMES[labId] });
    const secondsInput = name === 'cpu_burn'
      ? el('input', { type: 'number', min: 1, max: 120, value: params.seconds || 60, 'aria-label': 'Seconds to burn' })
      : null;
    const output = el('div', { class: 'result', 'aria-live': 'polite' });
    const hint = el('span', { class: 'meta', style: 'color:var(--muted);font-size:.86rem' });
    let busy = false;
    const update = () => {
      button.disabled = busy || !labUp(labId);
      hint.textContent = labUp(labId)
        ? (host.dataset.hint || '')
        : 'Live button off: ' + LAB_NAMES[labId] + ' is not running. Start it with: ' + LAB_START[labId];
    };
    document.addEventListener('labchange', update);
    update();
    button.addEventListener('click', async () => {
      busy = true;
      update();
      await fire(labId, name, secondsInput ? { ...params, seconds: Number(secondsInput.value) } : params, output);
      busy = false;
      update();
    });
    host.append(el('div', { class: 'row' },
      button,
      secondsInput ? el('label', { style: 'font-size:.9rem' }, 'Seconds ', secondsInput) : null,
      hint), output);
  }

  async function fire(labId, name, params, output) {
    output.textContent = '';
    const started = Date.now();
    const progress = el('p', { class: 'meta', text: 'Running...' });
    output.append(progress);
    const ticker = setInterval(() => {
      progress.textContent = 'Running... ' + Math.round((Date.now() - started) / 1000) + ' s';
    }, 1000);
    try {
      const { body } = await getJSON('/live/scenario/' + labId + '/' + name, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      clearInterval(ticker);
      output.textContent = '';
      if (!body.response || typeof body.response !== 'object') {
        output.append(el('p', { text: body.http
          ? 'The request did not reach the app: the proxy answered HTTP ' + body.http + '. Fire it again.'
          : LAB_NAMES[labId] + ' did not answer. It may be down.' }));
        return;
      }
      const state = loadState();
      state.fired[labId + '/' + name] = Date.now();
      saveState(state);
      output.append(
        el('p', { class: 'meta' }, httpChip(body.http), ' in ' + formatNumber(body.wall_ms) + ' ms'),
        el('pre', {}, el('code', { text: JSON.stringify(body.response, null, 2) })));
      if (body.response.trace_id) showTrace(body.response.trace_id, output);
      else await findTrace(labId, name, body.fired_ms, output);
    } catch (error) {
      clearInterval(ticker);
      output.textContent = 'The request failed. ' + LAB_NAMES[labId] + ' may be down.';
    }
  }

  function showTrace(traceId, output) {
    const spans = el('div', { class: 'spans-here' });
    output.append(
      el('div', { class: 'row', style: 'margin-top:.5rem' },
        el('a', { class: 'go', href: SIGNOZ + '/trace/' + traceId, target: '_blank', rel: 'noopener', text: 'Open trace in SigNoz' }),
        el('a', { class: 'alt', href: explorerLink('logs', "trace_id = '" + traceId + "'", '1h'), target: '_blank', rel: 'noopener', text: 'Logs for this trace' })),
      spans);
    watchTrace(traceId, spans);
  }

  /* Lab 1's API returns no trace ID, so ask SigNoz for the trace of the request
     the bridge just sent. It takes a few seconds to arrive, hence the waiting note. */
  async function findTrace(labId, name, firedMs, output) {
    const search = "service.name = '" + LAB_FRONTEND[labId] + "' AND http.target = '/api/scenario/" + name + "'";
    const note = el('p', { class: 'meta', role: 'status' });
    output.append(
      el('p', { class: 'meta', text: 'This response has no trace ID, because ' + LAB_NAMES[labId] + "'s app does not know it is being traced. This page finds the trace by searching SigNoz for the request it just sent." }),
      note,
      el('div', { class: 'row', style: 'margin-top:.5rem' },
        el('a', { class: 'alt', href: explorerLink('traces', search, '1h'), target: '_blank', rel: 'noopener', text: 'Run the search in SigNoz yourself' })));
    if (!queriesAvailable()) {
      note.textContent = 'SigNoz lookups are off, so the trace cannot be found from here.';
      return;
    }
    const started = Date.now();
    const seconds = () => Math.round((Date.now() - started) / 1000);
    const waiting = () => {
      note.textContent = 'Waiting for the trace to reach SigNoz: ' + seconds() + ' s. This usually takes a few seconds.';
    };
    waiting();
    const ticker = setInterval(waiting, 1000);
    try {
      while (Date.now() - started < TRACE_SEARCH_LIMIT_MS) {
        const { status, body } = await getJSON('/live/find/' + labId + '/' + name + '?since=' + firedMs);
        if (status === 200 && body.trace_id) {
          clearInterval(ticker);
          note.textContent = 'Found it in SigNoz after ' + seconds() + ' s.';
          showTrace(body.trace_id, output);
          return;
        }
        await sleep(TRACE_SEARCH_POLL_MS);
      }
      clearInterval(ticker);
      note.textContent = 'No matching trace after ' + seconds() + ' s. SigNoz may be busy. Use the search link below in a moment.';
    } catch (error) {
      clearInterval(ticker);
      note.textContent = 'The search failed. SigNoz may be down. Use the search link below when it is back.';
    }
  }

  async function watchTrace(traceId, host) {
    if (!queriesAvailable()) {
      host.append(el('p', { class: 'meta', text: 'SigNoz lookups are off, so spans cannot be shown here.' }));
      return;
    }
    const note = el('p', { class: 'meta', text: 'Waiting for every span to reach SigNoz...' });
    host.append(note);
    await sleep(SPAN_ARRIVAL_WAIT_MS);
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
            logTable(body.logs));
          if (stable) return;
        }
      } catch (error) {
        /* Keep trying until the attempts run out. */
      }
      await sleep(SPAN_RETRY_WAIT_MS);
    }
    if (spanCount < 0) {
      note.textContent = 'No spans yet. Use the SigNoz link above in a few seconds.';
    }
  }

  /* ---------- load generator ---------- */

  /* ---------- architecture diagram ---------- */

  // One drawing, on Start here and on each lab's first page. A view only says
  // what that lab covers. Each page also has the same facts in a table.
  const ARCH_REGIONS = [
    { x: 10, y: 10, w: 980, h: 72, label: 'Your machine', parts: ['browser', 'ai'] },
    { x: 10, y: 100, w: 980, h: 525, label: 'Kubernetes cluster: k3d or kind, two nodes', labelX: 120 },
    { x: 30, y: 128, w: 445, h: 148, label: 'Demo app: namespaces lab1 and lab2', parts: ['frontend', 'backend', 'postgres'] },
    { x: 490, y: 128, w: 140, h: 148, label: 'Namespace lab3', parts: ['workload'] },
    { x: 650, y: 128, w: 190, h: 320, label: 'SigNoz: namespace signoz', parts: ['signoz', 'clickhouse', 'collectors'] },
    { x: 30, y: 460, w: 600, h: 150, label: 'What it all runs on', parts: ['kubelet', 'nodes', 'apiserver'] },
    { x: 650, y: 462, w: 320, h: 100, label: 'Optional: namespace lab5', parts: ['lab5app', 'lab5pg'] },
  ];
  const ARCH_PARTS = [
    { id: 'browser', x: 40, y: 28, w: 170, h: 42, title: ['Your browser'] },
    { id: 'ai', lab: 6, x: 800, y: 28, w: 170, h: 42, title: ['AI agent'], detail: ['Claude Code, or your own'] },
    { id: 'frontend', lab: 1, x: 45, y: 152, w: 125, h: 112, title: ['frontend'], detail: ['FastAPI'],
      chips: [{ id: 'frontend.agent', text: 'Python agent' }, { id: 'frontend.code', text: 'OTel API calls', lab: 2 }] },
    { id: 'backend', lab: 1, x: 190, y: 152, w: 125, h: 112, title: ['backend'], detail: ['FastAPI'],
      chips: [{ id: 'backend.agent', text: 'Python agent' }, { id: 'backend.code', text: 'OTel API calls', lab: 2 }] },
    { id: 'postgres', lab: 1, x: 335, y: 152, w: 125, h: 112, outside: true, title: ['Postgres'],
      detail: ['No agent inside.', 'Seen from outside:', 'queries, logs, CPU'] },
    { id: 'workload', lab: 3, x: 500, y: 152, w: 120, h: 112, title: ['lab3-workload'], detail: ['FastAPI'],
      chips: [{ id: 'workload.agent', text: 'Python agent' }] },
    { id: 'operator', lab: 1, x: 518, y: 296, w: 112, h: 54, title: ['OpenTelemetry', 'Operator'] },
    { id: 'nodeagents', lab: 1, x: 30, y: 370, w: 600, h: 62, title: ['Node agents and a cluster collector (k8s-infra)'],
      detail: ['Add pod and node names to everything. Read container output. Collect pod and node metrics.'] },
    { id: 'signoz', lab: 1, x: 665, y: 152, w: 160, h: 82, title: ['SigNoz UI and API'], detail: ['What you read'],
      chips: [{ id: 'signoz.rules', text: 'Alert rules', lab: 4 }] },
    { id: 'clickhouse', lab: 1, x: 665, y: 268, w: 160, h: 56, title: ['ClickHouse'], detail: ['Stores all of it'] },
    { id: 'collectors', lab: 1, x: 665, y: 370, w: 160, h: 62, title: ['2 SigNoz collectors'], detail: ['Receive and write'] },
    { id: 'mcp', lab: 6, x: 860, y: 152, w: 110, h: 72, title: ['MCP server'], detail: ['Read-only key'] },
    { id: 'sink', lab: 4, x: 860, y: 290, w: 110, h: 72, title: ['Alert sink'], detail: ['Stands in for', 'Slack or PagerDuty'] },
    { id: 'kubelet', lab: 3, x: 45, y: 492, w: 180, h: 104, title: ['kubelet'], detail: ['Pod and node metrics,', 'container limits and', 'probe results'] },
    { id: 'nodes', lab: 3, x: 240, y: 492, w: 180, h: 104, title: ['Nodes and kernel'], detail: ['Host metrics, the kernel', 'log with its OOM kills,', 'k3s log or journal'] },
    { id: 'apiserver', lab: 3, x: 435, y: 492, w: 180, h: 104, title: ['API server'], detail: ['Request metrics, and', 'an audit log of who', 'asked for what'] },
    { id: 'lab5app', lab: 5, x: 665, y: 488, w: 130, h: 62, title: ['lab5-app'], detail: ['FastAPI, Python agent'] },
    { id: 'lab5pg', lab: 5, x: 825, y: 488, w: 130, h: 62, title: ['Postgres'], detail: ['Reports on itself'] },
  ];
  const ARCH_WIRES = [
    { d: 'M107,70 V152', from: 'browser', to: 'frontend', label: ['your clicks', 113, 95] },
    { d: 'M210,60 H560 V152', from: 'browser', to: 'workload' },
    { d: 'M210,44 H745 V152', from: 'browser', to: 'signoz', label: ['you read the results here', 440, 38] },
    { d: 'M170,180 H190', from: 'frontend', to: 'backend' },
    { d: 'M315,180 H335', from: 'backend', to: 'postgres' },
    { d: 'M545,296 V284 H125 V264', from: 'operator', to: 'frontend', kind: 'inject' },
    { d: 'M270,284 V264', from: 'operator', to: 'backend', kind: 'inject', label: ['adds the agent as a pod starts', 278, 298] },
    { d: 'M580,296 V264', from: 'operator', to: 'workload', kind: 'inject' },
    { d: 'M90,264 V370', from: 'frontend', to: 'nodeagents', label: ['OTLP: traces,', 97, 330, 'logs, metrics'] },
    { d: 'M235,264 V370', from: 'backend', to: 'nodeagents' },
    { d: 'M508,264 V370', from: 'workload', to: 'nodeagents' },
    { d: 'M397,264 V370', from: 'postgres', to: 'nodeagents', kind: 'outside', label: ['its logs and pod metrics,', 390, 330, 'read from outside', 'end'] },
    { d: 'M630,401 H665', from: 'nodeagents', to: 'collectors' },
    { d: 'M745,370 V324', from: 'collectors', to: 'clickhouse' },
    { d: 'M745,268 V234', from: 'clickhouse', to: 'signoz' },
    { d: 'M825,214 H843 V326 H860', from: 'signoz', to: 'sink', label: ['webhook', 862, 284] },
    { d: 'M860,188 H825', from: 'mcp', to: 'signoz', covers: ['lab6'], label: ['reads', 843, 180, null, 'middle'] },
    { d: 'M915,70 V152', from: 'ai', to: 'mcp', label: ['asks through MCP', 908, 95, null, 'end'] },
    { d: 'M970,49 H982 V326 H970', from: 'ai', to: 'sink', covers: ['lab6'], label: ['polls', 968, 284, null, 'end'] },
    { d: 'M982,326 V586 H615', from: 'ai', to: 'apiserver', covers: ['lab6'], label: ['kubectl, read-only', 800, 579, null, 'middle'] },
    { d: 'M190,492 V432', from: 'kubelet', to: 'nodeagents', label: ['scraped and read', 197, 450] },
    { d: 'M330,492 V432', from: 'nodes', to: 'nodeagents' },
    { d: 'M525,492 V432', from: 'apiserver', to: 'nodeagents' },
    { d: 'M795,519 H825', from: 'lab5app', to: 'lab5pg' },
    { d: 'M665,519 H640 V422 H630', from: 'lab5app', to: 'nodeagents' },
    { d: 'M890,488 V455 H645 V412 H630', from: 'lab5pg', to: 'nodeagents', kind: 'outside', label: ['stats and log', 897, 479] },
  ];
  const ARCH_APP = ['frontend', 'frontend.agent', 'backend', 'backend.agent'];
  const ARCH_PIPELINE = ['nodeagents', 'collectors', 'clickhouse', 'signoz'];
  const ARCH_CODE = ['frontend.code', 'backend.code'];
  const ARCH_LAB5 = ['lab5app', 'lab5pg'];
  const ARCH_VIEWS = {
    lab1: {
      covered: [...ARCH_APP, 'operator', ...ARCH_PIPELINE],
      seen: ['postgres'],
      off: [...ARCH_CODE, ...ARCH_LAB5, 'workload', 'workload.agent', 'signoz.rules', 'apiserver', 'sink', 'mcp', 'ai'],
    },
    lab2: {
      covered: ['frontend', 'backend', ...ARCH_CODE],
      seen: ['postgres'],
      off: [...ARCH_LAB5, 'workload', 'workload.agent', 'signoz.rules', 'apiserver', 'sink', 'mcp', 'ai'],
    },
    lab3: {
      covered: ['workload', 'workload.agent', 'nodeagents', 'kubelet', 'nodes', 'apiserver'],
      off: [...ARCH_APP, ...ARCH_CODE, ...ARCH_LAB5, 'postgres', 'signoz.rules', 'sink', 'mcp', 'ai'],
    },
    lab4: {
      covered: ['signoz', 'signoz.rules', 'sink'],
      off: [...ARCH_CODE, ...ARCH_LAB5, 'mcp', 'ai'],
    },
    lab5: {
      covered: [...ARCH_LAB5, 'nodeagents'],
      off: [...ARCH_APP, ...ARCH_CODE, 'postgres', 'workload', 'workload.agent', 'apiserver', 'signoz.rules', 'sink', 'mcp', 'ai'],
    },
    lab6: {
      covered: ['ai', 'mcp'],
      off: ARCH_LAB5,
    },
  };

  function archState(view, id) {
    const parts = ARCH_VIEWS[view];
    if (!parts) return 'used';
    if (parts.covered.includes(id)) return 'covered';
    if ((parts.seen || []).includes(id)) return 'seen';
    return parts.off.includes(id) ? 'off' : 'used';
  }

  function archWireState(view, wire) {
    const ends = [archState(view, wire.from), archState(view, wire.to)];
    if (ends.includes('off')) return 'off';
    if ((wire.covers || []).includes(view)) return 'covered';
    return ends.every((state) => state === 'covered' || state === 'seen') ? 'covered' : 'used';
  }

  function archSvg(view) {
    const badge = (x, y, lab) => (view === 'start' && lab
      ? `<circle class="dot" cx="${x}" cy="${y}" r="8"/><text class="dot-num" x="${x}" y="${y + 4}">${lab}</text>` : '');
    const regions = ARCH_REGIONS.map((region) => {
      const off = region.parts && region.parts.every((id) => archState(view, id) === 'off');
      return `<g class="${off ? 'off' : ''}"><rect class="region" x="${region.x}" y="${region.y}" width="${region.w}" height="${region.h}" rx="9"/>`
        + `<text class="region-label" x="${region.labelX || region.x + 10}" y="${region.y + 16}">${region.label}</text></g>`;
    }).join('');
    const wires = ARCH_WIRES.map((wire) => {
      const state = archWireState(view, wire);
      const [text, x, y, second, anchor] = wire.label || [];
      // A label's fourth item is a second line, and its fifth (or a fourth of "end") is its alignment.
      const align = anchor || (wire.label && wire.label[4]) || 'start';
      const lines = text ? [text, second && second !== 'end' && second].filter(Boolean) : [];
      const label = lines.map((line, i) => `<text class="wire-label" text-anchor="${align}" x="${x}" y="${y + i * 14}">${line}</text>`).join('');
      return `<g class="${state}"><path class="wire ${wire.kind || ''}" d="${wire.d}" marker-end="url(#arch-arrow-${state === 'covered' ? 'on' : 'plain'})"/>${label}</g>`;
    }).join('');
    const parts = ARCH_PARTS.map((part) => {
      const state = archState(view, part.id);
      const titles = part.title.map((line, i) => `<text class="title" x="${part.x + 10}" y="${part.y + 19 + i * 16}">${line}</text>`).join('');
      const top = part.y + 19 + (part.title.length - 1) * 16 + 16;
      const details = (part.detail || []).map((line, i) => `<text class="detail" x="${part.x + 10}" y="${top + i * 14}">${line}</text>`).join('');
      const chipRows = (part.chips || []).length;
      const chips = (part.chips || []).map((chip, i) => {
        const y = part.y + part.h - 7 - (chipRows - i) * 25 + 3;
        const on = archState(view, chip.id);
        return `<g class="chip ${on}"><rect x="${part.x + 7}" y="${y}" width="${part.w - 14}" height="22" rx="5"/>`
          + `<text x="${part.x + 14}" y="${y + 15}">${chip.text}</text>${badge(part.x + part.w - 16, y + 11, chip.lab)}</g>`;
      }).join('');
      return `<g class="part ${state}${part.outside ? ' outside' : ''}"><rect class="box" x="${part.x}" y="${part.y}" width="${part.w}" height="${part.h}" rx="7"/>`
        + `${titles}${details}${chips}${badge(part.x + part.w - 3, part.y + 3, part.lab)}</g>`;
    }).join('');
    const marker = (id) => `<marker id="arch-arrow-${id}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="arrow-${id}" d="M0,0 L8,4 L0,8 Z"/></marker>`;
    return `<svg viewBox="0 0 1000 635" role="img" aria-label="Architecture diagram. The table next to it says the same thing in words."><defs>${marker('plain')}${marker('on')}</defs>${regions}${wires}${parts}</svg>`;
  }

  function renderArch(node) {
    const view = node.dataset.arch;
    const key = (cls, text) => `<span class="key"><span class="swatch ${cls}"></span>${text}</span>`;
    const legend = view === 'start'
      ? key('num', 'The lab that adds this part') + key('seen-plain', 'Nothing runs inside it: seen from outside')
      : key('covered', 'Covered in this lab')
        + (ARCH_VIEWS[view].seen ? key('seen', 'Nothing runs inside it: seen from outside') : '')
        + key('used', 'Running, and nothing new here')
        + (ARCH_VIEWS[view].off.length ? key('off', 'Not part of this lab') : '');
    node.innerHTML = `<div class="arch-scroll">${archSvg(view)}</div><div class="arch-legend">${legend}</div>`;
  }

  function renderLoad(host) {
    const labId = host.dataset.loadPanel || 'lab1';
    host.classList.add('panel');
    const rps = el('input', { type: 'number', min: 0.5, max: 20, step: 0.5, value: 5, 'aria-label': 'Requests per second in ' + LAB_NAMES[labId] });
    /* Lab 3's load is plain requests. Its failures come from Kubernetes, not bad input. */
    const hasErrors = labId !== 'lab3';
    const rpsDefault = Number(host.dataset.rps || 5);
    rps.value = rpsDefault;
    const pct = el('input', { type: 'number', min: 0, max: 100, value: hasErrors ? 10 : 0, 'aria-label': 'Error percentage in ' + LAB_NAMES[labId] });
    const start = el('button', { class: 'go', text: 'Start load' });
    const stop = el('button', { class: 'alt', text: 'Stop load' });
    const status = el('p', { class: 'meta', style: 'color:var(--muted);font-size:.88rem;margin:.5rem 0 0', role: 'status' });
    const show = (load) => {
      if (!load || load.error) {
        status.textContent = LAB_NAMES[labId] + ' did not answer. It may be down.';
        return;
      }
      status.textContent = load.running
        ? 'Running at ' + load.rps + ' requests/s' + (hasErrors ? ' with ' + load.error_pct + '% errors' : '') + '. Sent ' + load.sent + '. Please stop it when you finish.'
        : 'Stopped.';
    };
    /* Several labs' traffic at once can overload a small Docker VM, as Lab 6 found. */
    const others = el('p', { class: 'meta', style: 'margin:.5rem 0 0' });
    const showOthers = () => {
      others.textContent = '';
      const running = Object.keys(LAB_START).filter((other) => other !== labId && labUp(other) && lab.labs[other].load && lab.labs[other].load.running);
      if (!running.length) return;
      others.append(running.map((other) => LAB_NAMES[other]).join(' and ') + ' traffic is also running. Run one at a time, because several can overload Docker. ');
      running.forEach((other) => others.append(el('button', {
        class: 'alt',
        text: 'Stop ' + LAB_NAMES[other],
        onclick: async () => { await getJSON('/live/load/' + other, { method: 'DELETE' }); refreshLab(); },
      })));
    };
    const update = () => {
      start.disabled = !labUp(labId);
      stop.disabled = !labUp(labId);
      showOthers();
      if (labUp(labId)) show(lab.labs[labId].load);
      else status.textContent = 'Live button off: ' + LAB_NAMES[labId] + ' is not running. Start it with: ' + LAB_START[labId];
    };
    const send = async (options) => {
      try {
        const { body } = await getJSON('/live/load/' + labId, options);
        show(body);
      } catch (error) {
        show(null);
      }
      refreshLab();
    };
    start.addEventListener('click', () => send({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rps: Number(rps.value), error_pct: Number(pct.value) }),
    }));
    stop.addEventListener('click', () => send({ method: 'DELETE' }));
    document.addEventListener('labchange', update);
    update();
    host.append(
      el('h4', { text: 'Background traffic in ' + LAB_NAMES[labId] }),
      el('div', { class: 'row' },
        el('label', { style: 'font-size:.9rem' }, 'Requests/s ', rps),
        hasErrors ? el('label', { style: 'font-size:.9rem' }, 'Error % ', pct) : null,
        start, stop),
      status,
      others);
  }

  /* ---------- alerts received by Lab 4's sink ---------- */

  function renderAlertFeed(host) {
    host.classList.add('panel');
    const status = el('p', { class: 'meta', style: 'color:var(--muted);font-size:.88rem;margin:.25rem 0 .5rem', role: 'status' });
    const box = el('div', { class: 'table-scroll' });
    const show = (alerts) => {
      box.textContent = '';
      status.textContent = alerts.length
        ? 'Refreshes every 5 seconds. Times are UTC. Showing the newest ' + Math.min(alerts.length, 12) + ' of ' + alerts.length + '.'
        : 'Nothing received yet. Refreshes every 5 seconds.';
      if (!alerts.length) return;
      box.append(el('table', {},
        el('thead', {}, el('tr', {}, ['Received', 'Status', 'Alert', 'Detail'].map((name) => el('th', { text: name })))),
        el('tbody', {}, alerts.slice(0, 12).map((alert) => el('tr', {},
          el('td', { text: alert.received }),
          el('td', { text: alert.status }),
          el('td', { text: alert.labels.alertname || '' }),
          el('td', { text: alert.annotations.description || '' }))))));
    };
    const refresh = async () => {
      try {
        const { status: code, body } = await getJSON('/live/alerts');
        if (code === 200 && Array.isArray(body)) show(body);
        else status.textContent = 'Lab 4 is not running. Start it with: make lab4';
      } catch (error) {
        status.textContent = 'Lab 4 is not running. Start it with: make lab4';
      }
    };
    host.append(el('h4', { text: 'Alerts received' }), status, box);
    refresh();
    setInterval(refresh, 5000);
  }

  /* What `make investigate` has saved, newest first. */
  function renderInvestigations(host) {
    host.classList.add('panel');
    const status = el('p', { class: 'meta', style: 'color:var(--muted);font-size:.88rem;margin:.25rem 0 .5rem', role: 'status' });
    const box = el('div');
    const notRunning = 'Could not read the reports. Is the tutorial server running?';
    const show = (items) => {
      box.textContent = '';
      status.textContent = items.length
        ? 'Refreshes every 10 seconds. Times are UTC.'
        : 'No reports yet. Run make investigate in a terminal. An alert takes about 5 minutes to fire. Refreshes every 10 seconds.';
      items.slice(0, 5).forEach((item) => {
        const facts = [item.status];
        if (item.startsAt) facts.unshift('fired ' + item.startsAt.slice(11, 19));
        if (item.seconds != null) facts.push(item.seconds + ' s');
        if (item.cost_usd != null) facts.push('$' + item.cost_usd.toFixed(2));
        box.append(el('h5', { text: item.alertname }), el('p', { class: 'meta', text: facts.join(' · ') }),
          el('pre', { style: 'white-space:pre-wrap', text: item.report || 'Investigating…' }));
      });
    };
    const refresh = async () => {
      try {
        const { status: code, body } = await getJSON('/live/investigations');
        if (code === 200 && Array.isArray(body)) show(body);
        else status.textContent = notRunning;
      } catch (error) {
        status.textContent = notRunning;
      }
    };
    host.append(el('h4', { text: 'AI investigations' }), status, box);
    refresh();
    setInterval(refresh, 10000);
  }

  /* ---------- query cards ---------- */

  function verifiedBadge(item) {
    if (item.verified === 'ui') return el('span', { class: 'badge ui', text: 'Seen in SigNoz UI' });
    return el('span', { class: 'badge api', text: 'Query API only' });
  }

  function labBadge(item) {
    const text = item.lab === 'both' ? 'Both labs' : LAB_NAMES[item.lab];
    return text ? el('span', { class: 'badge lab', text }) : null;
  }

  function savedView(saved, item) {
    const box = el('div');
    if (saved.warnings && saved.warnings.length) {
      box.append(el('p', { class: 'meta', text: 'SigNoz warning: ' + saved.warnings[0].slice(0, 170) }));
    }
    if (saved.kind === 'rows') {
      if (saved.matched !== undefined) {
        box.append(el('p', { class: 'meta', text: formatNumber(saved.matched) + ' matched. Newest ' + saved.rows.length + ' shown.' }));
      }
      if (saved.rows.length) box.append(rowsTable(saved.rows, item.extra));
    } else if (saved.kind === 'table') {
      box.append(scalarTable(saved.columns, saved.data));
    } else if (saved.kind === 'metric') {
      box.append(seriesTable(saved.series));
    }
    return box;
  }

  function rowsTable(rows, extra) {
    const isSpan = rows[0] && 'duration_nano' in rows[0];
    const columns = isSpan
      ? [['Time (UTC)', (row) => (row.timestamp || '').slice(11, 19)], ['Service', (row) => row['service.name']], ['Span', (row) => row.name], ['Duration', (row) => formatDuration(row.duration_nano / 1e6)], ['HTTP', (row) => row.response_status_code || '']]
      : [['Time (UTC)', (row) => (row.timestamp || '').slice(11, 19)], ['Service', (row) => row.service], ['Severity', (row) => row.severity], ['Message', (row) => row.body]];
    (extra || []).forEach((key) => columns.push([key, (row) => (row[key] === undefined || row[key] === null ? '' : String(row[key]))]));
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
        box.append(rowsTable(rows.map((row) => row.data), item.extra));
      } else {
        box.append(rowsTable(rows.map((row) => {
          const attributes = { ...(row.data.attributes_string || {}), ...(row.data.attributes_number || {}) };
          const extras = Object.fromEntries((item.extra || []).map((key) => [key, attributes[key]]));
          return {
            timestamp: row.timestamp,
            service: (row.data.resources_string || {})['service.name'] || '(blank)',
            severity: row.data.severity_text || '(blank)',
            body: (row.data.body || '').slice(0, 170),
            ...extras,
          };
        }), item.extra));
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

  function copyButton(text, label = 'Copy') {
    return el('button', {
      class: 'copy',
      text: label,
      onclick: async (event) => {
        try {
          await navigator.clipboard.writeText(text);
          event.target.textContent = 'Copied';
          setTimeout(() => { event.target.textContent = label; }, 1200);
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
    const isCpu = Boolean(item.metric && item.metric.metricName === 'k8s.pod.cpu.usage');
    const link = canLink
      ? el('a', { class: 'alt', href: explorerLink(item.signal, item.expr, relativeTimeFor(item.liveMinutes)), target: '_blank', rel: 'noopener', text: 'Open in SigNoz' })
      : el('a', { class: 'alt', href: isCpu ? cpuMetricLink(item.expr) : SIGNOZ + (item.metric ? '/metrics-explorer/explorer' : item.signal === 'logs' ? '/logs/logs-explorer' : '/traces-explorer'), target: '_blank', rel: 'noopener', text: isCpu ? 'Open in SigNoz' : item.metric ? 'Open Metrics Explorer' : 'Open Explorer' });
    return el('div', { class: 'panel query-card', 'data-search': (item.title + ' ' + showText + ' ' + item.group).toLowerCase() },
      el('h4', {}, item.title, ' ', labBadge(item), ' ', verifiedBadge(item)),
      compact ? null : el('p', { class: 'why', text: item.why.replace(/`/g, '') }),
      el('div', { class: 'expr' }, el('span', { text: showText }), copyButton(item.metric || item.aggs ? showText : item.expr)),
      el('div', { class: 'row' }, run, link),
      output,
      el('details', {},
        el('summary', { text: 'Saved result from ' + item.savedWindow.start.slice(0, 16).replace('T', ' ') + ' to ' + item.savedWindow.end.slice(11, 16) + ' UTC' }),
        item.requestType === 'scalar' ? scalarTable(item.saved.columns, item.saved.data, item.aggs) : savedView(item.saved, item)));
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
    const search = el('input', { type: 'search', placeholder: 'Filter queries, for example lab 1, sql, cpu or logs', 'aria-label': 'Filter queries' });
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
        el('h4', {}, item.title, ' ', labBadge(item), ' ', el('span', { class: 'badge data', text: 'ClickHouse SQL' })),
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
    const source = data.queries.find((query) => query.id === 'c-cpu-samples');
    const samples = source.result.rows
      .map(([time, cores]) => ({ t: Date.parse(time.replace(' ', 'T') + 'Z'), label: time.slice(11, 19), cores: Number(cores) }));
    const bands = source.bands.map((band) => ({ start: Date.parse(band.start), end: Date.parse(band.end), label: band.label }));
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
    const svg = svgEl('svg', { viewBox: '0 0 ' + width + ' ' + height, role: 'img', 'aria-label': source.caption });
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
      el('p', { class: 'why', text: source.caption }),
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

  // A diff shows removed and added lines as block spans, with no newline
  // characters between them. Copying its text would run lines together and keep
  // the removed ones, so a diff copies the code as it reads after the change.
  function codeAfterDiff(code) {
    const lines = [];
    let afterBlock = false;
    code.childNodes.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE && node.classList.contains('ln')) return;
      const isDel = node.nodeType === Node.ELEMENT_NODE && node.classList.contains('del');
      const isAdd = node.nodeType === Node.ELEMENT_NODE && node.classList.contains('add');
      if (isDel || isAdd) {
        if (isAdd) lines.push(node.textContent);
        afterBlock = true;
        return;
      }
      // A block span already ends its line, so a newline right after it is not a new line.
      let text = node.textContent;
      if (afterBlock && text.startsWith('\n')) text = text.slice(1);
      afterBlock = false;
      const parts = text.split('\n');
      parts.forEach((part, index) => {
        if (index < parts.length - 1 || part !== '') lines.push(part);
      });
    });
    // Each line starts with the diff's marker column: a space, or + for added lines.
    return lines.map((line) => (/^[ +]/.test(line) ? line.slice(1) : line)).join('\n') + '\n';
  }

  function setupCodeCopy() {
    document.querySelectorAll('figure.code').forEach((figure) => {
      const caption = figure.querySelector('figcaption');
      const code = figure.querySelector('pre code');
      if (!caption || !code) return;
      if (code.querySelector('.del, .add')) {
        const button = copyButton(codeAfterDiff(code), 'Copy new code');
        button.title = 'Copies the code after this change, without the removed lines';
        caption.append(button);
        return;
      }
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
  setupZoom();
  setupCodeCopy();
  setupResetButton();
  document.querySelectorAll('[data-arch]').forEach(renderArch);
  document.querySelectorAll('[data-quiz]').forEach(setupQuiz);
  document.querySelectorAll('[data-evidence]').forEach(renderEvidence);
  document.querySelectorAll('[data-fire]').forEach(renderFire);
  document.querySelectorAll('[data-load-panel]').forEach(renderLoad);
  document.querySelectorAll('[data-alert-feed]').forEach(renderAlertFeed);
  document.querySelectorAll('[data-investigations]').forEach(renderInvestigations);
  document.querySelectorAll('[data-query]').forEach(renderQuery);
  document.querySelectorAll('[data-query-index]').forEach(renderQueryIndex);
  document.querySelectorAll('[data-ch]').forEach(renderClickHouse);
  document.querySelectorAll('[data-cpu-chart]').forEach(renderCpuChart);
  refreshLab();
  setInterval(refreshLab, 20000);
})();
