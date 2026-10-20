<script setup>
// 任务中心: 实时进度列表 + 详情抽屉(输入素材/节点状态/日志/产物/执行图回放)
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, mediaUrl, fmtTime, jobTypeName, STATUS_TAG } from '../api'
import InputList from '../components/InputList.vue'

const router = useRouter()

const jobs = ref([])
const detail = ref(null)
const drawer = ref(false)
let timer = null

const NST_COLOR = { running: 'warning', ok: 'success', error: 'danger', skipped: 'info' }
const NST_LABEL = { running: '运行中', ok: '完成', error: '失败', skipped: '跳过' }
const SHOT_LABEL = { pending: '待生成', running: '生成中', done: '完成', failed: '失败' }
const SHOT_TAG = { pending: 'info', running: 'warning', done: 'success', failed: 'danger' }

async function load() {
  try { jobs.value = await api.get('/api/jobs') } catch {}
  if (drawer.value && detail.value) {
    try { detail.value = await api.get('/api/jobs/' + detail.value.id) } catch {}
  }
}

async function open(j) {
  drawer.value = true
  detail.value = j
  detail.value = await api.get('/api/jobs/' + j.id)
}

function res(j) { return j.result || {} }
function inputs(j) { return (j.params || {}).inputs || res(j).inputs || [] }
function shotList(j) { return res(j).shots || [] }
function shotDone(j) { return shotList(j).filter(s => s.status === 'done').length }
function planId(j) { return (j.params || {}).plan_id || '' }
function hasGraph(j) { return !!(j.params || {}).graph }
function nodeList(j) { return Object.entries(res(j).node_status || {}) }
function logs(j) { return res(j).logs || [] }
function items(j) { return res(j).items || (res(j).item_id ? [res(j).item_id] : []) }
function errMsg(j) {
  return res(j).error || res(j).recover_error || (res(j).errors || [])[0] || ''
}

onMounted(() => { load(); timer = setInterval(load, 4000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>任务中心</h2>
      <span class="sub">生成/画布/定时任务实时进度 · 每4秒刷新</span>
    </div>
    <div class="aimf-card">
      <el-table :data="jobs" size="default" @row-click="open" style="cursor:pointer">
        <el-table-column label="任务ID" prop="id" min-width="240" class-name="mono" show-overflow-tooltip />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">{{ jobTypeName(row.type) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="(STATUS_TAG[row.status]||{}).type || 'info'" size="small" effect="dark">
              {{ (STATUS_TAG[row.status]||{}).label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="分镜" width="100">
          <template #default="{ row }">
            <span v-if="row.type === 'product_video' && shotList(row).length" class="dim">
              {{ shotDone(row) }}/{{ shotList(row).length }} 镜
            </span>
          </template>
        </el-table-column>
        <el-table-column label="结果/错误" min-width="200">
          <template #default="{ row }">
            <span v-if="errMsg(row)" class="dim" style="color:#f87171">{{ errMsg(row).slice(0, 60) }}</span>
            <span v-else-if="items(row).length" class="dim">产出 {{ items(row).length }} 项</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }"><span class="dim">{{ fmtTime(row.created_at) }}</span></template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!jobs.length" description="暂无任务" :image-size="60" />
    </div>

    <el-drawer v-model="drawer" :title="detail?.id || ''" size="480px">
      <template v-if="detail">
        <div style="margin-bottom:14px">
          <el-tag :type="(STATUS_TAG[detail.status]||{}).type" effect="dark">
            {{ (STATUS_TAG[detail.status]||{}).label || detail.status }}
          </el-tag>
          <span class="dim" style="margin-left:10px;font-size:12.5px">{{ jobTypeName(detail.type) }}</span>
          <span class="dim" style="margin-left:10px;font-size:12.5px">{{ fmtTime(detail.created_at) }}</span>
          <span v-if="res(detail).phase" class="dim" style="margin-left:10px;font-size:12.5px">
            · {{ res(detail).phase }}
          </span>
        </div>

        <el-button v-if="hasGraph(detail)" size="small" type="primary" plain
                   @click="router.push({ name: 'canvas', query: { job: detail.id } })">
          查看对应图（只读回放）
        </el-button>
        <el-button v-if="planId(detail)" size="small" type="primary" plain
                   @click="router.push({ name: 'product-video', query: { plan: planId(detail) } })">
          打开带货视频方案
        </el-button>
        <el-button v-if="['fission_run', 'fission_p0'].includes(detail.type) && res(detail).run_dir"
                   size="small" type="primary" plain
                   @click="router.push({ name: 'fission', query: {
                     run: String(res(detail).run_dir).split('/').filter(Boolean).pop() } })">
          打开裂变结果
        </el-button>

        <template v-if="res(detail).provider_task">
          <h4 style="margin:14px 0 8px">服务商任务 ID</h4>
          <div class="mono dim" style="font-size:12px;user-select:all">
            {{ res(detail).provider_task }}
            <span v-if="res(detail).provider_via"> · {{ res(detail).provider_via }}</span>
          </div>
        </template>

        <template v-if="shotList(detail).length">
          <h4 style="margin:14px 0 8px">分镜进度</h4>
          <div class="tag-list">
            <el-tag v-for="s in shotList(detail)" :key="s.index"
                    :type="SHOT_TAG[s.status] || 'info'" size="small" effect="plain">
              分镜{{ s.index }}: {{ SHOT_LABEL[s.status] || s.status }}
            </el-tag>
          </div>
        </template>

        <template v-if="inputs(detail).length">
          <h4 style="margin:14px 0 8px">输入素材</h4>
          <InputList :items="inputs(detail)" />
        </template>

        <template v-if="nodeList(detail).length">
          <h4 style="margin:14px 0 8px">节点状态</h4>
          <div class="tag-list">
            <el-tag v-for="[nid, st] in nodeList(detail)" :key="nid"
                    :type="NST_COLOR[st] || 'info'" size="small" effect="plain">
              {{ nid }}: {{ NST_LABEL[st] || st }}
            </el-tag>
          </div>
        </template>

        <template v-if="res(detail).script || res(detail).visual_prompt">
          <h4 style="margin:14px 0 8px">生成文案</h4>
          <div class="aimf-card" style="padding:12px;font-size:12.5px">
            <div v-if="res(detail).script"><b>口播:</b> {{ res(detail).script }}</div>
            <div v-if="res(detail).visual_prompt" style="margin-top:6px"><b>画面:</b> {{ res(detail).visual_prompt }}</div>
          </div>
        </template>

        <template v-if="items(detail).length">
          <h4 style="margin:14px 0 8px">产物</h4>
          <div v-for="it in items(detail)" :key="it" style="margin-bottom:10px">
            <video :src="mediaUrl(it)" controls class="media-video" style="max-height:260px" />
            <div class="dim mono" style="font-size:11.5px">{{ it }}</div>
          </div>
        </template>

        <template v-if="logs(detail).length">
          <h4 style="margin:14px 0 8px">日志</h4>
          <div class="mono dim" style="font-size:12px">
            <div v-for="(l, i) in logs(detail)" :key="i">{{ l }}</div>
          </div>
        </template>

        <template v-if="errMsg(detail)">
          <h4 style="margin:14px 0 8px;color:#f87171">错误</h4>
          <div style="color:#f87171;font-size:12.5px;white-space:pre-wrap">{{ errMsg(detail) }}</div>
        </template>
      </template>
    </el-drawer>
  </div>
</template>
