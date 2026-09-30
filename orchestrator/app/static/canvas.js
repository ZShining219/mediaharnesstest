/* ============================================================
 * 节点画布 — ComfyUI 式工作流编辑器 (litegraph.js)
 *
 * 架构: 后端 /api/nodes 输出节点注册表 schema → 前端动态生成节点类型。
 * 画布图 = 任务定义: 序列化 {nodes,links} 提交 /api/graph/run,
 * 后端拓扑执行并回写每节点状态, 前端实时染色。
 * ============================================================ */

const LGT = window.LiteGraph;
let lgraph = null, lgcanvas = null, runningJob = null;
let NODE_SCHEMA = [];   // /api/nodes 返回的注册表

/* ---------- 工具 ---------- */
const NODE_COLORS = { material: '#1f3a4a', model: '#3a2a52', proc: '#2d4030', output: '#4a3a20' };

function w(node, name) {
  const x = (node.widgets || []).find(w => w.name === name);
  return x ? x.value : undefined;
}
function setW(node, name, v) {
  const x = (node.widgets || []).find(w => w.name === name);
  if (x) { x.value = v; if (x.callback) x.callback(v, undefined, undefined, undefined, node); }
}
function setNodeState(node, state) {
  const colors = { running: '#8a6d1f', ok: '#2ea36c', error: '#a04040', skipped: '#555' };
  node.color = colors[state] || NODE_COLORS[node._cat] || '#222';
  node.setDirtyCanvas(true, true);
}
function mediaUrl(path) { return withToken('/api/assets/file?path=' + encodeURIComponent(path)); }

function attachPreview(node, url, isVideo) {
  if (isVideo) {
    const v = document.createElement('video');
    v.src = url; v.muted = true; v.playsInline = true;
    v.addEventListener('loadeddata', () => { v.currentTime = Math.min(0.5, (v.duration || 1) / 3); });
    v.addEventListener('seeked', () => { node._img = v; node.setDirtyCanvas(true, true); });
  } else {
    const im = new Image();
    im.onload = () => { node._img = im; node.setDirtyCanvas(true, true); };
    im.src = url;
  }
}
function drawPreview(ctx) {
  if (!this._img) return;
  const iw = this._img.videoWidth || this._img.width;
  const ih = this._img.videoHeight || this._img.height;
  if (!iw) return;
  const bw = this.size[0] - 16, bh = this.size[1] - this._imgTop - 8;
  ctx.drawImage(this._img, 8, this._imgTop, bw, Math.min(bw * ih / iw, bh));
}

/* ---------- 参数 widget 工厂 ---------- */
const ASSET_GROUPS = {
  video: ['source'], image: ['image', 'garment'], audio: ['voice', 'bgm'],
};

function assetValues(group) {
  return (ASSET_GROUPS[group] || [])
    .flatMap(k => ASSETS[k] || []);
}

function resolveOptions(spec, node, widget) {
  if (spec === '@characters') return CHARS.map(c => c.name);
  if (spec === '@looks') {
    const ch = CHARS.find(c => c.name === w(node, '角色'));
    return (ch && ch.looks || []).map(l => `assets/characters/${ch.name}/looks/${l}`);
  }
  return spec || [];
}

function addParamWidget(node, p) {
  const kind = p.kind || 'text';
  if (kind.startsWith('asset:')) {
    const group = kind.slice(6);
    const vals = ['--选择--'].concat(assetValues(group));
    const cmb = node.addWidget('combo', p.name, p.default || vals[0], v => {
      if (v && !v.startsWith('--')) attachPreview(node, mediaUrl(v), group === 'video');
    }, { values: vals });
    cmb._isParam = true; cmb._assetGroup = group;
    node.addWidget('button', '↑上传' + ({ video: '视频', image: '图片', audio: '音频' })[group], '', () => {
      upAsset(group === 'video' ? 'source' : group === 'audio' ? 'voice' : 'image',
        path => { cmb.options.values.push(path); cmb.value = path; attachPreview(node, mediaUrl(path), group === 'video'); });
    });
  } else if (kind === 'combo' || kind.startsWith('@')) {
    const vals = ['--'].concat(resolveOptions(p.options === undefined && kind.startsWith('@') ? kind : p.options, node));
    const cmb = node.addWidget('combo', p.name, p.default || vals[0], v => {
      if (p.name === '角色') {   // 角色变了刷新形象版本列表
        const lw = (node.widgets || []).find(x => x._dyn === '@looks');
        if (lw) { lw.options.values = resolveOptions('@looks', node); lw.value = lw.options.values[0]; }
      }
    }, { values: vals });
    cmb._isParam = true;
    if (kind.startsWith('@')) cmb._dyn = kind;
    if (p.options === '@characters') cmb._dyn = '@characters';
    if (p.options === '@looks') cmb._dyn = '@looks';
  } else if (kind === 'toggle') {
    const t = node.addWidget('toggle', p.name, !!p.default, () => { });
    t._isParam = true;
  } else if (kind === 'number') {
    const nb = node.addWidget('number', p.name, p.default || 0, () => { }, { precision: 2 });
    nb._isParam = true;
  } else if (kind === 'textarea') {
    const t = node.addWidget('text', p.name + (p.hint ? `(${p.hint})` : ''), p.default || '', () => { }, { multiline: true });
    t._isParam = true;
  } else {
    const t = node.addWidget('text', p.name + (p.hint ? `(${p.hint})` : ''), p.default || '', () => { });
    t._isParam = true;
  }
}

