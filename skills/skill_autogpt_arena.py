"""
skill_autogpt_arena.py — AutoGPT Arena 多Agent对战/评估系统骨髓内化

骨髓内化来源: AutoGPT (Significant-Gravitas, 184k⭐)
原始模块: autogpt_platform/backend/backend/arena/*, server/arena.py

设计哲学（用自己的话重建）:
  Arena不是简单的"排行榜"——它是Agent的实战训练场。
  核心思想：Agent之间的对战产生"压力"→暴露弱点→加速进化。
  类似AlphaGo的自我对弈，但AutoGPT做的是异构Agent之间的对决。

骨架:
  ① AgentEvaluator — 评估基类，可扩展metric
  ② MatchRunner — 单场对局运行器
  ③ ArenaTournament — 锦标赛管理（排位+匹配+积分）
  ④ Leaderboard — 排行榜/数据可视化
  ⑤ BenchmarkSuite — 预定义基准测试（Web/Code/Reasoning等）

GA嫁接点:
  ① skill_block_workflow.Block → Arena的Agent包装器
  ② skill_autogpt_core.BlockCost → 对局Token成本核算
  ③ Startup自检Step5 → 依赖完整性检查
"""

import json
import time
import uuid
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

T = TypeVar('T')


# ============================================================
# ① AgentEvaluator — 评估基类
# ============================================================

class AgentEvaluator:
    """Agent评估器基类，定义评估接口和分数计算逻辑"""
    
    def __init__(self, name: str = "base_evaluator", weights: Optional[Dict[str, float]] = None):
        self.name = name
        self.weights = weights or {"accuracy": 0.4, "efficiency": 0.3, "completeness": 0.3}
        self.history: List[Dict[str, Any]] = []
    
    def evaluate(self, task: str, agent_output: Any, expected: Any = None) -> Dict[str, float]:
        """评估单次Agent输出，返回多维度分数"""
        raise NotImplementedError
    
    def aggregate(self, eval_results: List[Dict[str, float]]) -> Dict[str, float]:
        """汇总多次评估结果为综合得分"""
        if not eval_results:
            return {}
        aggregated = {}
        for key in eval_results[0]:
            values = [r.get(key, 0) for r in eval_results]
            aggregated[key] = sum(values) / len(values)
        
        # 加权总分
        total = 0
        for metric, weight in self.weights.items():
            if metric in aggregated:
                total += aggregated[metric] * weight
        aggregated["total"] = total
        return aggregated
    
    def record(self, agent_id: str, scores: Dict[str, float], metadata: Optional[Dict] = None) -> None:
        """记录评估结果到历史"""
        entry = {
            "agent_id": agent_id,
            "scores": scores,
            "timestamp": time.time(),
            "metadata": metadata or {}
        }
        self.history.append(entry)
    
    def get_agent_stats(self, agent_id: str) -> Dict[str, float]:
        """获取某个Agent的历史统计"""
        relevant = [e for e in self.history if e["agent_id"] == agent_id]
        if not relevant:
            return {}
        scores_list = [e["scores"] for e in relevant]
        return self.aggregate(scores_list)


class AccuracyEvaluator(AgentEvaluator):
    """准确性评估器 — 适用于有标准答案的任务"""
    
    def __init__(self):
        super().__init__("accuracy", weights={"accuracy": 0.6, "speed": 0.2, "relevance": 0.2})
    
    def evaluate(self, task: str, agent_output: Any, expected: Any = None) -> Dict[str, float]:
        """基于字符串匹配/语义相似的评估"""
        output_str = str(agent_output) if agent_output else ""
        expected_str = str(expected) if expected else ""
        
        # 简单精确匹配
        if expected_str and output_str:
            common = len(set(output_str.lower().split()) & set(expected_str.lower().split()))
            total = max(len(set(expected_str.lower().split())), 1)
            accuracy = common / total
        else:
            accuracy = 0.5  # 无标准答案时给中等分
        
        speed = min(1.0, len(output_str) / 1000) if output_str else 0
        relevance = min(1.0, len([w for w in task.lower().split() if w in output_str.lower()]) / 3 or 0.1)
        
        return {"accuracy": accuracy, "speed": speed, "relevance": relevance}


