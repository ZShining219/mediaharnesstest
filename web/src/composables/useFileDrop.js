// 可复用的文件拖拽上传: 过滤类型 + 拖入态 + 多文件
// 用法:
//   const { dragging, dropProps } = useFileDrop({ accept: ['video/*'], onFiles })
//   <div v-on="dropProps" :class="{ 'drop-active': dragging }">...</div>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

export function useFileDrop({ accept = [], multiple = true, onFiles, disabled = false } = {}) {
  const dragging = ref(false)
  let depth = 0

  function acceptList() {
    const a = typeof accept === 'function' ? accept() : accept
    if (!a) return []
    return Array.isArray(a) ? a : String(a).split(',').map(x => x.trim()).filter(Boolean)
  }

  function matches(file) {
    const list = acceptList()
    if (!list.length) return true
    const type = file.type || ''
    const name = (file.name || '').toLowerCase()
    return list.some(a => {
      const rule = a.toLowerCase()
      if (rule.includes('/')) {
        if (rule.endsWith('/*')) return type.startsWith(rule.slice(0, -1))
        return type === rule
      }
      return name.endsWith(rule)
    })
  }

  function onDragenter(ev) {
    if (disabled) return
    ev.preventDefault()
    ev.stopPropagation()
    depth += 1
    dragging.value = true
  }

  function onDragover(ev) {
    if (disabled) return
    ev.preventDefault()
    ev.stopPropagation()
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy'
  }

  function onDragleave(ev) {
    if (disabled) return
    ev.preventDefault()
    ev.stopPropagation()
    depth = Math.max(0, depth - 1)
    if (!depth) dragging.value = false
  }

  async function onDrop(ev) {
    if (disabled) return
    ev.preventDefault()
    ev.stopPropagation()
    depth = 0
    dragging.value = false
    const files = [...(ev.dataTransfer?.files || [])]
    if (!files.length) return
    const accepted = files.filter(matches)
    const ignored = files.length - accepted.length
    if (ignored) ElMessage.warning(`已忽略 ${ignored} 个不支持的文件`)
    if (accepted.length) {
      await onFiles(multiple ? accepted : accepted.slice(0, 1))
    }
  }

  return {
    dragging,
    // v-on="obj" 的 key 用事件名(不带 on), 由 Vue 转成 onDragenter 等
    dropProps: { dragenter: onDragenter, dragover: onDragover, dragleave: onDragleave, drop: onDrop },
  }
}
