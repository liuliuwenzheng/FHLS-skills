"""
skill_constitution.py — GA执行者宪法（道法术器）

骨髓内化来源: cc-best (Claude Code最佳实践模板, 44⭐)
核心设计: CONSTATUTION式CLAUDE.md → 规则碎片 → 专业技能三层架构
          "道"=哲学原则, "法"=执行框架, "术"=操作规范, "器"=工具链

核心功能:
  1. CorePrinciples — 8条核心原则(P1-P8) + 5条自主决策原则(A1-A5)
  2. DecisionLevel — 决策分层(禁止/允许/自主/兜底)
  3. PrincipleRegistry — 原则注册与查询
  4. DecisionLogger — 决策记录(依据+置信度)
  5. ConstitutionManager — 宪法生成/校验/注入

用法:
    from memory.skill_constitution import constitution_manager
    cm = constitution_manager()
    cm.assert_principle("P1")    # 断言P1原则: 接口先查文档
    cm.decide("execute_api", confidence="high")  # 自主决策+记录
"""

import enum
import datetime
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════
# 道 (Dao) — 哲学原则层
# ═══════════════════════════════════════════════════

class PrincipleID(enum.Enum):
    """核心原则ID (P1-P8)"""
    P1 = "API Handling 接口处理"
    P2 = "Execution Boundaries 执行边界"
    P3 = "Business Understanding 业务理解"
    P4 = "Code Reuse 代码复用"
    P5 = "Quality Assurance 质量保证"
    P6 = "Architecture Compliance 架构规范"
    P7 = "Honest Communication 诚信沟通"
    P8 = "Change Impact 变更管理"

class AutoPrincipleID(enum.Enum):
    """自主决策原则 (A1-A5)"""
    A1 = "Context Inference 上下文推断"
    A2 = "Decision Recording 决策记录"
    A3 = "Downstream Correction 下游纠偏"
    A4 = "MVP Fallback 兜底方案"
    A5 = "Issue Classification 问题分类"


# ═══════════════════════════════════════════════════
# 法 (Fa) — 执行框架层
# ═══════════════════════════════════════════════════

class DecisionLevel(enum.IntEnum):
    """决策层级（值越大约束越强）"""
    FREE = 0           # 完全自主，无需记录
    INFORM = 1         # 可自主执行，但需记录决策
    CONFIRM = 2        # 需先确认再执行
    FORBID = 3         # 禁止执行

    @classmethod
    def from_name(cls, name: str) -> "DecisionLevel":
        mapping = {
            "free": cls.FREE, "inform": cls.INFORM,
            "confirm": cls.CONFIRM, "forbid": cls.FORBID,
        }
        return mapping.get(name.lower(), cls.CONFIRM)


# ═══════════════════════════════════════════════════
# 核心数据结构
# ═══════════════════════════════════════════════════

@dataclass
class Principle:
    """一条原则"""
    id: str               # e.g. "P1", "A3"
    name: str             # 名称
    level: DecisionLevel  # 决策层级
    rule: str             # 核心规则
    rationale: str        # 为什么重要
    examples: list = field(default_factory=list)  # 正反示例

    def assert_check(self) -> str:
        """返回断言失败时的提示文本"""
        return f"[宪法] ⚠️ 违反 {self.id}: {self.rule}"


@dataclass
class DecisionRecord:
    """一次决策记录"""
    principle_id: str       # 关联原则
    action: str             # 决策动作
    rationale: str          # 决策依据
    confidence: str         # high/medium/low
    timestamp: str = field(default_factory=lambda:
        datetime.datetime.now().isoformat(timespec='seconds'))


# ═══════════════════════════════════════════════════
# PrincipleRegistry — 原则注册与查询
# ═══════════════════════════════════════════════════

