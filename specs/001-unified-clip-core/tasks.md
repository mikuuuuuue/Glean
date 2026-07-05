---
description: "Task list for 统一剪藏核心 (Unified Clip Core)"
---

# Tasks: 统一剪藏核心 (Unified Clip Core)

**Input**: Design documents from `/specs/001-unified-clip-core/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contract.md, quickstart.md

**Tests**: 宪法原则 I 要求 TDD(不可协商),因此测试任务为必需项,每个实现任务前先写失败测试。

**Organization**: 任务按用户故事分组(5 个 User Story,按 P1→P2→P3 优先级排序),前置阶段(Setup + Foundational)优先修正宪法违规项(零测试、无质量门禁)。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行(不同文件,无依赖)
- **[Story]**: 所属用户故事(US1-US5)
- 所有路径均含具体文件位置

---

## Phase 1: Setup (项目初始化)

**Purpose**: 吥建测试基础设施与质量门禁配置,修正宪法原则 I/II 违规

- [X] T001 创建测试目录结构 `tests/unit/`、`tests/integration/`、`tests/contract/` 及空 `__init__.py`
- [X] T002 [P] 创建 `requirements-tests.txt`,锁定 `pytest==8.x`、`pytest-httpx`、`pytest-mock`、`pytest-asyncio`、`pytest-cov`
- [X] T003 [P] 创建 `pyproject.toml`,配置 `ruff`(line-length=100、select=E/F/W/I/N/UP)与 `mypy`(strict=true)
- [X] T004 [P] 创建 `tests/conftest.py`,定义共享 fixture(config 工厂、tmp_path index fixture、mock httpx)
- [X] T005 锁定 `requirements.txt` 版本(将 `>=` 改为 `==`,宪法质量标准要求)

---

## Phase 2: Foundational (阻塞性前置)

**Purpose**: 配置单例、结构化日志、索引备份恢复、目录冲突处理——所有用户故事的前置依赖

**⚠️ CRITICAL**: 宪法违规修正,必须在任何用户故事实现前完成

### Tests (TDD - 先写失败测试)

- [X] T014 [P] 编写 `tests/unit/test_config.py`:验证 `get_config()` 单例、tmp_path 注入、环境变量覆盖层
- [X] T015 编写 `tests/unit/test_indexer.py`:验证索引增删查、损坏备份恢复(FR-013a)、fetch_backend 字段(FR-012)、"内容已更新"判定(FR-010)
- [X] T016 [P] 编写 `tests/unit/test_folder.py`:验证目录名冲突追加后缀(FR-009a)
- [X] T017 [P] 编写 `tests/unit/test_validators.py`:验证文件大小校验与视频时长校验(FR-013b)

### Implementation

- [X] T006 [P] 创建 `clipper/config.py` 单例配置加载器,提供 `get_config()` 函数,支持 `tmp_path` 注入(替代各模块 `_load_config()`)
- [X] T007 [P] 创建 `clipper/logging.py` structlog 配置,提供 `get_logger()`,与 `result["warnings"]` 职责分离
- [X] T008 重构 `clipper/indexer.py`:`Indexer._read()` 检测 JSONDecodeError 时备份损坏文件为 `_index.json.corrupted.{timestamp}`,重建空索引,structlog 记录恢复事件,向用户输出提示(FR-013a)
- [X] T009 重构 `clipper/indexer.py`:`add_entry()` 新增 `fetch_backend` 字段写入(FR-012);`find_by_url()` 返回全部匹配记录(非仅最早一条)以支撑"内容已更新"判定(FR-010)
- [X] T010 重构 `clipper/indexer.py`:新增"内容已更新"判定逻辑——URL 相同但 content_hash 不同时返回 `dedup_status="updated"`,URL 与 content_hash 均相同返回 `dedup_status="duplicate"`(FR-010)
- [X] T011 [P] 提取 `clipper/folder.py` 目录命名工具:`safe_folder_name()` 检查目标目录存在性,冲突时追加 `-1`/`-2` 后缀(FR-009a)
- [X] T012 [P] 提取 `clipper/validators.py` 前置校验:`validate_file_size(path, max_mb=20)` 与 `validate_video_duration(duration_sec, max_min=15)`(FR-013b)
- [X] T013 重构各模块配置加载:`clipper/web.py`、`clipper/video.py`、`clipper/asr.py`、`clipper/screenshot.py` 从 `clipper/config.py` 获取配置(移除各自 `_load_config()`;depends on T006)

**Checkpoint**: 基础设施就绪,宪法原则 I/II/III/V 违规已修正,用户故事实现可开始

---

## Phase 3: User Story 1 - 网页剪藏 (Priority: P1) 🎯 MVP

**Goal**: 用户输入网页网址,系统抓取正文转 Markdown、下载图片、生成整页截图、自动分类、去重检查、写入索引

**Independent Test**: 给定一个可访问网页网址,执行剪藏后,归档目录含正文 Markdown、图片、截图,索引含完整记录(含 fetch_backend)

### Tests for User Story 1 (TDD - 先写失败测试)

- [X] T018 [P] [US1] 编写 `tests/integration/test_web_pipeline.py`:Firecrawl mock → httpx 真实解析,验证正文 MD、图片下载、截图落盘、索引写入
- [X] T019 [P] [US1] 编写 `tests/unit/test_web_dedup.py`:验证完全重复(返回 `duplicate`)与内容已更新(返回 `updated`)两条路径(FR-010)
- [X] T020 [P] [US1] 编写 `tests/contract/test_firecrawl_api.py`:录制 Firecrawl 响应结构,验证字段契约(FR-005 宪法原则 IV)

### Implementation for User Story 1

- [X] T021 [US1] 重构 `clipper/web.py`:`clip_webpage` 与 `clip_webpage_firecrawl` 返回结果新增 `fetch_backend` 字段(FR-012)
- [X] T022 [US1] 重构 `clipper/web.py`:去重命中时区分"完全重复"与"内容已更新",调用 `Indexer.find_by_url()` 的全量返回判定(FR-010)
- [X] T023 [US1] 重构 `clipper/screenshot.py`:新增 `full_page` 与 `store_screenshot` 配置项,`take_fullpage_screenshot()` 透传 `full_page` 参数(参考 Karakeep)
- [X] T024 [US1] 重构 `clipper/web.py`:截图功能受 `screenshot.enabled` 控制(默认开启可关闭,澄清项确认)
- [X] T025 [US1] 重构 `clip.py` 的 `clip_url()`:提取目录创建/改名逻辑为独立函数,调用 `clipper/folder.py` 的冲突处理(FR-009a)
- [X] T026 [US1] 重构 `clip.py` 的 `clip_url()`:集成 structlog 日志,记录抓取后端、耗时、降级事件(FR-005 宪法原则 V)
- [X] T027 [US1] 重构 `clip.py`:网页剪藏失败时生成失败占位 md,不产生半成品目录(FR-013)

**Checkpoint**: 网页剪藏端到端可用,quickstart.md 场景 1-4 可验证

---

## Phase 4: User Story 2 - 视频剪藏 (Priority: P1)

**Goal**: 用户输入视频网址,系统获取视频信息、字幕与封面;无官方字幕时按 ASR 分级回退策略自动转写

**Independent Test**: 给定一个 B站视频网址,执行剪藏后,归档目录含视频信息、字幕文本与封面;无官方字幕时含 ASR 转写文本

### Tests for User Story 2 (TDD)

- [x] T028 [P] [US2] 编写 `tests/integration/test_asr_fallback.py`:mock 三个 ASRBackend(bijian/jianying/volcengine),验证回退顺序与每级日志记录(FR-005)
- [x] T029 [P] [US2] 编写 `tests/unit/test_video_dedup.py`:验证视频去重(BV 号相同判定)
- [x] T030 [P] [US2] 编写 `tests/contract/test_volcengine_api.py`:录制火山引擎 submit/query 响应结构,验证两段式契约(宪法原则 IV)
- [x] T031 [P] [US2] 编写 `tests/integration/test_video_asr_all_fail.py`:验证所有 ASR 后端失败时仍归档视频信息+封面+标注字幕缺失(FR-006)
- [x] T031a [P] [US2] 编写 `tests/contract/test_videocaptioner_api.py`:录制 VideoCaptioner 必剪/剪映后端的 subprocess 响应结构,验证 CLI 参数契约与输出格式(宪法原则 IV:每条回退路径 MUST 有覆盖)

### Implementation for User Story 2

- [X] T032 [P] [US2] 创建 `clipper/asr_backend.py`:`ASRBackend` 抽象基类(含 `transcribe()`、`available()`、`supports_language()` 方法)
- [X] T033 [P] [US2] 创建 `clipper/asr_bijian.py`:`BijianBackend` 实现,封装 VideoCaptioner subprocess 调用
- [X] T034 [P] [US2] 创建 `clipper/asr_jianying.py`:`JianyingBackend` 实现,封装 VideoCaptioner subprocess 调用
- [X] T035 [P] [US2] 创建 `clipper/asr_volcengine.py`:`VolcengineBackend` 实现,封装 httpx 两段式 submit→poll
- [X] T036 [US2] 创建 `clipper/asr_fallback.py`:`FallbackChain` 编排器,注入 backend 列表,逐级尝试,每级 structlog 记录(FR-005)
- [X] T037 [US2] 重构 `clipper/asr.py`:`transcribe_with_fallback()` 委托给 `FallbackChain`(保持公共接口不变)
- [X] T038 [US2] 重构 `clipper/video.py`:`clip_bilibili()` 返回结果新增 `fetch_backend`(含 `bili-cli` 与 `asr:<引擎>`);视频时长前置校验(FR-013b,调用 `validators.py`)
- [X] T039 [US2] 重构 `clipper/video.py`:ASR 全失败时仍归档视频信息+封面+标注字幕缺失,structlog 记录(FR-006)
- [X] T040 [US2] 创建 `clipper/platform_base.py`:`PlatformAdapter` 抽象基类,定义 `clip(url, output_dir, ...)` 接口,为多平台预留扩展接入点(FR-004 澄清项)
- [X] T041 [US2] 创建 `clipper/platform_bilibili.py`:`BilibiliAdapter` 实现 `PlatformAdapter`,封装 `clip_bilibili`
- [X] T042 [US2] 重构 `clip.py` 的 URL 类型识别:抽象为 `clipper/url_detector.py` 的 `detect_url_type(url)`,B站→video,其他→web;新增"无法识别类型"拒绝逻辑(FR-001)

**Checkpoint**: 视频剪藏端到端可用,quickstart.md 场景 5-6 可验证

---

## Phase 5: User Story 3 - 图片剪藏 (Priority: P2)

**Goal**: 用户输入一张或多张本地图片路径,系统保存原图,多张时合并为一次归档,写入索引并分类

**Independent Test**: 给定一张或多张图片,执行剪藏后,归档目录含原图,索引含记录;多张图片归档于同一目录

### Tests for User Story 3 (TDD)

- [x] T043 [P] [US3] 编写 `tests/integration/test_image_clip.py`:验证单图归档、多图合并同目录、索引写入
- [x] T044 [P] [US3] 编写 `tests/unit/test_image_dedup.py`:验证内容哈希查重(相同哈希判定为重复)

### Implementation for User Story 3

- [X] T045 [US3] 重构 `clipper/image.py`:`clip_image()` 返回结果新增 `fetch_backend` 字段;文件大小前置校验(FR-013b)
- [X] T046 [US3] 重构 `clipper/image.py`:去重逻辑集成 `Indexer.find_by_hash()` 的"内容已更新"判定(FR-010)
- [X] T047 [US3] 重构 `clip.py` 图片批处理:多张图片合并归档逻辑确认,汇总回执生成

**Checkpoint**: 图片剪藏端到端可用,quickstart.md 场景 7 可验证

---

## Phase 6: User Story 4 - 文档剪藏 (Priority: P2)

**Goal**: 用户输入 PDF 或 Word 文档,系统抽取正文、归档原文件、分类、写入索引

**Independent Test**: 给定一个 PDF 或 Word 文档,执行剪藏后,归档目录含抽取正文与原文件,索引含记录

### Tests for User Story 4 (TDD)

- [x] T048 [P] [US4] 编写 `tests/integration/test_doc_clip.py`:验证 PDF 正文抽取、Word 正文抽取、原文件归档、索引写入
- [x] T049 [P] [US4] 编写 `tests/unit/test_doc_dedup.py`:验证文档内容哈希查重
- [x] T050 [P] [US4] 编写 `tests/integration/test_doc_protected.py`:验证加密/损坏文档的优雅降级(不崩溃、提示原因、不产生半成品)

### Implementation for User Story 4

- [X] T051 [US4] 重构 `clipper/doc.py`:`clip_doc()` 返回结果新增 `fetch_backend` 字段;文件大小前置校验(FR-013b,调用 `validators.py`)
- [X] T052 [US4] 重构 `clipper/doc.py`:加密/损坏文档时不崩溃,生成失败占位 md,structlog 记录(FR-013)
- [X] T053 [US4] 重构 `clipper/doc.py`:去重逻辑集成 `Indexer.find_by_hash()`(FR-010)

**Checkpoint**: 文档剪藏端到端可用,quickstart.md 场景 8-9 可验证

---

## Phase 7: User Story 5 - 批量剪藏与去重回执 (Priority: P3)

**Goal**: 用户一次性传入多个网址或文件路径,系统依次执行剪藏、去重检查,完成后输出汇总回执

**Independent Test**: 给定一组混合类型输入,执行批处理后,用户获得汇总回执,逐条列出成功/失败/重复状态

### Tests for User Story 5 (TDD)

- [x] T054 [P] [US5] 编写 `tests/integration/test_batch_clip.py`:验证批量处理、逐条状态回执、单条失败重试 1 次(FR-011a)
- [x] T055 [P] [US5] 编写 `tests/integration/test_batch_mixed.py`:验证混合类型输入(网址+文件)的批处理

### Implementation for User Story 5

- [X] T056 [US5] 重构 `clip.py` 批处理流程:新增单条失败自动重试 1 次逻辑,仍失败则跳过并继续(FR-011a)
- [X] T057 [US5] 重构 `clip.py` 的 `build_summary()`:回执新增 `retried` 字段标注,区分"失败"与"重试后失败"
- [X] T058 [US5] 重构 `clip.py` 文件批处理:`--image` 与 `--doc` 合并处理,文件大小前置校验(FR-013b)
- [X] T059 [US5] 重构 `clip.py`:批量处理中单条失败不阻断后续,structlog 记录每条结果(FR-011a)

**Checkpoint**: 批量剪藏端到端可用,quickstart.md 场景 10 可验证

---

## Phase 8: Polish & 跨切面关注点

**Purpose**: 跨用户故事的改进与最终验证

- [X] T060 [P] 运行 `ruff check .` 与 `ruff format --check .`,修复全部告警(宪法原则 II)
- [X] T061 [P] 运行 `mypy --strict clipper/`,修复全部类型错误(宪法原则 II)
- [X] T062 运行 `pytest --cov=clipper --cov-report=term-missing --cov-fail-under=80`,确认覆盖率 ≥80%(宪法质量标准)
- [X] T063 [P] 补充 `tests/unit/test_categorizer.py`:验证 7 大分类关键词匹配、`needs_suggestion`、分类上限 6
- [X] T063a [P] 补充 `tests/unit/test_search_stats.py`:验证关键词检索(FR-014)返回正确结果、统计信息(FR-015)含总数与各领域分布、检索在 2 秒内完成(SC-007)
- [X] T064 [P] 补充 `tests/integration/test_clip_workflow.py`:端到端验证(抓取→分类→索引→归档完整管线)
- [X] T065 [P] 补充 `tests/contract/test_bilibili_cli.py`:录制 bili-cli subprocess 响应结构,验证契约(宪法原则 IV)
- [X] T066 更新 `config.example.yaml`:新增 `limits.max_file_size_mb`、`limits.max_video_duration_min`、`screenshot.full_page`、`screenshot.store_screenshot` 配置项
- [X] T067 [P] 更新 `README.md`:补充测试运行说明、质量门禁说明、新增配置项说明
- [X] T068 按 `quickstart.md` 执行全部 13 个验证场景,确认端到端通过

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖,可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成——**阻塞全部用户故事**
- **User Story 1 (Phase 3)**: 依赖 Foundational
- **User Story 2 (Phase 4)**: 依赖 Foundational;与 US1 可并行(不同模块)
- **User Story 3 (Phase 5)**: 依赖 Foundational;与 US1/US2 可并行
- **User Story 4 (Phase 6)**: 依赖 Foundational;与 US1/US2/US3 可并行
- **User Story 5 (Phase 7)**: 依赖 Foundational + US1-4 的单条剪藏流程稳定
- **Polish (Phase 8)**: 依赖全部用户故事完成

### User Story Dependencies

```
Phase 1 (Setup)
    │
    ▼
