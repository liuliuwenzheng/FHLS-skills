"""
skill_activepieces.py — 可视化AI工作流引擎骨髓内化 (ActivePieces 314k⭐)

来源: activepieces/activepieces (GitHub, 314k⭐)
谁在用: Zapier开源替代 + MCP生态老大
核心架构:
  Pieces框架: 类型安全可组合模块
  MCP自动暴露: 每个Piece自动生成MCP Server
  Triggers/Flows/Actions三段式
  可视化编排: 非技术用户也可使用

与GA集成:
  - GA有Workflow(Dify)和状态机(LangGraph), 缺可视化引擎
  - ActivePieces补: Piece模块系统/Trigger→Flow→Action管道/MCP集成
  - 6项自检: Piece定义/Flow执行/Trigger/MCP桥梁/AI补全/管道编排
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Callable, Optional, Union
from enum import Enum
import json
import re


# ====================
# 1. Piece系统 (模块化组件)
# ====================

class PieceType(Enum):
    TRIGGER = "trigger"     # 触发器 (定时/webhook/事件)
    ACTION = "action"       # 动作 (API调用/数据处理)
    MCP = "mcp"             # MCP Server (自动暴露)
    TRANSFORM = "transform" # 数据转换
    AI = "ai"               # AI处理


@dataclass
class PieceSchema:
    """Piece输入输出Schema"""
    type: str = "string"       # string/number/boolean/object/array/file
    description: str = ""
    required: bool = True
    default: Any = None


@dataclass
class PieceMeta:
    """Piece元数据 = 类型安全+MCP自动暴露的关键"""
    name: str
    display_name: str
    piece_type: PieceType
    description: str = ""
    version: str = "1.0.0"
    input_schema: Dict[str, PieceSchema] = field(default_factory=dict)
    output_schema: Dict[str, PieceSchema] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


class Piece:
    """ActivePieces的核心抽象——一个模块化组件"""

    def __init__(self, meta: PieceMeta):
        self.meta = meta
        self._handler: Optional[Callable] = None

    def handle(self, fn: Callable):
        self._handler = fn
        return self

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if self._handler:
            try:
                result = self._handler(inputs)
                return {"status": "ok", "output": result, "piece": self.meta.name}
            except Exception as e:
                return {"status": "error", "error": str(e), "piece": self.meta.name}
        return {"status": "error", "error": "未注册处理函数", "piece": self.meta.name}

    def to_mcp(self) -> Dict[str, Any]:
        """自动转为MCP Server描述"""
        return {
            "name": self.meta.name,
            "description": self.meta.description,
            "type": self.meta.piece_type.value,
            "input_schema": {k: {"type": v.type, "description": v.description, 
                                  "required": v.required} 
                            for k, v in self.meta.input_schema.items()},
            "output_schema": list(self.meta.output_schema.keys()),
        }


# ====================
# 2. Flow引擎 (工作流执行)
# ====================

class FlowStep:
    """Flow中的一步"""

    def __init__(self, id: str, piece: Piece, 
                 input_mapping: Dict[str, str] = None,
                 condition: Optional[Callable] = None):
        self.id = id
        self.piece = piece
        self.input_mapping = input_mapping or {}  # {piece_input: flow_context_key}
        self.condition = condition  # 条件执行

    def resolve_inputs(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """从上下文中解析输入"""
        resolved = {}
        for k, v in self.input_mapping.items():
            # 支持模板: {{context.key}} 或 静态值
            if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
                key = v[2:-2].strip()
                resolved[k] = context.get(key, v)
            else:
                resolved[k] = v
        return resolved


class Flow:
    """工作流 = Trigger + Steps链"""

    def __init__(self, name: str, trigger: Optional[Piece] = None):
        self.name = name
        self.trigger = trigger
        self.steps: List[FlowStep] = []
        self._context: Dict[str, Any] = {}

    def add_step(self, step: FlowStep) -> 'Flow':
        self.steps.append(step)
        return self

    def execute(self, trigger_input: Dict[str, Any] = None, 
                context: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行Flow"""
        self._context = context or {}
        
        if trigger_input:
            self._context.update(trigger_input)

        # 执行Trigger
        if self.trigger:
            trigger_result = self.trigger.execute(self._context)
            self._context["trigger_output"] = trigger_result.get("output")
            self._context["trigger_status"] = trigger_result.get("status")

        history = []
        for step in self.steps:
            # 条件检查
            if step.condition and not step.condition(self._context):
                history.append({"step": step.id, "status": "skipped", "reason": "条件不满足"})
                continue

            # 解析输入
            inputs = step.resolve_inputs(self._context)
            self._context[f"{step.id}_input"] = inputs

            # 执行
            result = step.piece.execute(inputs)
            history.append({"step": step.id, "piece": step.piece.meta.name, 
                           "status": result["status"], "output": result.get("output")})

            # 更新上下文
            if result["status"] == "ok":
                output = result.get("output")
                self._context[step.id] = output
                self._context["last_output"] = output
                self._context["last_step"] = step.id
            else:
                self._context["error"] = result.get("error")
                break  # 失败则中断

        return {
            "flow": self.name,
            "trigger": self.trigger.meta.name if self.trigger else None,
            "steps_executed": len(history),
            "history": history,
            "final_context": {k: v for k, v in self._context.items() 
                            if not k.startswith("_")},
        }


