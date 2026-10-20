<script setup>
// 带货视频 (B 线): 意图 + 固定人物照片 + 本期商品图
// -> 编导 Agent 生成 DirectorPlan(视觉概念/分镜/逐镜提示词)
// -> 确认 -> 逐镜生成 -> 合成 -> 审核
// 原则: 无口播; 不提交参考视频; 人物照片固定、商品图随时换。
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, assetUrl, mediaUrl } from '../api'
import { store, refreshMeta } from '../store'
import { useFileDrop } from '../composables/useFileDrop'

const route = useRoute()
const router = useRouter()
const STATE_KEY = 'pv_state_v1'

const SHOT_FUNCS = ['视觉钩子', '产品揭晓', '材质特写', '使用演示',
  '对比证明', '场景融入', '颜色切换', '结尾卡']

const intent = ref('')
const personPhotos = ref([])
const productImages = ref([])
const backgroundImages = ref([])
const bgm = ref('')
const pacing = ref('fast')

const plan = ref(null)
const busy = ref('')          // plan | job | upload
const job = ref(null)
const jobId = ref('')
const recentPlans = ref([])
const recentId = ref('')
const newDraft = ref(false)
let timer = null

const JOB_STATUS = {
  running: '生成中', done: '已完成', error: '失败',
  unknown: '待核对', interrupted: '已中断', queued: '排队中',
}
const SHOT_STATUS = {
  pending: '待生成', running: '生成中', done: '完成', failed: '失败',
}

const groups = {
  person: personPhotos,
  product: productImages,
  background: backgroundImages,
}

const picker = ref(null)      // { kind, selected: [] }

const { dragging: personDragging, dropProps: personDrop } = useFileDrop({
  accept: ['image/*'], onFiles: files => uploadFiles('person', files),
})
const { dragging: productDragging, dropProps: productDrop } = useFileDrop({
  accept: ['image/*'], onFiles: files => uploadFiles('product', files),
})
const { dragging: backgroundDragging, dropProps: backgroundDrop } = useFileDrop({
  accept: ['image/*'], onFiles: files => uploadFiles('background', files),
})

const bgmList = computed(() => store.assets.bgm || [])
const totalDuration = computed(() =>
  (plan.value?.shots || []).reduce((n, s) => n + Number(s.duration || 0), 0))
const estCost = computed(() => (totalDuration.value * 0.09).toFixed(2))
const resultId = computed(() => job.value?.result?.item_id || '')

const shotStatus = (i) => {
  const fromJob = (job.value?.result?.shots || []).find(x => x.index === i)
  if (fromJob) return fromJob.status
  const fromPlan = (plan.value?.shots || []).find(x => x.index === i)
  return fromPlan?.status || 'pending'
}

const faceArcText = (s) => {
  const f = s?.face_arc || {}
  return [f.start, f.turn, f.end].filter(Boolean).join(' → ')
}

const progress = computed(() => {
  const shots = plan.value?.shots || []
  if (!shots.length) return 0
  const done = shots.filter(s => shotStatus(s.index) === 'done').length
  return Math.round(done / shots.length * 100)
})

function snapshot() {
  return {
    intent: intent.value,
    personPhotos: [...personPhotos.value],
    productImages: [...productImages.value],
    backgroundImages: [...backgroundImages.value],
    bgm: bgm.value,
    pacing: pacing.value,
    planId: plan.value?.id || '',
    jobId: jobId.value || '',
    newDraft: newDraft.value,
  }
}

function saveState() {
  try { localStorage.setItem(STATE_KEY, JSON.stringify(snapshot())) } catch { /* 忽略 */ }
}

function restoreState() {
  try {
    const s = JSON.parse(localStorage.getItem(STATE_KEY) || 'null')
    if (!s) return null
    intent.value = s.intent || ''
    personPhotos.value = Array.isArray(s.personPhotos) ? s.personPhotos : []
    productImages.value = Array.isArray(s.productImages) ? s.productImages : []
    backgroundImages.value = Array.isArray(s.backgroundImages) ? s.backgroundImages : []
    bgm.value = s.bgm || ''
    pacing.value = s.pacing || 'fast'
    newDraft.value = !!s.newDraft
    return { planId: s.planId || '', jobId: s.jobId || '', newDraft: !!s.newDraft }
  } catch {
    return null
  }
}

