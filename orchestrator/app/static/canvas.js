/* ============================================================
 * 轻量化节点画布 — 基于 litegraph.js (ComfyUI 同款画布引擎)
 * 设计原则: 固定管线节点, 节点即"功能卡", 连线为数据流向示意。
 * 参数收集按节点类型读取 widget 值 —— 用户即使断开连线也不影响运行。
 * ============================================================ */

const LGT = window.LiteGraph;
let lgraph = null, lgcanvas = null, runningJob = null;

/* ---------- 工具 ---------- */
function w(node, name) {           // 读 widget 值
  const x = (node.widgets || []).find(w => w.name === name);
  return x ? x.value : undefined;
}
function setW(node, name, v) {
  const x = (node.widgets || []).find(w => w.name === name);
  if (x) { x.value = v; if (x.callback) x.callback(v); }
}
function nodeByType(t) { return lgraph.findNodesByType(t)[0]; }

function setNodeState(node, state) { // run|ok|err|idle
  const colors = { run: '#8a6d1f', ok: '#2ea36c', err: '#a04040', idle: null };
  node.color = colors[state] || '#2a3548';
  node._state = state;
  node.setDirtyCanvas(true, true);
}

/* 媒体预览: 画到节点下半区 */
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
  const bw = this.size[0] - 16;
  const top = this.size[1] - 8 - bw * ih / iw;
  ctx.drawImage(this._img, 8, Math.max(60, top), bw, Math.min(bw * ih / iw, this.size[1] - 70));
}

function mediaUrl(path) { return withToken('/api/assets/file?path=' + encodeURIComponent(path)); }

function comboValues(list, placeholder) {
  return placeholder ? [placeholder].concat(list) : list;
}

/* ---------- 节点定义 ---------- */
function registerNodes() {
  const mk = (type, title, build) => {
    function N() { this.size = [250, 90]; build.call(this); }
    N.title = title;
    LGT.registerNodeType('aimf/' + type, N);
  };

  /* 素材输入节点: 下拉选素材 + 上传按钮 + 预览 */
  function sourceNode(type, title, kind, extraWidgets) {
    mk(type, title, function () {
      const vals = comboValues(ASSETS[kind] || [], '--点击刷新选择--');
      this.addWidget('combo', '素材', vals[0], v => {
        if (v && !v.startsWith('--')) attachPreview(this, mediaUrl(v), kind === 'source');
      }, { values: vals });
      this.addWidget('button', '上传文件…', '', () => upFile(kind));
      this.addWidget('button', '刷新列表', '', () => refreshCanvasLists());
      (extraWidgets || []).forEach(fn => fn.call(this));
      this.addOutput('out', 'media');
      this.onDrawBackground = drawPreview;
      this.size = [270, 300];
    });
  }

  /* 对标视频输入 */
  sourceNode('src_video', '对标视频', 'source');

  /* 目标形象: 形象图 + 换装编辑 */
  mk('character', '目标形象', function () {
    const vals = comboValues(
      [...(ASSETS.image || []), ...(ASSETS.garment || []),
       ...CHARS.flatMap(c => (c.looks || []).map(l => `assets/characters/${c.name}/looks/${l}`))],
      '--选择形象图--');
    this.addWidget('combo', '形象', vals[0], v => {
      if (v && !v.startsWith('--')) attachPreview(this, mediaUrl(v));
    }, { values: vals });
    this.addWidget('button', '上传形象图…', '', () => upFile('image'));
    this.addWidget('text', '换装/换发型', '', () => { });
    this.addOutput('out', 'media');
    this.onDrawBackground = drawPreview;
    this.size = [260, 150];
  });

  /* 文案 (数字人) */
  mk('script', '口播文案', function () {
    this.addWidget('text', '文案', '', () => { });
    this.addWidget('text', '标题', '', () => { });
    this.addWidget('text', '标签(,分隔)', '', () => { });
    this.addOutput('out', 'text');
    this.size = [260, 130];
  });

  /* 角色+声音 (数字人) */
  mk('role', '角色/声音', function () {
    const vals = CHARS.map(c => c.name);
    this.addWidget('combo', '角色', vals[0] || 'default', () => { }, { values: vals });
    this.addWidget('combo', '情绪', 'neutral', () => { },
      { values: ['neutral', 'happy', 'sad', 'angry', 'surprise', 'fear', 'disgust'] });
    this.addWidget('text', '画面提示词', '', () => { });
    this.addOutput('out', 'role');
    this.size = [250, 110];
  });

  /* 引擎节点 */
  mk('engine_vt', '转换引擎 (Wan2.2-Animate)', function () {
    this.addInput('source', 'media');
    this.addInput('character', 'media');
    this.addWidget('combo', '模式', 'replace', () => { },
      { values: ['replace', 'animate2'] });
    this.addWidget('combo', '分辨率', '720p', () => { }, { values: ['480p', '720p'] });
    this.addWidget('text', '背景提示词', '', () => { });
    this.addOutput('out', 'media');
    this.size = [270, 140];
  });

  mk('engine_dh', '口播引擎 (InfiniteTalk)', function () {
    this.addInput('role', 'role');
    this.addInput('script', 'text');
    this.addWidget('combo', '分辨率', '720p', () => { }, { values: ['480p', '720p'] });
    this.addOutput('out', 'media');
    this.size = [250, 110];
  });

  /* 后处理 */
  mk('post', '后处理', function () {
    this.addInput('in', 'media');
    this.addWidget('toggle', '保留原声/加音轨', true, () => { });
    this.addWidget('combo', 'BGM', '无', () => { },
      { values: ['无'].concat((ASSETS.bgm || []).map(p => p.split('/').pop())) });
    this.addOutput('out', 'media');
    this.size = [240, 110];
  });

  /* 输出 */
  mk('output', '输出 → 审核队列', function () {
    this.addInput('in', 'media');
    this.addWidget('text', '标题', '', () => { });
    this.addWidget('text', '标签(,分隔)', '', () => { });
    this.addWidget('button', '查看审核', '', () => {
      document.querySelector('nav button[data-tab="review"]').click();
    });
    this.onDrawBackground = drawPreview;
    this.size = [260, 260];
  });
}

