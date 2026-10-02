<script setup>
// 工作台: 三张傻瓜功能卡 + 最近任务条
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, fmtTime, jobTypeName, STATUS_TAG } from '../api'
import { store, refreshMeta } from '../store'

const router = useRouter()
const dash = ref(null)
const dlg = ref('')          // dh | vt | ac
const submitting = ref(false)

// --- 数字人 ---
const dh = ref({ character: '', emotion: 'neutral', text: '', title: '', tags: '' })
// --- 视频转换 ---
const vt = ref({ source: '', face: '', prompt: '', resolution: '768P', title: '' })
// --- 自动创作 ---
const ac = ref({ subject: '', script: '', title: '' })

const emotions = ['neutral', 'happy', 'sad', 'angry', 'surprise', 'fear', 'disgust']

// 每张卡背后对应一条节点链(与节点画布的等效执行图一致)
const CARD_STEPS = {
  dh: ['口播文案', 'MiniMax TTS 配音', 'H3 形象口播(图+声音→视频)', '合成音轨 · 烧字幕', '审核队列'],
  vt: ['对标视频 + 形象图', 'H3 人物替换', '回填原视频音轨', '审核队列'],
  ac: ['主题', 'DeepSeek 口播文案', 'MiniMax TTS 配音', 'DeepSeek 画面提示词', 'H3 文生视频', '合成音轨', '审核队列'],
}

async function submit(kind) {
  submitting.value = true
  try {
    let r
    if (kind === 'dh') {
      if (!dh.value.text.trim()) { ElMessage.warning('请填口播文案'); return }
      if (!dh.value.character) { ElMessage.warning('请选择角色(先到素材库建角色并传形象图)'); return }
      r = await api.post('/api/jobs/digital-human', {
        text: dh.value.text, character: dh.value.character,
        emotion: dh.value.emotion || null, title: dh.value.title || null,
        tags: dh.value.tags.split(/[,，]/).filter(Boolean),
      })
    } else if (kind === 'vt') {
      if (!vt.value.source || !vt.value.face) { ElMessage.warning('需要对标视频和形象图'); return }
      r = await api.post('/api/jobs/video-transform', {
        source: vt.value.source, face: vt.value.face,
        prompt: vt.value.prompt, resolution: vt.value.resolution,
        title: vt.value.title || null,
      })
    } else {
      if (!ac.value.subject.trim()) { ElMessage.warning('请填主题'); return }
      r = await api.post('/api/jobs/auto-content', {
        subject: ac.value.subject, script: ac.value.script,
        title: ac.value.title || null,
      })
    }
    ElMessage.success('任务已入队，可在「任务中心」看进度')
    dlg.value = ''
    loadDash()
  } catch (e) {
    ElMessage.error('提交失败: ' + e.message)
  } finally { submitting.value = false }
}

async function uploadInline(kind, ev) {
  const f = ev.target.files?.[0]
  if (!f) return
  try {
    const r = await api.upload(f, kind)
    ElMessage.success('已上传 ' + r.path)
    store.loaded = false
    await refreshMeta(true)
    return r.path
  } catch (e) { ElMessage.error(e.message) }
}

async function vtPickVideo(e) {
  const p = await uploadInline('source', e)
  if (p) vt.value.source = p
}
async function vtPickImage(e) {
  const p = await uploadInline('image', e)
  if (p) vt.value.face = p
}

async function loadDash() { try { dash.value = await api.get('/api/dashboard') } catch {} }