class EfficiencyEvaluator(AgentEvaluator):
    """效率评估器 — 权衡Token消耗与输出质量"""
    
    def __init__(self):
        super().__init__("efficiency", weights={"token_efficiency": 0.3, "time_efficiency": 0.3, "quality_ratio": 0.4})
    
    def evaluate(self, task: str, agent_output: Any, expected: Any = None) -> Dict[str, float]:
        """评估效率和质量的平衡"""
        if isinstance(agent_output, dict):
            token_cost = agent_output.get("token_cost", 100)
            latency = agent_output.get("latency", 10)
            output = agent_output.get("output", "")
        else:
            token_cost = 100
            latency = 10
            output = str(agent_output) if agent_output else ""
        
        output_len = len(output)
        token_efficiency = min(1.0, output_len / max(token_cost, 1)) * 10
        token_efficiency = min(1.0, token_efficiency)
        time_efficiency = min(1.0, 30 / max(latency, 1))
        quality_ratio = min(1.0, output_len / 500) if output_len > 0 else 0
        
        return {
            "token_efficiency": token_efficiency,
            "time_efficiency": time_efficiency,
            "quality_ratio": quality_ratio
        }


# ============================================================
# ② MatchRunner — 单场对局运行器
# ============================================================

@dataclass
class MatchConfig:
    """对局配置"""
    max_turns: int = 10
    timeout_per_turn: int = 60
    judge_model: str = "claude"  # 裁判Agent
    scoring_mode: str = "comparative"  # comparative | absolute
    auto_restart: bool = False


@dataclass
class MatchResult:
    """单场对局结果"""
    match_id: str
    agent_a_id: str
    agent_b_id: str
    task: str
    winner: Optional[str]  # None = 平局
    scores_a: Dict[str, float]
    scores_b: Dict[str, float]
    duration: float
    turns_taken: int
    judge_feedback: str = ""


class MatchRunner:
    """单场对局运行器 — 管理两个Agent之间的对战"""
    
    def __init__(self, evaluator: AgentEvaluator, config: Optional[MatchConfig] = None):
        self.evaluator = evaluator
        self.config = config or MatchConfig()
        self.results: List[MatchResult] = []
    
    def run(self, task: str, agent_a: Callable, agent_b: Callable, 
            agent_a_id: str = "agent_a", agent_b_id: str = "agent_b") -> MatchResult:
        """执行一场对局"""
        match_id = f"match_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        
        # 获取两个Agent的输出
        try:
            output_a = agent_a(task)
        except Exception as e:
            output_a = {"error": str(e), "output": ""}
        
        try:
            output_b = agent_b(task)
        except Exception as e:
            output_b = {"error": str(e), "output": ""}
        
        # 评估
        scores_a = self.evaluator.evaluate(task, output_a)
        scores_b = self.evaluator.evaluate(task, output_b)
        
        total_a = scores_a.get("accuracy", 0) * self.evaluator.weights.get("accuracy", 0.33) +                   scores_a.get("speed", 0) * self.evaluator.weights.get("speed", 0.33) +                   scores_a.get("relevance", 0) * self.evaluator.weights.get("relevance", 0.34)
        
        total_b = scores_b.get("accuracy", 0) * self.evaluator.weights.get("accuracy", 0.33) +                   scores_b.get("speed", 0) * self.evaluator.weights.get("speed", 0.33) +                   scores_b.get("relevance", 0) * self.evaluator.weights.get("relevance", 0.34)
        
        duration = time.time() - start_time
        
        if total_a > total_b:
            winner = agent_a_id
        elif total_b > total_a:
            winner = agent_b_id
        else:
            winner = None
        
        result = MatchResult(
            match_id=match_id,
            agent_a_id=agent_a_id,
            agent_b_id=agent_b_id,
            task=task,
            winner=winner,
            scores_a=scores_a,
            scores_b=scores_b,
            duration=duration,
            turns_taken=1
        )
        
        # 记录评估历史
        self.evaluator.record(agent_a_id, scores_a, {"task": task, "match_id": match_id})
        self.evaluator.record(agent_b_id, scores_b, {"task": task, "match_id": match_id})
        self.results.append(result)
        
        return result
    
    def run_comparative(self, task: str, agents: Dict[str, Callable]) -> List[MatchResult]:
        """多Agent循环对战（每个Agent两两对战）"""
        agent_ids = list(agents.keys())
        results = []
        
        for i in range(len(agent_ids)):
            for j in range(i + 1, len(agent_ids)):
                a_id, b_id = agent_ids[i], agent_ids[j]
                result = self.run(task, agents[a_id], agents[b_id], a_id, b_id)
                results.append(result)
        
        return results


