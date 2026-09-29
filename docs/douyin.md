# 抖音自动发布配置

使用 social-auto-upload (sau)，Playwright + cookie 方案，支持定时发布。
不采用抖音开放平台 API —— 个人开发者无发布视频权限（需企业认证）。

## 首次登录 (需人工操作一次)

```bash
cd services/social-auto-upload
.venv/bin/sau douyin login --account main
```

会弹出浏览器/二维码，用抖音 App 扫码登录创作者中心。
登录态(cookie)存在 `cookies/` 下，之后非交互使用。

如登录态失效或二维码异常:

```bash
# 浏览器手动登录 https://creator.douyin.com 后导出 cookie:
bash export_douyin_cookie.sh --account main
.venv/bin/sau douyin check --account main   # 验证 cookie 有效性
```

## 手动发布

```bash
.venv/bin/sau douyin upload-video --account main \
  --file outputs/approved/xxx.mp4 \
  --title "标题" --desc "简介 #话题" \
  --tags tag1,tag2 \
  --schedule "2026-10-01 21:30"   # 可选: 定时发布
```

## 编排器内自动发布

- 审核页"通过"时可勾"发布"/填定时 → approved 队列
- 定时任务 `publish_approved` (config.yaml) 每晚 21:00 自动发布 approved 队列
- `auto_after_approve: true` + `auto_schedule: "now"` = 审核通过立即发

## 其他平台

sau 同套 CLI 支持: 小红书 `xiaohongshu`、B站 `bilibili`、快手 `kuaishou`、
视频号、百家号、TikTok、YouTube。审核页发布时下拉选平台即可（目前 UI 默认 douyin，
可多平台扩展）。
