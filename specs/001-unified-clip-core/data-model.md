# Data Model: 统一剪藏核心 (Unified Clip Core)

**Date**: 2026-07-04 | **Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## 实体概览

```
ClipRecord 1──* ClippedArtifact
ClipRecord *──1 IndexEntry
ClipRecord *──1 DedupRecord
BatchReceipt 1──* BatchItem
```

## 1. ClipRecord(剪藏记录)

一次剪藏操作的完整记录,是核心聚合根。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `url` | str | 必填,主身份之一 | 输入来源(网址或文件绝对路径) |
| `type` | enum | 必填,`web`/`video`/`image`/`doc` | 剪藏类型 |
| `title` | str | 必填 | 抓取/抽取得到的标题 |
| `category` | str | 必填,7 大领域之一 | 自动分类结果 |
| `folder` | str | 必填,格式`时间戳_标题` | 归档目录名(冲突时追加`-N`) |
| `status` | enum | 必填,`ok`/`partial`/`failed` | 抓取状态(三档) |
| `source` | str | 可选,缺省回退到 `url` | 原始来源(用于回溯) |
| `content_hash` | str \| null | 文件类必填,URL类可选 | SHA1 前 16 位(辅证去重) |
| `fetch_backend` | str | **新增**(FR-012) | 实际使用的抓取后端,如 `firecrawl`/`httpx`/`playwright`/`bili-cli`/`asr:volcengine` |
| `saved_at` | str | 必填,ISO 格式 `YYYY-MM-DD HH:MM:SS` | 抓取时间戳 |
| `warnings` | list[str] | 可选 | 警告信息(面向用户) |
| `errors` | list[str] | 可选 | 错误信息(面向用户) |

**验证规则**:
- `url` 与 `content_hash` 至少一个非空
- `status=ok` 时 `warnings` 与 `errors` 均为空
- `status=partial` 时 `errors` 非空且 `warnings` 可非空
- `status=failed` 时 `errors` 非空
- `type=video` 时 `fetch_backend` 应包含视频信息获取后端(如 `bili-cli`)与字幕获取后端(如 `asr:volcengine`),以分号分隔

**状态转换**:
```
[新建] → 抓取中 → ok | partial | failed | duplicate
```
- `duplicate` 状态仅在去重命中时出现,不写入索引(FR-010 规定命中时提示用户选择)
- `failed` 时仍可生成占位 md 落盘(现有行为保留)

## 2. ClippedArtifact(剪藏产物)

一次剪藏产生的具体文件,与 ClipRecord 是一对多关系。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `path` | str | 必填,绝对路径 | 文件落盘路径 |
| `artifact_type` | enum | 必填 | `article_md`/`screenshot`/`video_md`/`image_file`/`doc_file`/`subtitle`/`cover` |
| `source_url` | str \| null | 可选 | 产物对应的原始 URL(如图片的原始 URL) |
| `extra` | dict | 可选 | 类型特定元数据(见下) |

**类型特定元数据** (`extra` 字段内容):

| artifact_type | extra 字段 | 说明 |
|---------------|-----------|------|
| `article_md` | `images_downloaded: int`, `images_failed: int` | 图片下载统计 |
| `screenshot` | `method: str` | 截图方法: `playwright`/`firecrawl` |
| `video_md` | `has_subtitle: bool`, `subtitle_source: str \| null` | 字幕来源: `official`/`asr:volcengine`/`asr:bijian`/`asr:jianying`/`null` |
| `image_file` | `original_name: str` | 原始文件名 |
| `doc_file` | `page_count: int \| null` | 页数(PDF) |

**验证规则**:
- `path` 指向的文件必须存在(除非 `status=failed`)
- `artifact_type=screenshot` 时 `extra.method` 必填

## 3. IndexEntry(索引条目)

索引文件 `_index.json` 中的一条记录,指向一个 ClipRecord。这是持久化形态(ClipRecord 是运行时形态)。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `url` | str | 必填 | 主身份(网址或文件路径) |
| `type` | str | 必填 | `web`/`video`/`image`/`doc` |
| `title` | str | 必填 | 标题 |
| `category` | str | 必填 | 领域分类 |
| `folder` | str | 必填 | 归档目录名 |
| `files` | list[str] | 必填 | 文件绝对路径列表 |
| `source` | str | 可选 | 原始来源(缺省回退到 url) |
| `status` | str | 必填 | `ok`/`partial`/`failed` |
| `content_hash` | str \| null | 可选 | 内容哈希(文件类) |
| `fetch_backend` | str | **新增** | 抓取后端(FR-012) |
| `saved_at` | str | 必填 | 抓取时间 |
| `warnings` | list[str] | 可选 | 警告 |
| `errors` | list[str] | 可选 | 错误 |

