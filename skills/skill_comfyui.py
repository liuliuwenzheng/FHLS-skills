"""
skill_comfyui.py - ComfyUI(680k⭐)骨髓内化: 图像生成工作流引擎
==============================================================

核心架构:
  NodeGraph(节点图) → NodeRegistry(节点注册) → DataFlow(数据流引擎) → 
  ImagePipeline(图像流水线) → WorkflowManager(工作流管理)

与GUI版ComfyUI的差异化: 纯Python节点图运行时, 可编程构建工作流
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Set, Tuple
from enum import Enum


# ====================
# 1. 节点系统 (ComfyUI Node)
# ====================

class NodeCategory(Enum):
    LOADER = "loader"         # 模型加载器
    SAMPLER = "sampler"       # 采样器
    LATENT = "latent"         # 潜空间操作
    IMAGE = "image"           # 图像操作
    MASK = "mask"             # 遮罩
    CONDITION = "condition"   # 条件控制
    OUTPUT = "output"         # 输出
    CUSTOM = "custom"         # 自定义


@dataclass
class NodeSlot:
    """节点输入/输出槽位"""
    name: str
    type: str  # "MODEL", "LATENT", "IMAGE", "CONDITIONING", "CLIP", "VAE", "INT", "FLOAT", "STRING"
    description: str = ""
    default: Any = None
    required: bool = True


@dataclass
class NodeDef:
    """节点定义"""
    name: str
    category: NodeCategory
    display_name: str = ""
    description: str = ""
    inputs: List[NodeSlot] = field(default_factory=list)
    outputs: List[NodeSlot] = field(default_factory=list)
    handler: Optional[Callable] = None
    
    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.name


class NodeInstance:
    """节点实例 - 工作流中的具体节点"""
    
    def __init__(self, node_def: NodeDef, node_id: str = None):
        self.defn = node_def
        self.id = node_id or str(uuid.uuid4())[:8]
        self.params: Dict[str, Any] = {}
        self.connections: Dict[str, str] = {}  # input_name -> source_node_id
        self._output_cache: Dict[str, Any] = {}
    
    def set_param(self, key: str, value: Any) -> None:
        self.params[key] = value
    
    def connect(self, input_name: str, source_node_id: str) -> None:
        self.connections[input_name] = source_node_id
    
    def disconnect(self, input_name: str) -> None:
        self.connections.pop(input_name, None)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.defn.name,
            "params": self.params,
            "connections": self.connections,
        }


# ====================
# 2. 节点注册中心 (ComfyUI内置节点集)
# ====================

class NodeRegistry:
    """节点注册中心 - 管理所有可用节点类型"""
    
    def __init__(self):
        self._nodes: Dict[str, NodeDef] = {}
        self._register_defaults()
    
    def _register_defaults(self):
        """注册ComfyUI核心节点"""
        # 模型加载器
        self.register(NodeDef(
            "CheckpointLoader", NodeCategory.LOADER,
            description="加载Stable Diffusion检查点模型",
            outputs=[
                NodeSlot("model", "MODEL"),
                NodeSlot("clip", "CLIP"),
                NodeSlot("vae", "VAE"),
            ],
            inputs=[NodeSlot("ckpt_name", "STRING", "模型名称", required=True)],
        ))
        self.register(NodeDef(
            "CLIPTextEncode", NodeCategory.CONDITION,
            description="CLIP文本编码",
            inputs=[
                NodeSlot("text", "STRING", "提示词", required=True),
                NodeSlot("clip", "CLIP", "CLIP模型"),
            ],
            outputs=[NodeSlot("conditioning", "CONDITIONING")],
        ))
        # 潜空间
        self.register(NodeDef(
            "EmptyLatentImage", NodeCategory.LATENT,
            description="创建空白潜空间",
            inputs=[
                NodeSlot("width", "INT", "宽度", default=512),
                NodeSlot("height", "INT", "高度", default=512),
                NodeSlot("batch_size", "INT", "批次", default=1),
            ],
            outputs=[NodeSlot("latent", "LATENT")],
        ))
        self.register(NodeDef(
            "VAEDecode", NodeCategory.LATENT,
            description="VAE解码(潜空间→图像)",
            inputs=[
                NodeSlot("samples", "LATENT", "潜空间样本"),
                NodeSlot("vae", "VAE", "VAE模型"),
            ],
            outputs=[NodeSlot("image", "IMAGE")],
        ))
        self.register(NodeDef(
            "VAEEncode", NodeCategory.LATENT,
            description="VAE编码(图像→潜空间)",
            inputs=[
                NodeSlot("pixels", "IMAGE", "输入图像"),
                NodeSlot("vae", "VAE", "VAE模型"),
            ],
            outputs=[NodeSlot("latent", "LATENT")],
        ))
        # 采样器
        self.register(NodeDef(
            "KSampler", NodeCategory.SAMPLER,
            description="K采样器(核心扩散步骤)",
            inputs=[
                NodeSlot("model", "MODEL", "扩散模型"),
                NodeSlot("positive", "CONDITIONING", "正向条件"),
                NodeSlot("negative", "CONDITIONING", "负向条件"),
                NodeSlot("latent_image", "LATENT", "潜空间输入"),
                NodeSlot("seed", "INT", "随机种子", default=42),
                NodeSlot("steps", "INT", "步数", default=20),
                NodeSlot("cfg", "FLOAT", "CFG引导强度", default=7.0),
                NodeSlot("sampler_name", "STRING", "采样器名称", default="euler"),
                NodeSlot("scheduler", "STRING", "调度器", default="normal"),
                NodeSlot("denoise", "FLOAT", "降噪强度", default=1.0),
            ],
            outputs=[NodeSlot("latent", "LATENT")],
        ))
        # 图像操作
        self.register(NodeDef(
            "SaveImage", NodeCategory.OUTPUT,
            description="保存图像到文件",
            inputs=[
                NodeSlot("images", "IMAGE", "图像数据"),
                NodeSlot("filename_prefix", "STRING", "文件名前缀", default="ComfyUI"),
            ],
        ))
        self.register(NodeDef(
            "PreviewImage", NodeCategory.OUTPUT,
            description="预览图像",
            inputs=[NodeSlot("images", "IMAGE", "图像数据")],
        ))
        self.register(NodeDef(
            "ImageScale", NodeCategory.IMAGE,
            description="图像缩放",
            inputs=[
                NodeSlot("image", "IMAGE", "输入图像"),
                NodeSlot("width", "INT", "目标宽度", default=512),
                NodeSlot("height", "INT", "目标高度", default=512),
                NodeSlot("method", "STRING", "缩放方法", default="lanczos"),
            ],
            outputs=[NodeSlot("image", "IMAGE")],
        ))
        # 遮罩
        self.register(NodeDef(
            "LoadImage", NodeCategory.LOADER,
            description="加载图像文件",
            inputs=[NodeSlot("image", "STRING", "图像路径", required=True)],
            outputs=[
                NodeSlot("image", "IMAGE"),
                NodeSlot("mask", "MASK"),
            ],
        ))
    
    def register(self, node_def: NodeDef) -> None:
        self._nodes[node_def.name] = node_def
    
    def get(self, name: str) -> Optional[NodeDef]:
        return self._nodes.get(name)
    
    def list(self, category: Optional[NodeCategory] = None) -> List[NodeDef]:
        if category:
            return [n for n in self._nodes.values() if n.category == category]
        return list(self._nodes.values())
    
    def create_instance(self, node_type: str, node_id: str = None) -> Optional[NodeInstance]:
        """创建节点实例"""
        ndef = self.get(node_type)
        if ndef:
            return NodeInstance(ndef, node_id)
        return None


# ====================
# 3. 节点图 (ComfyUI Workflow Graph)
# ====================

class NodeGraph:
    """节点图 - 工作流的有向图结构"""
    
    def __init__(self, registry: NodeRegistry):
        self.registry = registry
        self._nodes: Dict[str, NodeInstance] = {}
        self._edges: List[Tuple[str, str, str, str]] = []  # (from_id, from_slot, to_id, to_slot)
    
    def add_node(self, node_type: str, node_id: str = None) -> Optional[str]:
        """添加节点, 返回节点ID"""
        inst = self.registry.create_instance(node_type, node_id)
        if inst:
            self._nodes[inst.id] = inst
            return inst.id
        return None
    
    def remove_node(self, node_id: str) -> bool:
        """移除节点及关联边"""
        if node_id in self._nodes:
            self._edges = [(f, fs, t, ts) for f, fs, t, ts in self._edges 
                          if f != node_id and t != node_id]
            del self._nodes[node_id]
            return True
        return False
    
    def connect(self, from_id: str, from_slot: str, to_id: str, to_slot: str) -> bool:
        """连接两个节点"""
        if from_id in self._nodes and to_id in self._nodes:
            self._edges.append((from_id, from_slot, to_id, to_slot))
            self._nodes[to_id].connect(to_slot, from_id)
            return True
        return False
    
    def get_node(self, node_id: str) -> Optional[NodeInstance]:
        return self._nodes.get(node_id)
    
    def get_upstream(self, node_id: str) -> List[str]:
        """获取上游节点ID列表"""
        return [f for f, fs, t, ts in self._edges if t == node_id]
    
    def get_downstream(self, node_id: str) -> List[str]:
        """获取下游节点ID列表"""
        return [t for f, fs, t, ts in self._edges if f == node_id]
    
    def topological_sort(self) -> List[str]:
        """拓扑排序(ComfyUI的执行顺序)"""
        in_degree = {nid: 0 for nid in self._nodes}
        for f, fs, t, ts in self._edges:
            if t in in_degree:
                in_degree[t] = in_degree.get(t, 0) + 1
        
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []
        
        while queue:
            nid = queue.pop(0)
            result.append(nid)
            for down_id in self.get_downstream(nid):
                in_degree[down_id] -= 1
                if in_degree[down_id] == 0:
                    queue.append(down_id)
        
        return result
    
    @property
    def node_count(self) -> int:
        return len(self._nodes)
    
    def to_dict(self) -> dict:
        return {
            "nodes": {nid: node.to_dict() for nid, node in self._nodes.items()},
            "edges": [(f, fs, t, ts) for f, fs, t, ts in self._edges],
        }


# ====================
# 4. 数据流引擎 (ComfyUI Execution)
# ====================

class MockTensor:
    """模拟张量 - ComfyUI中的图像/潜空间数据"""
    
    def __init__(self, shape: Tuple[int, ...], dtype: str = "float32", data: str = "mock"):
        self.shape = shape
        self.dtype = dtype
        self._data = data
    
    def __repr__(self):
        return f"MockTensor({self.shape}, {self.dtype})"


class DataFlowEngine:
    """数据流执行引擎 - ComfyUI的核心执行器"""
    
    def __init__(self, graph: NodeGraph):
        self.graph = graph
        self._execution_cache: Dict[str, Dict[str, Any]] = {}
    
    def execute(self, seed: int = None) -> Dict[str, Any]:
        """执行完整工作流"""
        self._execution_cache.clear()
        order = self.graph.topological_sort()
        
        if seed is not None:
            import random
            random.seed(seed)
        
        for node_id in order:
            self._execute_node(node_id)
        
        # 收集所有输出
        outputs = {}
        for node_id in order:
            node = self.graph.get_node(node_id)
            if node and node.defn.category in (NodeCategory.OUTPUT,):
                outputs[node_id] = self._execution_cache.get(node_id, {})
        
        return {
            "execution_order": order,
            "outputs": outputs,
            "node_count": len(order),
        }
    
    def _execute_node(self, node_id: str) -> Dict[str, Any]:
        """执行单个节点"""
        if node_id in self._execution_cache:
            return self._execution_cache[node_id]
        
        node = self.graph.get_node(node_id)
        if not node:
            return {}
        
        ndef = node.defn
        inputs = {}
        
        # 收集输入(来自上游节点)
        for inp in ndef.inputs:
            if inp.name in node.connections:
                source_id = node.connections[inp.name]
                source_output = self._execute_node(source_id)
                # 找匹配的输出槽
                source_node = self.graph.get_node(source_id)
                if source_node:
                    for i, sout in enumerate(source_node.defn.outputs):
                        if sout.name == inp.name or i == 0:
                            inputs[inp.name] = source_output.get(sout.name)
                            break
            else:
                # 使用默认值
                inputs[inp.name] = inp.default
        
        # 合并params
        inputs.update(node.params)
        
        # 执行(模拟)
        result = self._mock_execute(ndef, inputs)
        self._execution_cache[node_id] = result
        return result
    
    def _mock_execute(self, ndef: NodeDef, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """模拟节点执行 - 返回mock数据"""
        outputs = {}
        for out in ndef.outputs:
            if out.type == "LATENT":
                h = inputs.get("height", 512)
                w = inputs.get("width", 512)
                outputs[out.name] = MockTensor((1, 4, h//8, w//8), "float32", f"{ndef.name}_latent")
            elif out.type == "IMAGE":
                outputs[out.name] = MockTensor((1, 3, inputs.get("height", 512), 
                                               inputs.get("width", 512)), 
                                               "uint8", f"{ndef.name}_image")
            elif out.type == "CONDITIONING":
                outputs[out.name] = {"pooled": None, "crossattn": MockTensor((1, 77, 768))}
            elif out.type == "MODEL":
                outputs[out.name] = f"Model({inputs.get('ckpt_name', 'unknown')})"
            elif out.type == "CLIP":
                outputs[out.name] = f"CLIP({inputs.get('ckpt_name', 'unknown')})"
            elif out.type == "VAE":
                outputs[out.name] = f"VAE({inputs.get('ckpt_name', 'unknown')})"
            elif out.type == "MASK":
                outputs[out.name] = MockTensor((1, 1, inputs.get("height", 512), 
                                               inputs.get("width", 512)))
            else:
                outputs[out.name] = inputs.get(out.name, out.default)
        
        return outputs
    
    def reset(self) -> None:
        self._execution_cache.clear()


# ====================
# 5. 工作流管理器 (ComfyUI Queue/History)
# ====================

@dataclass
class WorkflowPrompt:
    """工作流提示 - 包含所有参数"""
    positive: str = ""
    negative: str = ""
    seed: int = 42
    steps: int = 20
    cfg: float = 7.0
    width: int = 512
    height: int = 512
    sampler: str = "euler"
    batch_size: int = 1
    model: str = "sd_xl_base_1.0"
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowResult:
    """工作流执行结果"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    prompt: WorkflowPrompt = field(default_factory=WorkflowPrompt)
    outputs: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    created_at: float = field(default_factory=time.time)
    status: str = "completed"