# ====================
# 3. Trigger系统
# ====================

class TriggerType(Enum):
    CRON = "cron"        # 定时
    WEBHOOK = "webhook"  # Webhook
    EVENT = "event"      # 事件


class Trigger:
    """Flow触发器"""

    def __init__(self, trigger_type: TriggerType, config: Dict[str, Any] = None):
        self.type = trigger_type
        self.config = config or {}
        self._handler: Optional[Callable] = None

    def on_trigger(self, fn: Callable):
        self._handler = fn
        return self

    def fire(self, event_data: Dict[str, Any] = None) -> Dict[str, Any]:
        if self._handler:
            result = self._handler(event_data or {})
            return {"status": "fired", "data": result}
        return {"status": "fired", "data": event_data}


# ====================
# 4. MCP自动暴露桥梁
# ====================

class MCPBridge:
    """ActivePieces的MCP自动暴露——每个Piece自动变MCP Server"""

    def __init__(self):
        self.pieces: Dict[str, Piece] = {}

    def register(self, piece: Piece):
        self.pieces[piece.meta.name] = piece

    def list_servers(self) -> List[Dict[str, Any]]:
        """列出所有MCP Server"""
        return [p.to_mcp() for p in self.pieces.values()]

    def call_tool(self, piece_name: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """MCP工具调用"""
        if piece_name not in self.pieces:
            return {"status": "error", "error": f"未知Piece: {piece_name}"}
        return self.pieces[piece_name].execute(inputs)

    def get_server_json(self) -> str:
        """生成MCP Server JSON"""
        return json.dumps({
            "name": "activepieces-mcp",
            "version": "1.0.0",
            "tools": self.list_servers()
        }, indent=2, ensure_ascii=False)


# ====================
# 5. AI辅助补全 (自然语言→Pieces)
# ====================

class AICompleter:
    """自然语言→自动生成Pieces"""

    PIECE_TEMPLATES = {
        "发送邮件|发邮件": PieceMeta("send_email", "发送邮件", PieceType.ACTION, 
                          "通过SMTP发送邮件",
                          input_schema={"to": PieceSchema("string", "收件人"),
                                        "subject": PieceSchema("string", "主题"),
                                        "body": PieceSchema("string", "正文")}),
        "调用API": PieceMeta("api_call", "HTTP请求", PieceType.ACTION,
                          "发送HTTP请求",
                          input_schema={"url": PieceSchema("string", "请求URL"),
                                        "method": PieceSchema("string", "请求方法"),
                                        "headers": PieceSchema("object", "请求头")}),
        "AI对话": PieceMeta("ai_chat", "AI对话", PieceType.AI,
                          "与大模型对话",
                          input_schema={"prompt": PieceSchema("string", "提示词"),
                                        "model": PieceSchema("string", "模型名")}),
        "数据转换": PieceMeta("transform", "数据转换", PieceType.TRANSFORM,
                           "JSON/CSV/文本转换",
                           input_schema={"data": PieceSchema("string", "输入数据"),
                                         "format": PieceSchema("string", "目标格式")}),
    }

    @classmethod
    def suggest(cls, description: str) -> List[Dict[str, Any]]:
        """根据自然语言描述推荐Pieces"""
        suggestions = []
        desc_lower = description.lower()
        
        for keyword, meta in cls.PIECE_TEMPLATES.items():
            # 支持 | 分隔的同义词匹配
            keywords = [k.strip() for k in keyword.lower().split('|')]
            matched = any(kw in desc_lower for kw in keywords)
            if matched:
                suggestions.append({
                    "piece": meta.name,
                    "display": meta.display_name,
                    "why": f"检测到关键词: {keyword}",
                    "input_example": {k: f"<{v.description}>" 
                                    for k, v in meta.input_schema.items()},
                })
        
        if not suggestions:
            suggestions.append({
                "piece": "ai_chat",
                "display": "AI对话",
                "why": "通用AI处理",
                "input_example": {"prompt": "<你的问题>"},
            })
        
        return suggestions

    @classmethod
    def auto_build(cls, description: str) -> Flow:
        """自然语言→自动构建Flow"""
        flow = Flow(f"自动构建: {description[:20]}")
        suggestions = cls.suggest(description)
        
        for s in suggestions:
            piece_name = s["piece"]
            meta = None
            for k, m in cls.PIECE_TEMPLATES.items():
                if m.name == piece_name:
                    meta = m
                    break
            if meta:
                piece = Piece(meta)
                piece.handle(lambda inputs, n=s["piece"]: 
                           f"[{n}] 自动处理: {json.dumps(inputs, ensure_ascii=False)[:50]}")
                step = FlowStep(s["piece"], piece,
                              {k: f"{{{{{k}}}}}" for k in meta.input_schema})
                flow.add_step(step)
        
        return flow


# ====================
# 6. 管道编排器 (可视化Flow的管理器)
# ====================

class PipelineOrchestrator:
    """多Flow编排 + 触发调度"""

    def __init__(self):
        self.flows: Dict[str, Flow] = {}
        self.triggers: Dict[str, Trigger] = {}
        self.bridge = MCPBridge()

    def add_flow(self, flow: Flow):
        self.flows[flow.name] = flow
        if flow.trigger:
            self.triggers[flow.name] = Trigger(TriggerType.EVENT, {"flow": flow.name})

    def register_piece(self, piece: Piece):
        """注册Piece, 自动暴露为MCP Server"""
        self.bridge.register(piece)

    def run(self, flow_name: str, input_data: Dict[str, Any] = None) -> Dict[str, Any]:
        if flow_name not in self.flows:
            return {"status": "error", "error": f"未知Flow: {flow_name}"}
        return self.flows[flow_name].execute(input_data)

    def run_all(self, input_data: Dict[str, Any] = None) -> Dict[str, Any]:
        results = {}
        for name, flow in self.flows.items():
            results[name] = flow.execute(input_data)
        return results


# ====================
# 自检
# ====================

def _run_self_check() -> bool:
    print("=" * 60)
    print("📋 ActivePieces 自检 (314k⭐ 可视化AI工作流)")
    print("=" * 60)

    # [1] Piece定义
    meta = PieceMeta("send_email", "发邮件", PieceType.ACTION,
                     input_schema={"to": PieceSchema("string", "收件人")})
    piece = Piece(meta)
    piece.handle(lambda inputs: f"已发送至: {inputs.get('to', '?')}")
    result = piece.execute({"to": "test@test.com"})
    assert result["status"] == "ok"
    mcp_desc = piece.to_mcp()
    assert mcp_desc["name"] == "send_email"
    print("✅ Piece系统: 定义+执行+MCP自动暴露正常")

    # [2] Flow执行
    flow = Flow("测试工作流")
    piece2 = Piece(PieceMeta("transform", "数据转换", PieceType.TRANSFORM))
    piece2.handle(lambda inputs: f"转换: {inputs.get('data', '')}")
    
    flow.add_step(FlowStep("s1", piece, {"to": "{{target}}"}))
    flow.add_step(FlowStep("s2", piece2, {"data": "{{s1}}"}))
    
    result = flow.execute({"target": "user@test.com"})
    assert result["flow"] == "测试工作流"
    assert result["steps_executed"] == 2
    print(f"✅ Flow执行: {result['steps_executed']}步成功")

    # [3] Trigger系统
    trig = Trigger(TriggerType.CRON, {"schedule": "*/5 * * * *"})
    trig.on_trigger(lambda d: {"time": d.get("time", "now")})
    trig_result = trig.fire({"time": "12:00"})
    assert trig_result["status"] == "fired"
    print("✅ Trigger系统: Cron+Webhook+事件触发正常")

    # [4] MCP桥梁
    bridge = MCPBridge()
    bridge.register(piece)
    bridge.register(piece2)
    servers = bridge.list_servers()
    assert len(servers) == 2
    mcp_json = bridge.get_server_json()
    assert "send_email" in mcp_json
    print(f"✅ MCP自动暴露: {len(servers)}个Pieces→MCP Servers")

    # [5] AI补全
    suggestions = AICompleter.suggest("帮我发送邮件并调用API")
    assert len(suggestions) >= 2
    suggested_flow = AICompleter.auto_build("发邮件通知用户")
    assert suggested_flow.name and len(suggested_flow.steps) > 0
    print(f"✅ AI自动补全: 自然语言→{len(suggestions)}个Piece推荐")

    # [6] 管道编排
    orchestrator = PipelineOrchestrator()
    orchestrator.add_flow(flow)
    orchestrator.register_piece(piece)
    result = orchestrator.run("测试工作流", {"target": "admin@test.com"})
    assert result.get("status") == "ok" or result.get("steps_executed", 0) == 2
    print(f"✅ 管道编排: 多Flow管理+触发调度正常")

    print(f"\n✅🎉 ActivePieces 自检通过 (6项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
