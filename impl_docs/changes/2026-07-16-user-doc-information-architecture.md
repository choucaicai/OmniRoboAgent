# User Documentation Information Architecture

Date: 2026-07-16
Related plan: `impl_docs/plans/0011-user-doc-information-architecture.md`

## Changed

- 将用户文档导航重组为 Quickstart、Configuration、Agent Core、Framework Components、Custom Components 和 Benchmarks。
- 在 Configuration 后新增 Agent Core 总览，并为 Agent、Planner、Verifier 和 Memory 分别创建子页面。
- 在 Agent Core 后新增 Model Backend、Skill Backend、Pipeline、Runtime、Environment 和 Evaluation 页面。
- 将原本集中且逐渐过时的 `interfaces.md` 收敛为 framework component 总览，详细 contract 移入对应页面。
- 重写 Quickstart 和 Configuration，移除维护者绝对路径与固定 model/provider 主流程；将 checked-in YAML 明确标记为 benchmark smoke example。
- 更新根 README、EB-ALFRED 和 RoboCasa365 的 model service 表述；保留 benchmark 历史结果中的具体模型作为 verified evidence。
- 补充自定义 LLMBackend、Memory、Runtime 和 benchmark runner 的配置入口。

## Files

- `README.md`
- `docs/`
- `impl_docs/README.md`
- `impl_docs/TODO.md`
- `impl_docs/plans/0011-user-doc-information-architecture.md`
- `impl_docs/changes/2026-07-16-user-doc-information-architecture.md`
- `impl_docs/changes/2026-07-16-user-doc-skill-generality.md`

## Verification

```bash
conda run -n omniagent python -c "from omniroboagent.agent_core import BaseAgent, DefaultAgent, Planner, LanguageSkillPlanner, TaskSkillPlanner, SubtaskSkillPlanner, Verifier, EnvironmentVerifier, SubtaskVerifier, Memory, InMemoryMemory, JsonlMemory, TieredMemory; from omniroboagent.backends.llm import LLMBackend, OpenAICompatibleLLMBackend; from omniroboagent.backends.skills import SkillBackend; from omniroboagent.pipelines import Pipeline, DirectPipeline, SkillExecutionPipeline; from omniroboagent.runtimes import Runtime, SyncRuntime; from omniroboagent.environments import Environment; print('documented public imports: ok')"
```

返回 `documented public imports: ok`。

```bash
for f in README.md $(find docs -type f -name '*.md' | sort) \
  impl_docs/plans/0011-user-doc-information-architecture.md; do
  while IFS= read -r target; do
    target="${target%%#*}"
    target="${target%%\?*}"
    case "$target" in
      ''|http://*|https://*|mailto:*|'#'*) continue ;;
    esac
    test -e "$(dirname "$f")/$target" || printf '%s -> %s\n' "$f" "$target"
  done < <(perl -ne 'while (/\[[^]]+\]\(([^)]+)\)/g) { print "$1\n" }' "$f")
done
```

无缺失本地 Markdown links。单独解析 `docs/_sidebar.md` 后，全部 target 均存在于 `docs/`。

```bash
git diff --check -- README.md docs impl_docs
```

通过，本次文档修改无 whitespace error。全仓 `git diff --check` 仍会命中用户已有且本次未修改的 `src/omniroboagent/agent_core/planners/base.py:9: trailing whitespace`。

未运行代码测试；本次不修改 runtime code，已用 `omniagent` 环境验证文档列出的公开 imports。

## Remaining Work

- 无。
