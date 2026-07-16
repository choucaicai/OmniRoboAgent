# User Documentation Information Architecture

Status: DONE

## Objective

将 `docs/` 从单一 interface 汇总页重组为面向不同使用者的框架教程。配置说明之后先介绍 Agent Core，并为 Agent、Planner、Verifier、Memory 提供独立页面；随后介绍 backends、Pipeline、Runtime、Environment 和 Evaluation。

## Scope

- 重写 `docs/README.md`、`docs/_sidebar.md`、`docs/quickstart.md`、`docs/configuration.md` 和 `docs/interfaces.md` 的入口与导航。
- 新增 `docs/agent_core/`，分别介绍 Agent Core 总览、Agent、Planner、Verifier 和 Memory。
- 新增 `docs/components/`，分别介绍 model backend、skill backend、Pipeline、Runtime、Environment 和 Evaluation。
- 更新 `docs/custom_components.md` 与根 `README.md` 的文档链接。
- 保持 `docs/eb_alfred.md` 和 `docs/robocasa365.md` 作为 benchmark-specific 指南，只修正与新导航直接相关的链接或表述。

## Content Rules

- 以当前 `src/omniroboagent/`、`configs/` 和 tests 为事实来源。
- 先说明 contract、ownership 和替换边界，再列当前实现。
- 不把任意 model provider、serving stack、endpoint、模型、checkpoint 或本机路径写成框架前置条件或项目级默认。
- 将已验证的具体配置标记为 example，不把实验结果混入通用 quickstart。
- 所有命令默认从 repository root 运行，避免维护者绝对路径。

## Tasks

- [x] 建立首页与 sidebar 的新导航顺序。
- [x] 拆分 Agent Core 总览及四个子组件页面。
- [x] 增加六个非 Agent Core framework component 页面。
- [x] 更新 quickstart、configuration、interfaces 和 custom component 入口。
- [x] 同步根 README、TODO 和 change record。
- [x] 校验本地 Markdown links、Docsify sidebar targets 和 whitespace。

## Acceptance

- `Configuration` 后紧接 `Agent Core`，且 Agent、Planner、Verifier、Memory 均有独立可导航页面。
- Agent Core 后按执行链介绍 Model Backend、Skill Backend、Pipeline、Runtime、Environment 和 Evaluation。
- Quickstart 不依赖维护者绝对路径或某个固定 model provider。
- 文档准确区分 framework contract、内置实现、provider-compatible 但未验证的实现和 benchmark-specific verified example。
- 所有新增或修改的本地 Markdown links 有效，`git diff --check` 对本次文件通过。
