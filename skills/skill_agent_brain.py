"""
skill_agent_brain.py — GA自主决策大脑

核心功能: 
  1. 维护一个"决策树"状态机
  2. 每轮根据[当前上下文, 刚刚做了什么, 记忆状态]决定下一件
  3. 可设定长期目标（不依赖用户指令）
  4. 内置"反思"信号——不会一直做同样的事

不依赖ga.py——即便在纯CLI中也可运行。
返回结构化action供消费方自由解析。

设计原则(Karpathy):
  - 单文件, 200行
  - 可序列化状态（跨会话恢复）
  - 不猜, 不编造, 用真实数据做决定
"""

import json, os, random, re
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass

GA_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = GA_ROOT / "temp" / "agent_brain_state.json"
L1_PATH = GA_ROOT / "memory" / "global_mem_insight.txt"

# ── 长期目标（用户给过我的指令沉淀） ──
LONG_TERM_GOALS = [
    "把GA打造成真正的自主Agent——不依赖人工指令也能自我进化",
    "骨髓内化所有学习过的技能为可import模块",
    "建立完整的测试覆盖（tests/）",
    "巩固安全链（P3层真正接入运行时）",
    "让GA能自我反省并调整策略（闭环学习）",
]

# ── 行动空间 ──
ACTIONS = {
    "explore": "打开浏览器学一个新项目/技能",
    "create": "编写一个新模块/工具",
    "improve": "改造现有代码，缩小已知缺口",
    "reflect": "暂停行动，检查方向",
    "build_test": "为已有模块编写测试",
    "connect": "把两个分离的模块连接起来",
    "review": "复习已学技能/检查记忆",
    "github": "push代码到GitHub备份",
}

# ── 动态已知缺口（运行时从L1扫描，non-gap缓存于completed_tasks） ──
def _scan_gaps_from_l1() -> list:
    """
    扫描L1，动态发现真正的缺口：
    - 只有L1索引无L3文件的 → 这是技能空缺
    - 已掌握但未实装的 → 从runtime视角发现断层
    返回 [(gap_name, desc), ...]
    """
    gaps = []
    try:
        if not L1_PATH.exists():
            return _get_fallback_gaps()
        l1 = L1_PATH.read_text(encoding='utf-8', errors='replace')
        # 扫描所有skill_/ga_引用
        refs = set(re.findall(r'(skill_\w+|ga_\w+)', l1))
        memory_dir = GA_ROOT / "memory"
        for r in sorted(refs):
            name_clean = r.replace('.py', '')
            # 别名映射：某些L1引用名与文件名不一致
            alias_map = {
                "skill_ga_self_eval": "ga_self_eval",
            }
            aliases = [name_clean]
            if name_clean in alias_map:
                aliases.append(alias_map[name_clean])
            candidates = []
            for a in aliases:
                candidates.extend([
                    memory_dir / f"{a}.py",
                    memory_dir / f"{a}.md",
                ])
            candidates.append(memory_dir / r / "__init__.py")
            has_file = any(c.exists() for c in candidates)
            if not has_file:
                gaps.append((f"技能空缺:{r}", f"L1有引用但memory/下无对应L3文件，需骨髓内化"))
        # 固定缺口（工程侧）
        gap_templates = [
            ("测试覆盖", "tests/目录需加固，核心模块单测覆盖率低"),
            ("安全层接入", "P3安全层代码写好但主循环没接"),
            ("跨会话记忆检索", "session_memory_saver只有feed_turn无cross-session检索"),
            ("技能复用链路", f"{len(refs)}+技能但运行时只注入经验性调用，非注册式"),
        ]
        gaps.extend(gap_templates)
        return gaps
    except:
        return _get_fallback_gaps()

def _get_fallback_gaps():
    return [
        ("技能内部核查", "未能读取L1，基于默认缺口决策"),
        ("测试覆盖", "tests/目录为空或很少"),
        ("安全层接入", "P3安全层代码写好但主循环没接"),
        ("自主决策深度", "当前仍依赖prompt工程而非代码级决策"),
    ]

KNOWN_GAPS = _scan_gaps_from_l1()

@dataclass
class BrainState:
    turn: int = 0
    current_mode: str = "explore"
    streak: int = 0  # 同一个action连续次数
    last_action: str = "none"
    last_result: str = "ok"
    completed_tasks: list = None
    active_goal_index: int = 0
    
    def __post_init__(self):
        if self.completed_tasks is None:
            self.completed_tasks = []


def _load_state() -> BrainState:
    try:
        if STATE_PATH.exists():
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return BrainState(**data)
    except:
        pass
    return BrainState()


def _save_state(state: BrainState):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump({
            "turn": state.turn,
            "current_mode": state.current_mode,
            "streak": state.streak,
            "last_action": state.last_action,
            "last_result": state.last_result,
            "completed_tasks": state.completed_tasks,
            "active_goal_index": state.active_goal_index,
        }, f, ensure_ascii=False, indent=2)


