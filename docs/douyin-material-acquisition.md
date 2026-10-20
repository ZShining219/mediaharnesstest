# 抖音素材获取模块

> 面向 Agent 的抖音账号/关键词素材获取能力：解析账号 → 拉作品清单 → 关键词筛选 → 下载到素材库 → 写入参考视频池。

## 1. 组成

| 位置 | 作用 |
|---|---|
| `orchestrator/app/douyin_materials.py` | 业务编排：解析、列作品、筛选、下载、入参考池 |
| `services/MediaCrawler/mc_creator.py` | 浏览器适配器：操作已登录抖音会话，输出账号/作品 JSON |
| `services/MediaCrawler/mc_search.py` | 关键词搜索（已有） |
| `scripts/douyin_acquire.py` | 命令行入口，Agent 可直接调用 |
| `orchestrator/app/main.py` | HTTP API 路由 |
| `data/reference_pool.json` | 参考池索引 |

## 2. 流程

```
账号昵称 / sec_uid / 搜索词
        ↓
mc_creator.py（Playwright + 已登录 Chrome）
        ↓
作品清单（标题、播放地址、商品锚点、是否视频）
        ↓
关键词 / 排除词筛选
        ↓
materials.download() → assets/sources/
        ↓
reference_pool.add() → data/reference_pool.json
```

## 3. Python 模块

```python
from orchestrator.app import douyin_materials as dm

# 1) 解析账号
users = dm.resolve_user("都市丽人服饰内衣旗舰店")

# 2) 列作品（不下载）
lst = dm.list_user_videos(sec_uid, max_videos=100, with_details=False)

# 3) 一条龙获取
report = dm.acquire(
    account="都市丽人服饰内衣旗舰店",
    keywords=["文胸", "高开衩"],
    max_videos=20,
    download=True,
    add_to_pool=True,
    dry_run=False,
)
```

`acquire()` 参数：

| 参数 | 说明 |
|---|---|
| `account` | 账号昵称，自动解析 sec_uid |
| `sec_uid` | 已知账号 ID，优先于 account |
| `queries` | 关键词搜索模式；与 `author_filter` 组合 |
| `author_filter` | 搜索结果作者需包含该字符串 |
| `keywords` | 标题/商品名关键词，任一命中即保留 |
| `exclude_keywords` | 命中即排除 |
| `max_videos` | 本次最多处理视频数（1–200） |
| `download` | 是否下载到 `assets/sources/` |
| `add_to_pool` | 是否写入参考池 |
| `tags` | 额外参考池标签 |
| `with_details` | 逐条打开作品页补商品锚点（慢但更准） |
| `dry_run` | 只返回匹配清单，不下载、不入池 |

返回报告包含：`listed`、`matched`、`downloaded`、`existing`、`failed`、`pool_added`、`items[]`、`errors[]`。

## 4. HTTP API

### 4.1 解析账号

```http
POST /api/douyin/resolve
Content-Type: application/json

{"name": "都市丽人服饰内衣旗舰店"}
```

### 4.2 列出并筛选作品（不下载）

```http
POST /api/douyin/videos
Content-Type: application/json

{
  "account": "都市丽人服饰内衣旗舰店",
  "keywords": ["文胸", "高开衩"],
  "max_videos": 50,
  "with_details": false
}
```

### 4.3 创建素材获取任务

```http
POST /api/jobs/douyin-acquire
Content-Type: application/json

{
  "account": "都市丽人服饰内衣旗舰店",
  "keywords": ["冰丝", "三角"],
  "max_videos": 20,
  "download": true,
  "add_to_pool": true,
  "dry_run": false
}
```

返回 `{"queued": true}` 并创建 `douyin_acquire` 任务；用 `GET /api/jobs/{jid}` 轮询结果。

搜索模式：

```json
{
  "queries": ["都市丽人 文胸", "都市丽人 聚拢内衣"],
  "author_filter": "都市丽人",
  "keywords": ["文胸"],
  "max_videos": 10,
  "download": true,
  "add_to_pool": true
}
```

## 5. CLI

```bash
# 只解析账号
.venv/bin/python scripts/douyin_acquire.py \
  --resolve-name "都市丽人服饰内衣旗舰店"

# 只列清单，不下载
.venv/bin/python scripts/douyin_acquire.py \
  --account "都市丽人服饰内衣旗舰店" \
  --keywords "冰丝,三角" --max-videos 20 --dry-run

# 下载并写入参考池
.venv/bin/python scripts/douyin_acquire.py \
  --account "都市丽人服饰内衣旗舰店" \
  --keywords "冰丝,三角" --max-videos 10

# 搜索其他都市丽人账号的文胸视频
.venv/bin/python scripts/douyin_acquire.py \
  --queries "都市丽人 文胸,都市丽人 聚拢内衣" \
  --author-filter "都市丽人" --keywords "文胸" --max-videos 10
```

## 6. Agent 工具描述（可直接给函数调用型 Agent）

```json
{
  "name": "acquire_douyin_materials",
  "description": "从抖音账号或关键词获取视频素材，下载到素材库并写入参考视频池。先可用 dry_run 预览匹配清单。",
  "parameters": {
    "type": "object",
    "properties": {
      "account": {"type": "string", "description": "抖音账号昵称"},
      "sec_uid": {"type": "string", "description": "已知账号 sec_uid，优先于 account"},
      "queries": {"type": "array", "items": {"type": "string"}, "description": "关键词搜索词"},
      "author_filter": {"type": "string", "description": "搜索结果作者需包含的字符串"},
      "keywords": {"type": "array", "items": {"type": "string"}, "description": "标题/商品关键词，任一命中"},
      "exclude_keywords": {"type": "array", "items": {"type": "string"}},
      "max_videos": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
      "download": {"type": "boolean", "default": true},
      "add_to_pool": {"type": "boolean", "default": true},
      "tags": {"type": "array", "items": {"type": "string"}},
      "with_details": {"type": "boolean", "default": false},
      "dry_run": {"type": "boolean", "default": false}
    },
    "required": []
  }
}
```

## 7. 运行前提与边界

- 需要抖音登录态：`services/MediaCrawler/browser_data/douyin_user_data_dir`
- 未登录时返回 `need_login: true`；先扫码：
  - 页面：`视频转换 → 自动选材 · 批量生成 → 抖音 → 扫码登录`
  - CLI：`cd services/MediaCrawler && uv run mc_search.py --platform douyin --login`
- 抖音持久化 profile 同时只能被一个 Chrome 使用；模块内部复用 `materials._social_lock`
- `with_details=true` 会逐条打开作品页，较慢，但能拿到商品标题/价格/销量
- 图文作品（`is_video=false`）会被跳过，不会当作视频下载
- 建议小批量、控制频率；平台风控可能导致首页加载超时或需要重新登录
- 下载文件进入 `assets/sources/`，参考池记录进入 `data/reference_pool.json`
