# Implementation Plan: 统一剪藏核心 (Unified Clip Core)

**Branch**: `001-unified-clip-core` | **Date**: 2026-07-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-unified-clip-core/spec.md`

## Summary

统一剪藏核心功能覆盖网页/视频/图片/文档的端到端剪藏流程。基于对现有代码的基线分析,项目已有模块化骨架(`clipper/` 下 8 个模块)、Firecrawl/httpx 双后端回退、Playwright/Firecrawl 截图配置化、ASR 分级回退链等核心能力。本计划聚焦于:(1) 补齐规格中 4 项缺失功能(目录冲突后缀、批量重试、索引损坏恢复、大小/时长校验);(2) 引入测试基础设施(从零搭建 tests/ 分层目录);(3) 引入结构化日志与统一类型识别抽象。技术方案参考 Karakeep 的"设置即启用、不设即降级"模式与 Archivy 的测试组织模式。

## Technical Context

**Language/Version**: Python 3.11+ (现有 `requirements.txt` 要求 httpx>=0.27、pypdf>=4.0 等现代版本)

**Primary Dependencies**:
- 核心: httpx(异步 HTTP)、html2text(HTML→MD)、pyyaml(配置)、firecrawl-py(网页抓取)
- 文档: python-docx(Word)、pypdf(PDF)
- 截图: playwright(整页截图)
- 外部 CLI(非 pip): bilibili-cli(B站视频,通过 subprocess 调用)、VideoCaptioner(ASR,通过 subprocess/importlib)
- 测试(新增): pytest、pytest-httpx、pytest-mock、pytest-asyncio
- 日志(新增): structlog

**Storage**: 本地文件系统 + JSON 索引(`clipped_pages/_index.json`),无数据库

**Testing**: pytest(新增),分层为 `tests/unit/`(纯函数)、`tests/integration/`(文件 I/O + mock 网络)、`tests/contract/`(外部 API 契约)

**Target Platform**: 跨平台 CLI(Windows/Linux/macOS),用户交互以命令行为唯一入口

**Project Type**: CLI 工具(library/cli 混合,以 CLI 为主)

**Performance Goals**:
- SC-001: 单个常规网页剪藏 ≤30 秒(含正文+图片+截图)
- SC-005: 批量 10 条混合输入 ≤5 分钟
- SC-007: 关键词检索 ≤2 秒

**Constraints**:
- 单文件 ≤20MB(FR-013b,前置校验)
- 视频时长 ≤15 分钟(FR-013b,前置校验)
- 单机本地存储,无云同步、无多用户
- `requirements.txt` 必须锁定版本(`==`,宪法质量标准要求)
- 圈复杂度 ≤10、`ruff check` 零告警、`mypy --strict` 零错误(宪法原则 II)

**Scale/Scope**: 单用户,本地存储,预估归档条目 <10,000 条

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

基于 `.specify/memory/constitution.md` v1.0.0 的五项核心原则逐项评估:

| 原则 | 状态 | 说明 | 行动 |
|------|------|------|------|
| I. 测试优先(不可协商) | ⚠️ 违规待修正 | 当前项目零自动化测试,无 tests/ 目录 | 本次迭代必须从零搭建测试基础设施,新功能 MUST TDD;详见 Complexity Tracking |
| II. 代码质量门禁 | ⚠️ 违规待修正 | 未配置 ruff/mypy,无 CI 门禁 | 本次迭代引入 ruff + mypy 配置;`clipper/` 各模块逐步补齐类型注解 |
| III. 模块化与可测试性 | 🟡 部分通过 | 模块按剪藏类型划分(✅);`category_fn` 回调注入是良好抽象(✅);但各模块顶层 `_load_config()` 硬编码路径(❌),`clip.py` 编排逻辑 1145 行过长(❌) | 提取 `clipper/config.py` 单例配置;`clip_url` 函数拆分为更小单元 |
| IV. 集成测试与契约测试 | ⚠️ 违规待修正 | 外部依赖(Firecrawl/bili-cli/火山引擎)无任何契约测试 | 本次迭代建立 `tests/contract/`,录制外部 API 响应结构 |
| V. 可观测性与错误处理 | 🟡 部分通过 | 占位 md 模式实现了"不产生半成品"(✅);但无 logging 框架(❌),warnings 以字符串列表承载(❌) | 引入 structlog;保留 `result["warnings"]` 面向用户回执,structlog 面向开发排障 |

**门禁结论**: 原则 I/II/IV 存在违规,但均为"项目尚处于初始阶段、测试基础设施未搭建"导致,而非原则本身不适用。本次迭代 MUST 在实现新功能前优先搭建测试基础设施与质量门禁配置。详见 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/001-unified-clip-core/
├── plan.md              # 本文件
├── spec.md              # 规格说明
├── research.md          # Phase 0 研究成果
├── data-model.md        # Phase 1 实体与数据模型
├── quickstart.md        # Phase 1 验证指南
├── contracts/
│   └── cli-contract.md  # Phase 1 CLI 接口契约
└── tasks.md             # Phase 2 输出(由 /speckit-tasks 创建)
```

