<script setup>
// 固定参考视频池: 人工维护的对标/爆款参考集合。
// 本页只做池维护(添加/移除); 参考视频只提供结构参考, 不进入生成请求。
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Delete, FolderOpened, Link, Plus, Refresh, Search, UploadFilled, VideoPlay,
} from '@element-plus/icons-vue'
import { api, assetUrl, fmtTime } from '../api'
import { store, refreshMeta } from '../store'
import { useFileDrop } from '../composables/useFileDrop'

const items = ref([])
const loading = ref(false)
const adding = ref(false)
const keyword = ref('')
const tagFilter = ref('')
const detail = ref(null)
const fileInput = ref(null)

const linkDlg = ref(false)
const linkForm = ref({ url: '', title: '', tags: '', note: '' })

const pickDlg = ref(false)
const picked = ref([])

const { dragging, dropProps } = useFileDrop({
  accept: ['video/*', '.mp4', '.mov', '.webm', '.mkv', '.m4v'],
  onFiles: uploadFiles,
})

const poolPaths = computed(() => new Set(items.value.map(it => it.path)))
const sourceOptions = computed(() =>
  (store.assets.source || []).filter(p => !poolPaths.value.has(p)))
const tags = computed(() => {
  const s = new Set()
  for (const it of items.value) for (const t of (it.tags || [])) s.add(t)
  return [...s]
})
const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return items.value.filter(it => {
    if (tagFilter.value && !(it.tags || []).includes(tagFilter.value)) return false
    if (!kw) return true
    const hay = [it.title, it.note, it.path, ...(it.tags || [])].join(' ').toLowerCase()
    return hay.includes(kw)
  })
})

