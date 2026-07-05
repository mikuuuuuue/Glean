# Quickstart: 统一剪藏核心 (Unified Clip Core)

**Date**: 2026-07-04 | **Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

本文件提供端到端验证指南,用于证明统一剪藏核心功能按规格工作。包含前置准备、运行命令与预期结果。

## 前置准备

### 1. 安装依赖

```bash
# 核心依赖
pip install -r requirements.txt

# 测试依赖(新增)
pip install -r requirements-tests.txt

# 整页截图(可选,推荐)
pip install playwright
playwright install --with-deps chromium

# B站视频(可选,通过 pipx)
pipx install "bilibili-cli[audio]"

# ASR 转写(可选)
pip install videocaptioner
```

### 2. 配置文件

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`,填入必要的 API Key:
- `scraping.firecrawl.api_key`: Firecrawl API Key(留空则自动走本地 httpx)
- `asr.volcengine.token`: 火山引擎 Token(留空则跳过该级 ASR)
- `limits.max_file_size_mb`: 确认为 20(FR-013b)
- `limits.max_video_duration_min`: 确认为 15(FR-013b)

### 3. 运行测试套件

```bash
# 全部测试(含覆盖率)
pytest --cov=clipper --cov-report=term-missing

# 仅单元测试(毫秒级)
pytest tests/unit/ -v

# 仅集成测试(需 tmp_path,无网络)
pytest tests/integration/ -v

# 仅契约测试(验证外部 API 结构)
pytest tests/contract/ -v
```

**预期**: 全部测试通过,`clipper/` 覆盖率 ≥80%(宪法质量标准)。

## 验证场景

以下场景按 spec.md 的 User Story 顺序组织,每个场景可独立验证。

### 场景 1: 网页剪藏 (P1)

**对应**: User Story 1, FR-001/002/003/009/012

```bash
python clip.py "https://example.com"
```

**预期结果**:
- 输出 `## 📎 剪藏结果: Example Domain`
- `clipped_pages/<分类>/<时间戳>_Example Domain/` 目录存在
- 目录含 `article.md`(正文 Markdown)
- 目录含 `screenshot.png`(整页截图,因 `screenshot.enabled` 默认 true)
- `clipped_pages/_index.json` 新增一条记录,含 `url`、`saved_at`、`fetch_backend` 字段

### 场景 2: 网页去重(完全重复)

**对应**: FR-010, User Story 1 接受场景 3

```bash
# 先剪藏一次
python clip.py "https://example.com"

# 再次剪藏同一 URL
python clip.py "https://example.com"
```

**预期结果**:
- 第二次输出 `## ♻️ 已剪藏过: Example Domain`
- 提示已存在的归档位置
- 不产生新的归档目录
- 不修改索引

### 场景 3: 网页去重(内容已更新)

**对应**: FR-010(澄清项), User Story 1

```bash
# 先剪藏一次(内容版本 A)
python clip.py "https://example.com"

# 假设网页内容已更新,再次剪藏
python clip.py "https://example.com"
```

**预期结果**:
- 第二次识别为"内容已更新"(URL 相同但内容哈希不同)
- 提示用户选择"刷新归档"或"跳过"
- 不直接覆盖(除非用户选择刷新或带 `--force`)

### 场景 4: 网页截图关闭

**对应**: FR-003(澄清项)

在 `config.yaml` 中设置:
```yaml
screenshot:
  enabled: false
```

```bash
python clip.py "https://example.com"
```

**预期结果**:
- 仍生成 `article.md` 与内嵌图片
- 不生成 `screenshot.png`
- 索引记录的 `fetch_backend` 不含 `playwright`

### 场景 5: 视频剪藏(B站,含官方字幕)

**对应**: User Story 2, FR-004/005/012

```bash
python clip.py "https://www.bilibili.com/video/BV1xx411c7mD"
```

