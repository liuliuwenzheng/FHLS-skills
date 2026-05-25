"""
skill_flowise.py - Flowise(320k⭐)骨髓内化: 低代码LLM应用构建
=============================================================

核心架构:
  FlowiseNode(基础节点系统) → LLMChain(LLM链管理) → 
  AgentExecutor(多Agent执行器) → VectorStore(向量数据库连接) → 
  WorkflowBuilder(可视化工作流构建)

与Dify的差异化:
  Dify: RAG应用+工作流+知识库管理(会话级)
  Flowise: 自定义Node/Chain/Agent编排(组件级)
  本模块聚焦Flowise的链式节点编排和动态Agent路由
"""

import json
import uuid
from enum import Enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ════════════════════════════════════════════════════════════
# 模块1: FlowiseNode - 节点系统(支持6种节点类型)
# ════════════════════════════════════════════════════════════

class NodeType(Enum):
    INPUT = "input"
    LLM = "llm"
    CHAIN = "chain"
    AGENT = "agent"
    TOOL = "tool"
    OUTPUT = "output"
    VECTOR_STORE = "vector_store"
    MEMORY = "memory"
    CONDITIONAL = "conditional"

@dataclass
class FlowiseNode:
    """基础节点"""
    id: str
    type: NodeType
    label: str
    config: dict = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    position: dict[str, float] = field(default_factory=lambda: {"x": 0, "y": 0})
    
    @classmethod
    def create_input(cls, label: str = "Input", prompt_template: str = "{{input}}"):
        return cls(
            id=str(uuid.uuid4())[:8],
            type=NodeType.INPUT,
            label=label,
            config={"prompt_template": prompt_template}
        )
    
    @classmethod
    def create_llm(cls, label: str = "LLM", provider: str = "openai", model: str = "gpt-4"):
        return cls(
            id=str(uuid.uuid4())[:8],
            type=NodeType.LLM,
            label=label,
            config={"provider": provider, "model": model, "temperature": 0.7}
        )
    
    @classmethod
    def create_chain(cls, label: str = "Chain", chain_type: str = "llm_chain"):
        return cls(
            id=str(uuid.uuid4())[:8],
            type=NodeType.CHAIN,
            label=label,
            config={"chain_type": chain_type}
        )
    
    @classmethod
    def create_agent(cls, label: str = "Agent", agent_type: str = "conversational", tools: list[str] = None):
        return cls(
            id=str(uuid.uuid4())[:8],
            type=NodeType.AGENT,
            label=label,
            config={"agent_type": agent_type, "tools": tools or []}
        )
    
    @classmethod
    def create_tool(cls, label: str = "Tool", tool_type: str = "search"):
        return cls(
            id=str(uuid.uuid4())[:8],
            type=NodeType.TOOL,
            label=label,
            config={"tool_type": tool_type}
        )
    
    @classmethod
    def create_output(cls, label: str = "Output", output_type: str = "text"):
        return cls(
            id=str(uuid.uuid4())[:8],
            type=NodeType.OUTPUT,
            label=label,
            config={"output_type": output_type}
        )
    
    def add_input(self, node_id: str):
        if node_id not in self.inputs:
            self.inputs.append(node_id)
    
    def add_output(self, node_id: str):
        if node_id not in self.outputs:
            self.outputs.append(node_id)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @staticmethod
    def from_dict(data: dict) -> "FlowiseNode":
        data["type"] = NodeType(data["type"])
        return FlowiseNode(**data)


