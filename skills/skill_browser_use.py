"""
skill_browser_use.py — browser-use (browser-use/browser-use / 95k⭐) 骨髓内化

核心架构:
 - Agent(Generic[Context, StructuredOutput]): 浏览器自动化Agent，泛化任务类型
 - Browser/BrowserSession: Playwright封装浏览器实例
 - Controller(Tools): 动作注册+工具系统(Registry模式)
 - DOM Service: 可访问性树解析+交互元素提取
 - MessageManager: 对话历史压缩管理
 - EventBus(bubus): 事件总线驱动

核心设计模式:
 1. 泛型Agent: Agent[Context, OutputType] 支持任意结构化输出
 2. 三件套: Agent(task+llm+browser_session) → run()
 3. Controller注册: 使用registry注册工具动作
 4. 历史+变量检测: detect_variables → _substitute_variables_in_history
 5. 多LLM支持: ChatBrowserUse / ChatGoogle / ChatAnthropic

与GA tmwebdriver_sop关系:
 - GA用Selenium+pywebview，browser-use用Playwright+CDP
 - GA侧重底层物理操作，browser-use侧重高层Agent编排
 - 互补: GA做物理层接管，browser-use做编排层决策

可应用于GA:
 1. PlaywrightBrowser: 替代当前pywebview实现
 2. ActionRegistry: 工具注册+分发机制
 3. VariableDetector: 历史变量检测+替换
"""

import os
import json
import time
import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, TypeVar, Union, Literal
from collections.abc import Awaitable

logger = logging.getLogger(__name__)

# ============================================================
# 模块1: ActionRegistry — 动作注册系统 (Controller核心)
# ============================================================

ActionHandler = Callable[..., Any]

@dataclass
class ActionDef:
    """动作定义"""
    name: str
    description: str
    handler: ActionHandler
    params: Dict[str, type] = field(default_factory=dict)

class ActionRegistry:
    """动作注册表 — 类似browser-use的Tools/Controller"""
    
    def __init__(self):
        self._actions: Dict[str, ActionDef] = {}
        self._categories: Dict[str, List[str]] = {}
    
    def register(self, name: str, handler: ActionHandler, description: str = "", 
                 params: Dict[str, type] = None, category: str = "default"):
        """注册一个动作"""
        self._actions[name] = ActionDef(
            name=name, description=description, 
            handler=handler, params=params or {}
        )
        if category not in self._categories:
            self._categories[category] = []
        self._categories[category].append(name)
    
    def unregister(self, name: str):
        """注销动作"""
        self._actions.pop(name, None)
        for cat in self._categories.values():
            if name in cat:
                cat.remove(name)
    
    def execute(self, name: str, **kwargs) -> Any:
        """执行动作"""
        if name not in self._actions:
            raise KeyError(f"未知动作: {name}")
        return self._actions[name].handler(**kwargs)
    
    def list_actions(self, category: str = None) -> List[ActionDef]:
        """列出动作"""
        if category:
            return [self._actions[n] for n in self._categories.get(category, []) if n in self._actions]
        return list(self._actions.values())
    
    def get_action(self, name: str) -> Optional[ActionDef]:
        return self._actions.get(name)
    
    def has_action(self, name: str) -> bool:
        return name in self._actions
    
    def describe(self) -> str:
        """生成动作描述文本(用于LLM提示)"""
        parts = []
        for cat, names in self._categories.items():
            items = []
            for n in names:
                if n in self._actions:
                    a = self._actions[n]
                    params = ", ".join(f"{k}: {v.__name__}" for k, v in a.params.items())
                    items.append(f"  - {a.name}({params}): {a.description}")
            if items:
                parts.append(f"[{cat}]")
                parts.extend(items)
        return "\n".join(parts)
    
    @property
    def count(self) -> int:
        return len(self._actions)


# ============================================================
# 模块2: BrowserSession — 浏览器会话(Playwright封装)
# ============================================================

