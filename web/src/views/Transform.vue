<script setup>
// 对标视频转换 · 独立功能页
// 一屏布局(不滚动): 左=参考槽位(人脸/身体/服饰+可追加) 中=对标视频+提示词 右=结果槽 下=产出管理(单行分页)
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Close, VideoPlay, Upload, Refresh } from '@element-plus/icons-vue'
import { api, assetUrl, mediaUrl, fmtTime, STATUS_TAG } from '../api'
import { store, refreshMeta } from '../store'
import { useFileDrop } from '../composables/useFileDrop'

const router = useRouter()

// ---------- 左侧: 参考槽位 (data-driven, 加新槽位=加一行配置) ----------
const SLOTS = [
  { key: 'face', label: '目标人脸', icon: '👤', required: true,
    desc: '换成这个人', upload: 'image', groups: ['image'] },
  { key: 'body', label: '身体·正面', icon: '🧍',
    desc: '体型/姿态(可空)', upload: 'image', groups: ['image'] },
  { key: 'body_back', label: '身体·背面', icon: '🔙',
    desc: '背面参考(可空)', upload: 'image', groups: ['image'] },
  { key: 'body_side', label: '身体·侧面', icon: '↔️',
    desc: '侧面参考(可空)', upload: 'image', groups: ['image'] },
  { key: 'cloth', label: '服饰', icon: '👗',
    desc: '换装参考(可空)', upload: 'garment', groups: ['garment', 'image'] },
]
const sel = ref({ face: '', body: '', cloth: '', body_back: '', body_side: '' })
const extras = ref([])                 // 追加参考槽 [{path}]
const MAX_EXTRA = 4

// ---------- 中间: 对标视频 + 提示词 ----------
const source = ref('')
const prompt = ref('')
const resolution = ref('768P')
const ratio = ref('adaptive')          // 秘塔画幅: adaptive/9:16/16:9/1:1
const duration = ref('')               // 秘塔时长 4-15s, 空=跟随对标视频
const keepAudio = ref(true)
const submitting = ref(false)

// ---------- 提示词模板 (服务端存取, 跨会话) ----------
const templates = ref([]), tplSel = ref('')

async function loadTpls() {
  try { templates.value = await api.get('/api/prompt-templates') } catch {}
}
function applyTpl(n) {
  const t = templates.value.find(x => x.name === n)
  if (t) prompt.value = t.text
}
async function saveTpl() {
  if (!prompt.value.trim()) { ElMessage.warning('提示词是空的, 先写内容'); return }
  const { value } = await ElMessageBox.prompt('模板名', '存为提示词模板', {
    confirmButtonText: '保存', cancelButtonText: '取消',
    inputValue: tplSel.value || '', inputPlaceholder: '如: 换人口播·干货向',
  }).catch(() => ({ value: null }))
  if (!value?.trim()) return
  try {
    await api.post('/api/prompt-templates', { name: value.trim(), text: prompt.value })
    tplSel.value = value.trim()
    await loadTpls()
    ElMessage.success('已存为模板')
  } catch (e) { ElMessage.error(e.message) }
}
async function delTpl() {
  await ElMessageBox.confirm(`删除模板「${tplSel.value}」？`, '确认', { type: 'warning' })
    .catch(() => Promise.reject())
  try {
    await api.del(`/api/prompt-templates/${encodeURIComponent(tplSel.value)}`)
    tplSel.value = ''
    await loadTpls()
  } catch (e) { ElMessage.error(e.message) }
}

// ---------- 中列: 视频框/提示词框 纵向拖拽分配 ----------
const midEl = ref(null)
const promptH = ref(110)           // 提示词框高(px); 视频框 flex:1 吃剩余
const splitting = ref(false)
let lastPromptH = 110
const MIN_V = 140, MIN_P = 34, SPLIT_H = 12

function startSplit(e) {
  e.preventDefault()
  const startY = e.clientY, startH = promptH.value
  const mid = midEl.value
  const optH = mid?.querySelector('.opt-row')?.offsetHeight || 36
  const maxP = Math.max(MIN_P, (mid?.clientHeight || 400) - optH - SPLIT_H - MIN_V)
  const move = ev => {
    promptH.value = Math.min(Math.max(startH - (ev.clientY - startY), MIN_P), maxP)
  }
  const up = () => {
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
    splitting.value = false
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
    saveForm()
  }
  splitting.value = true
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'row-resize'
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}
// 双击分隔条: 提示词框收起/还原
function togglePrompt() {
  if (promptH.value > MIN_P) { lastPromptH = promptH.value; promptH.value = MIN_P }
  else promptH.value = Math.max(lastPromptH, 60)
}

// ---------- 表单状态保留: 切页/刷新后恢复 ----------
const FORM_KEY = 'vt_form_v1'
function saveForm() {
  localStorage.setItem(FORM_KEY, JSON.stringify({
    sel: sel.value, extras: extras.value, source: source.value,
    prompt: prompt.value, resolution: resolution.value, ratio: ratio.value,
    duration: duration.value, keepAudio: keepAudio.value,
    promptH: promptH.value,
  }))
}
function restoreForm() {
  try {
    const d = JSON.parse(localStorage.getItem(FORM_KEY) || 'null')
    if (!d) return
    Object.assign(sel.value, d.sel || {})
    extras.value = d.extras || []
    source.value = d.source || ''
    prompt.value = d.prompt || ''
    resolution.value = d.resolution || '768P'
    ratio.value = d.ratio || 'adaptive'
    duration.value = d.duration ?? ''
    keepAudio.value = d.keepAudio !== false
    if (d.promptH) { promptH.value = d.promptH; lastPromptH = d.promptH }
  } catch { /* 损坏数据忽略 */ }
}
// 素材被删后清掉失效引用, 避免裂图
function pruneForm() {
  const known = new Set([...store.assets.source, ...store.assets.image, ...store.assets.garment])
  for (const k of Object.keys(sel.value)) if (sel.value[k] && !known.has(sel.value[k])) sel.value[k] = ''
  if (source.value && !known.has(source.value)) source.value = ''
  extras.value = extras.value.filter(e => !e.path || known.has(e.path))
}
watch([sel, extras, source, prompt, resolution, ratio, duration, keepAudio, promptH], saveForm, { deep: true })

// ---------- 素材选择器 (槽位/视频/追加槽共用一个弹窗) ----------
const picker = ref(null)               // {target:'slot'|'source'|'extra', key|idx, groups, upload, accept}
const uploading = ref(false)

const { dragging: pickDragging, dropProps: pickDrop } = useFileDrop({
  accept: () => picker.value?.accept,
  multiple: false,
  onFiles: uploadPicked,
})

