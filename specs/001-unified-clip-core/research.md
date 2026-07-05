# Research: 统一剪藏核心 (Unified Clip Core)

**Date**: 2026-07-04 | **Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## 1. 现有代码基线分析

### Decision: 基于现有模块化骨架增量演进,不重写

### Rationale

通过对 `clip.py`(1145 行)与 `clipper/` 下 8 个模块的逐文件分析,确认:

- **已有良好抽象**:`category_fn` 回调注入模式、失败占位 md 模式、`screenshot.engine` 与 `scraping.backend` 的可配置回退——这些抽象值得保留
- **已有完整功能链**:网页(Firecrawl+httpx 回退)、视频(B站完整+ASR 回退链)、图片(多图合并)、文档(PDF/Word 抽取)、索引(JSON 增删查)、分类(7 大领域关键词匹配)
- **重写成本远高于增量补齐**:现有代码已覆盖 FR-001 到 FR-015 中的 9 项"已实现",仅 4 项"缺失"与 5 项"部分实现"需补齐

### Alternatives Considered

- **全量重写为 Typer + dataclass 架构**:虽能一步到位,但会丢失已验证的回退链逻辑与占位 md 逻辑,回归风险高
- **仅补功能不改架构**:会导致 `clip_url` 函数进一步膨胀(已 470 行),违反宪法原则 II(圈复杂度 ≤10)

### 现有 FR 实现状态矩阵

| FR | 状态 | 缺口说明 |
|---|---|---|
| FR-001 | 🟡 部分 | URL 仅识别 B站,无统一类型识别抽象,无"无法识别类型"拒绝逻辑 |
| FR-002 | ✅ 已实现 | `clip_webpage` / `clip_webpage_firecrawl` |
| FR-003 | ✅ 已实现 | `screenshot.py` + `_capture_screenshot` 分级回退 |
| FR-004 | 🟡 部分 | B站完整;YouTube 仅 stub;**无显式"平台接入点"抽象接口** |
| FR-005 | 🟡 部分 | 回退链逐级尝试;但**无 logging 模块、无结构化日志** |
| FR-006 | ✅ 已实现 | 无字幕时仍归档视频信息+封面+标注缺失 |
| FR-007 | ✅ 已实现 | `clip_image` 多图合并 |
| FR-008 | ✅ 已实现 | `clip_doc` PDF/Word 抽取+原文件归档 |
| FR-009 | ✅ 已实现 | `Categorizer.classify` 7 大分类 |
| FR-009a | ❌ 缺失 | `safe_folder_name` 不检查冲突,会覆盖 |
| FR-010 | 🟡 部分 | `find_by_url`/`find_by_hash` 存在;**无"内容已更新"分支** |
| FR-011 | ✅ 已实现 | 串行处理 + `build_summary` 汇总 |
| FR-011a | ❌ 缺失 | 无任何重试逻辑 |
| FR-012 | 🟡 部分 | 记录 url/saved_at/source/files;**无 `fetch_backend` 字段** |
| FR-013 | 🟡 部分 | 占位 md 避免半成品;但 `shutil.move`/`rmtree` 无事务性 |
| FR-013a | ❌ 缺失 | `Indexer._read` 吞掉 `JSONDecodeError`,不备份不提示 |
| FR-013b | ❌ 缺失 | 全项目无 `os.path.getsize`,无视频时长上限 |
| FR-014 | ✅ 已实现 | `Indexer.search` |
| FR-015 | ✅ 已实现 | `Indexer.get_stats` |

## 2. 类似开源项目架构参考

### Decision: 借鉴 Karakeep 的"设置即启用、不设即降级"模式,不引入 worker 架构

### Rationale

- **Karakeep(原 Hoarder)**:采用可插拔 worker 架构(crawler/inference/search/video 等),存储后端抽象(本地/S3),搜索后端可降级 [1][2]。其"设置即启用、不设即降级"模式与 Glean 现有的 `screenshot.engine=auto/off`、`scraping.backend=auto/local/firecrawl` 思路一致,应推广为全局设计约定
- **Archivy**:基于 click-plugins + entry_points 的插件系统 [3][4]。适合"第三方扩展"场景,但 Glean 当前需求是内部多后端回退,函数级策略链已足够,过早引入 entry_points 会增加打包复杂度
- **Glean 现有抽象已足够 v1**:无需引入 Karakeep 的 worker 进程模型或 Archivy 的插件系统

### Alternatives Considered