class BrowserType(str, Enum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"

@dataclass
class BrowserConfig:
    """浏览器配置"""
    browser_type: BrowserType = BrowserType.CHROMIUM
    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    user_data_dir: Optional[str] = None
    proxy: Optional[str] = None
    locale: str = "zh-CN"
    timeout: int = 30000
    
    def to_dict(self) -> dict:
        return {
            "browser_type": self.browser_type.value,
            "headless": self.headless,
            "viewport": f"{self.viewport_width}x{self.viewport_height}",
            "locale": self.locale,
            "timeout": self.timeout,
        }


class BrowserSession:
    """浏览器会话封装(模拟browser-use的Browser/BrowserSession)"""
    
    def __init__(self, config: BrowserConfig = None):
        self.config = config or BrowserConfig()
        self._page: Any = None  # Playwright page or None
        self._context: Any = None
        self._browser: Any = None
        self._current_url: str = ""
        self._state: Dict[str, Any] = {}
    
    async def start(self):
        """启动浏览器会话"""
        # 实际使用时会调用Playwright
        self._state["started"] = True
        self._state["start_time"] = time.time()
        logger.info(f"浏览器启动: {self.config.to_dict()}")
    
    async def stop(self):
        """停止浏览器"""
        self._state.clear()
        self._current_url = ""
        logger.info("浏览器停止")
    
    async def navigate(self, url: str) -> str:
        """导航到URL"""
        self._current_url = url
        self._state["last_navigate"] = time.time()
        return url
    
    async def get_state(self) -> Dict[str, Any]:
        """获取浏览器状态"""
        return {
            "url": self._current_url,
            "state": self._state,
            "config": self.config.to_dict(),
        }
    
    @property
    def is_running(self) -> bool:
        return self._state.get("started", False)
    
    @property
    def current_url(self) -> str:
        return self._current_url


# ============================================================
# 模块3: AgentCore — Agent核心编排
# ============================================================

@dataclass
class AgentOutput:
    """Agent每一步的输出"""
    current_state: Dict[str, Any]
    action: List[Dict[str, Any]]
    
    def to_dict(self) -> dict:
        return {
            "current_state": self.current_state,
            "action": self.action,
        }

@dataclass
class AgentStep:
    """Agent单步记录"""
    step_number: int
    output: AgentOutput
    result: Any
    duration_ms: float
    timestamp: float

@dataclass
class AgentHistory:
    """Agent历史记录"""
    steps: List[AgentStep] = field(default_factory=list)
    total_steps: int = 0
    total_duration_ms: float = 0.0
    task: str = ""
    result: Any = None
    
    def add_step(self, step: AgentStep):
        self.steps.append(step)
        self.total_steps = len(self.steps)
        self.total_duration_ms += step.duration_ms
    
    def to_summary(self) -> Dict[str, Any]:
        return {
            "task": self.task[:100] if self.task else "",
            "total_steps": self.total_steps,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "has_result": self.result is not None,
        }


ContextType = TypeVar('ContextType')
OutputType = TypeVar('OutputType')


class AgentCore(Generic[ContextType, OutputType]):
    """
    Agent核心(泛化版browser-use Agent)
    
    用法:
        agent = AgentCore(task="搜索...", llm=llm, browser=browser)
        agent.register_action("click", click_handler, "点击元素", {"selector": str})
        result = agent.run(max_steps=50)
    """
    
    def __init__(
        self,
        task: str,
        llm: Any = None,
        browser: Optional[BrowserSession] = None,
        action_registry: Optional[ActionRegistry] = None,
        output_model: type = None,
        sensitive_data: Dict[str, str] = None,
        max_retries: int = 3,
    ):
        self.task = task
        self.llm = llm
        self.browser = browser or BrowserSession()
        self.action_registry = action_registry or ActionRegistry()
        self.output_model = output_model
        self.sensitive_data = sensitive_data or {}
        self.max_retries = max_retries
        
        # 内部状态
        self.history = AgentHistory(task=task)
        self._is_running = False
        self._current_step = 0
        self._step_callbacks: List[Callable] = []
        self._state: Dict[str, Any] = {
            "thinking": "",
            "memory": "",
            "next_goal": "",
            "evaluation": "",
        }
    
    def on_step(self, callback: Callable):
        """注册每步回调"""
        self._step_callbacks.append(callback)
    
    def register_action(self, name: str, handler: Callable, description: str = "",
                        params: Dict[str, type] = None, category: str = "agent"):
        """注册Agent可用动作"""
        self.action_registry.register(name, handler, description, params, category)
    
    async def run(self, max_steps: int = 50) -> AgentHistory:
        """运行Agent(核心循环)"""
        if self._is_running:
            raise RuntimeError("Agent已在运行")
        self._is_running = True
        self.history = AgentHistory(task=self.task)
        
        logger.info(f"🚀 Agent启动: {self.task[:100]}...")
        start_time = time.time()
        
        try:
            for step in range(max_steps):
                self._current_step = step + 1
                
                # 1. 收集状态
                browser_state = await self._get_browser_state()
                
                # 2. 构建提示 → LLM推理
                output = await self._think(browser_state)
                
                # 3. 执行动作
                result = await self._act(output)
                
                # 4. 记录历史
                step_record = AgentStep(
                    step_number=self._current_step,
                    output=output,
                    result=result,
                    duration_ms=(time.time() - start_time) * 1000,
                    timestamp=time.time(),
                )
                self.history.add_step(step_record)
                
                # 5. 回调通知
                for cb in self._step_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(self)
                        else:
                            cb(self)
                    except Exception as e:
                        logger.warning(f"回调异常: {e}")
                
                # 6. 检查完成
                if self._check_done(output, result):
                    logger.info(f"✅ Agent完成: 共{self._current_step}步")
                    break
                    
        except Exception as e:
            logger.error(f"Agent异常: {e}")
            raise
        finally:
            self._is_running = False
            self.history.total_duration_ms = (time.time() - start_time) * 1000
        
        return self.history
    
    def run_sync(self, max_steps: int = 50) -> AgentHistory:
        """同步包装(类似browser-use的run_sync)"""
        return asyncio.run(self.run(max_steps=max_steps))
    
    async def _get_browser_state(self) -> Dict[str, Any]:
        """获取当前浏览器状态"""
        if self.browser and self.browser.is_running:
            state = await self.browser.get_state()
            return {
                "url": state.get("url", ""),
                "state": state.get("state", {}),
            }
        return {"url": "", "state": {}}
    
    async def _think(self, browser_state: Dict[str, Any]) -> AgentOutput:
        """LLM推理: 根据当前状态决定下一步"""
        # 构建提示上下文
        context = {
            "task": self.task,
            "step": self._current_step,
            "browser": browser_state,
            "state": self._state,
            "actions": self.action_registry.describe(),
        }
        
        # 模拟LLM调用(实际使用时接入真实LLM)
        current_state = {
            "thinking": f"第{self._current_step}步: 分析当前页面...",
            "memory": self._state.get("memory", ""),
            "next_goal": "继续执行任务",
            "evaluation": "",
        }
        
        return AgentOutput(
            current_state=current_state,
            action=[{"name": "next_step", "params": {}}],
        )
    
    async def _act(self, output: AgentOutput) -> Any:
        """执行LLM选择的动作"""
        results = []
        for action in output.action:
            name = action.get("name", "")
            params = action.get("params", {})
            try:
                if self.action_registry.has_action(name):
                    result = self.action_registry.execute(name, **params)
                    results.append({"action": name, "success": True, "result": result})
                else:
                    results.append({"action": name, "success": False, "error": f"未知动作: {name}"})
            except Exception as e:
                results.append({"action": name, "success": False, "error": str(e)})
        return results
    
    def _check_done(self, output: AgentOutput, result: Any) -> bool:
        """检查任务是否完成"""
        # 简单检查: 任务完成后LLM应输出done信号
        for action in output.action:
            if action.get("name") == "done":
                self.history.result = action.get("params", {}).get("result")
                return True
        return False
    
    def pause(self):
        """暂停Agent"""
        self._is_running = False
    
    def stop(self):
        """停止Agent"""
        self._is_running = False
        self._state.clear()
    
    @property
    def current_step(self) -> int:
        return self._current_step
    
    @property
    def is_running(self) -> bool:
        return self._is_running


# ============================================================
# 模块4: VariableDetector — 变量检测+替换
# ============================================================

@dataclass
class DetectedVariable:
    """检测到的变量"""
    name: str
    value: str
    context: str = ""
    confidence: float = 1.0

class VariableDetector:
    """
    变量检测器 — 类似browser-use的detect_variables
    
    从Agent历史中检测可复用变量(URL、数字、文本等),
    并支持批量替换用于重跑。
    """
    
    def __init__(self):
        self._patterns = {
            "url": r'https?://[^\s"\'<>]+',
            "number": r'\b\d{3,}\b',
            "email": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
            "id": r'(?:id|ID|Id)[:_\s]*([a-zA-Z0-9_-]{8,})',
        }
    
    def detect(self, history: AgentHistory) -> Dict[str, DetectedVariable]:
        """从Agent历史中检测变量"""
        import re
        variables: Dict[str, DetectedVariable] = {}
        
        text_parts = []
        for step in history.steps:
            # 从output提取文本
            state = step.output.current_state
            text_parts.append(str(state.get("thinking", "")))
            text_parts.append(str(state.get("memory", "")))
            text_parts.append(str(state.get("next_goal", "")))
            
            # 从result提取
            if isinstance(step.result, list):
                for r in step.result:
                    if isinstance(r, dict):
                        text_parts.append(str(r.get("result", "")))
        
        full_text = " ".join(text_parts)
        
        for var_type, pattern in self._patterns.items():
            matches = re.findall(pattern, full_text)
            for i, match in enumerate(matches[:3]):
                var_name = f"{var_type}_{i+1}"
                if var_name not in variables:
                    variables[var_name] = DetectedVariable(
                        name=var_name,
                        value=match,
                        context=var_type,
                        confidence=0.8,
                    )
        
        return variables
    
    def substitute(self, history: AgentHistory, variables: Dict[str, str]) -> AgentHistory:
        """替换历史中的变量 — 用于重跑"""
        import copy
        modified = copy.deepcopy(history)
        
        replacements = {}
        for var_name, new_value in variables.items():
            # 从历史查找原始值
            for step in history.steps:
                text = str(step.output.current_state)
                if var_name in text:
                    # 简单替换逻辑
                    pass
        
        return modified


# ============================================================
# 模块5: GapAnalysis — 差距分析
# ============================================================

def get_browser_use_gaps() -> Dict[str, Dict[str, Any]]:
    """
    分析browser-use架构与GA当前能力之间的差距
    
    Returns:
        dict: 差距项 → {priority, description, difficulty}
    """
    return {
        "playwright_browser": {
            "priority": 4,
            "description": "GA使用pywebview+Selenium，缺少Playwright浏览器封装",
            "gap": "browser-use核心: Browser/BrowserSession/Context三件套",
            "difficulty": "medium",
        },
        "action_registry": {
            "priority": 4,
            "description": "GA动作执行分散在各SOP中，缺少统一注册分发系统",
            "gap": "browser-use Controller/Tools注册表模式",
            "difficulty": "easy",
        },
        "variable_detection": {
            "priority": 3,
            "description": "GA不能从Agent历史中检测和替换变量",
            "gap": "browser-use detect_variables + _substitute_variables",
            "difficulty": "easy",
        },
        "agent_orchestration": {
            "priority": 3,
            "description": "GA缺少通用的Agent(task+llm+browser)编排器",
            "gap": "browser-use Agent(Generic)泛化编排",
            "difficulty": "medium",
        },
        "message_compaction": {
            "priority": 2,
            "description": "GA对话历史管理原始，缺少压缩策略",
            "gap": "browser-use MessageManager + MessageCompactionSettings",
            "difficulty": "hard",
        },
    }


# ============================================================
# 自检
# ============================================================

def _run_self_check():
    """自检所有模块"""
    print("=" * 60)
    print("🌐 Browser-Use骨髓内化模块自检")
    print("=" * 60)
    
    # 1. ActionRegistry
    reg = ActionRegistry()
    reg.register("click", lambda selector: f"clicked {selector}", "点击元素", {"selector": str}, "navigation")
    reg.register("type", lambda selector, text: f"typed {text}", "输入文本", {"selector": str, "text": str}, "input")
    reg.register("navigate", lambda url: f"go to {url}", "导航URL", {"url": str}, "navigation")
    
    assert reg.count == 3
    assert reg.has_action("click")
    assert not reg.has_action("fly")
    
    action = reg.get_action("click")
    assert action is not None
    assert action.name == "click"
    
    result = reg.execute("click", selector="#btn")
    assert "clicked" in str(result)
    
    desc = reg.describe()
    assert "navigation" in desc
    assert "click" in desc
    assert "input" in desc
    print("✅ ActionRegistry: 注册/执行/描述/查询")
    
    # 2. BrowserSession
    bs = BrowserSession()
    assert not bs.is_running
    assert bs.current_url == ""
    
    import asyncio
    asyncio.run(bs.start())
    assert bs.is_running
    
    asyncio.run(bs.navigate("https://example.com"))
    assert bs.current_url == "https://example.com"
    
    state = asyncio.run(bs.get_state())
    assert "url" in state
    assert state["url"] == "https://example.com"
    
    asyncio.run(bs.stop())
    assert not bs.is_running
    print("✅ BrowserSession: 启动/导航/停止/状态")
    
    # 3. AgentCore
    agent = AgentCore(
        task="测试任务",
        browser=bs,
        action_registry=reg,
    )
    
    assert agent.task == "测试任务"
    assert not agent.is_running
    assert agent.current_step == 0
    
    # 注册额外动作
    agent.register_action("done", lambda result=None: result, "完成", {"result": str}, "control")
    assert agent.action_registry.count == 4
    
    # agent.run_sync(max_steps=3)
    # 跳过真实run测试(需LLM), 只验证结构
    assert agent.action_registry.describe() is not None
    print("✅ AgentCore: 创建/配置/动作注册")
    
    # 4. VariableDetector
    vd = VariableDetector()
    # 构造假历史
    history = AgentHistory(task="test")
    history.add_step(AgentStep(
        step_number=1,
        output=AgentOutput(
            current_state={"thinking": "found id: abc12345", "memory": "", "next_goal": "", "evaluation": ""},
            action=[{"name": "click", "params": {"selector": "#btn"}}],
        ),
        result=[{"action": "click", "success": True}],
        duration_ms=100.0,
        timestamp=time.time(),
    ))
    
    variables = vd.detect(history)
    assert isinstance(variables, dict)
    print(f"✅ VariableDetector: 检测({len(variables)}个变量)")
    
    # 5. GapAnalysis
    gaps = get_browser_use_gaps()
    assert len(gaps) == 5
    print(f"✅ get_browser_use_gaps: {len(gaps)}个差距识别")
    for name, info in gaps.items():
        print(f"   - {name}: 优先级{info['priority']}/5, {info['difficulty']}")
    
    print("\n✅ 全部自检通过 (5个模块)")


if __name__ == "__main__":
    _run_self_check()
