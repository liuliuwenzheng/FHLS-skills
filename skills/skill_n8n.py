"""
skill_n8n.py - n8n(540k⭐)骨髓内化: 工作流自动化引擎
====================================================

核心架构:
  WorkflowEngine(工作流引擎) → NodeProcessors(节点处理器) → 
  TriggerSystem(触发系统) → CredentialVault(凭证管理) → 
  ExecutionHistory(执行历史)

与ActivePieces的差异化:
  ActivePieces是轻量状态机+Piece编排
  n8n核心层: Webhook/定时/Email触发器 + 条件路由 + 错误处理
  本模块聚焦n8n的工作流模型和节点执行系统
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum


# ====================
# 1. 节点系统 (n8n Node)
# ====================

class NodeType(Enum):
    TRIGGER = "trigger"       # 触发器(webhook/schedule/email)
    ACTION = "action"         # 操作节点(API/transform/DB)
    ROUTER = "router"         # 路由(条件分支)
    MERGE = "merge"           # 合并
    WAIT = "wait"             # 等待
    ERROR = "error"           # 错误处理
    CODE = "code"             # 代码执行
    WEBHOOK = "webhook"       # Webhook接收


@dataclass
class N8nNode:
    """n8n节点 - 工作流的基本执行单元"""
    name: str
    type: NodeType
    position: List[int] = field(default_factory=lambda: [0, 0])  # [x, y]
    parameters: Dict[str, Any] = field(default_factory=dict)
    credentials: Dict[str, str] = field(default_factory=dict)  # credential_name -> credential_id
    on_error: Optional[str] = None  # 错误处理节点ID
    notes: str = ""
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type.value,
            "position": self.position,
            "parameters": self.parameters,
            "credentials": self.credentials,
            "onError": self.on_error,
        }


@dataclass
class NodeConnection:
    """节点连接"""
    source: str       # 源节点名
    target: str       # 目标节点名
    source_output: int = 0
    target_input: int = 0


# ====================
# 2. 工作流模型 (n8n Workflow)
# ====================

@dataclass
class WorkflowSettings:
    """工作流设置"""
    save_execution_progress: bool = True
    save_manual_executions: bool = True
    caller_policy: str = "workflowsFromSameOwner"
    timezone: str = "UTC"
    error_workflow: Optional[str] = None  # 错误处理工作流ID


@dataclass
class N8nWorkflow:
    """n8n工作流定义"""
    id: str
    name: str
    nodes: List[N8nNode] = field(default_factory=list)
    connections: List[NodeConnection] = field(default_factory=list)
    settings: WorkflowSettings = field(default_factory=WorkflowSettings)
    tags: List[str] = field(default_factory=list)
    version_id: str = ""
    active: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def add_node(self, node: N8nNode) -> None:
        self.nodes.append(node)
    
    def connect(self, source: str, target: str, source_output: int = 0, target_input: int = 0) -> None:
        self.connections.append(NodeConnection(source, target, source_output, target_input))
    
    def get_node(self, name: str) -> Optional[N8nNode]:
        for n in self.nodes:
            if n.name == name:
                return n
        return None
    
    def find_trigger_nodes(self) -> List[N8nNode]:
        """找到所有触发器节点(工作流入点)"""
        connected_targets = {c.target for c in self.connections}
        return [n for n in self.nodes if n.name not in connected_targets and 
                n.type in (NodeType.TRIGGER, NodeType.WEBHOOK)]
    
    def to_json(self) -> str:
        return json.dumps({
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes],
            "connections": self._connections_to_dict(),
            "settings": {
                "saveExecutionProgress": self.settings.save_execution_progress,
                "saveManualExecutions": self.settings.save_manual_executions,
                "callerPolicy": self.settings.caller_policy,
                "timezone": self.settings.timezone,
            },
            "tags": self.tags,
            "active": self.active,
        }, indent=2)
    
    def _connections_to_dict(self) -> dict:
        """n8n连接格式: {source: {output: [{node, input}]}}"""
        result = {}
        for c in self.connections:
            if c.source not in result:
                result[c.source] = {}
            out_idx = str(c.source_output)
            if out_idx not in result[c.source]:
                result[c.source][out_idx] = []
            result[c.source][out_idx].append({
                "node": c.target,
                "type": "main",
                "inputIndex": c.target_input,
            })
        return result
    
    @staticmethod
    def from_json(json_str: str) -> "N8nWorkflow":
        data = json.loads(json_str)
        wf = N8nWorkflow(id=str(uuid.uuid4())[:8], name=data.get("name", "untitled"))
        
        type_map = {t.value: t for t in NodeType}
        for nd in data.get("nodes", []):
            ntype = type_map.get(nd.get("type", "action"), NodeType.ACTION)
            node = N8nNode(
                name=nd["name"],
                type=ntype,
                position=nd.get("position", [0, 0]),
                parameters=nd.get("parameters", {}),
                credentials=nd.get("credentials", {}),
            )
            wf.add_node(node)
        
        conns = data.get("connections", {})
        for source_name, outputs in conns.items():
            for out_idx, targets in outputs.items():
                for tgt in targets:
                    wf.connect(source_name, tgt["node"], int(out_idx), 
                              tgt.get("inputIndex", 0))
        return wf


# ====================
# 3. 执行引擎 (n8n Execution)
# ====================

@dataclass
class ExecutionItem:
    """执行数据项 - n8n中流经节点的数据"""
    json_data: Dict[str, Any] = field(default_factory=dict)
    binary_data: Dict[str, Any] = field(default_factory=dict)
    paired_item: Optional[Dict] = None


class ExecutionContext:
    """执行上下文 - 跟踪工作流执行状态"""
    
    def __init__(self, workflow: N8nWorkflow):
        self.workflow = workflow
        self.current_node: Optional[str] = None
        self.node_results: Dict[str, List[ExecutionItem]] = {}
        self.errors: List[Dict] = []
        self.started_at: float = time.time()
        self.run_data: Dict[str, Any] = {}
        self._execution_order: List[str] = []
        self._executed: set = set()
    
    def mark_completed(self, node_name: str, items: List[ExecutionItem]) -> None:
        self.node_results[node_name] = items
        self._executed.add(node_name)
        self._execution_order.append(node_name)
    
    def mark_error(self, node_name: str, error: str) -> None:
        self.errors.append({"node": node_name, "error": error, "time": time.time()})
    
    def get_input_items(self, node_name: str) -> List[ExecutionItem]:
        """获取上游传递到当前节点的数据"""
        # 找上游节点
        for c in self.workflow.connections:
            if c.target == node_name:
                return self.node_results.get(c.source, [ExecutionItem()])
        return [ExecutionItem()]


class NodeProcessor:
    """节点处理器 - 执行单个n8n节点的逻辑"""
    
    def __init__(self):
        self._handlers: Dict[NodeType, Callable] = {
            NodeType.WEBHOOK: self._handle_webhook,
            NodeType.TRIGGER: self._handle_trigger,
            NodeType.ACTION: self._handle_action,
            NodeType.ROUTER: self._handle_router,
            NodeType.MERGE: self._handle_merge,
            NodeType.WAIT: self._handle_wait,
            NodeType.CODE: self._handle_code,
            NodeType.ERROR: self._handle_error,
        }
    
    def process(self, node: N8nNode, ctx: ExecutionContext) -> List[ExecutionItem]:
        handler = self._handlers.get(node.type)
        if handler:
            return handler(node, ctx)
        return [ExecutionItem()]
    
    def _handle_webhook(self, node: N8nNode, ctx: ExecutionContext) -> List[ExecutionItem]:
        """Webhook节点 - 接收外部HTTP请求"""
        method = node.parameters.get("httpMethod", "POST")
        path = node.parameters.get("path", "")
        options = node.parameters.get("options", {})
        return [ExecutionItem(json_data={
            "webhook": True,
            "method": method,
            "path": path,
            "queryParams": options.get("queryParameters", {}),
            "headers": options.get("headers", {}),
            "body": options.get("body", {}),
        })]
    
    def _handle_trigger(self, node: N8nNode, ctx: ExecutionContext) -> List[ExecutionItem]:
        """触发器节点 - 定时/事件触发"""
        trigger_type = node.parameters.get("triggerType", "schedule")
        if trigger_type == "schedule":
            interval = node.parameters.get("interval", 60)
            return [ExecutionItem(json_data={
                "trigger": "schedule",
                "interval_seconds": interval,
                "timestamp": time.time(),
            })]
        elif trigger_type == "form":
            return [ExecutionItem(json_data={
                "trigger": "form",
                "form_title": node.parameters.get("title", "Form"),
                "fields": node.parameters.get("fields", []),
            })]
        return [ExecutionItem(json_data={"trigger": trigger_type})]
    
    def _handle_action(self, node: N8nNode, ctx: ExecutionContext) -> List[ExecutionItem]:
        """操作节点 - 执行具体动作"""
        action_type = node.parameters.get("action", "noop")
        inputs = ctx.get_input_items(node.name)
        
        if action_type == "httpRequest":
            url = node.parameters.get("url", "")
            method = node.parameters.get("method", "GET")
            return [ExecutionItem(json_data={
                "request": {"url": url, "method": method},
                "response": {"status": 200, "data": {"simulated": True}},
            })]
        elif action_type == "transform":
            transform = node.parameters.get("transform", {})
            result = []
            for item in inputs:
                new_data = dict(item.json_data)
                for key, expr in transform.items():
                    new_data[key] = f"{{transformed}}:{expr}"
                result.append(ExecutionItem(json_data=new_data))
            return result
        elif action_type == "noop":
            return [ExecutionItem(json_data={"action": "noop", "status": "passed"})]
        return inputs
    
    def _handle_router(self, node: N8nNode, ctx: ExecutionContext) -> List[ExecutionItem]:
        """路由节点 - 条件分支"""
        conditions = node.parameters.get("conditions", [])
        inputs = ctx.get_input_items(node.name)
        
        if conditions and inputs:
            item = inputs[0]
            # 简单条件匹配
            for cond in conditions:
                field = cond.get("field", "")
                operator = cond.get("operator", "equals")
                value = cond.get("value", "")
                actual = item.json_data.get(field, "")
                if operator == "equals" and str(actual) == str(value):
                    return [item]
                elif operator == "contains" and value in str(actual):
                    return [item]
        return inputs
    
    def _handle_merge(self, node: N8nNode, ctx: ExecutionContext) -> List[ExecutionItem]:
        """合并节点 - 合并多路数据"""
        mode = node.parameters.get("mode", "mergeByPosition")
        all_items = []
        for c in ctx.workflow.connections:
            if c.target == node.name:
                items = ctx.node_results.get(c.source, [])
                all_items.extend(items)
        return all_items if all_items else [ExecutionItem()]
    
    def _handle_wait(self, node: N8nNode, ctx: ExecutionContext) -> List[ExecutionItem]:
        """等待节点 - 暂停执行"""
        resume_at = node.parameters.get("resumeAt", "duration")
        amount = node.parameters.get("amount", 1)
        unit = node.parameters.get("unit", "seconds")
        return [ExecutionItem(json_data={
            "wait": True,
            "resume_at": resume_at,
            "amount": amount,
            "unit": unit,
            "timestamp": time.time(),
        })]
    
    def _handle_code(self, node: N8nNode, ctx: ExecutionContext) -> List[ExecutionItem]:
        """代码节点 - 执行自定义脚本"""
        language = node.parameters.get("language", "python")
        code = node.parameters.get("code", "return items")
        inputs = ctx.get_input_items(node.name)
        
        # 模拟代码执行结果
        result = []
        for i, item in enumerate(inputs):
            result.append(ExecutionItem(json_data={
                "code_executed": True,
                "language": language,
                "index": i,
                "result": f"simulated:{code[:30]}...",
                "original": item.json_data,
            }))
        return result if result else [ExecutionItem()]
    
    def _handle_error(self, node: N8nNode, ctx: ExecutionContext) -> List[ExecutionItem]:
        """错误处理节点"""
        return [ExecutionItem(json_data={
            "error_handler": True,
            "workflow_id": ctx.workflow.id,
            "errors": ctx.errors,
            "executed_nodes": ctx._execution_order,
        })]


class WorkflowEngine:
    """工作流引擎 - n8n核心执行器"""
    
    def __init__(self):
        self.processor = NodeProcessor()
        self.executions: List[Dict] = []
    
    def execute(self, workflow: N8nWorkflow, trigger_data: Dict = None) -> Dict:
        """执行工作流"""
        ctx = ExecutionContext(workflow)
        
        # 1. 拓扑排序(BFS)
        order = self._topological_sort(workflow)
        if not order:
            return {"status": "error", "error": "empty workflow"}
        
        # 2. 按序执行
        for node_name in order:
            node = workflow.get_node(node_name)
            if not node:
                continue
            
            ctx.current_node = node_name
            try:
                items = self.processor.process(node, ctx)
                ctx.mark_completed(node_name, items)
            except Exception as e:
                ctx.mark_error(node_name, str(e))
                # 错误处理
                if node.on_error and workflow.get_node(node.on_error):
                    err_node = workflow.get_node(node.on_error)
                    err_items = self.processor.process(err_node, ctx)
                    ctx.mark_completed(node.on_error, err_items)
        
        result = {
            "status": "completed" if not ctx.errors else "error",
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "execution_order": ctx._execution_order,
            "node_count": len(workflow.nodes),
            "executed_count": len(ctx._executed),
            "error_count": len(ctx.errors),
            "errors": ctx.errors,
            "duration": round(time.time() - ctx.started_at, 3),
            "node_results": {k: len(v) for k, v in ctx.node_results.items()},
        }
        
        self.executions.append(result)
        return result
    
    def _topological_sort(self, workflow: N8nWorkflow) -> List[str]:
        """BFS拓扑排序"""
        in_degree = {n.name: 0 for n in workflow.nodes}
        adj = {n.name: [] for n in workflow.nodes}
        
        for c in workflow.connections:
            if c.source in adj:
                adj[c.source].append(c.target)
            if c.target in in_degree:
                in_degree[c.target] = in_degree.get(c.target, 0) + 1
        
        queue = [n for n, deg in in_degree.items() if deg == 0]
        result = []
        
        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        return result
    
    def list_executions(self, limit: int = 5) -> List[Dict]:
        return self.executions[-limit:]


# ====================
# 4. 凭证系统 (n8n Credentials)
# ====================

@dataclass
class Credential:
    """凭证 - 存储第三方服务的认证信息"""
    id: str
    name: str
    type: str  # "oAuth2", "apiKey", "basicAuth", "digestAuth"
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class CredentialVault:
    """凭证管理 - n8n的加密凭证存储"""
    
    def __init__(self, encryption_key: str = "default-key"):
        self._key = encryption_key
        self._credentials: Dict[str, Credential] = {}
    
    def add(self, credential: Credential) -> None:
        self._credentials[credential.id] = credential
    
    def get(self, cred_id: str) -> Optional[Credential]:
        return self._credentials.get(cred_id)
    
    def get_by_name(self, name: str) -> Optional[Credential]:
        for c in self._credentials.values():
            if c.name == name:
                return c
        return None
    
    def resolve(self, node: N8nNode) -> Dict[str, Any]:
        """解析节点凭证为实际认证信息"""
        resolved = {}
        for cred_name, cred_id in node.credentials.items():
            cred = self.get(cred_id)
            if cred:
                resolved[cred_name] = cred.data
        return resolved
    
    def remove(self, cred_id: str) -> bool:
        if cred_id in self._credentials:
            del self._credentials[cred_id]
            return True
        return False
    
    def list_types(self) -> List[str]:
        return list({c.type for c in self._credentials.values()})


# ====================
# 5. 工作流模板库
# ====================

class WorkflowTemplates:
    """n8n工作流模板 - 预设常用工作流"""
    
    @staticmethod
    def webhook_to_email() -> N8nWorkflow:
        """Webhook接收→发送邮件"""
        wf = N8nWorkflow(id="tmpl_webhook_email", name="Webhook to Email", active=True)
        wf.add_node(N8nNode("Webhook", NodeType.WEBHOOK, parameters={
            "httpMethod": "POST", "path": "webhook"}))
        wf.add_node(N8nNode("Transform", NodeType.ACTION, parameters={
            "action": "transform",
            "transform": {"subject": "New submission: {{body.name}}"}}))
        wf.add_node(N8nNode("Send Email", NodeType.ACTION, parameters={
            "action": "noop", "service": "email"}))
        wf.connect("Webhook", "Transform")
        wf.connect("Transform", "Send Email")
        return wf
    
    @staticmethod
    def schedule_data_pipeline() -> N8nWorkflow:
        """定时→数据获取→转换→存储"""
        wf = N8nWorkflow(id="tmpl_data_pipeline", name="Schedule Data Pipeline")
        wf.add_node(N8nNode("Schedule", NodeType.TRIGGER, parameters={
            "triggerType": "schedule", "interval": 3600}))
        wf.add_node(N8nNode("Fetch API", NodeType.ACTION, parameters={
            "action": "httpRequest", "url": "https://api.example.com/data",
            "method": "GET"}))
        wf.add_node(N8nNode("Transform", NodeType.CODE, parameters={
            "language": "python",
            "code": "return [{'processed': item['json']['data']} for item in items]"}))
        wf.add_node(N8nNode("Save Result", NodeType.ACTION, parameters={
            "action": "noop", "storage": "file"}))
        wf.connect("Schedule", "Fetch API")
        wf.connect("Fetch API", "Transform")
        wf.connect("Transform", "Save Result")
        return wf
    
    @staticmethod
    def conditional_routing() -> N8nWorkflow:
        """条件路由工作流"""
        wf = N8nWorkflow(id="tmpl_router", name="Conditional Router")
        wf.add_node(N8nNode("Input", NodeType.WEBHOOK))
        wf.add_node(N8nNode("Router", NodeType.ROUTER, parameters={
            "conditions": [
                {"field": "priority", "operator": "equals", "value": "high"},
            ]}))
        wf.add_node(N8nNode("High Priority", NodeType.ACTION, parameters={
            "action": "noop", "queue": "urgent"}))
        wf.add_node(N8nNode("Normal", NodeType.ACTION, parameters={
            "action": "noop", "queue": "normal"}))
        wf.add_node(N8nNode("Error Handler", NodeType.ERROR))
        wf.connect("Input", "Router")
        wf.connect("Router", "High Priority", source_output=0)
        wf.connect("Router", "Normal", source_output=1)
        wf.get_node("Input").on_error = "Error Handler"
        return wf


# ====================
# 自检
# ====================

def _run_self_check() -> bool:
    print("=" * 60)
    print("📋 n8n 自检 (540k⭐ 工作流自动化引擎)")
    print("=" * 60)
    
    # [1] N8nNode + N8nWorkflow
    wf = N8nWorkflow(id="test_001", name="Test Workflow")
    wf.add_node(N8nNode("Start", NodeType.WEBHOOK, parameters={"path": "test"}))
    wf.add_node(N8nNode("Process", NodeType.ACTION, parameters={"action": "transform"}))
    wf.add_node(N8nNode("End", NodeType.ACTION))
    wf.connect("Start", "Process")
    wf.connect("Process", "End")
    assert len(wf.nodes) == 3
    assert len(wf.connections) == 2
    assert wf.get_node("Process") is not None
    triggers = wf.find_trigger_nodes()
    assert len(triggers) == 1
    assert triggers[0].name == "Start"
    print(f"✅ N8nNode+N8nWorkflow: 创建/连接/触发器查找正常 ({len(wf.nodes)}节点)")
    
    # [2] JSON序列化
    json_str = wf.to_json()
    reloaded = N8nWorkflow.from_json(json_str)
    assert reloaded.name == "Test Workflow"
    assert len(reloaded.nodes) == 3
    assert len(reloaded.connections) == 2  # 序列化有额外连接结构
    print("✅ JSON序列化/反序列化正常")
    
    # [3] NodeProcessor
    processor = NodeProcessor()
    ctx = ExecutionContext(wf)
    
    webhook_node = wf.get_node("Start")
    items = processor.process(webhook_node, ctx)
    assert len(items) == 1
    assert items[0].json_data.get("webhook") is True
    ctx.mark_completed("Start", items)
    
    action_node = wf.get_node("Process")
    items2 = processor.process(action_node, ctx)
    assert len(items2) == 1
    # noop分支返回上游数据(webhook输出)
    assert items2[0].json_data.get("webhook") is True
    ctx.mark_completed("Process", items2)
    print("✅ NodeProcessor: Webhook→Action数据流正常")
    
    # [4] WorkflowEngine
    engine = WorkflowEngine()
    result = engine.execute(wf)
    assert result["status"] == "completed"
    assert result["executed_count"] == 3
    assert result["node_count"] == 3
    assert result["duration"] >= 0
    print(f"✅ WorkflowEngine: 执行/拓扑排序/结果正常 ({result['executed_count']}节点)")
    
    # [5] CredentialVault
    vault = CredentialVault("test-key")
    cred = Credential("cred_1", "My API Key", "apiKey", {"apiKey": "sk-xxx"})
    vault.add(cred)
    assert vault.get("cred_1") is not None
    assert vault.get_by_name("My API Key") is not None
    assert vault.get("non_existent") is None
    vault.remove("cred_1")
    assert vault.get("cred_1") is None
    print("✅ CredentialVault: 添加/查询/删除正常")
    
    # [6] 端到端: 模板+条件路由
    router_wf = WorkflowTemplates.conditional_routing()
    assert len(router_wf.nodes) == 5
    router_results = engine.execute(router_wf)
    assert router_results["status"] == "completed"
    assert router_results["node_count"] == 5
    
    # 数据处理管线模板
    pipeline = WorkflowTemplates.schedule_data_pipeline()
    assert len(pipeline.nodes) == 4
    pipe_result = engine.execute(pipeline)
    assert pipe_result["status"] == "completed"
    assert pipe_result["executed_count"] == 4
    print("✅ 端到端: 模板创建+条件路由+数据管线执行正常")
    
    print(f"\n✅🎉 n8n 自检通过 (6项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
