<script setup>
// 成果展示: 全部产出作品墙(审核中/待发布/已发布/已打回), 本地元数据直出
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, Refresh, VideoPlay, Download, Share } from '@element-plus/icons-vue'
import { api, mediaUrl, fmtTime, pipelineName } from '../api'
import InputList from '../components/InputList.vue'

const router = useRouter()
const items = ref([])
const loading = ref(false)
const stateFilter = ref('all')
const pipelineFilter = ref('all')
const keyword = ref('')
const sortDesc = ref(true)
const detail = ref(null)
const durs = reactive({})

const STATES = [
  { key: 'all', label: '全部' },
  { key: 'review', label: '审核中' },
  { key: 'approved', label: '待发布' },
  { key: 'published', label: '已发布' },
  { key: 'failed', label: '已打回' },
]
const STATE_TAG = {
  review: { type: 'warning', label: '审核中' },
  approved: { type: 'success', label: '待发布' },
  published: { type: 'primary', label: '已发布' },
  failed: { type: 'danger', label: '已打回' },
}

const counts = computed(() => {
  const c = { all: items.value.length }
  for (const s of STATES.slice(1)) c[s.key] = 0
  for (const it of items.value) if (c[it.state] != null) c[it.state]++
  return c
})

const pipelines = computed(() => {
  const m = new Map()
  for (const it of items.value) {
    const k = it.pipeline || 'graph'
    m.set(k, (m.get(k) || 0) + 1)
  }
  return [...m.entries()].map(([key, n]) => ({ key, label: pipelineName(key), n }))
})

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const arr = items.value.filter(it => {
    if (stateFilter.value !== 'all' && it.state !== stateFilter.value) return false
    if (pipelineFilter.value !== 'all' && (it.pipeline || 'graph') !== pipelineFilter.value) return false
    if (kw) {
      const hay = [it.title, it.id, it.desc, ...(it.tags || [])].join(' ').toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
  arr.sort((a, b) => (a.created_at || 0) - (b.created_at || 0))
  return sortDesc.value ? arr.reverse() : arr
})

async function load() {
  loading.value = true
  try {
    try {
      items.value = await api.get('/api/outputs/all')
    } catch {
      // 旧后端没有 all 端点时, 前端合并四类产出
      const states = ['review', 'approved', 'published', 'failed']
      const groups = await Promise.all(states.map(s => api.get('/api/outputs/' + s)))
      items.value = groups.flatMap((arr, i) => arr.map(it => ({ ...it, state: states[i] })))
    }
  } catch (e) { ElMessage.error('加载失败: ' + e.message) }
  finally { loading.value = false }
}

function onMeta(e, it) {
  const d = e.target.duration
  if (d && Number.isFinite(d)) durs[it.id] = d
  try { e.target.currentTime = 0.6 } catch { /* 元数据未就绪 */ }
}
function hoverPlay(e) {
  const v = e.currentTarget.querySelector('video')
  if (v) v.play().catch(() => {})
}
function hoverPause(e) {
  const v = e.currentTarget.querySelector('video')
  if (v) {
    v.pause()
    try { v.currentTime = 0.6 } catch { /* 忽略 */ }
  }
}
const fmtDur = (s) => !s ? '' : (s >= 60
  ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`
  : `${s.toFixed(1)}s`)

function openDetail(it) {
  document.querySelectorAll('.wall-thumb video').forEach(v => v.pause())
  detail.value = it
}
function download(it) {
  const a = document.createElement('a')
  a.href = mediaUrl(it.id)
  a.download = it.file || it.id
  document.body.appendChild(a)
  a.click()
  a.remove()
}
function goJob(it) {
  detail.value = null
  router.push({ name: 'canvas', query: { job: it.job } })
}

onMounted(load)
</script>

<template>
  <div class="page page-wide">
    <div class="page-head">
      <h2>成果展示</h2>
      <span class="sub">全部产出作品墙 · 审核中 / 待发布 / 已发布 / 已打回</span>
      <div class="sp" />
      <span class="dim" style="font-size:12.5px">共 {{ filtered.length }} 件</span>
    </div>

    <div class="aimf-card gallery-filter">
      <div class="state-chips">
        <button v-for="s in STATES" :key="s.key" :class="{ on: stateFilter === s.key }"
                @click="stateFilter = s.key">
          {{ s.label }}<span class="n">{{ counts[s.key] }}</span>
        </button>
      </div>
      <div class="filter-right">
        <el-select v-model="pipelineFilter" size="small" style="width:150px">
          <el-option value="all" label="全部类型" />
          <el-option v-for="p in pipelines" :key="p.key" :value="p.key"
                     :label="`${p.label} (${p.n})`" />
        </el-select>
        <el-input v-model="keyword" size="small" placeholder="搜索标题 / 标签 / 描述"
                  :prefix-icon="Search" clearable style="width:220px" />
        <el-button size="small" @click="sortDesc = !sortDesc">
          {{ sortDesc ? '最新在前' : '最早在前' }}
        </el-button>
        <el-button size="small" :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div v-loading="loading" class="wall" element-loading-background="transparent">
      <div v-for="it in filtered" :key="it.state + ':' + it.id" class="wall-card"
           @click="openDetail(it)" @mouseenter="hoverPlay" @mouseleave="hoverPause">
        <div class="wall-thumb">
          <video v-if="it.is_video" :src="mediaUrl(it.id)" muted loop playsinline
                 preload="metadata" @loadedmetadata="e => onMeta(e, it)" />
          <img v-else :src="mediaUrl(it.id)" />
          <span class="st-badge" :class="'st-' + it.state">
            {{ (STATE_TAG[it.state] || {}).label || it.state }}
          </span>
          <span class="pipe-badge">{{ pipelineName(it.pipeline) }}</span>
          <span v-if="durs[it.id]" class="dur">{{ fmtDur(durs[it.id]) }}</span>
          <span v-if="it.is_video" class="play-hint"><el-icon><VideoPlay /></el-icon></span>
        </div>
        <div class="wall-body">
          <div class="wall-title" :title="it.title || it.id">{{ it.title || it.id }}</div>
          <div class="wall-meta">
            <span>{{ fmtTime(it.created_at) }}</span>
            <template v-if="it.tags && it.tags.length">
              <span>·</span>
              <span class="wall-tags">{{ it.tags.slice(0, 2).join(' / ') }}</span>
            </template>
          </div>
        </div>
      </div>
    </div>

    <el-empty v-if="!loading && !filtered.length"
              :description="items.length ? '当前筛选下没有作品' : '还没有产出 — 到工作台或带货视频页生成第一条'"
              :image-size="70" />

    <el-dialog :model-value="!!detail" width="960px" class="detail-dialog"
               :title="detail?.title || detail?.id || '作品详情'" @close="detail = null">
      <div v-if="detail" class="detail">
        <div class="detail-media">
          <video v-if="detail.is_video" :src="mediaUrl(detail.id)" controls autoplay loop
                 class="detail-video" />
          <img v-else :src="mediaUrl(detail.id)" class="detail-video" style="object-fit:contain" />
        </div>
        <div class="detail-side">
          <div class="detail-tags">
            <el-tag :type="(STATE_TAG[detail.state] || {}).type || 'info'" effect="dark" size="small">
              {{ (STATE_TAG[detail.state] || {}).label || detail.state }}
            </el-tag>
            <el-tag effect="plain" size="small">{{ pipelineName(detail.pipeline) }}</el-tag>
            <span class="dim" style="font-size:12px">{{ fmtTime(detail.created_at) }}</span>
          </div>
          <div v-if="detail.desc" class="detail-desc">{{ detail.desc }}</div>
          <div v-if="detail.tags && detail.tags.length" class="tag-list">
            <el-tag v-for="t in detail.tags" :key="t" size="small" effect="plain" type="info">{{ t }}</el-tag>
          </div>
          <div class="detail-path mono">
            {{ detail.file }}
            <template v-if="detail.job">
              <br>任务 {{ detail.job }}
            </template>
          </div>
          <div class="detail-actions">
            <el-button type="primary" size="small" :icon="Download"
                       @click="download(detail)">下载成片</el-button>
            <el-button v-if="detail.job" size="small" :icon="Share"
                       @click="goJob(detail)">查看执行图</el-button>
          </div>
          <div class="detail-inputs">
            <div class="cap">输入素材</div>
            <InputList :items="detail.inputs || []" />
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.gallery-filter {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  padding: 12px 16px; margin-bottom: 16px;
}
.state-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.state-chips button {
  appearance: none; border: 1px solid var(--aimf-line); background: transparent;
  color: var(--aimf-dim); padding: 5px 12px; border-radius: 999px; cursor: pointer;
  font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px;
  transition: all .15s;
}
.state-chips button:hover { color: var(--aimf-fg); border-color: #3a4157; }
.state-chips button.on {
  color: #fff; border-color: transparent;
  background: linear-gradient(135deg, rgba(99,102,241,.9), rgba(139,92,246,.85));
  box-shadow: 0 2px 12px rgba(99,102,241,.3);
}
.state-chips .n {
  font-size: 11px; line-height: 16px; padding: 0 6px; border-radius: 999px;
  background: rgba(255,255,255,.08);
}
.state-chips button.on .n { background: rgba(255,255,255,.2); }
.filter-right {
  margin-left: auto; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}

.wall {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px; min-height: 120px;
}
.wall-card {
  border: 1px solid var(--aimf-line); border-radius: 14px; overflow: hidden;
  background: linear-gradient(180deg, var(--aimf-panel), #0f1219); cursor: pointer;
  transition: transform .18s, border-color .18s, box-shadow .18s;
}
.wall-card:hover {
  transform: translateY(-3px); border-color: rgba(99,102,241,.55);
  box-shadow: 0 10px 30px rgba(0,0,0,.4);
}
.wall-thumb { position: relative; aspect-ratio: 9 / 16; background: #05070b; overflow: hidden; }
.wall-thumb video, .wall-thumb img {
  width: 100%; height: 100%; object-fit: cover; display: block;
}
.wall-thumb::after {
  content: ''; position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(180deg, rgba(5,7,11,.38) 0%, transparent 26%,
              transparent 64%, rgba(5,7,11,.5) 100%);
}
.st-badge {
  position: absolute; top: 8px; left: 8px; z-index: 2;
  font-size: 10.5px; font-weight: 600; padding: 2px 8px; border-radius: 999px;
  backdrop-filter: blur(4px);
}
.st-review { background: rgba(251,191,36,.92); color: #3b2a00; }
.st-approved { background: rgba(52,211,153,.92); color: #00281c; }
.st-published { background: rgba(99,102,241,.94); color: #fff; }
.st-failed { background: rgba(248,113,113,.92); color: #3a0000; }
.pipe-badge {
  position: absolute; top: 8px; right: 8px; z-index: 2;
  font-size: 10.5px; padding: 2px 8px; border-radius: 999px;
  color: #dfe3f3; background: rgba(10,13,20,.66);
  border: 1px solid rgba(255,255,255,.14); backdrop-filter: blur(4px);
}
.dur {
  position: absolute; bottom: 8px; right: 8px; z-index: 2;
  font-size: 10.5px; padding: 1px 7px; border-radius: 6px;
  color: #eef0f6; background: rgba(5,7,11,.72);
}
.play-hint {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); z-index: 2;
  width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center;
  background: rgba(8,10,16,.55); backdrop-filter: blur(6px); color: #fff; font-size: 22px;
  transition: opacity .18s;
}
.wall-card:hover .play-hint { opacity: 0; }
.wall-body { padding: 10px 12px 12px; }
.wall-title {
  font-size: 13px; font-weight: 600; line-height: 1.4; min-height: 36px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.wall-meta {
  margin-top: 6px; font-size: 11px; color: var(--aimf-dim);
  display: flex; gap: 5px; white-space: nowrap; overflow: hidden;
}
.wall-tags { overflow: hidden; text-overflow: ellipsis; }

.detail { display: flex; gap: 20px; }
.detail-media { width: 340px; flex-shrink: 0; }
.detail-video {
  width: 100%; max-height: 70vh; border-radius: 12px; background: #000; display: block;
}
.detail-side { flex: 1; min-width: 0; }
.detail-tags { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
.detail-desc {
  font-size: 13px; color: #c9cede; white-space: pre-wrap; margin: 12px 0;
  max-height: 140px; overflow: auto;
}
.detail-path {
  font-size: 11.5px; color: var(--aimf-dim); word-break: break-all; margin: 10px 0;
}
.detail-actions { display: flex; gap: 8px; margin: 14px 0; }
.detail-inputs {
  border-top: 1px solid var(--aimf-line); padding-top: 12px; margin-top: 6px;
  max-height: 300px; overflow-y: auto; padding-right: 6px;
}
.detail-inputs .cap {
  font-size: 11.5px; color: var(--aimf-dim); letter-spacing: .5px; margin-bottom: 6px;
}
.detail-inputs :deep(.in-thumb) { height: 96px; max-height: 96px; }
@media (max-width: 760px) {
  .detail { flex-direction: column; }
  .detail-media { width: 100%; }
}
</style>
