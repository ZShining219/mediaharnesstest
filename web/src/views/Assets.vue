<script setup>
// 素材库: 分组浏览/上传/预览 + 角色管理
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled, Plus } from '@element-plus/icons-vue'
import { api, assetUrl } from '../api'
import { store, refreshMeta } from '../store'

const KINDS = [
  { key: 'source', label: '对标视频', icon: '📹', accept: 'video/*' },
  { key: 'image', label: '参考图', icon: '🖼️', accept: 'image/*' },
  { key: 'garment', label: '服装图', icon: '👗', accept: 'image/*' },
  { key: 'voice', label: '声音样本', icon: '🎙️', accept: 'audio/*' },
  { key: 'bgm', label: '背景音乐', icon: '🎵', accept: 'audio/*' },
]
const tab = ref('source')
const preview = ref(null)
const uploading = ref(false)

const isVideo = (p) => /\.(mp4|mov|webm|mkv)$/i.test(p)
const isAudio = (p) => /\.(mp3|wav|m4a|aac|ogg)$/i.test(p)
const isImage = (p) => /\.(png|jpe?g|webp|gif)$/i.test(p)
const fname = (p) => (p || '').split('/').pop()

async function onUpload(ev, kind) {
  const files = ev.target.files || ev.dataTransfer?.files
  if (!files?.length) return
  uploading.value = true
  try {
    for (const f of files) {
      const r = await api.upload(f, kind)
      ElMessage.success('已上传 ' + r.path)
    }
    store.loaded = false
    await refreshMeta(true)
  } catch (e) { ElMessage.error('上传失败: ' + e.message) }
  finally { uploading.value = false; if (ev.target) ev.target.value = '' }
}

// ---- 角色 ----
async function createChar() {
  const { value } = await ElMessageBox.prompt('角色名（英文/拼音）', '新建角色', {
    confirmButtonText: '创建', cancelButtonText: '取消', inputPattern: /\S+/,
  }).catch(() => ({}))
  if (!value) return
  await api.post(`/api/characters/${value}/config`, {})
  ElMessage.success('已创建角色 ' + value)
  await refreshMeta(true)
}
async function uploadLook(c) {
  const inp = document.createElement('input')
  inp.type = 'file'; inp.accept = 'image/*'
  inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return
    const r = await api.upload(f, 'look', `&character=${c.name}`)
    ElMessage.success('已上传 ' + r.path)
    // 自动设为当前形象
    await api.post(`/api/characters/${c.name}/config`, { look: 'looks/' + r.name })
    await refreshMeta(true)
  }
  inp.click()
}
async function cloneVoice(c) {
  const vs = store.assets.voice || []
  if (!vs.length) { ElMessage.warning('先上传一段声音样本(声音样本页签)'); return }
  const { value: v } = await ElMessageBox.prompt(
    '选声音样本路径：\n' + vs.join('\n'), `克隆声音 · ${c.name}`,
    { inputValue: vs[0], confirmButtonText: '下一步' }).catch(() => ({}))
  if (!v) return
  const { value: vid } = await ElMessageBox.prompt('自定义音色ID(英文)', `克隆声音 · ${c.name}`,
    { inputValue: c.name + '_voice', confirmButtonText: '开始克隆' }).catch(() => ({}))
  if (!vid) return
  try {
    const r = await api.post('/api/voice/clone', { voice_path: v, voice_id: vid, character: c.name })
    ElMessage.success('克隆完成: ' + r.voice_id)
    await refreshMeta(true)
  } catch (e) { ElMessage.error('克隆失败: ' + e.message) }
}
async function setLook(c, look) {
  await api.post(`/api/characters/${c.name}/config`, { look: 'looks/' + look })
  ElMessage.success('已切换形象')
  await refreshMeta(true)
}

