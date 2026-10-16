/* WNC 台风轨迹工作台（M3/M4 功能 + M5d 概率特征 + M6 影响概率；三栏布局：左导入与图例 — 中地图 — 右可滚动图表栏）：
 * 数据流：数据集选择 -> 拉取轨迹行 -> 客户端筛选（起报/成员/时效）-> Leaflet 渲染；
 *        (storm, init) 确定后拉取 ensemble-stats -> 均值轨迹/概率半径圆/统计图表；
 *        目标地点（预存/坐标/地图点选）确定后拉取 impact-stats -> 三级影响概率 + 最近接近。
 * 数据纪律：时效档位取实际存在的 lead_h，不插值；缺失保持缺失；不跨起报时次混合；
 *          集合统计口径见 window.STATS_CONFIG（单一事实来源 core.ensemble）。*/

const STATS = window.STATS_CONFIG;
const WIND_SCALE = STATS.categories.map((c) => ({
  min: c.minKt == null ? -Infinity : c.minKt,
  label: c.label,
  color: c.color,
}));
const CATEGORY_BY_KEY = {};
for (const c of STATS.categories) CATEGORY_BY_KEY[c.key] = c;
CATEGORY_BY_KEY[STATS.dissipated.key] = STATS.dissipated;
CATEGORY_BY_KEY[STATS.unknown.key] = STATS.unknown;
const STACK_ORDER = [...STATS.stackBottomUp]; // 自底向上：已消散→TD→…→H5（消散不与 H5 相邻）
const MEAN_COLOR = '#0f172a'; // 自算均值线（风速/气压/轨迹统一深色）

const MEMBER_COLORS = [
  '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4', '#46f0f0',
  '#f032e6', '#bcf60c', '#fabebe', '#008080', '#9a6324', '#800000',
];

const state = {
  datasets: [], fcId: null, obsId: null,
  storm: null, init: null, member: 'ALL', leadCut: null,
  fcRows: [], obsRows: [], leadSteps: [],
  selectedMember: null, lastRowsCount: 0, lastGroupCount: 0,
  stats: null, pSelected: '100', pApplied: '100', selectedKeyLead: null,
  target: null, places: null, impact: null,
};

const $ = (id) => document.getElementById(id);
const statusEl = $('status');

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle('error', isError);
}

function windColor(kt) {
  if (kt == null) return '#888888';
  for (const stop of WIND_SCALE) {
    if (kt >= stop.min) return stop.color;
  }
  return '#888888';
}

const memberColor = (index) => MEMBER_COLORS[index % MEMBER_COLORS.length];