function openPicker(target, opt = {}) {
  picker.value = {
    target,
    key: opt.key || '', idx: opt.idx ?? -1,
    groups: opt.groups || ['image'],
    upload: opt.upload || 'image',
    accept: opt.accept || 'image/*',
  }
}
const pickerAssets = computed(() => {
  if (!picker.value) return []
  return picker.value.groups.flatMap(g => store.assets[g] || [])
})
const isVideoPath = (p) => /\.(mp4|mov|webm|mkv)$/i.test(p)

function pick(p) {
  const t = picker.value
  if (t.target === 'source') source.value = p
  else if (t.target === 'slot') sel.value[t.key] = p
  else if (t.target === 'extra') extras.value[t.idx].path = p
  picker.value = null
}

function pickUpload(ev) {
  const files = [...(ev.target.files || [])]
  ev.target.value = ''
  return uploadPicked(files)
}

async function uploadPicked(files) {
  const f = files?.[0]
  if (!f) return
  uploading.value = true
  try {
    const r = await api.upload(f, picker.value.upload)
    store.loaded = false
    await refreshMeta(true)
    pick(r.path)
    ElMessage.success('已上传 ' + r.name)
  } catch (e) { ElMessage.error('上传失败: ' + e.message) }
  finally { uploading.value = false }
}

function addExtra() {
  if (extras.value.length >= MAX_EXTRA) return
  extras.value.push({ path: '' })
}

const fname = (p) => (p || '').split('/').pop()

// ---------- 自动选材: 视频/服装 候选搜索 + AI换装 + 批量生成 ----------
const mat = ref(false)
const mVkw = ref('人物 口播'), mVcount = ref(8), mPortrait = ref(true)
const mCkw = ref('服装 穿搭'), mCcount = ref(8)
const clothMode = ref('search')                    // search | gen (AI换装)
const genPrompts = ref('')
const mProv = ref('')
const vCands = ref([]), cCands = ref([])           // 候选 [{id,thumb,url,path?}]
const vSel = ref(new Set()), cSel = ref(new Set()) // 选中 id
const mBusy = ref('')                              // 'v'|'c'|'gen'|'run'|'dl'

async function mSearch(kind) {
  const isV = kind === 'video'
  mBusy.value = isV ? 'v' : 'c'
  try {
    const q = isV ? mVkw.value : mCkw.value
    const r = await api.get(`/api/materials/search?kind=${kind}&query=${encodeURIComponent(q)}`
      + `&count=${isV ? mVcount.value : mCcount.value}`
      + (isV && mPortrait.value ? '&orientation=portrait' : ''))
    mProv.value = r.provider
    const items = r.items.map(it => ({ ...it }))
    if (isV) vCands.value = items; else cCands.value.push(...items)
  } catch (e) { ElMessage.error('搜索失败: ' + e.message) }
  finally { mBusy.value = '' }
}

async function mGenLooks() {
  const base = sel.value.face || sel.value.body
  if (!base) { ElMessage.warning('AI换装需要先在左侧放入目标人脸或身体参考'); return }
  const prompts = genPrompts.value.split('\n').map(s => s.trim()).filter(Boolean)
  if (!prompts.length) { ElMessage.warning('每行写一条服装/造型描述'); return }
  mBusy.value = 'gen'
  try {
    const r = await api.post('/api/materials/gen-looks', {
      image: base, prompts, ratio: '3:4', n: 1 })
    const news = (r.paths || []).map((p, i) => ({
      id: 'gen-' + i + '-' + Date.now(), kind: 'image', local: true,
      thumb: assetUrl(p), path: p, desc: prompts[i] || 'AI换装',
    }))
    cCands.value.push(...news)
    for (const c of news) cSel.value.add(c.id)
    ElMessage.success(`生成 ${news.length} 张服装造型图`)
  } catch (e) { ElMessage.error('生成失败: ' + e.message) }
  finally { mBusy.value = '' }
}

function toggle(setRef, id) {
  setRef.value.has(id) ? setRef.value.delete(id) : setRef.value.add(id)
  setRef.value = new Set(setRef.value)               // 触发响应
}

const selVids = computed(() => vCands.value.filter(v => vSel.value.has(v.id)))
const selCls = computed(() => cCands.value.filter(c => cSel.value.has(c.id)))
const batchCount = computed(() =>
  selVids.value.length * Math.max(1, selCls.value.length))

// ---------- 社媒采集: 小红书/抖音 (MediaCrawler 子进程 + DeepSeek 规划/初筛) ----------
const socBrief = ref('')
const socPlan = ref(null)
const socKw = ref({ xhs: '', douyin: '' })
const socStatus = ref({ xhs: {}, douyin: {} })
const socBusy = ref('')                    // 'plan'|'xhs'|'douyin'|'rank'
let socTimer = null
const SOC_NAME = { xhs: '小红书', douyin: '抖音' }

async function refreshSoc() {
  try { socStatus.value = await api.get('/api/materials/social/status') } catch {}
}
watch(mat, v => { if (v) { refreshSoc(); loadPool() } })

// ---------- 每日备料池 (material_scout 产出, agent 已按方向筛好) ----------
const pool = ref([])
const scouting = ref(false)
const poolGroups = computed(() => {
  const m = new Map()
  for (const it of pool.value) {
    if (it.gone) continue
    if (!m.has(it.direction)) m.set(it.direction, [])
    m.get(it.direction).push(it)
  }
  return [...m.entries()].map(([name, items]) => ({ name, items }))
})

async function loadPool() {
  try { pool.value = (await api.get('/api/materials/pool?days=3')).items || [] } catch {}
}

function poolToggle(it) {
  const isV = it.kind === 'video'
  const list = isV ? vCands : cCands, setRef = isV ? vSel : cSel
  if (!list.value.find(x => x.id === it.id)) {
    list.value.push({ ...it,
      thumb: it.kind === 'video' ? it.thumb : assetUrl(it.path) })
  }
  toggle(setRef, it.id)
}

function scoutNow() {
  api.post('/api/materials/scout', {}).then(() => {
    ElMessage.success('备料任务已启动(约1-3分钟), 完成后自动刷新')
    scouting.value = true
    const t = setInterval(async () => {
      await pollJobs()
      const j = jobs.value.find(x => x.type === 'material_scout')
      if (j && j.status !== 'running') {
        clearInterval(t)
        scouting.value = false
        if (j.status === 'done') {
          ElMessage.success(`备料完成: 入池 ${j.result?.stocked ?? 0} 条`)
          loadPool()
        } else {
          ElMessage.error('备料失败: ' + (j.result?.error || '见任务中心'))
        }
      }
    }, 5000)
  }).catch(e => ElMessage.error(e.message))
}

