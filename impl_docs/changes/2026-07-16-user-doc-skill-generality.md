# General User Documentation Skill

Date: 2026-07-16
Related plan: N/A

## Changed

- 将 `update-omniroboagent-user-docs` 的目标目录从已失效的 `tutorial_docs/` 修正为当前 `docs/`。
- 增加按首次使用者、模型或 benchmark 使用者、组件扩展开发者组织教程的要求。
- 要求按 framework contract、内置 adapter 及其协议要求、可选 provider 示例三层描述模型集成。
- 明确 `OpenAICompatibleLLMBackend` 是 provider-neutral protocol adapter，而不是任一 serving stack 的专用 integration；其他协议通过自定义 `LLMBackend + class_path` 扩展。
- 禁止把任意单一 provider 或 serving stack 写成项目级前置条件、默认或唯一主流程；个人模型、endpoint、绝对路径、环境、硬件和 checkpoint 也不得写成框架默认。
- 允许保留明确标注范围的 verified example，并要求区分已实现、已验证、协议兼容但未验证三种状态。
- 修正 `update-omniroboagent-impl-docs` 中残留的 `tutorial_docs/` 路径，使两个文档 skill 都指向当前 `docs/`。

## Files

- `.agents/skills/update-omniroboagent-user-docs/SKILL.md`
- `.agents/skills/update-omniroboagent-user-docs/agents/openai.yaml`
- `.agents/skills/update-omniroboagent-impl-docs/SKILL.md`
- `impl_docs/TODO.md`
- `impl_docs/changes/2026-07-16-user-doc-skill-generality.md`

## Verification

```bash
python /home/zzz/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/update-omniroboagent-user-docs
python /home/zzz/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/update-omniroboagent-impl-docs
```

两个命令均返回 `Skill is valid!`。

```bash
for f in .agents/skills/update-omniroboagent-user-docs/SKILL.md \
  .agents/skills/update-omniroboagent-impl-docs/SKILL.md \
  impl_docs/TODO.md \
  impl_docs/changes/2026-07-16-user-doc-skill-generality.md; do
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

无缺失链接输出。

```bash
git diff --check -- \
  .agents/skills/update-omniroboagent-user-docs \
  .agents/skills/update-omniroboagent-impl-docs \
  impl_docs/TODO.md \
  impl_docs/changes/2026-07-16-user-doc-skill-generality.md
```

通过，本次修改无 whitespace error。全仓 `git diff --check` 仍会命中用户已有且未由本次修改触碰的 `src/omniroboagent/agent_core/planners/base.py:9: trailing whitespace`。

未运行代码测试；本次只修改项目级文档维护 skill 和状态文档，不改变运行时代码。

## Remaining Work

- 已由 `impl_docs/plans/0011-user-doc-information-architecture.md` 完成 `README.md` 和 `docs/` 审计与重组。