Phase 2 (Foundational) ← 阻塞全部
    │
    ├──────────┬──────────┬──────────┐
    ▼          ▼          ▼          ▼
  US1(P1)   US2(P1)    US3(P2)   US4(P2)
  网页       视频        图片      文档
    │          │          │          │
    └──────────┴──────────┴──────────┘
                    │
                    ▼
              US5(P3) 批量
                    │
                    ▼
              Polish (Phase 8)
```

### Within Each User Story

- 测试先行(TDD):先写失败测试,确认测试意图正确,再实现
- 模型/抽象 → 服务/实现 → 集成
- 核心实现 → 错误处理 → 日志
- 单故事完成后再进入下一优先级

### Parallel Opportunities

- Phase 1: T002/T003/T004 可并行(不同文件)
- Phase 2: T006/T007/T011/T012 可并行(不同模块);T016/T017 可并行(不同测试文件)
- Phase 3 (US1): T018/T019/T020 测试可并行
- Phase 4 (US2): T028/T029/T030/T031 测试可并行;T032-T035 的 ASRBackend 实现可并行
- Phase 5-6 (US3/US4): 不同用户故事可并行
- Phase 8: T060/T061/T063/T064/T065/T067 可并行

---

## Parallel Example: User Story 2 (视频剪藏)

```bash
# 并行启动全部测试(先写失败测试):
Task T028: "test_asr_fallback.py - mock 三个 ASRBackend 验证回退顺序"
Task T029: "test_video_dedup.py - 验证 BV 号去重"
Task T030: "test_volcengine_api.py - 录制火山引擎响应契约"
Task T031: "test_video_asr_all_fail.py - 验证全失败仍归档"