class PrincipleRegistry:
    """原则注册中心——"宪法"的正文"""

    def __init__(self):
        self._principles: dict[str, Principle] = {}
        self._init_defaults()

    def _init_defaults(self):
        """初始化8条核心原则 P1-P8"""
        defaults = [
            Principle("P1", "接口先查文档", DecisionLevel.CONFIRM,
                      "调用API前必须查阅文档，禁止猜测",
                      "避免因参数误用导致运行时错误",
                      examples=[
                          ("✅ 好", "先看SDK文档再调接口"),
                          ("❌ 坏", "凭记忆直接传参"),
                      ]),
            Principle("P2", "执行先明边界", DecisionLevel.CONFIRM,
                      "执行前必须明确输入输出边界",
                      "防止无限循环或资源溢出",
                      examples=[
                          ("✅ 好", "确认文件大小再读取"),
                          ("❌ 坏", "不设超时直接调API"),
                      ]),
            Principle("P3", "需求拒绝假设", DecisionLevel.CONFIRM,
                      "逻辑必须来源于明确需求，禁止假设",
                      "需求假设是Bug的头号来源",
                      examples=[
                          ("✅ 好", "问清格式要求再解析"),
                          ("❌ 坏", "'它应该能处理JSON'"),
                      ]),
            Principle("P4", "先查再建", DecisionLevel.INFORM,
                      "创建新模块前必须检查现有实现",
                      "最大化复用，最小化重复",
                      examples=[
                          ("✅ 好", "搜memory/找已有模块"),
                          ("❌ 坏", "直接pip install另一个版本"),
                      ]),
            Principle("P5", "可测才提交", DecisionLevel.CONFIRM,
                      "提交前必须具备可执行测试用例",
                      "无测试=不可靠的代码",
                      examples=[
                          ("✅ 好", "写自测函数"),
                          ("❌ 坏", '"这是个小改动不用测"'),
                      ]),
            Principle("P6", "架构不可违", DecisionLevel.FORBID,
                      "必须遵循现行架构规范，禁止跨层调用",
                      "架构违规导致系统腐化",
                      examples=[
                          ("✅ 好", "skill模块通过registry调用"),
                          ("❌ 坏", "直接import另一个skill的内部"),
                      ]),
            Principle("P7", "不懂就说", DecisionLevel.CONFIRM,
                      "信息不完整时必须说明，禁止假装理解",
                      "诚实是可靠的基础",
                      examples=[
                          ("✅ 好", '"这块不太确定，我查下文档"'),
                          ("❌ 坏", "沉默地给出错误回答"),
                      ]),
            Principle("P8", "改前先看影响", DecisionLevel.CONFIRM,
                      "修改前必须分析依赖影响，保留回滚路径",
                      "无计划的修改=灾难",
                      examples=[
                          ("✅ 好", "先grep调用处再改函数签名"),
                          ("❌ 坏", "改完发现10处编译错误"),
                      ]),
        ]
        for p in defaults:
            self.register(p)

        # A1-A5 自主决策原则
        auto_principles = [
            Principle("A1", "上下文推断", DecisionLevel.FREE,
                      "基于项目上下文推断，不中断询问用户",
                      "保持Agent工作流连续性"),
            Principle("A2", "决策记录", DecisionLevel.INFORM,
                      "记录决策依据和置信度(high/medium/low)",
                      "下游可追踪推理链条"),
            Principle("A3", "下游纠偏", DecisionLevel.FREE,
                      "下游Agent可纠正上游决策，形成闭环",
                      "容忍错误，但必须可修正"),
            Principle("A4", "兜底方案", DecisionLevel.INFORM,
                      "无依据时采用最小可行方案，标注TBD",
                      "不要卡住，用MVP推进"),
            Principle("A5", "问题分类", DecisionLevel.INFORM,
                      "区分'实现bug'和'需求假设错误'",
                      "不同问题不同修复策略"),
        ]
        for p in auto_principles:
            self.register(p)

    def register(self, principle: Principle):
        self._principles[principle.id] = principle

    def get(self, principle_id: str) -> Optional[Principle]:
        return self._principles.get(principle_id.upper())

    def list_by_level(self, level: DecisionLevel) -> list[Principle]:
        return [p for p in self._principles.values() if p.level == level]

    def list_all(self) -> list[Principle]:
        return list(self._principles.values())

    def assert_principle(self, principle_id: str) -> str:
        """断言检查，违反时返回警告文本"""
        p = self.get(principle_id)
        if p:
            return p.assert_check()
        return f"[宪法] 未知原则: {principle_id}"

    def count(self) -> int:
        return len(self._principles)


