---
name: clip_collection
description: 剪藏并用。当使用者在对话里分享网页链接、B 站视频链接、图片（一张或多张）、PDF 或 Word 文档，并附带"收藏一下 / 剪藏这个 / 存一下 / 帮我归档"等剪藏意图时触发：自动判定来源类型、抓取或抽取内容、按领域分类存到本地、生成索引、回执。支持 /skip 跳过本次、/move 跨领域移动、已剪链接去重提醒与 --force 覆盖、抓取失败的占位 md、多链接/多文件批处理与汇总回执。识图（OCR/描述）由 agent 自身视觉能力完成。
---

# 剪藏 (Clip Collection)

把使用者分享的网页、视频、图片、文档剪藏到本机普通文件夹，按领域自动分类、可查重、可移动、可追溯原始来源。

## 触发条件

当使用者**分享内容并附带剪藏意图**时触发剪藏。识别意图，不用背命令：

- 剪藏意图话术：**"收藏一下 / 剪藏这个 / 存一下 / 帮我归档 / 存一下这个"** 等。
- 分享类型（任一即可触发）：
  - 网页链接（http/https，含公众号文章）
  - B 站视频链接（`bilibili.com/video/`、`b23.tv`、`bilibili.com/bangumi/play/`）
  - **图片**（一张或多张；本地或微信下载均可）
  - **PDF / Word 文档**（.pdf / .docx）
- 多链接 / 多文件 / 混合也可一次性剪藏（自动批处理 + 汇总回执）。
- **无明确剪藏意图的内容不触发**（避免误伤日常对话）。常见聊天里只是发个链接没有"保存"含义时，应当先确认再剪藏。

## 命令话术

- `/skip` 或"这次不用剪藏 / 先不存 / 跳过"：**本次不剪藏**，仅简单回"已跳过"，不调用 `clip.py`。
- `/move <目标领域>` 或"把刚才那个挪到 XX 领域"：跨领域移动已剪条目（md + 资源 + 更新索引）。
- `/skip` ≠ 撤销：跳过是当场不剪，不涉及已存条目删除。

## 使用方式

### 网页 / B站视频 剪藏

```bash
python clip.py "<URL>"                       # 单链接
python clip.py "<URL1>" "<URL2>" ...         # 多链接批处理
python clip.py "<URL>" --no-images           # 不下载网页图片
python clip.py "<URL>" --force               # 已剪过→覆盖重剪
```

### 图片剪藏

```bash
python clip.py --image "/path/a.png"                     # 单张
python clip.py --image a.png --image b.jpg               # 多张合并为一条
```

剪藏后 md 中每张图位置留有占位 `<!-- agent-describe: ... -->`。
**由你（clawbot）用自身视觉能力读图**，把 OCR 识别的文字与一句话描述填进 md 对应位置。

### PDF / Word 剪藏

```bash
python clip.py --doc "/path/report.pdf"
python clip.py --doc report.pdf --doc notes.docx
```

### 其它命令

```bash
python clip.py --search "<关键词>"    # 搜索已保存内容
python clip.py --stats                 # 统计信息
python clip.py --list [分类]           # 列出内容（可选分类）
python clip.py --reclassify "<时间戳_标题>" --to "<分类名>"   # /move 实现
python clip.py --add-category "<分类名>" --keywords "关键词1,关键词2"
python clip.py --replace "<旧分类>" --to "<新分类>"          # 替换分类
```

## 领域分类与建议新建流程

- 默认领域（首次运行自动创建）：科技与AI / 财经与商业 / 游戏与文化 / 阅读与思考 / 工具与技巧 / 视频与影音 / 其他收藏（兜底）。
- 每次剪藏 AI 按内容判定领域（网页/B站按标题+简介；文档按文件名+正文首段；图片按文件名）。
- 内容明显不属于现有领域、且剪藏结果落在"其他收藏"时，`clip.py` 会回执 `needs_suggestion`。
  - **此时你应先在微信询问使用者"是否新建'XX'领域？"**
  - **经使用者确认后**再执行 `--add-category` 建夹并把条目归入新领域。**未经确认不擅自建夹。**
- 领域硬上限 **6 个**（不含兜底"其他收藏"）。到上限时不再新建，提示用户用 `--replace` 替换一个旧领域后再移动。

## /move 流程

- 使用者说"把刚才那个挪到设计领域"或 `/move 设计`。
- 你解析出目标领域与要移动的条目（最近一条由当前对话/上下文获取，或让用户在索引里指出 `时间戳_标题`）后执行：

```bash
python clip.py --reclassify "<时间戳_标题>" --to "<领域>"
```

- 目标领域不存在会先创建（若未触硬上限）；移动后索引 `category` 字段同步更新并落盘。

## 去重 / 已剪藏提醒

- 链接类按原始 URL 查重；文件类（图片/PDF/Word）按内容哈希查重。
- 命中已剪：`clip.py` 不重复保存，回执"已于 YYYY-MM-DD 剪藏，标题/领域/路径"，并给出 `--force` 覆盖命令。
- 使用者口语确认"重新覆盖"后，你执行 `python clip.py "<URL>" --force` 删除旧条目与目录并重剪。

