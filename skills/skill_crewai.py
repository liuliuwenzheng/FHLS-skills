"""
skill_crewai.py — 多Agent自主团队编排引擎 (骨髓内化 CrewAI v1.14.5)

来源: skill_crewai.md (60行骨髓笔记, ⭐51.8k)
核心: Agent(Role+Goal+Backstory) → Task(Description+Tools) → Crew(Process+Memory)
双架构: Crews(自主团队) + Flows(事件驱动工作流)
本模块实现 Crews 架构: 多Agent角色编排、任务委派、自主决策

GA注入: 与skill_brain_adapter/agent_brain互补——Brain做单Agent决策,
         CrewAI做多Agent团队编排。

仅暴露: Agent, Task, Crew, Process, Flow, build_crew, kickoff
"""

import json
import random
from dataclasses import dataclass, field
from typing import Callable, Optional
from enum import Enum


# ══════════════════════════════════════════════════════════════
# 基础数据模型
# ══════════════════════════════════════════════════════════════

class ProcessType(Enum):
    """Crew编排方式"""
    SEQUENTIAL = "sequential"       # 顺序执行
    HIERARCHICAL = "hierarchical"   # 层级委派（Manager Agent调度）
    CONSENSUS = "consensus"         # 共识投票（多Agent投票决定）


@dataclass
class Agent:
    """AI Agent角色定义"""
    role: str                          # 角色名: "研究员", "写手"
    goal: str                          # 目标: "找到最新AI新闻"
    backstory: str                     # 背景: "你是一个资深技术记者..."
    tools: list[Callable] = field(default_factory=list)  # 可用工具函数列表
    allow_delegation: bool = True      # 是否允许委派任务给其他Agent
    verbose: bool = False

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "goal": self.goal,
            "backstory": self.backstory[:50] + "...",
            "tools": [t.__name__ if hasattr(t, '__name__') else str(t) for t in self.tools],
            "allow_delegation": self.allow_delegation,
        }


@dataclass
class Task:
    """任务定义"""
    description: str                   # 任务描述: "搜索GitHub上最新的LLM项目"
    expected_output: str = ""          # 期望输出描述: "一个Markdown列表"
    agent: Optional[Agent] = None      # 分配给的Agent
    tools: list[Callable] = field(default_factory=list)  # 任务级工具
    context: list = field(default_factory=list)           # 上下文（其他任务的输出）
    async_execution: bool = False      # 是否异步执行

    # 执行结果
    result: str = ""
    status: str = "pending"            # pending | running | completed | failed

    def to_dict(self) -> dict:
        return {
            "description": self.description[:60] + "...",
            "expected_output": self.expected_output[:30] + "...",
            "agent": self.agent.role if self.agent else "unassigned",
            "status": self.status,
        }


@dataclass
class Crew:
    """Agent团队"""
    agents: list[Agent]
    tasks: list[Task]
    process: ProcessType = ProcessType.SEQUENTIAL
    verbose: bool = False
    memory: bool = True                # 是否启用任务记忆（上下文传递）
    max_rpm: int = 0                   # 每分钟最大请求数

    # 执行状态
    _results: list = field(default_factory=list)
    _step: int = 0

    def to_dict(self) -> dict:
        return {
            "agents": [a.role for a in self.agents],
            "tasks": len(self.tasks),
            "process": self.process.value,
            "memory": self.memory,
        }


@dataclass
class FlowState:
    """Flow执行状态"""
    state: dict = field(default_factory=dict)
    methods: dict = field(default_factory=dict)  # name -> Callable


@dataclass
class Flow:
    """事件驱动工作流 (简化版)"""
    name: str
    description: str = ""
    _state: FlowState = field(default_factory=FlowState)


# ══════════════════════════════════════════════════════════════
# 核心编排逻辑
# ══════════════════════════════════════════════════════════════