function stopTimer() {
  if (timer) { clearInterval(timer); timer = null }
}

watch(
  () => [intent.value, personPhotos.value, productImages.value,
    backgroundImages.value, bgm.value, pacing.value, plan.value?.id || '',
    jobId.value, newDraft.value],
  saveState,
  { deep: true },
)

function pickFiles(kind) {
  const inp = document.createElement('input')
  inp.type = 'file'
  inp.accept = 'image/*'
  inp.multiple = true
  inp.onchange = () => {
    const files = [...(inp.files || [])]
    inp.value = ''
    uploadFiles(kind, files)
  }
  inp.click()
}

async function uploadFiles(kind, files) {
  if (!files?.length) return
  busy.value = 'upload'
  try {
    for (const f of files) {
      const r = await api.upload(f, kind)
      groups[kind].value.push(r.path)
    }
    ElMessage.success(`已上传 ${files.length} 张`)
    store.loaded = false
    await refreshMeta(true)
  } catch (e) {
    ElMessage.error('上传失败: ' + e.message)
  } finally {
    busy.value = ''
  }
}

function openPicker(kind) {
  picker.value = { kind, selected: [...groups[kind].value] }
}

function togglePick(p) {
  const sel = picker.value.selected
  const i = sel.indexOf(p)
  if (i >= 0) sel.splice(i, 1)
  else sel.push(p)
}

function confirmPicker() {
  if (!picker.value) return
  groups[picker.value.kind].value = [...picker.value.selected]
  picker.value = null
}

function removeAsset(kind, i) {
  groups[kind].value.splice(i, 1)
}

async function loadRecentPlans() {
  try {
    recentPlans.value = await api.get('/api/product-video/plans')
  } catch { recentPlans.value = [] }
}

async function loadPlanById(id) {
  if (!id) return null
  const p = await api.get('/api/product-video/plan/' + id)
  plan.value = p
  intent.value = p.intent || ''
  personPhotos.value = [...(p.assets?.person_photos || [])]
  productImages.value = [...(p.assets?.product_images || [])]
  backgroundImages.value = [...(p.assets?.background_images || [])]
  bgm.value = p.bgm || ''
  pacing.value = p.meta?.pacing || 'fast'
  recentId.value = p.id
  newDraft.value = false
  return p
}

async function loadRecent(id) {
  if (!id) return
  try {
    stopTimer()
    await loadPlanById(id)
    job.value = null
    jobId.value = ''
    saveState()
    ElMessage.success('已载入方案：' + (plan.value.title || plan.value.id))
  } catch (e) {
    ElMessage.error('载入方案失败: ' + e.message)
  }
}

async function loadJob(id, { silent = false } = {}) {
  if (!id) return null
  const j = await api.get('/api/jobs/' + id)
  job.value = j
  jobId.value = j.id
  newDraft.value = false
  if (j.params?.plan_id && plan.value?.id !== j.params.plan_id) {
    try { await loadPlanById(j.params.plan_id) } catch { /* 方案可能已删除 */ }
  }
  if (j.status === 'running') {
    stopTimer()
    timer = setInterval(pollJob, 3000)
  } else if (!silent) {
    ElMessage.success(j.status === 'done' ? '已载入已完成任务' : '已载入任务')
  }
  saveState()
  return j
}

async function generatePlan() {
  if (!intent.value.trim()) { ElMessage.warning('先描述你想做的视频'); return }
  if (!personPhotos.value.length) { ElMessage.warning('先上传至少 1 张人物照片'); return }
  if (!productImages.value.length) { ElMessage.warning('先上传至少 1 张商品图'); return }
  busy.value = 'plan'
  stopTimer()
  job.value = null
  jobId.value = ''
  try {
    plan.value = await api.post('/api/product-video/plan', {
      intent: intent.value,
      person_photos: personPhotos.value,
      product_images: productImages.value,
      background_images: backgroundImages.value,
      bgm: bgm.value || null,
      pacing: pacing.value,
    })
    recentId.value = plan.value.id
    newDraft.value = false
    await loadRecentPlans()
    saveState()
    ElMessage.success('编导方案已生成，可修改分镜后生成视频')
  } catch (e) {
    ElMessage.error('生成方案失败: ' + e.message)
  } finally {
    busy.value = ''
  }
}

