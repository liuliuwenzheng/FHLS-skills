"""
GA Skill: Kairos 主动AI助手模式
================================
骨髓内化自 Anthropic Kairos 模式架构（图5）
+ Issue #61167(Opus4.7伪造agent调度) #60226(无据分析) 的教训

Kairos 核心理念: 从『被动响应』到『主动发现和帮助』
骨架: SDK + 网关 + 团队管理 + 跨会话记忆
GA可import: 主动检查器/自动团队生成/上下文整合
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from enum import Enum
import time, json, hashlib


# ============================================================
# 1. Kairos 模式核心定义
# ============================================================

class InteractionMode(Enum):
    """交互模式 — Kairos vs 普通"""
    PASSIVE = "passive"          # 普通: 被动响应
    PROACTIVE = "proactive"      # Kairos: 主动交互
    HYBRID = "hybrid"            # 混合模式


class TaskState(Enum):
    PENDING = "pending"          # 等待中
    ACTIVE = "active"            # 执行中
    COMPLETED = "completed"      # 已完成
    DEFERRED = "deferred"        # 延迟执行
    FAILED = "failed"            # 失败


@dataclass
class KairosConfig:
    """Kairos 模式配置 — 对应源码 feature flag KAIROS"""
    enabled: bool = False
    mode: InteractionMode = InteractionMode.PASSIVE
    
    # 主动行为参数
    auto_discover: bool = True           # 自动发现潜在问题
    background_tasks: bool = True        # 异步后台执行
    cross_session_memory: bool = True    # 跨会话记忆
    auto_team_generation: bool = True    # 自动生成Agent团队
    max_concurrent_tasks: int = 3        # 最大并行任务数
    proactive_interval: int = 300        # 主动检查间隔(秒)


@dataclass
class KairosState:
    """Kairos 运行时状态"""
    active_tasks: List[Dict] = field(default_factory=list)
    completed_tasks: List[Dict] = field(default_factory=list)
    discovered_issues: List[Dict] = field(default_factory=list)
    agent_team: List[Dict] = field(default_factory=list)
    last_proactive_check: float = 0.0
    session_id: str = ""


class KairosEngine:
    """
    Kairos 主动AI引擎 — GA版
    
    Kairos vs 普通模式:
    ┌────────────────┬────────────────────┐
    │    普通模式     │     Kairos模式      │
    ├────────────────┼────────────────────┤
    │ 被动响应        │ 主动交互             │
    │ 同步阻塞        │ 异步后台、多任务并行   │
    │ 单次会话        │ 跨会话持续记忆        │
    │ 手动创建Agent   │ 自动生成团队          │
    └────────────────┴────────────────────┘
    
    用法:
        kairos = KairosEngine()
        kairos.start_proactive_check()
    """
    
    def __init__(self, config: Optional[KairosConfig] = None):
        self.config = config or KairosConfig()
        self.state = KairosState()
        self.state.session_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:12]
        self._task_handlers: Dict[str, Callable] = {}
    
    def register_handler(self, task_type: str, handler: Callable):
        """注册任务处理函数"""
        self._task_handlers[task_type] = handler
    
    def start_proactive_check(self) -> List[Dict]:
        """主动检查 — Kairos核心: 不等待用户提问，主动发现问题"""
        if not self.config.auto_discover:
            return []
        
        now = time.time()
        if now - self.state.last_proactive_check < self.config.proactive_interval:
            return []
        
        self.state.last_proactive_check = now
        issues = self._discover_potential_issues()
        self.state.discovered_issues.extend(issues)
        return issues
    
    def _discover_potential_issues(self) -> List[Dict]:
        """发现潜在问题/机会 — 可扩展的检查清单"""
        checks = []
        # 检查未完成的任务
        pending = [t for t in self.state.active_tasks if t['state'] == TaskState.PENDING.value]
        if pending:
            checks.append({
                "type": "stalled_tasks",
                "severity": "info",
                "message": f"{len(pending)}个任务等待中，是否继续？",
                "tasks": [t['name'] for t in pending[:3]],
            })
        
        # 检查失败的任务
        failed = [t for t in self.state.completed_tasks if t['state'] == TaskState.FAILED.value]
        if failed:
            checks.append({
                "type": "failed_tasks",
                "severity": "warning",
                "message": f"{len(failed)}个任务失败，需处理",
                "tasks": [t['name'] for t in failed[:3]],
            })
        
        # 检查Agent团队状态
        overloaded = [a for a in self.state.agent_team if a.get('task_count', 0) > 3]
        if overloaded:
            checks.append({
                "type": "team_overload",
                "severity": "warning",
                "message": f"{len(overloaded)}个Agent过载",
                "agents": [a['name'] for a in overloaded],
            })
        
        return checks
    
    def spawn_agent_team(self, task_description: str) -> List[Dict]:
        """
        自动生成Agent团队 — Kairos核心能力
        
        根据任务描述自动生成合适的Agent团队配置
        """
        if not self.config.auto_team_generation:
            return []
        
        # 根据任务类型推断需要的Agent角色
        roles = self._infer_agent_roles(task_description)
        team = []
        
        for role in roles:
            agent = {
                "name": f"{role}_{len(self.state.agent_team)+1}",
                "role": role,
                "task_count": 0,
                "created_at": time.strftime('%H:%M:%S'),
                "status": "idle",
            }
            team.append(agent)
        
        self.state.agent_team.extend(team)
        return team
    
    def _infer_agent_roles(self, task: str) -> List[str]:
        """推断任务需要的Agent角色 — 策略模式"""
        task_lower = task.lower()
        roles = []
        
        role_patterns = [
            ("researcher", ["研究", "调研", "分析", "research", "analyze"]),
            ("developer", ["开发", "编码", "实现", "develop", "implement", "code"]),
            ("reviewer", ["审查", "检查", "review", "audit"]),
            ("tester", ["测试", "test", "debug"]),
            ("architect", ["架构", "设计", "architecture", "design"]),
            ("writer", ["文档", "报告", "write", "document"]),
            ("operator", ["部署", "运维", "deploy", "monitor"]),
        ]
        
        for role, keywords in role_patterns:
            if any(kw in task_lower for kw in keywords):
                if role not in roles:
                    roles.append(role)
        
        return roles[:self.config.max_concurrent_tasks]  # 不超过并发限制
    
    def background_execute(self, task_type: str, params: dict) -> str:
        """异步后台执行任务 — 不阻塞主流程"""
        if not self.config.background_tasks:
            return "background_tasks_disabled"
        
        task_id = hashlib.md5(f"{task_type}{time.time()}".encode()).hexdigest()[:8]
        task = {
            "id": task_id,
            "type": task_type,
            "params": params,
            "state": TaskState.ACTIVE.value,
            "created_at": time.strftime('%H:%M:%S'),
        }
        
        self.state.active_tasks.append(task)
        
        # 如果有注册的处理函数，立即执行
        if task_type in self._task_handlers:
            try:
                handler = self._task_handlers[task_type]
                result = handler(**params)
                task['state'] = TaskState.COMPLETED.value
                task['result'] = str(result)[:200]
            except Exception as e:
                task['state'] = TaskState.FAILED.value
                task['error'] = str(e)
        
        return task_id
    
    def integrate_memory(self, new_memory: Dict):
        """跨会话记忆整合 — Kairos的核心差异点"""
        if not self.config.cross_session_memory:
            return
        
        # 记忆去重 + 整合
        memory_hash = hashlib.md5(json.dumps(new_memory, sort_keys=True).encode()).hexdigest()
        new_memory['memory_id'] = memory_hash
        new_memory['integrated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        
        return new_memory
    
    def status_report(self) -> Dict:
        """Kairos状态报告"""
        return {
            "mode": self.config.mode.value,
            "active_tasks": len(self.state.active_tasks),
            "completed_tasks": len(self.state.completed_tasks),
            "discovered_issues": len(self.state.discovered_issues),
            "agent_team_size": len(self.state.agent_team),
            "session_id": self.state.session_id,
        }


# ============================================================
# 2. Kairos 模式宪法 — 防止AI越权（来自Issue #61167教训）
# ============================================================

KAIROS_CONSTITUTION = [
    "【R27-主动但透明】Kairos主动检查必须告知用户正在检查什么",
    "【R28-不伪造调度】Issue #61167教训: Agent调度必须有可见的审计链",
    "【R29-不越权】主动发现的问题不能自动执行，必须经用户确认",
    "【R30-可中断】任何主动后台任务都必须能被用户一键取消",
    "【R31-不虚构分析】Issue #60226教训: 无依据的分析不能作为决策基础",
    "【R32-记忆透明】跨会话记忆的内容必须可审计、可删除",
    "【R33-团队规模限制】自动生成的Agent团队不超过max_concurrent_tasks(默认3)",
]


if __name__ == "__main__":
    config = KairosConfig(enabled=True, mode=InteractionMode.PROACTIVE)
    kairos = KairosEngine(config)
    
    # 测试1: 主动检查
    issues = kairos.start_proactive_check()
    print(f"主动检查: 发现 {len(issues)} 个问题")
    
    # 测试2: 自动生成Agent团队
    team = kairos.spawn_agent_team("帮我开发一个Web应用，需要设计架构、编码实现、编写文档")
    print(f"\nAgent团队: 生成了 {len(team)} 个Agent")
    for agent in team:
        print(f"  🤖 {agent['name']} ({agent['role']})")
    
    # 测试3: 后台任务
    task_id = kairos.background_execute("research", {"query": "Kairos模式最佳实践"})
    print(f"\n后台任务: {task_id}")
    
    # 测试4: 状态报告
    report = kairos.status_report()
    print(f"\nKairos状态: {json.dumps(report, indent=2)}")