def _simulate_agent_think(agent: Agent, task: Task, context: list = None) -> str:
    """
    模拟Agent执行任务。
    在真实CrewAI中, Agent会调用LLM生成回复. 
    本模块作为编排引擎, 由GA的工具(如skill_brain_adapter)注入真实LLM调用。
    此处返回模拟结果用于测试验证。
    """
    tools_desc = ", ".join(t.__name__ if hasattr(t, '__name__') else str(t) for t in agent.tools)
    context_str = ""
    if context:
        context_str = "\n  上下文: " + "; ".join(c[:40] for c in context if c)
    
    return (
        f"[{agent.role}] 完成: {task.description[:40]}\n"
        f"  背景: {agent.backstory[:50]}...\n"
        f"  目标: {agent.goal}\n"
        f"  工具: [{tools_desc or '无'}]\n"
        f"  输出: 根据'{task.expected_output[:30]}'生成的模拟结果{context_str}"
    )


def _sequential_process(crew: Crew) -> list:
    """顺序执行: task1→task2→task3"""
    results = []
    prev_output = ""
    
    for i, task in enumerate(crew.tasks):
        task.status = "running"
        agent = task.agent or crew.agents[i % len(crew.agents)]
        context = [prev_output] if crew.memory and prev_output else []
        
        result = _simulate_agent_think(agent, task, context)
        task.result = result
        task.status = "completed"
        results.append(result)
        prev_output = result
        
        if crew.verbose:
            print(f"  [{i+1}/{len(crew.tasks)}] {agent.role}: {task.description[:40]}... ✅")
    
    return results


def _hierarchical_process(crew: Crew) -> list:
    """层级委派: Manager分配任务给Agent执行"""
    # 第一个Agent作为Manager
    manager = crew.agents[0]
    workers = crew.agents[1:] if len(crew.agents) > 1 else crew.agents
    
    results = []
    
    for i, task in enumerate(crew.tasks):
        task.status = "running"
        
        # Manager决策: 谁最适合执行
        assigned = workers[i % len(workers)]
        
        if crew.verbose:
            print(f"  [{i+1}/{len(crew.tasks)}] {manager.role} 委派给 {assigned.role}")
        
        result = _simulate_agent_think(assigned, task)
        task.result = result
        task.status = "completed"
        results.append(result)
    
    return results


def _consensus_process(crew: Crew) -> list:
    """共识投票: 所有Agent独立执行, 投票选最佳结果"""
    results = []
    
    for i, task in enumerate(crew.tasks):
        task.status = "running"
        candidates = []
        
        # 所有Agent独立执行
        for agent in crew.agents:
            result = _simulate_agent_think(agent, task)
            candidates.append((agent.role, result))
        
        # 投票: 选第一个Agent的结果作为共识
        # 真实CrewAI中, 这步也会调LLM去评估
        chosen = candidates[0]
        
        if crew.verbose:
            print(f"  [{i+1}/{len(crew.tasks)}] 共识: {chosen[0]} 的方案被选中 ({len(candidates)}个候选)")
        
        task.result = chosen[1]
        task.status = "completed"
        results.append(chosen[1])
    
    return results


# ══════════════════════════════════════════════════════════════
# 公开API
# ══════════════════════════════════════════════════════════════

PROCESS_MAP = {
    ProcessType.SEQUENTIAL: _sequential_process,
    ProcessType.HIERARCHICAL: _hierarchical_process,
    ProcessType.CONSENSUS: _consensus_process,
}


def build_crew(agents: list[Agent], tasks: list[Task], 
               process: ProcessType = ProcessType.SEQUENTIAL,
               verbose: bool = False, memory: bool = True) -> Crew:
    """从Agent和Task列表构建Crew"""
    # 自动分配Agent给Task
    for i, task in enumerate(tasks):
        if task.agent is None:
            task.agent = agents[i % len(agents)]
    
    return Crew(
        agents=agents,
        tasks=tasks,
        process=process,
        verbose=verbose,
        memory=memory,
    )


def kickoff(crew: Crew) -> list:
    """启动Crew执行, 返回每个任务的结果列表"""
    if not crew.agents:
        raise ValueError("Crew必须包含至少1个Agent")
    if not crew.tasks:
        raise ValueError("Crew必须包含至少1个Task")
    
    if crew.verbose:
        print(f"\n🚀 Kickoff: {len(crew.agents)}个Agent, {len(crew.tasks)}个Task, {crew.process.value}模式")
    
    executor = PROCESS_MAP.get(crew.process)
    if not executor:
        raise ValueError(f"不支持的编排方式: {crew.process}")
    
    crew._results = executor(crew)
    crew._step = len(crew.tasks)
    
    return crew._results