async function api(path, params) {
  const query = params
    ? '?' + new URLSearchParams(
        Object.entries(params).filter(([, v]) => v != null && v !== ''),
      ).toString()
    : '';
  const res = await fetch(path + query);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

/* ---------- 地图 ---------- */

const map = L.map('map', { worldCopyJump: true }).setView([22, 132], 4);
let pickMode = false; // M6 地图点选模式：下一次地图点击作为目标地点（优先于空白取消选中）
map.on('click', (e) => {
  if (pickMode) {
    setTarget(e.latlng.lat, toSignedLon(e.latlng.lng), '地图点选');
    setPickMode(false);
    return;
  }
  // 点击空白（底图/观测层/点位冒泡）取消持久选中（成员与关键标签）
  setMemberSelection(null);
  if (state.selectedKeyLead != null) setSelectedKeyLead(null);
});
L.tileLayer(window.TILE_CONFIG.urlTemplate, {
  attribution: window.TILE_CONFIG.attribution,
  maxZoom: 20, maxNativeZoom: window.TILE_CONFIG.maxZoom,
}).addTo(map);
const forecastLayer = L.layerGroup().addTo(map);
const obsLayer = L.layerGroup().addTo(map);
// 概率圆专用 Canvas renderer：SVG path 的 zoom 增量更新会丢失圆类几何（d="M0 0"），
// Canvas 在视图变化时全量重绘，不受影响。圆均为 interactive:false，
// 画布整体关闭指针事件以免拦截下层成员线的 hover/click
const statsCircleRenderer = L.canvas({ padding: 0.5 });
statsCircleRenderer.on('add', () => {
  statsCircleRenderer._container.style.pointerEvents = 'none';
});
const statsLayer = L.layerGroup().addTo(map);
const targetLayer = L.layerGroup().addTo(map); // M6 目标地点标记与参考圆（最上层）
// 引线标签的像素偏移依赖当前 zoom：视图变化后仅重算锚点坐标（updateStatsAnchors），
// 不重建图层（规避 zoom 动画窗口内矢量层增删与渲染器异步更新的竞态）
let statsAnchorRetimer = null;
map.on('moveend zoomend resize', () => {
  clearTimeout(statsAnchorRetimer);
  statsAnchorRetimer = setTimeout(updateStatsAnchors, 300);
});

function pointCoords(row) {
  if (row.lat == null) return null;
  const lon = row.lon_signed != null ? row.lon_signed : row.lon;
  return lon == null ? null : [row.lat, lon];
}

function toSignedLon(lon) {
  // 0–360° 与 −180–180° 双约定统一（纪律第 3 条）；缺失保持 null
  if (lon == null) return null;
  return ((lon % 360) + 540) % 360 - 180;
}

function popupText(row, groupKey) {
  const lines = [groupKey ? `气旋/成员: ${groupKey}` : ''];
  if (row.member != null) lines.push(`成员: ${row.member}`);
  if (row.valid != null) lines.push(`有效时刻: ${row.valid}`);
  if (row.lead_h != null) lines.push(`时效: ${row.lead_h} h`);
  if (row.wind != null) lines.push(`最大风速: ${row.wind} kt`);
  if (row.pressure != null) lines.push(`中心气压: ${row.pressure} hPa`);
  if (row.lat != null) lines.push(`位置: ${row.lat.toFixed(2)}, ${pointCoords(row)[1].toFixed(2)}`);
  return lines.filter(Boolean).join('<br>');
}

function groupBy(rows, keyFn) {
  const groups = new Map();
  for (const row of rows) {
    const key = keyFn(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  return groups;
}

function sortedUnique(rows, field, numeric = false) {
  const seen = new Set();
  for (const row of rows) {
    const v = row[field];
    if (v != null) seen.add(v);
  }
  const list = [...seen];
  list.sort(numeric ? (a, b) => a - b : (a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));
  return list;
}

/* ---------- 强度曲线（M4 uPlot，与地图同源数据/同配色，双向联动） ---------- */

const markersByKey = new Map(); // `${member}#${lead_h}` -> circleMarker（单成员模式点级联动）
const linesByMember = new Map(); // member -> { line, highlight, shown }
let chart = null;
let chartMembers = [];
let lastHighlight = null;
let hoverMember = null; // 当前 hover 聚焦的成员（临时高亮，与持久选中相互独立）

const fmt = (v) => (v == null ? '—' : v);

/* 光标提示：跟随十字光标显示时次与关键数值（uPlot 无内建 tooltip，叠加于 over 层） */
function makeCursorTip(uplot) {
  const tip = document.createElement('div');
  tip.className = 'cursor-tip';
  tip.style.display = 'none';
  uplot.over.appendChild(tip);
  return (text, leftPx) => {
    if (text == null) { tip.style.display = 'none'; return; }
    tip.textContent = text;
    tip.style.display = 'block';
    const half = tip.offsetWidth / 2 + 4;
    const x = Math.min(Math.max(leftPx, half), uplot.over.clientWidth - half);
    tip.style.left = `${x}px`;
  };
}

function destroyChart() {
  if (chart) { chart.destroy(); chart = null; }
  $('chart-readout').textContent = '';
}

function chartSize() {
  const wrap = $('chart-wrap');
  return {
    width: Math.max(wrap.clientWidth - 16, 60),
    height: Math.max(wrap.clientHeight - 10, 60),
  };
}

function renderChart(rows) {
  destroyChart();
  if (!rows.length || typeof uPlot === 'undefined') return;
  // x 轴档位 = 实际存在的 lead_h（不插值）；数据已与地图同截断于 leadCut
  const leads = [...new Set(rows.map((r) => r.lead_h).filter((v) => v != null))]
    .sort((a, b) => a - b);
  if (!leads.length) return;
  const { width, height } = chartSize();
  const readout = $('chart-readout');
  const baseAxes = [{ label: '时效 (h)', values: (u, vals) => vals.map((v) => `${v}h`) }];

  if (state.member !== 'ALL') {
    const byLead = new Map(rows.map((r) => [r.lead_h, r]));
    const wind = leads.map((l) => byLead.get(l)?.wind ?? null);
    const pres = leads.map((l) => byLead.get(l)?.pressure ?? null);
    let tipUpdate = null;
    chart = new uPlot(
      {
        width, height,
        title: `成员 ${state.member}：风速 / 气压`,
        legend: { show: true, live: true },
        cursor: { drag: { x: false, y: false } },
        scales: { x: { time: false }, y: {}, y2: {} },
        axes: baseAxes.concat([{ label: '风速 (kt)' }, { side: 3, label: '气压 (hPa)' }]),
        series: [
          {},
          { label: '风速 kt', scale: 'y', stroke: '#2563eb', width: 2, points: { space: 14, r: 3 } },
          { label: '气压 hPa', scale: 'y2', stroke: '#dc2626', width: 2, dash: [5, 3], points: { space: 14, r: 3 } },
        ],
        // 注意：uPlot 1.6.32 的 options.hooks 各成员必须为数组（单函数会在 fire 时抛
        // "forEach is not a function"，且联动静默失效）——所有 hooks 一律 [fn] 形式
        hooks: {
          setCursor: [(u) => {
            const idx = u.cursor.idx;
            if (idx == null) {
              highlightMarker(null); readout.textContent = '';
              if (tipUpdate) tipUpdate(null, 0);
              return;
            }
            const lead = u.data[0][idx];
            highlightMarker(lead);
            readout.textContent = `${lead} h | 风 ${fmt(u.data[1][idx])} kt | 压 ${fmt(u.data[2][idx])} hPa`;
            if (tipUpdate) {
              tipUpdate(`${lead}h · 风 ${fmt(u.data[1][idx])} kt · 压 ${fmt(u.data[2][idx])} hPa`, u.cursor.left);
            }
          }],
          ready: [(u) => {
            u.over.addEventListener('click', () => {
              const idx = u.cursor.idx;
              if (idx == null) return;
              const marker = markersByKey.get(`${state.member}#${u.data[0][idx]}`);
              if (marker) { marker.openPopup(); map.panTo(marker.getLatLng()); }
            });
          }],
        },
      },
      [leads, wind, pres],
      $('chart'),
    );
    tipUpdate = makeCursorTip(chart);
    return;
  }

  // 全部成员：每成员风速细线（配色与地图意面图一致，同 groupBy 顺序取色）+ 自算均值粗线
  const groups = groupBy(rows, (r) => r.member ?? '—');
  chartMembers = [...groups.keys()];
  const meanWindByLead = meanSeriesByLead('mean_wind');
  const data = [leads].concat(
    chartMembers.map((m) => {
      const byLead = new Map(groups.get(m).map((r) => [r.lead_h, r.wind]));
      return leads.map((l) => (byLead.has(l) ? byLead.get(l) : null));
    }),
  );
  if (meanWindByLead) data.push(leads.map((l) => meanWindByLead.get(l) ?? null));
  const memberSeries = chartMembers.map((m, i) => ({
    label: `成员 ${m}`,
    stroke: memberColor(i),
    width: 1.2,
    points: { show: false },
    spanGaps: false,
  }));
  // 均值线：深色实线（uPlot stroke 正序、末位在最上层，可见性由层级保证；样式按用户偏好回归原版）
  const meanSeries = meanWindByLead
    ? [{ label: '均值（自算）', stroke: MEAN_COLOR, width: 2.5, points: { show: false }, spanGaps: false }]
    : [];
  const meanDataIndex = 1 + chartMembers.length; // 均值在 data 中的索引
  let tipUpdate = null;
  chart = new uPlot(
    {
      width, height,
      title: '成员风速曲线（深色线 = 自算均值）',
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, prox: 5 },
      scales: { x: { time: false }, y: {} },
      axes: baseAxes.concat([{ label: '风速 (kt)' }]),
      series: [{}].concat(memberSeries, meanSeries),
      hooks: {
        setCursor: [(u) => {
          const idx = u.cursor.idx;
          readout.textContent = idx == null ? '' : `${u.data[0][idx]} h`;
          if (!tipUpdate) return;
          if (idx == null) { tipUpdate(null, 0); return; }
          const lead = u.data[0][idx];
          const meanValue = meanWindByLead ? u.data[meanDataIndex][idx] : null;
          tipUpdate(`${lead}h · 均值 ${meanValue == null ? '—' : meanValue.toFixed(1)} kt`, u.cursor.left);
        }],
        setSeries: [(u, i, value) => {
          const member = chartMembers[i - 1]; // 末位为均值线（无地图联动），索引超界自然跳过
          if (member == null || !linesByMember.has(member)) return;
          const focused = value === true || (value != null && value.focus === true);
          if (focused) {
            if (state.selectedMember !== member) hoverMember = member; // 持久选中的程序聚焦不算 hover
            showMemberHighlight(member);
            readout.textContent = `聚焦 成员 ${member}`;
          } else {
            if (hoverMember === member) hoverMember = null;
            hideMemberHighlight(member); // 选中态时保留（guard）
            if (state.selectedMember === member) {
              focusChartSeries(member, true); // 恢复被图表 prox blur 误关的选中聚焦
            }
          }
        }],
        ready: [(u) => {
          // 图表侧发起选中：点击时若有 hover 聚焦成员，则选中/切换/取消
          u.over.addEventListener('click', () => {
            if (hoverMember != null) {
              setMemberSelection(state.selectedMember === hoverMember ? null : hoverMember);
            }
          });
        }],
      },
    },
    data,
    $('chart'),
  );
  tipUpdate = makeCursorTip(chart);
}

function highlightMarker(lead) {
  if (lastHighlight) { lastHighlight.setStyle({ radius: 4.5, weight: 0.8 }); lastHighlight = null; }
  if (lead == null || state.member === 'ALL') return;
  const marker = markersByKey.get(`${state.member}#${lead}`);
  if (marker) { marker.setStyle({ radius: 7, weight: 2 }); marker.bringToFront(); lastHighlight = marker; }
}

function pointToChart(lead) {
  if (!chart || lead == null) return;
  const px = chart.valToPos(lead, 'x') + chart.bbox.left;
  if (Number.isFinite(px)) chart.setCursor({ left: px });
}

function focusChartSeries(member, on) {
  // 已停用（M5d-R10）：uPlot 的 setSeries({focus}) 在未配置 focus.alpha 时仍会内部淡出
  // 其余 series（曾致 hover 成员时均值线"消失"、被聚焦成员显得像被加粗）。风速图行为
  // 与气压图对齐（无 focus 淡出）；地图↔成员线的 hover/选中高亮由各自事件直接驱动，不受影响。
}

/* ---------- 集合概率特征（M5d）：均值/分布/半径图表 + 地图均值轨迹与 p 圆 ---------- */

let pressureChart = null;
let stackChart = null;
let radiusChart = null;
const meanDotsByKey = new Map(); // lead_h -> circleMarker（统计图表 hover 联动）

function statsVisible() {
  return state.member === 'ALL' && state.stats != null && state.stats.count > 0;
}

function statsByLead() {
  return state.stats ? new Map(state.stats.leads.map((l) => [l.lead_h, l])) : new Map();
}

function meanSeriesByLead(field) {
  if (!statsVisible()) return null;
  return new Map(state.stats.leads.map((l) => [l.lead_h, l[field]]));
}

function destroyStatsCharts() {
  for (const c of [pressureChart, stackChart, radiusChart]) {
    if (c) c.destroy();
  }
  pressureChart = null; stackChart = null; radiusChart = null;
  for (const id of ['pressure-readout', 'stack-readout', 'radius-readout']) {
    $(id).textContent = '';
  }
}

function cardSize(wrapId) {
  const wrap = $(wrapId);
  return { width: Math.max(wrap.clientWidth - 16, 60), height: Math.max(wrap.clientHeight - 10, 60) };
}

function highlightMeanDot(lead) {
  // 与 M4 highlightMarker 同型：放大当前时次的均值点，其余还原（divIcon 用 class 切换）
  for (const [key, dot] of meanDotsByKey) {
    const element = dot.getElement()?.querySelector('.mean-dot-tag');
    element?.classList.toggle('active', key === lead);
  }
}

function statsCursorReadout(u, readout, format) {
  const idx = u.cursor.idx;
  if (idx == null) { highlightMeanDot(null); readout.textContent = ''; return; }
  const lead = u.data[0][idx];
  highlightMeanDot(lead);
  const entry = statsByLead().get(lead);
  readout.textContent = entry ? format(lead, entry) : `${lead} h`;
}

function renderPressureChart() {
  const { width, height } = cardSize('pressure-wrap');
  const rows = currentForecastRows();
  const leads = [...new Set(rows.map((r) => r.lead_h).filter((v) => v != null))].sort((a, b) => a - b);
  const groups = groupBy(rows, (r) => r.member ?? '—');
  const members = [...groups.keys()];
  const meanPressure = meanSeriesByLead('mean_pressure');
  const data = [leads].concat(
    members.map((m) => {
      const byLead = new Map(groups.get(m).map((r) => [r.lead_h, r.pressure]));
      return leads.map((l) => (byLead.has(l) ? byLead.get(l) : null));
    }),
  );
  if (meanPressure) data.push(leads.map((l) => meanPressure.get(l) ?? null));
  const meanDataIndex = 1 + members.length; // 均值在 data 中的索引（末位=最上层）
  const readout = $('pressure-readout');
  let tipUpdate = null;
  pressureChart = new uPlot(
    {
      width, height,
      title: '成员气压曲线（深色线 = 自算均值）',
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, prox: 5 },
      scales: { x: { time: false }, y: {} },
      axes: [{ label: '时效 (h)', values: (u, vals) => vals.map((v) => `${v}h`) }, { label: '气压 (hPa)' }],
      series: [{}].concat(
        members.map((m, i) => ({
          label: `成员 ${m}`,
          stroke: memberColor(i),
          width: 1.2,
          points: { show: false },
          spanGaps: false,
        })),
        meanPressure
          ? [{ label: '均值（自算）', stroke: MEAN_COLOR, width: 2.5, points: { show: false }, spanGaps: false }]
          : [],
      ),
      hooks: {
        setCursor: [(u) => {
          statsCursorReadout(u, readout, (lead, e) => `${lead} h | 均值气压 ${fmt(e.mean_pressure)} hPa | n ${e.n_present}/${e.n_total}`);
          if (!tipUpdate) return;
          const idx = u.cursor.idx;
          if (idx == null) { tipUpdate(null, 0); return; }
          const lead = u.data[0][idx];
          const meanValue = meanPressure ? u.data[meanDataIndex][idx] : null;
          tipUpdate(`${lead}h · 均值气压 ${meanValue == null ? '—' : meanValue.toFixed(1)} hPa`, u.cursor.left);
        }],
      },
    },
    data,
    $('pressure-chart'),
  );
  tipUpdate = makeCursorTip(pressureChart);
}

function renderStackChart() {
  const { width, height } = cardSize('stack-wrap');
  const leads = state.stats.leads.map((l) => l.lead_h);
  const nTotal = state.stats.leads[0]?.n_total ?? 0;
  const hasUnknown = state.stats.leads.some((l) => (l.category_counts[STATS.unknown.key] ?? 0) > 0);
  const order = hasUnknown ? [...STACK_ORDER, STATS.unknown.key] : [...STACK_ORDER];
  // 占比堆叠：各带值 = 累计成员数 / 成员总数 × 100（消散计入分母，各时次合计 100%）
  const cumulative = {};
  let acc = leads.map(() => 0);
  for (const key of order) {
    acc = acc.map((v, i) => v + (state.stats.leads[i].category_counts[key] ?? 0));
    cumulative[key] = acc.map((v) => (nTotal ? +((v * 100) / nTotal).toFixed(2) : 0));
  }
  const data = [leads];
  const series = [{}];
  // uPlot 按数组顺序绘制、后画覆盖先画：不透明填充的堆叠面积需按"视觉自顶向下"排列
  // （顶层带先画整片，后续底层带逐个覆盖到自身累计值，各带可见区域即增量段）
  for (const key of [...order].reverse()) {
    const color = CATEGORY_BY_KEY[key]?.color ?? '#888888';
    data.push(cumulative[key]);
    series.push({
      label: CATEGORY_BY_KEY[key]?.label ?? key,
      stroke: color,
      width: 0.8,
      fill: color,
      points: { show: false },
    });
  }
  const readout = $('stack-readout');
  stackChart = new uPlot(
    {
      width, height,
      title: '强度分布（占成员总数百分比）',
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, prox: 5 },
      scales: { x: { time: false }, y: { range: () => [0, 100] } },
      axes: [
        { label: '时效 (h)', values: (u, vals) => vals.map((v) => `${v}h`) },
        { label: '占比 (%)', values: (u, vals) => vals.map((v) => `${Math.round(v)}%`) },
      ],
      series,
      hooks: {
        setCursor: [(u) => {
          statsCursorReadout(u, readout, (lead, e) => {
            const parts = order
              .map((key) => [key, e.category_counts[key] ?? 0])
              .map(([key, count]) => (count > 0
                ? `${CATEGORY_BY_KEY[key]?.label ?? key} ${Math.round((count * 100) / Math.max(e.n_total, 1))}%(${count})`
                : ''))
              .filter(Boolean);
            return `${lead} h | ${parts.join(' ') || '无成员'} | n ${e.n_present}/${e.n_total}`;
          });
        }],
      },
    },
    data,
    $('stack-chart'),
  );
  $('stack-wrap').setAttribute('data-n-total', String(nTotal));
}