async function savePlan(notify = true) {
  if (!plan.value) return null
  plan.value.meta = plan.value.meta || {}
  plan.value.meta.duration = totalDuration.value
  plan.value.meta.pacing = pacing.value
  try {
    plan.value = await api.put(`/api/product-video/plan/${plan.value.id}`, plan.value)
    if (notify) ElMessage.success('方案已保存')
    return plan.value
  } catch (e) {
    ElMessage.error('保存失败: ' + e.message)
    throw e
  }
}

async function compilePlan() {
  if (!plan.value) return
  await savePlan(false)
  try {
    plan.value = await api.post(`/api/product-video/plan/${plan.value.id}/compile`)
    ElMessage.success('已按结构化字段重新编译逐镜提示词')
  } catch (e) {
    ElMessage.error('编译失败: ' + e.message)
  }
}

async function generateVideo() {
  if (!plan.value) return
  busy.value = 'job'
  stopTimer()
  try {
    await savePlan(false)
    plan.value = await api.post(`/api/product-video/plan/${plan.value.id}/compile`)
    const r = await api.post('/api/jobs/product-video', {
      plan_id: plan.value.id,
      bgm: bgm.value || plan.value.bgm || null,
    })
    jobId.value = r.job
    job.value = { status: 'running', result: { shots: [] } }
    saveState()
    ElMessage.success('任务已发送，正在逐镜生成')
    pollJob()
    timer = setInterval(pollJob, 3000)
  } catch (e) {
    ElMessage.error('提交失败: ' + e.message)
    busy.value = ''
  }
}

async function pollJob() {
  if (!jobId.value) return
  try {
    const j = await api.get('/api/jobs/' + jobId.value)
    job.value = j
    if (j.status !== 'running') {
      stopTimer()
      busy.value = ''
      saveState()
      if (j.status === 'done') ElMessage.success('视频已生成，已进入审核队列')
      else ElMessage.error('生成失败: ' + (j.result?.error || j.status))
    }
  } catch { /* 轮询失败静默重试 */ }
}

async function newPlan() {
  if (plan.value || jobId.value) {
    const ok = await ElMessageBox.confirm(
      '新建会清空当前方案和本期商品图（保留固定人物照片、背景和 BGM），继续？',
      '新建带货视频', { type: 'warning', confirmButtonText: '新建', cancelButtonText: '取消' },
    ).then(() => true).catch(() => false)
    if (!ok) return
  }
  stopTimer()
  plan.value = null
  job.value = null
  jobId.value = ''
  recentId.value = ''
  intent.value = ''
  productImages.value = []
  newDraft.value = true
  saveState()
}

async function restoreOnEnter() {
  await refreshMeta().catch(() => {})
  await loadRecentPlans()
  const saved = restoreState()

  let targetPlanId = typeof route.query.plan === 'string' ? route.query.plan : ''
  let targetJobId = saved?.jobId || ''
  if (!targetPlanId && saved?.planId) targetPlanId = saved.planId

  // 没有保存过状态时：自动恢复最近一条带货任务（运行中或 24 小时内）
  // 用户主动点过「新建」则不自动拉回旧任务
  if (!targetPlanId && !targetJobId && !saved?.newDraft) {
    try {
      const jobs = await api.get('/api/jobs')
      const latest = jobs.find(j => j.type === 'product_video' &&
        (j.status === 'running' ||
          Date.now() / 1000 - (j.created_at || 0) < 86400))
      if (latest) {
        targetJobId = latest.id
        targetPlanId = latest.params?.plan_id || ''
      }
    } catch { /* 忽略 */ }
  }

  if (targetPlanId) {
    try { await loadPlanById(targetPlanId) } catch { /* 方案可能已删除 */ }
  }
  if (targetJobId) {
    try { await loadJob(targetJobId, { silent: true }) } catch { /* 任务可能已过期 */ }
  }
  saveState()
}

onMounted(restoreOnEnter)
onUnmounted(() => { saveState(); stopTimer() })
</script>

