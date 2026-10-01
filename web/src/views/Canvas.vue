<script setup>
// 节点画布: Vue Flow 编排 + 后端拓扑执行 + 实时状态染色
import { ref, computed, onMounted, nextTick } from 'vue'
import { VueFlow, useVueFlow, Position } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { ElMessage, ElMessageBox } from 'element-plus'
import { VideoPlay, FolderAdd, Delete, Refresh } from '@element-plus/icons-vue'
import FlowNode from '../components/FlowNode.vue'
import { api, mediaUrl } from '../api'
import { store, refreshMeta } from '../store'

const nodes = ref([])
const edges = ref([])
const runningJob = ref(null)
const jobLogs = ref([])
const resultItems = ref([])
const resultVisible = ref(false)
const paletteVisible = ref(false)
const paletteKw = ref('')
const templates = ref([])
const tplSel = ref('')
const saving = ref(false)

const { onConnect, screenToFlowCoordinate, fitView } = useVueFlow()

// ---------- 工具 ----------
const nodeDef = (type) => store.nodeSchema.find(d => d.type === type)
const CAT_LABEL = { material: '素材', model: '模型', proc: '后处理', output: '输出' }

const groups = computed(() => {
  const kw = paletteKw.value.trim().toLowerCase()
  const g = {}
  for (const d of store.nodeSchema) {
    if (kw && !(d.title + d.type).toLowerCase().includes(kw)) continue
    ;(g[d.category] = g[d.category] || []).push(d)
  }
  return g
})

function slotType(nodeId, handle, dir) {
  const n = nodes.value.find(x => x.id === nodeId)
  if (!n) return '*'
  const def = n.data.def
  const slot = parseInt((handle || '').split('-')[1] || 0)
  const list = dir === 'out' ? def.outputs : def.inputs
  return (list[slot] || [])[1] ?? '*'
}

function isValidConnection(conn) {
  if (conn.source === conn.target) return false
  const outT = slotType(conn.source, conn.sourceHandle, 'out')
  const inT = slotType(conn.target, conn.targetHandle, 'in')
  if (outT !== inT && outT !== '*' && inT !== '*') return false
  // 一个输入口只允许一条连线
  return !edges.value.some(e =>
    e.target === conn.target && e.targetHandle === conn.targetHandle)
}

onConnect((conn) => {
  edges.value.push({
    id: `e-${conn.source}-${conn.sourceHandle}-${conn.target}-${conn.targetHandle}`,
    ...conn, animated: false,
  })
})

let seq = 0
function addNode(type, pos) {
  const def = nodeDef(type)
  if (!def) return
  const params = {}
  for (const p of def.params || []) params[p.name] = p.default ?? ''
  nodes.value.push({
    id: `n${++seq}-${Date.now() % 100000}`,
    type: 'custom',
    position: pos || { x: 120 + Math.random() * 160, y: 80 + Math.random() * 160 },
    data: { def, params, status: null },
  })
}

function addAtCenter(type) {
  addNode(type)
  paletteVisible.value = false
}

