"""
skill_trading_agents.py — TradingAgents(TauricResearch/78.6k⭐) 骨髓内化

核心: 多Agent分层的辩论-决策框架
 - 分析师(4种): Fundamentals/Sentiment/News/Technical
 - 研究员(2种): Bull vs Bear 结构化辩论
 - 交易员: 综合分析报告做决策
 - 风控组(3种): Aggressive/Neutral/Conservative 辩论
 - 投资组合经理: 最终决策

与GA skill_multi_agent_dev_team的差异:
 - GA只有PM+Dev双Agent, 这里8种角色分层
 - 辩论机制(bull/bear, aggressive/conservative)多层级注入
 - 结构化输出(schemas.py + Pydantic)而非纯文本
 - LangGraph + checkpointer 实现可恢复工作流

可复用模式:
 1. MultiLayerDebatePattern — 多层级辩论决策
 2. StructuredOutputPattern — Pydantic schema结构化输出
 3. RoleDecompositionPattern — 模拟真实团队的角色分解
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


# ═══════════════════════════════════════════════════════
# 模块一: 角色分解模式
# ═══════════════════════════════════════════════════════

class AnalystType(Enum):
    """分析师类型 — 对应TradingAgents的4位分析师"""
    FUNDAMENTALS = "fundamentals"   # 基本面分析师
    SENTIMENT = "sentiment"         # 情绪分析师
    NEWS = "news"                   # 新闻分析师
    TECHNICAL = "technical"         # 技术分析师


class RoleType(Enum):
    """TradingAgents完整角色体系"""
    FUNDAMENTALS_ANALYST = "fundamentals_analyst"
    SENTIMENT_ANALYST = "sentiment_analyst"
    NEWS_ANALYST = "news_analyst"
    TECHNICAL_ANALYST = "technical_analyst"
    BULL_RESEARCHER = "bull_researcher"
    BEAR_RESEARCHER = "bear_researcher"
    TRADER = "trader"
    AGGRESSIVE_DEBATOR = "aggressive_debator"
    NEUTRAL_DEBATOR = "neutral_debator"
    CONSERVATIVE_DEBATOR = "conservative_debator"
    RESEARCH_MANAGER = "research_manager"
    PORTFOLIO_MANAGER = "portfolio_manager"


@dataclass
class RoleSpec:
    """角色规约 — TradingAgents的角色定义模式"""
    name: str
    objective: str                            # 目标陈述
    data_sources: List[str] = field(default_factory=list)  # 数据源
    output_format: str = "report"             # report / decision / debate
    debating_style: Optional[str] = None      # 辩论风格
    priority: int = 1                         # 执行优先级


def get_role_spec(role_type: RoleType) -> RoleSpec:
    """获取指定角色的规约"""
    specs = {
        RoleType.FUNDAMENTALS_ANALYST: RoleSpec(
            "基本面分析师",
            "评估公司财务和绩效指标，识别内在价值和潜在风险信号",
            ["财务报表", "资产负债表", "现金流", "利润表"],
            "report"
        ),
        RoleType.SENTIMENT_ANALYST: RoleSpec(
            "情绪分析师",
            "聚合新闻、社交媒体的情绪，判断短期市场情绪方向",
            ["新闻", "StockTwits", "Reddit"],
            "report"
        ),
        RoleType.NEWS_ANALYST: RoleSpec(
            "新闻分析师",
            "监控全球新闻和宏观经济指标，解读对市场条件的影响",
            ["全球新闻", "宏观指标"],
            "report"
        ),
        RoleType.TECHNICAL_ANALYST: RoleSpec(
            "技术分析师",
            "利用技术指标（MACD/RSI）检测交易模式并预测价格走势",
            ["价格数据", "交易量", "技术指标"],
            "report"
        ),
        RoleType.BULL_RESEARCHER: RoleSpec(
            "看涨研究员",
            "积极评估分析师团队提供的见解，构建看涨论点，突出潜在收益",
            priority=2,
            debating_style="bullish"
        ),
        RoleType.BEAR_RESEARCHER: RoleSpec(
            "看跌研究员",
            "批判性评估分析师见解，构建看跌论点，突出潜在风险",
            priority=2,
            debating_style="bearish"
        ),
        RoleType.TRADER: RoleSpec(
            "交易员Agent",
            "综合分析师和研究员的报告，做出知情的交易决策（时机和规模）",
            priority=3,
            output_format="decision"
        ),
        RoleType.AGGRESSIVE_DEBATOR: RoleSpec(
            "激进风控辩手",
            "优先追求高收益增长，承受较高风险，主动挑战保守观点",
            priority=4,
            debating_style="aggressive"
        ),
        RoleType.NEUTRAL_DEBATOR: RoleSpec(
            "中性风控辩手",
            "平衡风险与收益，综合各家观点给出中庸判断",
            priority=4,
            debating_style="neutral"
        ),
        RoleType.CONSERVATIVE_DEBATOR: RoleSpec(
            "保守风控辩手",
            "保护资产，最小化波动，确保稳定可靠的增长，挑战高风险元素",
            priority=4,
            debating_style="conservative"
        ),
        RoleType.RESEARCH_MANAGER: RoleSpec(
            "研究经理",
            "分析在研究员辩论后整合最终的研究报告",
            priority=5,
            output_format="report"
        ),
        RoleType.PORTFOLIO_MANAGER: RoleSpec(
            "投资组合经理",
            "评估市场波动性/流动性等风险因素，做出最终决策",
            priority=6,
            output_format="decision"
        ),
    }
    return specs.get(role_type)


# ═══════════════════════════════════════════════════════
# 模块二: 多层级辩论模式
# ═══════════════════════════════════════════════════════

@dataclass
class DebateRound:
    """一轮辩论"""
    speaker: str
    stance: str        # bullish/bearish/aggressive/neutral/conservative
    argument: str
    counter_to: Optional[str] = None  # 针对谁的论点


@dataclass
class MultiLayerDebate:
    """TradingAgents多层级辩论
    
    第一层: 分析师团队(4人)并行产出报告
    第二层: 研究员(bull vs bear)辩论投资方向
    第三层: 风控组(aggressive/neutral/conservative)辩论风险
    """
    layer1_analyst_reports: Dict[str, str] = field(default_factory=dict)
    layer2_researcher_debate: List[DebateRound] = field(default_factory=list)
    layer3_risk_debate: List[DebateRound] = field(default_factory=list)
    
    # 各辩手状态
    bull_history: str = ""
    bear_history: str = ""
    aggressive_history: str = ""
    neutral_history: str = ""
    conservative_history: str = ""
    
    trader_decision: str = ""
    research_manager_report: str = ""
    final_decision: str = ""


def create_debate_prompt(
    role: str,
    stance: str,
    reports: Dict[str, str],
    trader_decision: str = "",
    history: str = "",
    opposing_args: str = ""
) -> str:
    """创建辩论Prompt — 模拟TradingAgents的辩论模板"""
    prompt = f"作为{role}（{stance}派），你的核心目标是"
    if stance == "bullish":
        prompt += "突出潜在收益和增长机会。"
    elif stance == "bearish":
        prompt += "突出潜在风险和下行因素。"
    elif stance == "aggressive":
        prompt += "追求高收益增长，承受较高风险。"
    elif stance == "conservative":
        prompt += "保护资产，最小化波动，确保稳定增长。"
    else:  # neutral
        prompt += "平衡风险与收益，给出中庸判断。"
    
    prompt += f"\n\n分析报告:\n"
    for name, content in reports.items():
        prompt += f"\n{name}报告: {content[:200]}..."
    
    if trader_decision:
        prompt += f"\n\n交易员决策: {trader_decision}"
    if history:
        prompt += f"\n\n对话历史: {history}"
    if opposing_args:
        prompt += f"\n\n对手论点: {opposing_args}"
    
    return prompt


# ═══════════════════════════════════════════════════════
# 模块三: 结构化输出模式 (模拟TradingAgents schemas.py)
# ═══════════════════════════════════════════════════════

@dataclass
class StructuredDecision:
    """结构化决策输出 - 类比TradingAgents的Pydantic schema"""
    signal: str                          # buy / sell / hold
    confidence: int                      # 0-100
    reasoning: str                       # 决策理由
    risk_level: str = "medium"          # low / medium / high
    time_horizon: str = "short_term"    # short_term / medium_term / long_term
    key_factors: List[str] = field(default_factory=list)
    alternative_scenarios: List[str] = field(default_factory=list)


def structured_output_to_markdown(decision: StructuredDecision) -> str:
    """转换结构化决策为markdown — 模拟TradingAgents的render helper"""
    return f"""## 交易决策

