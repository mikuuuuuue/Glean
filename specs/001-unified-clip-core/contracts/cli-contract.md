# CLI Contract: 统一剪藏核心 (Unified Clip Core)

**Date**: 2026-07-04 | **Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

本文件定义 GLEAN CLI 对外暴露的命令与参数契约。GLEAN 是命令行工具,这是其唯一的对外接口。

## 命令总览

```
clip.py <url> [<url> ...]              # 网页/视频剪藏(支持批处理)
clip.py --image <path> [--image ...]  # 图片剪藏
clip.py --doc <path> [--doc ...]       # PDF/Word 剪藏
clip.py --search <keyword>             # 搜索已剪藏内容
clip.py --stats                        # 统计信息
clip.py --list [category]              # 列出内容
clip.py --reclassify <folder> --to <cat>  # 重新分类
clip.py --add-category <name> --keywords <kw>  # 新增分类
clip.py --replace <old> --to <new>     # 替换分类
```

## 剪藏命令

### URL 剪藏

```
clip.py <url> [<url> ...] [options]
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `url` | positional, nargs=* | 必填 | 一个或多个网址 |
| `--no-images` | flag | False | 不下载网页图片 |
| `--no-video` | flag | False | 不处理视频 |
| `--force` | flag | False | 跳过查重,覆盖原条目后重剪 |

**行为契约**:
- 自动识别 URL 类型: B站视频网址 → 视频剪藏;其他网址 → 网页剪藏
- 多 URL 时串行处理,完成后输出汇总回执
- 去重命中时(非 `--force`):提示已存在位置;若内容哈希不同则标注"内容已更新"并询问刷新或跳过
- 单条失败自动重试 1 次,仍失败则跳过并继续后续条目
- 输出格式: 每条结果格式化文本 + 批处理时追加汇总表

**退出码**:
- `0`: 至少一条成功(`ok` 或 `partial`)
- `1`: 全部失败

### 文件剪藏

```
clip.py --image <path> [--image ...] [--doc <path> [--doc ...]] [options]
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--image` | append | 可多次 | 图片文件路径 |
| `--doc` | append | 可多次 | PDF/Word 文件路径 |
| `--force` | flag | False | 跳过查重,覆盖原条目 |

**行为契约**:
- 按后缀自动识别: `.png/.jpg/.jpeg/.gif/.webp/.bmp/.svg` → 图片; `.pdf/.docx` → 文档
- 不支持的类型: 输出错误提示,不产生归档
- 文件大小 >20MB: 拒绝并输出提示(FR-013b)
- 多文件时串行处理,输出汇总回执

**退出码**:
- `0`: 至少一条成功
- `1`: 全部失败

## 查询命令

### 搜索

```
clip.py --search <keyword>
```

**输出格式**:
```
🔍 搜索 '<keyword>' 的结果 (N 条):

  📌 <title>
     🔗 <url>
     📁 <category> | 🕐 <saved_at>
```

无结果时输出: `🔍 未找到与 '<keyword>' 相关的内容`

### 统计

```
clip.py --stats
```

**输出格式**:
```
📊 剪藏统计
   总计: N 条
   最后更新: YYYY-MM-DD HH:MM:SS
   分类分布:
     - <category1>: <count>
     - <category2>: <count>
```

### 列表

```
clip.py --list [category]
```

- 无参数或 `all`: 列出全部内容
- 指定分类名: 仅列出该分类内容

**输出格式**: 同搜索结果格式

## 分类管理命令

### 新增分类

```
clip.py --add-category <name> --keywords <kw1,kw2>
```

**约束**:
- 分类上限 6 个(不含"其他收藏")
- 达到上限时提示先 `--replace` 替换旧分类

### 替换分类

```
clip.py --replace <old_category> --to <new_category> [--keywords <kw1,kw2>]
```

**行为**: 替换分类名与关键词,移动文件,更新索引。"其他收藏"不可替换。

### 重新分类

```
clip.py --reclassify <folder_name> --to <category>
```

**行为**: 将指定文件夹移动到目标分类,更新索引。若目标分类不存在则自动创建(受 6 上限约束)。

## 输出格式契约

### 单条结果格式

```
## 📎 剪藏结果: <title>

### ✅ 成功
- 📄 文章已保存 (N 张图片)
- 🖼️ 长截图已保存
- 📺 视频信息已保存 (官方字幕)
- 🖼️ 图片已保存 (N 张原图)
- 📑 文档已保存

### ⚠️ 警告
- <warning detail>

### ❌ 错误
- <error detail>

📁 分类: **<category>**
📂 路径: `<folder_path>`
🔗 原始链接: <url>
```

### 去重提示格式

```
## ♻️ 已剪藏过: <title>

- 📅 之前剪藏时间: <saved_at>
- 📁 当时分类: **<category>**
- 📂 路径: `<folder_path>`
- 🔗 原始链接: <url>

如需重新覆盖,请确认后重试并带 --force:
python clip.py "<url>" --force
```

### 批量汇总格式

```
## 📦 批处理汇总

共 N 条:

| 类型 | 标题 | 领域 | 状态 | 链接/文件 |
|------|------|------|------|-----------|
| web  | <title> | <category> | ✅ | <source> |
| video | <title> | <category> | ⚠️ | <source> |
| image | <title> | <category> | ❌ | <source> |
| doc  | <title> | <category> | ♻️ | <source> |
```

状态图标: `✅` ok | `⚠️` partial | `❌` failed/error | `♻️` duplicate

## 配置契约

配置文件 `config.yaml`(从 `config.example.yaml` 复制),详见 [data-model.md](data-model.md) 第 6 节。

**关键配置项**:

| 配置路径 | 类型 | 默认 | 说明 |
|---------|------|------|------|
| `scraping.backend` | str | `auto` | `auto`/`local`/`firecrawl` |
| `scraping.firecrawl.api_key` | str | "" | Firecrawl API Key |
| `screenshot.engine` | str | `auto` | `auto`/`playwright`/`firecrawl`/`off` |
| `screenshot.enabled` | bool | true | 截图总开关 |
| `screenshot.full_page` | bool | true | 整页 vs 首屏(新增) |
| `features.download_images` | bool | true | 是否下载网页图片 |
| `features.video_subtitle` | bool | true | 是否获取视频字幕 |
| `asr.enabled` | bool | false | ASR 开关 |
| `asr.fallback_chain` | list | `["videocaptioner:bijian", "videocaptioner:jianying", "volcengine"]` | ASR 回退链 |
| `limits.max_file_size_mb` | int | 20 | 单文件大小上限(新增,FR-013b) |
| `limits.max_video_duration_min` | int | 15 | 视频时长上限(新增,FR-013b) |
