<script setup>
// 节点画布: Vue Flow 编排 + 后端拓扑执行 + 实时状态染色 + 任务回放
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { VueFlow, useVueFlow, MarkerType } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { ElMessage, ElMessageBox } from 'element-plus'
import { VideoPlay, FolderAdd, Delete, Refresh, Plus, Search, Back } from '@element-plus/icons-vue'
import FlowNode from '../components/FlowNode.vue'
import { api, mediaUrl } from '../api'
import { store, refreshMeta } from '../store'

const route = useRoute()
const router = useRouter()

const nodes = ref([])
const edges = ref([])
const runningJob = ref(null)
const jobLogs = ref([])
const resultItems = ref([])
const resultVisible = ref(false)
const addDlg = ref(false)
const addKw = ref('')
const addPos = ref(null)
const addInput = ref(null)
const paletteKw = ref('')
const templates = ref([])
const tplSel = ref('')
const tplInfo = ref(null)
const saving = ref(false)
const replay = ref(false)
const replayJob = ref(null)
const showTip = ref(!localStorage.getItem('aimf_canvas_tip'))
const { onConnect, screenToFlowCoordinate, fitView } = useVueFlow()

// ---------- 工具 ----------
const nodeDef = (type) => store.nodeSchema.find(d => d.type === type)
const CAT_LABEL = { material: '素材', model: '模型', proc: '后处理', output: '输出' }
const DT_COLOR = { video: '#22d3ee', image: '#a78bfa', audio: '#34d399', text: '#fbbf24' }
const dtColor = (t) => DT_COLOR[t] || '#94a3b8'

const groups = computed(() => {
  const kw = paletteKw.value.trim().toLowerCase()
  const g = {}
  for (const d of store.nodeSchema) {
    if (kw && !(d.title + d.type).toLowerCase().includes(kw)) continue
    ;(g[d.category] = g[d.category] || []).push(d)
  }
  return g
})

const addGroups = computed(() => {
  const kw = addKw.value.trim().toLowerCase()
  const g = {}
  for (const d of store.nodeSchema) {
    if (kw && !(d.title + d.type + CAT_LABEL[d.category]).toLowerCase().includes(kw)) continue
    ;(g[d.category] = g[d.category] || []).push(d)
  }
  return g
})

function slotInfo(nodeId, handle, dir) {
  const n = nodes.value.find(x => x.id === nodeId)
  if (!n || !n.data.def) return ['?', '*']
  const slot = parseInt((handle || '').split('-')[1] || 0)
  const list = dir === 'out' ? n.data.def.outputs : n.data.def.inputs
  return list[slot] || ['?', '*']
}
const slotType = (n, h, dir) => slotInfo(n, h, dir)[1] ?? '*'

// ---------- 连线 = 真实数据流 ----------
let edgeAdded = false
let lastInvalid = null

function isValidConnection(conn) {
  const [on, outT] = slotInfo(conn.source, conn.sourceHandle, 'out')
  const [inm, inT] = slotInfo(conn.target, conn.targetHandle, 'in')
  const fail = (msg) => { lastInvalid = msg; return false }
  if (conn.source === conn.target) return fail('不能连到节点自身')
  if (outT !== inT && outT !== '*' && inT !== '*')
    return fail(`类型不匹配: 「${on}」输出 ${outT}，「${inm.replace(/^\?/, '')}」需要 ${inT}`)
  // 一个输入口只允许一条连线; 校验时排除边自身(setEdges 会对已在列表里的边重验)
  if (edges.value.some(e =>
    e.target === conn.target && e.targetHandle === conn.targetHandle &&
    !(e.source === conn.source && e.sourceHandle === conn.sourceHandle)))
    return fail(`「${inm.replace(/^\?/, '')}」输入口已有连线`)
  lastInvalid = null
  return true
}

function mkEdge(conn) {
  const [on, outT] = slotInfo(conn.source, conn.sourceHandle, 'out')
  const [inm] = slotInfo(conn.target, conn.targetHandle, 'in')
  const color = dtColor(outT)
  return {
    id: `e-${conn.source}-${conn.sourceHandle}-${conn.target}-${conn.targetHandle}`,
    source: conn.source, sourceHandle: conn.sourceHandle,
    target: conn.target, targetHandle: conn.targetHandle,
    label: `${on} → ${inm.replace(/^\?/, '')} · ${outT}`,
    style: { stroke: color, strokeWidth: 2 },
    labelStyle: { fill: '#eef0f6', fontSize: 11 },
    labelBgStyle: { fill: '#141824', fillOpacity: 0.94 },
    labelBgPadding: [6, 3],
    markerEnd: 'arrowclosed',
  }
}