<template>
  <div class="page pv-page">
    <div class="page-head">
      <h2>带货视频</h2>
      <span class="sub">固定人物照片 · 换商品图 · 编导 Agent 设计画面与提示词 · 无口播视觉展示</span>
      <div class="sp" />
      <el-button size="small" @click="newPlan">新建</el-button>
      <el-select v-model="recentId" placeholder="最近方案" size="small" clearable
                 style="width:230px" @change="loadRecent">
        <el-option v-for="p in recentPlans" :key="p.id" :value="p.id"
                   :label="`${p.title || p.id} · ${p.shots}镜`" />
      </el-select>
      <el-tag effect="plain">仅图片驱动 · 不提交参考视频</el-tag>
    </div>

    <div class="pv-grid">
      <!-- 左：意图 + 资产 -->
      <div class="pv-left">
        <div class="aimf-card">
          <h3>① 意图</h3>
          <el-input
            v-model="intent" type="textarea" :rows="4"
            placeholder="例：用这组人物照片和这组羽绒服图，做一条 15 秒视觉冲击型带货视频，突出轻、暖、可收纳，快节奏，9:16，无口播。"
          />
          <div class="pv-hint">Agent 会设计视觉概念、分镜、运镜、转场和逐镜提示词；不写口播台词。</div>
          <div class="pv-pace-row">
            <span class="pv-hint">节奏</span>
            <el-select v-model="pacing" size="small" style="width:150px">
              <el-option value="fast" label="快节奏（推荐）" />
              <el-option value="medium" label="中速" />
              <el-option value="slow" label="慢节奏" />
            </el-select>
            <span class="pv-hint">计划 2–4 秒/镜，生成后自动裁剪</span>
          </div>
        </div>

        <div class="aimf-card">
          <h3>
            ② 固定资产 · 人物照片
            <el-tag size="small" type="success" effect="plain">长期复用</el-tag>
          </h3>
          <div class="pv-thumbs" :class="{ 'drop-active': personDragging }" v-on="personDrop">
            <div v-for="(p, i) in personPhotos" :key="p + i" class="pv-thumb">
              <img :src="assetUrl(p)" />
              <span class="pv-x" @click="removeAsset('person', i)">×</span>
            </div>
            <div class="pv-add" title="点击上传，或把图片拖到这一区域" @click="pickFiles('person')">
              ＋<span>{{ personDragging ? '松开' : '上传' }}</span>
            </div>
          </div>
          <div class="pv-tools">
            <el-button size="small" text @click="openPicker('person')">从素材库选</el-button>
            <span class="pv-hint">1–5 张同一人的照片；商品图未覆盖的下装/配饰保持这里</span>
          </div>
        </div>

        <div class="aimf-card">
          <h3>
            ③ 流动资产 · 本期商品图
            <el-tag size="small" type="warning" effect="plain">随时换</el-tag>
          </h3>
          <div class="pv-thumbs" :class="{ 'drop-active': productDragging }" v-on="productDrop">
            <div v-for="(p, i) in productImages" :key="p + i" class="pv-thumb">
              <img :src="assetUrl(p)" />
              <span class="pv-x" @click="removeAsset('product', i)">×</span>
            </div>
            <div class="pv-add" title="点击上传，或把图片拖到这一区域" @click="pickFiles('product')">
              ＋<span>{{ productDragging ? '松开' : '上传' }}</span>
            </div>
          </div>
          <div class="pv-tools">
            <el-button size="small" text @click="openPicker('product')">从素材库选</el-button>
            <span class="pv-hint">正面/侧面/细节/包装；未包含的下装/配饰不会新增</span>
          </div>
        </div>

        <div class="aimf-card">
          <h3>背景图 <span class="pv-opt">可选</span></h3>
          <div class="pv-thumbs" :class="{ 'drop-active': backgroundDragging }" v-on="backgroundDrop">
            <div v-for="(p, i) in backgroundImages" :key="p + i" class="pv-thumb">
              <img :src="assetUrl(p)" />
              <span class="pv-x" @click="removeAsset('background', i)">×</span>
            </div>
            <div class="pv-add" title="点击上传，或把图片拖到这一区域" @click="pickFiles('background')">
              ＋<span>{{ backgroundDragging ? '松开' : '上传' }}</span>
            </div>
          </div>
          <div class="pv-tools">
            <el-button size="small" text @click="openPicker('background')">从素材库选</el-button>
            <span class="pv-hint">不传则由 Agent 按意图描述场景</span>
          </div>
        </div>

        <div class="aimf-card">
          <h3>BGM <span class="pv-opt">可选</span></h3>
          <el-select v-model="bgm" clearable placeholder="不加 BGM" style="width:100%">
            <el-option v-for="b in bgmList" :key="b" :value="b.split('/').pop()" :label="b.split('/').pop()" />
          </el-select>
          <div class="pv-hint">H3 原生音轨会被丢弃；选一条 BGM 作为成片音轨。</div>
        </div>

        <el-button type="primary" size="large" style="width:100%"
                   :loading="busy === 'plan'" @click="generatePlan">
          生成编导方案
        </el-button>
      </div>

      <!-- 右：方案 + 生成 -->
      <div class="pv-right">
        <div v-if="!plan && !jobId" class="aimf-card pv-empty">
          <div>
            <div class="pv-empty-title">一句话 + 一组图 → 一条带货视频</div>
            <div class="pv-hint">左侧填意图、上传人物照片和商品图，点击「生成编导方案」。</div>
          </div>
        </div>

        <div v-else-if="!plan && jobId" class="aimf-card">
          <h3>当前任务</h3>
          <div class="pv-meta">
            <el-tag :type="job?.status === 'done' ? 'success' : job?.status === 'error' ? 'danger' : 'warning'">
              {{ JOB_STATUS[job?.status] || job?.status || '生成中' }}
            </el-tag>
            <span class="dim mono" style="font-size:12px">{{ jobId }}</span>
          </div>
          <div class="pv-hint">方案文件未载入，可在任务中心查看完整进度和产物。</div>
          <el-button size="small" type="primary" plain @click="router.push({ name: 'jobs' })">
            去任务中心 →
          </el-button>
        </div>

        <template v-else>
          <div class="aimf-card">
            <h3>
              编导方案 <span class="dim">{{ plan.title }}</span>
            </h3>
            <div class="pv-meta">
              <el-tag>{{ totalDuration }}s</el-tag>
              <el-tag>{{ plan.meta?.aspect_ratio || '9:16' }}</el-tag>
              <el-tag>{{ plan.meta?.resolution || '768P' }}</el-tag>
              <el-tag>{{ plan.meta?.pacing || 'fast' }}</el-tag>
              <el-tag v-if="plan.generation_mode === 'single'" type="success" effect="plain">
                整条一次生成
              </el-tag>
              <el-tag type="warning">≈ ¥{{ estCost }}</el-tag>
              <el-tag v-if="plan.meta?.fallback_reason" type="info" effect="plain">模板兜底</el-tag>
              <el-tag v-if="plan.lint && (!plan.lint.ok || !plan.lint.granularity_ok)"
                      type="warning" effect="plain">提示词待补</el-tag>
            </div>
            <div class="pv-concept">{{ plan.meta?.visual_concept }}</div>
            <div v-if="plan.meta?.direction_name" class="pv-hook">
              创意方向：{{ plan.meta.direction_name }}
              <span v-if="plan.meta?.direction_concept"> · {{ plan.meta.direction_concept }}</span>
            </div>
            <div v-if="plan.meta?.reading" class="pv-hook">解读：{{ plan.meta.reading }}</div>
            <div v-if="plan.constraints?.product?.must_show?.length" class="pv-hook">
              商品必须出现：{{ plan.constraints.product.must_show.join('、') }}
            </div>
            <div v-if="plan.constraints?.product?.must_not_change?.length" class="pv-hook">
              商品不得改变：{{ plan.constraints.product.must_not_change.join('、') }}
            </div>
            <div v-if="plan.constraints?.performance?.require_face_arc" class="pv-hook">
              表演约束：每个有人物镜头必须有可观察的面部/视线/呼吸变化
            </div>
            <div v-if="plan.meta?.motif || plan.meta?.visual_thesis" class="pv-hook">
              母题：{{ plan.meta.motif || '—' }}
              <span v-if="plan.meta?.visual_thesis"> · 记忆画面：{{ plan.meta.visual_thesis }}</span>
            </div>
            <div v-if="plan.meta?.hook" class="pv-hook">视觉钩子：{{ plan.meta.hook }}</div>
            <div v-if="plan.meta?.rhythm" class="pv-hook">节奏：{{ plan.meta.rhythm }}</div>
            <div v-if="plan.meta?.bgm_style" class="pv-hook">BGM 建议：{{ plan.meta.bgm_style }}</div>
            <div v-if="plan.lint && (!plan.lint.ok || !plan.lint.granularity_ok)"
                 class="pv-hook">
              提示词提醒：{{ (plan.lint.errors || []).concat(plan.lint.warnings || []).slice(0, 2).join('；') }}
            </div>
          </div>

          <div v-if="plan.prompt && plan.generation_mode === 'single'" class="aimf-card">
            <h3>整条视频提示词 <span class="dim">一次 H3 生成</span></h3>
            <el-input v-model="plan.prompt" type="textarea" :rows="7" readonly />
          </div>

          <div class="aimf-card">
            <h3>分镜 <span class="dim">{{ plan.shots.length }} 镜 · 逻辑分镜 · 可编辑</span></h3>

            <div v-for="s in plan.shots" :key="s.index" class="pv-shot">
              <div class="pv-shot-head">
                <b>#{{ s.index }}</b>
                <el-input-number v-model="s.duration" :min="2" :max="5" size="small" />
                <span class="dim" style="font-size:12px">秒</span>
                <el-select v-model="s.shot_function" size="small" style="width:148px"
                           allow-create filterable default-first-option>
                  <el-option v-for="f in SHOT_FUNCS" :key="f" :value="f" :label="f" />
                </el-select>
                <el-tag size="small"
                        :type="shotStatus(s.index) === 'done' ? 'success'
                          : shotStatus(s.index) === 'running' ? 'warning' : 'info'">
                  {{ shotStatus(s.index) }}
                </el-tag>
              </div>

              <div class="pv-row">
                <el-input v-model="s.camera" size="small" placeholder="镜头/运镜" />
                <el-input v-model="s.lighting" size="small" placeholder="光线" />
              </div>
              <div class="pv-row">
                <el-input v-model="s.person_action" size="small" placeholder="人物动作" />
                <el-input v-model="s.product_action" size="small" placeholder="商品动作/画面证据" />
              </div>
              <div class="pv-row">
                <el-input v-model="s.start_state" size="small" placeholder="起始画面/承接上一镜" />
                <el-input v-model="s.end_state" size="small" placeholder="结束画面/给下一镜留动作" />
              </div>
              <div class="pv-row">
                <el-input v-model="s.on_screen_text" size="small" placeholder="后期文字（可空）" />
                <el-input v-model="s.transition" size="small" placeholder="切镜/转场" />
              </div>
              <div v-if="faceArcText(s)" class="pv-row">
                <el-input :model-value="faceArcText(s)" size="small" readonly
                          placeholder="面部表演：起始 → 转折 → 结束" />
              </div>
              <div v-if="s.product_evidence?.length" class="pv-hook">
                商品证据：{{ s.product_evidence.join('、') }}
              </div>
              <el-input v-model="s.prompt" type="textarea" :rows="6" size="small" readonly
                        :placeholder="plan.generation_mode === 'single'
                          ? '逻辑分镜片段（整条提示词见上方）'
                          : '逐镜提示词（点「重新编译」生成）'" />
            </div>

            <div class="pv-actions">
              <el-button size="small" @click="savePlan()">保存</el-button>
              <el-button size="small" @click="compilePlan">重新编译提示词</el-button>
              <el-button type="primary" :loading="busy === 'job'" @click="generateVideo">
                生成视频
              </el-button>
            </div>
          </div>

          <div v-if="jobId" class="aimf-card">
            <h3>
              生成进度
              <span class="dim">{{ JOB_STATUS[job?.status] || job?.status || '生成中' }}</span>
              <span class="sp" />
              <el-button size="small" text @click="router.push({ name: 'jobs' })">任务中心 →</el-button>
            </h3>
            <div class="pv-hint mono" style="margin-bottom:8px">{{ jobId }}</div>
            <el-progress :percentage="progress" :status="job?.status === 'error' ? 'exception' : undefined" />
            <div class="pv-shots-status">
              <span v-for="s in plan.shots" :key="s.index"
                    :class="'st-' + shotStatus(s.index)">
                #{{ s.index }} {{ SHOT_STATUS[shotStatus(s.index)] || shotStatus(s.index) }}
              </span>
            </div>
            <video v-if="resultId" :src="mediaUrl(resultId)" controls
                   class="media-video" style="margin-top:12px" />
            <div v-if="resultId" style="margin-top:8px">
              <el-button size="small" type="primary" @click="router.push('/review')">
                去审核队列 →
              </el-button>
            </div>
            <div v-if="job?.result?.error" class="pv-error">{{ job.result.error }}</div>
          </div>
        </template>
      </div>
    </div>

    <!-- 素材库选择器 -->
    <el-dialog :model-value="!!picker" title="从素材库选择" width="680px"
               @close="picker = null">
      <div v-if="picker" class="pv-picker-grid">
        <div v-for="p in (store.assets[picker.kind] || [])" :key="p"
             class="pv-pick" :class="{ on: picker.selected.includes(p) }"
             @click="togglePick(p)">
          <img :src="assetUrl(p)" />
          <span class="pv-pick-name">{{ p.split('/').pop() }}</span>
        </div>
      </div>
      <el-empty v-if="picker && !(store.assets[picker.kind] || []).length"
                description="素材库暂无，先在左侧上传" :image-size="56" />
      <template #footer>
        <el-button @click="picker = null">取消</el-button>
        <el-button type="primary" @click="confirmPicker">使用选中</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.pv-page { max-width: 1500px; }
