<script setup>
// 系统状态: 各服务健康检查 + 配置提示
import { ref, onMounted } from 'vue'
import { api } from '../api'

const h = ref(null)
const loading = ref(true)

const ITEMS = [
  { key: 'minimax', name: 'MiniMax 视频生成(秘塔代理)', desc: 'H3 文生/图生/参考生视频，换脸链路核心' },
  { key: 'minimax_tts', name: 'MiniMax TTS(官方站)', desc: '情感 TTS / 声音克隆' },
  { key: 'deepseek', name: 'DeepSeek LLM', desc: '文案/提示词生成' },
  { key: 'wavespeed', name: 'WaveSpeed', desc: 'InfiniteTalk/Wan-Animate 备选通道' },
  { key: 'comfyui', name: 'ComfyUI(自建GPU)', desc: '可选高级通道' },
  { key: 'mpt', name: 'MoneyPrinterTurbo', desc: '自动创作备选后端' },
  { key: 'sau', name: 'sau 发布', desc: '抖音等平台自动发布' },
]

const okOf = (k, v) => v.ok ?? v.configured ?? v.installed ?? false

onMounted(async () => {
  try { h.value = await api.get('/api/health') } catch {}
  loading.value = false
})
</script>

<template>
  <div class="page">
    <div class="page-head"><h2>系统状态</h2><span class="sub">各服务连通性</span></div>
    <div class="aimf-card">
      <el-skeleton v-if="loading" :rows="4" animated />
      <template v-else-if="h">
        <div v-for="it in ITEMS" :key="it.key" style="display:flex;align-items:center;gap:12px;padding:10px 4px;border-bottom:1px solid var(--aimf-line)">
          <span :style="{
            width: '10px', height: '10px', borderRadius: '50%', flexShrink: 0,
            background: okOf(it.key, h[it.key] || {}) ? '#34d399' : '#f87171',
          }"></span>
          <div style="flex:1">
            <b>{{ it.name }}</b>
            <div class="dim" style="font-size:12px">{{ it.desc }} · {{ (h[it.key]||{}).url || '' }}</div>
          </div>
          <el-tag :type="okOf(it.key, h[it.key] || {}) ? 'success' : 'danger'" size="small" effect="plain">
            {{ okOf(it.key, h[it.key] || {}) ? '正常' : '不可用' }}
          </el-tag>
        </div>
        <div class="dim" style="font-size:12px;margin-top:12px">
          秘塔代理只代理 video_generation; TTS/声音克隆走官方站 (MINIMAX_API_KEY_OFFICIAL)。
          WaveSpeed/ComfyUI/MPT 为可选备选通道，未配置不影响主链路。
        </div>
      </template>
      <el-empty v-else description="后端不可达" />
    </div>
  </div>
</template>