function renderRadiusChart() {
  const { width, height } = cardSize('radius-wrap');
  const leads = state.stats.leads.map((l) => l.lead_h);
  const p = state.pApplied;
  const radius = (l) => l.radius_km[p];
  // 低分母降权：n < 30%×n_total 的时次改虚线（数据保留，仅视觉区分）
  const solid = state.stats.leads.map((l) => (l.low_denominator ? null : radius(l)));
  const dashed = state.stats.leads.map((l) => (l.low_denominator ? radius(l) : null));
  const lowCount = state.stats.leads.filter((l) => l.low_denominator).length;
  const readout = $('radius-readout');
  const seriesDef = lowCount
    ? [
        { label: `p=${p}%`, stroke: '#2563eb', width: 2, points: { space: 14, r: 3 }, spanGaps: false },
        { label: `p=${p}%（低分母 n<${Math.round(STATS.lowDenominatorFraction * 100)}%）`, stroke: '#2563eb', width: 2, dash: [6, 4], points: { space: 14, r: 3 }, spanGaps: false },
      ]
    : [{ label: `p=${p}%`, stroke: '#2563eb', width: 2, points: { space: 14, r: 3 }, spanGaps: false }];
  const data = lowCount ? [leads, solid, dashed] : [leads, solid];
  radiusChart = new uPlot(
    {
      width, height,
      title: `位置概率半径（p = ${p}%）`,
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, prox: 5 },
      scales: { x: { time: false }, y: {} },
      axes: [{ label: '时效 (h)', values: (u, vals) => vals.map((v) => `${v}h`) }, { label: '半径 (km)' }],
      series: [{}].concat(seriesDef),
      hooks: {
        setCursor: [(u) => {
          statsCursorReadout(u, readout, (lead, e) => {
            const r = e.radius_km[p];
            const low = e.low_denominator ? '（低分母）' : '';
            return `${lead} h | 半径 ${r == null ? '—' : `${Math.round(r)} km`} | n ${e.n_present}/${e.n_total}${low}`;
          });
        }],
      },
    },
    data,
    $('radius-chart'),
  );
  $('radius-wrap').setAttribute('data-p', p);
  $('radius-wrap').setAttribute('data-low-count', String(lowCount));
}

