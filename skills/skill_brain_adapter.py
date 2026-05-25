"""
skill_brain_adapter.py — Brain决策 → 技能编排 适配层 (≤80行)

桥接 skill_agent_brain（决策）和 skill_orchestrator（技能编排）。
每次 brain 做出 action 后，adapter 把它 enrich 成带技能上下文的
"增强决策"——让系统提示里能看到可用技能。

设计原则(Karpathy):
  1. 不侵入 brain 逻辑，只是装饰
  2. 零异常：所有 import/scan/call 失败返回原始 decision
  3. 单方向依赖：adapter → orchestrator，反向无依赖
"""

from typing import Optional

# ── 懒加载：只有被调用时才 import orchestrator ──
_orchestrator = None

def _get_orch():
    global _orchestrator
    if _orchestrator is None:
        try:
            from skill_orchestrator import SkillOrchestrator
            _orchestrator = SkillOrchestrator()
        except Exception:
            _orchestrator = False  # 标记失败，避免反复尝试
    return _orchestrator if _orchestrator else None


def enrich(decision: dict, session_context: Optional[dict] = None) -> dict:
    """
    给 brain decision 注入技能上下文。

    Args:
        decision: skill_agent_brain.decide() 的结果 dict
        session_context: 可选，当前会话上下文

    Returns:
        增强后的 decision dict，新增字段:
          - matched_skills: [str, ...]  匹配的技能名
          - skill_summary: str          简短技能描述
          - load_chain: [str, ...]      建议加载顺序
    失败时原样返回 decision（零侵入）
    """
    orch = _get_orch()
    if not orch:
        return decision

    # 构造查询：优先用 decision 的 target+rationale
    action = decision.get("action", "")
    target = decision.get("target", "")
    rationale = decision.get("rationale", "")
    request = f"{target} {rationale}".strip() or action

    # 额外配上 session_context 的 last_summary
    if session_context:
        last = session_context.get("last_summary", "")
        if last:
            request = f"{request} {last}"

    try:
        route = orch.route(request, top_n=3)
        decision["matched_skills"] = [s.name for s in route.get("matched_skills", [])]
        decision["skill_summary"] = route.get("summary", "")
        decision["load_chain"] = route.get("load_chain", [])
    except Exception:
        pass  # 零侵入，失败就当没 adapter

    return decision


def quick_skills(request: str) -> str:
    """
    快速查询某个请求匹配哪些技能，返回短文本。
    用于在 quick_prompt 中追加技能上下文。
    """
    orch = _get_orch()
    if not orch:
        return ""
    try:
        route = orch.route(request, top_n=2)
        skills = route.get("matched_skills", [])
        if not skills:
            return ""
        names = [s.name for s in skills]
        return f" | 📦 可用: {', '.join(names[:3])}"
    except Exception:
        return ""
