# Cursor Agent Skills（无需 Teams）

Cursor 里点 **Publish** 会要求加入 **Team marketplace**，那是 Teams/Enterprise 付费功能。个人账号没有「团队」就会卡住——正常。

## 不买团队也能用

本仓把可复用配方放在 `.cursor/skills/*/SKILL.md`。任选其一：

1. **克隆后本地用**
   ```bash
   git clone https://github.com/liuliuwenzheng/FHLS-skills.git
   # 在 Cursor 打开该仓，或把 .cursor/skills 拷到你的项目 / ~/.cursor/skills/
   ```
2. **拷到自己项目**（Cloud Agent 也能读仓内技能）
   ```bash
   cp -R FHLS-skills/.cursor/skills/agent-trust-ladder your-repo/.cursor/skills/
   cp -R FHLS-skills/.cursor/skills/capability-guide-post your-repo/.cursor/skills/
   ```
3. **Grok Bot** 侧已有同名技能时，直接在聊天里 @ 即可，不必 Publish。

## 本仓已收录

| 技能 | 何时用 |
|------|--------|
| [agent-trust-ladder](.cursor/skills/agent-trust-ladder/SKILL.md) | 纠正 agent、升信任再并行 |
| [capability-guide-post](.cursor/skills/capability-guide-post/SKILL.md) | 写「产品能力说明书」式长文 |

与 `skills/skill_*.py`（可 import 的 Python 模块）是两套东西：Python 技能给程序调用；`.cursor/skills` 给 Cursor / Grok Bot 配方用。