function renderStatsCharts() {
  destroyStatsCharts();
  const show = statsVisible();
  for (const id of ['pressure-wrap', 'stack-wrap', 'radius-wrap']) {
    $(id).classList.toggle('hidden', !show);
  }
  if (!show) return;
  renderPressureChart();
  renderStackChart();
  renderRadiusChart();
}

function statsPopupText(lead, entry) {
  const r = entry.radius_km[state.pApplied];
  return [
    `集合统计（自算口径）`,
    `时效: ${lead} h`,
    `分母: ${entry.n_present}/${entry.n_total} 成员`,
    entry.mean_wind != null ? `平均风速: ${Math.round(entry.mean_wind)} kt` : '',
    entry.mean_pressure != null ? `平均气压: ${Math.round(entry.mean_pressure)} hPa` : '',
    r != null ? `p=${state.pApplied}% 半径: ${Math.round(r)} km` : '',
    entry.low_denominator ? `低分母（n < ${Math.round(STATS.lowDenominatorFraction * 100)}%×总成员）` : '',
  ].filter(Boolean).join('<br>');
}

function meanLeadLabel(entry) {
  // 关键时次的均值强度标签：等级色点 + 时效 + 平均风速（缺失保持缺失，不显示 kt）
  const wind = entry.mean_wind != null ? `·${Math.round(entry.mean_wind)}kt` : '';
  const dot = entry.mean_wind != null
    ? `<i style="background:${windColor(entry.mean_wind)}"></i>`
    : '';
  return `<span class="mean-label-tag">${dot}${entry.lead_h}h${wind}</span>`;
}

/* 关键时次标签与圆的选中联动：单选、再点取消、点地图空白取消（与 M4 成员选中同型） */
const keyCircles = new Map(); // lead_h -> L.circle
const keyLabels = new Map(); // lead_h -> { marker, span, leader }
let lastStatsLayout = null; // { drawnLeads, currentLead }：zoom 后仅更新标签/引线坐标，不重建图层
const KEY_CIRCLE_BASE = {
  color: '#1d4ed8', weight: 1.5, opacity: 0.75, fillColor: '#2563eb', fillOpacity: 0.04,
  dashArray: '3 5',
};
const KEY_CIRCLE_HIGHLIGHT = {
  color: '#2563eb', weight: 2.5, opacity: 1, fillColor: '#2563eb', fillOpacity: 0.08,
  dashArray: '3 5',
};

function applyKeySelectionStyles() {
  for (const [lead, circle] of keyCircles) {
    circle.setStyle(state.selectedKeyLead === lead ? KEY_CIRCLE_HIGHLIGHT : KEY_CIRCLE_BASE);
  }
  for (const [, entry] of keyLabels) {
    entry.span.classList.toggle('selected', entry.marker._lead === state.selectedKeyLead);
  }
  const mapEl = $('map'); // E2E/调试锚点（Canvas 圆无 path 元素，挂容器）
  if (state.selectedKeyLead == null) mapEl.removeAttribute('data-key-selected');
  else mapEl.setAttribute('data-key-selected', String(state.selectedKeyLead));
}

function setSelectedKeyLead(lead) {
  const target = lead != null && keyLabels.has(lead) ? lead : null;
  if (target === state.selectedKeyLead) return;
  state.selectedKeyLead = target;
  applyKeySelectionStyles();
}

function labelAnchorNeighbors(drawnLeads, index) {
  // 引线偏移方向：取轨迹相邻时次作切线（首尾点退化为自身与邻点）
  const prev = drawnLeads[Math.max(0, index - 1)];
  const next = drawnLeads[Math.min(drawnLeads.length - 1, index + 1)];
  return [prev, next];
}

function offsetLatLng(center, prev, next, side) {
  // 沿轨迹法线偏移固定像素。用 map.project/unproject 纯投影计算（世界像素=CSS 像素），
  // 不经 latLngToContainerPoint（后者包含 pane transform，zoom 动画收尾窗口内读取会得到
  // 带残留的坐标，曾致锚点地理点系统性漂移）
  const zoom = map.getZoom();
  const c = map.project(center, zoom);
  const p = map.project([prev.mean_lat, toSignedLon(prev.mean_lon)], zoom);
  const n = map.project([next.mean_lat, toSignedLon(next.mean_lon)], zoom);
  const dx = n.x - p.x;
  const dy = n.y - p.y;
  const len = Math.hypot(dx, dy) || 1;
  const px = c.x + (-dy / len) * 55 * side;
  const py = c.y + (dx / len) * 55 * side;
  return map.unproject([px, py], zoom);
}

function destinationPoint(lat, lon, bearingDeg, distKm) {
  // 球面直达点公式（与 core.geo.haversine 同球模型 R=6371.0088）
  const R = 6371.0088;
  const br = bearingDeg * Math.PI / 180;
  const la = lat * Math.PI / 180;
  const lo = lon * Math.PI / 180;
  const dr = distKm / R;
  const la2 = Math.asin(Math.sin(la) * Math.cos(dr) + Math.cos(la) * Math.sin(dr) * Math.cos(br));
  const lo2 = lo + Math.atan2(Math.sin(br) * Math.sin(dr) * Math.cos(la),
    Math.cos(dr) - Math.sin(la) * Math.sin(la2));
  return [la2 * 180 / Math.PI, ((lo2 * 180 / Math.PI + 540) % 360) - 180];
}

function geoCirclePoints(center, radiusKm, segments = 64) {
  // 概率圆用多边形逼近（polyline 家族）：Leaflet SVG 对 circle/circleMarker 的 zoom 几何
  // 重算存在写空缺陷（d="M0 0"），多边形路径不受影响
  const points = [];
  for (let i = 0; i <= segments; i += 1) {
    points.push(destinationPoint(center[0], center[1], (360 / segments) * i, radiusKm));
  }
  return points;
}