class WorkflowManager:
    """工作流管理器 - 管理提示队列/历史/模板"""
    
    def __init__(self, engine: DataFlowEngine, graph: NodeGraph):
        self.engine = engine
        self.graph = graph
        self.history: List[WorkflowResult] = []
        self._templates: Dict[str, dict] = {}
    
    def run_prompt(self, prompt: WorkflowPrompt) -> WorkflowResult:
        """执行文本提示(自动构建工作流)"""
        start = time.time()
        
        # 自动构建标准txt2img工作流
        graph = NodeGraph(self.graph.registry)
        
        # CheckpointLoader → CLIPTextEncode(pos) → KSampler → VAEDecode → SaveImage
        ckpt = graph.add_node("CheckpointLoader")
        graph.get_node(ckpt).set_param("ckpt_name", prompt.model)
        
        clip_pos = graph.add_node("CLIPTextEncode")
        graph.get_node(clip_pos).set_param("text", prompt.positive)
        graph.connect(ckpt, "clip", clip_pos, "clip")
        
        clip_neg = graph.add_node("CLIPTextEncode")
        graph.get_node(clip_neg).set_param("text", prompt.negative or "")
        graph.connect(ckpt, "clip", clip_neg, "clip")
        
        latent = graph.add_node("EmptyLatentImage")
        graph.get_node(latent).set_param("width", prompt.width)
        graph.get_node(latent).set_param("height", prompt.height)
        graph.get_node(latent).set_param("batch_size", prompt.batch_size)
        
        sampler = graph.add_node("KSampler")
        s_node = graph.get_node(sampler)
        s_node.set_param("seed", prompt.seed)
        s_node.set_param("steps", prompt.steps)
        s_node.set_param("cfg", prompt.cfg)
        s_node.set_param("sampler_name", prompt.sampler)
        graph.connect(ckpt, "model", sampler, "model")
        graph.connect(clip_pos, "conditioning", sampler, "positive")
        graph.connect(clip_neg, "conditioning", sampler, "negative")
        graph.connect(latent, "latent", sampler, "latent_image")
        
        decode = graph.add_node("VAEDecode")
        graph.connect(sampler, "latent", decode, "samples")
        graph.connect(ckpt, "vae", decode, "vae")
        
        output = graph.add_node("SaveImage")
        graph.get_node(output).set_param("filename_prefix", f"GA_{prompt.model}")
        graph.connect(decode, "image", output, "images")
        
        # 执行
        self.engine = DataFlowEngine(graph)
        result_data = self.engine.execute(prompt.seed)
        
        elapsed = time.time() - start
        wf_result = WorkflowResult(
            prompt=prompt,
            outputs=result_data,
            execution_time=elapsed,
        )
        self.history.append(wf_result)
        return wf_result
    
    def load_workflow(self, workflow_json: str) -> NodeGraph:
        """从JSON加载工作流"""
        data = json.loads(workflow_json)
        graph = NodeGraph(self.graph.registry)
        
        for node_id, node_data in data.get("nodes", {}).items():
            graph.add_node(node_data["type"], node_id)
            inst = graph.get_node(node_id)
            if inst:
                for k, v in node_data.get("params", {}).items():
                    inst.set_param(k, v)
        
        for edge in data.get("edges", []):
            graph.connect(edge[0], edge[1], edge[2], edge[3])
        
        return graph
    
    def save_template(self, name: str, graph_dict: dict) -> None:
        """保存工作流模板"""
        self._templates[name] = graph_dict
    
    def list_history(self, limit: int = 10) -> List[WorkflowResult]:
        return self.history[-limit:]


