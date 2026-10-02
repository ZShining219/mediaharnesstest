<script setup>
// 输入素材清单: 任务/审核记录的前后对照左栏。items: [{label,kind,path|text}]
import { ref } from 'vue'
import { fileUrl } from '../api'

defineProps({ items: { type: Array, default: () => [] } })

const preview = ref(null)   // {label,kind,path}
const KIND_TAG = { video: '', image: 'success', audio: 'warning', text: 'info' }
const KIND_LABEL = { video: '视频', image: '图片', audio: '音频', text: '文本' }
const fname = (p) => (p || '').split('/').pop()
const short = (t) => (t || '').length > 90 ? t.slice(0, 90) + '…' : t
</script>

<template>
  <div v-if="items.length" class="in-list">
    <div v-for="(inp, i) in items" :key="i" class="in-item"
         :class="{ clickable: inp.kind !== 'text' || (inp.text || '').length > 90 }"
         @click="inp.kind !== 'text' || (inp.text || '').length > 90 ? preview = inp : null">
      <template v-if="inp.kind === 'video'">
        <video :src="fileUrl(inp.path)" class="in-thumb" muted preload="metadata" />
      </template>
      <template v-else-if="inp.kind === 'image'">
        <img :src="fileUrl(inp.path)" class="in-thumb" />
      </template>
      <template v-else-if="inp.kind === 'audio'">
        <div class="in-thumb in-audio">🎵</div>
      </template>
      <template v-else>
        <div class="in-text">{{ short(inp.text) }}</div>
      </template>
      <div class="in-meta">
        <el-tag size="small" :type="KIND_TAG[inp.kind] || 'info'" effect="plain">
          {{ KIND_LABEL[inp.kind] || inp.kind }}
        </el-tag>
        <span class="in-label" :title="inp.path || inp.text">{{ inp.label }}</span>
      </div>
      <div class="in-path mono dim" :title="inp.path">{{ inp.path ? fname(inp.path) : '' }}</div>
    </div>
  </div>
  <div v-else class="dim" style="font-size:12px;padding:8px 2px">无输入素材记录(旧任务)</div>

  <el-dialog :model-value="!!preview" :title="preview?.label" width="560px"
             @close="preview = null">
    <video v-if="preview?.kind === 'video'" :src="fileUrl(preview.path)"
           controls class="media-video" />
    <img v-else-if="preview?.kind === 'image'" :src="fileUrl(preview.path)"
         style="width:100%;border-radius:10px" />
    <audio v-else-if="preview?.kind === 'audio'" :src="fileUrl(preview.path)"
           controls style="width:100%" />
    <div v-else style="white-space:pre-wrap;font-size:13px">{{ preview?.text }}</div>
    <div class="mono dim" style="font-size:12px;margin-top:8px">{{ preview?.path }}</div>
  </el-dialog>
</template>
