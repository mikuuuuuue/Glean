# 剪藏 Clip Collection

把分享的网页、视频、图片、文档剪藏到本地，按领域自动分类、可查重、可移动、可追溯原始来源。

## 功能

- 网页剪藏：抓取正文转 Markdown，下载图片，整页长截图
- B站视频：获取视频信息、字幕、封面
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
        ├── video.md         # B站视频信息
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
    ├── categorizer.py    # 分类器
    ├── doc.py            # PDF/Word 处理
    ├── image.py          # 图片处理
    ├── indexer.py        # 索引管理
    ├── screenshot.py     # 整页截图
    ├── video.py          # B站视频处理
    └── web.py            # 网页抓取
```

## 依赖

- httpx - HTTP 客户端
- html2text - HTML 转 Markdown
- pyyaml - YAML 配置解析
- firecrawl-py - Firecrawl 网页抓取
- python-docx - Word 文档解析
- pypdf - PDF 解析
- playwright - 整页长截图

## 许可证

MIT
