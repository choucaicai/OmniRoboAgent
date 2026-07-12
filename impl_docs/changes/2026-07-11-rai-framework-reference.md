# RAI Framework Reference

Date: 2026-07-11
Related plan: N/A

## Changed

- 基于本地 RAI commit `e54f8ca995dc80cc3e058171500948a24129b302` 编写源码分析文档。
- 说明 RAI 的 Agent、LangGraph、LLM、tool、多模态、ROS2、WhoAmI、memory、simulation、benchmark 和 fine-tuning 模块。
- 区分 RAI 已实现能力、实验性模块和未完成路径。
- 对比 RAI 与 OmniRoboAgent 的模块边界，并记录建议借鉴和不建议继承的设计。
- 在文档索引中增加 `reference/` 目录。

## Files

- `impl_docs/reference/rai-framework-analysis.md`
- `impl_docs/README.md`
- `impl_docs/changes/2026-07-11-rai-framework-reference.md`

## Verification

- 检查文档中引用的本地源码路径存在。
- 检查 Markdown 相对链接可以解析。
- 检查 Markdown 尾随空白。
- 本次未修改 RAI 或 OmniRoboAgent 运行代码，因此不运行代码测试。

## Remaining Work

- 实现 OmniRoboAgent ROS2 integration 前，决定直接使用 RAI connector 还是基于 `rclpy` 实现更小的 adapter。
- RAI 上游版本变化后，按文档记录的 commit 重新核对实验性模块状态。