# 并行启动全部 ASRBackend 实现(不同文件):
Task T032: "asr_backend.py - ASRBackend 抽象基类"
Task T033: "asr_bijian.py - BijianBackend"
Task T034: "asr_jianying.py - JianyingBackend"
Task T035: "asr_volcengine.py - VolcengineBackend"
```

---

## Implementation Strategy

### MVP First (仅 User Story 1)

1. 完成 Phase 1: Setup(测试基础设施 + 质量门禁配置)
2. 完成 Phase 2: Foundational(配置单例、日志、索引恢复、目录冲突、前置校验)
3. 完成 Phase 3: User Story 1(网页剪藏)
4. **STOP and VALIDATE**: 按 quickstart.md 场景 1-4 独立验证
5. 确认宪法原则 I/II/III/V 违规已修正

### Incremental Delivery

1. Setup + Foundational → 基础设施就绪,宪法违规修正
2. + US1 网页剪藏 → 测试独立验证 → MVP 交付
3. + US2 视频剪藏 → 测试独立验证 → B站完整能力
4. + US3 图片剪藏 + US4 文档剪藏 → 可并行 → 全类型覆盖
5. + US5 批量剪藏 → 依赖单条流程稳定 → 批处理能力
6. Polish → 质量门禁全绿、覆盖率达标、端到端验证

### Parallel Team Strategy

- 开发者 A: US1 网页剪藏(核心管线)
- 开发者 B: US2 视频剪藏(ASR 抽象,独立模块)
- 开发者 C: US3 图片 + US4 文档(轻量模块,可串行)
- US5 批量待 US1-4 稳定后由任一开发者接手

---

## Notes

- 宪法原则 I 要求 TDD 不可协商:每个实现任务前 MUST 先写失败测试
- 宪法原则 II 要求质量门禁:Phase 8 的 T060-T062 是 release 前置
- 宪法原则 IV 要求契约测试:不可只 Mock 不验证真实契约,contract/ 测试是必需层
- 宪法原则 V 要求可观测性:structlog 日志与 `result["warnings"]` 职责分离
- 每个任务完成后提交(commit),遵循 Conventional Commits
- 在任意 Checkpoint 可暂停验证当前故事

---

## Phase 9: Convergence

**Purpose**: 修复 /speckit-implement 执行后发现的规格与实现差距、宪法违规项

- [X] T069 修复 `requirements.txt` 与 `requirements-tests.txt` 版本锁定:将所有 `>=` 替换为 `==`(T005 标记完成但实际未执行) per Constitution II, T005 (contradicts)
- [X] T070 拆分 `clip.py` 的 `clip_url()` 函数(当前 487 行,远超复杂度 ≤10):提取 `_clip_bilibili()`、`_clip_web_firecrawl()`、`_clip_web_local()`、`_finalize_clip()` 等子函数,每个 ≤80 行 per Constitution II, plan Complexity Tracking (partial)
- [X] T071 为 `clipper/web.py`、`clipper/video.py`、`clipper/image.py`、`clipper/doc.py`、`clipper/asr.py`、`clipper/screenshot.py`、`clipper/categorizer.py` 接入 structlog(`get_logger()`),记录抓取后端切换、降级事件、耗时(T026 仅覆盖 `clip.py` 入口) per Constitution V (partial)
- [X] T072 将 `clipper/indexer.py:72` 的 `print()` 替换为 `_log.warning()`,或明确标注为用户面向输出并与 structlog 日志分离 per Constitution V (contradicts)
- [X] T073 在 `clip.py` 的 `clip_file()` 函数 `add_entry()` 调用中补充 `fetch_backend` 参数(当前文件类剪藏索引记录的 fetch_backend 为空字符串) per FR-012 (missing)
- [X] T074 引入外部依赖注入模式:为 `FirecrawlApp`、`httpx.AsyncClient`、`subprocess` 调用提供可注入的工厂/Provider,使 `clipper/web.py`、`clipper/video.py`、`clipper/doc.py` 可在测试中替换外部依赖 per Constitution III (partial)

## Phase 10: Convergence

**Purpose**: 修复运行时测试发现的 ASR/bcut 失败根因与字幕获取缺陷

- [X] T075 在 `BijianBackend` 和 `JianyingBackend` 的 `transcribe()` 方法中,导入 `videocaptioner` 前预初始化 diskcache:检测 `CACHE_PATH/llm_translation/cache.db` 是否存在,若不存在则用 `sqlite3` 手动创建含 `Settings` 和 `Cache` 表的空数据库,避免 diskcache 首次初始化时 `PRAGMA` 语句在表创建前执行导致 `unable to open database file` 错误 per FR-005 (partial)
- [X] T076 在 `clipper/video.py` 的 `clip_bilibili()` 中,当 bili-cli 返回 `subtitle.available=false` 且 stderr 含 `Credential` 或 `sessdata` 时,在 `result["warnings"]` 中追加用户友好提示:"bili-cli 未登录,运行 `bili login` 扫码登录后可获取官方字幕" per FR-005, US2/AC1 (missing)
- [X] T077 在 `clipper/asr_bijian.py` 和 `asr_jianying.py` 的 `transcribe()` 异常处理中,将完整错误链(含 diskcache/sqlite 根因)透传到返回的 warnings 列表,而非仅截断 200 字符的表层错误 per Constitution V (partial)
- [X] T078 补充 `tests/unit/test_video_extended.py` 中 av 号合集视频转换测试:验证 `resolve_av_to_bv()` 对合集 av 号(返回 `data.episodes` 而非 `data.bvid`)正确取第一集 BV 号 per FR-004 (partial)
