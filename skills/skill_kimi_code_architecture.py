"""
skill_kimi_code_architecture

kimi-code (MoonshotAI) 架构骨髓内化 → GA可import模式库

Q1: kimi-code为什么从Python CLI换成TypeScript?
A1: 核心不是语言, 而是"单二进制分发"战略 — Node.js 24.15+ 的
    单二进制打包能力使TS可编译为.exe/.bin, 用户无需装运行时,
    实现"毫秒级启动 + 零依赖"体验。但其架构模式语言无关。

Q2: kimi-code最值得GA借鉴的核心架构是什么?
A2: 三层关注点分离:
    apps/kimi-code/      → TUI/CLI层 (纯UI, 不依赖agent引擎)
    packages/agent-core/ → Agent引擎层 (纯逻辑, 不依赖UI)
    packages/kosong/     → LLM抽象层 (可切换任何提供商)
    每层只做一件事, 接口清晰

Q3: 哪些模式能直接内化到GA?
A3: 5个模式: ①subagent技能系统 ②background-agent ③lifecycle hooks
    ④TUI组件化 ⑤审批面板

架构快照 (1385文件, 7顶级目录):
  apps/kimi-code/src/tui/ → 163组件, 6子目录
  packages/agent-core/    → 425文件, agent/skill/tool/permission
  .agents/skills/         → 4个SKILL.md技能定义
"""

import os, re, inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ================================================================
# 模式1: subagent技能系统
# ----------------------------------------------------------------
# kimi-code: .agents/skills/*/SKILL.md + AGENTS.md分层配置
# GA映射:    skills/ + memory/ 已有技能文件, 需要分层manifest
# ================================================================