async function socDoPlan() {
  if (!socBrief.value.trim()) { ElMessage.warning('先写主题, 如: 职场西装穿搭口播'); return }
  socBusy.value = 'plan'
  try {
    const r = await api.post('/api/materials/plan', { brief: socBrief.value, want_garment: true })
    socPlan.value = r
    if (r.xhs_queries?.length) socKw.value.xhs = r.xhs_queries[0]
    if (r.douyin_queries?.length) socKw.value.douyin = r.douyin_queries[0]
    if (r.garment_queries?.length) mCkw.value = r.garment_queries[0]
    if (r.fallback) ElMessage.warning('AI规划不可用, 已按原词填充')
  } catch (e) { ElMessage.error(e.message) }
  finally { socBusy.value = '' }
}

async function socSearch(pf) {
  const q = (socKw.value[pf] || socBrief.value).trim()
  if (!q) { ElMessage.warning('先写检索词或主题'); return }
  socBusy.value = pf
  try {
    const r = await api.get(`/api/materials/social/search?platform=${pf}`
      + `&query=${encodeURIComponent(q)}&count=12`)
    if (r.need_login) {
      socStatus.value[pf] = { ...socStatus.value[pf], need_login: true }
      ElMessage.warning(`${SOC_NAME[pf]}需要扫码登录, 点右侧[扫码登录]`)
      return
    }
    socStatus.value[pf] = { ...socStatus.value[pf], need_login: false }
    if (r.error && !r.items?.length) { ElMessage.error(r.error); return }
    const exist = new Set(vCands.value.map(v => v.id))
    const news = (r.items || []).filter(i => i.url && !exist.has(i.id))
    vCands.value.push(...news)
    mProv.value = `社媒:${pf}`
    ElMessage.success(`${SOC_NAME[pf]}返回 ${r.items?.length || 0} 条, 可下载 ${news.length} 条`)
  } catch (e) { ElMessage.error('搜索失败: ' + e.message) }
  finally { socBusy.value = '' }
}

function socLogin(pf) {
  api.post('/api/materials/social/login', { platform: pf })
    .then(() => {
      ElMessage.success('已弹出浏览器窗口, 请扫码登录(约5分钟内有效)')
      socStatus.value[pf] = { ...socStatus.value[pf], logging_in: true }
      clearInterval(socTimer)
      socTimer = setInterval(async () => {
        await refreshSoc()
        if (!socStatus.value[pf]?.logging_in) {
          clearInterval(socTimer)
          socStatus.value[pf] = { ...socStatus.value[pf], need_login: false }
          ElMessage.success('登录窗口已关闭, 可重试搜索')
        }
      }, 4000)
    })
    .catch(e => ElMessage.error(e.message))
}

async function socRank() {
  if (!vCands.value.length) { ElMessage.warning('先搜索候选'); return }
  socBusy.value = 'rank'
  try {
    const r = await api.post('/api/materials/rank', {
      brief: socBrief.value || mVkw.value, items: vCands.value, top: 30 })
    const map = Object.fromEntries(vCands.value.map(v => [v.id, v]))
    vCands.value = (r.order || []).map(id => map[id]).filter(Boolean)
      .map(v => ({ ...v, reason: r.reasons?.[v.id] }))
    for (const v of vCands.value.slice(0, 8)) vSel.value.add(v.id)
    vSel.value = new Set(vSel.value)
    ElMessage.success(r.fallback ? 'AI筛选不可用, 保持原顺序'
      : `AI已排序并勾选前 ${Math.min(8, vCands.value.length)} 条`)
  } catch (e) { ElMessage.error(e.message) }
  finally { socBusy.value = '' }
}

// 远端候选下载入库 -> 返回项目相对路径
async function dlSelected(items, kind) {
  const remote = items.filter(i => !i.path)
  const paths = items.filter(i => i.path).map(i => i.path)
  if (!remote.length) return paths
  const r = await api.post('/api/materials/download', {
    items: remote.map(i => ({ url: i.url, kind, name: i.desc,
                              headers: i.dl_headers })) })
  if (r.errors?.length) ElMessage.warning(`有 ${r.errors.length} 项下载失败`)
  return paths.concat(r.paths || [])
}

async function mImport() {                          // 仅入库
  mBusy.value = 'dl'
  try {
    const vp = await dlSelected(selVids.value, 'source')
    const cp = await dlSelected(selCls.value, 'garment')
    store.loaded = false; await refreshMeta(true)
    ElMessage.success(`已入库 视频${vp.length} · 服装${cp.length}`)
  } catch (e) { ElMessage.error(e.message) }
  finally { mBusy.value = '' }
}

async function batchRun() {
  if (!sel.value.face && !sel.value.body) {
    ElMessage.warning('先在左侧放入目标人脸或身体参考'); return
  }
  if (!selVids.value.length) { ElMessage.warning('先搜并勾选对标视频'); return }
  const n = batchCount.value
  const ok = await ElMessageBox.confirm(
    `将生成 ${n} 单（${selVids.value.length} 视频 × ${Math.max(1, selCls.value.length)} 服装），`
    + `预估 ≈¥${n}，产出全部进审核队列由你筛选`, '批量生成确认',
    { confirmButtonText: `生成 ${n} 单`, cancelButtonText: '取消', type: 'warning' })
    .then(() => true).catch(() => false)
  if (!ok) return
  mBusy.value = 'run'
  try {
    const vp = await dlSelected(selVids.value, 'source')
    const cp = await dlSelected(selCls.value, 'garment')
    const combos = cp.length ? cp : [null]
    let fired = 0
    for (const v of vp) for (const c of combos) {
      await api.post('/api/jobs/video-transform', {
        source: v, face: sel.value.face || null, body: sel.value.body || null,
        body_back: sel.value.body_back || null, body_side: sel.value.body_side || null,
        cloth: c, refs: extras.value.map(e => e.path).filter(Boolean),
        prompt: prompt.value, resolution: resolution.value, ratio: ratio.value,
        duration: duration.value || null, keep_audio: keepAudio.value,
      })
      fired++
    }
    store.loaded = false; refreshMeta(true)
    mat.value = false
    ElMessage.success(`已提交 ${fired} 单，产出陆续进审核队列`)
    pollJobs()
  } catch (e) { ElMessage.error('批量提交失败: ' + e.message) }
  finally { mBusy.value = '' }
}