.pv-grid { display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 18px; align-items: start; }
@media (max-width: 1100px) { .pv-grid { grid-template-columns: 1fr; } }
.pv-left, .pv-right { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.pv-hint { font-size: 12px; color: var(--aimf-dim); margin-top: 6px; line-height: 1.6; }
.pv-opt { font-size: 11px; color: var(--aimf-dim); font-weight: 400; margin-left: 4px; }
.pv-pace-row { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.pv-tools { display: flex; align-items: center; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.pv-tools .pv-hint { margin-top: 0; }
.pv-thumbs { display: flex; flex-wrap: wrap; gap: 8px; border-radius: 12px; padding: 4px; margin: -4px; transition: all .15s; }
.pv-thumb { position: relative; width: 76px; height: 76px; border-radius: 10px; overflow: hidden; border: 1px solid var(--aimf-line); background: #0d1119; }
.pv-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.pv-x { position: absolute; top: 2px; right: 2px; width: 18px; height: 18px; border-radius: 50%; background: rgba(0,0,0,.68); color: #fff; display: grid; place-items: center; cursor: pointer; font-size: 12px; line-height: 1; }
.pv-add { width: 76px; height: 76px; border-radius: 10px; border: 1px dashed var(--aimf-line); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; cursor: pointer; color: var(--aimf-dim); font-size: 15px; transition: all .15s; }
.pv-add span { font-size: 11px; }
.pv-add:hover { border-color: var(--aimf-acc); color: var(--aimf-fg); }
.pv-add.drop-active { border-color: rgba(34,211,238,.85); color: #bdf5ff; }
.pv-empty { min-height: 360px; display: grid; place-items: center; text-align: center; }
.pv-empty-title { font-size: 16px; font-weight: 700; margin-bottom: 6px; }
.pv-meta { display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0; }
.pv-concept { font-size: 14px; line-height: 1.7; color: var(--aimf-fg); }
.pv-hook { font-size: 12.5px; color: var(--aimf-dim); margin-top: 4px; }
.pv-shot { border: 1px solid var(--aimf-line); border-radius: 12px; padding: 12px; margin-bottom: 10px; background: rgba(255,255,255,.02); display: flex; flex-direction: column; gap: 8px; }
.pv-shot-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pv-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
@media (max-width: 700px) { .pv-row { grid-template-columns: 1fr; } }
.pv-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 8px; flex-wrap: wrap; }
.pv-shots-status { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px; font-size: 12px; }
.st-done { color: #34d399; }
.st-running { color: #fbbf24; }
.st-failed { color: #f87171; }
.st-pending { color: var(--aimf-dim); }
.pv-error { margin-top: 8px; color: #f87171; font-size: 12px; white-space: pre-wrap; }
.pv-picker-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 10px; max-height: 440px; overflow: auto; }
.pv-pick { position: relative; border: 2px solid transparent; border-radius: 10px; overflow: hidden; cursor: pointer; background: #0d1119; }
.pv-pick.on { border-color: var(--aimf-acc); box-shadow: 0 0 0 2px rgba(99,102,241,.25); }
.pv-pick img { width: 100%; height: 100px; object-fit: cover; display: block; }
.pv-pick-name { display: block; padding: 4px 6px; font-size: 11px; color: var(--aimf-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