- **引入 entry_points 插件系统**:被驳回——v1 仅需内部多后端回退,函数级抽象已满足
- **引入 Meilisearch 全文检索**:被驳回——Glean 作为单机 CLI,JSON 索引+内存过滤已满足 SC-007(2 秒检索);条目过万时再评估 SQLite FTS5

### 参考来源

- [Karakeep README](https://github.com/karakeep-app/karakeep)
- [Karakeep 配置文档](https://docs.karakeep.app/configuration)
- [Archivy 仓库](https://github.com/archivy/archivy)
- [Archivy 插件文档](https://github.com/archivy/archivy/blob/master/plugins.md)

## 3. CLI 框架与配置管理

### Decision: 维持 argparse(v1),引入 `clipper/config.py` 单例配置,不迁移至 Typer

### Rationale

- **argparse 已满足当前需求**:现有 `clip.py` 的 argparse 参数解析覆盖全部 FR(网址/文件/搜索/统计/分类管理),迁移至 Typer 需重写 `main()` 函数,收益不抵成本
- **配置单例化是更高优先级**:当前 `web.py`、`video.py`、`asr.py`、`screenshot.py` 各自 `_load_config()` 重复读盘且硬编码路径,阻碍测试注入临时配置(违反宪法原则 III:依赖显式)。提取 `clipper/config.py` 提供 `get_config()` 函数,各模块改为从单例获取
- **配置分层覆盖**:维持 YAML 为基础,新增环境变量覆盖层(密钥类如 `GLEAN_FIRECRAWL_API_KEY`、`GLEAN_VOLC_TOKEN`),适配 NAS/Docker 场景

### Alternatives Considered

- **迁移至 Typer**:被驳回——v1 保持 argparse 兼容,待 v2 再评估迁移
- **切换为 TOML 配置**:被驳回——YAML 支持注释与多行字符串(`ai_summary.prompt_template`),TOML 对深层嵌套表达力弱

## 4. 结构化日志方案

### Decision: 引入 structlog,与 `result["warnings"]` 职责分离

### Rationale

- **structlog 兼容标准 logging**:可平滑迁移,不必一次性替换全部模块
- **职责分离**:`result["warnings"]` 面向用户回执(人类可读),structlog 面向开发排障(结构化 key-value,可持久化)
- **多后端回退场景适配**:每次 ASR/抓取/截图回退可结构化记录 `engine=bijian, status=failed, reason=exit_code_5`,便于事后分析

### Alternatives Considered

- **仅用标准 logging**:被驳回——标准 logging 输出非结构化,多后端回退场景排障效率低
- **一次性替换全部 warnings 为 structlog**:被驳回——渐进采用,先在新模块(config.py、新增 FR 功能)用 structlog,旧模块逐步过渡

### 参考来源

- [structlog 官方文档](https://www.structlog.org/)

## 5. ASR 分级回退链抽象

### Decision: 引入 `ASRBackend` 抽象基类 + `FallbackChain` 编排器

### Rationale

- 当前 `asr.py` 的 `transcribe_with_fallback` 已实现逐级回退,但过程式 `if engine == 'bijian'` 分支难以单元测试(需 mock subprocess)
- 抽象为 `ASRBackend` 基类后,每个后端(bijian/jianying/volcengine)可独立 mock 测试;`FallbackChain` 编排器可注入 mock backend 列表验证回退顺序
- 新增后端(如 whisper-api)只需新增子类并注册到 `fallback_chain` 配置,符合开闭原则

### Alternatives Considered

- **维持过程式分支**:被驳回——无法满足宪法原则 III(纯函数优先、可测试)与原则 IV(集成测试分层)

### 参考来源

- 项目已有文档 `.trae/documents/asr-fallback-strategy.md`(完整回退链设计)
- [火山引擎录音文件识别 API](https://www.volcengine.com/docs/6561/80820)
- [VideoCaptioner CLI 文档](https://github.com/WEIFENG2333/VideoCaptioner)

## 6. 网页抓取回退策略

### Decision: 统一为"backend + auto 回退"模式,新增 `full_page` 与 `store_screenshot` 独立开关

### Rationale

- 现有 `scraping.backend=auto/local/firecrawl` 与 `screenshot.engine=auto/playwright/firecrawl/off` 已是良好实践
- 参考 Karakeep 的 `CRAWLER_FULL_PAGE_SCREENSHOT`(默认 false)与 `CRAWLER_STORE_SCREENSHOT`(默认 true)两个独立开关 [2],建议拆分:
  - `screenshot.full_page`(新增):整页 vs 首屏,超长页(无尽流)可降级为首屏避免爆内存
  - `screenshot.store_screenshot`(新增):是否落盘,允许"截图仅用于展示但不归档"
- 抓取后端也应抽象为 `ScraperBackend` 接口,便于测试 mock 与未来新增后端(如 Jina Reader)

### Alternatives Considered

- **维持单一 `screenshot.enabled` 开关**:被驳回——无法区分"整页 vs 首屏"与"是否归档"两个独立决策

### 参考来源

- [Karakeep 爬虫配置](https://docs.karakeep.app/configuration) 的 `CRAWLER_*` 配置项

## 7. 测试基础设施方案

### Decision: 从零搭建 tests/ 分层目录,使用 pytest + pytest-httpx + pytest-mock + pytest-asyncio

### Rationale

- **测试分层**(对应宪法质量标准):
  - `tests/unit/`:纯函数(分类器、索引器、配置加载、HTML→MD 转换、标题清洗、目录名冲突处理),毫秒级,无网络无 IO
  - `tests/integration/`:模块组合(抓取→分类→索引→归档管线),用 `tmp_path` 真实文件系统,网络用 mock
  - `tests/contract/`:外部 API(火山引擎、Firecrawl、bili-cli)录制响应结构,验证字段契约
- **Mock 策略**:
  - httpx 网络请求用 `pytest-httpx`(专为 httpx 设计,`httpx_mock.add_response()`)
  - subprocess(bili-cli/videocaptioner)用 `pytest-mock` 的 `mocker.patch(subprocess.run)`
  - Playwright 维持现有 `CLIP_SCREENSHOT_MOCK` 环境变量钩子
  - 配置用 `tmp_path / "config.yaml"` + monkeypatch 路径
- **配置加载解耦是测试前提**:各模块 `_load_config()` 硬编码路径是当前最大测试障碍,必须先提取 `clipper/config.py` 才能注入测试配置

### Alternatives Considered

- **用 responses 库 mock httpx**:被驳回——responses 为 requests 设计,对 httpx 支持需额外适配
- **仅用 unit 测试不建 contract 层**:被驳回——宪法原则 IV 明确要求"严禁只 Mock 不验证真实契约"

### 参考来源

- [pytest-httpx](https://github.com/Colin-b/pytest_httpx)
- [pytest-mock](https://github.com/pytest-dev/pytest-mock)
- [Archivy 测试组织](https://github.com/archivy/archivy)(conftest.py + requirements-tests.txt)

## 8. 索引损坏恢复方案

### Decision: 备份损坏索引 + 重建空索引 + 日志记录 + 用户提示

### Rationale

- 现有 `Indexer._read()` 吞掉 `JSONDecodeError` 直接返回空索引,不备份不记录——违反宪法原则 V(可观测性)与 FR-013a
- 方案:检测到索引损坏时,将损坏文件重命名为 `_index.json.corrupted.{timestamp}` 备份,新建空索引继续操作,structlog 记录恢复事件,向用户输出提示
- 此方案保证当前剪藏操作不被阻断,同时保留损坏文件供事后分析

## 9. 目录命名冲突处理

### Decision: 自动追加数字后缀(`-1`、`-2`)

### Rationale

- 现有 `safe_folder_name` 仅截断标题到 40 字符,不检查目录是否已存在,同名同时间戳会覆盖
- 方案:在 `mkdir` 前检查目标目录是否存在,存在则追加 `-1`、`-2` 直到不冲突
- 这是文件系统最稳妥、可预测且对用户无侵入的冲突解决方式

## 10. 统一设计原则

以下原则贯穿全部实现决策,应作为代码审查清单:

1. **"设置即启用、不设即降级"**:Firecrawl API Key 未设→走 httpx;Playwright 未装→走 Firecrawl 截图;火山 token 未配→跳过该级 ASR;`asr.enabled=false`→零行为变更。此原则已在 `web.py`、`screenshot.py` 中体现,应推广为全局约定
2. **"后端抽象 + 配置选择 + 自动降级"**:无论是 ASR、抓取、截图还是存储,统一用 `XxxBackend` 抽象基类 + 配置选择 + 自动降级模式
3. **"配置与代码解耦"**:提取 `clipper/config.py` 提供可注入的配置对象,让 `tmp_path` 测试配置成为可能
4. **"v1 不引入过度抽象"**:entry_points 插件系统、DI 容器、Meilisearch 搜索服务对当前单机 CLI 是过度设计,函数级后端抽象 + YAML 配置 + pytest mock 已足够