onMounted(() => refreshMeta())
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>素材库</h2>
      <span class="sub">素材即 assets/ 目录，管线与画布直接引用</span>
      <div class="sp" />
      <el-button size="small" @click="refreshMeta(true)">刷新</el-button>
    </div>

    <div class="aimf-card">
      <h3>角色管理 <el-button size="small" :icon="Plus" @click="createChar">新建角色</el-button></h3>
      <div style="display:flex;gap:14px;flex-wrap:wrap">
        <div v-for="c in store.characters" :key="c.name" class="aimf-card"
             style="padding:14px;display:flex;gap:12px;min-width:320px">
          <img v-if="c.has_look" :src="assetUrl(`assets/characters/${c.name}/${c.look}`)"
               style="width:88px;height:88px;object-fit:cover;border-radius:10px" />
          <div v-else style="width:88px;height:88px;border-radius:10px;background:#0d1119;
               display:grid;place-items:center;color:#5f6780;font-size:12px">无形象</div>
          <div style="flex:1">
            <b>{{ c.name }}</b>
            <el-tag size="small" :type="c.voice_id ? 'success' : 'warning'" effect="plain"
                    style="margin-left:8px">{{ c.voice_id ? '已配声音' : '默认音色' }}</el-tag>
            <div class="dim" style="font-size:12px;margin:6px 0">
              形象: {{ c.look || '-' }}
              <template v-if="c.looks.length > 1">
                <el-select size="small" :model-value="(c.look||'').replace('looks/','')"
                           style="width:150px;margin-left:6px" @change="v => setLook(c, v)">
                  <el-option v-for="l in c.looks" :key="l" :value="l" :label="l" />
                </el-select>
              </template>
            </div>
            <el-button size="small" @click="uploadLook(c)">上传形象图</el-button>
            <el-button size="small" @click="cloneVoice(c)">克隆声音</el-button>
          </div>
        </div>
        <el-empty v-if="!store.characters.length" description="还没有角色，点右上角新建" :image-size="50" />
      </div>
    </div>

    <div class="aimf-card">
      <el-tabs v-model="tab">
        <el-tab-pane v-for="k in KINDS" :key="k.key" :name="k.key"
                     :label="`${k.icon} ${k.label} (${(store.assets[k.key]||[]).length})`" />
      </el-tabs>

      <el-upload drag multiple :show-file-list="false" :auto-upload="false"
                 :accept="KINDS.find(k=>k.key===tab)?.accept"
                 @change="f => onUpload({ target: { files: [f.raw] } }, tab)">
        <el-icon size="40" style="color:#5f6780"><UploadFilled /></el-icon>
        <div style="color:var(--aimf-dim);font-size:13px">
          拖拽文件到这里，或<em style="color:#a5b4fc">点击上传</em>
        </div>
      </el-upload>

      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin-top:16px">
        <div v-for="p in store.assets[tab] || []" :key="p"
             style="border:1px solid var(--aimf-line);border-radius:10px;overflow:hidden;cursor:pointer;background:#0d1119"
             @click="preview = p">
          <video v-if="isVideo(p)" :src="assetUrl(p)" class="media-thumb" muted
                 preload="metadata" @loadeddata="e => e.target.currentTime = 0.5" />
          <img v-else-if="isImage(p)" :src="assetUrl(p)" class="media-thumb" />
          <div v-else-if="isAudio(p)" style="padding:14px;text-align:center;color:var(--aimf-dim)">🎵 音频</div>
          <div v-else style="padding:14px;text-align:center;color:var(--aimf-dim)">📄 文件</div>
          <div style="padding:8px 10px;font-size:12px" class="dim">
            <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ fname(p) }}</div>
          </div>
        </div>
      </div>
      <el-empty v-if="!(store.assets[tab]||[]).length" description="该分类还没有素材" :image-size="50" />
    </div>

    <el-dialog :model-value="!!preview" :title="fname(preview)" width="560px" @close="preview = null">
      <video v-if="preview && isVideo(preview)" :src="assetUrl(preview)" controls class="media-video" />
      <img v-else-if="preview && isImage(preview)" :src="assetUrl(preview)" style="width:100%;border-radius:10px" />
      <audio v-else-if="preview && isAudio(preview)" :src="assetUrl(preview)" controls style="width:100%" />
      <div class="mono dim" style="font-size:12px;margin-top:8px">{{ preview }}</div>
    </el-dialog>
  </div>
</template>