function renderStatsLayer() {
  statsLayer.clearLayers();
  meanDotsByKey.clear();
  keyCircles.clear();
  keyLabels.clear();
  $('map').removeAttribute('data-key-leads');
  $('map').removeAttribute('data-current-circle');
  if (!statsVisible()) return;
  const redrawables = []; // 渲染完成后统一强制重绘（Leaflet SVG 异步几何写入在动画窗口内可能缺失）
  const allLeads = state.stats.leads.filter((l) => l.mean_lat != null && l.mean_lon != null);
  const centerOf = (l) => [l.mean_lat, toSignedLon(l.mean_lon)];

  // mean 线截断：自首时次起连续绘制，遇到低分母时次（消散比例 > 1-30% 阈值）即停止延伸
  let cutIndex = allLeads.length;
  for (let i = 0; i < allLeads.length; i += 1) {
    if (allLeads[i].low_denominator) { cutIndex = i; break; }
  }
  const drawnLeads = allLeads.slice(0, cutIndex);
  // 统计图层除关键标签外一律不拦截指针事件（interactive:false），避免遮挡 M4 交互
  if (drawnLeads.length >= 2) {
    const track = L.polyline(drawnLeads.map(centerOf), {
      color: MEAN_COLOR, weight: 3.5, opacity: 0.9, interactive: false,
      smoothFactor: 0, noClip: true,
    }).addTo(statsLayer);
    redrawables.push(track);
    track._path?.setAttribute('data-mean-track', state.storm ?? ''); // E2E/调试锚点
    if (cutIndex < allLeads.length) {
      track._path?.setAttribute('data-mean-cut', String(allLeads[cutIndex].lead_h));
    }
  }
  for (const entry of drawnLeads) {
    // 时次点用 divIcon（HTML 定位）而非 circleMarker：Leaflet SVG 的 circleMarker 几何
    // 在 zoom 重算时会被写成 M0 0（同容器 polyline 正常，属其更新路径缺陷），HTML 定位不受影响
    const dot = L.marker(centerOf(entry), {
      icon: L.divIcon({ className: 'mean-dot', html: '<span class="mean-dot-tag"></span>', iconSize: null }),
      interactive: false, keyboard: false,
    }).addTo(statsLayer);
    dot.getElement()?.setAttribute('data-mean-dot', String(entry.lead_h)); // E2E/调试锚点（引线终点）
    meanDotsByKey.set(entry.lead_h, dot);
  }

  // 滑块当前时次（高亮样式，低分母时次同样绘制，数据不删仅视觉区分）
  const entry = state.stats.leads.find((l) => l.lead_h === state.leadCut)
    ?? allLeads[allLeads.length - 1];
  const currentLead = entry?.lead_h;
  if (entry && entry.mean_lat != null) {
    const marker = L.marker(centerOf(entry), {
      icon: L.divIcon({
        className: 'mean-dot',
        html: '<span class="mean-dot-tag mean-dot-center"></span>',
        iconSize: null,
      }),
      keyboard: false,
    }).bindPopup(statsPopupText(entry.lead_h, entry)).addTo(statsLayer);
    marker.getElement()?.setAttribute('data-mean-center', String(entry.lead_h));
    const radiusKm = entry.radius_km[state.pApplied];
    if (radiusKm != null) {
      const circle = L.polygon(geoCirclePoints(centerOf(entry), radiusKm), {
        color: '#2563eb', weight: 1.5, opacity: 0.9,
        fill: false, dashArray: '6 5', interactive: false,
        smoothFactor: 0, noClip: true, renderer: statsCircleRenderer,
      }).addTo(statsLayer);
      // Canvas 圆无 path 元素：E2E/调试锚点挂到 #map 容器
      $('map').setAttribute('data-current-circle', `${state.pApplied}|${Math.round(radiusKm)}`);
    }
  }

  // 关键时次（24h 倍数的实际存在时次）：概率圆 + 引线式强度标签（法线偏移）；
  // 与 mean 线同口径止于截断点（低分母时次的均值强度不具参考性，不标注），当前时次已高亮故排除
  let keyIndex = 0;
  for (let i = 0; i < drawnLeads.length; i += 1) {
    const l = drawnLeads[i];
    if (l.lead_h % 24 !== 0 || l.lead_h === currentLead) continue;
    const radiusKm = l.radius_km[state.pApplied];
    if (radiusKm == null) continue;
    const center = centerOf(l);
    const circle = L.polygon(geoCirclePoints(center, radiusKm), {
      ...KEY_CIRCLE_BASE, interactive: false, smoothFactor: 0, noClip: true,
      renderer: statsCircleRenderer,
    }).addTo(statsLayer);
    keyCircles.set(l.lead_h, circle);

    // 引线标签：偏移点在轨迹法线方向，关键点奇偶交替两侧，减少与轨迹/彼此重叠
    const [prev, next] = labelAnchorNeighbors(drawnLeads, i);
    const side = keyIndex % 2 === 0 ? 1 : -1;
    keyIndex += 1;
    const anchor = offsetLatLng(center, prev, next, side);
    if (window.__probeRenders) {
      const a = map.latLngToContainerPoint(anchor);
      const c = map.latLngToContainerPoint(center);
      console.log(`[probe-render] lead=${l.lead_h} anchorDist=${Math.round(a.distanceTo(c))} zoom=${map.getZoom()}`);
    }
    const leader = L.polyline([center, anchor], {
      color: MEAN_COLOR, weight: 1, opacity: 0.9, interactive: false,
      smoothFactor: 0, noClip: true,
    }).addTo(statsLayer);
    redrawables.push(leader);
    leader._path?.setAttribute('data-mean-leader', String(l.lead_h));
    const label = L.marker(anchor, {
      icon: L.divIcon({ className: 'mean-label', html: meanLeadLabel(l), iconSize: null }),
      keyboard: false,
    }).addTo(statsLayer);
    label._lead = l.lead_h;
    label.getElement()?.setAttribute('data-mean-label', String(l.lead_h));
    label.on('click', (e) => {
      L.DomEvent.stopPropagation(e); // 阻止冒泡到 map click（空白取消）
      setSelectedKeyLead(state.selectedKeyLead === l.lead_h ? null : l.lead_h);
    });
    keyLabels.set(l.lead_h, { marker: label, leader, span: label.getElement()?.querySelector('.mean-label-tag') });
  }
  applyKeySelectionStyles(); // 重建后恢复选中态
  $('map').setAttribute('data-key-leads', [...keyCircles.keys()].map(String).join(','));
  if (!entry || entry.mean_lat == null || (entry.radius_km[state.pApplied] ?? null) == null) {
    $('map').removeAttribute('data-current-circle');
  }
  lastStatsLayout = { drawnLeads, currentLead };
}

function updateStatsAnchors() {
  // zoom/resize 后仅重算引线标签的偏移锚点（setLatLng 立即生效）。
  // 不在此重建图层：zoom 动画窗口内增删矢量层会与 Leaflet 渲染器的异步几何更新竞态，
  // 曾致部分时次点几何丢失（常驻图层由地图 viewreset 原生重定位，从未受影响）。
  if (!lastStatsLayout || !statsVisible()) return;
  let keyIndex = 0;
  for (let i = 0; i < lastStatsLayout.drawnLeads.length; i += 1) {
    const l = lastStatsLayout.drawnLeads[i];
    if (l.lead_h % 24 !== 0 || l.lead_h === lastStatsLayout.currentLead) continue;
    const entry = keyLabels.get(l.lead_h);
    if (!entry) continue;
    const center = [l.mean_lat, toSignedLon(l.mean_lon)];
    const [prev, next] = labelAnchorNeighbors(lastStatsLayout.drawnLeads, i);
    const anchor = offsetLatLng(center, prev, next, keyIndex % 2 === 0 ? 1 : -1);
    keyIndex += 1;
    entry.marker.setLatLng(anchor);
    entry.leader.setLatLngs([center, anchor]);
  }
}

async function loadStats() {
  state.stats = null;
  if (!state.fcId || !state.storm || !state.init) { render(); await loadImpact(); return; }
  try {
    state.stats = await api(`/api/datasets/${state.fcId}/ensemble-stats`, {
      storm: state.storm, init: state.init,
    });
  } catch (err) {
    state.stats = null;
    setStatus(`集合统计获取失败：${err.message}`, true);
  }
  render();
  await loadImpact(); // (storm, init) 变化后目标地点影响统计同步刷新
}

