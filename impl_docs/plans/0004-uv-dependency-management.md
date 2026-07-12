# uv Dependency Management

Status: DONE

## Goal

使用 `uv` 统一解析、锁定、安装和运行 OmniRoboAgent 依赖，减少基础开发和 EB-ALFRED 环境的手工安装步骤。

## Scope

- 使用 `pyproject.toml` 声明 runtime、development、OpenPI 和 EB-ALFRED 依赖。
- 生成并提交 `uv.lock`。
- 基础依赖安装到 `omniagent`，benchmark 依赖安装到各自独立 Conda 环境。
- 将安装、测试和 EB-ALFRED 启动文档改为 `uv` 命令。
- 不修改第三方 submodule 源码，不管理 vLLM server 进程或 EB-ALFRED dataset。

## Tasks

- [x] 更新 dependency groups、optional extras 和 uv source 配置。
- [x] 生成 lockfile，并验证基础环境同步。
- [x] 更新运行脚本和当前使用文档。
- [x] 运行 unit tests、Ruff、mypy 和文档一致性检查。

## Acceptance

- `uv lock --check` 通过。
- `uv pip install` 能明确使用目标 Conda Python 解析项目依赖。
- pytest、Ruff 和 mypy 在 `omniagent` 中通过。
- README 包含 clone、安装 optional extras、测试和启动命令。

Change record: [`../changes/2026-07-12-uv-dependency-management.md`](../changes/2026-07-12-uv-dependency-management.md)