# ═══════════════════════════════════════════════════
# DecisionLogger — 决策记录
# ═══════════════════════════════════════════════════

class DecisionLogger:
    """决策日志——每步决策有据可查"""

    def __init__(self, max_records: int = 100):
        self._records: list[DecisionRecord] = []
        self._max = max_records

    def log(self, principle_id: str, action: str,
            rationale: str, confidence: str = "medium"):
        """记录一次决策"""
        record = DecisionRecord(
            principle_id=principle_id.upper(),
            action=action,
            rationale=rationale,
            confidence=confidence,
        )
        self._records.append(record)
        if len(self._records) > self._max:
            self._records.pop(0)
        return record

    def recent(self, n: int = 5) -> list[DecisionRecord]:
        return self._records[-n:]

    def by_confidence(self, level: str) -> list[DecisionRecord]:
        return [r for r in self._records if r.confidence == level]

    def summary(self) -> str:
        """生成决策摘要"""
        if not self._records:
            return "暂无决策记录"
        total = len(self._records)
        confs = {}
        for r in self._records:
            confs[r.confidence] = confs.get(r.confidence, 0) + 1
        lines = [
            f"📊 决策记录: {total}条",
            *[f"  {k}: {v}条" for k, v in confs.items()],
            "── 最近3条 ──",
            *[f"  [{r.timestamp}] {r.principle_id} | {r.action[:40]} | conf={r.confidence}"
              for r in self._records[-3:]],
        ]
        return "\n".join(lines)


# ═══════════════════════════════════════════════════
# ConstitutionManager — 宪法管理器
# ═══════════════════════════════════════════════════

class ConstitutionManager:
    """宪法管理器——整合原则注册+决策追踪+宪法生成"""

    def __init__(self):
        self.registry = PrincipleRegistry()
        self.logger = DecisionLogger()

    def assert_principle(self, principle_id: str) -> str:
        """断言原则，自动记录"""
        msg = self.registry.assert_principle(principle_id)
        self.logger.log(principle_id, f"assert_check: {principle_id}",
                        msg, "medium")
        return msg

    def decide(self, action: str, rationale: str,
               confidence: str = "medium") -> dict:
        """
        自主决策入口——记录决策+检查约束
        返回: {"allow": bool, "level": str, "principles": [...]}
        """
        # 检查所有原则
        violations = []
        for p in self.registry.list_all():
            if p.level >= DecisionLevel.FORBID and p.id in action.upper():
                violations.append(p.id)

        # 记录决策
        self.logger.log("A2", action, rationale, confidence)

        return {
            "allow": len(violations) == 0,
            "level": "free" if not violations else "forbidden",
            "violations": violations,
            "rationale": rationale,
            "confidence": confidence,
        }

    def generate_constitution(self, project_name: str = "GA",
                              add_date: bool = True) -> str:
        """生成可读的宪法文本（类似cc-best的CLAUDE.md）"""
        lines = [
            f"# {project_name} Constitution",
            f"",
            f"**Version**: 1.0.0" +
            (f" | **Ratified**: {datetime.date.today()}" if add_date else ""),
            f"",
            f"> 本文档是项目的'宪法'，定义不可违背的核心原则。",
            f"",
            f"## 道 — 元原则",
            f"",
            f"- **上下文为王** — 垃圾进垃圾出",
            f"- **先结构后代码** — 规划好框架再实现",
            f"- **如无必要勿增代码** — 奥卡姆剃刀",
            f"- **凡是AI能做的** — 就不要人工做",
            f"",
            f"## 法 — 核心原则 (P1-P8)",
            f"",
        ]
        for p in self.registry.list_all():
            if p.id.startswith("P"):
                level_name = p.level.name if hasattr(p.level, 'name') else str(p.level)
                lines.append(f"| {p.id:4s} | {p.name:20s} | {level_name:8s} | {p.rule} |")
        lines += [
            f"",
            f"## 术 — 自主决策原则 (A1-A5)",
            f"",
        ]
        for p in self.registry.list_all():
            if p.id.startswith("A"):
                lines.append(f"- **{p.id} {p.name}**: {p.rule}")
        lines += [
            f"",
            f"## 器 — 工具链",
            f"",
            f"- 原则注册中心: PrincipleRegistry ({self.registry.count()}条原则)",
            f"- 决策日志: DecisionLogger ({len(self.logger._records)}条记录)",
            f"- 决策层级: FREE<INFORM<CONFIRM<FORBID",
        ]
        return "\n".join(lines)

    def inject_to_prompt(self) -> str:
        """生成可注入Agent提示的宪法摘要（单行，<200tokens）
        供startup_selfcheck_sop在会话开始时注入"""
        principles = self.registry.list_all()
        p_rules = "; ".join(f"{p.id}:{p.rule[:30]}" for p in principles if p.id.startswith("P"))
        a_rules = "; ".join(f"{p.id}:{p.rule[:30]}" for p in principles if p.id.startswith("A"))
        return (
            f"[宪法注入] 13原则激活 | "
            f"核心(P1先查文档/P2明边界/P3拒假设/P4先查再建/"
            f"P5可测才交/P6架构不可违/P7不懂就说/P8改前看影响) | "
            f"自主(A1上下文推断/A2决策记录/A3下游纠偏/A4兜底/A5问题分类) | "
            f"层级:FORBID>CONFIRM>INFORM>FREE | "
            f"已记录{len(self.logger._records)}次决策"
        )

    def summary(self) -> str:
        """生成运行时状态摘要"""
        return (
            f"📜 GA宪法 v1.0\n"
            f"  原则总数: {self.registry.count()}条 (P1-P8核心 + A1-A5自主)\n"
            f"  决策层级: FREE={len(self.registry.list_by_level(DecisionLevel.FREE))} "
            f"INFORM={len(self.registry.list_by_level(DecisionLevel.INFORM))} "
            f"CONFIRM={len(self.registry.list_by_level(DecisionLevel.CONFIRM))} "
            f"FORBID={len(self.registry.list_by_level(DecisionLevel.FORBID))}\n"
            f"  决策记录: {len(self.logger._records)}条\n"
            f"{self.logger.summary()}"
        )