| 维度 | 值 |
|------|-----|
| 信号 | **{decision.signal.upper()}** |
| 置信度 | {decision.confidence}/100 |
| 风险等级 | {decision.risk_level} |
| 时间跨度 | {decision.time_horizon} |

### 推理过程
{decision.reasoning}

### 关键因素
{chr(10).join(f"- {f}" for f in decision.key_factors)}

### 替代情景
{chr(10).join(f"- {s}" for s in decision.alternative_scenarios)}
"""


# ═══════════════════════════════════════════════════════
# 模块四: 工作流编排模式 (模拟TradingAgents graph/)
# ═══════════════════════════════════════════════════════

@dataclass
class WorkflowStep:
    """工作流步骤"""
    name: str
    roles: List[str]
    parallel: bool = False     # 是否并行执行
    depends_on: List[str] = field(default_factory=list)  # 依赖的步骤


TRADING_AGENTS_WORKFLOW = [
    WorkflowStep("analysis", ["fundamentals_analyst", "sentiment_analyst", 
                                "news_analyst", "technical_analyst"], parallel=True),
    WorkflowStep("researcher_debate", ["bull_researcher", "bear_researcher"],
                depends_on=["analysis"]),
    WorkflowStep("trading_decision", ["trader"],
                depends_on=["researcher_debate"]),
    WorkflowStep("risk_debate", ["aggressive_debator", "neutral_debator", 
                                 "conservative_debator"],
                parallel=True, depends_on=["trading_decision"]),
    WorkflowStep("portfolio_decision", ["portfolio_manager"],
                depends_on=["risk_debate"]),
]


def get_workflow_schedule(company: str, date: str) -> List[str]:
    """获取工作流步骤顺序（字符串形式）"""
    return [step.name for step in TRADING_AGENTS_WORKFLOW]


# ═══════════════════════════════════════════════════════
# 差距分析: 与GA对比
# ═══════════════════════════════════════════════════════

def get_trading_agents_gaps() -> Dict[str, Dict[str, Any]]:
    """返回GA与TradingAgents之间的差距"""
    return {
        "multi_layer_debate": {
            "priority": 4,
            "ga_current": "skill_multi_agent_dev_team: PM+Dev双Agent, 无辩论机制",
            "trading_agents": "3层辩论(分析师→研究员→风控)",
            "impact": "大幅提升决策质量，减少单一视角偏差"
        },
        "role_decomposition": {
            "priority": 3,
            "ga_current": "2种角色(PM/Dev)",
            "trading_agents": "12种角色(4分析师+2研究员+1交易员+3风控+1研究经理+1PM)",
            "impact": "专业化分工提升多Agent协作的深度"
        },
        "structured_output": {
            "priority": 2,
            "ga_current": "纯文本输出",
            "trading_agents": "Pydantic schema结构化输出 + render helper",
            "impact": "提高输出一致性，方便下游解析和验证"
        },
        "workflow_checkpoint": {
            "priority": 2,
            "ga_current": "无checkpoint机制",
            "trading_agents": "LangGraph + SqliteSaver checkpoint",
            "impact": "崩溃恢复，长任务可靠性大幅提升"
        },
        "memory_log_past_context": {
            "priority": 3,
            "ga_current": "有认知记忆无交易历史持久化",
            "trading_agents": "TradingMemoryLog跨交易日持久化",
            "impact": "实现跨会话知识积累"
        },
    }


def describe() -> str:
    """Describe this skill"""
    return (
        "skill_trading_agents: TradingAgents(TauricResearch/78.6k⭐) 骨髓内化模块\n"
        "- RoleDecompositionPattern: 12种Agent角色定义\n"
        "- MultiLayerDebatePattern: 3层辩论机制(分析师→研究员→风控)\n"
        "- StructuredOutputPattern: Pydantic schema结构化决策\n"
        "- WorkflowPattern: 并行/串行工作流编排\n"
        "- get_trading_agents_gaps(): 返回5个GA差距\n"
        "→ 骨髓原则: 骨架优先(12角色体系)→用自己的话重建(辩论Prompt模式)→GA可执行→自检通过"
    )


# ═══════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("📊 TradingAgents骨髓内化模块自检")
    print("=" * 60)
    
    # 1. 角色规约
    for rt in RoleType:
        spec = get_role_spec(rt)
        assert spec is not None, f"{rt.value} 缺失规约"
    print(f"✅ RoleDecompositionPattern: {len(RoleType)}种角色已定义")
    
    # 2. 多层级辩论
    debate = MultiLayerDebate()
    debate.layer1_analyst_reports["fundamentals"] = "公司营收增长15%"
    debate.layer2_researcher_debate.append(
        DebateRound("bull", "bullish", "增长趋势强劲，建议买入")
    )
    debate.layer3_risk_debate.append(
        DebateRound("conservative", "conservative", "但负债率上升，需谨慎")
    )
    assert len(debate.layer2_researcher_debate) == 1
    assert len(debate.layer3_risk_debate) == 1
    print(f"✅ MultiLayerDebatePattern: 3层辩论结构可用")
    
    # 3. 辩论Prompt
    prompt = create_debate_prompt("看涨研究员", "bullish", 
                                   {"技术": "MACD金叉"},
                                   trader_decision="买入1000股",
                                   opposing_args="基本面恶化")
    assert "bullish" in prompt and "保守" not in prompt
    print(f"✅ MultiLayerDebatePattern.create_debate_prompt: Prompt生成成功 ({len(prompt)}字符)")
    
    # 4. 结构化输出
    decision = StructuredDecision(
        signal="buy", confidence=75, reasoning="综合多家分析",
        risk_level="medium", time_horizon="short_term",
        key_factors=["技术面看涨", "情绪指标改善"],
        alternative_scenarios=["若跌破支撑则止损"]
    )
    md = structured_output_to_markdown(decision)
    assert "BUY" in md and "75" in md
    print(f"✅ StructuredOutputPattern: 结构化决策生成成功")
    
    # 5. 工作流编排
    schedule = get_workflow_schedule("AAPL", "2026-05-23")
    assert len(schedule) == 5
    assert schedule[0] == "analysis" and schedule[-1] == "portfolio_decision"
    print(f"✅ WorkflowPattern: {len(schedule)}步工作流编排")
    
    # 6. 差距分析
    gaps = get_trading_agents_gaps()
    assert len(gaps) == 5
    print(f"✅ get_trading_agents_gaps: {len(gaps)}个差距识别")
    for name, info in gaps.items():
        print(f"   - {name}: 优先级{info['priority']}/5")
    
    print("\n✅ 全部自检通过 (5个模块)")