/* ---------- 管线模板 ---------- */
const TEMPLATES = {
  transform: {
    name: '对标视频转换',
    build(g) {
      const src = LGT.createNode('aimf/src_video');
      const chr = LGT.createNode('aimf/character');
      const eng = LGT.createNode('aimf/engine_vt');
      const post = LGT.createNode('aimf/post');
      const out = LGT.createNode('aimf/output');
      [[src, 40, 60], [chr, 40, 330], [eng, 340, 160], [post, 660, 160], [out, 950, 160]]
        .forEach(([n, x, y]) => { n.pos = [x, y]; g.add(n); });
      src.connect(0, eng, 0); chr.connect(0, eng, 1);
      eng.connect(0, post, 0); post.connect(0, out, 0);
    },
    submit() {
      const src = nodeByType('aimf/src_video');
      const chr = nodeByType('aimf/character');
      const eng = nodeByType('aimf/engine_vt');
      const post = nodeByType('aimf/post');
      const out = nodeByType('aimf/output');
      const source = w(src, '素材'), face = w(chr, '形象');
      if (!source || source.startsWith('--')) throw new Error('请选择对标视频');
      if (!face || face.startsWith('--')) throw new Error('请选择目标形象图');
      return {
        ep: '/api/jobs/video-transform',
        body: {
          source, face, prompt: w(eng, '背景提示词') || '',
          mode: w(eng, '模式'), resolution: w(eng, '分辨率'),
          pre_edit_prompt: w(chr, '换装/换发型') || null,
          keep_audio: !!w(post, '保留原声/加音轨'),
          bgm: w(post, 'BGM') === '无' ? null : w(post, 'BGM'),
          title: w(out, '标题') || null,
          tags: (w(out, '标签(,分隔)') || '').split(',').filter(Boolean),
        },
        nodes: [src, chr, eng, post, out],
      };
    },
  },

  digital_human: {
    name: '数字人口播',
    build(g) {
      const role = LGT.createNode('aimf/role');
      const scr = LGT.createNode('aimf/script');
      const eng = LGT.createNode('aimf/engine_dh');
      const post = LGT.createNode('aimf/post');
      const out = LGT.createNode('aimf/output');
      [[role, 40, 60], [scr, 40, 330], [eng, 340, 160], [post, 640, 160], [out, 920, 160]]
        .forEach(([n, x, y]) => { n.pos = [x, y]; g.add(n); });
      role.connect(0, eng, 0); scr.connect(0, eng, 1);
      eng.connect(0, post, 0); post.connect(0, out, 0);
      // 后处理节点首项"保留原声"对数字人不适用 → 改标字幕
      const pw = post.widgets.find(x => x.name === '保留原声/加音轨');
      if (pw) pw.name = '字幕';
      out.title = '输出 → 审核队列';
    },
    submit() {
      const role = nodeByType('aimf/role');
      const scr = nodeByType('aimf/script');
      const eng = nodeByType('aimf/engine_dh');
      const post = nodeByType('aimf/post');
      const out = nodeByType('aimf/output');
      const text = w(scr, '文案');
      if (!text) throw new Error('请填写口播文案');
      return {
        ep: '/api/jobs/digital-human',
        body: {
          text, character: w(role, '角色'),
          emotion: w(role, '情绪') === 'neutral' ? null : w(role, '情绪'),
          prompt: w(role, '画面提示词') || null,
          resolution: w(eng, '分辨率'),
          subtitles: !!w(post, '字幕'),
          title: w(scr, '标题') || w(out, '标题') || null,
          tags: (w(scr, '标签(,分隔)') || w(out, '标签(,分隔)') || '').split(',').filter(Boolean),
        },
        nodes: [role, scr, eng, out],
      };
    },
  },
};