// ---------- 提交 ----------
async function submit() {
  if (!source.value) { ElMessage.warning('请先放入对标视频'); return }
  if (!sel.value.face && !sel.value.body) {
    ElMessage.warning('至少需要目标人脸或身体参考其一'); return
  }
  submitting.value = true
  try {
    await api.post('/api/jobs/video-transform', {
      source: source.value, face: sel.value.face || null,
      body: sel.value.body || null,
      body_back: sel.value.body_back || null, body_side: sel.value.body_side || null,
      cloth: sel.value.cloth || null,
      refs: extras.value.map(e => e.path).filter(Boolean),
      prompt: prompt.value, resolution: resolution.value, ratio: ratio.value,
      duration: duration.value || null,
      keep_audio: keepAudio.value,
    })
    ElMessage.success('已提交，右侧看进度')
    pollJobs()
  } catch (e) { ElMessage.error('提交失败: ' + e.message) }
  finally { submitting.value = false }
}

// ---------- 右侧: 结果槽 (跟随最近一条 video_transform 任务) ----------
const jobs = ref([])
const nowTs = ref(Date.now() / 1000)
let timer = null

const vtJobs = computed(() => jobs.value.filter(j => j.type === 'video_transform'))
const activeJob = computed(() => vtJobs.value.find(j => j.status === 'running'))
const latestJob = computed(() => vtJobs.value[0] || null)
const resultId = computed(() =>
  latestJob.value?.status === 'done' ? (latestJob.value.result?.item_id || '') : '')
const elapsed = computed(() => {
  if (!activeJob.value) return ''
  const s = Math.max(0, Math.round(nowTs.value - activeJob.value.created_at))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})

async function pollJobs() {
  try {
    const prevDone = latestJob.value?.status === 'done'
    jobs.value = await api.get('/api/jobs')
    nowTs.value = Date.now() / 1000
    if (!prevDone && latestJob.value?.status === 'done') loadOutputs()
  } catch { /* 后端未起时静默 */ }
}

// 断连判错的任务: 按记录的秘塔 task_id 取回已生成结果
const recovering = ref(false)
async function recoverJob(jid) {
  recovering.value = true
  try {
    await api.post(`/api/jobs/${jid}/recover`, {})
    ElMessage.success('取回中(秘塔仍在生成则需等其完成), 稍后自动进审核队列')
    pollJobs()
  } catch (e) { ElMessage.error('取回失败: ' + e.message) }
  finally { recovering.value = false }
}

// 提交断连没记下 task_id 时: 从服务商后台抄 ID 手动取回(避免重复扣费重发)
async function manualRecover(jid) {
  const { value } = await ElMessageBox.prompt(
    '秘塔后台直接填任务 ID; 若在官方站, 填 official:任务ID',
    '按 task_id 取回结果', {
      confirmButtonText: '开始取回', cancelButtonText: '取消',
      inputPlaceholder: '如 2109957954248638464 或 official:2109957954248638464',
    }).catch(() => ({ value: null }))
  if (!value?.trim()) return
  recovering.value = true
  try {
    await api.post(`/api/jobs/${jid}/recover?task_id=${encodeURIComponent(value.trim())}`, {})
    ElMessage.success('取回中(仍在生成则需等其完成), 稍后自动进审核队列')
    pollJobs()
  } catch (e) { ElMessage.error('取回失败: ' + e.message) }
  finally { recovering.value = false }
}

// ---------- 下方: 产出素材管理 (单行横排 + 分页) ----------
const outs = ref([])
const page = ref(1)
const pageSize = ref(5)
const stripEl = ref(null)
const preview = ref(null)              // 点开看的产出 item
const busy = ref('')
let ro = null

const STATE_TAG = {
  review: { label: '待审核', type: 'warning' }, approved: { label: '待发布', type: 'success' },
  published: { label: '已发布', type: 'info' }, failed: { label: '已打回', type: 'danger' },
}

async function loadOutputs() {
  const all = []
  for (const st of Object.keys(STATE_TAG)) {
    try {
      const items = await api.get('/api/outputs/' + st)
      for (const it of items) if (it.pipeline === 'video_transform') all.push({ ...it, _state: st })
    } catch {}
  }
  all.sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
  outs.value = all
  page.value = Math.min(page.value, Math.max(1, Math.ceil(all.length / pageSize.value)))
}
const pageItems = computed(() =>
  outs.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))

// 审核动作与 Review 页一致
async function approve(it) {
  const { value } = await ElMessageBox.prompt('发布信息(标题必填，定时可空)', `通过 · ${it.id}`, {
    confirmButtonText: '通过并进待发布', cancelButtonText: '取消',
    inputValue: it.title || '', inputPlaceholder: '标题 | 用 \n 换行加简介…', inputType: 'textarea',
  }).catch(() => ({ value: null }))
  if (value === null) return
  const lines = (value || '').split('\n')
  try {
    await api.post(`/api/review/${it.id}/approve`, {
      title: lines[0] || it.id, desc: lines.slice(1).join('\n') || it.desc || '',
      tags: it.tags || [], platform: 'douyin', publish_now: false,
    })
    ElMessage.success('已通过'); preview.value = null; loadOutputs()
  } catch (e) { ElMessage.error(e.message) }
}
async function reject(it) {
  await ElMessageBox.confirm(`打回 ${it.title || it.id}？`, '确认打回', { type: 'warning' })
    .catch(() => Promise.reject())
  try {
    await api.post(`/api/review/${it.id}/reject`)
    ElMessage.success('已打回'); preview.value = null; loadOutputs()
  } catch (e) { ElMessage.error(e.message) }
}
async function publish(it) {
  busy.value = it.id
  try {
    await api.post(`/api/approved/${it.id}/publish`, {})
    ElMessage.success('已提交发布'); preview.value = null; loadOutputs()
  } catch (e) { ElMessage.error('发布失败: ' + e.message) }
  finally { busy.value = '' }
}

onMounted(async () => {
  restoreForm()
  loadTpls()
  await refreshMeta().catch(() => {})
  pruneForm()
  pollJobs(); loadOutputs()
  timer = setInterval(pollJobs, 4000)
  ro = new ResizeObserver(es => {
    const w = es[0].contentRect.width
    pageSize.value = Math.max(1, Math.floor((w + 14) / 194))   // 卡片180 + 间距14
  })
  if (stripEl.value) ro.observe(stripEl.value)
})
onUnmounted(() => { clearInterval(timer); ro?.disconnect() })
</script>