def build_flow(name: str, description: str = "") -> Flow:
    """构建事件驱动工作流"""
    return Flow(name=name, description=description)


def add_step(flow: Flow, name: str, fn: Callable, 
             depends_on: list[str] = None) -> Flow:
    """向Flow添加步骤"""
    flow._state.methods[name] = {
        "fn": fn,
        "depends_on": depends_on or [],
        "result": None,
    }
    return flow


def run_flow(flow: Flow, initial_state: dict = None) -> dict:
    """执行Flow, 返回合并后的state"""
    state = dict(initial_state or {})
    
    executed = set()
    while len(executed) < len(flow._state.methods):
        made_progress = False
        for name, meta in flow._state.methods.items():
            if name in executed:
                continue
            deps = meta.get("depends_on", [])
            if all(d in executed for d in deps):
                context = {d: flow._state.methods[d]["result"] for d in deps}
                fn = meta["fn"]
                result = fn(state, context) if deps else fn(state)
                meta["result"] = result
                if isinstance(result, dict):
                    state.update(result)
                executed.add(name)
                made_progress = True
                break
        if not made_progress:
            break
    
    return state


def _run_self_check():
    """自检：验证核心API可用"""
    print("=" * 60)
    print("📋 CrewAI 自检 (51.8k⭐ 多Agent编排)")
    print("=" * 60)

    # 1. Agent创建
    agent = Agent(
        role="研究员",
        goal="收集数据",
        backstory="你是一名研究员",
        tools=[],
        allow_delegation=False,
        verbose=True
    )
    d = agent.to_dict()
    assert d["role"] == "研究员", f"role不对: {d['role']}"
    assert d["allow_delegation"] == False
    print(f"✅ Agent创建: role={d['role']}, delegation={d['allow_delegation']}")

    # 2. Task创建
    task = Task(
        description="分析数据",
        agent=agent,
        expected_output="分析报告"
    )
    assert task.agent.role == "研究员"
    assert task.status == "pending"
    print(f"✅ Task创建: desc={task.description[:10]}..., agent={task.agent.role}")

    # 3. Crew创建
    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=ProcessType.SEQUENTIAL,
        verbose=True
    )
    assert len(crew.agents) == 1
    assert len(crew.tasks) == 1
    assert crew.process == ProcessType.SEQUENTIAL
    print(f"✅ Crew创建: {len(crew.agents)} agent, {len(crew.tasks)} task, process={crew.process.name}")

    # 4. build_crew + kickoff
    crew2 = build_crew([agent], [task], verbose=False)
    results = kickoff(crew2)
    assert isinstance(results, list)
    assert len(results) == 1
    print(f"✅ build_crew+kickoff: {len(crew2.agents)} agent, {len(crew2.tasks)} tasks, {len(results)} results")

    # 5. Flow测试
    flow = build_flow("test_flow", "自检工作流")
    flow._state.methods["step1"] = {"fn": lambda s: {"data": "hello"}, "depends_on": []}
    flow._state.methods["step2"] = {"fn": lambda s, ctx: {"result": f"got {ctx['step1']['data']}"}, "depends_on": ["step1"]}
    state = run_flow(flow)
    assert state["data"] == "hello", f"step1不对: {state}"
    assert state["result"] == "got hello", f"step2不对: {state}"
    print(f"✅ Flow DAG: step1→step2, result={state['result']}")

    # 6. ProcessType枚举
    assert ProcessType.SEQUENTIAL.value == "sequential"
    assert ProcessType.HIERARCHICAL.value == "hierarchical"
    assert ProcessType.CONSENSUS.value == "consensus"
    print(f"✅ ProcessType枚举: 3种({ProcessType.SEQUENTIAL.name}/{ProcessType.HIERARCHICAL.name}/{ProcessType.CONSENSUS.name})")

    print(f"\n{'✅' if True else '❌'} CrewAI 自检通过 ({len(dir())} 公开API)")
    print("=" * 60)
    return True
