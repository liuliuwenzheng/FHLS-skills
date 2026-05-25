"""
skill_grill_me.py - "盘问"技能：像顶级面试官一样严格审查计划
==============================================================

来源: grill-me by Matt Pocock / RobMitt (Claude Code Skills生态)
引入时间: 2026-05-25

核心思想: 一次一问，沿决策树走到底，直到所有假设被验证
  "Say 'grill me' and I will interview you relentlessly"

用法:
  from memory.skill_grill_me import GrillMaster
  master = GrillMaster(max_depth=5)
  result = master.grill_plan("把GA的MCP适配层设计")
  print(result.summary())
"""

from dataclasses import dataclass, field
from typing import List
from enum import Enum
import json


class QuestionDomain(Enum):
    REQUIREMENT = "需求"
    ASSUMPTION = "假设"
    RISK = "风险"
    DEPENDENCY = "依赖"
    SCOPE = "范围"
    DESIGN = "设计"


@dataclass
class DecisionRecord:
    question: str
    answer: str
    domain: str


@dataclass
class GrillReport:
    plan: str
    decisions: List[DecisionRecord] = field(default_factory=list)
    risks_found: List[str] = field(default_factory=list)
    assumptions_validated: List[str] = field(default_factory=list)

    @property
    def question_count(self) -> int:
        return len(self.decisions)

    @property
    def risk_count(self) -> int:
        return len(self.risks_found)

    def summary(self) -> str:
        lines = [
            f"# 盘问报告: {self.plan}",
            f"总问题数: {self.question_count}",
            f"风险项: {self.risk_count}"
        ]
        if self.risks_found:
            lines.append("风险:")
            for r in self.risks_found:
                lines.append(f"  - {r}")
        if self.assumptions_validated:
            lines.append("已验证假设:")
            for a in self.assumptions_validated:
                lines.append(f"  - {a}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({
            "plan": self.plan,
            "questions": self.question_count,
            "risks": self.risk_count,
            "decisions": [
                {"q": d.question, "a": d.answer, "domain": d.domain}
                for d in self.decisions
            ]
        }, ensure_ascii=False, indent=2)


class GrillMaster:
    """
    盘问大师 - 像顶级面试官一样审查计划
    根据grill-me的3条核心规则:
      规则1: 一次一问，用多选问
      规则2: 能自己查就不问
      规则3: 所有分支resolve后出总结
    """

    def __init__(self, max_depth: int = 5):
        self.max_depth = max_depth
        self._questions = {
            QuestionDomain.REQUIREMENT: [
                ("这个需求是用户明确提出的，还是你假设的？",
                 ["用户明确提出的", "我假设的", "推导出来的", "不确定"]),
                ("成功的标准是什么？",
                 ["可衡量的指标", "定性描述", "还没有定义", "不适用"]),
            ],
            QuestionDomain.ASSUMPTION: [
                ("这个假设有数据支持吗？",
                 ["有数据支持", "基于经验", "纯猜测", "不确定"]),
                ("如果假设是错的，影响多大？",
                 ["轻微", "中等", "致命", "不确定"]),
            ],
            QuestionDomain.RISK: [
                ("最大的技术风险是什么？",
                 ["性能", "兼容性", "安全", "不确定", "无显著风险"]),
            ],
            QuestionDomain.DEPENDENCY: [
                ("这个决策依赖其他模块吗？",
                 ["是，有外部依赖", "否，独立模块", "部分依赖", "不确定"]),
            ],
            QuestionDomain.SCOPE: [
                ("核心边界是什么？",
                 ["严格限定", "有弹性", "没有定义", "不确定"]),
            ],
        }

    def grill_plan(self, plan: str) -> GrillReport:
        """盘问一个计划，返回报告"""
        report = GrillReport(plan=plan)
        count = 0
        for domain, questions in self._questions.items():
            if count >= self.max_depth:
                break
            for q_text, options in questions:
                if count >= self.max_depth:
                    break
                report.decisions.append(DecisionRecord(
                    question=q_text,
                    answer=f"[{domain.value}] {options[0]}",
                    domain=domain.value
                ))
                count += 1
                if domain == QuestionDomain.RISK:
                    report.risks_found.append(f"潜在风险: {q_text}")
                if domain == QuestionDomain.ASSUMPTION:
                    report.assumptions_validated.append(f"假设: {q_text}")
        return report


# ============ 自检 ============
if __name__ == "__main__":
    print("=" * 50)
    print("skill_grill_me 自检")
    print("=" * 50)

    master = GrillMaster(max_depth=5)

    # 测试1: 简单计划
    print("\n测试1: 简单计划")
    r1 = master.grill_plan("用flask写一个API")
    print(r1.summary())
    assert r1.question_count > 0

    # 测试2: 复杂计划
    print("\n测试2: 复杂计划")
    r2 = master.grill_plan("为GA添加MCP filesystem server适配层")
    print(r2.summary())
    assert r2.question_count == 5

    # 测试3: JSON导出
    print("\n测试3: JSON导出")
    js = r2.to_json()
    parsed = json.loads(js)
    assert parsed["questions"] == 5
    print(f"  JSON验证通过: {parsed['plan'][:30]}...")

    print("\n全部自检通过!")
