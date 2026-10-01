// 轻量共享状态: 素材列表 / 角色列表 (各页 + 画布节点共用)
import { reactive } from 'vue'
import { api } from './api'

export const store = reactive({
  assets: { source: [], garment: [], voice: [], image: [], bgm: [], characters: [] },
  characters: [],
  nodeSchema: [],
  loaded: false,
})

export async function refreshMeta(force = false) {
  if (store.loaded && !force) return
  const [a, c, n] = await Promise.all([
    api.get('/api/assets'), api.get('/api/characters'), api.get('/api/nodes'),
  ])
  store.assets = a
  store.characters = c
  store.nodeSchema = n
  store.loaded = true
}

// asset:<group> 参数对应的素材分组
export const ASSET_GROUPS = {
  video: ['source'], image: ['image', 'garment'], audio: ['voice', 'bgm'],
}
export function assetValues(group) {
  return (ASSET_GROUPS[group] || []).flatMap(k => store.assets[k] || [])
}
export function groupUploadKind(group) {
  return { video: 'source', image: 'image', audio: 'voice' }[group] || 'image'
}