/* ---------- 画布初始化与运行 ---------- */
async function refreshCanvasLists() {
  await refreshMeta();          // ASSETS / CHARS
  const cur = TEMPLATES[$('#pipe-tpl').value];
  initCanvas(cur);              // 重建画布刷新下拉(参数会重置)
}

function initCanvas(tpl) {
  const el = document.getElementById('lgcanvas');
  lgraph = new LGT.LGraph();
  if (!lgcanvas) {
    lgcanvas = new LGT.LGraphCanvas(el, lgraph);
    lgcanvas.allow_reconnect_links = false;
    lgcanvas.show_info = false;
  } else {
    lgcanvas.setGraph(lgraph);
  }
  el.width = el.parentElement.clientWidth - 4;
  el.height = Math.max(560, window.innerHeight - 240);
  tpl.build(lgraph);
  lgcanvas.draw();
  const st = document.getElementById('canvas-status');
  if (st) st.textContent = `已加载: ${tpl.name} · ${lgraph._nodes.length} 个节点`;
  window._lgraph = lgraph;
}

function pollJob(jid, nodes) {
  const timer = setInterval(async () => {
    const j = await api('/api/jobs/' + jid);
    if (j.status === 'running') return;
    clearInterval(timer);
    runningJob = null;
    if (j.status === 'done') {
      nodes.forEach(n => setNodeState(n, 'ok'));
      const item = j.result && j.result.item_id;
      toast('生成完成，已进审核队列');
      if (item) {
        const out = nodeByType('aimf/output');
        if (out) attachPreview(out, withToken('/media/' + item), true);
      }
      load && load('review');
    } else {
      nodes.forEach(n => setNodeState(n, 'err'));
      toast('失败: ' + ((j.result && j.result.error) || '').slice(0, 120));
    }
  }, 4000);
}

async function runPipeline() {
  if (runningJob) { toast('有任务在运行中'); return; }
  const tpl = TEMPLATES[$('#pipe-tpl').value];
  let req;
  try { req = tpl.submit(); } catch (e) { toast(e.message); return; }
  const r = await api(req.ep, 'POST', req.body);
  if (!r.queued) { toast('提交失败: ' + JSON.stringify(r)); return; }
  const jobs = await api('/api/jobs');
  runningJob = jobs[0].id;
  req.nodes.forEach(n => setNodeState(n, 'run'));
  toast('任务已提交: ' + runningJob);
  pollJob(runningJob, req.nodes);
}

/* ---------- 挂载 ---------- */
window.initNodeCanvas = async function () {
  if (!window.LiteGraph) { toast('画布库未加载'); return; }
  await refreshMeta();
  registerNodes();
  const sel = $('#pipe-tpl');
  sel.innerHTML = Object.entries(TEMPLATES)
    .map(([k, v]) => `<option value="${k}">${v.name}</option>`).join('');
  sel.onchange = () => initCanvas(TEMPLATES[sel.value]);
  initCanvas(TEMPLATES[sel.value]);
  window._lgraph = lgraph;   // debug/测试钩子
  window._canvasReady = true;
};
