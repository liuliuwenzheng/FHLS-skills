"""
skill_block_workflow.py - AutoGPT Block Workflow 骨髓内化

基于 AutoGPT (Significant-Gravitas/AutoGPT, 184k⭐) 的 Block 编排架构
用自己的话重建, GA 可执行产出

核心概念:
1. Block (积木块) - 单一原子操作单元
2. Graph (工作流图) - 连接 Block 形成执行链  
3. Workflow (执行引擎) - 调度 Graph 执行
"""

import asyncio
import logging
import time as time_module
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Generic,
    Optional,
    TypeVar,
)

logger = logging.getLogger(__name__)

# ============================================================
# 模块 1: Block 类型系统
# ============================================================

class BlockType(Enum):
    STANDARD = auto()
    INPUT = auto()
    OUTPUT = auto()
    NOTE = auto()
    WEBHOOK = auto()
    AGENT = auto()
    AI = auto()
    HUMAN_TOOL = auto()
    MCP_TOOL = auto()
    GATE = auto()


class BlockCategory(Enum):
    AI = "AI 能力"
    TEXT = "文本处理"
    SEARCH = "搜索/信息提取"
    BASIC = "基础操作"
    LOGIC = "流程控制"
    DATA = "数据处理"
    AGENT = "Agent 交互"
    SAFETY = "安全机制"
    MULTIMEDIA = "多媒体"
    INPUT = "输入"
    OUTPUT = "输出"
    WEBHOOK = "Webhook"
    HUMAN_TOOL = "人工参与"


# ============================================================
# 模块 2: Schema 系统
# ============================================================

@dataclass
class FieldDef:
    name: str
    type_hint: str
    description: str = ""
    required: bool = True
    default: Any = None
    enum_values: list[Any] | None = None


@dataclass
class Schema:
    fields: list[FieldDef] = field(default_factory=list)

    def to_dict(self) -> dict:
        props = {}
        for f in self.fields:
            entry = {"type": f.type_hint, "description": f.description}
            if f.default is not None:
                entry["default"] = f.default
            if f.enum_values:
                entry["enum"] = f.enum_values
            props[f.name] = entry
        return {
            "type": "object",
            "properties": props,
            "required": [f.name for f in self.fields if f.required],
        }

    def validate(self, data: dict) -> str | None:
        for f in self.fields:
            if f.required and f.name not in data:
                return f"Missing required field: {f.name}"
            if f.name in data and f.enum_values:
                if data[f.name] not in f.enum_values:
                    return f"Field '{f.name}' value '{data[f.name]}' not in {f.enum_values}"
        return None


# ============================================================
# 模块 3: Block 核心基类
# ============================================================

I = TypeVar("I", bound=dict)
O = TypeVar("O", bound=AsyncGenerator)


class Block(ABC, Generic[I, O]):
    """Block 基类 —— GA 中的原子操作单元"""

    id: str = ""
    name: str = ""
    type: BlockType = BlockType.STANDARD
    categories: list[BlockCategory] = []
    description: str = ""
    version: str = "1.0.0"
    input_schema: Schema = Schema()
    output_schema: Schema = Schema()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.id:
            cls.id = cls.__name__.lower()
            if cls.id.endswith("block"):
                cls.id = cls.id[:-5]

    @abstractmethod
    async def run(self, input_data: I) -> O:
        ...

    async def validate_input(self, input_data: dict) -> str | None:
        return self.input_schema.validate(input_data)

    def to_info(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.name,
            "description": self.description,
            "version": self.version,
            "categories": [c.name for c in self.categories],
            "input_schema": self.input_schema.to_dict(),
            "output_schema": self.output_schema.to_dict(),
        }


# ============================================================
# 模块 4: Graph (工作流图)
# ============================================================