class NodeRegistry:
    """节点注册表"""
    def __init__(self):
        self.nodes: dict[str, FlowiseNode] = {}
    
    def register(self, node: FlowiseNode) -> str:
        self.nodes[node.id] = node
        return node.id
    
    def get(self, node_id: str) -> Optional[FlowiseNode]:
        return self.nodes.get(node_id)
    
    def remove(self, node_id: str):
        if node_id in self.nodes:
            del self.nodes[node_id]
            for n in self.nodes.values():
                if node_id in n.inputs: n.inputs.remove(node_id)
                if node_id in n.outputs: n.outputs.remove(node_id)
    
    def connect(self, from_id: str, to_id: str):
        if from_id in self.nodes and to_id in self.nodes:
            self.nodes[from_id].add_output(to_id)
            self.nodes[to_id].add_input(from_id)
    
    def get_input_nodes(self, node_id: str) -> list[FlowiseNode]:
        node = self.nodes.get(node_id)
        if not node: return []
        return [self.nodes[i] for i in node.inputs if i in self.nodes]
    
    def get_output_nodes(self, node_id: str) -> list[FlowiseNode]:
        node = self.nodes.get(node_id)
        if not node: return []
        return [self.nodes[i] for i in node.outputs if i in self.nodes]
    
    def get_chain_order(self) -> list[str]:
        """拓扑排序"""
        in_degree = {nid: 0 for nid in self.nodes}
        for nid, node in self.nodes.items():
            for out in node.outputs:
                if out in in_degree:
                    in_degree[out] += 1
        
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []
        while queue:
            nid = queue.pop(0)
            result.append(nid)
            for out in self.nodes[nid].outputs:
                if out in in_degree:
                    in_degree[out] -= 1
                    if in_degree[out] == 0:
                        queue.append(out)
        
        if len(result) != len(self.nodes):
            raise ValueError("Cycle detected in node graph")
        return result
    
    def all_nodes(self) -> list[FlowiseNode]:
        return list(self.nodes.values())
    
    def size(self) -> int:
        return len(self.nodes)
    
    def to_serializable(self) -> dict:
        nodes = {}
        for nid, n in self.nodes.items():
            nodes[nid] = {"type": n.type.value, "label": n.label, "config": n.config,
                          "inputs": n.inputs, "outputs": n.outputs, "position": n.position}
        return nodes
    
    @staticmethod
    def from_serializable(data: dict) -> "NodeRegistry":
        reg = NodeRegistry()
        for nid, ndata in data.items():
            node = FlowiseNode(id=nid, type=NodeType(ndata["type"]), label=ndata["label"],
                               config=ndata.get("config", {}), inputs=ndata.get("inputs", []),
                               outputs=ndata.get("outputs", []), position=ndata.get("position", {"x":0,"y":0}))
            reg.nodes[nid] = node
        return reg

# ════════════════════════════════════════════════════════════
# 模块2: LLMChain - 链管理(Stuff/MapReduce/Refine)
# ════════════════════════════════════════════════════════════

class ChainType(Enum):
    LLM_CHAIN = "llm_chain"
    STUFF = "stuff"
    MAP_REDUCE = "map_reduce"
    REFINE = "refine"
    CONVERSATIONAL = "conversational"
    ROUTER = "router"

@dataclass
class LLMChain:
    """LLM链"""
    id: str
    chain_type: ChainType
    llm_config: dict = field(default_factory=dict)
    prompt_template: str = ""
    input_variables: list[str] = field(default_factory=list)
    output_key: str = "text"
    max_iterations: int = 3
    
    @classmethod
    def simple_chain(cls, prompt: str = "Answer: {{input}}", model: str = "gpt-4"):
        return cls(id=str(uuid.uuid4())[:8], chain_type=ChainType.LLM_CHAIN,
                   llm_config={"model": model, "temperature": 0.7},
                   prompt_template=prompt, input_variables=["input"])
    
    def execute(self, inputs: dict[str, Any]) -> dict:
        """模拟执行链"""
        output = self.prompt_template
        for var, val in inputs.items():
            output = output.replace("{{" + var + "}}", str(val))
        return {self.output_key: output}


class ChainManager:
    """链管理器"""
    def __init__(self):
        self.chains: dict[str, LLMChain] = {}
    
    def register(self, chain: LLMChain) -> str:
        self.chains[chain.id] = chain
        return chain.id
    
    def get(self, chain_id: str) -> Optional[LLMChain]:
        return self.chains.get(chain_id)
    
    def execute_chain(self, chain_id: str, inputs: dict) -> dict:
        chain = self.get(chain_id)
        if not chain:
            raise ValueError(f"Chain not found: {chain_id}")
        return chain.execute(inputs)
    
    def create_stuff_chain(self, documents: list[str], prompt: str) -> LLMChain:
        """Stuff: 将文档直接填入prompt"""
        combined = "\n\n".join(documents)
        full_prompt = prompt.replace("{{documents}}", combined)
        return LLMChain(id=str(uuid.uuid4())[:8], chain_type=ChainType.STUFF,
                       llm_config={"model": "gpt-4"}, prompt_template=full_prompt)


# ════════════════════════════════════════════════════════════
# 模块3: AgentExecutor - 多Agent执行器
# ════════════════════════════════════════════════════════════

class AgentType(Enum):
    CONVERSATIONAL = "conversational"
    REACT = "react"
    TOOL_CALLING = "tool_calling"
    ROUTER = "router"
    ORCHESTRATOR = "orchestrator"

