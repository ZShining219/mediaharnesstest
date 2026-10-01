<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from './api'
import {
  Monitor, Share, DocumentChecked, Finished, FolderOpened, Timer, Odometer, VideoPlay,
} from '@element-plus/icons-vue'

const route = useRoute()
const reviewCount = ref(0)
const runningCount = ref(0)
let timer = null

const menus = [
  { name: 'studio', label: '工作台', icon: Monitor },
  { name: 'canvas', label: '节点画布', icon: Share },
  { name: 'jobs', label: '任务中心', icon: DocumentChecked },
  { name: 'review', label: '审核队列', icon: Finished, badge: () => reviewCount.value },
  { name: 'assets', label: '素材库', icon: FolderOpened },
  { name: 'schedules', label: '定时发布', icon: Timer },
  { name: 'status', label: '系统状态', icon: Odometer },
]

async function poll() {
  try {
    const [rv, jb] = await Promise.all([api.get('/api/review'), api.get('/api/jobs')])
    reviewCount.value = rv.length
    runningCount.value = jb.filter(j => j.status === 'running').length
  } catch { /* 后端未起时静默 */ }
}
onMounted(() => { poll(); timer = setInterval(poll, 8000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="layout">
    <aside class="side">
      <div class="logo"><span class="ico"><el-icon><VideoPlay /></el-icon></span>AI 传媒工作台</div>
      <nav>
        <a v-for="m in menus" :key="m.name" href="javascript:;"
           :class="{ on: route.name === m.name }"
           @click="$router.push({ name: m.name })">
          <el-icon><component :is="m.icon" /></el-icon>
          {{ m.label }}
          <el-badge v-if="m.badge && m.badge()" :value="m.badge()" class="badge" type="danger" />
          <el-badge v-else-if="m.name==='jobs' && runningCount" :value="runningCount" class="badge" type="warning" />
        </a>
      </nav>
      <div class="foot">MiniMax H3 · DeepSeek<br>托管推理 · 零 GPU</div>
    </aside>
    <main class="main">
      <router-view />
    </main>
  </div>
</template>
