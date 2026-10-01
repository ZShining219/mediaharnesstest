<script setup>
// 画布自定义节点: 标题(分类色) + 类型化端口 + 参数表单 + 状态染色 + 素材预览
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { ElMessage } from 'element-plus'
import { api, assetUrl } from '../api'
import { store, assetValues, groupUploadKind } from '../store'

const props = defineProps({
  id: String,
  type: String,
  data: Object,   // {def, params, status}
  selected: Boolean,
})

const def = computed(() => props.data.def || {})
const params = computed(() => props.data.params)

const inPorts = computed(() => (def.value.inputs || []).map(([n, t], i) => ({
  name: n.replace(/^\?/, ''), optional: n.startsWith('?'), dtype: t, id: `in-${i}`, slot: i,
})))
const outPorts = computed(() => (def.value.outputs || []).map(([n, t], i) => ({
  name: n, dtype: t, id: `out-${i}`, slot: i,
})))

const DT_COLOR = { video: '#22d3ee', image: '#a78bfa', audio: '#34d399', text: '#fbbf24' }
const portColor = (t) => DT_COLOR[t] || '#94a3b8'

const statusLabel = computed(() => ({
  running: '运行中', ok: '完成', error: '失败', skipped: '跳过',
}[props.data.status] || ''))
const statusType = computed(() => ({
  running: 'warning', ok: 'success', error: 'danger', skipped: 'info',
}[props.data.status] || 'info'))

// ---- 参数控件 ----
function comboOptions(p) {
  // @characters / @looks 动态选项
  const spec = p.options === undefined && (p.kind || '').startsWith('@') ? p.kind : p.options
  if (spec === '@characters') return store.characters.map(c => c.name)
  if (spec === '@looks') {
    const ch = store.characters.find(c => c.name === params.value['角色'])
    return (ch?.looks || []).map(l => `assets/characters/${ch.name}/looks/${l}`)
  }
  return p.options || []
}

function isAsset(p) { return (p.kind || '').startsWith('asset:') }
function assetGroup(p) { return p.kind.slice(6) }
function assetOpts(p) { return assetValues(assetGroup(p)) }

function isVideoPath(p) { return /\.(mp4|mov|webm|mkv)$/i.test(p || '') }
function isImgPath(p) { return /\.(png|jpe?g|webp|gif)$/i.test(p || '') }

function pickUpload(p) {
  const inp = document.createElement('input')
  inp.type = 'file'
  inp.onchange = async () => {
    const f = inp.files[0]
    if (!f) return
    try {
      const r = await api.upload(f, groupUploadKind(assetGroup(p)))
      params.value[p.name] = r.path
      ElMessage.success('已上传 ' + r.path)
      store.loaded = false
    } catch (e) { ElMessage.error('上传失败: ' + e.message) }
  }
  inp.click()
}
</script>

<template>
  <div class="flow-node" :class="[`cat-${def.category}`, data.status ? `st-${data.status}` : '']">
    <div class="fn-head">
      <span>{{ def.title }}</span>
      <el-tag v-if="statusLabel" :type="statusType" size="small"
              style="margin-left:auto" effect="dark">{{ statusLabel }}</el-tag>
    </div>
    <div class="fn-io">
      <div v-for="p in inPorts" :key="p.id" class="fn-port">
        {{ p.name }}<span v-if="p.optional" class="t">(可选)</span>
        <Handle type="target" :id="p.id" :position="Position.Left"
                :class="`dt-${p.dtype === '*' ? 'any' : p.dtype}`"
                :style="{ background: portColor(p.dtype) }" />
      </div>
      <div v-for="p in outPorts" :key="p.id" class="fn-port out">
        {{ p.name }}
        <Handle type="source" :id="p.id" :position="Position.Right"
                :class="`dt-${p.dtype === '*' ? 'any' : p.dtype}`"
                :style="{ background: portColor(p.dtype) }" />
      </div>
    </div>
    <div class="fn-params" v-if="(def.params || []).length">
      <template v-for="p in def.params" :key="p.name">
        <div class="nodrag nowheel">
          <label>{{ p.name }}<span v-if="p.hint" class="t"> · {{ p.hint }}</span></label>

          <!-- 素材选择 -->
          <div v-if="isAsset(p)" style="display:flex;gap:4px">
            <el-select v-model="params[p.name]" size="small" filterable clearable
                       :placeholder="'选择素材'" style="flex:1" @change="()=>{}">
              <el-option v-for="v in assetOpts(p)" :key="v" :value="v"
                         :label="v.split('/').pop()" />
            </el-select>
            <el-button size="small" @click="pickUpload(p)">传</el-button>
          </div>
          <img v-if="isAsset(p) && isImgPath(params[p.name])" class="preview-img"
               :src="assetUrl(params[p.name])" alt="">
          <video v-else-if="isAsset(p) && isVideoPath(params[p.name])" class="preview-img"
                 :src="assetUrl(params[p.name])" muted playsinline preload="metadata"></video>

          <el-select v-else-if="p.kind === 'combo' || (p.kind || '').startsWith('@')"
                     v-model="params[p.name]" size="small" filterable clearable>
            <el-option v-for="o in comboOptions(p)" :key="o" :value="o" :label="o" />
          </el-select>
          <el-switch v-else-if="p.kind === 'toggle'" v-model="params[p.name]" size="small" />
          <el-input v-else-if="p.kind === 'number'" v-model.number="params[p.name]"
                    type="number" size="small" />
          <el-input v-else-if="p.kind === 'textarea'" v-model="params[p.name]"
                    type="textarea" :rows="2" size="small" resize="none" />
          <el-input v-else v-model="params[p.name]" size="small" />
        </div>
      </template>
    </div>
  </div>
</template>
