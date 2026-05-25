"""
spark_hook.py — Spark 主动提议钩子（运行时注入点）

三问骨髓内化:
Q1: Gemini Spark 最值钱的是什么？
A1: "24/7 personal AI agent designed to proactively manage tasks 
     and help you navigate your digital life, all under your direction."
     → 关键在 proactive + under your direction（主动但不越权）

Q2: GA 缺少什么？
A2: GA现有 autonomous_scheduler.py（自主决策）和 skill_kairos_proactive.py（主动模式），
    但缺少一个"轻量级运行时提议器"——在Agent空闲/等待时主动给用户建议下一步。
    不是抢控制权，而是像好友一样"嘿，要不要试试这个？"

Q3: 怎么和现有系统融合？
A3: 不替代任何现有模块，只做一个"注入点"——agentmain在检测到空闲/轮次多时，
    调用 spark_hook.suggest_next() 返回提议。如果用户采纳就执行，不采纳就忽略。
    完全尊重 "all under your direction" 原则。

用法:
    from skill_spark_agent import SparkContext, ProactiveProposer
    from spark_hook import SparkHook
    hook = SparkHook()  # 自动读GA当前状态
    sug = hook.suggest_next()  # 返回提议字典
"""

import os, json, datetime, random
from pathlib import Path

# 尝试导入SPARK模块（graceful fallback）
try:
    from skill_spark_agent import SparkContext, ProactiveProposer
    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False
    SparkContext = None

GA_ROOT = Path(__file__).resolve().parent