/* ---------- 动态注册节点 ---------- */
function buildNodeClass(def) {
  function N() {
    (def.inputs || []).forEach(([n, t]) => this.addInput(n.replace(/^\?/, '') + (n[0] === '?' ? '·可选' : ''), t === '*' ? 0 : t));
    (def.outputs || []).forEach(([n, t]) => this.addOutput(n, t === '*' ? 0 : t));
    (def.params || []).forEach(p => addParamWidget(this, p));
    const base = 40 + (def.params || []).length * 26 + (def.inputs || []).length * 8;
    this.size = [265, Math.max(base, 110)];
    this._cat = def.category;
    this.color = NODE_COLORS[def.category] || '#222';
    // 素材节点加预览区
    if (def.category === 'material' || def.type.startsWith('output/')) {
      this.onDrawBackground = drawPreview;
      this._imgTop = this.size[1] - 8;
      this.size[1] += 150;
      this._imgTop = base + 10;
    }
  }
  N.title = def.title;
  N.desc = def.type;
  LGT.registerNodeType(def.type, N);
}

/* ---------- 添加节点菜单 ---------- */
function showAddNodeMenu(ev) {
  const entries = NODE_SCHEMA.map(d => ({
    content: `${{ material: '素材', model: '模型', proc: '后处理', output: '输出' }[d.category]} / ${d.title}`,
    value: d.type,
    callback: (v, opt, e) => {
      const n = LGT.createNode(v);
      n.pos = lgcanvas.convertEventToCanvasOffset(ev);
      lgraph.add(n);
    },
  }));
  new LGT.ContextMenu(entries, { event: ev || window.event, title: '添加节点' }, window);
}

/* ---------- 图序列化/加载 ---------- */
function collectGraph() {
  return {
    nodes: lgraph._nodes.map(n => ({
      id: n.id, type: n.type, pos: [n.pos[0], n.pos[1]],
      params: Object.fromEntries(
        (n.widgets || []).filter(x => x._isParam).map(x => [x.name.split('(')[0], x.value])),
    })),
    links: Object.values(lgraph.links).map(l => ({
      src: l.origin_id, src_slot: l.origin_slot,
      dst: l.target_id, dst_slot: l.target_slot,
    })),
  };
}

function loadGraphJSON(g) {
  lgraph.clear();
  const idmap = {};
  (g.nodes || []).forEach(n => {
    const node = LGT.createNode(n.type);
    if (!node) return;
    node.pos = n.pos || [100, 100];
    lgraph.add(node);
    idmap[n.id] = node;
    Object.entries(n.params || {}).forEach(([k, v]) => setW(node, k, v));
  });
  (g.links || []).forEach(l => {
    const s = idmap[l.src], d = idmap[l.dst];
    if (s && d) s.connect(l.src_slot, d, l.dst_slot);
  });
  lgcanvas.draw();
}

/* ---------- 内置模板 ---------- */
const TEMPLATES = {
  '内置·对标视频转换': () => {
    const t = (ty, x, y) => { const n = LGT.createNode(ty); n.pos = [x, y]; lgraph.add(n); return n; };
    const src = t('material/video', 40, 80);
    const chr = t('material/character', 40, 460);
    const eng = t('model/wan_animate', 400, 220);
    const post = t('proc/bgm', 740, 220);
    const out = t('output/review', 1040, 220);
    const bgm = t('material/audio', 740, 480);
    src.connect(0, eng, 0); chr.connect(0, eng, 1);
    eng.connect(0, post, 0); bgm.connect(0, post, 1); post.connect(0, out, 0);
  },
  '内置·数字人口播': () => {
    const t = (ty, x, y) => { const n = LGT.createNode(ty); n.pos = [x, y]; lgraph.add(n); return n; };
    const role = t('material/character', 30, 60);
    const scr = t('material/text', 30, 430);
    const tts = t('model/tts_minimax', 350, 430);
    const italk = t('model/infinitetalk', 350, 60);
    const post = t('proc/subtitles', 700, 60);
    const out = t('output/review', 1000, 60);
    const scr2 = t('material/text', 700, 380);
    role.connect(0, italk, 0); tts.connect(0, italk, 1); scr2.connect(0, italk, 2);
    scr.connect(0, tts, 0); italk.connect(0, post, 0); scr.connect(0, post, 1);
    post.connect(0, out, 0);
  },
};