/* ---------- 目标地点与影响概率（M6）：预存地点/坐标输入/地图点选 + 三级概率与最近接近 ---------- */

const TARGET_REFERENCE_RADII = [100, 200, 400, 800]; // 参考圆半径 km（仅视觉参考，不参与判定）
// M7a 分级配色：每圈一色（玫红/橙/金/紫，已避让强度色阶、成员色与概率圆蓝），
// 实线 2px/0.9 不透明，明暗瓦片下均易辨认；色值与左栏图例同源
const TARGET_REFERENCE_CIRCLE_COLORS = { 100: '#db2777', 200: '#ea580c', 400: '#ca8a04', 800: '#6d28d9' };

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}

function targetLabel() {
  const t = state.target;
  if (!t) return '';
  const coords = `${t.lat.toFixed(4)}, ${t.lon.toFixed(4)}`;
  return t.label ? `${t.label}（${coords}）` : coords;
}

function renderTargetLayer() {
  targetLayer.clearLayers();
  $('map').removeAttribute('data-target-circles');
  if (!state.target) return;
  const center = [state.target.lat, state.target.lon];
  const marker = L.marker(center, {
    icon: L.divIcon({ className: 'target-pin', html: '<span class="target-dot-tag"></span>', iconSize: null }),
    keyboard: false,
  }).addTo(targetLayer);
  marker.getElement()?.setAttribute('data-target-marker', `${state.target.lat.toFixed(4)},${state.target.lon.toFixed(4)}`);
  marker.bindPopup([
    `<b>目标地点：${escapeHtml(state.target.label ?? '临时坐标')}</b>`,
    `坐标: ${state.target.lat.toFixed(4)}, ${state.target.lon.toFixed(4)}`,
    `参考圆: ${TARGET_REFERENCE_RADII.join('/')} km（仅视觉参考，不参与判定）`,
  ].join('<br>'));
  for (let i = TARGET_REFERENCE_RADII.length - 1; i >= 0; i -= 1) {
    const radius = TARGET_REFERENCE_RADII[i];
    // 大圆先画小圆后画（Canvas 后画在上层）；与概率圆同渲染器，不拦截下层交互
    L.polygon(geoCirclePoints(center, radius), {
      color: TARGET_REFERENCE_CIRCLE_COLORS[radius], weight: 2, opacity: 0.9,
      fill: false, interactive: false, smoothFactor: 0, noClip: true,
      renderer: statsCircleRenderer,
    }).addTo(targetLayer);
  }
  $('map').setAttribute('data-target-circles', TARGET_REFERENCE_RADII.join(','));
}

function setTarget(lat, lon, label) {
  // 经度已在 [-180,180] 内时原值保留（toSignedLon 的模运算会引入浮点尾差）
  const lonValue = lon >= -180 && lon <= 180 ? lon : toSignedLon(lon);
  state.target = { lat, lon: lonValue, label: label ?? null };
  $('target-lat').value = String(state.target.lat);
  $('target-lon').value = String(state.target.lon);
  renderTargetLayer();
  setStatus(`目标地点：${targetLabel()}`);
  void loadImpact();
}

function clearTarget() {
  state.target = null;
  state.impact = null;
  $('target-lat').value = '';
  $('target-lon').value = '';
  $('place-select').value = '';
  targetLayer.clearLayers();
  $('map').removeAttribute('data-target-circles');
  renderImpactCard();
}

function setPickMode(on) {
  pickMode = on;
  $('map').classList.toggle('pick', on);
  if (on) $('map').setAttribute('data-pick-mode', '1');
  else $('map').removeAttribute('data-pick-mode');
  $('target-pick').textContent = on ? '点选中…（点击地图）' : '地图点选';
}

async function loadImpact() {
  state.impact = null;
  if (!state.target || !state.fcId || !state.storm || !state.init) { renderImpactCard(); return; }
  try {
    state.impact = await api(`/api/datasets/${state.fcId}/impact-stats`, {
      lat: state.target.lat, lon: state.target.lon, storm: state.storm, init: state.init,
    });
  } catch (err) {
    state.impact = { error: err.message }; // 如缺风圈列：显式展示不可用原因，不回退
  }
  renderImpactCard();
}

function renderImpactCard() {
  const wrap = $('impact-wrap');
  const body = $('impact-body');
  if (!state.target) { wrap.classList.add('hidden'); body.innerHTML = ''; return; }
  wrap.classList.remove('hidden');
  if (!state.impact) { body.innerHTML = '<p class="muted">影响统计计算中…</p>'; return; }
  if (state.impact.error) {
    wrap.removeAttribute('data-impact-total');
    body.innerHTML = `<p class="impact-error">${escapeHtml(state.impact.error)}</p>`;
    return;
  }
  const data = state.impact;
  const rows = data.thresholds.map((t) => {
    const pct = t.fraction == null ? '—' : `${(t.fraction * 100).toFixed(1)}%`;
    return `<div class="impact-row"><span>${escapeHtml(t.label)}</span>` +
      `<span class="impact-value">${pct}<span class="muted-inline">${t.hit_members}/${t.total_members} 成员</span></span></div>`;
  }).join('');
  const c = data.closest;
  const when = c && c.valid ? `（${c.valid.replace('T', ' ').slice(0, 16)}Z）` : '';
  const closestHtml = c
    ? '<h3>最近接近（mean 口径）</h3>' +
      `<div class="impact-row"><span>时效</span><span>${c.lead_h} h${when}</span></div>` +
      `<div class="impact-row"><span>距离</span><span>${Math.round(c.distance_km)} km</span></div>` +
      `<div class="impact-row"><span>气旋方位</span><span>${escapeHtml(c.compass)}（${c.bearing_deg.toFixed(1)}°）</span></div>` +
      `<div class="impact-row"><span>强度（自算均值）</span><span>风 ${c.mean_wind == null ? '—' : c.mean_wind.toFixed(0)} kt / 压 ${c.mean_pressure == null ? '—' : c.mean_pressure.toFixed(0)} hPa</span></div>`
    : '<p class="muted">无有效均值位置，最近接近不可用</p>';
  body.innerHTML = `<h3>目标：${escapeHtml(targetLabel())}</h3>` + rows + closestHtml;
  wrap.setAttribute('data-impact-total', String(data.thresholds[0]?.total_members ?? ''));
}

async function loadPlaces() {
  try {
    state.places = await api('/api/places');
  } catch (err) {
    state.places = { available: false, places: [], warnings: [`预存地点获取失败：${err.message}`] };
  }
  const list = state.places?.places ?? [];
  const options = [{
    value: '',
    label: list.length ? '— 选择预存地点 —' : '— 无预存地点（填坐标或地图点选）—',
  }].concat(list.map((p) => ({ value: p.name, label: p.note ? `${p.name}（${p.note}）` : p.name })));
  fillSelect($('place-select'), options, false);
  $('place-warnings').textContent = (state.places?.warnings ?? []).join('\n');
}

/* 成员线高亮：不改原线颜色/粗细，叠加同色低透明度光晕层使其显眼；
 * 选中成员或正被 hover 的成员光晕常显（hide 内建 guard） */
function showMemberHighlight(member) {
  const entry = linesByMember.get(member);
  if (!entry || entry.shown) return;
  forecastLayer.addLayer(entry.highlight);
  entry.highlight._path?.setAttribute('data-highlight', member); // E2E/调试锚点
  entry.shown = true;
}

function hideMemberHighlight(member) {
  if (member === state.selectedMember || member === hoverMember) return;
  const entry = linesByMember.get(member);
  if (!entry || !entry.shown) return;
  forecastLayer.removeLayer(entry.highlight);
  entry.shown = false;
}