<template>
  <div class="page page-wide tpage">
    <div class="page-head">
      <h2>对标视频转换</h2>
      <span class="sub">对标视频 + 参考槽位 → 换人/换脸/换装 · MiniMax H3</span>
      <div class="sp" />
      <el-button size="small" @click="mat = true">自动选材 · 批量生成</el-button>
      <el-tag effect="plain" class="dim">≈ ¥1/条 · 约1分钟</el-tag>
    </div>

    <!-- ===== 上: 三列工作区 ===== -->
    <div class="stage">
      <!-- 左: 参考槽位 -->
      <div class="col slots">
        <div v-for="s in SLOTS" :key="s.key" class="slot" :class="{ filled: sel[s.key] }">
          <div class="slot-head">
            <span>{{ s.icon }} {{ s.label }}</span>
            <span v-if="s.required" class="req">*</span>
            <el-icon v-if="sel[s.key]" class="clr" @click="sel[s.key] = ''"><Close /></el-icon>
          </div>
          <div v-if="sel[s.key]" class="thumb" @click="openPicker('slot', { key: s.key, groups: s.groups, upload: s.upload })">
            <img :src="assetUrl(sel[s.key])" />
            <div class="fname">{{ fname(sel[s.key]) }}</div>
          </div>
          <div v-else class="drop" @click="openPicker('slot', { key: s.key, groups: s.groups, upload: s.upload })">
            <el-icon><Plus /></el-icon><span>{{ s.desc }}</span>
          </div>
        </div>

        <!-- 可拓展: 追加参考槽 -->
        <div v-for="(e, i) in extras" :key="i" class="slot" :class="{ filled: e.path }">
          <div class="slot-head">
            <span>➕ 追加参考{{ i + 1 }}</span>
            <el-icon class="clr" @click="extras.splice(i, 1)"><Close /></el-icon>
          </div>
          <div v-if="e.path" class="thumb" @click="openPicker('extra', { idx: i, groups: ['image', 'garment'] })">
            <img :src="assetUrl(e.path)" /><div class="fname">{{ fname(e.path) }}</div>
          </div>
          <div v-else class="drop" @click="openPicker('extra', { idx: i, groups: ['image', 'garment'] })">
            <el-icon><Plus /></el-icon><span>选参考图</span>
          </div>
        </div>
        <div v-if="extras.length < MAX_EXTRA" class="slot-add" @click="addExtra">
          <el-icon><Plus /></el-icon> 添加参考槽
        </div>
      </div>

      <!-- 中: 对标视频 + 提示词 -->
      <div class="col mid" ref="midEl">
        <div class="video-slot" :class="{ filled: source }">
          <template v-if="source">
            <video :src="assetUrl(source)" controls muted class="vprev" />
            <div class="vbar">
              <span class="fname">{{ fname(source) }}</span>
              <el-button size="small" text @click="openPicker('source', { groups: ['source'], upload: 'source', accept: 'video/*' })">
                更换
              </el-button>
            </div>
          </template>
          <div v-else class="drop big" @click="openPicker('source', { groups: ['source'], upload: 'source', accept: 'video/*' })">
            <el-icon :size="30"><VideoPlay /></el-icon>
            <span>放入对标视频</span>
            <span class="dim" style="font-size:12px">点击从素材库选择或本地上传</span>
          </div>
        </div>
        <div class="vsplit" :class="{ on: splitting }" title="拖拽调整提示词区高度 · 双击收起/还原"
             @mousedown="startSplit" @dblclick="togglePrompt">
          <span class="grip"></span>
        </div>
        <el-input v-model="prompt" type="textarea" resize="none"
                  class="prompt-box" :style="{ height: promptH + 'px' }"
                  placeholder="提示词（可空）· 左侧槽位自动标注为参考图1/2/3…，可直接在提示词里引用；不填则用默认换人文案" />
        <div class="opt-row">
          <el-radio-group v-model="resolution" size="small">
            <el-radio-button value="768P">768P</el-radio-button>
            <el-radio-button value="480p">480p 省钱</el-radio-button>
            <el-radio-button value="2K">2K 高清</el-radio-button>
          </el-radio-group>
          <span class="dim" style="font-size:12px">画幅</span>
          <el-radio-group v-model="ratio" size="small">
            <el-radio-button value="adaptive">自适应</el-radio-button>
            <el-radio-button value="9:16">9:16 竖屏</el-radio-button>
            <el-radio-button value="16:9">16:9 横屏</el-radio-button>
            <el-radio-button value="1:1">1:1 方形</el-radio-button>
          </el-radio-group>
          <span class="dim" style="font-size:12px">时长</span>
          <el-select v-model="duration" size="small" style="width:104px" clearable
                     placeholder="跟随原片">
            <el-option v-for="s in 12" :key="s + 3" :value="s + 3" :label="`${s + 3} 秒`" />
          </el-select>
          <el-checkbox v-model="keepAudio" size="small">保留原音轨</el-checkbox>
          <el-select v-model="tplSel" size="small" style="width:132px" clearable
                     placeholder="提示词模板" @change="applyTpl">
            <el-option v-for="t in templates" :key="t.name" :value="t.name" :label="t.name" />
          </el-select>
          <el-button size="small" text :disabled="!prompt.trim()"
                     @click="saveTpl">存模板</el-button>
          <el-button v-if="tplSel" size="small" text type="danger"
                     @click="delTpl">删模板</el-button>
          <el-button type="primary" :loading="submitting" @click="submit">开始转换</el-button>
        </div>
      </div>

      <!-- 右: 结果槽 -->
      <div class="col result">
        <div class="slot-head" style="margin-bottom:8px"><span>🎬 结果</span>
          <el-icon v-if="!activeJob" class="clr" @click="pollJobs(); loadOutputs()"><Refresh /></el-icon>
        </div>
        <template v-if="activeJob">
          <div class="running">
            <el-icon class="is-loading" :size="26"><Refresh /></el-icon>
            <div class="mono">{{ activeJob.id }}</div>
            <div class="dim">已运行 {{ elapsed }} · 完成后自动进审核队列</div>
          </div>
        </template>
        <template v-else-if="resultId">
          <video :src="mediaUrl(resultId)" controls class="vprev" />
          <div class="dim" style="font-size:12px;margin-top:6px">最新产出 · {{ latestJob.id }}</div>
          <el-button size="small" style="margin-top:8px" @click="router.push('/review')">去审核队列 →</el-button>
        </template>
        <template v-else-if="latestJob && latestJob.status === 'error'">
          <div class="err">
            <div>上一次转换失败</div>
            <div class="dim mono" style="font-size:11.5px">{{ latestJob.result?.error }}</div>
            <el-button v-if="latestJob.result?.provider_task" size="small" type="warning" plain
                       style="margin-top:10px" :loading="recovering"
                       @click="recoverJob(latestJob.id)">
              远端可能已生成 — 尝试取回</el-button>
            <el-button size="small" text type="warning" style="margin-top:6px"
                       :loading="recovering" @click="manualRecover(latestJob.id)">
              已在服务商后台? 填 task_id 取回</el-button>
          </div>
        </template>
        <template v-else-if="latestJob && latestJob.status === 'unknown'">
          <div class="err">
            <div>上一次提交状态待核对</div>
            <div class="dim mono" style="font-size:11.5px">{{ latestJob.result?.error }}</div>
            <div class="dim" style="font-size:12px;margin-top:4px">
              远端可能已生成({{ latestJob.result?.provider_via || '?' }}), 先取回或后台核对, 勿直接重发避免重复扣费</div>
            <el-button v-if="latestJob.result?.provider_task" size="small" type="warning"
                       style="margin-top:10px" :loading="recovering"
                       @click="recoverJob(latestJob.id)">
              按 task_id 取回结果</el-button>
            <el-button size="small" text type="warning" style="margin-top:6px"
                       :loading="recovering" @click="manualRecover(latestJob.id)">
              手动填 task_id 取回</el-button>
          </div>
        </template>
        <div v-else class="drop" style="min-height:180px">
          <span class="dim">还没有产出</span>
          <span class="dim" style="font-size:12px">左侧选好参考 + 中间放入视频后点「开始转换」</span>
        </div>
      </div>
    </div>

    <!-- ===== 下: 产出素材管理 (单行横排分页) ===== -->
    <div class="outbar">
      <div class="out-head">
        <span>产出素材 <span class="dim">({{ outs.length }})</span></span>
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="outs.length"
                       layout="prev, pager, next" small background hide-on-single-page />
      </div>
      <div ref="stripEl" class="strip">
        <div v-for="it in pageItems" :key="it._state + it.id" class="ocard" @click="preview = it">
          <video :src="mediaUrl(it.id)" preload="metadata" muted class="cover" />
          <el-tag class="stag" size="small" effect="dark" :type="STATE_TAG[it._state].type">
            {{ STATE_TAG[it._state].label }}
          </el-tag>
          <div class="ometa">
            <div class="otitle">{{ it.title || it.id }}</div>
            <div class="dim otime">{{ fmtTime(it.created_at) }}</div>
          </div>
        </div>
        <div v-if="!outs.length" class="oempty dim">暂无产出 — 完成一次转换后会出现在这里</div>
      </div>
    </div>

    <!-- ===== 素材选择弹窗 ===== -->
    <el-dialog :model-value="!!picker" :title="picker?.target === 'source' ? '选择对标视频' : '选择参考图'"
               width="640px" @close="picker = null">
      <div class="pick-grid" v-on="pickDrop" :class="{ 'drop-active': pickDragging }">
        <div v-for="p in pickerAssets" :key="p" class="pcell" @click="pick(p)">
          <video v-if="isVideoPath(p)" :src="assetUrl(p)" preload="metadata" muted />
          <img v-else :src="assetUrl(p)" />
          <div class="pname">{{ fname(p) }}</div>
        </div>
        <label class="pcell pup">
          <el-icon :size="22"><Upload /></el-icon>
          <span>{{ uploading ? '上传中…' : pickDragging ? '松开上传' : '本地上传 / 拖入' }}</span>
          <input type="file" :accept="picker?.accept" hidden :disabled="uploading" @change="pickUpload" />
        </label>
        <div v-if="!pickerAssets.length" class="dim" style="grid-column:1/-1;text-align:center;padding:20px">
          素材库还没有可用素材 — 点「本地上传」或去 <el-link @click="router.push('/assets')">素材库</el-link> 添加
        </div>
      </div>
    </el-dialog>

    <!-- ===== 自动选材 / 批量生成 ===== -->
    <el-dialog :model-value="mat" title="自动选材 · 批量生成" width="780px" @close="mat = false">
      <div class="mat-sec">
        <div class="mat-head">
          <b>⓪ 备料池</b>
          <el-tag size="small" effect="plain">agent 已按方向筛好</el-tag>
          <div style="flex:1"></div>
          <el-button size="small" text :loading="scouting" @click="scoutNow">立即备料</el-button>
          <el-button size="small" text @click="loadPool">刷新</el-button>
        </div>
        <div v-if="!poolGroups.length" class="dim" style="font-size:12px;padding:2px 0 8px">
          暂无备料 — 在定时任务里加 material_scout(如 0 9 * * *) 每日自动备,
          或点[立即备料]手动跑一次
        </div>
        <div v-for="g in poolGroups" :key="g.name">
          <div class="pool-dir">{{ g.name }} <span class="dim">{{ g.items.length }}条</span></div>
          <div class="pick-grid mgrid">
            <div v-for="it in g.items" :key="it.id" class="pcell"
                 :class="{ sel: (it.kind === 'video' ? vSel : cSel).has(it.id) }"
                 :title="[it.author, it.reason,
                          it.score != null ? `AI评分${it.score}` : ''].filter(Boolean).join(' · ')"
                 @click="poolToggle(it)">
              <img :src="it.kind === 'video' ? it.thumb : assetUrl(it.path)" />
              <span class="soc-tag">{{ it.provider === 'xhs' ? '红' : it.provider === 'douyin' ? '抖' : '衣' }}</span>
              <span v-if="it.score != null" class="dur">{{ it.score }}</span>
              <div class="pname">{{ it.desc || it.id }}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="mat-sec">
        <div class="mat-head">
          <b>① 对标视频</b>
          <el-input v-model="mVkw" size="small" style="width:180px"
                    placeholder="关键词: 人物口播 / talking head" />
          <el-select v-model="mVcount" size="small" style="width:78px">
            <el-option v-for="n in [4, 8, 12, 16]" :key="n" :value="n" :label="`${n}个`" />
          </el-select>
          <el-checkbox v-model="mPortrait" size="small">竖屏优先</el-checkbox>
          <el-button size="small" type="primary" plain :loading="mBusy === 'v'"
                     @click="mSearch('video')">搜索</el-button>
          <span class="dim" style="font-size:11px">源: {{ mProv || 'pexels/commons' }}</span>
        </div>
        <div class="pick-grid mgrid">
          <div v-for="v in vCands" :key="v.id" class="pcell" :class="{ sel: vSel.has(v.id) }"
               :title="[v.author, v.likes != null ? `赞${v.likes}` : '', v.reason].filter(Boolean).join(' · ')"
               @click="toggle(vSel, v.id)">
            <img :src="v.thumb" />
            <span v-if="v.duration" class="dur">{{ v.duration }}s</span>
            <span v-if="v.provider === 'xhs' || v.provider === 'douyin'"
                  class="soc-tag">{{ v.provider === 'xhs' ? '红' : '抖' }}</span>
            <div class="pname">{{ v.desc || v.id }}</div>
          </div>
          <div v-if="!vCands.length" class="dim mat-empty">搜索后在此勾选要用的视频</div>
        </div>
      </div>

      <div class="mat-sec">
        <div class="mat-head">
          <b>② 社媒对标视频</b>
          <el-tag size="small" effect="plain">小红书 / 抖音</el-tag>
          <el-input v-model="socBrief" size="small" style="width:200px"
                    placeholder="主题: 职场西装穿搭口播" @keyup.enter="socDoPlan" />
          <el-button size="small" :loading="socBusy === 'plan'"
                     @click="socDoPlan">AI规划检索词</el-button>
          <el-button size="small" :loading="socBusy === 'rank'" :disabled="!vCands.length"
                     @click="socRank">AI初筛前8</el-button>
        </div>
        <div v-if="socPlan" class="plan-row">
          小红书: {{ socPlan.xhs_queries?.join(' / ') || '—' }} ·
          抖音: {{ socPlan.douyin_queries?.join(' / ') || '—' }}
          <template v-if="socPlan.garment_queries?.length">
            · 服装: {{ socPlan.garment_queries.join(' / ') }}</template>
          <template v-if="socPlan.rank_rule"> · 偏好: {{ socPlan.rank_rule }}</template>
        </div>
        <div v-for="pf in ['xhs', 'douyin']" :key="pf" class="mat-head soc-row">
          <span class="soc-name">{{ SOC_NAME[pf] }}</span>
          <el-input v-model="socKw[pf]" size="small" style="width:180px"
                    :placeholder="`${SOC_NAME[pf]}检索词`" @keyup.enter="socSearch(pf)" />
          <el-button size="small" type="primary" plain :loading="socBusy === pf"
                     @click="socSearch(pf)">搜索</el-button>
          <span v-if="socStatus[pf]?.logging_in" class="dim" style="font-size:11.5px">
            登录窗口已打开, 等待扫码…</span>
          <el-button v-else size="small" text
                     :type="socStatus[pf]?.need_login || !socStatus[pf]?.profile ? 'danger' : 'info'"
                     @click="socLogin(pf)">
            {{ socStatus[pf]?.need_login ? '需扫码登录' : '扫码登录' }}
          </el-button>
          <span v-if="!socStatus[pf]?.profile && !socStatus[pf]?.logging_in"
                class="dim" style="font-size:11px">首次使用需扫码登录</span>
        </div>
      </div>

      <div class="mat-sec">
        <div class="mat-head">
          <b>③ 服装参考</b>
          <el-radio-group v-model="clothMode" size="small">
            <el-radio-button value="search">搜图</el-radio-button>
            <el-radio-button value="gen">AI换装(固定人物)</el-radio-button>
          </el-radio-group>
          <template v-if="clothMode === 'search'">
            <el-input v-model="mCkw" size="small" style="width:160px"
                      placeholder="关键词: 西装 / 连衣裙 / ootd" />
            <el-select v-model="mCcount" size="small" style="width:78px">
              <el-option v-for="n in [4, 8, 12, 16]" :key="n" :value="n" :label="`${n}个`" />
            </el-select>
            <el-button size="small" type="primary" plain :loading="mBusy === 'c'"
                       @click="mSearch('image')">搜索</el-button>
          </template>
        </div>
        <div v-if="clothMode === 'gen'" class="genrow">
          <el-input v-model="genPrompts" type="textarea" :rows="2" resize="none"
                    :placeholder="'每行一条服装描述，基于当前人脸/身体参考图生成同款造型:\n黑色西装套装\n白色连衣裙\n牛仔夹克配白T'" />
          <el-button size="small" type="primary" plain :loading="mBusy === 'gen'"
                     @click="mGenLooks">生成造型图</el-button>
        </div>
        <div class="pick-grid mgrid">
          <div v-for="c in cCands" :key="c.id" class="pcell" :class="{ sel: cSel.has(c.id) }"
               @click="toggle(cSel, c.id)">
            <img :src="c.thumb" />
            <div class="pname">{{ c.desc || c.id }}</div>
          </div>
          <div v-if="!cCands.length" class="dim mat-empty">搜图或 AI 换装后在此勾选服装</div>
        </div>
      </div>

      <template #footer>
        <div style="display:flex;align-items:center;gap:10px">
          <span class="dim" style="font-size:12px">
            已选 视频×{{ vSel.size }} · 服装×{{ cSel.size }} → {{ batchCount }} 单
          </span>
          <div style="flex:1"></div>
          <el-button :loading="mBusy === 'dl'" @click="mImport">仅入库</el-button>
          <el-button type="primary" :loading="mBusy === 'run'" :disabled="!vSel.size"
                     @click="batchRun">批量生成</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- ===== 产出预览弹窗 ===== -->
    <el-dialog :model-value="!!preview" :title="preview?.title || preview?.id" width="560px"
               @close="preview = null">
      <template v-if="preview">
        <video :src="mediaUrl(preview.id)" controls class="media-video" />
        <div class="dim" style="font-size:12.5px;margin-top:8px">
          {{ STATE_TAG[preview._state].label }} · {{ fmtTime(preview.created_at) }} · {{ preview.job }}
        </div>
      </template>
      <template #footer>
        <template v-if="preview?._state === 'review'">
          <el-button type="success" @click="approve(preview)">通过</el-button>
          <el-button type="danger" plain @click="reject(preview)">打回</el-button>
        </template>
        <el-button v-if="preview?._state === 'approved'" type="primary"
                   :loading="busy === preview.id" @click="publish(preview)">发布到抖音</el-button>
        <el-button @click="preview = null">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 一屏布局: 整页不滚动, 上工作区自适应 + 下产出条固定高 */