onConnect((conn) => { edgeAdded = true; edges.value = [...edges.value, mkEdge(conn)] })

function onConnStart() { edgeAdded = false; lastInvalid = null }
function onConnEnd() {
  // 拖到类型不符/已占用端口上松手: 明确拒绝反馈
  if (!edgeAdded && lastInvalid) ElMessage.warning('连线被拒绝: ' + lastInvalid)
  edgeAdded = false
  lastInvalid = null
}

// ---------- 图校验(与后端同规则: 必填输入必须有连线) ----------
const issues = computed(() => {
  const linked = new Set(edges.value.map(e => `${e.target}|${e.targetHandle}`))
  const out = []
  for (const n of nodes.value) {
    const d = n.data.def
    for (const [i, [name]] of (d.inputs || []).entries()) {
      if (!name.startsWith('?') && !linked.has(`${n.id}|in-${i}`))
        out.push(`「${d.title}」缺必填输入 ${name}`)
    }
  }
  return out
})

// ---------- 节点增删 ----------
let seq = 0
function addNode(type, pos) {
  const def = nodeDef(type)
  if (!def) return
  const params = {}
  for (const p of def.params || []) params[p.name] = p.default ?? ''
  nodes.value.push({
    id: `n${++seq}-${Date.now() % 100000}`,
    type: 'custom',
    position: pos || { x: 120 + Math.random() * 260, y: 80 + Math.random() * 200 },
    data: { def, params, status: null },
  })
}

function openAdd(pos = null) {
  addPos.value = pos
  addKw.value = ''
  addDlg.value = true
}
function pickAdd(type) { addNode(type, addPos.value); addDlg.value = false }

// 拖拽添加
function onDragStart(e, type) { e.dataTransfer.setData('application/vueflow', type) }
function onDrop(e) {
  const type = e.dataTransfer.getData('application/vueflow')
  if (!type || replay.value) return
  addNode(type, screenToFlowCoordinate({ x: e.clientX, y: e.clientY }))
}