/* 持久选中：光晕常显 + 曲线聚焦保持；点线选中/再点同线取消（toggle）/点空白取消 */
function setMemberSelection(member) {
  const target = member != null && linesByMember.has(member) ? member : null;
  const previous = state.selectedMember;
  if (target === previous) return;
  state.selectedMember = target; // 先更新状态：hide 的 guard 据此放行旧选中光晕的移除
  if (previous != null) {
    hideMemberHighlight(previous); // guard：若正被 hover，光晕交由 mouseout 收
    if (previous !== hoverMember) focusChartSeries(previous, false);
  }
  if (target != null) {
    showMemberHighlight(target);
    focusChartSeries(target, true);
  }
  updateStatusBar();
}

function updateStatusBar() {
  const selectedInfo = state.selectedMember != null
    ? `；已选中: 成员 ${state.selectedMember}（再点该线或点空白取消）`
    : '';
  setStatus(`预报 ${state.lastRowsCount} 行 / 成员 ${state.lastGroupCount} 组` +
    (state.obsId ? `；观测叠加 ${state.obsRows.length} 行` : '') + selectedInfo);
}

/* ---------- 渲染 ---------- */

function currentForecastRows() {
  return state.fcRows.filter((row) => {
    if (state.init != null && row.init !== state.init) return false;
    if (state.member !== 'ALL' && row.member !== state.member) return false;
    if (state.leadCut != null && row.lead_h != null && row.lead_h > state.leadCut + 1e-9) return false;
    return true;
  });
}

function render() {
  forecastLayer.clearLayers();
  obsLayer.clearLayers();
  markersByKey.clear();
  linesByMember.clear();
  lastHighlight = null;

  const bounds = [];
  const rows = currentForecastRows();
  const singleMember = state.member !== 'ALL';
  const groups = groupBy(rows, (r) => `${r.storm ?? r.name ?? '?'}#${r.member ?? '—'}`);
  let colorIndex = 0;
  for (const [key, group] of groups) {
    const memberKey = group[0].member ?? '—';
    const coords = group.map(pointCoords).filter(Boolean);
    if (coords.length >= 2) {
      const line = L.polyline(coords, {
        color: singleMember ? '#374151' : memberColor(colorIndex),
        weight: singleMember ? 3 : 1.4,
        opacity: 0.85,
      }).addTo(forecastLayer);
      if (!singleMember) {
        // 高亮光晕层：同色、加宽、低透明度、不可交互；默认隐藏，hover/持久选中时叠加
        const highlight = L.polyline(coords, {
          color: memberColor(colorIndex), weight: 9, opacity: 0.35, interactive: false,
        });
        linesByMember.set(memberKey, { line, highlight, shown: false });
        line._path?.setAttribute('data-member', memberKey); // E2E/调试锚点
        line.on('mouseover', () => {
          hoverMember = memberKey;
          showMemberHighlight(memberKey);
          focusChartSeries(memberKey, true);
        });
        line.on('mouseout', () => {
          if (hoverMember === memberKey) hoverMember = null;
          hideMemberHighlight(memberKey); // 选中态时保留（guard）
          if (memberKey !== state.selectedMember) focusChartSeries(memberKey, false);
        });
        line.on('click', (e) => {
          L.DomEvent.stopPropagation(e); // 阻止冒泡到 map click（空白取消）
          setMemberSelection(state.selectedMember === memberKey ? null : memberKey);
        });
      }
    }
    if (singleMember) {
      for (const row of group) {
        const c = pointCoords(row);
        if (!c) continue;
        bounds.push(c);
        const marker = L.circleMarker(c, {
          radius: 4.5, color: '#333', weight: 0.8,
          fillColor: windColor(row.wind), fillOpacity: 0.95,
        }).bindPopup(popupText(row, key)).addTo(forecastLayer);
        markersByKey.set(`${row.member ?? '—'}#${row.lead_h}`, marker);
        marker.on('mouseover', () => pointToChart(row.lead_h));
      }
    } else {
      for (const c of coords) bounds.push(c);
    }
    colorIndex += 1;
  }

  if (state.obsId) {
    const obsGroups = groupBy(state.obsRows, (r) => `${r.storm ?? r.name ?? '?'}`);
    for (const [key, group] of obsGroups) {
      const coords = group.map(pointCoords).filter(Boolean);
      if (coords.length >= 2) {
        L.polyline(coords, { color: '#111111', weight: 2, dashArray: '6,6' }).addTo(obsLayer);
      }
      for (const row of group) {
        const c = pointCoords(row);
        if (!c) continue;
        bounds.push(c);
        L.circleMarker(c, {
          radius: 3, color: '#111111', weight: 1, fillColor: '#111111', fillOpacity: 0.9,
        }).bindPopup(popupText(row, `观测: ${key}`)).addTo(obsLayer);
      }
    }
  }

  if (bounds.length) {
    map.fitBounds(L.latLngBounds(bounds).pad(0.08));
  }
  state.lastRowsCount = rows.length;
  state.lastGroupCount = groups.size;
  // 恢复持久选中：成员仍在当前数据中才保留，否则清除
  if (state.selectedMember != null && !linesByMember.has(state.selectedMember)) {
    state.selectedMember = null;
  }
  if (state.selectedMember != null) showMemberHighlight(state.selectedMember);
  updateStatusBar();
  renderChart(rows); // 重建后由其内部恢复选中成员的曲线聚焦
  renderStatsLayer(); // M5d：均值轨迹 + 滑块当前时次的 p 半径圆
  renderStatsCharts(); // M5d：气压/强度分布/概率半径图表（单成员模式自动隐藏）
}

/* ---------- 控件联动 ---------- */

function fillSelect(select, options, keepValue) {
  const previous = keepValue ? select.value : null;
  select.innerHTML = '';
  for (const opt of options) {
    const el = document.createElement('option');
    el.value = opt.value;
    el.textContent = opt.label;
    select.appendChild(el);
  }
  if (previous && options.some((o) => o.value === previous)) select.value = previous;
}

function datasetLabel(meta) {
  const when = (meta.created_at || '').slice(0, 16).replace('T', ' ');
  return `${meta.original_filename}（${meta.kind}, ${meta.rows}行, ${when}）`;
}

function refreshDatasets() {
  const forecasts = state.datasets.filter((d) => d.kind === 'forecast');
  const observations = state.datasets.filter((d) => d.kind === 'observation');

  fillSelect($('fc-dataset'), forecasts.map((d) => ({ value: d.dataset_id, label: datasetLabel(d) })), true);
  fillSelect(
    $('obs-dataset'),
    [{ value: '', label: '— 无观测叠加 —' }].concat(
      observations.map((d) => ({ value: d.dataset_id, label: datasetLabel(d) })),
    ),
    true,
  );
  state.fcId = $('fc-dataset').value || null;
  state.obsId = $('obs-dataset').value || null;
  if (!forecasts.length) {
    fillSelect($('storm'), [{ value: '', label: '（先导入预报数据集）' }]);
    fillSelect($('init'), [{ value: '', label: '—' }]);
    fillSelect($('member'), [{ value: 'ALL', label: '全部成员' }]);
  }
}

async function loadStormOptions() {
  const meta = state.datasets.find((d) => d.dataset_id === state.fcId);
  if (!meta) { state.fcRows = []; state.stats = null; render(); return; }
  fillSelect(
    $('storm'),
    meta.summary.storms.map((s) => ({
      value: s.storm,
      label: `${s.storm}（${s.rows}行，成员${s.member_count ?? '—'}，时效 ${s.lead_min ?? '?'}–${s.lead_max ?? '?'} h）`,
    })),
    true,
  );
  await onStormChange();
}

