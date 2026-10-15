/* WNC 台风轨迹工作台（M3）：
 * 数据流：数据集选择 -> 拉取轨迹行 -> 客户端筛选（起报/成员/时效）-> Leaflet 渲染。
 * 数据纪律：时效档位取实际存在的 lead_h，不插值；缺失保持缺失；不跨起报时次混合。*/

const WIND_SCALE = [
  { min: 137, label: '≥137 kt（H5）', color: '#9d4edd' },
  { min: 113, label: '113–136 kt（H4）', color: '#d62828' },
  { min: 96, label: '96–112 kt（H3）', color: '#ef767a' },
  { min: 83, label: '83–95 kt（H2）', color: '#f4a261' },
  { min: 64, label: '64–82 kt（H1）', color: '#ffd166' },
  { min: 34, label: '34–63 kt（TS）', color: '#66c2a5' },
  { min: -Infinity, label: '<34 kt（TD）', color: '#6fb7e0' },
];
const MEMBER_COLORS = [
  '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4', '#46f0f0',
  '#f032e6', '#bcf60c', '#fabebe', '#008080', '#9a6324', '#800000',
];

const state = {
  datasets: [], fcId: null, obsId: null,
  storm: null, init: null, member: 'ALL', leadCut: null,
  fcRows: [], obsRows: [], leadSteps: [],
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
L.tileLayer(window.TILE_CONFIG.urlTemplate, {
  attribution: window.TILE_CONFIG.attribution,
  maxZoom: 20, maxNativeZoom: window.TILE_CONFIG.maxZoom,
}).addTo(map);
const forecastLayer = L.layerGroup().addTo(map);
const obsLayer = L.layerGroup().addTo(map);

function pointCoords(row) {
  if (row.lat == null) return null;
  const lon = row.lon_signed != null ? row.lon_signed : row.lon;
  return lon == null ? null : [row.lat, lon];
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

  const bounds = [];
  const rows = currentForecastRows();
  const singleMember = state.member !== 'ALL';
  const groups = groupBy(rows, (r) => `${r.storm ?? r.name ?? '?'}#${r.member ?? '—'}`);
  let colorIndex = 0;
  for (const [key, group] of groups) {
    const coords = group.map(pointCoords).filter(Boolean);
    if (coords.length >= 2) {
      L.polyline(coords, {
        color: singleMember ? '#374151' : memberColor(colorIndex),
        weight: singleMember ? 3 : 1.4,
        opacity: 0.85,
      }).addTo(forecastLayer);
    }
    if (singleMember) {
      for (const row of group) {
        const c = pointCoords(row);
        if (!c) continue;
        bounds.push(c);
        L.circleMarker(c, {
          radius: 4.5, color: '#333', weight: 0.8,
          fillColor: windColor(row.wind), fillOpacity: 0.95,
        }).bindPopup(popupText(row, key)).addTo(forecastLayer);
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
  setStatus(`预报 ${rows.length} 行 / 成员 ${groups.size} 组` +
    (state.obsId ? `；观测叠加 ${state.obsRows.length} 行` : ''));
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
  if (!meta) { state.fcRows = []; render(); return; }
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
  render();
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
$('init').addEventListener('change', () => { state.init = $('init').value || null; render(); });
$('member').addEventListener('change', () => { state.member = $('member').value || 'ALL'; render(); });
$('lead').addEventListener('input', () => {
  const idx = Number($('lead').value);
  state.leadCut = state.leadSteps.length ? state.leadSteps[idx] : null;
  $('lead-label').textContent = state.leadCut == null ? '全部' : `${state.leadCut} h`;
  render();
});
$('obs-dataset').addEventListener('change', onObsChange);

(function initLegend() {
  const box = $('legend');
  for (const stop of WIND_SCALE) {
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
