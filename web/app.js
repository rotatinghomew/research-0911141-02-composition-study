const state = {context: null, current: null};
const element = identifier => document.getElementById(identifier);

async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '请求失败');
  return value;
}

function message(value, error = false) {
  element('status').textContent = value;
  element('status').className = error ? 'error' : '';
}

async function guarded(action) {
  try { await action(); } catch (error) { message(error.message, true); }
}

function selected() {
  const selection = {};
  for (const control of state.context.product.options) selection[control[0]] = element('select-' + control[0]).value;
  return {revision: element('revision').value, selection};
}

function renderControls() {
  const revision = element('revision').value || state.context.default_revision;
  element('revision').replaceChildren();
  for (const dataset of state.context.datasets) {
    const option = document.createElement('option');
    option.value = dataset.revision;
    option.textContent = dataset.label + ' · ' + dataset.revision.slice(0, 9);
    element('revision').append(option);
  }
  element('revision').value = revision;
  if (!element('revision').value) element('revision').value = state.context.default_revision;
  if (element('controls').children.length) return;
  for (const [key, labelText, choices] of state.context.product.options) {
    const label = document.createElement('label');
    label.textContent = labelText;
    const select = document.createElement('select');
    select.id = 'select-' + key;
    for (const choice of choices) {
      const option = document.createElement('option');
      option.value = choice;
      option.textContent = choice;
      select.append(option);
    }
    select.value = state.context.product.selection[key];
    label.append(select);
    element('controls').append(label);
  }
}

function displayValue(value) {
  if (value === null || value === undefined) return '未观测';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4);
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

function drawChart(series) {
  const canvas = element('chart');
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  const values = series.filter(point => typeof point.y === 'number' && Number.isFinite(point.y));
  context.font = '12px sans-serif';
  if (!values.length) { context.fillText('该范围没有可定量的描述值', 30, 50); return; }
  const low = Math.min(0, ...values.map(point => point.y));
  const high = Math.max(1, ...values.map(point => point.y));
  const scale = value => 250 - (value - low) / (high - low || 1) * 210;
  context.strokeStyle = '#90a5ad';
  context.beginPath(); context.moveTo(45, 20); context.lineTo(45, 250); context.lineTo(940, 250); context.stroke();
  context.fillStyle = '#0a7168';
  const scatter = values.every(point => typeof point.x === 'number');
  const minimumX = scatter ? Math.min(...values.map(point => point.x)) : 0;
  const maximumX = scatter ? Math.max(...values.map(point => point.x)) : 1;
  values.forEach((point, index) => {
    const position = scatter ? 60 + (point.x - minimumX) / (maximumX - minimumX || 1) * 850 : 55 + index * 875 / values.length;
    if (scatter) {
      context.beginPath(); context.arc(position, scale(point.y), 3.5, 0, Math.PI * 2); context.fill();
    } else {
      context.fillRect(position, Math.min(scale(point.y), scale(0)), Math.max(3, 800 / values.length), Math.max(1, Math.abs(scale(point.y) - scale(0))));
    }
    if (values.length < 12) context.fillText(point.label, position, 275);
  });
  context.fillStyle = '#29434e';
  context.fillText(high.toFixed(2), 0, 45); context.fillText(low.toFixed(2), 0, 250);
  context.fillText(scatter ? '沿用方法均值 → 候选方法均值（原始定量配对）' : '按表中顺序展示描述值；缺测不绘制为零', 50, 20);
}

function render(result, heading) {
  state.current = result;
  element('summary').replaceChildren();
  for (const [label, value] of Object.entries(result.view.summary)) {
    const card = document.createElement('article');
    const title = document.createElement('span'); title.textContent = label;
    const amount = document.createElement('strong'); amount.textContent = displayValue(value);
    card.append(title, amount); element('summary').append(card);
  }
  element('notes').replaceChildren();
  for (const note of result.view.notes) {
    const paragraph = document.createElement('p'); paragraph.textContent = note; element('notes').append(paragraph);
  }
  const rows = result.view.rows;
  const fields = rows.length ? Object.keys(rows[0]) : [];
  const header = document.createElement('tr');
  for (const field of fields) { const cell = document.createElement('th'); cell.textContent = field; header.append(cell); }
  element('columns').replaceChildren(header); element('rows').replaceChildren();
  for (const row of rows) {
    const line = document.createElement('tr'); line.tabIndex = 0;
    for (const field of fields) { const cell = document.createElement('td'); cell.textContent = displayValue(row[field]); line.append(cell); }
    line.onclick = () => { element('details').textContent = JSON.stringify(row, null, 2); };
    line.onkeydown = event => { if (event.key === 'Enter') line.click(); };
    element('rows').append(line);
  }
  drawChart(result.view.series);
  element('details').textContent = JSON.stringify({revision: result.revision, selection: result.selection,
    history: result.view.history || null}, null, 2);
  message((heading || '已更新描述') + ' · 数据 ' + result.revision.slice(0, 12));
}

