/* WNC 台风轨迹工作台（M3/M4 功能 + M5d 概率特征；三栏布局：左导入与图例 — 中地图 — 右可滚动图表栏）：
 * 数据流：数据集选择 -> 拉取轨迹行 -> 客户端筛选（起报/成员/时效）-> Leaflet 渲染；
 *        (storm, init) 确定后拉取 ensemble-stats -> 均值轨迹/概率半径圆/统计图表。
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
  stats: null, pSelected: '100', pApplied: '100',
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
map.on('click', () => setMemberSelection(null)); // 点击空白（底图/观测层/点位冒泡）取消持久选中
L.tileLayer(window.TILE_CONFIG.urlTemplate, {
  attribution: window.TILE_CONFIG.attribution,
  maxZoom: 20, maxNativeZoom: window.TILE_CONFIG.maxZoom,
}).addTo(map);
const forecastLayer = L.layerGroup().addTo(map);
const obsLayer = L.layerGroup().addTo(map);
const statsLayer = L.layerGroup().addTo(map);

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
  const cutoff = state.leadCut == null ? '全部' : `${state.leadCut} h`;
  const baseAxes = [{ label: '时效 (h)', values: (u, vals) => vals.map((v) => `${v}h`) }];

  if (state.member !== 'ALL') {
    const byLead = new Map(rows.map((r) => [r.lead_h, r]));
    const wind = leads.map((l) => byLead.get(l)?.wind ?? null);
    const pres = leads.map((l) => byLead.get(l)?.pressure ?? null);
    chart = new uPlot(
      {
        width, height,
        title: `成员 ${state.member}：风速/气压（截至 ${cutoff}）`,
        legend: { show: true, live: true },
        cursor: { drag: { x: false, y: false } },
        scales: { x: { time: false }, y: {}, y2: {} },
        axes: baseAxes.concat([{ label: '风速 (kt)' }, { side: 3, label: '气压 (hPa)' }]),
        series: [
          {},
          { label: '风速 kt', scale: 'y', stroke: '#2563eb', width: 2, points: { space: 14, r: 3 } },
          { label: '气压 hPa', scale: 'y2', stroke: '#dc2626', width: 2, dash: [5, 3], points: { space: 14, r: 3 } },
        ],
        hooks: {
          setCursor: (u) => {
            const idx = u.cursor.idx;
            if (idx == null) { highlightMarker(null); readout.textContent = ''; return; }
            const lead = u.data[0][idx];
            highlightMarker(lead);
            readout.textContent = `${lead} h | 风 ${fmt(u.data[1][idx])} kt | 压 ${fmt(u.data[2][idx])} hPa`;
          },
          ready: (u) => {
            u.over.addEventListener('click', () => {
              const idx = u.cursor.idx;
              if (idx == null) return;
              const marker = markersByKey.get(`${state.member}#${u.data[0][idx]}`);
              if (marker) { marker.openPopup(); map.panTo(marker.getLatLng()); }
            });
          },
        },
      },
      [leads, wind, pres],
      $('chart'),
    );
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
  const meanSeries = meanWindByLead
    ? [{ label: '均值（自算）', stroke: MEAN_COLOR, width: 2.5, points: { show: false }, spanGaps: false }]
    : [];
  chart = new uPlot(
    {
      width, height,
      title: `成员风速曲线（${chartMembers.length} 成员，配色与地图一致；深色为自算均值）`,
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, prox: 5 },
      focus: { alpha: 0.12 },
      scales: { x: { time: false }, y: {} },
      axes: baseAxes.concat([{ label: '风速 (kt)' }]),
      series: [{}].concat(memberSeries, meanSeries),
      hooks: {
        setCursor: (u) => {
          const idx = u.cursor.idx;
          readout.textContent = idx == null ? '' : `${u.data[0][idx]} h`;
        },
        setSeries: (u, i, value) => {
          const member = chartMembers[i - 1];
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
        },
        ready: (u) => {
          // 图表侧发起选中：点击时若有 hover 聚焦成员，则选中/切换/取消
          u.over.addEventListener('click', () => {
            if (hoverMember != null) {
              setMemberSelection(state.selectedMember === hoverMember ? null : hoverMember);
            }
          });
        },
      },
    },
    data,
    $('chart'),
  );
  // 重建后恢复持久选中的曲线聚焦（触发 setSeries hook，光晕幂等）
  if (state.selectedMember != null) {
    const idx = chartMembers.indexOf(state.selectedMember);
    if (idx >= 0) chart.setSeries(idx + 1, { focus: true });
  }
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
  if (!chart || state.member !== 'ALL') return;
  const idx = chartMembers.indexOf(member);
  if (idx >= 0) chart.setSeries(idx + 1, { focus: on });
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
  // 与 M4 highlightMarker 同型：放大当前时次的均值点，其余还原
  for (const [key, dot] of meanDotsByKey) {
    const active = key === lead;
    dot.setStyle({ radius: active ? 7 : 2.5, weight: active ? 2 : 0.5 });
    if (active) dot.bringToFront();
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
  const readout = $('pressure-readout');
  pressureChart = new uPlot(
    {
      width, height,
      title: `成员气压曲线（${members.length} 成员，配色与地图一致；深色为自算均值）`,
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
        setCursor: (u) => { statsCursorReadout(u, readout, (lead, e) => `${lead} h | 均值气压 ${fmt(e.mean_pressure)} hPa | n ${e.n_present}/${e.n_total}`); },
      },
    },
    data,
    $('pressure-chart'),
  );
}

function renderStackChart() {
  const { width, height } = cardSize('stack-wrap');
  const leads = state.stats.leads.map((l) => l.lead_h);
  const nTotal = state.stats.leads[0]?.n_total ?? 0;
  const hasUnknown = state.stats.leads.some((l) => (l.category_counts[STATS.unknown.key] ?? 0) > 0);
  const order = hasUnknown ? [...STACK_ORDER, STATS.unknown.key] : [...STACK_ORDER];
  // 占比堆叠：各带值 = 累计成员数 / 成员总数 × 100（消散计入分母，各时次合计 100%）
  let acc = leads.map(() => 0);
  const data = [leads];
  const series = [{}];
  for (const key of order) {
    acc = acc.map((v, i) => v + (state.stats.leads[i].category_counts[key] ?? 0));
    const share = acc.map((v) => (nTotal ? +((v * 100) / nTotal).toFixed(2) : 0));
    data.push(share);
    // 不透明填充：上层完全覆盖下层，各带颜色与左栏图例一致（透明填充会与下层混色）
    series.push({
      label: CATEGORY_BY_KEY[key]?.label ?? key,
      stroke: CATEGORY_BY_KEY[key]?.color ?? '#888888',
      width: 0.8,
      fill: CATEGORY_BY_KEY[key]?.color ?? '#888888',
      points: { show: false },
    });
  }
  const readout = $('stack-readout');
  stackChart = new uPlot(
    {
      width, height,
      title: '强度分布（占成员总数百分比；自底向上：已消散→TD→…→H5）',
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, prox: 5 },
      scales: { x: { time: false }, y: { range: () => [0, 100] } },
      axes: [
        { label: '时效 (h)', values: (u, vals) => vals.map((v) => `${v}h`) },
        { label: '占比 (%)', values: (u, vals) => vals.map((v) => `${Math.round(v)}%`) },
      ],
      series,
      hooks: {
        setCursor: (u) => {
          statsCursorReadout(u, readout, (lead, e) => {
            const parts = order
              .map((key) => [key, e.category_counts[key] ?? 0])
              .map(([key, count]) => (count > 0
                ? `${CATEGORY_BY_KEY[key]?.label ?? key} ${Math.round((count * 100) / Math.max(e.n_total, 1))}%(${count})`
                : ''))
              .filter(Boolean);
            return `${lead} h | ${parts.join(' ') || '无成员'} | n ${e.n_present}/${e.n_total}`;
          });
        },
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
      title: `位置概率半径（覆盖离均值中心最近 ${p}% 成员的最小半径；圆心=球面均值）`,
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, prox: 5 },
      scales: { x: { time: false }, y: {} },
      axes: [{ label: '时效 (h)', values: (u, vals) => vals.map((v) => `${v}h`) }, { label: '半径 (km)' }],
      series: [{}].concat(seriesDef),
      hooks: {
        setCursor: (u) => {
          statsCursorReadout(u, readout, (lead, e) => {
            const r = e.radius_km[p];
            const low = e.low_denominator ? '（低分母）' : '';
            return `${lead} h | 半径 ${r == null ? '—' : `${Math.round(r)} km`} | n ${e.n_present}/${e.n_total}${low}`;
          });
        },
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

function renderStatsLayer() {
  statsLayer.clearLayers();
  meanDotsByKey.clear();
  if (!statsVisible()) return;
  const allLeads = state.stats.leads.filter((l) => l.mean_lat != null && l.mean_lon != null);
  const centerOf = (l) => [l.mean_lat, toSignedLon(l.mean_lon)];

  // mean 线截断：自首时次起连续绘制，遇到低分母时次（消散比例 > 1-30% 阈值）即停止延伸
  let cutIndex = allLeads.length;
  for (let i = 0; i < allLeads.length; i += 1) {
    if (allLeads[i].low_denominator) { cutIndex = i; break; }
  }
  const drawnLeads = allLeads.slice(0, cutIndex);
  // 统计图层一律不拦截地图/成员线的指针事件（interactive:false），避免遮挡 M4 交互
  if (drawnLeads.length >= 2) {
    const track = L.polyline(drawnLeads.map(centerOf), {
      color: MEAN_COLOR, weight: 3.5, opacity: 0.9, interactive: false,
    }).addTo(statsLayer);
    track._path?.setAttribute('data-mean-track', state.storm ?? ''); // E2E/调试锚点
    if (cutIndex < allLeads.length) {
      track._path?.setAttribute('data-mean-cut', String(allLeads[cutIndex].lead_h));
    }
  }
  for (const entry of drawnLeads) {
    const dot = L.circleMarker(centerOf(entry), {
      radius: 2.5, color: MEAN_COLOR, weight: 0.5, fillColor: MEAN_COLOR, fillOpacity: 0.7,
      interactive: false,
    }).addTo(statsLayer);
    meanDotsByKey.set(entry.lead_h, dot);
  }

  // 滑块当前时次（高亮样式，低分母时次同样绘制，数据不删仅视觉区分）
  const entry = state.stats.leads.find((l) => l.lead_h === state.leadCut)
    ?? allLeads[allLeads.length - 1];
  const currentLead = entry?.lead_h;
  if (entry && entry.mean_lat != null) {
    const marker = L.circleMarker(centerOf(entry), {
      radius: 6, color: MEAN_COLOR, weight: 2, fillColor: '#2563eb', fillOpacity: 0.95,
    }).bindPopup(statsPopupText(entry.lead_h, entry)).addTo(statsLayer);
    marker._path?.setAttribute('data-mean-center', String(entry.lead_h));
    const radiusKm = entry.radius_km[state.pApplied];
    if (radiusKm != null) {
      const circle = L.circle(centerOf(entry), {
        radius: radiusKm * 1000, color: '#2563eb', weight: 1.5, opacity: 0.9,
        fill: false, dashArray: '6 5', interactive: false,
      }).addTo(statsLayer);
      circle._path?.setAttribute('data-stats-circle', state.pApplied);
      circle._path?.setAttribute('data-p', state.pApplied);
      circle._path?.setAttribute('data-radius-km', String(Math.round(radiusKm)));
    }
  }

  // 关键时次（24h 倍数的实际存在时次）：淡色概率圆 + 均值强度标签；
  // 与 mean 线同口径止于截断点（低分母时次的均值强度不具参考性，不标注），当前时次已高亮故排除
  for (const l of drawnLeads) {
    if (l.lead_h % 24 !== 0 || l.lead_h === currentLead) continue;
    const radiusKm = l.radius_km[state.pApplied];
    if (radiusKm == null) continue;
    const circle = L.circle(centerOf(l), {
      radius: radiusKm * 1000, color: '#2563eb', weight: 1, opacity: 0.4,
      fill: false, dashArray: '2 4', interactive: false,
    }).addTo(statsLayer);
    circle._path?.setAttribute('data-stats-circle-key', String(l.lead_h));
    const label = L.marker(centerOf(l), {
      icon: L.divIcon({ className: 'mean-label', html: meanLeadLabel(l), iconSize: null }),
      interactive: false, keyboard: false,
    }).addTo(statsLayer);
    label.getElement()?.setAttribute('data-mean-label', String(l.lead_h));
  }
}

async function loadStats() {
  state.stats = null;
  if (!state.fcId || !state.storm || !state.init) { render(); return; }
  try {
    state.stats = await api(`/api/datasets/${state.fcId}/ensemble-stats`, {
      storm: state.storm, init: state.init,
    });
  } catch (err) {
    state.stats = null;
    setStatus(`集合统计获取失败：${err.message}`, true);
  }
  render();
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

(async function init() {
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