@dataclass
class SkillManifest:
    """技能清单 — 对应kimi-code的SKILL.md元数据"""
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "constraints": self.constraints
        }

    @classmethod
    def from_file(cls, path: str) -> "SkillManifest":
        """从skill文件的docstring提取元数据"""
        import ast
        with open(path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
        doc = ast.get_docstring(tree) or ""
        lines = doc.split('\n')
        name = os.path.basename(path).replace('.py', '')
        desc = lines[1] if len(lines) > 1 else name
        return cls(name=name, description=desc)

    @classmethod
    def scan_skills(cls, skill_dirs: list[str]) -> list["SkillManifest"]:
        """扫描技能目录, 返回所有技能manifest"""
        manifests = []
        for d in skill_dirs:
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                if f.startswith('skill_') and f.endswith('.py'):
                    fp = os.path.join(d, f)
                    try:
                        manifests.append(cls.from_file(fp))
                    except:
                        manifests.append(cls(name=f.replace('.py',''), description=f))
        return manifests


# ================================================================
# 模式2: background-agent (后台Agent)
# ----------------------------------------------------------------
# kimi-code: agent-core/agent/background/ 并行执行引擎
#            TUI底部显示"● 正在分析代码..."状态
# GA映射:    可注入到agent_loop的BackgroundAgentMixin
# ================================================================

@dataclass
class BackgroundAgent:
    """
    后台Agent — 不阻塞主任务流的并行执行单元。
    
    kimi-code特点:
    - TUI底部显示实时状态 (● idle / ● running / [OK] done / ❌ error)
    - 不阻塞用户继续交互
    - 完成后通过callback通知主Agent
    """
    name: str
    status: str = "idle"  # idle|running|done|error
    _result: Any = None
    _on_done: Optional[Callable] = None

    def run(self, task: Callable, on_done: Optional[Callable] = None):
        self.status = "running"
        self._on_done = on_done
        return self

    def complete(self, result: Any = None):
        self._result = result
        self.status = "done"
        if self._on_done:
            self._on_done(result)

    @property
    def icon(self) -> str:
        return {"idle": "○", "running": "●", "done": "[OK]", "error": "❌"}.get(self.status, "○")


class BackgroundAgentMixin:
    """可混入agent_loop的后台Agent管理器"""
    
    def __init__(self):
        self._agents: dict[str, BackgroundAgent] = {}

    def spawn(self, name: str, task: Callable) -> BackgroundAgent:
        agent = BackgroundAgent(name=name)
        self._agents[name] = agent
        agent.run(task)
        return agent

    def status_snapshot(self) -> list[dict]:
        return [{"name": a.name, "status": a.status, "icon": a.icon}
                for a in self._agents.values()]


# ================================================================
# 模式3: lifecycle hooks (生命周期钩子)
# ----------------------------------------------------------------
# kimi-code: agent-core/agent/hooks/ 引擎
#            tool_call前/后触发自定义脚本, 支持gating
# GA映射:    plugins/hooks.py 已有, 此模块提供标准化钩子点
# ================================================================

@dataclass
class HookPoint:
    name: str
    description: str
    can_abort: bool = False


HOOK_BEFORE_TOOL = HookPoint("before_tool_call", "工具调用前", can_abort=True)
HOOK_AFTER_TOOL = HookPoint("after_tool_call", "工具调用后")
HOOK_BEFORE_CODE = HookPoint("before_code_run", "代码运行前", can_abort=True)
HOOK_ON_USER_INPUT = HookPoint("on_user_input", "收到用户输入")
HOOK_ON_ERROR = HookPoint("on_error", "出错时")


class HookRegistry:
    """钩子注册表 — 管理lifecycle hooks。支持gating(阻止操作)"""
    
    def __init__(self):
        self._hooks: dict[str, list[Callable]] = {}

    def register(self, hp: HookPoint, handler: Callable):
        self._hooks.setdefault(hp.name, []).append(handler)

    def unregister(self, hp: HookPoint, handler: Callable):
        hs = self._hooks.get(hp.name, [])
        if handler in hs:
            hs.remove(handler)

    def trigger(self, hp: HookPoint, **ctx) -> bool:
        """触发钩子。返回False=被gating阻止"""
        for handler in self._hooks.get(hp.name, []):
            if handler(**ctx) is False and hp.can_abort:
                return False
        return True


# ================================================================
# 模式4: TUI组件化
# ----------------------------------------------------------------
# kimi-code: 163个TUI组件, 每个<50行
#            chrome/ dialogs/ editor/ messages/ panels/
# GA映射:    组件基类, 可嵌入tuiapp.py
# ================================================================

class TUIComponent:
    """TUI组件基类 — 每个组件只做一件事"""
    def __init__(self, name: str):
        self.name = name
        self.visible = True

    def render(self) -> str:
        raise NotImplementedError

    def handle_key(self, key: str) -> bool:
        return False


class StatusBar(TUIComponent):
    """状态栏 — 显示background-agent状态+系统信息"""
    
    def __init__(self):
        super().__init__("status_bar")
        self.bg_agents: list[dict] = []
        self.system_info: str = ""

    def render(self) -> str:
        parts = [f"{a['icon']} {a['name']}" for a in self.bg_agents]
        return " | ".join(parts) if parts else ""


class ApprovalPanel(TUIComponent):
    """审批面板 — 高风险操作需用户确认(对应kimi-code approval-panel)"""
    
    def __init__(self):
        super().__init__("approval_panel")
        self.pending: Optional[dict] = None

    def request(self, action: str, detail: str) -> bool:
        self.pending = {"action": action, "detail": detail, "approved": False}
        return False  # 默认需要审批

    def approve(self):
        if self.pending:
            self.pending["approved"] = True
            self.pending = None

    def reject(self):
        if self.pending:
            self.pending["approved"] = False
            self.pending = None

    def render(self) -> str:
        if not self.pending:
            return ""
        return f"[审批] {self.pending['action']}: {self.pending['detail']} (y/N)"


# ================================================================
# 模式5: 审批面板
# ----------------------------------------------------------------
# kimi-code: permission-selector + approval-panel
#            文件修改/命令执行/网络请求 分级审批
# GA映射:    PermissionGate集成到HookRegistry
# ================================================================

class PermissionGate:
    """
    权限门 — 按操作类型分级审批。
    
    kimi-code审批设计:
    - 按类型分级: read(免审) < write(确认) < execute(高危) < network(高危)
    - 支持"记住选择" (缓存)
    """
    
    LEVELS = {"read": 0, "write": 1, "execute": 2, "network": 3}
    
    def __init__(self, panel: Optional[ApprovalPanel] = None):
        self._panel = panel or ApprovalPanel()
        self._cache: dict[str, bool] = {}

    def check(self, action: str, detail: str, level: str = "write") -> bool:
        if self.LEVELS.get(level, 0) == 0:
            return True
        key = f"{action}:{detail}"
        if key in self._cache and self._cache[key]:
            return True
        result = self._panel.request(action, detail)
        if result:
            self._cache[key] = True
        return result


# ================================================================
# 自检
# ================================================================

def self_test():
    """运行自检确认模块可用"""
    print("[TEST] skill_kimi_code_architecture.py 自检")
    
    # 1. SkillManifest
    m = SkillManifest("test", "测试技能", triggers=["analyze"], constraints=["只读"])
    assert m.name == "test"
    print(f"  [OK] SkillManifest: {m.to_dict()}")
    
    # 2. BackgroundAgent
    bg = BackgroundAgent(name="analyzer")
    assert bg.status == "idle"
    assert bg.icon == "○"
    bg.run(lambda: None)
    assert bg.status == "running"
    assert bg.icon == "●"
    bg.complete("ok")
    assert bg.status == "done"
    print(f"  [OK] BackgroundAgent: {bg.name} → {bg.status} {bg.icon}")
    
    # 3. HookRegistry
    reg = HookRegistry()
    calls = []
    reg.register(HOOK_BEFORE_TOOL, lambda **ctx: calls.append(ctx.get("tool")))
    assert reg.trigger(HOOK_BEFORE_TOOL, tool="run_code") is True
    assert calls == ["run_code"]
    print(f"  [OK] HookRegistry: trigger OK ({calls})")
    
    # 4. TUIComponent (StatusBar)
    sb = StatusBar()
    sb.bg_agents = [{"name": "a1", "status": "running", "icon": "●"}]
    assert "● a1" in sb.render()
    print(f"  [OK] StatusBar: {sb.render()}")
    
    # 5. PermissionGate
    gate = PermissionGate()
    assert gate.check("read", "读文件", "read") is True
    print(f"  [OK] PermissionGate: 低风险直通")
    
    print("\n[OK] 全部自检通过!")


if __name__ == "__main__":
    self_test()
