<script setup>
// 定时任务: cron 生成/发布计划 (写回 config.yaml 持久化)
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { store, refreshMeta } from '../store'

const jobs = ref([])
const dlg = ref(false)
const form = ref({ type: 'publish_approved', cron: '0 21 * * *', params: {} })

const TYPES = [
  { value: 'digital_human', label: '数字人口播生成', fields: [
    { k: 'character', label: '角色', type: 'character' },
    { k: 'text', label: '口播文案', type: 'textarea' },
    { k: 'emotion', label: '情绪', type: 'select', opts: ['neutral', 'happy', 'sad'] },
  ]},
  { value: 'video_transform', label: '视频转换(人物替换)', fields: [
    { k: 'source', label: '对标视频(素材路径)', type: 'select', opts: () => store.assets.source },
    { k: 'face', label: '形象图(素材路径)', type: 'select', opts: () => [...store.assets.image, ...store.assets.garment] },
  ]},
  { value: 'auto_content', label: '自动创作生成', fields: [
    { k: 'subject', label: '主题', type: 'text' },
  ]},
  { value: 'publish_approved', label: '发布已通过队列', fields: [
    { k: 'platform', label: '平台', type: 'select', opts: ['douyin', 'xhs', 'bilibili'] },
  ]},
]

const curType = () => TYPES.find(t => t.value === form.value.type)
const opts = (f) => typeof f.opts === 'function' ? f.opts() : (f.opts || [])

async function load() { jobs.value = await api.get('/api/schedules') }

async function add() {
  try {
    const params = {}
    for (const f of curType().fields) {
      const v = form.value.params[f.k]
      if (v !== undefined && v !== '') params[f.k] = v
    }
    await api.post('/api/schedules', { type: form.value.type, cron: form.value.cron, params })
    ElMessage.success('已添加定时任务')
    dlg.value = false
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function del(j) {
  await ElMessageBox.confirm(`删除定时任务 ${j.id}？`, '确认', { type: 'warning' }).catch(() => Promise.reject())
  await api.del('/api/schedules/' + j.id)
  ElMessage.success('已删除')
  load()
}

const TYPE_LABEL = { digital_human: '数字人', video_transform: '视频转换', auto_content: '自动创作', publish_approved: '发布队列' }

onMounted(async () => { await refreshMeta().catch(() => {}); load() })
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>定时任务</h2>
      <span class="sub">cron 定时生成 / 定点发布（写回 config.yaml 持久化）</span>
      <div class="sp" />
      <el-button type="primary" size="small" @click="dlg = true">新增定时任务</el-button>
    </div>

    <div class="aimf-card">
      <el-table :data="jobs" size="default">
        <el-table-column label="ID" prop="id" min-width="160" class-name="mono" show-overflow-tooltip />
        <el-table-column label="类型" width="130">
          <template #default="{ row }">{{ TYPE_LABEL[row.type] || row.type }}</template>
        </el-table-column>
        <el-table-column label="cron" prop="cron" width="140" class-name="mono" />
        <el-table-column label="参数" min-width="200">
          <template #default="{ row }">
            <span class="dim" style="font-size:12px">{{ JSON.stringify(row.params || {}) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="下次执行" width="180">
          <template #default="{ row }">
            <span class="dim" style="font-size:12.5px">{{ row.next_run ? new Date(row.next_run).toLocaleString('zh-CN',{hour12:false}) : '未启用' }}</span>
          </template>
        </el-table-column>
        <el-table-column width="80">
          <template #default="{ row }">
            <el-button link type="danger" size="small" @click="del(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!jobs.length" description="暂无定时任务" :image-size="60" />
      <div class="dim" style="font-size:12px;margin-top:10px">
        cron 格式：分 时 日 月 周，例如 <code class="mono">0 21 * * *</code> = 每天 21:00；<code class="mono">0 8 * * *</code> = 每天 8:00
      </div>
    </div>

    <el-dialog v-model="dlg" title="新增定时任务" width="480px">
      <el-form label-position="top">
        <el-form-item label="任务类型">
          <el-select v-model="form.type" style="width:100%" @change="form.params = {}">
            <el-option v-for="t in TYPES" :key="t.value" :value="t.value" :label="t.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="cron 表达式">
          <el-input v-model="form.cron" placeholder="分 时 日 月 周" />
        </el-form-item>
        <el-form-item v-for="f in curType().fields" :key="f.k" :label="f.label">
          <el-select v-if="f.type === 'select' || f.type === 'character'"
                     v-model="form.params[f.k]" style="width:100%" filterable>
            <el-option v-for="o in (f.type === 'character' ? store.characters.map(c => c.name) : opts(f))"
                       :key="o" :value="o" :label="o.split ? o.split('/').pop() : o" />
          </el-select>
          <el-input v-else-if="f.type === 'textarea'" v-model="form.params[f.k]" type="textarea" :rows="3" />
          <el-input v-else v-model="form.params[f.k]" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" @click="add">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>
