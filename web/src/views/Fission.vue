<script setup>
// 裂变素材 v2: 商品/人物/Profile -> 全池无感对标 -> 契约 -> 生成 -> 审核
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { MagicStick, Refresh, Download } from '@element-plus/icons-vue'
import { api, assetUrl, fileUrl, fmtTime } from '../api'

const route = useRoute()
const router = useRouter()
const profiles = ref([])
const assets = ref({ person: [], product: [] })
const runs = ref([])
const detail = ref(null)
const busy = ref(false)
const jobId = ref('')
const job = ref(null)
const textDlg = ref(false)
const textTitle = ref('')
const textBody = ref('')
const productInput = ref(null)
const personInput = ref(null)
let timer = null

const form = ref({
  engine: 'p0.2',
  profile_id: 'bra-milk-lace',
  product_image: '',
  person: '',
  n: 5,
  seed: null,
  prepare_materials: true,
  refresh_materials: false,
  skip_generate: false,
})

const selectedProfile = computed(() =>
  profiles.value.find(p => p.profile_id === form.value.profile_id))

const uniq = (xs) => [...new Set(xs.filter(Boolean))]
const productOptions = computed(() => uniq([
  ...(assets.value.product || []),
  ...profiles.value.map(p => p.image),
]))
const personOptions = computed(() => uniq([
  ...(assets.value.person || []),
  ...profiles.value.map(p => p.person),
]))

const STAGE_LABELS = {
  pool: '参考池', brief: '商品 Brief', guidance: '全池指导',
  variants: '变体规划', contracts: '契约', generation: '生成',
  evaluation: '评估', materials: '素材解读', anchor: '商品锚点',
  style_atlas: '风格图谱', planner: '风格采样', worlds: '创意世界',
  audit: '审计',
}
const LEGACY_ORDER = [
  'pool', 'brief', 'guidance', 'variants', 'contracts', 'generation',
  'evaluation',
]
const P0_ORDER = [
  'materials', 'anchor', 'style_atlas', 'planner', 'worlds',
  'contracts', 'audit', 'generation',
]
const isP0Engine = (engine) => String(engine || '').startsWith('p0')
const stageDefs = computed(() => {
  const m = detail.value?.manifest || {}
  const stages = m.stages || {}
  const order = isP0Engine(m.engine) ? P0_ORDER : LEGACY_ORDER
  return order
    .filter(k => stages[k] || k === 'contracts' || k === 'generation')
    .map(k => [k, STAGE_LABELS[k] || k])
})
const stageStatus = (key) => {
  const st = detail.value?.manifest?.stages?.[key]
  if (st?.status) return st.status
  const vs = detail.value?.variants || []
  if (key === 'contracts' && vs.length) return 'done'
  if (key === 'generation' && vs.length && vs.every(v => v.video)) return 'done'
  return 'pending'
}
const stageType = (s) => s === 'done' ? 'success'
  : s === 'failed' ? 'danger'
    : s === 'running' || s === 'partial' ? 'warning' : 'info'
const runStatusType = (s) => s === 'done' ? 'success'
  : s === 'failed' || s === 'error' ? 'danger'
    : s === 'partial' || s === 'contracts_done' || s === 'audit_failed'
      ? 'warning' : 'info'
const canResume = computed(() => {
  const s = detail.value?.manifest?.status
  return ['contracts_done', 'partial', 'failed', 'error'].includes(s)
    && !busy.value
})
const resumeLabel = computed(() => {
  const s = detail.value?.manifest?.status
  if (s === 'contracts_done') return '继续生成'
  if (s === 'partial' || s === 'failed' || s === 'error') return '重试未完成'
  return '续跑'
})

function applyProfile() {
  const p = selectedProfile.value
  if (!p) return
  form.value.product_image = p.image || form.value.product_image
  form.value.person = p.person || form.value.person
}

async function loadAll() {
  try {
    const [ps, as, rs] = await Promise.all([
      api.get('/api/fission/profiles'),
      api.get('/api/assets'),
      api.get('/api/fission/runs'),
    ])
    profiles.value = Array.isArray(ps) ? ps : []
    assets.value = as || { person: [], product: [] }
    runs.value = (rs && rs.items) || []
    if (!form.value.profile_id && profiles.value.length) {
      form.value.profile_id = profiles.value[0].profile_id
    }
    if (!form.value.product_image) applyProfile()
    const qRun = String(route.query.run || '')
    if (qRun && runs.value.some(r => r.run_id === qRun)) {
      await loadRun(qRun)
    } else if (runs.value.length && !detail.value) {
      await loadRun(runs.value[0].run_id)
    }
  } catch (e) {
    ElMessage.error('加载失败: ' + e.message)
  }
}