# ====================
# 自检
# ====================

def _run_self_check() -> bool:
    print("=" * 60)
    print("📋 ComfyUI 自检 (680k⭐ 图像生成工作流)")
    print("=" * 60)
    
    # [1] NodeRegistry
    registry = NodeRegistry()
    nodes = registry.list()
    assert len(nodes) >= 10  # 至少10个内置节点
    assert registry.get("KSampler") is not None
    assert registry.get("NonExistent") is None
    assert registry.get("CheckpointLoader").category == NodeCategory.LOADER
    print(f"✅ NodeRegistry: {len(nodes)}个节点注册正常")
    
    # [2] NodeInstance
    inst = registry.create_instance("KSampler", "sampler_1")
    assert inst is not None
    assert inst.id == "sampler_1"
    inst.set_param("steps", 30)
    assert inst.params["steps"] == 30
    inst.connect("model", "ckpt_1")
    assert inst.connections["model"] == "ckpt_1"
    inst.disconnect("model")
    assert "model" not in inst.connections
    print("✅ NodeInstance: 创建/参数/连接正常")
    
    # [3] NodeGraph
    graph = NodeGraph(registry)
    ckpt_id = graph.add_node("CheckpointLoader")
    assert ckpt_id is not None
    latent_id = graph.add_node("EmptyLatentImage")
    sampler_id = graph.add_node("KSampler")
    assert graph.node_count == 3
    
    # 连接
    assert graph.connect(ckpt_id, "model", sampler_id, "model")
    assert graph.connect(latent_id, "latent", sampler_id, "latent_image")
    upstream = graph.get_upstream(sampler_id)
    assert len(upstream) == 2
    
    # 拓扑排序
    order = graph.topological_sort()
    assert len(order) == 3
    # CheckpointLoader和EmptyLatentImage应在KSampler之前
    assert order.index(ckpt_id) < order.index(sampler_id)
    assert order.index(latent_id) < order.index(sampler_id)
    
    # 删除节点
    graph.remove_node(latent_id)
    assert graph.node_count == 2
    
    print("✅ NodeGraph: 添加/连接/拓扑排序/删除正常")
    
    # [4] DataFlowEngine
    graph2 = NodeGraph(registry)
    ckpt = graph2.add_node("CheckpointLoader")
    graph2.get_node(ckpt).set_param("ckpt_name", "sd_xl_base")
    pos = graph2.add_node("CLIPTextEncode")
    graph2.get_node(pos).set_param("text", "beautiful landscape")
    graph2.connect(ckpt, "clip", pos, "clip")
    latent = graph2.add_node("EmptyLatentImage")
    graph2.get_node(latent).set_param("width", 1024)
    graph2.get_node(latent).set_param("height", 1024)
    sampler = graph2.add_node("KSampler")
    graph2.get_node(sampler).set_param("seed", 123)
    graph2.get_node(sampler).set_param("steps", 30)
    graph2.connect(ckpt, "model", sampler, "model")
    graph2.connect(pos, "conditioning", sampler, "positive")
    graph2.connect(latent, "latent", sampler, "latent_image")
    
    engine = DataFlowEngine(graph2)
    result = engine.execute(seed=123)
    assert result["node_count"] == 4
    assert len(result["execution_order"]) == 4
    
    engine.reset()
    assert engine._execution_cache == {}
    print("✅ DataFlowEngine: 执行/排序/重置正常")
    
    # [5] WorkflowManager
    graph3 = NodeGraph(registry)
    wfm = WorkflowManager(engine, graph3)
    prompt = WorkflowPrompt(
        positive="masterpiece, detailed",
        negative="blurry, low quality",
        seed=42, steps=20, cfg=7.5,
        width=768, height=768,
    )
    wf_result = wfm.run_prompt(prompt)
    assert len(wf_result.id) > 0
    assert wf_result.execution_time > 0
    history = wfm.list_history()
    assert len(history) == 1
    
    # 第二次运行
    wfm.run_prompt(WorkflowPrompt(seed=99))
    assert len(wfm.list_history()) == 2
    print("✅ WorkflowManager: 自动构建工作流/执行/历史正常")
    
    # [6] 端到端: 工作流JSON加载
    wf_json = json.dumps({
        "nodes": {
            "n1": {"type": "CheckpointLoader", "params": {"ckpt_name": "sd"}},
            "n2": {"type": "EmptyLatentImage", "params": {"width": 512, "height": 512}},
            "n3": {"type": "KSampler", "params": {"seed": 1}},
        },
        "edges": [
            ["n1", "model", "n3", "model"],
            ["n2", "latent", "n3", "latent_image"],
        ]
    })
    loaded_graph = wfm.load_workflow(wf_json)
    assert loaded_graph.node_count == 3
    assert loaded_graph.get_node("n3") is not None
    print("✅ 端到端: 工作流JSON序列化/反序列化正常")
    
    print(f"\n✅🎉 ComfyUI 自检通过 (6项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
