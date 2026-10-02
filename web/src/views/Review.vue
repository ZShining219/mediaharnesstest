<script setup>
// 审核队列: 「输入素材 → 产出」对照式呈现 -> 通过(填标题/定时) / 打回
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { api, mediaUrl, fmtTime } from '../api'
import InputList from '../components/InputList.vue'

const router = useRouter()
const tab = ref('review')
const lists = ref({ review: [], approved: [], published: [], failed: [] })
const busy = ref('')

const TABS = [
  { key: 'review', label: '待审核' },
  { key: 'approved', label: '待发布' },
  { key: 'published', label: '已发布' },
  { key: 'failed', label: '已打回' },
]

async function load() {
  for (const k of Object.keys(lists.value)) {
    try { lists.value[k] = await api.get('/api/outputs/' + k) } catch {}
  }
}

async function approve(it) {
  const { value } = await ElMessageBox.prompt('发布信息(标题必填，定时可空)', `通过 · ${it.id}`, {
    confirmButtonText: '通过并进待发布', cancelButtonText: '取消',
    inputValue: it.title || '',
    inputPlaceholder: '标题 | 用 \n 换行加简介…',
    inputType: 'textarea',
  }).catch(() => ({ value: null }))
  if (value === null) return
  const lines = (value || '').split('\n')
  try {
    const r = await api.post(`/api/review/${it.id}/approve`, {
      title: lines[0] || it.id, desc: lines.slice(1).join('\n') || it.desc || '',
      tags: it.tags || [], platform: 'douyin', publish_now: false,
    })
    ElMessage.success('已通过，进入待发布队列')
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function reject(it) {
  await ElMessageBox.confirm(`打回 ${it.title || it.id}？`, '确认打回', { type: 'warning' })
    .catch(() => Promise.reject())
  try {
    await api.post(`/api/review/${it.id}/reject`)
    ElMessage.success('已打回')
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function publish(it) {
  const { value } = await ElMessageBox.prompt(
    '定时发布时间 (YYYY-MM-DD HH:MM)，留空=立即发布', `发布 · ${it.id}`, {
      confirmButtonText: '发布', cancelButtonText: '取消',
      inputPlaceholder: '如 2026-10-03 20:00',
    }).catch(() => ({ value: null }))
  if (value === null) return
  busy.value = it.id
  try {
    await api.post(`/api/approved/${it.id}/publish`, { schedule: value || null })
    ElMessage.success('已提交发布')
    load()
  } catch (e) { ElMessage.error('发布失败: ' + e.message) }
  finally { busy.value = '' }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>审核队列</h2>
      <span class="sub">左边是输入素材，右边是产出 — 对照验收后才发布</span>
      <div class="sp" />
      <el-button size="small" @click="load">刷新</el-button>
    </div>

    <el-tabs v-model="tab">
      <el-tab-pane v-for="t in TABS" :key="t.key"
                   :label="`${t.label} (${lists[t.key].length})`" :name="t.key" />
    </el-tabs>

    <el-empty v-if="!lists[tab].length" :description="tab === 'review' ? '暂无待审核作品 — 到工作台生成' : '这里空空如也'" :image-size="70" />

    <div v-for="it in lists[tab]" :key="it.id" class="aimf-card">
      <div class="cmp">
        <!-- 左: 输入素材 -->
        <div class="cmp-side">
          <div class="cmp-cap">输入素材</div>
          <InputList :items="it.inputs || []" />
        </div>
        <div class="cmp-arrow">→</div>

        <!-- 右: 产出 -->
        <div class="cmp-main">
          <div style="flex-shrink:0">
            <div class="cmp-cap">产出</div>
            <video v-if="it.is_video" :src="mediaUrl(it.id)" controls class="media-video"
                   style="width:300px;max-height:340px" />
            <img v-else :src="mediaUrl(it.id)" style="width:300px;object-fit:contain;border-radius:10px" />
          </div>
          <div style="flex:1;min-width:240px">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <b>{{ it.title || it.id }}</b>
              <el-tag size="small" effect="plain">{{ it.pipeline || 'graph' }}</el-tag>
              <span class="dim" style="font-size:12px">{{ fmtTime(it.created_at) }}</span>
            </div>
            <div v-if="it.desc" class="dim" style="font-size:12.5px;margin-top:6px">{{ it.desc }}</div>
            <div class="tag-list" style="margin-top:8px">
              <el-tag v-for="t in it.tags || []" :key="t" size="small" effect="plain" type="info">{{ t }}</el-tag>
            </div>
            <div class="dim mono" style="font-size:11.5px;margin-top:8px">{{ it.file }}</div>
            <div v-if="it.job" class="dim" style="font-size:11.5px;margin-top:2px">
              任务 <el-link type="primary" style="font-size:11.5px"
                     @click="router.push({ name: 'canvas', query: { job: it.job } })">{{ it.job }} · 查看执行图</el-link>
            </div>
            <div style="margin-top:14px">
              <template v-if="tab === 'review'">
                <el-button type="success" @click="approve(it)">通过</el-button>
                <el-button type="danger" plain @click="reject(it)">打回</el-button>
              </template>
              <el-button v-if="tab === 'approved'" type="primary" :loading="busy === it.id"
                         @click="publish(it)">发布到抖音</el-button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
