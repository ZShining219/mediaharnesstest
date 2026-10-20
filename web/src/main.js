import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
import App from './App.vue'
import './styles.css'

import Studio from './views/Studio.vue'
import Transform from './views/Transform.vue'
import ReferencePool from './views/ReferencePool.vue'
import Fission from './views/Fission.vue'
import ProductVideo from './views/ProductVideo.vue'
import Canvas from './views/Canvas.vue'
import Assets from './views/Assets.vue'
import Jobs from './views/Jobs.vue'
import Review from './views/Review.vue'
import Gallery from './views/Gallery.vue'
import Schedules from './views/Schedules.vue'
import Status from './views/Status.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'studio', component: Studio, meta: { title: '工作台' } },
    { path: '/transform', name: 'transform', component: Transform, meta: { title: '视频转换' } },
    { path: '/reference-pool', name: 'reference-pool', component: ReferencePool, meta: { title: '参考视频池' } },
    { path: '/fission', name: 'fission', component: Fission, meta: { title: '裂变素材' } },
    { path: '/product-video', name: 'product-video', component: ProductVideo, meta: { title: '带货视频' } },
    { path: '/canvas', name: 'canvas', component: Canvas, meta: { title: '节点画布' } },
    { path: '/jobs', name: 'jobs', component: Jobs, meta: { title: '任务中心' } },
    { path: '/review', name: 'review', component: Review, meta: { title: '审核队列' } },
    { path: '/gallery', name: 'gallery', component: Gallery, meta: { title: '成果展示' } },
    { path: '/assets', name: 'assets', component: Assets, meta: { title: '素材库' } },
    { path: '/schedules', name: 'schedules', component: Schedules, meta: { title: '定时发布' } },
    { path: '/status', name: 'status', component: Status, meta: { title: '系统状态' } },
  ],
})

createApp(App)
  .use(router)
  .use(ElementPlus, { locale: zhCn })
  .mount('#app')
