<!--
同步影响报告 (Sync Impact Report)
=====================================
版本变更: (未初始化模板) → 1.0.0
变更类型: MAJOR — 首次批准并填充宪法,确立以代码质量与测试标准为核心的项目治理原则

修改的原则:
- 新增 I. 测试优先 (Test-First, 不可协商)
- 新增 II. 代码质量门禁 (Code Quality Gates)
- 新增 III. 模块化与可测试性 (Modularity & Testability)
- 新增 IV. 集成测试与契约测试 (Integration & Contract Testing)
- 新增 V. 可观测性与错误处理 (Observability & Error Handling)

新增章节:
- 「质量标准」章节:覆盖率/复杂度/文档/依赖量化指标
- 「开发工作流」章节:代码审查、CI 门禁、提交规范
- 「治理」章节:修正流程、版本策略、合规审查

模板同步状态:
- .specify/templates/plan-template.md — ✅ 兼容(已有 Constitution Check 门禁,无需修改)
- .specify/templates/spec-template.md — ✅ 兼容(User Scenarios & Testing 与测试优先原则对齐)
- .specify/templates/tasks-template.md — ✅ 兼容(任务模板已包含测试任务分层,与 TDD 原则对齐)
- .specify/templates/commands/*.md — ✅ 无命令文件,无需更新
- README.md — ✅ 无宪法引用,无需更新

待办事项: 无(所有占位符均已填充)
-->

# 剪藏-GLEAN Constitution

## Core Principles

### I. 测试优先 (Test-First) — 不可协商

TDD 是本项目的强制开发纪律。所有新功能与缺陷修复 MUST 遵循 Red-Green-Refactor 循环:

- 先编写失败的测试,经用户/ reviewer 确认测试意图正确,再开始实现
- 实现代码的唯一目标是让测试通过,不允许在测试之外添加未被覆盖的行为
- 重构阶段 MUST 保持测试全绿,不得借重构之名引入未测试的分支
- 缺陷修复 MUST 先复现该缺陷的失败测试,再修复
- 任何未被测试覆盖的代码路径视为技术债, MUST 在下一个迭代中补齐

**理由**: GLEAN 依赖多个外部服务(B站 API、Firecrawl、Playwright、ASR 引擎),回归成本高;测试先行是锁定行为契约、抑制外部依赖波动的唯一可靠手段。

### II. 代码质量门禁 (Code Quality Gates)

所有合入主干的代码 MUST 通过以下静态质量门禁,无一例外:

- **静态检查**: `ruff check .` 零告警;`mypy --strict clipper/` 零错误
- **类型注解**: 所有公共函数、模块级变量 MUST 携带完整类型注解;`Any` 的使用 MUST 在注释中说明原因
- **格式化**: `ruff format .` 必须无差异;禁止人工调整格式
- **命名规范**: 模块/函数 `snake_case`;类 `PascalCase`;常量 `UPPER_SNAKE_CASE`;私有成员以单下划线前缀
- **函数复杂度**: 单函数圈复杂度 MUST ≤ 10;超过 MUST 拆分并附拆分说明
- **重复代码**: 重复块超过 15 行 MUST 抽取为共享函数或基类

**理由**: 统一的静态门禁是多人协作下维持代码可读性、可演进性的最低成本保障,远低于事后返工。

### III. 模块化与可测试性 (Modularity & Testability)

`clipper/` 下每个模块 MUST 满足「独立可测试」三条件:

- **单一职责**: 一个模块只解决一类剪藏场景(网页/视频/图片/文档/索引),禁止跨场景耦合业务逻辑
- **依赖显式**: 外部依赖(HTTP 客户端、文件系统、第三方 SDK)MUST 通过构造函数参数注入,禁止在模块内直接实例化具体实现
- **纯函数优先**: 无副作用的转换逻辑(HTML→Markdown、标题清洗、分类匹配)MUST 提取为纯函数,优先接受输入并返回输出,不触碰 I/O

违反以上任一条的模块 MUST 在 `Complexity Tracking` 中记录并附简化方案被驳回的理由。

**理由**: GLEAN 的模块天然按剪藏对象划分边界,模块化既是测试前提,也使各场景可独立演进而不互相拖累。

### IV. 集成测试与契约测试 (Integration & Contract Testing)

针对外部依赖的集成点 MUST 建立分层测试,严禁「只 Mock 不验证真实契约」:

- **契约测试**: B站 `bilibili-cli`、Firecrawl API、VideoCaptioner ASR 的输入输出结构 MUST 有契约测试固定;契约变更时测试 MUST 先于实现更新
- **集成测试**: 文件 I/O(写入 `clipped_pages/`、`_index.json`)、Playwright 截图、配置加载 MUST 有真实文件系统级别的集成测试
- **Mock 分层**: 单元测试用 Mock 隔离网络;集成测试 MUST 触达真实 I/O;契约测试 MUST 验证外部响应结构
- **ASR 回退链**: 火山引擎/必剪/剪映的分级回退路径 MUST 每条都有覆盖,不得只测主路径

**理由**: GLEAN 的稳定性瓶颈在外部依赖,仅靠单元测试无法暴露契约漂移与回退链失效。

### V. 可观测性与错误处理 (Observability & Error Handling)

所有运行路径 MUST 可观测、可诊断,错误 MUST 分类处理:

- **结构化日志**: 使用统一 logger,关键字段(`source`、`category`、`url`、`elapsed_ms`)MUST 随日志输出;禁止 `print` 直接输出业务信息
- **错误分类**: 外部依赖失败(网络/超时/限流)与内部逻辑错误 MUST 分开捕获;外部失败 MUST 实现优雅降级或回退,不得直接崩溃
- **可追溯来源**: 每条剪藏记录 MUST 保留原始 URL、抓取时间戳、抓取后端,写入 `_index.json` 以便回溯
- **ASR/截图回退**: `auto` 模式下后端失败 MUST 自动降级到下一个后端,并在日志中记录降级原因

**理由**: 剪藏是一次性不可重放的操作(原页可能下线),事后排障依赖完整的可观测链路,而非重新抓取。

## 质量标准 (Quality Standards)

以下为可量化、可自动校验的质量底线,CI MUST 拦截不达标的提交:

| 维度 | 指标 | 阈值 |
|------|------|------|
| 测试覆盖率 | `clipper/` 行覆盖率 | ≥ 80% |
| 测试覆盖率 | 新增/修改行覆盖率 | ≥ 90% |
| 代码复杂度 | 单函数圈复杂度 | ≤ 10 |
| 类型覆盖 | `mypy --strict` | 0 错误 |
| 静态检查 | `ruff check .` | 0 告警 |
| 文档覆盖 | 公共 API docstring | 100% |
| 依赖管理 | `requirements.txt` | 必须锁定版本(`==`) |

- **测试目录结构**: `tests/unit/`(纯函数/模块)、`tests/integration/`(文件 I/O、配置)、`tests/contract/`(外部 API 契约),与 `clipper/` 模块一一对应
- **测试命名**: `test_<被测模块>_<行为>_<条件>.py`,意图自解释
- **测试隔离**: 每个测试 MUST 自清理产生的临时文件,使用 `tmp_path` fixture,禁止污染工作区

## 开发工作流 (Development Workflow)

- **代码审查**: 所有合入主干的变更 MUST 至少经过一次人工审查;审查清单 MUST 包含五项核心原则的符合性核对
- **CI 门禁**: 提交触发 CI MUST 依次执行 `ruff check` → `ruff format --check` → `mypy --strict` → `pytest --cov`;任一失败禁止合并
- **提交规范**: 遵循 Conventional Commits(`feat:`、`fix:`、`test:`、`refactor:`、`docs:`、`chore:`);scope 指向 `clipper` 子模块名(如 `feat(asr): ...`)
- **分支策略**: 功能分支 `###-<feature-name>`;缺陷分支 `fix-<issue-id>`;主干保持随时可发布
- **提交粒度**: 一次提交只解决一件事;测试与实现可在同一提交,但 MUST 保证该提交整体测试通过

## Governance

本宪法是 GLEAN 项目的最高工程准则,在与其他实践冲突时以本宪法为准。

- **修正流程**: 任何原则的修订 MUST 提交 PR,附(a)修订理由、(b)受影响模块清单、(c)迁移计划;经至少一名 maintainer 审查通过后方可合并
- **版本策略**: 遵循语义化版本——原则移除或重定义为 MAJOR;新增原则或实质性扩展为 MINOR;措辞与笔误修正为 PATCH
- **合规审查**: 每次 release 前 MUST 重新核对项目与宪法的一致性;发现的违规项 MUST 记录为 issue 并排期修复,不得在 release notes 中隐瞒
- **运行时指引**: 日常开发遵循 `README.md` 与 `SKILL.md`;当两者与本宪法冲突时,以本宪法为准并提 issue 修正指引文档

**Version**: 1.0.0 | **Ratified**: 2026-07-04 | **Last Amended**: 2026-07-04