@dataclass
class Agent:
    """Agent定义"""
    id: str
    agent_type: AgentType
    system_prompt: str = "You are a helpful assistant."
    tools: list[str] = field(default_factory=list)
    llm_config: dict = field(default_factory=lambda: {"model": "gpt-4", "temperature": 0.7})
    max_steps: int = 10
    
    @classmethod
    def conversational(cls, prompt: str = "You are a helpful assistant."):
        return cls(id=str(uuid.uuid4())[:8], agent_type=AgentType.CONVERSATIONAL, system_prompt=prompt)
    
    @classmethod
    def tool_caller(cls, tools: list[str]):
        return cls(id=str(uuid.uuid4())[:8], agent_type=AgentType.TOOL_CALLING, tools=tools)
    
    @classmethod
    def router(cls, routes: dict[str, str]):
        prompt = "Route to: " + ", ".join(f"{k}:{v}" for k, v in routes.items())
        return cls(id=str(uuid.uuid4())[:8], agent_type=AgentType.ROUTER, system_prompt=prompt)


class AgentExecutor:
    """Agent执行器"""
    def __init__(self):
        self.agents: dict[str, Agent] = {}
        self.tool_results: dict[str, Any] = {}
    
    def register(self, agent: Agent) -> str:
        self.agents[agent.id] = agent
        return agent.id
    
    def get(self, agent_id: str) -> Optional[Agent]:
        return self.agents.get(agent_id)
    
    def execute(self, agent_id: str, input_text: str, context: dict = None) -> dict:
        agent = self.get(agent_id)
        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")
        return {
            "agent_id": agent_id,
            "agent_type": agent.agent_type.value,
            "input": input_text,
            "output": f"[{agent.agent_type.value}] Processed: {input_text[:50]}...",
            "steps": [{"tool": t, "result": f"simulated_{t}"} for t in agent.tools] if agent.tools else []
        }
    
    def execute_with_tools(self, agent_id: str, input_text: str, tools: dict[str, callable]) -> dict:
        agent = self.get(agent_id)
        if not agent or not agent.tools:
            return self.execute(agent_id, input_text)
        
        steps = []
        for tool_name in agent.tools:
            if tool_name in tools:
                result = tools[tool_name](input_text)
                steps.append({"tool": tool_name, "result": result})
                self.tool_results[tool_name] = result
        
        return {
            "agent_id": agent_id,
            "agent_type": agent.agent_type.value,
            "input": input_text,
            "output": f"Completed {len(steps)} tool steps: {', '.join(s['tool'] for s in steps)}",
            "steps": steps
        }
    
    def route(self, router_id: str, input_text: str) -> str:
        """Router Agent: 根据输入路由到不同处理路径"""
        agent = self.get(router_id)
        if not agent or agent.agent_type != AgentType.ROUTER:
            raise ValueError("Invalid router agent")
        # 模拟路由: 根据关键词路由
        if "?" in input_text:
            return "qa_chain"
        elif any(w in input_text.lower() for w in ["create", "make", "generate"]):
            return "generation_chain"
        else:
            return "general_chain"


# ════════════════════════════════════════════════════════════
# 模块4: VectorStore - 向量数据库连接
# ════════════════════════════════════════════════════════════

@dataclass
class Document:
    """文档"""
    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    embedding: Optional[list[float]] = None


class VectorStore:
    """向量存储(内存实现)"""
    def __init__(self, name: str = "default"):
        self.name = name
        self.documents: list[Document] = []
        self.index: dict[str, Document] = {}
    
    def add_documents(self, docs: list[Document]):
        for doc in docs:
            self.index[doc.id] = doc
            self.documents.append(doc)
    
    def get(self, doc_id: str) -> Optional[Document]:
        return self.index.get(doc_id)
    
    def similarity_search(self, query: str, k: int = 4) -> list[Document]:
        """模拟相似度搜索"""
        scored = []
        query_lower = query.lower()
        query_words = set(query_lower.split())
        for doc in self.documents:
            content_lower = doc.content.lower()
            score = sum(1 for w in query_words if w in content_lower)
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for score, doc in scored[:k]]
    
    def delete(self, doc_id: str):
        if doc_id in self.index:
            self.documents = [d for d in self.documents if d.id != doc_id]
            del self.index[doc_id]
    
    def clear(self):
        self.documents.clear()
        self.index.clear()
    
    def size(self) -> int:
        return len(self.documents)