async function onStormChange() {
  state.storm = $('storm').value || null;
  if (!state.fcId || !state.storm) { state.fcRows = []; render(); return; }
  try {
    const body = await api(`/api/datasets/${state.fcId}/tracks`, { storm: state.storm });
    state.fcRows = body.rows;
  } catch (err) {
    state.fcRows = [];
    setStatus(`预报轨迹获取失败：${err.message}`, true);
    return;
  }
  const inits = sortedUnique(state.fcRows, 'init');
  fillSelect($('init'), inits.length
    ? inits.map((v) => ({ value: v, label: v.replace('T', ' ').slice(0, 16) + 'Z' }))
    : [{ value: '', label: '（无起报字段）' }]);
  state.init = inits.length ? inits[0] : null;

  const members = sortedUnique(state.fcRows, 'member');
  fillSelect($('member'),
    [{ value: 'ALL', label: `全部成员（${members.length}）` }].concat(
      members.map((v) => ({ value: v, label: `成员 ${v}` })),
    ));
  state.member = 'ALL';

  const steps = sortedUnique(state.fcRows, 'lead_h', true);
  state.leadSteps = steps;
  const slider = $('lead');
  slider.max = String(Math.max(0, steps.length - 1));
  slider.value = slider.max;
  state.leadCut = steps.length ? steps[steps.length - 1] : null;
  $('lead-label').textContent = '全部';
  await loadStats(); // (storm, init) 就绪后拉取集合统计并渲染
}

async function onObsChange() {
  state.obsId = $('obs-dataset').value || null;
  state.obsRows = [];
  if (state.obsId) {
    try {
      const body = await api(`/api/datasets/${state.obsId}/tracks`,
        state.storm ? { storm: state.storm } : {});
      state.obsRows = body.rows;
    } catch (err) {
      try {
        const body = await api(`/api/datasets/${state.obsId}/tracks`, {});
        state.obsRows = body.rows;
        setStatus(`观测数据集中未找到气旋 ${state.storm}，已显示全部观测轨迹`, false);
      } catch (err2) {
        setStatus(`观测叠加获取失败：${err2.message}`, true);
      }
    }
  }
  render();
}

/* ---------- 事件绑定与初始化 ---------- */

$('upload-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = $('upload-file').files[0];
  if (!file) { setStatus('请选择 CSV 文件', true); return; }
  const body = new FormData();
  body.append('file', file);
  body.append('kind', $('upload-kind').value);
  setStatus('上传解析中…');
  try {
    const res = await fetch('/api/datasets', { method: 'POST', body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    setStatus(`导入成功：${data.dataset_id}（${data.rows} 行，${(data.summary.storms || []).length} 个气旋）`);
    state.datasets = (await api('/api/datasets')).datasets;
    refreshDatasets();
    const kind = data.kind;
    if (kind === 'forecast') {
      $('fc-dataset').value = data.dataset_id;
      state.fcId = data.dataset_id;
      await loadStormOptions();
    } else {
      $('obs-dataset').value = data.dataset_id;
      await onObsChange();
    }
  } catch (err) {
    setStatus(`导入失败：${err.message}`, true);
  }
});

$('fc-dataset').addEventListener('change', async () => {
  state.fcId = $('fc-dataset').value || null;
  await loadStormOptions();
  await onObsChange();
});
$('storm').addEventListener('change', async () => { await onStormChange(); await onObsChange(); });
$('init').addEventListener('change', () => { state.init = $('init').value || null; void loadStats(); });
$('member').addEventListener('change', () => {
  state.member = $('member').value || 'ALL';
  state.selectedMember = null; // 切换成员视图模式时清除持久选中
  render();
});
$('lead').addEventListener('input', () => {
  const idx = Number($('lead').value);
  state.leadCut = state.leadSteps.length ? state.leadSteps[idx] : null;
  $('lead-label').textContent = state.leadCut == null ? '全部' : `${state.leadCut} h`;
  render();
});
$('obs-dataset').addEventListener('change', onObsChange);

/* M6 目标地点：预存地点下拉 / 坐标应用（Enter 同效）/ 地图点选开关 / 清除 */
$('place-select').addEventListener('change', () => {
  const name = $('place-select').value;
  if (!name) return;
  const place = (state.places?.places ?? []).find((p) => p.name === name);
  if (place) setTarget(place.lat, place.lon, place.name);
});
function applyTargetInputs() {
  const lat = Number.parseFloat($('target-lat').value.trim());
  const lon = Number.parseFloat($('target-lon').value.trim());
  if (!Number.isFinite(lat) || !Number.isFinite(lon) ||
      lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    setStatus('目标坐标无效：需 lat∈[-90,90]、lon∈[-180,180]（十进制度）', true);
    return;
  }
  setTarget(lat, lon, null);
}
$('target-apply').addEventListener('click', applyTargetInputs);
for (const id of ['target-lat', 'target-lon']) {
  $(id).addEventListener('keydown', (event) => {
    if (event.key === 'Enter') applyTargetInputs();
  });
}
$('target-pick').addEventListener('click', () => setPickMode(!pickMode));
$('target-clear').addEventListener('click', () => { setPickMode(false); clearTarget(); });

/* p 下拉 + 应用按钮：切换 p 仅暂存，点击"应用"才重绘（半径/圆/读数） */
(function initPSelect() {
  const select = $('p-select');
  for (const value of STATS.pValues) {
    const el = document.createElement('option');
    el.value = String(value);
    el.textContent = `${value}%`;
    select.appendChild(el);
  }
  select.value = state.pApplied;
})();
$('p-select').addEventListener('change', () => { state.pSelected = $('p-select').value; });
$('p-apply').addEventListener('click', () => {
  state.pApplied = state.pSelected;
  render(); // 地图圆 + 半径曲线 + 弹窗读数统一按已应用的 p 重绘
});

(function initLegend() {
  const box = $('legend');
  // 与堆叠图同源同色：强度条目之外扩充"已消散"（成员未输出该时次），单一图例避免两套口径
  const stops = [...WIND_SCALE, { label: `${STATS.dissipated.label}（成员未输出该时次）`, color: STATS.dissipated.color }];
  for (const stop of stops) {
    const item = document.createElement('div');
    item.className = 'item';
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.style.background = stop.color;
    item.appendChild(chip);
    item.appendChild(document.createTextNode(stop.label));
    box.appendChild(item);
  }
})();

/* M7a 参考圆图例：环样式色值与地图参考圆同源（TARGET_REFERENCE_CIRCLE_COLORS），不另立口径 */
(function initTargetCircleLegend() {
  const box = $('target-circle-legend');
  for (const radius of TARGET_REFERENCE_RADII) {
    const item = document.createElement('span');
    item.className = 'item';
    const ring = document.createElement('span');
    ring.className = 'ring';
    ring.style.borderColor = TARGET_REFERENCE_CIRCLE_COLORS[radius];
    item.appendChild(ring);
    item.appendChild(document.createTextNode(`${radius} km`));
    box.appendChild(item);
  }
})();

(async function init() {
  void loadPlaces(); // 预存地点独立加载（失败仅提示，不阻塞工作台）
  try {
    state.datasets = (await api('/api/datasets')).datasets;
  } catch (err) {
    setStatus(`数据集列表获取失败：${err.message}`, true);
    return;
  }
  refreshDatasets();
  if (state.fcId) await loadStormOptions();
})();

// 窗口尺寸变化重建全部图表（地图 Leaflet 自适应）
let chartResizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(chartResizeTimer);
  chartResizeTimer = setTimeout(() => {
    renderChart(currentForecastRows());
    if (statsVisible()) {
      destroyStatsCharts();
      renderPressureChart();
      renderStackChart();
      renderRadiusChart();
    }
  }, 150);
});