// 拖拽添加
function onDragStart(e, type) { e.dataTransfer.setData('application/vueflow', type) }
function onDrop(e) {
  const type = e.dataTransfer.getData('application/vueflow')
  if (!type) return
  addNode(type, screenToFlowCoordinate({ x: e.clientX, y: e.clientY }))
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

function loadGraph(g) {
  nodes.value = []
  edges.value = []
  const idmap = {}
  for (const n of g.nodes || []) {
    const def = nodeDef(n.type)
    if (!def) continue
    const node = {
      id: String(n.id), type: 'custom',
      position: { x: (n.pos || [100, 100])[0], y: (n.pos || [100, 100])[1] },
      data: { def, params: { ...Object.fromEntries((def.params || []).map(p => [p.name, p.default ?? ''])), ...(n.params || {}) }, status: null },
    }
    nodes.value.push(node)
    idmap[String(n.id)] = node
  }
  for (const l of g.links || []) {
    const sh = `out-${l.src_slot}`, th = `in-${l.dst_slot}`
    edges.value.push({
      id: `e-${l.src}-${sh}-${l.dst}-${th}`,
      source: String(l.src), sourceHandle: sh,
      target: String(l.dst), targetHandle: th,
    })
  }
  nextTick(() => fitView({ padding: 0.15, duration: 300 }))
}

// ---------- 内置模板 ----------
const BUILTIN = {
  '模板·对标视频人物替换': {
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
  if (v.startsWith('saved:')) {
    const g = await api.get('/api/graphs/' + v.slice(6))
    loadGraph(g.graph || g)
  } else {
    loadGraph(BUILTIN[v])
  }
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
  if (!g.nodes.length) { ElMessage.warning('画布为空'); return }
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

onMounted(async () => {
  await refreshMeta(true)
  await refreshTemplates()
  if (templates.value.length) { tplSel.value = templates.value[0].value; await loadTemplate(tplSel.value) }
})
</script>

<template>
  <div class="canvas-wrap">
    <!-- 左: 节点面板 -->
    <aside style="width:196px;flex-shrink:0;border-right:1px solid var(--aimf-line);background:rgba(15,18,25,.85);display:flex;flex-direction:column">
      <div style="padding:12px 12px 6px;font-size:12.5px;color:var(--aimf-dim);font-weight:600">节点库 · 点击或拖入画布</div>
      <el-input v-model="paletteKw" size="small" placeholder="搜索节点" clearable
                style="padding:0 12px 8px" />
      <div style="flex:1;overflow-y:auto;padding:0 10px 12px">
        <div v-for="(list, cat) in groups" :key="cat" style="margin-bottom:10px">
          <div style="font-size:11px;color:#5f6780;padding:4px 2px">{{ CAT_LABEL[cat] || cat }}</div>
          <div v-for="d in list" :key="d.type"
               draggable="true" @dragstart="e => onDragStart(e, d.type)"
               @dblclick="addAtCenter(d.type)" @click="addAtCenter(d.type)"
               style="padding:6px 9px;margin:3px 0;border-radius:8px;cursor:pointer;font-size:12.5px;
                      background:var(--aimf-panel2);border:1px solid var(--aimf-line);transition:all .12s"
               onmouseover="this.style.borderColor='#6366f1'" onmouseout="this.style.borderColor='var(--aimf-line)'">
            {{ d.title.replace(/^[^·]*·/, '') }}
          </div>
        </div>
      </div>
    </aside>

    <!-- 右: 工具栏 + 画布 -->
    <div style="flex:1;display:flex;flex-direction:column;min-width:0">
      <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--aimf-line);flex-wrap:wrap">
        <el-select v-model="tplSel" placeholder="选择模板" size="small" style="width:230px" @change="loadTemplate">
          <el-option v-for="t in templates" :key="t.value" :value="t.value" :label="t.label" />
        </el-select>
        <el-button type="primary" size="small" :icon="VideoPlay" :loading="!!runningJob" @click="run">
          {{ runningJob ? '运行中' : '运行' }}
        </el-button>
        <el-button size="small" :icon="FolderAdd" :loading="saving" @click="saveGraph">保存为模板</el-button>
        <el-button size="small" :icon="Refresh" @click="refreshMeta(true).then(()=>ElMessage.success('已刷新素材'))">刷新素材</el-button>
        <el-button size="small" :icon="Delete" @click="clearCanvas">清空</el-button>
        <el-tag v-if="runningJob" type="warning" effect="dark" class="mono">{{ runningJob }}</el-tag>
        <span class="dim" style="font-size:12px;margin-left:auto">连线类型匹配才可连 · Delete 删除选中 · 双击节点面板项快速添加</span>
      </div>

      <VueFlow v-model:nodes="nodes" v-model:edges="edges"
               :is-valid-connection="isValidConnection"
               :min-zoom="0.2" :max-zoom="2"
               style="flex:1;background:var(--aimf-bg)"
               @drop="onDrop" @dragover.prevent
               @pane-context-menu.prevent="paletteVisible = true">
        <template #node-custom="props">
          <FlowNode v-bind="props" />
        </template>
        <Background :gap="22" pattern-color="#232838" />
        <Controls position="bottom-right" />
        <MiniMap position="bottom-left" :width="150" :height="90"
                 style="background:#141824;border-radius:8px"
                 mask-color="rgba(10,12,17,.7)" node-color="#3a425f" />
      </VueFlow>

      <!-- 运行日志 -->
      <div v-if="jobLogs.length"
           style="max-height:110px;overflow-y:auto;border-top:1px solid var(--aimf-line);
                  padding:8px 14px;font-size:12px" class="mono dim">
        <div v-for="(l, i) in jobLogs" :key="i">{{ l }}</div>
      </div>
    </div>

    <!-- 结果预览 -->
    <el-dialog v-model="resultVisible" title="产出已进审核队列" width="520px">
      <div v-for="it in resultItems" :key="it" style="margin-bottom:12px">
        <video :src="mediaUrl(it)" controls class="media-video" />
        <div class="dim mono" style="font-size:12px;margin-top:4px">{{ it }}</div>
      </div>
      <template #footer>
        <el-button @click="$router.push('/review')" type="primary">前往审核</el-button>
        <el-button @click="resultVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>