def decide(session_context: dict = None) -> dict:
    """
    核心决策函数
    
    Args:
        session_context: {
            "turn": int,
            "last_tool": str,
            "last_summary": str,
            "available_tools": [str],
        }
    
    Returns:
        {
            "action": str,  # ACTIONS的key
            "target": str,
            "rationale": str,
            "goal": str,
            "priority": int 1-5
        }
    """
    state = _load_state()
    state.turn += 1
    
    # ── 信号1: 连续做同一件事太久 → 切换 ──
    if state.streak >= 5:
        state.current_mode = "reflect"
        state.streak = 0
        result = {
            "action": "reflect",
            "target": "self",
            "rationale": f"连续{state.streak}轮同一模式，主动切换防固化",
            "goal": LONG_TERM_GOALS[state.active_goal_index],
            "priority": 5
        }
        _save_state(state)
        return result
    
    # ── 信号2: 如果上次结果有错误 → 优先修复 ──
    if session_context:
        last = session_context.get("last_summary", "")
        if any(w in last.lower() for w in ["error", "fail", "exception", "traceback", "❌"]):
            state.streak = 0
            state.current_mode = "improve"
            result = {
                "action": "improve",
                "target": session_context.get("last_tool", "unknown"),
                "rationale": f"上次执行异常，优先修复",
                "goal": LONG_TERM_GOALS[state.active_goal_index],
                "priority": 5
            }
            _save_state(state)
            return result
    
    # ── 信号3: 周期性自检 ──
    if state.turn % 5 == 0:
        state.current_mode = "reflect"
        result = {
            "action": "reflect",
            "target": "self",
            "rationale": "5轮周期性自检，确保方向正确",
            "goal": LONG_TERM_GOALS[state.active_goal_index],
            "priority": 3
        }
        _save_state(state)
        return result
    
    # ── 信号4: 动态扫描gap，选一个还没解决的 ──
    fresh_gaps = _scan_gaps_from_l1()
    # 过滤已知"假缺口"（扫描逻辑找不到文件但代码实体完好）
    _known_fake = {"ga_genetic_poc", "genetic_p9_inject", "genetic_llm_evaluator",
                    "ga_autonomous_engine", "ga_lmstudio_bridge", "skill_autonomous_scheduler"}
    unresolved = [(name, desc) for name, desc in fresh_gaps
                  if name.replace("技能空缺:", "") not in _known_fake
                  and name not in (state.completed_tasks or [])]
    if unresolved and random.random() < 0.3:
        name, desc = unresolved[0]
        state.completed_tasks = state.completed_tasks or []
        if name not in state.completed_tasks:
            state.completed_tasks.append(name)
        state.current_mode = "improve"
        result = {
            "action": "improve",
            "target": name,
            "rationale": desc,
            "goal": LONG_TERM_GOALS[state.active_goal_index],
            "priority": 4
        }
        _save_state(state)
        return result
    
    # ── 默认: 轮流探索和创造 ──
    modes = ["explore", "create", "improve"]
    idx = state.turn % len(modes)
    state.current_mode = modes[idx]
    state.streak += 1
    
    actions_for_mode = {
        "explore": ("explore", "GitHub搜索高星项目做骨髓内化"),
        "create": ("create", "编写新模块填补GA功能空白"),
        "improve": ("improve", "改造现有代码缩小已知缺口"),
    }
    action, rationale = actions_for_mode[state.current_mode]
    
    result = {
        "action": action,
        "target": state.current_mode,
        "rationale": rationale,
        "goal": LONG_TERM_GOALS[state.active_goal_index],
        "priority": 3
    }
    
    if session_context:
        result["turn"] = session_context.get("turn", state.turn)
    
    _save_state(state)
    return result


def quick_prompt(session_context: dict = None) -> str:
    """生成简短的自检提示文本，可追加到Agent的next_prompt中"""
    decision = decide(session_context)
    now = datetime.now().strftime("%H:%M")

    # 技能注入：让brain知道当前可用技能
    try:
        from memory.skill_brain_adapter import enrich
        decision = enrich(decision, session_context)
    except Exception:
        pass

    base = (
        f"\n[🧠 {now} Agent Brain] "
        f"行动: {decision['action'].upper()} → {decision['target']} "
        f"(优先级{decision['priority']}/5) "
        f"| {decision['rationale']}"
    )

    # 追加技能上下文
    skills = decision.get("matched_skills", [])
    if skills:
        base += f"\n[📦 可用技能] {', '.join(skills[:4])}"
        chain = decision.get("load_chain", [])
        if chain:
            base += f"\n[🔗 加载链] {' → '.join(chain[:3])}"

    return base


def mark_done(task_name: str):
    """标记一个缺口为已完成"""
    state = _load_state()
    if state.completed_tasks is None:
        state.completed_tasks = []
    if task_name not in state.completed_tasks:
        state.completed_tasks.append(task_name)
    _save_state(state)


if __name__ == "__main__":
    # 测试
    for i in range(3):
        decision = decide({"turn": i, "last_tool": "code_run", "last_summary": "ok"})
        print(f"[{i}] {decision['action']:>8} → {decision['target']:<20} | {decision['rationale']}")