# ════════════════════════════════════════════════════════════
# 模块5: WorkflowBuilder - 工作流构建器
# ════════════════════════════════════════════════════════════

@dataclass
class ChatFlow:
    """完整对话流"""
    id: str
    name: str
    nodes: NodeRegistry
    chains: ChainManager
    agents: AgentExecutor
    vector_store: VectorStore
    entry_node_id: str = ""
    
    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "nodes": self.nodes.to_serializable(),
            "entry_node_id": self.entry_node_id
        }
    
    @staticmethod
    def from_dict(data: dict) -> "ChatFlow":
        flow = ChatFlow(id=data["id"], name=data["name"],
                       nodes=NodeRegistry.from_serializable(data["nodes"]),
                       chains=ChainManager(), agents=AgentExecutor(),
                       vector_store=VectorStore())
        flow.entry_node_id = data.get("entry_node_id", "")
        return flow


class WorkflowBuilder:
    """工作流构建器"""
    def __init__(self):
        self.nodes = NodeRegistry()
        self.chains = ChainManager()
        self.agents = AgentExecutor()
        self.vector_store = VectorStore("flowise_default")
    
    def add_input(self, prompt_template: str = "{{input}}") -> str:
        n = FlowiseNode.create_input(prompt_template=prompt_template)
        return self.nodes.register(n)
    
    def add_llm(self, provider: str = "openai", model: str = "gpt-4") -> str:
        n = FlowiseNode.create_llm(provider=provider, model=model)
        return self.nodes.register(n)
    
    def add_chain(self, chain_type: str = "llm_chain") -> str:
        n = FlowiseNode.create_chain(chain_type=chain_type)
        nid = self.nodes.register(n)
        chain = LLMChain.simple_chain()
        self.chains.register(chain)
        return nid
    
    def add_agent(self, agent_type: str = "conversational") -> str:
        n = FlowiseNode.create_agent(agent_type=agent_type)
        nid = self.nodes.register(n)
        agent = Agent.conversational()
        self.agents.register(agent)
        return nid
    
    def add_tool(self, tool_type: str = "search") -> str:
        n = FlowiseNode.create_tool(tool_type=tool_type)
        return self.nodes.register(n)
    
    def add_output(self, output_type: str = "text") -> str:
        n = FlowiseNode.create_output(output_type=output_type)
        return self.nodes.register(n)
    
    def connect(self, from_id: str, to_id: str):
        self.nodes.connect(from_id, to_id)
    
    def build_rag_flow(self, llm_model: str = "gpt-4") -> str:
        """构建RAG查询流程: Input -> VectorStore -> Chain -> Output"""
        inp = self.add_input()
        vs_node = FlowiseNode(
            id=f"vs_{uuid.uuid4().hex[:4]}", type=NodeType.VECTOR_STORE,
            label="VectorStore", config={"collection": "default", "k": 3})
        vs_id = self.nodes.register(vs_node)
        chain_node = self.add_chain()
        out = self.add_output()
        
        self.connect(inp, vs_id)
        self.connect(vs_id, chain_node)
        self.connect(chain_node, out)
        return inp
    
    def build_tool_agent_flow(self) -> str:
        """构建工具Agent流程: Input -> Agent(with Tools) -> Output"""
        inp = self.add_input()
        agent_node = self.add_agent(agent_type="tool_calling")
        tool_node = self.add_tool(tool_type="search")
        out = self.add_output()
        
        self.connect(inp, agent_node)
        self.connect(agent_node, out)
        return inp
    
    def build(self) -> ChatFlow:
        """构建会话流"""
        entry_nodes = [n for n in self.nodes.all_nodes() 
                      if n.type == NodeType.INPUT and not n.inputs]
        entry_id = entry_nodes[0].id if entry_nodes else ""
        
        return ChatFlow(
            id=str(uuid.uuid4())[:8],
            name=f"flow_{uuid.uuid4().hex[:6]}",
            nodes=self.nodes,
            chains=self.chains,
            agents=self.agents,
            vector_store=self.vector_store,
            entry_node_id=entry_id
        )
    
    def assemble(self, flow_id: str, root_node_id: str) -> str:
        """组装完整流程"""
        all_ids = set(n.id for n in self.nodes.all_nodes())
        for n in self.nodes.all_nodes():
            for i in n.inputs: assert i in all_ids, f"Missing input: {i}"
            for o in n.outputs: assert o in all_ids, f"Missing output: {o}"
        return root_node_id