.tpage { height: 100%; box-sizing: border-box; display: flex; flex-direction: column; overflow: hidden; }
.tpage .page-head { margin-bottom: 12px; flex-shrink: 0; }

.stage { flex: 1; min-height: 0; display: grid; grid-template-columns: 250px 1fr 300px; gap: 14px; }
.col { min-height: 0; display: flex; flex-direction: column; }

/* ---- 左: 槽位列 ---- */
.slots { overflow-y: auto; gap: 10px; padding-right: 2px; }
.slot {
  border: 1px dashed var(--aimf-line); border-radius: 12px; padding: 8px;
  background: rgba(19, 23, 34, .6); flex-shrink: 0;
}
.slot.filled { border-style: solid; border-color: rgba(99, 102, 241, .5); }
.slot-head { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; }
.slot-head .req { color: #f87171; }
.slot-head .clr { margin-left: auto; cursor: pointer; color: var(--aimf-dim); }
.slot-head .clr:hover { color: #f87171; }
.drop {
  margin-top: 6px; min-height: 64px; border-radius: 8px; cursor: pointer;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
  color: var(--aimf-dim); font-size: 12px; background: #0d1119; transition: all .15s;
}
.drop:hover { color: #a5b4fc; box-shadow: inset 0 0 0 1px rgba(99, 102, 241, .45); }
.drop.big { min-height: 0; flex: 1; margin-top: 0; }
.thumb { margin-top: 6px; cursor: pointer; position: relative; }
.thumb img { width: 100%; max-height: 130px; object-fit: cover; border-radius: 8px; display: block; }
.fname { font-size: 10.5px; color: var(--aimf-dim); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.slot-add {
  flex-shrink: 0; padding: 7px; border-radius: 10px; cursor: pointer; text-align: center;
  color: var(--aimf-dim); font-size: 12px; border: 1px dashed var(--aimf-line);
}
.slot-add:hover { color: #a5b4fc; border-color: rgba(99, 102, 241, .45); }

/* ---- 中: 视频槽 + 提示词 ---- */
.mid { gap: 0; }
.video-slot {
  flex: 1; min-height: 140px; border: 1px dashed var(--aimf-line); border-radius: 12px;
  background: rgba(19, 23, 34, .6); display: flex; flex-direction: column; overflow: hidden;
}
.video-slot.filled { border-style: solid; }
/* 视频以视频框为界、整体可见(高度受限时按高度、宽度受限时按宽度), 不裁剪不拉伸 */
.vprev { width: 100%; flex: 1; min-height: 0; object-fit: contain; background: #000; }

/* 视频/提示词分隔条 */
.vsplit {
  height: 12px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  cursor: row-resize; border-radius: 6px;
}
.vsplit .grip {
  width: 44px; height: 4px; border-radius: 2px;
  background: var(--aimf-line); transition: background .15s, width .15s;
}
.vsplit:hover .grip, .vsplit.on .grip { background: var(--aimf-acc); width: 64px; }
.prompt-box { flex-shrink: 0; }
.prompt-box :deep(.el-textarea__inner) { height: 100%; }
.mid > .opt-row { margin-top: 8px; }
.result .vprev { max-height: none; }
.vbar { display: flex; align-items: center; justify-content: space-between; padding: 4px 10px; }
.opt-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.opt-row .el-button { margin-left: auto; }

/* ---- 右: 结果槽 ---- */
.result {
  border: 1px solid var(--aimf-line); border-radius: 12px; padding: 10px;
  background: rgba(19, 23, 34, .6); overflow-y: auto;
}
.running { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 40px 8px; text-align: center; }
.running .mono { font-size: 11.5px; }
.err { padding: 20px 10px; font-size: 12.5px; color: #fca5a5; }

/* ---- 下: 产出条 ---- */
.outbar { flex-shrink: 0; margin-top: 12px; }
.out-head { display: flex; align-items: center; justify-content: space-between; font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.strip { display: flex; gap: 14px; overflow: hidden; height: 148px; }
.ocard {
  flex: 0 0 180px; border-radius: 10px; overflow: hidden; cursor: pointer; position: relative;
  border: 1px solid var(--aimf-line); background: #0d1119; transition: border-color .15s;
}
.ocard:hover { border-color: rgba(99, 102, 241, .55); }
.ocard .cover { width: 100%; height: 104px; object-fit: cover; display: block; background: #000; }
.ocard .stag { position: absolute; top: 6px; right: 6px; }
.ometa { padding: 5px 8px; }
.otitle { font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.otime { font-size: 10.5px; }
.oempty { margin: auto; font-size: 12.5px; }

/* ---- 素材选择弹窗 ---- */
.pick-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 10px; max-height: 52vh; overflow-y: auto; border: 1px solid transparent; border-radius: 10px; padding: 4px; transition: all .15s; }
.pcell { border: 1px solid var(--aimf-line); border-radius: 8px; overflow: hidden; cursor: pointer; background: #0d1119; }
.pcell:hover { border-color: var(--aimf-acc); }
.pcell img, .pcell video { width: 100%; height: 74px; object-fit: cover; display: block; background: #000; }
.pname { font-size: 10px; color: var(--aimf-dim); padding: 3px 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pup { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; min-height: 96px; color: var(--aimf-dim); font-size: 12px; }
.pup:hover { color: #a5b4fc; }

/* ---- 自动选材 ---- */
.mat-sec + .mat-sec { margin-top: 16px; }
.mat-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.mat-head b { font-size: 13.5px; }
.mgrid { max-height: 210px; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); }
.mgrid .pcell { position: relative; }
.pcell.sel { border-color: var(--aimf-acc); box-shadow: 0 0 0 2px rgba(99, 102, 241, .4); }
.pcell.sel::after {
  content: '✓'; position: absolute; top: 4px; left: 4px; width: 18px; height: 18px;
  border-radius: 50%; background: var(--aimf-acc); color: #fff; font-size: 11px;
  display: grid; place-items: center;
}
.pcell .dur {
  position: absolute; top: 4px; right: 4px; background: rgba(0, 0, 0, .65);
  color: #fff; font-size: 10px; border-radius: 4px; padding: 0 5px;
}
.genrow { display: flex; gap: 10px; margin-bottom: 8px; align-items: flex-start; }
.genrow .el-button { flex-shrink: 0; margin-top: 2px; }
.mat-empty { grid-column: 1/-1; text-align: center; padding: 18px; font-size: 12px; }

/* ---- 社媒采集 ---- */
.soc-tag {
  position: absolute; bottom: 22px; left: 4px; width: 16px; height: 16px;
  border-radius: 4px; background: rgba(0, 0, 0, .7); color: #fda4af;
  font-size: 10px; display: grid; place-items: center;
}
.plan-row { font-size: 11.5px; color: var(--aimf-dim); margin: -2px 0 8px; }
.soc-row { margin-bottom: 6px; }
.soc-name { font-size: 12.5px; width: 42px; flex-shrink: 0; }
.pool-dir { font-size: 12.5px; font-weight: 600; margin: 8px 0 6px; }
</style>