### Source Code (repository root)

```text
clip.py                  # 主入口 CLI(argparse,待渐进迁移至 typer)
clipper/
├── __init__.py
├── config.py            # 新增:单例配置加载(替代各模块 _load_config)
├── logging.py           # 新增:structlog 配置,提供 get_logger()
├── folder.py            # 新增:目录命名工具(冲突追加后缀,FR-009a)
├── validators.py        # 新增:前置校验(文件大小/视频时长,FR-013b)
├── url_detector.py      # 新增:URL 类型识别(B站→video,其他→web)
├── categorizer.py       # 现有:关键词分类器
├── indexer.py           # 现有:JSON 索引管理(需补备份恢复+fetch_backend字段)
├── web.py               # 现有:网页抓取(Firecrawl+httpx 回退)
├── video.py             # 现有:B站视频(含 ASR 集成点)
├── image.py             # 现有:图片剪藏+内容哈希
├── doc.py               # 现有:PDF/Word 正文抽取
├── asr.py               # 现有:ASR 分级回退(委托给 FallbackChain)
├── asr_backend.py       # 新增:ASRBackend 抽象基类
├── asr_bijian.py        # 新增:BijianBackend 实现
├── asr_jianying.py       # 新增:JianyingBackend 实现
├── asr_volcengine.py     # 新增:VolcengineBackend 实现
├── asr_fallback.py       # 新增:FallbackChain 编排器
├── platform_base.py     # 新增:PlatformAdapter 抽象基类(多平台扩展接入点)
├── platform_bilibili.py # 新增:BilibiliAdapter 实现
└── screenshot.py        # 现有:Playwright 整页截图
clipped_pages/           # 归档根目录
├── _index.json          # 索引文件
└── {分类}/{时间戳_标题}/ # 各归档条目
tests/                   # 新增:测试目录
├── conftest.py          # 共享 fixture
├── unit/                # 单元测试(纯函数,无 IO/网络)
│   ├── test_config.py
│   ├── test_indexer.py
│   ├── test_folder.py
│   ├── test_validators.py
│   ├── test_categorizer.py
│   ├── test_web_dedup.py
│   ├── test_video_dedup.py
│   ├── test_image_dedup.py
│   └── test_doc_dedup.py
├── integration/         # 集成测试(真实文件系统 + mock 网络)
│   ├── test_web_pipeline.py
│   ├── test_asr_fallback.py
│   ├── test_video_asr_all_fail.py
│   ├── test_image_clip.py
│   ├── test_doc_clip.py
│   ├── test_doc_protected.py
│   ├── test_batch_clip.py
│   ├── test_batch_mixed.py
│   └── test_clip_workflow.py
└── contract/            # 契约测试(外部 API 响应结构)
    ├── test_firecrawl_api.py
    ├── test_volcengine_api.py
    ├── test_videocaptioner_api.py
    └── test_bilibili_cli.py
config.example.yaml      # 配置模板
config.yaml              # 用户配置(不入 git)
requirements.txt         # pip 依赖(需锁定版本)
requirements-tests.txt   # 新增:测试依赖
pyproject.toml           # 新增:ruff + mypy 配置
```

**Structure Decision**: 采用单项目结构(Option 1),保持现有 `clipper/` 模块划分。新增 `clipper/config.py`、`tests/` 分层目录、`pyproject.toml`(ruff+mypy 配置)与 `requirements-tests.txt`。不引入 backend/frontend 分离,因项目为纯 CLI 工具。

## Complexity Tracking

> **Constitution Check 违规项的修正计划**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 原则 I: 零测试 | 项目处于功能验证阶段,需先搭建测试基础设施再补功能 | "先补功能后补测试"被驳回:宪法原则 I 明确要求 TDD 不可协商,且新功能(FR-009a/011a/013a/013b)均需测试验证,无测试基础设施则无法执行 TDD |
| 原则 II: 无 ruff/mypy | 需统一代码风格与类型检查以支撑多人协作 | "仅靠人工 review"被驳回:宪法原则 II 要求可量化门禁,ruff/mypy 是 Python 生态最低成本的自动化门禁 |
| 原则 IV: 无契约测试 | 外部依赖(Firecrawl/火山引擎)API 结构易变,无契约测试则回归不可发现 | "仅靠集成测试 mock"被驳回:宪法原则 IV 明确要求"严禁只 Mock 不验证真实契约",契约测试固定外部响应结构是必要层 |
| `clip_url` 函数 470 行 | 现有编排逻辑集中在单函数,新增功能会进一步膨胀 | "保持现状只补功能"被驳回:宪法原则 II 要求圈复杂度 ≤10,470 行函数必然超标;且拆分后新功能(目录冲突、重试等)可独立测试 |
| `_load_config()` 各模块重复加载 | 阻碍测试注入临时配置(宪法原则 III:依赖显式) | "维持各自加载"被驳回:测试需 `tmp_path` 注入测试配置,硬编码路径无法注入 |
