# Documentation Skills

Date: 2026-07-12
Related plan: N/A

## Changed

- 新增 `update-omniroboagent-user-docs` skill，约束 `tutorial_docs/` 和根 `README.md` 的用户文档同步流程。
- 新增 `update-omniroboagent-impl-docs` skill，约束架构、计划、TODO、reference 和 change record 的同步流程。
- 明确公开行为或架构同时变化时，两个 skill 需要互相联动。

## Files

- `.agents/skills/update-omniroboagent-user-docs/`
- `.agents/skills/update-omniroboagent-impl-docs/`
- `impl_docs/changes/2026-07-12-documentation-skills.md`

## Verification

```bash
python /home/zzz/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/update-omniroboagent-user-docs
python /home/zzz/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/update-omniroboagent-impl-docs
```

验证结果：两个 skill 均返回 `Skill is valid!`。

```bash
git diff --check
```

验证结果：通过，无 whitespace error。

## Remaining Work

- 无。