@dataclass
class Node:
    id: str = field(default_factory=lambda: f"node_{uuid.uuid4().hex[:8]}")
    block_id: str = ""
    config: dict = field(default_factory=dict)
    label: str = ""
    x: float = 0
    y: float = 0

    def to_dict(self) -> dict:
        return {"id": self.id, "block_id": self.block_id, "config": self.config,
                "label": self.label, "position": {"x": self.x, "y": self.y}}


@dataclass
class Link:
    source_node_id: str
    source_output: str
    target_node_id: str
    target_input: str
    id: str = field(default_factory=lambda: f"link_{uuid.uuid4().hex[:8]}")
    label: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "source": self.source_node_id,
                "source_output": self.source_output, "target": self.target_node_id,
                "target_input": self.target_input, "label": self.label}


@dataclass
class Graph:
    id: str = field(default_factory=lambda: f"graph_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    nodes: list[Node] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def add_node(self, node: Node) -> str:
        self.nodes.append(node)
        return node.id

    def add_link(self, source: Node | str, output: str,
                 target: Node | str, target_input: str) -> str:
        src_id = source if isinstance(source, str) else source.id
        tgt_id = target if isinstance(target, str) else target.id
        link = Link(source_node_id=src_id, source_output=output,
                    target_node_id=tgt_id, target_input=target_input)
        self.links.append(link)
        return link.id

    def get_node(self, node_id: str) -> Node | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def get_outgoing_links(self, node_id: str) -> list[Link]:
        return [l for l in self.links if l.source_node_id == node_id]

    def get_incoming_links(self, node_id: str) -> list[Link]:
        return [l for l in self.links if l.target_node_id == node_id]

    def topological_sort(self) -> list[str]:
        """Kahn 算法拓扑排序"""
        in_degree: dict[str, int] = {n.id: 0 for n in self.nodes}
        adj: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for link in self.links:
            adj[link.source_node_id].append(link.target_node_id)
            in_degree[link.target_node_id] = in_degree.get(link.target_node_id, 0) + 1
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []
        while queue:
            node_id = queue.pop(0)
            result.append(node_id)
            for neighbor in adj.get(node_id, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        if len(result) != len(self.nodes):
            raise ValueError("Graph contains a cycle!")
        return result

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "description": self.description,
                "nodes": [n.to_dict() for n in self.nodes],
                "links": [l.to_dict() for l in self.links],
                "metadata": self.metadata}


# ============================================================
# 模块 5: Workflow 执行引擎
# ============================================================

class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeResult:
    node_id: str
    block_id: str
    status: ExecutionStatus
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class WorkflowResult:
    graph_id: str
    status: ExecutionStatus
    node_results: list[NodeResult] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000

    def get_node_result(self, node_id: str) -> NodeResult | None:
        for r in self.node_results:
            if r.node_id == node_id:
                return r
        return None


class WorkflowEngine:
    """按拓扑排序执行 Graph, 通过 Link 传递数据"""

    def __init__(self):
        self._block_registry: dict[str, Block] = {}

    def register_block(self, block: Block) -> str:
        self._block_registry[block.id] = block
        return block.id

    def register_blocks(self, *blocks: Block) -> None:
        for b in blocks:
            self.register_block(b)

    def get_block(self, block_id: str) -> Block | None:
        return self._block_registry.get(block_id)

    def list_blocks(self) -> list[dict]:
        return [b.to_info() for b in self._block_registry.values()]

    async def execute(self, graph: Graph,
                      initial_inputs: dict[str, dict] | None = None,
                      on_node_complete: Callable[[NodeResult], None] | None = None) -> WorkflowResult:
        result = WorkflowResult(graph_id=graph.id, status=ExecutionStatus.RUNNING,
                                start_time=time_module.time())
        try:
            order = graph.topological_sort()
        except ValueError as e:
            result.status = ExecutionStatus.FAILED
            result.error = str(e)
            result.end_time = time_module.time()
            return result

        node_inputs: dict[str, dict] = dict(initial_inputs or {})

        visited: set[str] = set()
        remaining = set(order)

        while remaining:
            current_layer = []
            for nid in sorted(remaining):
                incoming = graph.get_incoming_links(nid)
                if all(l.source_node_id in visited for l in incoming):
                    current_layer.append(nid)
            if not current_layer:
                result.status = ExecutionStatus.FAILED
                result.error = f"Cannot resolve execution order. Remaining: {remaining}"
                result.end_time = time_module.time()
                return result

            tasks = []
            for node_id in current_layer:
                node = graph.get_node(node_id)
                if not node:
                    continue
                block = self._block_registry.get(node.block_id)
                if not block:
                    continue
                tasks.append(self._execute_node(node, block, node_inputs, graph, result, on_node_complete))

            if tasks:
                new_outputs = await asyncio.gather(*tasks, return_exceptions=True)
                for node_id, output in zip(current_layer, new_outputs):
                    if isinstance(output, Exception):
                        logger.warning(f"Node {node_id} failed: {output}")
                    elif output is not None:
                        for link in graph.get_outgoing_links(node_id):
                            if link.target_node_id not in node_inputs:
                                node_inputs[link.target_node_id] = {}
                            if link.target_input in output:
                                node_inputs[link.target_node_id][link.target_input] = output[link.target_input]

            for nid in current_layer:
                remaining.discard(nid)
                visited.add(nid)

        result.status = ExecutionStatus.SUCCESS
        result.end_time = time_module.time()
        return result

    async def _execute_node(self, node: Node, block: Block,
                            node_inputs: dict[str, dict], graph: Graph,
                            result: WorkflowResult,
                            on_node_complete: Callable[[NodeResult], None] | None) -> dict | None:
        start = time_module.time()
        node_result = NodeResult(node_id=node.id, block_id=block.id, status=ExecutionStatus.RUNNING)

        input_data = dict(node.config)
        if node.id in node_inputs:
            input_data.update(node_inputs[node.id])

        validation_error = await block.validate_input(input_data)
        if validation_error:
            node_result.status = ExecutionStatus.FAILED
            node_result.error = f"Input validation: {validation_error}"
            node_result.duration_ms = (time_module.time() - start) * 1000
            result.node_results.append(node_result)
            if on_node_complete:
                on_node_complete(node_result)
            return None

        try:
            outputs: dict[str, Any] = {}
            async for output_name, output_data in block.run(input_data):
                outputs[output_name] = output_data
            node_result.status = ExecutionStatus.SUCCESS
            node_result.outputs = outputs
            node_result.duration_ms = (time_module.time() - start) * 1000
            result.node_results.append(node_result)
            if on_node_complete:
                on_node_complete(node_result)
            return outputs
        except Exception as e:
            node_result.status = ExecutionStatus.FAILED
            node_result.error = f"{type(e).__name__}: {e}"
            node_result.duration_ms = (time_module.time() - start) * 1000
            result.node_results.append(node_result)
            if on_node_complete:
                on_node_complete(node_result)
            return None


# ============================================================
# 模块 6: 预置 Block 实现
# ============================================================

class TextInputBlock(Block[dict, AsyncGenerator]):
    id = "text_input"
    name = "文本输入"
    type = BlockType.INPUT
    categories = [BlockCategory.INPUT, BlockCategory.BASIC]
    description = "输入或接收文本数据"
    input_schema = Schema([
        FieldDef("text", "string", "输入文本", required=False, default=""),
        FieldDef("default_text", "string", "默认文本", required=False, default="Hello"),
    ])
    output_schema = Schema([
        FieldDef("text", "string", "输出文本"),
        FieldDef("length", "integer", "文本长度"),
    ])

    async def run(self, input_data: dict) -> AsyncGenerator:
        text = input_data.get("text") or input_data.get("default_text", "")
        yield "text", text
        yield "length", len(text)


class TextTransformBlock(Block[dict, AsyncGenerator]):
    id = "text_transform"
    name = "文本转换"
    type = BlockType.STANDARD
    categories = [BlockCategory.TEXT, BlockCategory.BASIC]
    description = "文本大小写转换、修剪等基本操作"
    input_schema = Schema([
        FieldDef("text", "string", "输入文本"),
        FieldDef("operation", "string", "操作类型",
                 enum_values=["uppercase", "lowercase", "title", "strip", "reverse"]),
    ])
    output_schema = Schema([
        FieldDef("result", "string", "转换结果"),
        FieldDef("original", "string", "原始文本"),
    ])

    async def run(self, input_data: dict) -> AsyncGenerator:
        text = input_data["text"]
        op = input_data.get("operation", "uppercase")
        ops = {"uppercase": text.upper(), "lowercase": text.lower(),
               "title": text.title(), "strip": text.strip(), "reverse": text[::-1]}
        result = ops.get(op, text)
        yield "result", result
        yield "original", text


class ConditionalGateBlock(Block[dict, AsyncGenerator]):
    id = "conditional_gate"
    name = "条件门"
    type = BlockType.GATE
    categories = [BlockCategory.LOGIC]
    description = "根据条件选择走 true 或 false 分支"
    input_schema = Schema([
        FieldDef("condition", "boolean", "条件值"),
        FieldDef("true_value", "string", "条件为真时传递的值", required=False, default=""),
        FieldDef("false_value", "string", "条件为假时传递的值", required=False, default=""),
    ])
    output_schema = Schema([
        FieldDef("output", "string", "选择的输出值"),
        FieldDef("branch", "string", "选择的分支 (true/false)"),
    ])

    async def run(self, input_data: dict) -> AsyncGenerator:
        if input_data.get("condition", False):
            yield "output", input_data.get("true_value", "")
            yield "branch", "true"
        else:
            yield "output", input_data.get("false_value", "")
            yield "branch", "false"


class LogBlock(Block[dict, AsyncGenerator]):
    id = "log"
    name = "日志输出"
    type = BlockType.OUTPUT
    categories = [BlockCategory.OUTPUT, BlockCategory.BASIC]
    description = "将数据输出到日志和控制台"
    input_schema = Schema([
        FieldDef("message", "string", "日志消息"),
        FieldDef("data", "object", "额外数据", required=False),
        FieldDef("level", "string", "日志级别",
                 enum_values=["debug", "info", "warning", "error"],
                 required=False, default="info"),
    ])
    output_schema = Schema([
        FieldDef("logged", "boolean", "是否成功记录"),
        FieldDef("level_used", "string", "使用的日志级别"),
    ])

    async def run(self, input_data: dict) -> AsyncGenerator:
        level = input_data.get("level", "info")
        msg = input_data["message"]
        data = input_data.get("data")
        log_msg = f"[Workflow] {msg}"
        if data:
            log_msg += f" | data={data}"
        log_fn = {"debug": logger.debug, "info": logger.info,
                  "warning": logger.warning, "error": logger.error}.get(level, logger.info)
        log_fn(log_msg)
        print(log_msg)
        yield "logged", True
        yield "level_used", level


# ============================================================
# 模块 7: Workflow Builder
# ============================================================

class WorkflowBuilder:
    """链式 API 构建 Graph"""

    def __init__(self, name: str = "", description: str = ""):
        self.graph = Graph(name=name, description=description)
        self._node_refs: dict[str, str] = {}

    def add_block(self, block: Block, config: dict | None = None,
                  label: str = "") -> "WorkflowBuilder":
        node = Node(block_id=block.id, config=config or {}, label=label or block.name)
        self.graph.add_node(node)
        node_key = block.id
        if node_key in self._node_refs:
            idx = 1
            while f"{node_key}_{idx}" in self._node_refs:
                idx += 1
            node_key = f"{node_key}_{idx}"
        self._node_refs[node_key] = node.id
        return self

    def connect(self, from_block: str | Block, from_output: str,
                to_block: str | Block, to_input: str) -> "WorkflowBuilder":
        src_key = from_block.id if isinstance(from_block, Block) else from_block
        tgt_key = to_block.id if isinstance(to_block, Block) else to_block
        src_node_id = self._node_refs.get(src_key)
        tgt_node_id = self._node_refs.get(tgt_key)
        if not src_node_id or not tgt_node_id:
            raise ValueError(f"Cannot connect {src_key}->{tgt_key}. Available: {list(self._node_refs.keys())}")
        self.graph.add_link(source=src_node_id, output=from_output,
                            target=tgt_node_id, target_input=to_input)
        return self

    def add_input(self, to_block: str, input_name: str, value: Any) -> "WorkflowBuilder":
        tgt_key = to_block.id if isinstance(to_block, Block) else to_block
        node_id = self._node_refs.get(tgt_key)
        if node_id:
            node = self.graph.get_node(node_id)
            if node:
                node.config[input_name] = value
        return self

    def remove(self, block_id: str) -> "WorkflowBuilder":
        node_id = self._node_refs.pop(block_id, None)
        if node_id:
            self.graph.nodes = [n for n in self.graph.nodes if n.id != node_id]
            self.graph.links = [l for l in self.graph.links
                                if l.source_node_id != node_id and l.target_node_id != node_id]
        return self

    def build(self) -> Graph:
        return self.graph

    def list_nodes(self) -> list[dict]:
        return [{"key": k, "node_id": v,
                 "block_id": self.graph.get_node(v).block_id if self.graph.get_node(v) else "?"}
                for k, v in self._node_refs.items()]


# ============================================================
# 模块 8: 装饰器系统
# ============================================================

_global_registry: dict[str, Block] = {}


def register(block_class: type[Block]) -> type[Block]:
    instance = block_class()
    _global_registry[instance.id] = instance
    return block_class


def block(id: str = "", name: str = "", type: BlockType = BlockType.STANDARD,
          categories: list[BlockCategory] | None = None, description: str = "",
          inputs: list[FieldDef] | None = None, outputs: list[FieldDef] | None = None):
    """装饰器: 从 async 函数快速创建 Block"""
    def decorator(func: Callable) -> type[Block]:
        class FuncBlock(Block[dict, AsyncGenerator]):
            id = id or func.__name__
            name = name or func.__name__.replace("_", " ").title()
            type = type
            categories = categories or [BlockCategory.BASIC]
            description = description or (func.__doc__ or "").strip()
            input_schema = Schema(inputs or [])
            output_schema = Schema(outputs or [])

            async def run(self, input_data: dict) -> AsyncGenerator:
                async for item in func(input_data):
                    yield item
        return FuncBlock
    return decorator


# ============================================================
# 自检函数
# ============================================================

def self_check() -> list[dict]:
    """6 项自检, 验证所有模块正常工作"""
    results = []

    # 1. BlockType + BlockCategory
    try:
        assert len(BlockType) == 10
        assert len(BlockCategory) == 13
        results.append({"name": "1. BlockType/BlockCategory", "status": "PASS",
                        "detail": "10 types, 13 categories"})
    except Exception as e:
        results.append({"name": "1. BlockType/BlockCategory", "status": "FAIL", "detail": str(e)})

    # 2. Schema + FieldDef
    try:
        s = Schema([FieldDef("name", "string", "名字"), FieldDef("age", "integer", "年龄", required=False)])
        d = s.to_dict()
        assert d["required"] == ["name"]
        assert s.validate({"name": "test"}) is None
        assert s.validate({}) is not None
        s2 = Schema([FieldDef("color", "string", "颜色", enum_values=["red", "blue"])])
        assert s2.validate({"color": "red"}) is None
        assert s2.validate({"color": "green"}) is not None
        results.append({"name": "2. Schema/FieldDef", "status": "PASS", "detail": "validation+enum OK"})
    except Exception as e:
        results.append({"name": "2. Schema/FieldDef", "status": "FAIL", "detail": str(e)})

    # 3. Block 基类
    try:
        class TestB(Block[dict, AsyncGenerator]):
            id = "test_block"
            name = "Test"
            input_schema = Schema([FieldDef("x", "integer")])
            output_schema = Schema([FieldDef("y", "integer")])
            async def run(self, input_data):
                yield "y", input_data["x"] * 2
        tb = TestB()
        info = tb.to_info()
        assert info["id"] == "test_block"
        assert info["type"] == "STANDARD"
        results.append({"name": "3. Block 基类", "status": "PASS", "detail": "subclass+to_info OK"})
    except Exception as e:
        results.append({"name": "3. Block 基类", "status": "FAIL", "detail": str(e)})

    # 4. Graph + 拓扑排序
    try:
        g = Graph(name="test")
        n1, n2, n3 = Node(block_id="a", id="n1"), Node(block_id="b", id="n2"), Node(block_id="c", id="n3")
        g.add_node(n1); g.add_node(n2); g.add_node(n3)
        g.add_link("n1", "out", "n2", "in"); g.add_link("n2", "out", "n3", "in")
        order = g.topological_sort()
        assert order == ["n1", "n2", "n3"]
        g2 = Graph()
        n4, n5 = Node(block_id="d", id="n4"), Node(block_id="e", id="n5")
        g2.add_node(n4); g2.add_node(n5)
        g2.add_link("n4", "o", "n5", "i"); g2.add_link("n5", "o", "n4", "i")
        try:
            g2.topological_sort()
            assert False, "Should detect cycle"
        except ValueError:
            pass
        results.append({"name": "4. Graph/拓扑排序", "status": "PASS", "detail": "sort+cycle detection OK"})
    except Exception as e:
        results.append({"name": "4. Graph/拓扑排序", "status": "FAIL", "detail": str(e)})

    # 5. WorkflowEngine 执行
    try:
        engine = WorkflowEngine()
        engine.register_blocks(TextInputBlock(), TextTransformBlock(), LogBlock())
        g3 = Graph(name="wf_test")
        tn = Node(block_id="text_input", config={"default_text": "hello world"}, id="ti")
        tt = Node(block_id="text_transform", config={"operation": "uppercase"}, id="tt")
        lg = Node(block_id="log", config={"level": "info"}, id="lg")
        g3.add_node(tn); g3.add_node(tt); g3.add_node(lg)
        g3.add_link("ti", "text", "tt", "text"); g3.add_link("tt", "result", "lg", "message")

        result = asyncio.run(engine.execute(g3))
        assert result.status == ExecutionStatus.SUCCESS
        ti_res = result.get_node_result("ti")
        tt_res = result.get_node_result("tt")
        assert ti_res and ti_res.status == ExecutionStatus.SUCCESS
        assert tt_res and tt_res.outputs.get("result") == "HELLO WORLD"
        results.append({"name": "5. WorkflowEngine", "status": "PASS",
                        "detail": f"exec OK, 3 nodes, {result.duration_ms:.1f}ms"})
    except Exception as e:
        results.append({"name": "5. WorkflowEngine", "status": "FAIL", "detail": str(e)})

    # 6. WorkflowBuilder 链式构建
    try:
        wf = (WorkflowBuilder("我的工作流")
              .add_block(TextInputBlock(), config={"default_text": "auto"})
              .add_block(TextTransformBlock(), config={"operation": "reverse"})
              .add_block(LogBlock(), config={"level": "info"})
              .connect("text_input", "text", "text_transform", "text")
              .connect("text_transform", "result", "log", "message"))
        g4 = wf.build()
        assert len(g4.nodes) == 3
        assert len(g4.links) == 2
        results.append({"name": "6. WorkflowBuilder", "status": "PASS",
                        "detail": "3 nodes, 2 links, chain API OK"})
    except Exception as e:
        results.append({"name": "6. WorkflowBuilder", "status": "FAIL", "detail": str(e)})

    return results