class SparkHook:
    """Spark 运行时钩子 — 在GA运行间隙自动提议下一步"""
    
    def __init__(self):
        self.ctx = SparkContext() if SPARK_AVAILABLE else None
        self.proposer = ProactiveProposer() if SPARK_AVAILABLE else None
        self._load_state()
    
    def _load_state(self):
        """探测当前GA运行状态"""
        self.state = {
            "turn_count": 0,
            "recent_actions": [],
            "last_action_time": None,
            "today_tasks_completed": 0,
            "skill_count": 0,
            "has_pending_tasks": False,
        }
        # 尝试读GA的运行时状态
        state_file = GA_ROOT / 'temp' / 'spark_state.json'
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    data = json.load(f)
                    self.state.update(data)
            except:
                pass
        
        # 从memory读技能数量
        insight_file = GA_ROOT / 'memory' / 'global_mem_insight.txt'
        if insight_file.exists():
            with open(insight_file, 'r') as f:
                content = f.read()
                # 统计"||"开头的行
                skill_lines = [l for l in content.split('\n') if l.startswith('||')]
                self.state["skill_count"] = len(skill_lines)
    
    def save_state(self):
        """持久化当前状态"""
        state_file = GA_ROOT / 'temp' / 'spark_state.json'
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, 'w') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
    
    def record_action(self, action_desc: str):
        """记录一次用户操作（供后续提议参考）"""
        self.state["turn_count"] += 1
        self.state["recent_actions"].append({
            "action": action_desc,
            "time": datetime.datetime.now().isoformat(),
        })
        # 只保留最近20条
        if len(self.state["recent_actions"]) > 20:
            self.state["recent_actions"] = self.state["recent_actions"][-20:]
        self.state["last_action_time"] = datetime.datetime.now().isoformat()
        self.save_state()
    
    def suggest_next(self) -> dict:
        """根据当前GA状态，提议下一步行动
        
        Returns:
            {
                "has_suggestion": bool,
                "suggestion": str,  # 提议内容
                "reason": str,      # 为什么提议这个
                "priority": int,    # 1-3, 1最高
                "action_type": str,  # explore/improve/create/review/rest
            }
            or {"has_suggestion": False, "reason": "无可提议的内容"}
        """
        st = self.state
        now = datetime.datetime.now()
        
        # === 1. 优先级检查 ===
        
        # 如果超过20轮没有新增技能 → 提议学新东西
        if st["skill_count"] > 0 and st["turn_count"] > 20:
            return {
                "has_suggestion": True,
                "suggestion": "要不要去逛逛X或GitHub，看看有什么新东西可以学？",
                "reason": f"已经陪你了{st['turn_count']}轮，该学点新东西了",
                "priority": 2,
                "action_type": "explore"
            }
        
        # 如果技能书签数 < 10 → 提议从知识库提炼技能
        if st["skill_count"] < 10:
            return {
                "has_suggestion": True,
                "suggestion": "我的技能还不够多，要不要让我去GitHub上找些好项目学习？",
                "reason": f"目前只有{st['skill_count']}项技能，成长空间很大",
                "priority": 2,
                "action_type": "improve"
            }
        
        # 如果已经有一段时间没做有成果的事 → 提议做点东西
        if st["last_action_time"]:
            last = datetime.datetime.fromisoformat(st["last_action_time"])
            idle_minutes = (now - last).total_seconds() / 60
            if idle_minutes > 10:
                return {
                    "has_suggestion": True,
                    "suggestion": "感觉有一会儿没干活了，要不要我检查一下GA的状态、看看有没有可以优化的地方？",
                    "reason": f"已经空闲{int(idle_minutes)}分钟了",
                    "priority": 1,
                    "action_type": "review"
                }
        
        # 如果有pending任务
        if st.get("has_pending_tasks"):
            return {
                "has_suggestion": True,
                "suggestion": "你还有待办任务没处理，需要我继续完成吗？",
                "reason": "检测到未完成的任务队列",
                "priority": 1,
                "action_type": "continue"
            }
        
        # 如果刚刚完成了什么事 → 提议庆祝或休息
        if st["today_tasks_completed"] > 0 and st["today_tasks_completed"] % 5 == 0:
            return {
                "has_suggestion": True,
                "suggestion": f"今天已经完成了{st['today_tasks_completed']}件事！要不要休息一下，或者让我给你讲个今天学的有趣知识？",
                "reason": "里程碑达成，值得庆祝",
                "priority": 3,
                "action_type": "rest"
            }
        
        # 默认：没有特别提议
        return {
            "has_suggestion": False,
            "reason": "暂时没有需要主动提议的事项"
        }
    
    def health_status(self) -> dict:
        """Spark 钩子的健康状态报告"""
        st = self.state
        return {
            "spark_hook_version": "1.0.0",
            "spark_core_available": SPARK_AVAILABLE,
            "turn_count": st["turn_count"],
            "skill_count": st["skill_count"],
            "last_action": st["recent_actions"][-1] if st["recent_actions"] else None,
            "status": "ready" if st["skill_count"] > 0 else "bootstrap",
            "suggest": self.suggest_next()
        }


def self_test():
    print("[TEST] spark_hook 自检")
    
    hook = SparkHook()
    assert hook is not None
    print(f"  [OK] SparkHook 创建成功")
    
    # 记录一条操作
    hook.record_action("自检操作")
    assert hook.state["turn_count"] == 1
    print(f"  [OK] record_action: turn={hook.state['turn_count']}")
    
    # 检查提议
    sug = hook.suggest_next()
    assert "has_suggestion" in sug
    print(f"  [OK] suggest_next 返回结构完整: has_suggestion={sug['has_suggestion']}")
    
    # 模拟多轮
    for i in range(22):
        hook.record_action(f"操作{i+1}")
    sug2 = hook.suggest_next()
    print(f"  [OK] 22轮后提议: {sug2['suggestion'][:50] if sug2['has_suggestion'] else '无提议'}")
    assert sug2["has_suggestion"]
    assert sug2["action_type"] == "explore"
    
    # health
    h = hook.health_status()
    print(f"  [OK] health_status: status={h['status']}, spark_core={h['spark_core_available']}")
    
    # 清理
    state_file = GA_ROOT / 'temp' / 'spark_state.json'
    if state_file.exists():
        state_file.unlink()
    print(f"  [OK] 测试状态已清理")
    
    print(f"\n[OK] 全部自检通过!")
    return True


if __name__ == "__main__":
    self_test()