**预期结果**:
- 输出 `## 📎 剪藏结果: <视频标题>`
- 目录含 `video.md`(视频信息)、`transcript.txt`(字幕)、封面图片
- `video.md` 标注字幕来源为"官方字幕"
- 不触发 ASR 转写
- 索引 `fetch_backend` 含 `bili-cli`

### 场景 6: 视频剪藏(无字幕,ASR 回退)

**对应**: FR-004/005/006, User Story 2 接受场景 2/3

确保 `config.yaml` 中 `asr.enabled: true`:
```bash
python clip.py "https://www.bilibili.com/video/<无字幕视频BV号>"
```

**预期结果**:
- ASR 回退链逐级尝试(bijian → jianying → volcengine)
- 成功时:`transcript.txt` 存在,`video.md` 标注 `asr:<引擎名>`
- 全部失败时:仍归档视频信息与封面,`video.md` 标注字幕缺失
- 日志(structlog)记录每级回退的引擎名与成功/失败状态

### 场景 7: 图片剪藏

**对应**: User Story 3, FR-007

```bash
python clip.py --image /path/to/image1.png --image /path/to/image2.jpg
```

**预期结果**:
- 两张图片合并归档于同一目录
- 目录含 `image.md` 与原图文件(命名 `1-image1.png`、`2-image2.jpg`)
- 索引新增一条记录,`type=image`

### 场景 8: 文档剪藏

**对应**: User Story 4, FR-008

```bash
python clip.py --doc /path/to/report.pdf
```

**预期结果**:
- 目录含 `doc.md`(抽取的正文)与原文件 `report.pdf`
- 索引新增一条记录,`type=doc`,含 `content_hash`

### 场景 9: 文件大小校验

**对应**: FR-013b

```bash
# 创建一个 >20MB 的文件
python clip.py --doc /path/to/large_file.pdf
```

**预期结果**:
- 输出明确的拒绝提示:文件超过 20MB 上限
- 不进入抓取或转写流程
- 不产生归档目录

### 场景 10: 批量剪藏与汇总回执

**对应**: User Story 5, FR-011/011a

```bash
python clip.py "https://example.com" "https://www.bilibili.com/video/BV1xx411c7mD" --image /path/to/image.png
```

**预期结果**:
- 依次处理每条输入
- 每条输出独立结果
- 最后输出 `## 📦 批处理汇总` 表格,逐条列出状态(✅/⚠️/❌/♻️)
- 若某条失败,自动重试 1 次,回执中标注 `retried`

### 场景 11: 目录命名冲突

**对应**: FR-009a(澄清项)

```bash
# 同一秒内对同标题网页剪藏两次(模拟冲突)
python clip.py "https://example.com" --force
python clip.py "https://example.com" --force
```

**预期结果**:
- 两个归档目录共存: `<时间戳>_Example Domain` 与 `<时间戳>_Example Domain-1`
- 不覆盖已有目录

### 场景 12: 索引损坏恢复

**对应**: FR-013a(澄清项)

```bash
# 手动损坏索引文件
echo "corrupted" > clipped_pages/_index.json

# 执行剪藏
python clip.py "https://example.com"
```

**预期结果**:
- 系统不崩溃
- 损坏文件被备份为 `_index.json.corrupted.<时间戳>`
- 重建空索引并完成剪藏
- 向用户输出提示:索引已重建及备份位置
- structlog 日志记录恢复事件

### 场景 13: 搜索与统计

**对应**: FR-014/015

```bash
python clip.py --search "example"
python clip.py --stats
```

**预期结果**:
- 搜索输出匹配条目的标题、URL、分类、时间
- 统计输出总条目数、最后更新时间、各分类分布

## 质量门禁验证

```bash
# 静态检查(宪法原则 II)
ruff check .
ruff format --check .
mypy --strict clipper/

# 测试覆盖率(宪法质量标准)
pytest --cov=clipper --cov-report=term-missing --cov-fail-under=80
```

**预期**: 全部零告警、零错误,覆盖率 ≥80%。