async function load() {
  loading.value = true
  try {
    items.value = await api.get('/api/reference-pool')
  } catch (e) {
    ElMessage.error('加载失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

function triggerUpload() { fileInput.value?.click() }

function onFiles(ev) {
  const files = [...(ev.target.files || [])]
  ev.target.value = ''
  return uploadFiles(files)
}

async function uploadFiles(files) {
  if (!files?.length) return
  adding.value = true
  let ok = 0
  try {
    for (const f of files) {
      const r = await api.upload(f, 'source')
      await api.post('/api/reference-pool', {
        path: r.path,
        title: f.name.replace(/\.[^.]+$/, ''),
      })
      ok++
    }
    ElMessage.success(`已加入参考池 ${ok} 条`)
    await load()
  } catch (e) {
    ElMessage.error('添加失败: ' + e.message)
  } finally {
    adding.value = false
  }
}

function splitTags(s) {
  return (s || '').split(/[,，、;；\s]+/).map(x => x.trim()).filter(Boolean)
}

async function addLink() {
  const f = linkForm.value
  if (!f.url.trim()) return ElMessage.warning('请填写视频链接')
  adding.value = true
  try {
    const r = await api.post('/api/reference-pool', {
      url: f.url.trim(),
      title: f.title.trim() || undefined,
      tags: splitTags(f.tags),
      note: f.note.trim(),
      source_url: f.url.trim(),
    })
    ElMessage.success(`已加入参考池: ${r.title || '未命名'}`)
    linkDlg.value = false
    linkForm.value = { url: '', title: '', tags: '', note: '' }
    await load()
  } catch (e) {
    ElMessage.error('添加失败: ' + e.message)
  } finally {
    adding.value = false
  }
}

async function openPick() {
  await refreshMeta(true).catch(() => {})
  picked.value = []
  pickDlg.value = true
}

function togglePick(p) {
  const i = picked.value.indexOf(p)
  if (i >= 0) picked.value.splice(i, 1)
  else picked.value.push(p)
}

async function addPicked() {
  if (!picked.value.length) return
  adding.value = true
  try {
    for (const p of picked.value) {
      await api.post('/api/reference-pool', {
        path: p,
        title: fileName(p).replace(/\.[^.]+$/, ''),
      })
    }
    ElMessage.success(`已加入参考池 ${picked.value.length} 条`)
    pickDlg.value = false
    await load()
  } catch (e) {
    ElMessage.error('添加失败: ' + e.message)
  } finally {
    adding.value = false
  }
}

async function remove(it) {
  try {
    await ElMessageBox.confirm(
      `从参考池移除「${it.title || fileName(it.path)}」？\n只移除记录，原视频文件保留。`,
      '移除参考', { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' })
  } catch { return }
  try {
    await api.del('/api/reference-pool/' + it.id)
    if (detail.value?.id === it.id) detail.value = null
    ElMessage.success('已移除')
    await load()
  } catch (e) {
    ElMessage.error('移除失败: ' + e.message)
  }
}

const fileName = (p) => (p || '').split('/').pop() || ''
const fmtDur = (s) => !s ? '' : `${Number(s).toFixed(1)}s`

function onMeta(e, it) {
  const d = e.target.duration
  if (d && Number.isFinite(d)) it.duration = d
  try { e.target.currentTime = 0.4 } catch { /* 元数据未就绪 */ }
}
function hoverPlay(e) {
  const v = e.currentTarget.querySelector('video')
  if (v) v.play().catch(() => {})
}
function hoverPause(e) {
  const v = e.currentTarget.querySelector('video')
  if (v) {
    v.pause()
    try { v.currentTime = 0.4 } catch { /* 忽略 */ }
  }
}

onMounted(async () => {
  await refreshMeta().catch(() => {})
  load()
})
</script>

<template>
  <div class="page page-wide" v-on="dropProps">
    <div v-if="dragging" class="drop-overlay"><div>松开以上传参考视频</div></div>
    <div class="page-head">
      <h2>参考视频池</h2>
      <span class="sub">固定参考集合 · 用于结构分析与爆款追踪，只借结构，不进入生成</span>
      <div class="sp" />
      <span class="dim" style="font-size:12.5px">共 {{ filtered.length }} 条</span>
      <input ref="fileInput" type="file" accept="video/*" multiple hidden @change="onFiles" />
      <el-button type="primary" size="small" :icon="UploadFilled" :loading="adding"
                 @click="triggerUpload">上传视频</el-button>
      <el-button size="small" :icon="FolderOpened" :loading="adding"
                 @click="openPick">从素材库添加</el-button>
      <el-button size="small" :icon="Link" @click="linkDlg = true">添加链接</el-button>
    </div>

    <div class="aimf-card ref-filter">
      <div class="tag-chips">
        <button :class="{ on: !tagFilter }" @click="tagFilter = ''">全部</button>
        <button v-for="t in tags" :key="t" :class="{ on: tagFilter === t }"
                @click="tagFilter = tagFilter === t ? '' : t">{{ t }}</button>
      </div>
      <div class="filter-right">
        <el-input v-model="keyword" size="small" placeholder="搜索标题 / 备注 / 标签"
                  :prefix-icon="Search" clearable style="width:230px" />
        <el-button size="small" :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="ref-drop" :class="{ on: dragging }" @click="triggerUpload">
      <el-icon><UploadFilled /></el-icon>
      <span>拖入视频到页面任意位置，或点击上传</span>
    </div>

    <div v-loading="loading" class="ref-grid" element-loading-background="transparent">
      <div v-for="it in filtered" :key="it.id" class="ref-card" @click="detail = it">
        <div class="ref-thumb" @mouseenter="hoverPlay" @mouseleave="hoverPause">
          <video v-if="it.exists" :src="assetUrl(it.path)" muted loop playsinline
                 preload="metadata" @loadedmetadata="e => onMeta(e, it)" />
          <div v-else class="ref-missing">原文件已丢失</div>
          <span class="ref-badge">参考</span>
          <span v-if="it.duration" class="ref-dur">{{ fmtDur(it.duration) }}</span>
          <span v-if="it.exists" class="play-hint"><el-icon><VideoPlay /></el-icon></span>
          <button class="ref-del" title="从池中移除" @click.stop="remove(it)">
            <el-icon><Delete /></el-icon>
          </button>
        </div>
        <div class="ref-body">
          <div class="ref-title" :title="it.title || it.filename">{{ it.title || it.filename }}</div>
          <div v-if="it.note" class="ref-note">{{ it.note }}</div>
          <div v-if="it.tags && it.tags.length" class="ref-tags">
            <el-tag v-for="t in it.tags" :key="t" size="small" effect="plain" type="info">{{ t }}</el-tag>
          </div>
          <div class="ref-meta">
            <span>{{ fmtTime(it.created_at) }}</span>
            <span v-if="it.source_url">· 链接导入</span>
          </div>
        </div>
      </div>
    </div>

    <el-empty v-if="!loading && !filtered.length"
              :description="items.length ? '当前筛选下没有参考视频' : '参考池为空 — 上传视频、从素材库选择或粘贴链接'"
              :image-size="70" />

    <!-- 详情 -->
    <el-dialog :model-value="!!detail" width="880px" :title="detail?.title || '参考视频'"
               @close="detail = null">
      <div v-if="detail" class="ref-detail">
        <div class="ref-detail-media">
          <video v-if="detail.exists" :src="assetUrl(detail.path)" controls autoplay loop
                 class="ref-detail-video" />
          <div v-else class="ref-missing ref-detail-video">原文件已丢失</div>
        </div>
        <div class="ref-detail-side">
          <div class="ref-detail-tags">
            <el-tag effect="dark" size="small">参考视频</el-tag>
            <el-tag v-if="detail.duration" effect="plain" size="small">
              {{ fmtDur(detail.duration) }}
            </el-tag>
            <span class="dim" style="font-size:12px">{{ fmtTime(detail.created_at) }}</span>
          </div>
          <div v-if="detail.note" class="ref-detail-note">{{ detail.note }}</div>
          <div v-if="detail.tags && detail.tags.length" class="ref-tags">
            <el-tag v-for="t in detail.tags" :key="t" size="small" effect="plain" type="info">{{ t }}</el-tag>
          </div>
          <div class="ref-detail-path mono">
            {{ detail.path }}
            <template v-if="detail.source_url"><br>来源：{{ detail.source_url }}</template>
          </div>
          <div class="ref-detail-actions">
            <el-button type="danger" plain size="small" :icon="Delete" @click="remove(detail)">
              从参考池移除
            </el-button>
          </div>
          <div class="ref-detail-tip">
            后续分析只会提取镜头结构、节奏和卖点表达，不会把参考视频作为生成输入。
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 添加链接 -->
    <el-dialog v-model="linkDlg" width="520px" title="添加视频链接">
      <el-form label-width="70px" size="default">
        <el-form-item label="链接">
          <el-input v-model="linkForm.url" placeholder="抖音 / 小红书 / TikTok 视频直链" clearable />
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="linkForm.title" placeholder="留空则使用文件名" clearable />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="linkForm.tags" placeholder="逗号分隔，如：口播, 痛点, 服装" clearable />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="linkForm.note" type="textarea" :rows="2"
                    placeholder="为什么值得参考 / 想借鉴什么" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="linkDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="adding" @click="addLink">下载并加入</el-button>
      </template>
    </el-dialog>

    <!-- 从素材库添加 -->
    <el-dialog v-model="pickDlg" width="680px" title="从素材库添加参考视频">
      <div v-if="!sourceOptions.length" class="dim" style="padding:18px 0">
        素材库中没有可添加的视频。请先到「素材库 → 对标视频」上传。
      </div>
      <div v-else class="src-list">
        <div v-for="p in sourceOptions" :key="p"
             :class="['src-item', { on: picked.includes(p) }]" @click="togglePick(p)">
          <video :src="assetUrl(p)" muted preload="metadata" />
          <div class="src-name" :title="fileName(p)">{{ fileName(p) }}</div>
          <span class="src-check">{{ picked.includes(p) ? '✓' : '' }}</span>
        </div>
      </div>
      <template #footer>
        <span class="dim" style="margin-right:auto;font-size:12px">已选 {{ picked.length }} 条</span>
        <el-button size="small" @click="pickDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="adding"
                   :disabled="!picked.length" @click="addPicked">添加所选</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ref-filter {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  padding: 12px 16px; margin-bottom: 16px;
}
.tag-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.tag-chips button {
  appearance: none; border: 1px solid var(--aimf-line); background: transparent;
  color: var(--aimf-dim); padding: 4px 12px; border-radius: 999px; cursor: pointer;
  font-size: 12.5px; transition: all .15s;
}
.tag-chips button:hover { color: var(--aimf-fg); border-color: #3a4157; }
.tag-chips button.on {
  color: #fff; border-color: transparent;
  background: linear-gradient(135deg, rgba(34,211,238,.75), rgba(99,102,241,.85));
  box-shadow: 0 2px 12px rgba(34,211,238,.22);
}
.filter-right { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.ref-drop {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  margin: 0 0 16px; padding: 12px; border-radius: 12px; cursor: pointer;
  border: 1px dashed var(--aimf-line); color: var(--aimf-dim); font-size: 12.5px;
  background: rgba(255, 255, 255, .015); transition: all .15s;
}
.ref-drop:hover, .ref-drop.on {
  color: #bdf5ff; border-color: rgba(34, 211, 238, .6);
  background: rgba(34, 211, 238, .06);
}

.ref-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 16px; min-height: 120px;
}
.ref-card {
  border: 1px solid var(--aimf-line); border-radius: 14px; overflow: hidden;
  background: linear-gradient(180deg, var(--aimf-panel), #0f1219); cursor: pointer;
  transition: transform .18s, border-color .18s, box-shadow .18s;
}
.ref-card:hover {
  transform: translateY(-3px); border-color: rgba(34,211,238,.5);
  box-shadow: 0 10px 30px rgba(0,0,0,.4);
}
.ref-thumb { position: relative; aspect-ratio: 9 / 16; background: #05070b; overflow: hidden; }
.ref-thumb video { width: 100%; height: 100%; object-fit: cover; display: block; }
.ref-thumb::after {
  content: ''; position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(180deg, rgba(5,7,11,.4) 0%, transparent 24%,
              transparent 66%, rgba(5,7,11,.55) 100%);
}
.ref-missing {
  width: 100%; height: 100%; display: grid; place-items: center;
  color: var(--aimf-dim); font-size: 12px;
}
.ref-badge {
  position: absolute; top: 8px; left: 8px; z-index: 2;
  font-size: 10.5px; font-weight: 600; padding: 2px 8px; border-radius: 999px;
  color: #04262b; background: rgba(34,211,238,.9); backdrop-filter: blur(4px);
}
.ref-dur {
  position: absolute; bottom: 8px; right: 8px; z-index: 2;
  font-size: 10.5px; padding: 1px 7px; border-radius: 6px;
  color: #eef0f6; background: rgba(5,7,11,.72);
}
.ref-del {
  position: absolute; top: 7px; right: 7px; z-index: 3;
  width: 26px; height: 26px; border-radius: 8px; border: 1px solid rgba(255,255,255,.14);
  display: grid; place-items: center; cursor: pointer;
  color: #fca5a5; background: rgba(8,10,16,.62); backdrop-filter: blur(6px);
  opacity: 0; transition: opacity .15s, background .15s;
}
.ref-card:hover .ref-del { opacity: 1; }
.ref-del:hover { background: rgba(127,29,29,.8); color: #fff; }
.play-hint {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); z-index: 2;
  width: 42px; height: 42px; border-radius: 50%; display: grid; place-items: center;
  background: rgba(8,10,16,.55); backdrop-filter: blur(6px); color: #fff; font-size: 20px;
  transition: opacity .18s;
}
.ref-card:hover .play-hint { opacity: 0; }
.ref-body { padding: 10px 12px 12px; }
.ref-title {
  font-size: 13px; font-weight: 600; line-height: 1.4; min-height: 36px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.ref-note {
  margin-top: 4px; font-size: 11.5px; color: var(--aimf-dim);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ref-tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 7px; }
.ref-meta {
  margin-top: 7px; font-size: 11px; color: var(--aimf-dim);
  display: flex; gap: 5px; white-space: nowrap; overflow: hidden;
}

.ref-detail { display: flex; gap: 20px; }
.ref-detail-media { width: 300px; flex-shrink: 0; }
.ref-detail-video {
  width: 100%; max-height: 70vh; border-radius: 12px; background: #000; display: block;
}
.ref-detail-side { flex: 1; min-width: 0; }
.ref-detail-tags { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ref-detail-note {
  margin: 12px 0; font-size: 13px; color: #c9cede; white-space: pre-wrap;
  max-height: 150px; overflow: auto;
}
.ref-detail-path {
  margin: 14px 0; font-size: 11.5px; color: var(--aimf-dim); word-break: break-all;
}
.ref-detail-actions { margin: 14px 0; }
.ref-detail-tip {
  border-top: 1px solid var(--aimf-line); padding-top: 12px; margin-top: 6px;
  font-size: 12px; color: var(--aimf-dim); line-height: 1.7;
}

.src-list {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px; max-height: 52vh; overflow-y: auto; padding-right: 4px;
}
.src-item {
  position: relative; border: 1px solid var(--aimf-line); border-radius: 10px;
  overflow: hidden; cursor: pointer; background: #0d1119; transition: all .15s;
}
.src-item.on { border-color: rgba(34,211,238,.8); box-shadow: 0 0 0 2px rgba(34,211,238,.2); }
.src-item video { width: 100%; aspect-ratio: 9/16; object-fit: cover; display: block; background: #000; }
.src-name {
  padding: 6px 8px; font-size: 11px; color: var(--aimf-dim);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.src-check {
  position: absolute; top: 6px; right: 6px; width: 20px; height: 20px;
  border-radius: 50%; display: grid; place-items: center; font-size: 12px; font-weight: 700;
  color: #04262b; background: rgba(34,211,238,.92);
}
@media (max-width: 760px) {
  .ref-detail { flex-direction: column; }
  .ref-detail-media { width: 100%; }
}
</style>