onMounted(async () => {
  await refreshMeta().catch(() => {})
  loadDash()
  if (store.characters.length && !dh.value.character) dh.value.character = store.characters[0].name
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>工作台</h2>
      <span class="sub">固定流程卡 · 照流程填表即跑（想自己编排节点请去「节点画布」）</span>
      <div class="sp" />
      <template v-if="dash">
        <el-tag type="warning" effect="plain">待审核 {{ dash.review }}</el-tag>
        <el-tag type="success" effect="plain">待发布 {{ dash.approved }}</el-tag>
        <el-tag effect="plain">已发布 {{ dash.published }}</el-tag>
        <el-tag v-if="dash.jobs_running" type="danger" effect="plain">运行中 {{ dash.jobs_running }}</el-tag>
      </template>
    </div>

    <div class="feat-grid">
      <div class="feat-card" @click="dlg = 'dh'">
        <div class="fico">👤</div>
        <h3>数字人口播</h3>
        <p>选一个数字人角色 + 粘一段文案，自动配音、生成口播视频、烧字幕、进审核。</p>
        <span class="cost">≈ ¥0.5/条 · MiniMax TTS + H3</span>
        <span class="cta">开始制作 →</span>
      </div>
      <div class="feat-card" @click="dlg = 'vt'">
        <div class="fico">🔄</div>
        <h3>对标视频转换</h3>
        <p>传对标视频 + 目标形象图，把视频里的人物替换成你的形象(换脸/换人)，动作场景保留。</p>
        <span class="cost">≈ ¥1/条 · MiniMax H3</span>
        <span class="cta">开始转换 →</span>
      </div>
      <div class="feat-card" @click="dlg = 'ac'">
        <div class="fico">⚡</div>
        <h3>自动化创作</h3>
        <p>只填主题：DeepSeek 写文案+画面提示词，MiniMax 配音、生成画面、自动合成。</p>
        <span class="cost">≈ ¥0.7/条 · DeepSeek + MiniMax</span>
        <span class="cta">开始创作 →</span>
      </div>
    </div>

    <div class="aimf-card" style="margin-top:20px">
      <h3>最近任务 <el-link type="primary" style="font-size:12px;font-weight:400" @click="router.push('/jobs')">全部 →</el-link></h3>
      <el-table v-if="dash && dash.jobs_recent.length" :data="dash.jobs_recent" size="small"
                @row-click="r => router.push('/jobs')" style="cursor:pointer">
        <el-table-column label="任务" prop="id" min-width="260" class-name="mono" show-overflow-tooltip />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">{{ jobTypeName(row.type) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="(STATUS_TAG[row.status]||{}).type || 'info'" size="small" effect="dark">
              {{ (STATUS_TAG[row.status]||{}).label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }"><span class="dim">{{ fmtTime(row.created_at) }}</span></template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="还没有任务 — 点上面的功能卡开始" :image-size="60" />
    </div>

    <!-- ===== 数字人弹窗 ===== -->
    <el-dialog :model-value="dlg==='dh'" title="数字人口播" width="480px" @close="dlg=''">
      <el-form label-position="top" size="default">
        <el-form-item label="角色（形象+声音）">
          <el-select v-model="dh.character" style="width:100%">
            <el-option v-for="c in store.characters" :key="c.name" :value="c.name"
                       :label="c.name + (c.voice_id ? '' : ' (未配声音，用默认音色)')" />
          </el-select>
          <div class="dim" style="font-size:12px">没有角色？到 <el-link @click="router.push('/assets')">素材库</el-link> 新建并上传形象图</div>
        </el-form-item>
        <el-form-item label="情绪">
          <el-select v-model="dh.emotion" style="width:100%">
            <el-option v-for="e in emotions" :key="e" :value="e" :label="e" />
          </el-select>
        </el-form-item>
        <el-form-item label="口播文案">
          <el-input v-model="dh.text" type="textarea" :rows="4"
                    placeholder="输入要朗读的文字（60~90字约15秒）" />
        </el-form-item>
        <el-form-item label="标题 / 标签">
          <div style="display:flex;gap:8px;width:100%">
            <el-input v-model="dh.title" placeholder="发布标题(可空)" />
            <el-input v-model="dh.tags" placeholder="标签,逗号分隔" />
          </div>
        </el-form-item>
      </el-form>
      <div class="steps-sum">
        <div class="cap">本次将执行</div>
        <div class="step-line">
          <template v-for="(s, i) in CARD_STEPS.dh" :key="s">
            <span v-if="i" class="ar">→</span><span class="st">{{ s }}</span>
          </template>
        </div>
      </div>
      <template #footer>
        <el-button @click="dlg=''">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit('dh')">生成口播视频</el-button>
      </template>
    </el-dialog>

    <!-- ===== 视频转换弹窗 ===== -->
    <el-dialog :model-value="dlg==='vt'" title="对标视频转换（换脸/人物替换）" width="520px" @close="dlg=''">
      <el-form label-position="top">
        <el-form-item label="对标视频（要替换人物的原视频）">
          <div style="display:flex;gap:8px;width:100%">
            <el-select v-model="vt.source" style="flex:1" filterable placeholder="从素材库选">
              <el-option v-for="p in store.assets.source" :key="p" :value="p" :label="p.split('/').pop()" />
            </el-select>
            <el-button @click="$refs.vtFile.click()">上传</el-button>
            <input ref="vtFile" type="file" accept="video/*" hidden @change="vtPickVideo">
          </div>
          <video v-if="vt.source" :src="`/api/assets/file?path=${encodeURIComponent(vt.source)}`"
                 class="media-video" style="max-height:180px;margin-top:6px" muted controls />
        </el-form-item>
        <el-form-item label="目标形象图（换成这个人）">
          <div style="display:flex;gap:8px;width:100%">
            <el-select v-model="vt.face" style="flex:1" filterable placeholder="选人像参考图">
              <el-option v-for="p in [...store.assets.image, ...store.assets.garment]"
                         :key="p" :value="p" :label="p.split('/').pop()" />
            </el-select>
            <el-button @click="$refs.vtImg.click()">上传</el-button>
            <input ref="vtImg" type="file" accept="image/*" hidden @change="vtPickImage">
          </div>
          <img v-if="vt.face" :src="`/api/assets/file?path=${encodeURIComponent(vt.face)}`"
               style="max-height:140px;border-radius:8px;margin-top:6px" />
        </el-form-item>
        <el-form-item label="提示词（可空，默认按参考图替换人物）">
          <el-input v-model="vt.prompt" type="textarea" :rows="2"
                    placeholder="如：把人物换成参考图中的女性，保持讲话动作和场景" />
        </el-form-item>
        <el-form-item label="清晰度">
          <el-radio-group v-model="vt.resolution">
            <el-radio-button value="768P">768P 标准</el-radio-button>
            <el-radio-button value="480p">480p 省钱</el-radio-button>
            <el-radio-button value="2K">2K 高清</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <div class="steps-sum">
        <div class="cap">本次将执行</div>
        <div class="step-line">
          <template v-for="(s, i) in CARD_STEPS.vt" :key="s">
            <span v-if="i" class="ar">→</span><span class="st">{{ s }}</span>
          </template>
        </div>
      </div>
      <template #footer>
        <el-button @click="dlg=''">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit('vt')">开始转换</el-button>
      </template>
    </el-dialog>

    <!-- ===== 自动创作弹窗 ===== -->
    <el-dialog :model-value="dlg==='ac'" title="自动化创作" width="480px" @close="dlg=''">
      <el-form label-position="top">
        <el-form-item label="主题">
          <el-input v-model="ac.subject" placeholder="如：3个让周报更好写的 AI 技巧" />
        </el-form-item>
        <el-form-item label="自定义文案（可空，空则 DeepSeek 写稿）">
          <el-input v-model="ac.script" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="ac.title" placeholder="可空" />
        </el-form-item>
      </el-form>
      <div class="steps-sum">
        <div class="cap">本次将执行</div>
        <div class="step-line">
          <template v-for="(s, i) in CARD_STEPS.ac" :key="s">
            <span v-if="i" class="ar">→</span><span class="st">{{ s }}</span>
          </template>
        </div>
      </div>
      <template #footer>
        <el-button @click="dlg=''">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit('ac')">生成视频</el-button>
      </template>
    </el-dialog>
  </div>
</template>