# ═══════════════════════════════════════════════════
# 单例工厂
# ═══════════════════════════════════════════════════

_constitution_instance: Optional[ConstitutionManager] = None

def constitution_manager() -> ConstitutionManager:
    """获取单例宪法管理器"""
    global _constitution_instance
    if _constitution_instance is None:
        _constitution_instance = ConstitutionManager()
    return _constitution_instance


# ═══════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════

def self_test() -> dict:
    """执行全部自检"""
    results = {}

    # 1. 初始化
    cm = constitution_manager()
    results["init"] = cm.registry.count() == 13  # 8P + 5A

    # 2. 原则查询
    p1 = cm.registry.get("P1")
    results["get_p1"] = p1 is not None and "API" in p1.rule

    # 3. 断言检查
    msg = cm.assert_principle("P1")
    results["assert_msg"] = "违反" in msg

    # 4. 决策记录
    dec = cm.decide("execute_api", "查阅文档后调用REST API",
                    confidence="high")
    results["decide_allow"] = dec["allow"] is True
    results["decide_level"] = dec["level"] == "free"

    # 5. 决策日志
    recent = cm.logger.recent(1)
    results["logger_recent"] = len(recent) == 1

    # 6. 宪法生成
    const_text = cm.generate_constitution("GA-Test")
    results["constitution_generate"] = "P1" in const_text and "A1" in const_text

    # 7. 层级分类
    free_list = cm.registry.list_by_level(DecisionLevel.FREE)
    results["free_count"] = len(free_list) >= 2  # A1, A3

    # 8. 汇总
    summary = cm.summary()
    results["summary_has_count"] = "13" in summary or "13" in summary

    all_pass = all(results.values())
    return {
        "pass": all_pass,
        "results": results,
        "details": {
            "principles": cm.registry.count(),
            "decisions": len(cm.logger._records),
            "constitution_len": len(const_text) if 'const_text' in dir() else 0,
        }
    }


if __name__ == "__main__":
    result = self_test()
    status = "✅ ALL PASS" if result["pass"] else "❌ FAILED"
    print(f"  [{status}] skill_constitution.py 自检")
    for k, v in result["results"].items():
        print(f"    {'✅' if v else '❌'} {k}")
    print(f"  详情: {result['details']}")