/* ---------- 上传回调 ---------- */
function upAsset(kind, cb) {
  const inp = document.createElement('input'); inp.type = 'file';
  inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    const r = await fetch(`/api/upload?kind=${kind}&token=${TOKEN}`, { method: 'POST', body: fd }).then(r => r.json());
    if (r.path) { toast('已上传 ' + r.path); cb && cb(r.path); }
    else toast('失败: ' + (r.detail || ''));
  }; inp.click();
}

/* ---------- 运行 ---------- */
async function runPipeline() {
  if (runningJob) { toast('有任务在运行中'); return; }
  const g = collectGraph();
  if (!g.nodes.length) { toast('空图'); return; }
  const r = await api('/api/graph/run', 'POST', g);
  if (r.detail) { toast('图校验失败: ' + r.detail); return; }
  if (!r.queued) { toast('提交失败 ' + JSON.stringify(r)); return; }
  runningJob = r.job;
  lgraph._nodes.forEach(n => setNodeState(n, 'running'));
  toast('任务已提交: ' + r.job);
  pollJob(r.job);
}

function pollJob(jid) {
  const timer = setInterval(async () => {
    const j = await api('/api/jobs/' + jid);
    const ns = (j.result || {}).node_status || {};
    lgraph._nodes.forEach(n => { if (ns[n.id]) setNodeState(n, ns[n.id]); });
    if (j.status === 'running') return;
    clearInterval(timer);
    runningJob = null;
    if (j.status === 'done') {
      toast('完成，产物已进审核队列');
      const items = (j.result || {}).items || [];
      lgraph._nodes.filter(n => n.type.startsWith('output/') && items.length)
        .forEach((n, i) => attachPreview(n, withToken('/media/' + items[Math.min(i, items.length - 1)]), true));
      const errs = (j.result || {}).errors || [];
      if (errs.length) toast('部分节点失败: ' + errs[0].slice(0, 100));
    } else {
      toast('失败: ' + ((j.result && j.result.error) || '').slice(0, 150));
    }
  }, 4000);
}

/* ---------- 保存/加载模板 ---------- */
async function saveTemplate() {
  const name = prompt('模板名称'); if (!name) return;
  await api('/api/graphs', 'POST', { name, graph: collectGraph() });
  toast('已保存模板 ' + name);
  refreshTemplateList();
}
async function refreshTemplateList() {
  const saved = await api('/api/graphs');
  const sel = $('#pipe-tpl');
  sel.innerHTML = Object.keys(TEMPLATES).map(k => `<option value="${k}">${k}</option>`).join('')
    + saved.map(g => `<option value="saved:${g.name}">★ ${g.name}</option>`).join('');
}
async function loadSelected() {
  const v = $('#pipe-tpl').value;
  if (v.startsWith('saved:')) {
    const g = await api('/api/graphs/' + v.slice(6));
    lgraph.clear();
    loadGraphJSON(g.graph || g);
  } else {
    lgraph.clear();
    TEMPLATES[v]();
  }
  lgcanvas.draw();
  const st = document.getElementById('canvas-status');
  if (st) st.textContent = `已加载: ${v.replace('saved:', '')} · ${lgraph._nodes.length} 个节点`;
}

/* ---------- 挂载 ---------- */
window.initNodeCanvas = async function () {
  if (!window.LiteGraph) { toast('画布库未加载'); return; }
  await refreshMeta();
  NODE_SCHEMA = await api('/api/nodes');
  NODE_SCHEMA.forEach(buildNodeClass);
  const el = document.getElementById('lgcanvas');
  lgraph = new LGT.LGraph();
  if (!lgcanvas) {
    lgcanvas = new LGT.LGraphCanvas(el, lgraph);
    lgcanvas.show_info = false;
    el.width = el.parentElement.clientWidth - 4;
    el.height = Math.max(560, window.innerHeight - 260);
  } else {
    lgcanvas.setGraph(lgraph);
  }
  await refreshTemplateList();
  $('#pipe-tpl').onchange = loadSelected;
  loadSelected();
};

window.runPipeline = runPipeline;
window.saveTemplate = saveTemplate;
window.showAddNodeMenu = showAddNodeMenu;
window.refreshCanvasLists = async () => { await refreshMeta(); loadSelected(); };