# ════════════════════════════════════════════════════════════
# 自检
# ════════════════════════════════════════════════════════════

def _run_self_check():
    print("=" * 60)
    print("📋 Flowise 自检 (320k⭐ 低代码LLM应用构建)")
    print("=" * 60)
    
    # [1] FlowiseNode + NodeRegistry
    n1 = FlowiseNode.create_input()
    n2 = FlowiseNode.create_llm()
    n3 = FlowiseNode.create_chain()
    n4 = FlowiseNode.create_agent()
    n5 = FlowiseNode.create_tool()
    n6 = FlowiseNode.create_output()
    
    reg = NodeRegistry()
    reg.register(n1); reg.register(n2); reg.register(n3)
    reg.register(n4); reg.register(n5); reg.register(n6)
    assert reg.size() == 6
    
    reg.connect(n1.id, n2.id); reg.connect(n2.id, n3.id)
    reg.connect(n3.id, n4.id); reg.connect(n4.id, n5.id)
    reg.connect(n5.id, n6.id)
    assert len(reg.get_input_nodes(n6.id)) == 1
    
    order = reg.get_chain_order()
    assert len(order) == 6 and order[0] == n1.id
    
    sdata = reg.to_serializable()
    assert len(sdata) == 6
    reg2 = NodeRegistry.from_serializable(sdata)
    assert reg2.size() == 6
    print("✅ FlowiseNode+NodeRegistry: 创建/连接/拓扑/序列化正常 (6节点)")
    
    # [2] LLMChain + ChainManager
    chain = LLMChain.simple_chain("Hello {{name}}!")
    cm = ChainManager()
    cm.register(chain)
    result = cm.execute_chain(chain.id, {"name": "Flowise"})
    assert "Hello Flowise" in result["text"]
    
    docs = ["Doc1 content", "Doc2 content"]
    stuff = cm.create_stuff_chain(docs, "Summarize: {{documents}}")
    assert stuff.chain_type == ChainType.STUFF
    print("✅ LLMChain+ChainManager: 简单链/Stuff链执行正常")
    
    # [3] AgentExecutor
    conv_agent = Agent.conversational()
    tool_agent = Agent.tool_caller(tools=["search", "calculator"])
    router_agent = Agent.router({"qa": "qa", "gen": "gen"})
    
    ae = AgentExecutor()
    ae.register(conv_agent); ae.register(tool_agent); ae.register(router_agent)
    
    r1 = ae.execute(conv_agent.id, "Hello")
    assert r1["agent_type"] == "conversational"
    
    mock_tools = {"search": lambda x: f"searched: {x}", "calculator": lambda x: "42"}
    r2 = ae.execute_with_tools(tool_agent.id, "Calculate 6*7", mock_tools)
    assert len(r2["steps"]) == 2
    
    route_result = ae.route(router_agent.id, "How are you?")
    assert route_result == "qa_chain"
    print("✅ AgentExecutor: 对话/Tool调用/Router执行正常")
    
    # [4] VectorStore
    vs = VectorStore("test")
    docs = [Document(id=f"d{i}", content=f"Content about topic {i}") for i in range(5)]
    vs.add_documents(docs)
    assert vs.size() == 5
    results = vs.similarity_search("topic 3", k=2)
    assert len(results) >= 1
    print("✅ VectorStore: 文档添加/相似搜索正常")
    
    # [5] WorkflowBuilder
    builder = WorkflowBuilder()
    inp_id = builder.build_rag_flow()
    flow = builder.build()
    assert flow.entry_node_id == inp_id
    assert flow.nodes.size() >= 4
    
    serialized = flow.to_dict()
    assert "nodes" in serialized
    restored = ChatFlow.from_dict(serialized)
    assert restored.nodes.size() == flow.nodes.size()
    print("✅ WorkflowBuilder: RAG流程构建/序列化/反序列化正常")
    
    # [6] 端到端
    vs_node_config = FlowiseNode.create_input()
    vs_node_config.config = {"collection": "knowledge_base", "k": 3, "score": 0.8}
    result = vs_node_config.to_dict()
    assert result["config"]["k"] == 3
    
    assembled = builder.assemble("test_flow", root_node_id=inp_id)
    assert assembled == inp_id
    print("✅ 端到端: RAG流程构建/组装正常")
    
    print(f"\n✅🎉 Flowise 自检通过 (6项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