async function refresh() {
  state.context = await request('/api/context');
  renderControls();
  element('archive').replaceChildren();
  for (const notebook of state.context.notebooks) {
    const button = document.createElement('button'); button.textContent = notebook.title + ' #' + notebook.id;
    button.onclick = () => guarded(async () => {
      const saved = await request('/api/notebooks/' + notebook.id);
      element('revision').value = saved.revision;
      for (const [key, value] of Object.entries(saved.selection)) {
        const control = element('select-' + key); if (control) control.value = value;
      }
      render(saved.result, '已读取保存的描述，不随新数据变化');
    });
    element('archive').append(button);
  }
  element('compare-archive').replaceChildren();
  for (const item of state.context.comparisons || []) {
    const button = document.createElement('button'); button.textContent = item.title + ' #' + item.id;
    button.onclick = () => guardedCompare(async () => {
      const saved = await request('/api/comparisons/' + item.id);
      state.savedScheme = saved.scheme;
      element('rerun-compare').hidden = false;
      renderCompare(saved.result, '已读取保存的比较 #' + saved.id + '（冻结结果，不随新数据变化）');
    });
    element('compare-archive').append(button);
  }
}

element('inspect').onclick = () => guarded(async () => render(await request('/api/explore', selected())));
element('save').onclick = () => guarded(async () => {
  const saved = await request('/api/notebooks', {...selected(), title: element('title').value});
  await refresh(); render(saved.result, '已保存记录 #' + saved.id);
});
element('raw').onclick = () => guarded(async () => {
  const revision = state.current ? state.current.revision : element('revision').value;
  element('details').textContent = JSON.stringify(await request('/api/data?revision=' + encodeURIComponent(revision)), null, 2);
});
element('upload').onchange = () => guarded(async () => {
  const file = element('upload').files[0]; if (!file) return;
  const data = JSON.parse(await file.text());
  const uploaded = await request('/api/datasets', {label: file.name, data});
  await refresh(); element('revision').value = uploaded.revision;
  render(await request('/api/explore', selected()), '已导入独立数据版本');
});
element('export').onclick = () => guarded(async () => {
  if (!state.current) throw new Error('请先查看一个范围');
  const data = await request('/api/data?revision=' + encodeURIComponent(state.current.revision));
  const blob = new Blob([JSON.stringify({description: state.current, data}, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = 'analysis-' + state.current.revision.slice(0, 12) + '.json'; link.click();
  URL.revokeObjectURL(url);
});
guarded(async () => {
  await refresh();
  render(await request('/api/explore', selected()));
  await guardedCompare(setupCompare);
});

// ---------------------------------------------------------------- 配方比较

function paragraph(text) {
  const p = document.createElement('p'); p.textContent = text; return p;
}

function compareMessage(value, error = false) {
  element('compare-status').textContent = value;
  element('compare-status').className = error ? 'error' : '';
}

async function guardedCompare(action) {
  try { await action(); } catch (error) { compareMessage(error.message, true); }
}

function fillTable(columnsId, rowsId, rows) {
  const fields = [...new Set(rows.flatMap(row => Object.keys(row)))];
  const header = document.createElement('tr');
  for (const field of fields) { const cell = document.createElement('th'); cell.textContent = field; header.append(cell); }
  element(columnsId).replaceChildren(header);
  element(rowsId).replaceChildren();
  for (const row of rows) {
    const line = document.createElement('tr');
    for (const field of fields) { const cell = document.createElement('td'); cell.textContent = displayValue(row[field]); line.append(cell); }
    element(rowsId).append(line);
  }
}

async function setupCompare() {
  const revision = element('revision').value || (state.context && state.context.default_revision);
  if (!revision) return;
  const options = await request('/api/compare/options?revision=' + encodeURIComponent(revision));
  state.compareOptions = options;
  for (const id of ['group-a', 'group-b']) {
    const select = element(id); const previous = select.value;
    select.replaceChildren();
    for (const group of options.groups) {
      const option = document.createElement('option'); option.value = group; option.textContent = group; select.append(option);
    }
    if (options.groups.includes(previous)) select.value = previous;
  }
  if (element('group-a').value === element('group-b').value && options.groups.length > 1) {
    element('group-b').value = options.groups.find(group => group !== element('group-a').value);
  }
  const below = element('below-limit');
  if (!below.children.length) {
    for (const [key, label] of Object.entries(options.scenarios)) {
      const option = document.createElement('option'); option.value = key; option.textContent = key + ' · ' + label; below.append(option);
    }
    below.value = options.default_scenario;
  }
  const picker = element('component-picker'); picker.replaceChildren();
  for (const component of options.components) {
    const label = document.createElement('label');
    const box = document.createElement('input'); box.type = 'checkbox'; box.value = component; box.checked = true;
    label.append(box, component); picker.append(label);
  }
  const sets = element('component-sets'); sets.replaceChildren();
  for (const [name, members] of Object.entries(options.component_groups)) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = '仅选成分组 ' + name;
    button.onclick = () => {
      for (const box of document.querySelectorAll('#component-picker input')) box.checked = members.includes(box.value);
    };
    sets.append(button);
  }
}

function currentScheme() {
  const components = [...document.querySelectorAll('#component-picker input')]
    .filter(box => box.checked).map(box => box.value);
  return {group_a: element('group-a').value, group_b: element('group-b').value,
          components, below_limit: element('below-limit').value};
}

function renderCompare(result, heading) {
  state.compare = result;
  const view = result.view;
  element('compare-groups').replaceChildren();
  for (const [group, info] of Object.entries(view.groups)) {
    element('compare-groups').append(paragraph(
      `${group}：样本 ${info.samples}，批次 ${info.batches.join('、')}，独立总量 ${info.with_total}/${info.samples}，` +
      `未检出单元格 ${info.below_limit_cells}，未检测单元格 ${info.not_measured_cells}`));
  }
  fillTable('level-columns', 'level-rows', view.level);
  fillTable('contrast-columns', 'contrast-rows', view.contrasts);
  fillTable('balance-columns', 'balance-rows', view.balances);
  element('structural-list').replaceChildren();
  if (!view.structural.length) element('structural-list').append(paragraph('所选成分在两端配方中均有使用记录，无结构差异。'));
  for (const item of view.structural) element('structural-list').append(paragraph(`成分 ${item.component}：${item.note}`));
  fillTable('sensitivity-columns', 'sensitivity-rows', view.sensitivity);
  element('limitations').replaceChildren();
  if (!view.limitations.length) element('limitations').append(paragraph('未发现批次、独立总量或可比样本方面的额外限制。'));
  for (const text of view.limitations) element('limitations').append(paragraph(text));
  element('compare-notes').replaceChildren();
  for (const text of view.notes) element('compare-notes').append(paragraph(text));
  element('compare-details').textContent = JSON.stringify(
    {revision: result.revision, data_sha256: result.data_sha256, scheme: result.scheme}, null, 2);
  compareMessage(heading + ' · 数据 ' + result.revision.slice(0, 12));
}

element('run-compare').onclick = () => guardedCompare(async () => {
  const revision = element('revision').value || state.context.default_revision;
  const result = await request('/api/compare', {revision, scheme: currentScheme()});
  state.savedScheme = null; element('rerun-compare').hidden = true;
  renderCompare(result, '已完成比较（未保存）');
});

element('save-compare').onclick = () => guardedCompare(async () => {
  const revision = element('revision').value || state.context.default_revision;
  const saved = await request('/api/comparisons', {
    title: element('compare-title').value, revision, scheme: currentScheme()});
  state.savedScheme = saved.scheme; element('rerun-compare').hidden = false;
  await refresh();
  renderCompare(saved.result, '已保存比较 #' + saved.id);
});

element('rerun-compare').onclick = () => guardedCompare(async () => {
  if (!state.savedScheme) return;
  const revision = element('revision').value || state.context.default_revision;
  const result = await request('/api/compare', {revision, scheme: state.savedScheme});
  renderCompare(result, '已用当前数据版本重做保存方案（原保存记录不变）');
});

element('revision').addEventListener('change', () => guardedCompare(setupCompare));
