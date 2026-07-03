# 剪藏-GLEAN

剪藏skill，把分享的网页、视频、图片、文档剪藏到本地，按领域自动分类、可查重、可移动、可追溯原始来源。
建议搭配各类claw使用，在Astrbot中运行正常，其他环境请自测。


## 功能

- 网页剪藏：抓取正文转 Markdown，下载图片，整页长截图
- B站视频：获取视频信息、字幕、封面；无字幕时自动 ASR 转写（必剪/剪映/火山引擎分级回退）
- 图片剪藏：原图存档，支持多张合并
- PDF/Word 文档：正文抽取，原文件存档
- 自动分类：按内容关键词匹配 7 大领域
- 去重提醒：URL 查重 + 文件内容哈希查重
- 批处理：多链接/多文件一次性剪藏，汇总回执

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置文件并填入你的 API Key
cp config.example.yaml config.yaml

# 整页长截图（可选，NAS/Linux 容器）
pip install playwright
playwright install --with-deps chromium

# 剪藏网页
python clip.py "https://example.com"

# 剪藏 B站视频
python clip.py "https://www.bilibili.com/video/BVxxxxx"

# 剪藏图片
python clip.py --image /path/to/image.png

# 剪藏 PDF/Word
python clip.py --doc /path/to/report.pdf

# 多链接批处理
python clip.py "https://url1.com" "https://url2.com"

# 搜索已保存内容
python clip.py --search "关键词"

# 统计信息
python clip.py --stats
```

## 配置

编辑 `config.yaml`（从 `config.example.yaml` 复制）：

| 配置项 | 说明 |
|--------|------|
| `scraping.backend` | `auto`（Firecrawl 优先，失败回退本地）/ `local`（仅本地） |
| `scraping.firecrawl.api_key` | Firecrawl API Key |
| `screenshot.engine` | `auto`（Playwright 优先）/ `playwright` / `firecrawl` / `off` |
| `features.download_images` | 是否下载网页图片 |
| `features.video_subtitle` | 是否获取视频字幕 |

## 存储结构

```
clipped_pages/
└── {分类}/
    └── {时间戳_标题}/
        ├── article.md       # 网页正文 Markdown
        ├── screenshot.png   # 整页长截图
        ├── image.md         # 图片剪藏
        ├── video.md         # B站视频信息+字幕
        ├── transcript.txt   # ASR 转写文本（无官方字幕时）
        └── doc.md           # PDF/Word 正文
```

索引文件：`clipped_pages/_index.json`

## 项目结构

```
.
├── clip.py              # 主入口脚本
├── config.yaml          # 配置文件（需自行创建，勿上传）
├── config.example.yaml  # 配置模板
├── requirements.txt     # Python 依赖
├── SKILL.md             # Skill 详细文档
└── clipper/             # 核心模块
    ├── __init__.py
    ├── asr.py            # ASR 分级回退（VideoCaptioner + 火山引擎）
    ├── categorizer.py    # 分类器
    ├── doc.py            # PDF/Word 处理
    ├── image.py          # 图片处理
    ├── indexer.py        # 索引管理
    ├── screenshot.py     # 整页截图
    ├── video.py          # B站视频处理
    └── web.py            # 网页抓取
```

## 依赖

### Python 库

| 库 | 用途 |
|----|------|
| [httpx](https://github.com/encode/httpx) | HTTP 客户端 |
| [html2text](https://github.com/Alir3z4/html2text) | HTML 转 Markdown |
| [pyyaml](https://github.com/yaml/pyyaml) | YAML 配置解析 |
| [firecrawl-py](https://github.com/mendableai/firecrawl) | Firecrawl 网页抓取 |
| [python-docx](https://github.com/python-openxml/python-docx) | Word 文档解析 |
| [pypdf](https://github.com/py-pdf/pypdf) | PDF 解析 |
| [playwright](https://github.com/microsoft/playwright) | 整页长截图 |
| [videocaptioner](https://github.com/WEIFENG2333/VideoCaptioner) | ASR 语音转写（必剪/剪映引擎） |
| [bilibili-cli](https://github.com/jackwener/bilibili-cli) | B站视频信息、字幕、音频下载 |

### 外部工具

- [bili-cli](https://github.com/jackwener/bilibili-cli) — B站 CLI，获取视频信息/字幕/音频（需 `pipx install "bilibili-cli[audio]"` 启用音频）
- [VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner) — 视频字幕工具，提供免费的必剪/剪映 ASR 引擎
- [Firecrawl](https://github.com/mendableai/firecrawl) — 网页抓取与截图服务（需 API Key）
- [Playwright](https://github.com/microsoft/playwright) — 浏览器自动化，用于整页长截图
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube 视频下载（预留支持）

## 致谢

本项目依赖以下开源项目，感谢它们的作者：

- [bilibili-cli](https://github.com/jackwener/bilibili-cli) — B站命令行工具，提供视频信息获取、字幕提取、音频下载能力
- [VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner) — 视频字幕生成工具，提供免费的必剪/剪映 ASR 转写引擎
- [Firecrawl](https://github.com/mendableai/firecrawl) — 网页抓取 API，将网页转为干净的 Markdown
- [Playwright](https://github.com/microsoft/playwright) — 浏览器自动化框架，用于生成整页长截图
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — 视频下载命令行工具（YouTube 支持预留）
- [httpx](https://github.com/encode/httpx) — 异步 HTTP 客户端
- [html2text](https://github.com/Alir3z4/html2text) — HTML 转 Markdown 转换器
- [python-docx](https://github.com/python-openxml/python-docx) — Word 文档解析库
- [pypdf](https://github.com/py-pdf/pypdf) — PDF 文档解析库

## 许可证

MIT