**索引文件结构**:
```json
{
  "pages": [IndexEntry, ...],
  "total": int,
  "last_updated": "YYYY-MM-DD HH:MM:SS"
}
```

**损坏恢复机制** (FR-013a):
- 读取时若 JSON 解析失败,将损坏文件重命名为 `_index.json.corrupted.{timestamp}`
- 重建空索引 `{"pages": [], "total": 0, "last_updated": "now"}`
- structlog 记录 `event=index_corrupted, backup_path=..., recovered_at=...`
- 向用户输出提示: "索引文件损坏,已备份至 {path} 并重建空索引"

## 4. DedupRecord(去重记录)

用于判重的内部记录,不直接持久化(由 IndexEntry 的 `url` 与 `content_hash` 字段支撑)。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `url_hash` | str | 必填,主身份 | 网址的规范化哈希 |
| `content_hash` | str \| null | 辅证 | 文件内容的 SHA1 前 16 位 |

**去重判定逻辑** (FR-010):
```
1. 规范化输入 URL(去除 query 参数中的追踪参数)
2. 查找索引中同 URL 的记录:
   - 无记录 → 非重复,继续剪藏
   - 有记录且 content_hash 相同 → "完全重复",提示已存在位置
   - 有记录但 content_hash 不同 → "内容已更新",提示用户选择刷新或跳过
3. 文件类输入:计算 content_hash,查找同哈希记录
   - 命中 → "完全重复",提示已存在位置
```

## 5. BatchReceipt(批量回执)

批量剪藏的汇总结果,当前仅在内存生成不落盘。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `total_count` | int | 必填 | 总输入条数 |
| `items` | list[BatchItem] | 必填 | 逐条结果 |
| `generated_at` | str | 必填 | 回执生成时间 |

### BatchItem

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `input` | str | 必填 | 原始输入(网址或文件路径) |
| `status` | enum | 必填,`ok`/`failed`/`duplicate` | 处理状态 |
| `title` | str | 可选 | 标题 |
| `category` | str | 可选 | 分类 |
| `folder` | str | 可选 | 归档位置 |
| `error` | str \| null | 失败时必填 | 失败原因 |
| `retried` | bool | **新增**(FR-011a) | 是否经过重试 |
| `source` | str | 可选 | 原始来源 |

## 6. 配置实体 (Config)

### Decision: 提取 `clipper/config.py` 单例,各模块从单例获取配置

配置分层覆盖优先级: `config.yaml`(默认) → 环境变量(密钥类) → CLI 参数(最高)

| 配置节 | 关键字段 | 说明 |
|--------|---------|------|
| `storage` | `base_dir`, `index_file` | 存储根目录与索引文件名 |
| `categories` | 7 个分类 | 领域分类列表 |
| `category_keywords` | 每分类一组关键词 | 关键词匹配分类 |
| `features` | `download_images`, `video_subtitle`, `ai_summary` | 功能开关 |
| `scraping` | `backend`(auto/local/firecrawl), `firecrawl.{api_key,...}` | 网页抓取后端 |
| `video` | `platforms: [bilibili]` | 视频平台(v1 仅 B站) |
| `asr` | `enabled`, `fallback_chain`, `videocaptioner{}`, `volcengine{}` | ASR 配置 |
| `limits` | `max_images`, `max_content_chars`, `image_timeout`, `page_fetch_timeout`, **`max_file_size_mb: 20`**(新增), **`max_video_duration_min: 15`**(新增) | 各类上限(FR-013b) |
| `screenshot` | `enabled`, `engine`, `timeout`, `user_agent`, **`full_page: true`**(新增), **`store_screenshot: true`**(新增) | 截图配置 |

**新增配置项**:
- `limits.max_file_size_mb`: 单文件大小上限(FR-013b),默认 20
- `limits.max_video_duration_min`: 视频时长上限(FR-013b),默认 15
- `screenshot.full_page`: 整页 vs 首屏(参考 Karakeep),默认 true
- `screenshot.store_screenshot`: 是否落盘归档,默认 true

## 7. 验证规则汇总

| 规则 | 来源 FR | 说明 |
|------|---------|------|
| 文件大小 ≤20MB | FR-013b | 剪藏前 `os.path.getsize()` 校验 |
| 视频时长 ≤15 分钟 | FR-013b | 从视频信息中提取 duration 校验 |
| 目录名冲突追加后缀 | FR-009a | `mkdir` 前检查存在性,追加 `-1`/`-2` |
| 索引损坏备份+重建 | FR-013a | `JSONDecodeError` 时备份并重建 |
| 批量单条失败重试 1 次 | FR-011a | 失败后自动重试,仍失败则跳过 |
| 去重区分"完全重复"与"内容已更新" | FR-010 | URL 同+哈希同=完全重复;URL 同+哈希不同=内容已更新 |
| 索引记录 fetch_backend | FR-012 | 新增字段,记录实际使用的抓取后端 |