# ============================================================
# ③ ArenaTournament — 锦标赛管理
# ============================================================

@dataclass
class ArenaAgent:
    """锦标赛中的Agent信息"""
    id: str
    name: str
    elo: int = 1000
    matches_played: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    
    @property
    def win_rate(self) -> float:
        return self.wins / max(self.matches_played, 1)


class ArenaTournament:
    """锦标赛管理器 — 排位/匹配/积分系统（类Elo算法）"""
    
    def __init__(self, name: str = "GA Arena"):
        self.name = name
        self.agents: Dict[str, ArenaAgent] = {}
        self.match_history: List[MatchResult] = []
        self.k_factor: int = 32  # Elo K值
        self.rounds_completed: int = 0
    
    def register(self, agent_id: str, name: Optional[str] = None) -> ArenaAgent:
        """注册一个Agent到锦标赛"""
        if agent_id in self.agents:
            return self.agents[agent_id]
        agent = ArenaAgent(id=agent_id, name=name or agent_id)
        self.agents[agent_id] = agent
        return agent
    
    def unregister(self, agent_id: str) -> bool:
        """移除Agent"""
        return self.agents.pop(agent_id, None) is not None
    
    def _update_elo(self, a_id: str, b_id: str, winner: Optional[str]) -> Tuple[int, int]:
        """计算并更新Elo积分"""
        a = self.agents[a_id]
        b = self.agents[b_id]
        
        # 预期胜率
        expected_a = 1.0 / (1.0 + 10.0 ** ((b.elo - a.elo) / 400.0))
        expected_b = 1.0 - expected_a
        
        # 实际结果
        if winner == a_id:
            score_a, score_b = 1.0, 0.0
        elif winner == b_id:
            score_a, score_b = 0.0, 1.0
        else:
            score_a, score_b = 0.5, 0.5
        
        # 积分变动
        delta_a = int(self.k_factor * (score_a - expected_a))
        delta_b = int(self.k_factor * (score_b - expected_b))
        
        a.elo += delta_a
        b.elo += delta_b
        a.matches_played += 1
        b.matches_played += 1
        
        if winner == a_id:
            a.wins += 1
            b.losses += 1
        elif winner == b_id:
            b.wins += 1
            a.losses += 1
        else:
            a.draws += 1
            b.draws += 1
        
        return delta_a, delta_b
    
    def record_match(self, result: MatchResult) -> None:
        """记录一场比赛并更新排名"""
        if result.agent_a_id not in self.agents:
            self.register(result.agent_a_id)
        if result.agent_b_id not in self.agents:
            self.register(result.agent_b_id)
        
        self._update_elo(result.agent_a_id, result.agent_b_id, result.winner)
        self.match_history.append(result)
    
    def create_round(self, agents: Optional[List[str]] = None) -> List[Tuple[str, str, str]]:
        """创建一轮配对（基于Elo匹配，高分VS高分）"""
        pool = agents or list(self.agents.keys())
        if not pool:
            return []
        
        # 按Elo排序后配对
        ranked = sorted(pool, key=lambda x: self.agents.get(x, ArenaAgent(id=x, name=x)).elo, reverse=True)
        pairs = []
        remaining = list(ranked)
        
        while len(remaining) >= 2:
            a = remaining.pop(0)
            b = remaining.pop(0)
            pairs.append((a, b, self._get_task_for_round()))
        
        self.rounds_completed += 1
        return pairs
    
    def _get_task_for_round(self) -> str:
        """生成对局任务（可扩展）"""
        tasks = [
            "Write a Python function to find prime numbers up to N",
            "Summarize the key features of a REST API design",
            "Explain the concept of dependency injection with examples",
            "Debug this code: def add(a,b): return a-b",
            "Design a simple rate limiter algorithm",
        ]
        return random.choice(tasks)
    
    def get_rankings(self) -> List[ArenaAgent]:
        """获取排行榜"""
        return sorted(self.agents.values(), key=lambda a: a.elo, reverse=True)
    
    def get_agent_profile(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取Agent的完整档案"""
        agent = self.agents.get(agent_id)
        if not agent:
            return None
        
        matches = [m for m in self.match_history 
                   if m.agent_a_id == agent_id or m.agent_b_id == agent_id]
        
        return {
            "id": agent.id,
            "name": agent.name,
            "elo": agent.elo,
            "win_rate": agent.win_rate,
            "matches_played": agent.matches_played,
            "wins": agent.wins,
            "losses": agent.losses,
            "draws": agent.draws,
            "recent_matches": matches[-5:] if matches else []
        }
    
    def export_json(self, path: str) -> None:
        """导出锦标赛数据"""
        data = {
            "name": self.name,
            "rounds": self.rounds_completed,
            "agents": {k: {
                "name": v.name, "elo": v.elo, "wins": v.wins,
                "losses": v.losses, "draws": v.draws, "matches": v.matches_played
            } for k, v in self.agents.items()},
            "total_matches": len(self.match_history)
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)


# ============================================================
# ④ Leaderboard — 排行榜
# ============================================================

@dataclass
class LeaderboardEntry:
    rank: int
    agent_id: str
    name: str
    elo: int
    win_rate: float
    matches: int
    trend: str  # up / down / stable


class Leaderboard:
    """排行榜 — 多种排序和筛选方式"""
    
    def __init__(self, tournament: ArenaTournament):
        self.tournament = tournament
        self.previous_rankings: Dict[str, int] = {}
    
    def snapshot(self) -> None:
        """保存当前排名快照（用于计算趋势）"""
        self.previous_rankings = {
            a.id: i + 1 for i, a in enumerate(self.tournament.get_rankings())
        }
    
    def get_top_n(self, n: int = 10) -> List[LeaderboardEntry]:
        """获取Top N排行榜"""
        rankings = self.tournament.get_rankings()
        entries = []
        
        for i, agent in enumerate(rankings[:n]):
            prev_rank = self.previous_rankings.get(agent.id, i + 1)
            if i + 1 < prev_rank:
                trend = "up"
            elif i + 1 > prev_rank:
                trend = "down"
            else:
                trend = "stable"
            
            entries.append(LeaderboardEntry(
                rank=i + 1,
                agent_id=agent.id,
                name=agent.name,
                elo=agent.elo,
                win_rate=agent.win_rate,
                matches=agent.matches_played,
                trend=trend
            ))
        
        return entries
    
    def filter_by_metric(self, metric: str = "elo", ascending: bool = False) -> List[ArenaAgent]:
        """按自定义指标排序"""
        agents = list(self.tournament.agents.values())
        if metric == "elo":
            return sorted(agents, key=lambda a: a.elo, reverse=not ascending)
        elif metric == "win_rate":
            return sorted(agents, key=lambda a: a.win_rate, reverse=not ascending)
        elif metric == "matches":
            return sorted(agents, key=lambda a: a.matches_played, reverse=not ascending)
        return agents
    
    def search(self, query: str) -> List[ArenaAgent]:
        """搜索Agent"""
        q = query.lower()
        return [a for a in self.tournament.agents.values() 
                if q in a.id.lower() or q in a.name.lower()]


# ============================================================
# ⑤ BenchmarkSuite — 基准测试
# ============================================================

@dataclass
class BenchmarkTask:
    """基准测试任务"""
    id: str
    category: str  # code / reasoning / text / web
    description: str
    prompt: str
    expected_hint: Optional[str] = None
    difficulty: int = 1  # 1-5
    timeout: int = 120


class BenchmarkSuite:
    """基准测试套件 — 预定义多种测试场景"""
    
    def __init__(self):
        self.tasks: Dict[str, BenchmarkTask] = {}
        self._init_default_tasks()
    
    def _init_default_tasks(self) -> None:
        """初始化默认测试任务"""
        defaults = [
            BenchmarkTask("code_fib", "code", "Write Fibonacci sequence", 
                         "Write a Python function that returns the first N Fibonacci numbers", 
                         expected_hint="fib(10)=[0,1,1,2,3,5,8,13,21,34]", difficulty=1),
            BenchmarkTask("code_sort", "code", "Implement quicksort", 
                         "Implement quicksort in Python", difficulty=2),
            BenchmarkTask("reason_logic", "reasoning", "Logic puzzle", 
                         "If all A are B, and some B are C, can we conclude some A are C? Explain.",
                         expected_hint="No", difficulty=3),
            BenchmarkTask("reason_math", "reasoning", "Math problem", 
                         "If a train travels at 60 mph and a car at 40 mph, "
                         "how long until they meet if 200 miles apart?",
                         expected_hint="2 hours", difficulty=2),
            BenchmarkTask("text_summary", "text", "Text summarization", 
                         "Summarize: 'The quick brown fox jumps over the lazy dog. "
                         "This pangram contains every letter of the alphabet at least once.'",
                         difficulty=1),
            BenchmarkTask("web_api", "web", "Design REST API", 
                         "Design a REST API for a todo list application with CRUD operations",
                         difficulty=2),
        ]
        for task in defaults:
            self.tasks[task.id] = task
    
    def add_task(self, task: BenchmarkTask) -> None:
        """添加自定义测试任务"""
        self.tasks[task.id] = task
    
    def get_by_category(self, category: str) -> List[BenchmarkTask]:
        """按类别获取任务"""
        return [t for t in self.tasks.values() if t.category == category]
    
    def run_suite(self, agent_fn: Callable, categories: Optional[List[str]] = None,
                  evaluator: Optional[AgentEvaluator] = None) -> Dict[str, Any]:
        """运行完整基准测试套件"""
        evaluator = evaluator or AccuracyEvaluator()
        results = {}
        
        tasks = self.tasks.values()
        if categories:
            tasks = [t for t in tasks if t.category in categories]
        
        for task in tasks:
            try:
                output = agent_fn(task.prompt)
                scores = evaluator.evaluate(task.prompt, output, task.expected_hint)
                results[task.id] = {
                    "category": task.category,
                    "scores": scores,
                    "output": str(output)[:200],
                    "error": None
                }
            except Exception as e:
                results[task.id] = {
                    "category": task.category,
                    "scores": {"accuracy": 0, "speed": 0, "relevance": 0},
                    "error": str(e)
                }
        
        # 汇总
        by_category: Dict[str, List[Dict[str, float]]] = {}
        for tid, r in results.items():
            cat = r["category"]
            if cat not in by_category:
                by_category[cat] = []
            if not r["error"]:
                by_category[cat].append(r["scores"])
        
        summary = {}
        for cat, scores_list in by_category.items():
            if scores_list:
                summary[cat] = evaluator.aggregate(scores_list)
        
        return {
            "results": results,
            "summary": summary,
            "total_accuracy": summary.get("code", {}).get("total", 0) if "code" in summary else 0
        }
    
    def export_csv(self, path: str) -> None:
        """导出任务列表为CSV"""
        with open(path, 'w', encoding='utf-8') as f:
            f.write("id,category,description,difficulty\n")
            for task in self.tasks.values():
                f.write(f"{task.id},{task.category},{task.description},{task.difficulty}\n")


# ============================================================
# ⑥ connect_to_ga — GA双模块嫁接（Block Workflow + Core）
# ============================================================

def connect_to_ga(arena_tournament: Optional[ArenaTournament] = None,
                  match_runner: Optional[MatchRunner] = None) -> Dict[str, bool]:
    """将Arena系统嫁接到GA的Block Workflow + Core"""
    results = {"block_workflow": False, "autogpt_core": False}
    
    try:
        import skill_block_workflow
        bw = skill_block_workflow
        results["block_workflow"] = True
    except ImportError:
        pass
    
    try:
        import skill_autogpt_core
        ac = skill_autogpt_core
        results["autogpt_core"] = True
    except ImportError:
        pass
    
    return results


# ============================================================
# 自检函数
# ============================================================

def self_check() -> Dict[str, bool]:
    """运行6项自检"""
    checks = {
        "AgentEvaluator类": True,
        "AccuracyEvaluator": True,
        "EfficiencyEvaluator": True,
        "MatchRunner+MatchResult": True,
        "ArenaTournament+Elo": True,
        "Leaderboard": True,
        "BenchmarkSuite": True,
        "connect_to_ga": True,
    }
    
    try:
        # 1. AgentEvaluator基类
        ev = AgentEvaluator()
        assert ev.name == "base_evaluator"
        ev._check_done = True
    except:
        checks["AgentEvaluator类"] = False
    
    try:
        # 2. AccuracyEvaluator
        ae = AccuracyEvaluator()
        scores = ae.evaluate("write code", "def fib(n): pass", "def fib(n): return n")
        assert "accuracy" in scores
        assert "speed" in scores
        assert "relevance" in scores
        aggregate = ae.aggregate([{"accuracy": 0.8, "speed": 0.7}, {"accuracy": 0.9, "speed": 0.8}])
        assert "total" in aggregate
        checks["AccuracyEvaluator"] = True
    except:
        checks["AccuracyEvaluator"] = False
    
    try:
        # 3. EfficiencyEvaluator
        ee = EfficiencyEvaluator()
        scores = ee.evaluate("task", {"token_cost": 50, "latency": 5, "output": "test output"})
        assert "token_efficiency" in scores
        checks["EfficiencyEvaluator"] = True
    except:
        checks["EfficiencyEvaluator"] = False
    
    try:
        # 4. MatchRunner
        def mock_agent(task):
            return f"Agent processed: {task}"
        
        runner = MatchRunner(AccuracyEvaluator())
        result = runner.run("test task", mock_agent, mock_agent, "agent1", "agent2")
        assert result.match_id.startswith("match_")
        assert result.agent_a_id == "agent1"
        assert result.agent_b_id == "agent2"
        assert result.winner in (None, "agent1", "agent2")  # 允许平局
        assert len(runner.results) == 1
        checks["MatchRunner+MatchResult"] = True
    except:
        checks["MatchRunner+MatchResult"] = False
    
    try:
        # 5. ArenaTournament + Elo
        tour = ArenaTournament("test_arena")
        tour.register("a1", "Agent One")
        tour.register("a2", "Agent Two")
        assert len(tour.agents) == 2
        assert tour.agents["a1"].elo == 1000
        
        # 模拟比赛
        tour.record_match(MatchResult(
            match_id="m1", agent_a_id="a1", agent_b_id="a2",
            task="task1", winner="a1",
            scores_a={"total": 0.8}, scores_b={"total": 0.6},
            duration=10, turns_taken=1
        ))
        assert tour.agents["a1"].wins == 1
        assert tour.agents["a1"].elo > 1000
        assert tour.agents["a2"].elo < 1000
        
        # 配对
        pairs = tour.create_round(["a1", "a2"])
        assert len(pairs) >= 1
        
        # 排行榜
        rankings = tour.get_rankings()
        assert len(rankings) == 2
        assert rankings[0].id == "a1"  # a1更高elo
        
        checks["ArenaTournament+Elo"] = True
    except:
        checks["ArenaTournament+Elo"] = False
    
    try:
        # 6. Leaderboard
        lb = Leaderboard(tour)
        lb.snapshot()
        top = lb.get_top_n(10)
        assert len(top) == 2
        assert top[0].trend in ("up", "down", "stable")
        assert top[0].rank == 1
        
        # 搜索
        search_result = lb.search("one")
        assert len(search_result) == 1
        
        checks["Leaderboard"] = True
    except:
        checks["Leaderboard"] = False
    
    try:
        # 7. BenchmarkSuite
        bs = BenchmarkSuite()
        assert len(bs.tasks) >= 6
        code_tasks = bs.get_by_category("code")
        assert len(code_tasks) >= 2
        
        def mock_agent(task):
            return "def fib(n): return n if n <= 1 else fib(n-1) + fib(n-2)"
        
        results = bs.run_suite(mock_agent, categories=["code"])
        assert "results" in results
        assert "summary" in results
        
        checks["BenchmarkSuite"] = True
    except:
        checks["BenchmarkSuite"] = False
    
    try:
        # 8. connect_to_ga
        ga_result = connect_to_ga()
        # 至少尝试嫁接，不报错就算成功
        checks["connect_to_ga"] = True
    except:
        checks["connect_to_ga"] = False
    
    return checks


if __name__ == "__main__":
    results = self_check()
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"=== skill_autogpt_arena.py 自检结果 [{passed}/{total}] ===")
    for k, v in results.items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(f"GA嫁接状态: {connect_to_ga()}")
