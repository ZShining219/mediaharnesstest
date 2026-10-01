// 后端 API 封装: token 处理(ORCH_TOKEN) + 统一错误提示
const TOKEN = new URLSearchParams(location.search).get('token')
  || localStorage.getItem('orch_token') || ''
if (TOKEN) localStorage.setItem('orch_token', TOKEN)

export function withToken(u) {
  if (!TOKEN) return u
  return u + (u.includes('?') ? '&' : '?') + 'token=' + TOKEN
}

async function req(path, method = 'GET', body, isForm = false) {
  const headers = { 'X-Token': TOKEN }
  if (!isForm) headers['Content-Type'] = 'application/json'
  const r = await fetch(withToken(path), {
    method, headers,
    body: isForm ? body : (body ? JSON.stringify(body) : undefined),
  })
  let data = null
  try { data = await r.json() } catch { /* non-json */ }
  if (!r.ok) {
    const msg = (data && (data.detail || data.error)) || `HTTP ${r.status}`
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return data
}

export const api = {
  get: (p) => req(p),
  post: (p, b) => req(p, 'POST', b || {}),
  del: (p) => req(p, 'DELETE'),
  upload: (file, kind, extra = '') => {
    const fd = new FormData()
    fd.append('file', file)
    return req(`/api/upload?kind=${kind}${extra}`, 'POST', fd, true)
  },
}

export const assetUrl = (p) => withToken('/api/assets/file?path=' + encodeURIComponent(p))
export const mediaUrl = (id) => withToken('/media/' + id)

export const fmtTime = (ts) => ts ? new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false }) : '-'

export const JOB_TYPES = {
  digital_human: '数字人口播', video_transform: '视频转换', auto_content: '自动创作',
  graph: '节点画布', 'cron:digital_human': '定时·数字人', 'cron:video_transform': '定时·视频转换',
  'cron:auto_content': '定时·自动创作', 'cron:publish_approved': '定时·发布',
}
export const jobTypeName = (t) => JOB_TYPES[t] || t

export const STATUS_TAG = {
  running: { type: 'warning', label: '运行中' },
  done: { type: 'success', label: '完成' },
  error: { type: 'danger', label: '失败' },
  interrupted: { type: 'info', label: '已中断' },
  queued: { type: 'info', label: '排队中' },
}
