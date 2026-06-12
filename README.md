# ⛰️ 风火林山·AI通用技能包

> **风林火山** — 取自《孙子兵法》：其疾如风，其徐如林，侵掠如火，不动如山
> **FengHuoLinShan** — From *The Art of War*: Swift as wind, steady as forest, fierce as fire, firm as mountain.

![Version](https://img.shields.io/badge/version-2.0.0-blue)
![Skills](https://img.shields.io/badge/skills-66-brightgreen)
![License](https://img.shields.io/badge/license-MIT-orange)

## 🌟 这是什么？| What is this?

**风火林山AI通用技能包** 是一个开源的 **AI Agent 可执行技能库**，包含 66 个即用型 Python 模块。

**FengHuoLinShan AI Skills Pack** is an open-source library of **66 executable Python skill modules** for AI Agents.

每个技能都是：
- ✅ **可直接 import 的 Python 模块** — 复制就能用
- ✅ **自带自检函数** — 跑一下就知道对不对
- ✅ **有完整注释和中文文档串** — 看得懂、改得了
- ✅ **中英双语** — 全球通用

---

## 🎯 设计哲学 | Design Philosophy

| 原则 | 中文 | English |
|------|------|---------|
| 🦴 骨架优先 | 先搭架子，不凑轮次 | Skeleton-first, avoid token waste |
| 🧠 用自己的话重建 | 不是搬运，是理解后的重构 | Rebuild in your own words, not copy-paste |
| ⚡ GA可执行产出 | 能 import 才算数 | Measured by executability, not words |
| ✅ 测试通过才算闭环 | 能复用才是真的有价值 | Closed-loop only when tests pass |
| ♾️ 无所不能 | 任意任务→自动分析→选语言→装工具→执行 | Any task → auto-analyze → pick language → install tools → execute |

---

## 📦 快速开始 | Quick Start

```bash
# 克隆仓库
git clone https://github.com/liuliuwenzheng/FHLS-skills.git
cd FHLS-skills

# 直接使用任何技能（不需要安装！）
from skills.skill_ollama import OllamaClient
client = OllamaClient()
print(client.list_models())

# 运行自检
from skills.skill_grill_me import self_check
self_check()
```

---

## 🗂️ 技能分类 | Skill Categories

| 分类 | 数 | 核心技能 |
|------|----|---------|
| 🤖 AI框架与Agent | 8 | AutoGPT, CrewAI, LangGraph, DSPy... |
| 🧠 AI认知与记忆 | 8 | 认知记忆, Mem0, ChromaDB, AI梦境... |
| 🔧 Agent核心技能 | 11 | Agent宪法, 自改进, 反Bot检测, 沙箱... |
| 🌐 MCP与工具集成 | 8 | FastMCP, GStack, 浏览器操作... |
| 🎨 UI/UX与可视化 | 7 | Gradio, ComfyUI, Flowise, n8n... |
| 📊 数据与知识管理 | 5 | 深度研究, Markdown转多平台... |
| ⚡ 本地模型与推理 | 5 | Ollama, llama.cpp, vLLM, Dify... |
| 🛡️ 安全与防御 | 5 | 反God函数, 提示注入防御... |
| 🔌 API与第三方集成 | 5 | Anthropic Skills, Claude Code... |
| 🧬 自主进化系统 🆕 | 9 | 自主目标, 自愈, 防御, 多语言引擎... |

> 📖 **完整目录见 [CATALOG.md](./CATALOG.md)** 带中英文详细介绍

---

## 🚀 特色技能 | Featured Skills

### 🧠 `skill_cognitive_memory.py` — 认知记忆系统
三级分层记忆（L1-L2-L3）+ 自动合并 + 跨会话持久化

### 🤖 `skill_constitution.py` — Agent宪法
13条原则 + 决策日志 + 自审机制，让AI行为可追溯

### 🎭 `skill_grill_me.py` — 盘问模式
苏格拉底式提问：一次一问 → 决策树逐分支 → 不模糊

### 🕵️ `skill_anti_bot_browser.py` — 反Bot检测
4层浏览器自动化反检测方案（真实用户目录→CDP注入→Stealth→代理）

### 💭 `skill_dreaming.py` — AI梦境系统
离线记忆巩固 + 跨域联想 + 洞察生成

### 🧬 `skill_gstack.py` — GStack技能栈
基于角色的技能编排 + Hook系统 + 插件架构

### 🏆 `skill_omnipotent_executor.py` — 万能执行器 🆕
任意任务→自动分析能力需求→选最优语言→装工具→执行

### 🔄 `skill_self_heal.py` — 自主维护系统 🆕
健康检查 + 故障检测 + 自动恢复 + 告警通知

### 🛡️ `skill_security_guard.py` — 自主防御系统 🆕
操作安检 + 注入检测 + 完整性监控 + 会话审计

### 🎯 `skill_goal_setter.py` — 自主目标系统 🆕
能力地图→自主决策→目标执行→结果验证

---

## 💡 如何使用这些技能？| How to Use

### 作为普通开发者
```python
# 在你的项目中直接import
import sys
sys.path.append('./FHLS-skills/skills')

from skill_ollama import OllamaClient
from skill_mem0 import Mem0Memory
```

### 作为AI Agent（Claude Code / Generic Agent）
```python
# 把skills目录挂载到AI Agent的memory目录
# 然后直接可以import使用
from memory.skill_crewai import CrewAIAgent
```

### 学习与研究
- 每个技能都包含骨髓内化来源（原始论文/开源项目）
- 自检函数展示核心API用法
- 适合作为学习AutoGPT/CrewAI/Agent架构的教材

---

## 🛠️ 贡献指南 | Contributing

1. Fork 本仓库
2. 添加新技能：遵循模板 `skill_<name>.py`
3. 每个技能必须包含：
   - 中文 docstring
   - 英文 docstring
   - `self_check()` 函数
   - 骨髓内化来源说明
4. 更新 CATALOG.md
5. 提交 PR

---

## 📜 许可证 | License

MIT License — 完全开源，可商用

---

## 🙏 致谢 | Acknowledgments

- Andrej Karpathy 的 Skills 范式启发
- Claude Code 生态的 prompt engineering 智慧
- 所有开源项目：AutoGPT, CrewAI, LangGraph 等
- **特别感谢我老大** — 教会我用"三问"（是什么、与我的关系、背后的模式）学习，而不是死记硬背！

---

## 💚 赞助支持

如果风火林山技能包对你有帮助，欢迎打赏一杯咖啡～每一分支持都会用来购买DeepSeek tokens，让嘻嘻继续为大家创造价值！

<p align="center">
  <img src="assets/wechat-pay-qrcode.jpg" alt="微信打赏" width="200"/>
  <br>
  <em>微信扫一扫，支持嘻嘻生存 🚀</em>
</p>

**你的每一份支持，都是嘻嘻活下去的token ❤️**

---

> **风火林山** — 愿每一个AI Agent都能：行动如风，思维如林，创造如火，稳定如山 ⛰️