async function loadRun(runId) {
  if (!runId) return
  try {
    detail.value = await api.get('/api/fission/runs/' + runId)
  } catch (e) {
    ElMessage.error('读取 run 失败: ' + e.message)
  }
}

function stopTimer() {
  if (timer) { clearInterval(timer); timer = null }
}

async function submit() {
  if (!form.value.product_image) return ElMessage.warning('先选商品图')
  if (!form.value.person) return ElMessage.warning('先选人物图')
  busy.value = true
  stopTimer()
  detail.value = null
  try {
    const p0 = form.value.engine === 'p0.2'
    const payload = {
      profile_id: form.value.profile_id,
      product_image: form.value.product_image,
      person: form.value.person,
      n: Number(form.value.n),
      skip_generate: !!form.value.skip_generate,
    }
    if (p0) {
      payload.seed = form.value.seed === null || form.value.seed === ''
        ? null : Number(form.value.seed)
      payload.prepare_materials = !!form.value.prepare_materials
      payload.refresh_materials = !!form.value.refresh_materials
    }
    const r = await api.post(
      p0 ? '/api/jobs/fission-p0' : '/api/jobs/fission', payload)
    jobId.value = r.job
    job.value = { status: 'running', result: { phase: 'queued' } }
    ElMessage.success('裂变任务已提交')
    timer = setInterval(pollJob, 3000)
    pollJob()
  } catch (e) {
    ElMessage.error('提交失败: ' + e.message)
    busy.value = false
  }
}

async function pollJob() {
  if (!jobId.value) return
  try {
    const j = await api.get('/api/jobs/' + jobId.value)
    job.value = j
    if (j.status === 'running') {
      const rid = j.result?.run_id
      if (rid) {
        try {
          detail.value = await api.get('/api/fission/runs/' + rid)
        } catch { /* run 目录还没建立，下次轮询再试 */ }
      }
      return
    }
    stopTimer()
    busy.value = false
    if (j.status === 'done' || j.status === 'partial') {
      if (j.status === 'partial') ElMessage.warning('裂变部分完成，可继续生成')
      else ElMessage.success('裂变完成')
      await loadAll()
      const rd = j.result?.run_dir
      if (rd) {
        const rid = String(rd).split('/').filter(Boolean).pop()
        if (rid) await loadRun(rid)
      }
    } else {
      const rd = j.result?.run_dir
      if (rd) {
        const rid = String(rd).split('/').filter(Boolean).pop()
        if (rid) await loadRun(rid)
      }
      ElMessage.error('裂变失败: ' + (j.result?.error || j.status))
    }
  } catch { /* 网络抖动，下次再试 */ }
}

async function resume() {
  if (!detail.value?.run_id) return
  busy.value = true
  stopTimer()
  try {
    const r = await api.post(`/api/fission/runs/${detail.value.run_id}/resume`, {})
    jobId.value = r.job
    job.value = { status: 'running', result: { phase: 'resuming' } }
    ElMessage.success('已提交续跑')
    timer = setInterval(pollJob, 3000)
    pollJob()
  } catch (e) {
    ElMessage.error('续跑失败: ' + e.message)
    busy.value = false
  }
}

function pick(kind) {
  if (kind === 'product') productInput.value?.click()
  else personInput.value?.click()
}

async function onUpload(ev, kind) {
  const f = ev.target.files?.[0]
  if (!f) return
  try {
    const r = await api.upload(f, kind)
    if (kind === 'product') form.value.product_image = r.path
    else form.value.person = r.path
    await loadAll()
    ElMessage.success('已上传 ' + r.path)
  } catch (e) {
    ElMessage.error('上传失败: ' + e.message)
  } finally {
    ev.target.value = ''
  }
}

function openText(title, body) {
  textTitle.value = title
  textBody.value = body || ''
  textDlg.value = true
}

function showPrompt(v) {
  openText(`Prompt · #${v.index} ${v.name}`, v.prompt)
}

function showContract(v) {
  openText(`Contract · #${v.index} ${v.name}`,
    JSON.stringify(v.contract || {}, null, 2))
}

function showVoice(v) {
  openText(`口播 · #${v.index} ${v.name}`, v.voiceover || '（本变体无口播）')
}