## 失败占位

- 抓取/字幕获取/正文抽取失败时，仍生成一条占位 md：头部标"抓取状态：失败/部分失败"，正文写失败原因 + 已获取信息，并保留原始来源。
- 单条失败不中断批处理其余条目。
- 公众号图片（mmbiz/qpic 等防盗链域名）：微信文章页内带文章 Referer 下载并本地化；非微信页面本地化失败时，保留远程 URL，不丢弃图片引用。

## 回执

- 单条剪藏：标题 / 类型 / 领域 / 保存路径 / 原始链接。
- 批处理：先逐条回执，最后一张汇总表（类型 | 标题 | 领域 | 状态 | 链接/文件），避免微信刷屏。

## 存储结构

```
clipped_pages/
└── {分类}/
    └── {时间戳_标题}/
        ├── article.md       # 网页正文 Markdown（含图片/长截图）
        ├── screenshot.png   # 网页长截图（Firecrawl 生效时）
        ├── image.md         # 图片剪藏
        ├── video.md         # B站视频（标题/简介/字幕/封面 cover.*）
        └── doc.md           # PDF/Word 抽取正文（原文件存档同目录）
clippings 索引：_index.json（条目：url/type/title/category/folder/source/status/...）
```

## 抓取后端与防盗链

- `config.yaml` 中 `scraping.backend`：`auto`（默认）= 有 Firecrawl key 先用 Firecrawl（非微信链接），失败再回退本地 httpx；无 key 全走本地。
- **微信公众号文章优先本地 httpx**：mp.weixin 正文是服务端直出（`<div id="js_content">`），本地 httpx 即可拿全正文；Firecrawl 对 mp.weixin 常误判验证码/付费墙返回空，故 auto 模式下微信链接绕过 Firecrawl 直接走本地。
- **微信正文图懒加载**：公众号正文图普遍用 `data-src` 而非 `src`，抓取后会先把 `data-src` 归一化到 `src`，html2text 才能 render 进 md，否则 md 里一张图都看不到。
- **mp 图防盗链本地化**：mmbiz/qpic 图离开 `mp.weixin.qq.com` Referer 立刻 403。本 skill 对微信文章页放开 `unsupported_image_domains` 黑名单（不为这些域名放弃下载），改为带文章页 Referer 下载；非微信页面仍按黑名单保留远程 URL。
- 本地 httpx 带浏览器特征头（UA/Referer/Sec-Fetch）+ Cookie 复用，应对轻度反爬；图片下载走 原页 URL→origin Referer 重试，仍失败则保留远程 URL。
- Firecrawl 返回正文空但有长截图时，按"部分失败"保存截图并写占位 md。

## 整页长截图

每条网页（公众号/通用网页）剪藏除 article.md 外，**额外保存一张整页长截图** `screenshot.png` 到条目目录，并在 md 头部插入 `![长截图](screenshot.png)` 引用（需求 §5.1）。

- `config.yaml` 中 `screenshot.engine`：
  - `auto`（默认）：**Playwright headless chromium 优先**，失败/未装时回退 Firecrawl `screenshot@fullPage`。
  - `playwright`：仅本地 Playwright（失败也认，不回退）。
  - `firecrawl`：仅云端 Firecrawl 整页截图（NAS 未装 Playwright 时的纯云端模式，零本地依赖）。
  - `off`：关闭截图。`screenshot.enabled: false` 同效。
- Playwright 用 **headless chromium**（无显示器容器/NAS 可跑），不依赖桌面浏览器。
- **NAS/Linux 容器安装**（首次）：
  ```bash
  pip install playwright
  playwright install --with-deps chromium   # 自动 apt 装系统库 + 下 chromium
  ```
  装不上的环境自动回退 Firecrawl；不想本地装库可设 `screenshot.engine: firecrawl`。
- 截图失败一律降级为 warning（回执里提示"长截图失败，已跳过"），**绝不阻断正文剪藏**。
- 超长页面整页截图偶发被浏览器分块/超时，可调 `screenshot.timeout`。

## 配置

编辑 `config.yaml`：

```yaml
scraping:
  backend: "auto"            # auto=有Key用Firecrawl并失败回退本地；local=仅本地
  firecrawl:
    api_key: "fc-xxx"        # 可选
features:
  download_images: true
  video_subtitle: true
unsupported_image_domains:   # 这些域名的图片在【非微信文章页】上放弃本地化、保留远程 URL；
                             # 微信文章页内会带 mp Referer 尝试下载，不受此黑名单
  - mmbiz
  - qpic.cn
  - weixin
```

## 依赖

```bash
pip install httpx html2text pyyaml firecrawl-py
pip install python-docx pypdf               # 文档剪藏
pip install playwright && playwright install --with-deps chromium   # 整页长截图（NAS/Linux 容器）；不装则回退 Firecrawl
pipx install bilibili-cli && bili login    # B站视频（扫码登录）
```

## 本地性与隐私

- 原文不主动上传第三方服务；Firecrawl 仅用于公开网页抓取，AI 总结/OCR 由 clawbot agent 自身能力完成。
- 每条剪藏必有原始来源与日期，确保可追溯。