async function deleteSelection(targetNode = null) {
  if (replay.value) return
  const ns = targetNode ? [targetNode] : nodes.value.filter(n => n.selected)
  const es = targetNode ? [] : edges.value.filter(e => e.selected)
  if (!ns.length && !es.length) { ElMessage.info('先在画布上点选要删除的节点或连线'); return }
  const withOut = ns.filter(n => edges.value.some(e => e.source === n.id))
  if (withOut.length) {
    const names = withOut.map(n => n.data.def.title.replace(/^[^·]*·/, '')).join('、')
    const cnt = withOut.reduce((a, n) => a + edges.value.filter(e => e.source === n.id).length, 0)
    try {
      await ElMessageBox.confirm(
        `节点「${names}」有 ${cnt} 条出边，删除后下游节点将缺少输入。`,
        '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    } catch { return }
  }
  const ids = new Set(ns.map(n => n.id))
  const eids = new Set(es.map(e => e.id))
  edges.value = edges.value.filter(e =>
    !eids.has(e.id) && !ids.has(e.source) && !ids.has(e.target))
  nodes.value = nodes.value.filter(n => !ids.has(n.id))
}

function disconnectNode(n) {
  edges.value = edges.value.filter(e => e.source !== n.id && e.target !== n.id)
}

function onKey(e) {
  if (replay.value || addDlg.value) return
  const t = e.target
  if (t && (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable)) return
  if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelection() }
}

// ---------- 右键菜单 ----------
const ctxMenu = ref({ show: false, x: 0, y: 0, type: '', obj: null })
function openCtx(e, type, obj) {
  ctxMenu.value = { show: true, x: e.clientX, y: e.clientY, type, obj }
  nextTick(() => window.addEventListener('click', () => ctxMenu.value.show = false, { once: true }))
}
function onNodeMenu({ event, node }) { if (!replay.value) openCtx(event, 'node', node) }
function onEdgeMenu({ event, edge }) { if (!replay.value) openCtx(event, 'edge', edge) }
function onPaneMenu(e) {
  if (replay.value) return
  e.preventDefault()
  openAdd(screenToFlowCoordinate({ x: e.clientX, y: e.clientY }))
}
function onPaneDbl(e) {
  if (replay.value || addDlg.value) return
  if (e.target.closest('.vue-flow__node,.vue-flow__handle,.vue-flow__edge,.vue-flow__controls,.vue-flow__minimap,.ctx-menu')) return
  openAdd(screenToFlowCoordinate({ x: e.clientX, y: e.clientY }))
}

// ---------- 序列化 ----------
function serialize() {
  return {
    nodes: nodes.value.map(n => ({
      id: n.id, type: n.data.def.type, pos: [n.position.x, n.position.y],
      params: n.data.params,
    })),
    links: edges.value.map(e => ({
      src: e.source, src_slot: parseInt((e.sourceHandle || 'out-0').split('-')[1]),
      dst: e.target, dst_slot: parseInt((e.targetHandle || 'in-0').split('-')[1]),
    })),
  }
}

async function loadGraph(g) {
  const ns = []
  for (const n of g.nodes || []) {
    const def = nodeDef(n.type)
    if (!def) continue
    ns.push({
      id: String(n.id), type: 'custom',
      position: { x: (n.pos || [100, 100])[0], y: (n.pos || [100, 100])[1] },
      data: { def, params: { ...Object.fromEntries((def.params || []).map(p => [p.name, p.default ?? ''])), ...(n.params || {}) }, status: null },
    })
  }
  nodes.value = ns   // 先同步节点, mkEdge/连线校验依赖 nodes.value
  const es = (g.links || []).map(l => mkEdge({
    source: String(l.src), sourceHandle: `out-${l.src_slot}`,
    target: String(l.dst), targetHandle: `in-${l.dst_slot}`,
  }))
  edges.value = es
  nextTick(() => fitView({ padding: 0.15, duration: 300 }))
}

// ---------- 内置模板 ----------
const BUILTIN = {
  '模板·对标视频人物替换': {
    desc: '把对标视频里的人物替换成参考图形象，动作/表情/场景/运镜保留，产出直接进审核。',
    edgeDoc: [
      '源视频 → 人物替换·video：要被替换人物的对标视频',
      '形象图 → 人物替换·image：替换成这个人（五官/发型/着装以它为准）',
      '提示词 → 人物替换·text：给模型的指令（可选，不连有默认值）',
      '人物替换·video → 审核队列·media：产出成片进审核队列',
    ],
    nodes: [
      { id: 'src', type: 'material/video', pos: [40, 60], params: {} },
      { id: 'face', type: 'material/image', pos: [40, 330], params: {} },
      { id: 'tip', type: 'material/text', pos: [40, 590], params: { '内容': '把参考视频中的人物替换为参考图片中的人物，保持动作、表情、场景和运镜一致' } },
      { id: 'swap', type: 'model/h3_faceswap', pos: [400, 180], params: {} },
      { id: 'out', type: 'output/review', pos: [740, 180], params: {} },
    ],
    links: [
      { src: 'src', src_slot: 0, dst: 'swap', dst_slot: 0 },
      { src: 'face', src_slot: 0, dst: 'swap', dst_slot: 1 },
      { src: 'tip', src_slot: 0, dst: 'swap', dst_slot: 2 },
      { src: 'swap', src_slot: 0, dst: 'out', dst_slot: 0 },
    ],
  },
  '模板·数字人口播': {
    desc: '角色形象图 + 口播文案：MiniMax 先配音，再让 H3 把形象图驱动成按音频说话的视频。',
    edgeDoc: [
      '文案 → TTS·text：要朗读的文字',
      '角色形象 → 形象口播·image：出镜头的人',
      'TTS·audio → 形象口播·audio：驱动口型的配音',
      '形象口播·video → 审核队列·media：产出成片进审核队列',
    ],
    nodes: [
      { id: 'role', type: 'material/character', pos: [40, 60], params: {} },
      { id: 'txt', type: 'material/text', pos: [40, 340], params: {} },
      { id: 'tts', type: 'model/tts_minimax', pos: [390, 340], params: {} },
      { id: 'avatar', type: 'model/h3_avatar', pos: [700, 120], params: {} },
      { id: 'out', type: 'output/review', pos: [1040, 120], params: {} },
    ],
    links: [
      { src: 'txt', src_slot: 0, dst: 'tts', dst_slot: 0 },
      { src: 'role', src_slot: 0, dst: 'avatar', dst_slot: 0 },
      { src: 'tts', src_slot: 0, dst: 'avatar', dst_slot: 1 },
      { src: 'avatar', src_slot: 0, dst: 'out', dst_slot: 0 },
    ],
  },
  '模板·自动创作': {
    desc: '只给一个主题：DeepSeek 写画面提示词，MiniMax H3 文生视频，产出进审核。',
    edgeDoc: [
      '主题 → DeepSeek·text：创作主题/大纲',
      'DeepSeek·text → H3·text：生成的画面提示词',
      'H3·video → 审核队列·media：产出成片进审核队列',
    ],
    nodes: [
      { id: 'topic', type: 'material/text', pos: [40, 80], params: { '内容': '主题: ' } },
      { id: 'llm', type: 'model/llm_deepseek', pos: [380, 80], params: { '任务': 'prompt' } },
      { id: 'h3', type: 'model/minimax_h3', pos: [720, 80], params: {} },
      { id: 'out', type: 'output/review', pos: [1060, 80], params: {} },
    ],
    links: [
      { src: 'topic', src_slot: 0, dst: 'llm', dst_slot: 0 },
      { src: 'llm', src_slot: 0, dst: 'h3', dst_slot: 0 },
      { src: 'h3', src_slot: 0, dst: 'out', dst_slot: 0 },
    ],
  },
}

async function refreshTemplates() {
  const saved = await api.get('/api/graphs')
  templates.value = [
    ...Object.keys(BUILTIN).map(k => ({ label: k, value: k })),
    ...saved.map(g => ({ label: '★ ' + g.name, value: 'saved:' + g.name })),
  ]
}

async function loadTemplate(v) {
  if (!v) return
  let g
  if (v.startsWith('saved:')) {
    g = await api.get('/api/graphs/' + v.slice(6))
    g = g.graph || g
    tplInfo.value = null
  } else {
    g = BUILTIN[v]
    tplInfo.value = g
  }
  loadGraph(g)
  ElMessage.info(`已加载 ${v.replace('saved:', '')} · ${nodes.value.length} 个节点`)
}

async function saveGraph() {
  try {
    const { value } = await ElMessageBox.prompt('模板名称', '保存模板', {
      confirmButtonText: '保存', cancelButtonText: '取消',
    })
    if (!value) return
    saving.value = true
    await api.post('/api/graphs', { name: value, graph: serialize() })
    await refreshTemplates()
    tplSel.value = 'saved:' + value
    ElMessage.success('已保存模板 ' + value)
  } catch { /* 取消 */ } finally { saving.value = false }
}

// ---------- 运行 ----------
async function run() {
  if (runningJob.value) { ElMessage.warning('有任务在运行中'); return }
  const g = serialize()
  if (!g.nodes.length) { ElMessage.warning('画布为空，先添加节点'); return }
  if (issues.value.length) {
    ElMessage.error(`图校验未通过: ${issues.value[0]}${issues.value.length > 1 ? ` 等 ${issues.value.length} 处` : ''}`)
    return
  }
  nodes.value.forEach(n => { n.data.status = null })
  try {
    const r = await api.post('/api/graph/run', { ...g, name: tplSel.value || undefined })
    runningJob.value = r.job
    ElMessage.success('已提交 ' + r.job)
    nodes.value.forEach(n => { n.data.status = 'running' })
    poll(r.job)
  } catch (e) {
    ElMessage.error('提交失败: ' + e.message)
  }
}

let pollTimer = null
function poll(jid) {
  pollTimer = setInterval(async () => {
    try {
      const j = await api.get('/api/jobs/' + jid)
      const ns = (j.result || {}).node_status || {}
      nodes.value.forEach(n => { if (ns[n.id]) n.data.status = ns[n.id] })
      jobLogs.value = (j.result || {}).logs || []
      if (j.status === 'running') return
      clearInterval(pollTimer)
      runningJob.value = null
      if (j.status === 'done') {
        const items = (j.result || {}).items || []
        if (items.length) { resultItems.value = items; resultVisible.value = true }
        const errs = (j.result || {}).errors || []
        ElMessage[errs.length ? 'warning' : 'success'](
          errs.length ? `完成(部分节点失败): ${errs[0].slice(0, 80)}` : '完成，产物已进审核队列')
      } else {
        ElMessage.error('任务失败: ' + ((j.result || {}).error || '').slice(0, 150))
      }
    } catch (e) { /* 单次轮询失败忽略 */ }
  }, 2500)
}

function clearCanvas() {
  nodes.value = []
  edges.value = []
  jobLogs.value = []
}

// ---------- 回放(任务中心「查看对应图」) ----------
async function enterReplay(jid) {
  let j
  try { j = await api.get('/api/jobs/' + jid) } catch { return }
  const g = (j.params || {}).graph
  if (!g) { ElMessage.warning('该任务没有执行图记录(旧任务)'); return }
  replay.value = true
  replayJob.value = j
  loadGraph(g)
  const ns = (j.result || {}).node_status || {}
  if (Object.keys(ns).length) {
    nodes.value.forEach(n => { n.data.status = ns[n.id] || null })
  } else {
    // 管线任务无逐节点状态: 素材→ok, 首个处理节点按整体状态, 下游跳过
    let seen = false
    nodes.value.forEach(n => {
      const cat = n.data.def.category
      if (j.status === 'done') n.data.status = 'ok'
      else if (cat === 'material') n.data.status = 'ok'
      else if (!seen) { seen = true; n.data.status = j.status === 'running' ? 'running' : 'error' }
      else n.data.status = j.status === 'error' ? 'skipped' : null
    })
  }
  jobLogs.value = (j.result || {}).logs || []
  const items = (j.result || {}).items || ((j.result || {}).item_id ? [j.result.item_id] : [])
  if (items.length) resultItems.value = items
  ElMessage.info('回放模式: 只读查看该任务的执行图与节点状态')
}

function exitReplay() {
  replay.value = false
  replayJob.value = null
  jobLogs.value = []
  router.replace({ query: {} })
}

function dismissTip() {
  localStorage.setItem('aimf_canvas_tip', '1')
  showTip.value = false
}

onMounted(async () => {
  await refreshMeta(true)
  window.addEventListener('keydown', onKey)
  if (route.query.job) {
    enterReplay(String(route.query.job))
    return
  }
  await refreshTemplates()
  if (templates.value.length) { tplSel.value = templates.value[0].value; await loadTemplate(tplSel.value) }
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="canvas-wrap">
    <!-- 左: 节点库面板 -->
    <aside v-if="!replay"
           style="width:210px;flex-shrink:0;border-right:1px solid var(--aimf-line);background:rgba(15,18,25,.85);display:flex;flex-direction:column">
      <div style="padding:12px 12px 6px;font-size:12.5px;color:var(--aimf-dim);font-weight:600">
        节点库 · 拖入画布或双击添加
      </div>
      <el-input v-model="paletteKw" size="small" placeholder="🔍 搜索节点（拖到画布 / 双击添加）"
                clearable :prefix-icon="Search" style="padding:0 12px 8px" />
      <div style="flex:1;overflow-y:auto;padding:0 10px 12px">
        <div v-for="(list, cat) in groups" :key="cat" style="margin-bottom:10px">
          <div style="font-size:11px;color:#5f6780;padding:4px 2px">{{ CAT_LABEL[cat] || cat }}</div>
          <div v-for="d in list" :key="d.type"
               draggable="true" @dragstart="e => onDragStart(e, d.type)"
               @dblclick="addNode(d.type)"
               :title="`拖到画布或双击添加\n输入: ${(d.inputs||[]).map(i=>i[0]+':'+i[1]).join(' , ') || '无'}\n输出: ${(d.outputs||[]).map(o=>o[0]+':'+o[1]).join(' , ') || '无'}`"
               class="pal-item"
               onmouseover="this.style.borderColor='#6366f1'" onmouseout="this.style.borderColor='var(--aimf-line)'">
            <span class="pal-dot" :class="`dot-${d.category}`"></span>
            {{ d.title.replace(/^[^·]*·/, '') }}
          </div>
        </div>
      </div>
    </aside>

    <!-- 右: 说明 + 工具栏 + 画布 -->
    <div style="flex:1;display:flex;flex-direction:column;min-width:0">
      <div class="canvas-intro" v-if="!replay">
        节点画布 = <b style="color:#a5b4fc">进阶编排</b>：每个节点是一步处理，连线是真实数据流（端口按类型着色，类型匹配才连得上）。
        想照固定流程走请回「工作台」。
      </div>
      <div class="canvas-intro" v-else style="color:#fbbf24">
        回放模式 · 任务 <span class="mono">{{ replayJob?.id }}</span> 的执行图（只读，
        {{ (replayJob?.result||{}).node_status ? '逐节点真实状态' : '按任务结果推断状态' }}）
      </div>

      <el-alert v-if="showTip && !replay" type="info" :closable="true" @close="dismissTip"
                style="margin:8px 14px 0" show-icon>
        小提示：点工具栏「＋ 节点」、<b>双击画布空白</b>或<b>右键画布</b>都能添加节点；悬停连线可看传输的数据含义，Delete 删除选中。
      </el-alert>

      <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--aimf-line);flex-wrap:wrap">
        <template v-if="!replay">
          <el-select v-model="tplSel" placeholder="选择模板" size="small" style="width:230px" @change="loadTemplate">
            <el-option v-for="t in templates" :key="t.value" :value="t.value" :label="t.label" />
          </el-select>
          <el-button type="primary" size="small" :icon="VideoPlay" :loading="!!runningJob" @click="run">
            {{ runningJob ? '运行中' : '运行' }}
          </el-button>
          <el-button type="success" size="small" :icon="Plus" @click="openAdd()">＋ 节点</el-button>
          <el-button size="small" :icon="FolderAdd" :loading="saving" @click="saveGraph">保存为模板</el-button>
          <el-button size="small" :icon="Refresh" @click="refreshMeta(true).then(()=>ElMessage.success('已刷新素材'))">刷新素材</el-button>
          <el-button size="small" :icon="Delete" @click="deleteSelection()" title="删除选中节点/连线 (Delete)">删除选中</el-button>
          <el-button size="small" @click="clearCanvas">清空</el-button>
          <el-tooltip placement="bottom">
            <template #content>
              <template v-if="issues.length">
                <div v-for="s in issues" :key="s" style="font-size:12px">{{ s }}</div>
              </template>
              <div v-else style="font-size:12px">所有必填输入均已连线，可运行</div>
            </template>
            <el-tag :type="issues.length ? 'warning' : 'success'" effect="plain" size="small">
              {{ issues.length ? `${issues.length} 处必填输入未接线` : '图校验通过' }}
            </el-tag>
          </el-tooltip>
        </template>
        <template v-else>
          <el-tag :type="replayJob?.status === 'done' ? 'success' : replayJob?.status === 'error' ? 'danger' : 'warning'"
                  effect="dark" size="small">{{ replayJob?.status }}</el-tag>
          <el-button v-if="resultItems.length" size="small" type="primary" @click="resultVisible = true">查看产出 ({{ resultItems.length }})</el-button>
          <el-button size="small" :icon="Back" @click="exitReplay">退出回放</el-button>
          <el-button size="small" @click="router.push('/jobs')">回任务中心</el-button>
        </template>
        <el-tag effect="plain" size="small">{{ nodes.length }} 节点 · {{ edges.length }} 连线</el-tag>
        <el-tag v-if="runningJob" type="warning" effect="dark" class="mono">{{ runningJob }}</el-tag>
      </div>

      <details v-if="tplInfo && !replay" class="tpl-doc" open>
        <summary>模板说明 · {{ tplSel }}</summary>
        <div style="margin-top:6px">{{ tplInfo.desc }}</div>
        <ul>
          <li v-for="(d, i) in tplInfo.edgeDoc" :key="i">{{ d }}</li>
        </ul>
      </details>

      <div style="flex:1;position:relative" @dblclick="onPaneDbl">
        <VueFlow v-model:nodes="nodes" v-model:edges="edges"
                 :is-valid-connection="isValidConnection"
                 :delete-key-code="[]"
                 :nodes-draggable="!replay" :nodes-connectable="!replay"
                 :min-zoom="0.2" :max-zoom="2"
                 style="height:100%;background:var(--aimf-bg)"
                 @drop="onDrop" @dragover.prevent
                 @pane-context-menu="onPaneMenu"
                 @node-context-menu="onNodeMenu"
                 @edge-context-menu="onEdgeMenu"
                 @connect-start="onConnStart" @connect-end="onConnEnd">
          <template #node-custom="props">
            <FlowNode v-bind="props" />
          </template>
          <Background :gap="22" pattern-color="#232838" />
          <Controls position="bottom-right" />
          <MiniMap position="bottom-left" :width="150" :height="90"
                   style="background:#141824;border-radius:8px"
                   mask-color="rgba(10,12,17,.7)" node-color="#3a425f" />
        </VueFlow>

        <!-- 空画布引导 -->
        <div v-if="!nodes.length && !replay" class="empty-add">
          <div>
            <el-button type="primary" size="large" :icon="Plus" @click="openAdd()">＋ 添加节点</el-button>
            <div class="dim" style="margin-top:10px;font-size:12.5px">
              或从左侧节点库拖入 / 双击 · 也可以选上方模板一键载入
            </div>
          </div>
        </div>

        <!-- 右键菜单 -->
        <div v-if="ctxMenu.show" class="ctx-menu" :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }">
          <template v-if="ctxMenu.type === 'node'">
            <button class="danger" @click="deleteSelection(ctxMenu.obj); ctxMenu.show = false">删除该节点</button>
            <button @click="disconnectNode(ctxMenu.obj); ctxMenu.show = false">断开它的全部连线</button>
          </template>
          <template v-else-if="ctxMenu.type === 'edge'">
            <button class="danger" @click="edges = edges.filter(e => e.id !== ctxMenu.obj.id); ctxMenu.show = false">删除这条连线</button>
          </template>
        </div>
      </div>

      <!-- 运行日志 -->
      <div v-if="jobLogs.length"
           style="max-height:110px;overflow-y:auto;border-top:1px solid var(--aimf-line);
                  padding:8px 14px;font-size:12px" class="mono dim">
        <div v-for="(l, i) in jobLogs" :key="i">{{ l }}</div>
      </div>
    </div>

    <!-- 添加节点弹窗 -->
    <el-dialog v-model="addDlg" title="添加节点" width="460px" top="14vh"
               @opened="addInput?.focus?.()">
      <el-input ref="addInput" v-model="addKw" :prefix-icon="Search" clearable
                placeholder="搜索节点：如 视频 / TTS / 替换 / 审核" style="margin-bottom:10px" />
      <div style="max-height:46vh;overflow-y:auto">
        <div v-for="(list, cat) in addGroups" :key="cat" style="margin-bottom:10px">
          <div style="font-size:11px;color:#5f6780;padding:4px 2px">{{ CAT_LABEL[cat] || cat }}</div>
          <div v-for="d in list" :key="d.type" class="pal-item" @click="pickAdd(d.type)"
               onmouseover="this.style.borderColor='#6366f1'" onmouseout="this.style.borderColor='var(--aimf-line)'">
            <span class="pal-dot" :class="`dot-${d.category}`"></span>
            {{ d.title.replace(/^[^·]*·/, '') }}
            <span class="dim" style="float:right;font-size:10.5px">
              {{ (d.inputs||[]).map(i=>i[1]).join('+') || '—' }} → {{ (d.outputs||[]).map(o=>o[1]).join('+') || '—' }}
            </span>
          </div>
        </div>
        <el-empty v-if="!Object.keys(addGroups).length" description="没有匹配的节点" :image-size="50" />
      </div>
    </el-dialog>

    <!-- 结果预览 -->
    <el-dialog v-model="resultVisible" title="产出已进审核队列" width="520px">
      <div v-for="it in resultItems" :key="it" style="margin-bottom:12px">
        <video :src="mediaUrl(it)" controls class="media-video" />
        <div class="dim mono" style="font-size:12px;margin-top:4px">{{ it }}</div>
      </div>
      <template #footer>
        <el-button @click="router.push('/review')" type="primary">前往审核</el-button>
        <el-button @click="resultVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>