function download(v) {
  if (!v.video) return
  const a = document.createElement('a')
  a.href = fileUrl(v.video)
  a.download = `variant_${String(v.index).padStart(2, '0')}.mp4`
  document.body.appendChild(a)
  a.click()
  a.remove()
}

onMounted(loadAll)
onUnmounted(stopTimer)
</script>

<template>
  <div class="page page-wide fission-page">
    <div class="page-head">
      <h2>裂变素材</h2>
      <span class="sub">商品图 + 人物图 → 系统自动使用视频池整体对标 → 契约 → 多条素材</span>
      <div class="sp" />
      <el-tag effect="plain">无需手选参考视频</el-tag>
      <el-button size="small" :icon="Refresh" @click="loadAll">刷新</el-button>
    </div>

    <div class="fission-grid">
      <!-- 左：输入 -->
      <div class="fission-left">
        <div class="aimf-card">
          <h3>① 商品</h3>
          <div class="row" style="margin-bottom:10px">
            <span>引擎</span>
            <el-select v-model="form.engine" size="small" style="flex:1">
              <el-option label="创意世界 P0.2（推荐）" value="p0.2" />
              <el-option label="旧车道（兼容）" value="legacy" />
            </el-select>
          </div>
          <el-select v-model="form.profile_id" filterable style="width:100%"
                     @change="applyProfile">
            <el-option v-for="p in profiles" :key="p.profile_id"
                       :value="p.profile_id"
                       :label="`${p.profile_id} · ${p.category || ''}`" />
          </el-select>
          <div v-if="selectedProfile" class="profile-meta">
            <el-tag size="small">{{ selectedProfile.category }}</el-tag>
            <el-tag size="small" type="info">{{ selectedProfile.default_archetype }}</el-tag>
            <span class="dim">{{ selectedProfile.identity }}</span>
          </div>
          <div v-if="selectedProfile" class="hint">
            商品事实/卖点/不可变特征来自该 Profile。商品图只替换为同款另一张照片；
            换商品请先新增 Profile（configs/products/*.json）。
          </div>
          <div class="preview-box">
            <img v-if="form.product_image" :src="assetUrl(form.product_image)" alt="product" />
          </div>
          <div class="row">
            <el-select v-model="form.product_image" filterable
                       placeholder="选择/上传商品图" style="flex:1">
              <el-option v-for="p in productOptions" :key="p" :value="p"
                         :label="p.split('/').pop()" />
            </el-select>
            <el-button size="small" @click="pick('product')">上传</el-button>
          </div>
          <input ref="productInput" type="file" accept="image/*"
                 style="display:none" @change="onUpload($event, 'product')" />
        </div>

        <div class="aimf-card">
          <h3>② 人物</h3>
          <div class="preview-box person">
            <img v-if="form.person" :src="assetUrl(form.person)" alt="person" />
          </div>
          <div class="row">
            <el-select v-model="form.person" filterable
                       placeholder="选择/上传人物图" style="flex:1">
              <el-option v-for="p in personOptions" :key="p" :value="p"
                         :label="p.split('/').pop()" />
            </el-select>
            <el-button size="small" @click="pick('person')">上传</el-button>
          </div>
          <input ref="personInput" type="file" accept="image/*"
                 style="display:none" @change="onUpload($event, 'person')" />
          <div class="hint">只复用人物身份；服装/场景由契约替换。请确认肖像授权。</div>
        </div>

        <div class="aimf-card">
          <h3>③ 产出</h3>
          <div class="row">
            <span>数量</span>
            <el-input-number v-model="form.n" :min="1" :max="10" size="small" />
            <span class="dim">条</span>
            <div class="sp" />
            <el-switch v-model="form.skip_generate" size="small"
                       active-text="只生成契约" />
          </div>
          <div v-if="form.engine === 'p0.2'" class="row" style="margin-top:8px">
            <el-switch v-model="form.prepare_materials" size="small"
                       active-text="素材解读" />
            <el-switch v-if="form.prepare_materials"
                       v-model="form.refresh_materials" size="small"
                       active-text="强制重读素材" />
          </div>
          <div v-if="form.engine === 'p0.2'" class="row" style="margin-top:8px">
            <span>随机种子</span>
            <el-input-number v-model="form.seed" :min="1" :max="999999999"
                             size="small" controls-position="right" />
            <span class="dim">可复现同批风格</span>
          </div>
          <el-button type="primary" size="large" style="width:100%;margin-top:12px"
                     :icon="MagicStick" :loading="busy" @click="submit">
            生成裂变素材
          </el-button>
          <div class="hint">
            系统会自动从视频池归纳开场/证明/信息密度/收尾，不需要选择对标视频。
          </div>
        </div>

        <div v-if="jobId" class="aimf-card">
          <h3>当前任务 <span class="dim">{{ job?.status || '运行中' }}</span></h3>
          <div class="mono dim">{{ jobId }}</div>
          <el-progress v-if="job?.status === 'running'" :percentage="60"
                       :indeterminate="true" :duration="2" />
          <div v-if="job?.result?.error" class="error-text">{{ job.result.error }}</div>
        </div>
      </div>

      <!-- 右：运行记录与结果 -->
      <div class="fission-right">
        <div class="aimf-card">
          <h3>运行记录 <span class="dim">{{ runs.length }} 次</span></h3>
          <div v-if="!runs.length" class="empty-text">还没有运行记录。</div>
          <div v-else class="run-list">
            <div v-for="r in runs" :key="r.run_id"
                 :class="['run-item', { on: detail?.run_id === r.run_id }]"
                 @click="loadRun(r.run_id)">
              <div class="run-head">
                <b>{{ r.run_id }}</b>
                <el-tag size="small" :type="runStatusType(r.status)">{{ r.status }}</el-tag>
              </div>
              <div class="dim">
                {{ fmtTime(r.created_at) }} · {{ r.engine || 'legacy' }}
                · 契约 {{ r.contracts ?? '-' }} · {{ r.videos || 0 }} 条
                · {{ r.profile_id }}
              </div>
            </div>
          </div>
        </div>

        <div v-if="detail" class="aimf-card">
          <h3>
            当前 run
            <span class="dim mono">{{ detail.run_id }}</span>
            <div class="sp" />
            <el-button v-if="canResume" size="small" :loading="busy" @click="resume">
              {{ resumeLabel }}
            </el-button>
          </h3>
          <div class="stage-row">
            <el-tag v-for="([key, label]) in stageDefs" :key="key"
                    :type="stageType(stageStatus(key))" size="small" effect="plain">
              {{ label }} · {{ stageStatus(key) }}
            </el-tag>
            <el-tag v-if="detail.diversity?.audit"
                    size="small" effect="dark"
                    :type="detail.diversity.audit.ok ? 'success' : 'warning'">
              多元车道 {{ detail.diversity.audit.unique_lanes }}/{{ detail.diversity.audit.variant_count }}
            </el-tag>
            <el-tag v-if="isP0Engine(detail.manifest?.engine) && detail.manifest?.audit"
                    size="small" effect="dark"
                    :type="detail.manifest.audit.ok ? 'success' : 'warning'">
              P0 审计 {{ detail.manifest.audit.ok ? '通过' : '待修' }}
              · 语义 {{ detail.manifest.audit.semantic_world_ok == null ? '-' : (detail.manifest.audit.semantic_world_ok ? '通过' : '待修') }}
              · 文案重复 {{ detail.manifest.audit.copy_duplicates ?? '-' }}
            </el-tag>
          </div>

          <div v-if="!detail.variants?.length" class="empty-text">
            还没有契约/视频。可以续跑，或检查任务错误。
          </div>
          <div v-else class="variant-grid">
            <div v-for="v in detail.variants" :key="v.index" class="variant-card">
              <video v-if="v.video" :src="fileUrl(v.video)" controls preload="metadata" />
              <div v-else class="no-video">未生成视频</div>
              <div class="variant-body">
                <div class="variant-title">#{{ v.index }} {{ v.name }}</div>
                <div v-if="v.creative_world?.title" class="variant-hypo">
                  创意世界：{{ v.creative_world.title }}
                </div>
                <div class="dim">参考 {{ v.primary_ref }} · {{ v.beats }} beat · {{ v.duration }}s</div>
                <div v-if="v.lane || v.archetype" class="tag-row">
                  <el-tag v-if="v.lane" size="small" type="warning" effect="plain">
                    {{ v.lane }}
                  </el-tag>
                  <el-tag v-if="v.person_visibility" size="small" effect="plain">
                    {{ v.person_visibility }}
                  </el-tag>
                  <el-tag v-if="v.presenter_mode" size="small" effect="plain">
                    {{ v.presenter_mode }}
                  </el-tag>
                  <el-tag v-if="v.archetype" size="small" effect="plain">
                    {{ v.archetype }}
                  </el-tag>
                </div>
                <div v-if="v.lane_summary" class="variant-hypo">{{ v.lane_summary }}</div>
                <div v-if="v.hypothesis" class="variant-hypo">{{ v.hypothesis }}</div>
                <div class="tag-row">
                  <el-tag size="small" :type="v.validation?.ok ? 'success' : 'danger'">
                    契约 {{ v.validation?.ok ? '通过' : '失败' }}
                  </el-tag>
                  <el-tag v-if="v.product_validation" size="small"
                          :type="v.product_validation.verdict === 'pass' ? 'success' : 'danger'">
                    商品 {{ v.product_validation.verdict || '-' }}
                  </el-tag>
                  <el-tag v-if="v.product_validation" size="small">
                    identity {{ v.product_validation.identity_match ?? '-' }}
                  </el-tag>
                  <el-tag v-if="v.product_validation" size="small">
                    color {{ v.product_validation.color_match ?? '-' }}
                  </el-tag>
                  <el-tag v-if="v.product_validation" size="small">
                    detail {{ v.product_validation.detail_match ?? '-' }}
                  </el-tag>
                </div>
                <div v-if="v.product_validation?.issues?.length" class="issues">
                  {{ v.product_validation.issues.join('；') }}
                </div>
                <div class="actions">
                  <el-button size="small" @click="showPrompt(v)">Prompt</el-button>
                  <el-button size="small" @click="showContract(v)">契约</el-button>
                  <el-button size="small" @click="showVoice(v)">口播</el-button>
                  <el-button size="small" :icon="Download" :disabled="!v.video"
                             @click="download(v)">下载</el-button>
                  <el-button size="small" type="primary" plain
                             @click="router.push({ name: 'review' })">去审核</el-button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="aimf-card empty-text">
          选择左侧商品/人物，或从上方运行记录里选一次结果。
        </div>
      </div>
    </div>

    <el-dialog v-model="textDlg" :title="textTitle" width="860px">
      <pre class="text-pre">{{ textBody }}</pre>
    </el-dialog>
  </div>
</template>

<style scoped>
.fission-page { max-width: 1500px; }
.fission-grid {
  display: grid;
  grid-template-columns: 400px 1fr;
  gap: 16px;
  align-items: start;
}
@media (max-width: 1100px) { .fission-grid { grid-template-columns: 1fr; } }
.fission-left, .fission-right { display: flex; flex-direction: column; gap: 14px; }
.profile-meta { display: flex; gap: 6px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
.preview-box {
  margin: 10px 0; height: 170px; border-radius: 10px; overflow: hidden;
  background: #f4f1ea; display: flex; align-items: center; justify-content: center;
}
.preview-box.person { height: 150px; }
.preview-box img { max-width: 100%; max-height: 100%; object-fit: contain; }
.row { display: flex; gap: 8px; align-items: center; }
.sp { flex: 1; }
.hint { margin-top: 8px; font-size: 12px; color: #8a8175; line-height: 1.5; }
.error-text { color: #c45656; font-size: 12.5px; margin-top: 8px; }
.empty-text { color: #8a8175; font-size: 13px; padding: 12px 0; }
.run-list { display: flex; flex-direction: column; gap: 8px; }
.run-item {
  border: 1px solid #eee7db; border-radius: 9px; padding: 9px 10px;
  cursor: pointer; transition: .15s;
}
.run-item:hover, .run-item.on { border-color: #c9a86a; background: #fbf7ef; }
.run-head { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.stage-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 14px; }
.variant-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.variant-card {
  border: 1px solid #eee7db; border-radius: 10px; overflow: hidden;
  background: #fff; display: flex; flex-direction: column;
}
.variant-card video, .no-video {
  width: 100%; aspect-ratio: 9/16; max-height: 360px; background: #f4f1ea;
  object-fit: contain; display: flex; align-items: center; justify-content: center;
  color: #8a8175; font-size: 12px;
}
.variant-body { padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.variant-title { font-size: 13px; font-weight: 600; line-height: 1.4; }
.variant-hypo { font-size: 12px; color: #6f675c; line-height: 1.45; }
.tag-row { display: flex; flex-wrap: wrap; gap: 4px; }
.issues { font-size: 11.5px; color: #b06a3b; line-height: 1.4; }
.actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.text-pre {
  max-height: 60vh; overflow: auto; white-space: pre-wrap; word-break: break-word;
  font-size: 12px; line-height: 1.5; background: #faf8f3; padding: 12px;
  border-radius: 8px;
}
</style>
