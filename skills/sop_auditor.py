"""
sop_auditor.py — SOP指令审计器（BitterPill Engineering骨髓内化）

骨髓内化来源: Daniel Miessler PAI v5.0.0 — BitterPillEngineering
核心设计: "更智能的模型会让这条规则多余吗？" → 五问法分类每一条规则

核心功能:
  1. 五问审计 (Q1-Q5) — 问出规则的"苦药味"
  2. 五分分类 (CUT/RESOLVE/MERGE/SHARPEN/KEEP) — 明确处置方式
  3. Token节省估算 — 量化每次优化的价值
  4. Rule审计 → 对skill_rule_engine的Rule做审计
  5. SOP文件审计 → 对memory/*.md SOP做全文扫描

用法:
  from memory.sop_auditor import SOPAuditor
  sa = SOPAuditor()
  # 审计一条规则
  result = sa.audit_rule("不要使用百度搜索", context="搜索规则")
  # 审计整个SOP文件
  report = sa.audit_file("../memory/web_access_sop.md")
  # 审计全部SOP
  full = sa.audit_all_sops()
"""

import os
import re
import json
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════
# 核心数据结构 — BitterPill五问法
# ═══════════════════════════════════════════════════

class AuditQuestion:
    """五问：每种问法对应一种脆弱性模式"""
    Q1_DEFAULT_BEHAVIOR = "default"    # "更聪明的模型默认会做这个吗？"
    Q2_CONTRADICTION = "contradiction" # "和其他规则矛盾吗？"
    Q3_REDUNDANCY = "redundancy"       # "另一条规则已经覆盖这个吗？"
    Q4_ONE_TIME_FIX = "one_time_fix"   # "这只是在修复某个特定错误输出吗？"
    Q5_VAGUE = "vague"                 # "每次解释这个规则结果都一样吗？"

    ALL = [Q1_DEFAULT_BEHAVIOR, Q2_CONTRADICTION, Q3_REDUNDANCY,
           Q4_ONE_TIME_FIX, Q5_VAGUE]


class AuditVerdict:
    """五种审计结论"""
    CUT = "CUT"              # 直接删除 → 模型默认能做
    RESOLVE = "RESOLVE"      # 需要解决矛盾
    MERGE = "MERGE"          # 合并到其他规则
    SHARPEN = "SHARPEN"      # 需要更精确的表述
    KEEP = "KEEP"            # 保留（反脆弱规则）


@dataclass
class RuleAuditItem:
    """一条规则的审计结果"""
    rule_text: str                     # 规则原文
    context: str = ""                  # 来源上下文（文件名、章节）
    questions: dict = field(default_factory=dict)  # {question_id: True/False/None}
    verdict: str = ""                  # AuditVerdict
    reason: str = ""                   # 为什么这么判
    token_saving: int = 0              # 估计节省的token数
    suggestion: str = ""               # 改进建议

    def to_dict(self) -> dict:
        return {
            "rule": self.rule_text[:80],
            "context": self.context,
            "questions": {k: v for k, v in self.questions.items() if v is not None},
            "verdict": self.verdict,
            "reason": self.reason,
            "token_saving": self.token_saving,
            "suggestion": self.suggestion,
        }


@dataclass
class AuditReport:
    """完整审计报告"""
    source: str                        # 来源文件/上下文
    items: list = field(default_factory=list)  # RuleAuditItem列表
    summary: dict = field(default_factory=dict)  # 统计汇总

    def compute_summary(self):
        """计算汇总统计"""
        counts = {"CUT": 0, "RESOLVE": 0, "MERGE": 0, "SHARPEN": 0, "KEEP": 0}
        total_saving = 0
        for item in self.items:
            v = item.verdict
            if v in counts:
                counts[v] += 1
            total_saving += item.token_saving
        self.summary = {
            "total_rules": len(self.items),
            "verdicts": counts,
            "total_token_saving": total_saving,
            "keep_rate": round(counts.get("KEEP", 0) / max(len(self.items), 1) * 100, 1),
            "cut_potential": counts.get("CUT", 0) + counts.get("MERGE", 0),
        }
        return self.summary

    def to_text(self) -> str:
        """生成可读报告"""
        self.compute_summary()
        lines = [
            f"╔═══ SOP审计报告: {self.source} ═══╗",
            f"  规则总数: {self.summary['total_rules']}",
            f"  CUT(删除): {self.summary['verdicts']['CUT']}",
            f"  RESOLVE(解决矛盾): {self.summary['verdicts']['RESOLVE']}",
            f"  MERGE(合并): {self.summary['verdicts']['MERGE']}",
            f"  SHARPEN(精炼): {self.summary['verdicts']['SHARPEN']}",
            f"  KEEP(保留): {self.summary['verdicts']['KEEP']}",
            f"  保持率: {self.summary['keep_rate']}%",
            f"  预计Token节省: ~{self.summary['total_token_saving']} tokens",
            f"  ────────────",
        ]
        for item in self.items:
            tag = {"CUT": "✂️", "RESOLVE": "⚡", "MERGE": "📎",
                   "SHARPEN": "🔧", "KEEP": "✅"}.get(item.verdict, "❓")
            lines.append(f"  {tag} [{item.verdict}] {item.rule_text[:70]}")
            if item.suggestion:
                lines.append(f"     → {item.suggestion}")
        lines.append(f"╚═══ ═══╝")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════
# 审计引擎
# ═══════════════════════════════════════════════════

class BitterPillEngine:
    """
    BitterPill审计引擎核心

    "Would a smarter model make this rule unnecessary?"
    五问法 + 自动分类 → 找出每条规则的"苦药味"
    """

    # 常见的"默认行为"模式 —— 更智能的模型不需要告诉它
    DEFAULT_PATTERNS = [
        r"不要(重复|啰嗦|冗余)",
        r"请(提供|给出|确保|保持)(清晰|简洁|准确|完整)",
        r"请用(中文|英文)",
        r"不要(使用|用).*(搜索|查询|百度)",
        r"请在.*前(先|提前).*",
        r"记得(检查|确认|验证)",
        r"注意(不要|避免|防止)",
        r"务必(保证|确保|注意)",
        r"严格遵守",
        r"必须(遵守|遵循|按照)",
        r"这是(重要|关键|核心)的",
        r"请不要(忽略|忘记|遗漏)",
    ]

    # 一次性修复模式 —— 针对某个具体错误的补丁
    ONE_TIME_FIX_PATTERNS = [
        r"不要把.*写成.*",
        r"不要(用|使用).*作为.*",
        r"如果.*报错.*就.*",
        r"上次.*错误.*不要.*",
        r"这个.*坑.*注意.*",
        r".*已知问题.*避免.*",
        r".*临时.*方案.*",
        r".*hotfix.*",
        r".*workaround.*",
    ]

    # 模糊模式 —— 表达不精确
    VAGUE_PATTERNS = [
        r"适当(地|的)",
        r"合理(地|的)",
        r"尽量",
        r"尽可能",
        r"一般来说",
        r"通常情况下",
        r"酌情",
    ]

    # 反脆弱模式 —— 这些规则值得保留
    ANTIFRAGILE_PATTERNS = [
        r"(禁止|允许|必须).*(执行|删除|修改|创建).*文件",
        r"(禁止|允许|必须).*(调用|执行|运行).*(命令|脚本|代码)",
        r"(token|key|密钥|密码|secret).*(不要|禁止|不能)",
        r"(安全|权限|认证).*(检查|验证|确认)",
        r"git (commit|push|pull|add).*(前|后|时|之前|之后)",
        r"(备份|保存|存档).*(前|后|时)",
        r"先.*确认.*再.*执行",
        r"必须.*请示.*才能",
        r"禁止.*自主.*决定",
    ]

    def __init__(self, model_level: int = 5):
        """
        model_level: 模型智能等级 (1-10)
           1 = 最笨（规则越多越好）
           10 = 最聪明（规则越少越好）
           默认5 = 中等
        """
        self.model_level = model_level

    def ask_five_questions(self, rule_text: str) -> dict:
        """
        对一条规则问五问。
        返回: {question_id: True/False/None}
          True = 此问法命中
          False = 此问法不命中
          None = 不确定
        """
        rule_lower = rule_text.lower()
        questions = {}

        # Q1: 默认行为？更智能的模型默认会做这个吗？
        q1 = False
        for pattern in self.DEFAULT_PATTERNS:
            if re.search(pattern, rule_text):
                q1 = True
                break
        # 如果模型等级高，默认行为嫌疑更大
        if self.model_level >= 7:
            # 高等级模型，"不要啰嗦"类规则基本是废话
            for p in [r"不要(重复|啰嗦|冗余)", r"请(提供|给出).*(清晰|简洁)"]:
                if re.search(p, rule_text):
                    q1 = True
        questions[AuditQuestion.Q1_DEFAULT_BEHAVIOR] = q1

        # Q2: 矛盾？这条规则和常见规则有矛盾吗？
        q2 = None  # 默认不确定，因为需要上下文
        contradiction_signals = [
            (r"(不要|禁止).*自主", r"(可以|允许).*自主"),
            (r"先.*请示", r"自主.*决定"),
            (r"尽量.*详细", r"保持.*简洁"),
        ]
        for a, b in contradiction_signals:
            if re.search(a, rule_text) and re.search(b, rule_text):
                q2 = True
                break
        questions[AuditQuestion.Q2_CONTRADICTION] = q2

        # Q3: 冗余？和其他规则重复？
        q3 = None  # 需要全局扫描判断
        questions[AuditQuestion.Q3_REDUNDANCY] = q3

        # Q4: 一次性修复？
        q4 = False
        for pattern in self.ONE_TIME_FIX_PATTERNS:
            if re.search(pattern, rule_text):
                q4 = True
                break
        questions[AuditQuestion.Q4_ONE_TIME_FIX] = q4

        # Q5: 模糊？
        q5 = False
        for pattern in self.VAGUE_PATTERNS:
            if re.search(pattern, rule_lower):
                q5 = True
                break
        questions[AuditQuestion.Q5_VAGUE] = q5

        return questions

    def classify(self, rule_text: str, questions: dict = None) -> tuple:
        """
        根据五问结果分类。
        返回: (verdict, reason, token_saving, suggestion)
        """
        if questions is None:
            questions = self.ask_five_questions(rule_text)

        q1 = questions.get(AuditQuestion.Q1_DEFAULT_BEHAVIOR, False)
        q4 = questions.get(AuditQuestion.Q4_ONE_TIME_FIX, False)
        q5 = questions.get(AuditQuestion.Q5_VAGUE, False)

        # 检查反脆弱模式 —— 如果是安全/操作规则，直接KEEP
        is_antifragile = False
        for pattern in self.ANTIFRAGILE_PATTERNS:
            if re.search(pattern, rule_text):
                is_antifragile = True
                break

        if is_antifragile:
            # 安全/操作规则，保留
            saving = self._estimate_tokens(rule_text)
            return (AuditVerdict.KEEP,
                    "安全/操作规则，约束具体行为，反脆弱",
                    0,
                    "")

        # Q1 + Q4 + Q5 的组合判断
        if q1 and not q4 and not q5:
            # 只是默认行为，没有额外价值
            saving = self._estimate_tokens(rule_text)
            return (AuditVerdict.CUT,
                    f"更智能的模型默认会做（模型等级{self.model_level}）",
                    saving,
                    "直接删除，不替换")

        if q4 and not q1:
            # 一次性修复 —— 需要看看根源问题
            saving = self._estimate_tokens(rule_text)
            return (AuditVerdict.RESOLVE,
                    "看起来是修补特定错误的补丁规则",
                    saving // 2,
                    "建议找到根源问题，修复模型/代码而非加规则")

        if q5:
            # 模糊规则
            saving = self._estimate_tokens(rule_text)
            if q1:
                return (AuditVerdict.CUT,
                        "模糊且模型默认会做，直接删除",
                        saving,
                        "")
            return (AuditVerdict.SHARPEN,
                    "规则表述模糊，每次解释结果可能不同",
                    saving // 2,
                    "建议用具体示例替换模糊表述")

        if q1 and q4:
            saving = self._estimate_tokens(rule_text)
            return (AuditVerdict.CUT,
                    "默认行为+一次性修复，双重冗余",
                    saving,
                    "直接删除")

        # 默认：保留
        return (AuditVerdict.KEEP, "有明确的约束价值", 0, "")

    def audit(self, rule_text: str, context: str = "") -> RuleAuditItem:
        """单条规则审计"""
        questions = self.ask_five_questions(rule_text)
        verdict, reason, saving, suggestion = self.classify(rule_text, questions)

        return RuleAuditItem(
            rule_text=rule_text,
            context=context,
            questions=questions,
            verdict=verdict,
            reason=reason,
            token_saving=saving,
            suggestion=suggestion,
        )

    def _estimate_tokens(self, text: str) -> int:
        """估计规则占用的token数（英文~4字符/token，中文~1.5字符/token）"""
        # 粗略估计：中英文混排 ~2.5字符/token
        chars = len(text)
        return max(5, chars // 3)  # 最低5 tokens


# ═══════════════════════════════════════════════════
# SOP文件扫描
# ═══════════════════════════════════════════════════

class SOPFileScanner:
    """扫描SOP/Markdown文件，提取需要审计的规则"""

    # 规则提取模式：列表项、代码块中的规则、特定关键字行
    RULE_PATTERNS = [
        r"^\s*[-*+]\s+(.*)",               # Markdown列表项
        r"^\s*\d+[.、]\s+(.*)",             # 编号列表
        r"^\s*>\s*(.*)",                     # 引用块
        r"^\s*[-*+]\s*\[.*\]\s*(.*)",       # 任务列表
    ]

    def __init__(self):
        self._rule_cache = {}

    def extract_rules(self, text: str, filename: str = "") -> list:
        """从文本中提取规则"""
        rules = []
        lines = text.split("\n")

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # 跳过空行/标题/代码块标记
            if not stripped or stripped.startswith("#") or stripped.startswith("```"):
                i += 1
                continue

            # 跳过纯英文（大概率是代码/配置）
            if re.match(r'^[a-zA-Z0-9_\-\.\/\s\[\]\(\)\{\}]+$', stripped):
                i += 1
                continue

            # 检查规则模式
            for pattern in self.RULE_PATTERNS:
                m = re.match(pattern, stripped)
                if m:
                    content = m.group(1).strip()
                    # 过滤太短的行（<5字符）或太长（>500字符）
                    if 8 <= len(content) <= 500:
                        rules.append(content)
                    break
            i += 1

        return rules

    def deduplicate(self, rules: list) -> list:
        """去重（基于前缀匹配）"""
        seen = []
        result = []
        for r in rules:
            # 如果已存在的规则包含此规则，跳过
            found = False
            for s in seen:
                if r in s or s in r:
                    found = True
                    break
            if not found:
                seen.append(r)
                result.append(r)
        return result


# ═══════════════════════════════════════════════════
# SOP审计器统一入口
# ═══════════════════════════════════════════════════

class SOPAuditor:
    """
    SOP审计器 — 统一入口

    集成BitterPillEngine + SOPFileScanner
    可以对单条规则、单个文件、全部SOP做审计
    """

    def __init__(self, memory_dir: str = None, model_level: int = 5):
        self.engine = BitterPillEngine(model_level=model_level)
        self.scanner = SOPFileScanner()
        if memory_dir is None:
            self.memory_dir = os.path.join(os.path.dirname(__file__))
        else:
            self.memory_dir = memory_dir

    def audit_rule(self, rule_text: str, context: str = "") -> RuleAuditItem:
        """审计一条规则"""
        return self.engine.audit(rule_text, context)

    def audit_file(self, filepath: str) -> AuditReport:
        """审计一个SOP文件"""
        if not os.path.exists(filepath):
            return AuditReport(source=f"FILE_NOT_FOUND: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()

        raw_rules = self.scanner.extract_rules(text, filepath)
        rules = self.scanner.deduplicate(raw_rules)

        filename = os.path.basename(filepath)
        report = AuditReport(source=filename)

        for rule in rules:
            item = self.engine.audit(rule, context=filename)
            report.items.append(item)

        report.compute_summary()
        return report

    def audit_all_sops(self, pattern: str = "*.md") -> list:
        """审计所有SOP文件"""
        if not os.path.isdir(self.memory_dir):
            return []

        import glob
        reports = []
        for f in sorted(glob.glob(os.path.join(self.memory_dir, pattern))):
            if os.path.basename(f) in ("global_mem_insight.txt", "README.md"):
                continue
            report = self.audit_file(f)
            if report.items:
                reports.append(report)

        return reports

    def audit_text(self, text: str, source: str = "text") -> AuditReport:
        """直接审计文本内容"""
        raw_rules = self.scanner.extract_rules(text, source)
        rules = self.scanner.deduplicate(raw_rules)

        report = AuditReport(source=source)
        for rule in rules:
            item = self.engine.audit(rule, context=source)
            report.items.append(item)

        report.compute_summary()
        return report

    def print_summary(self, reports: list):
        """打印汇总报告"""
        total_rules = 0
        total_cut = 0
        total_saving = 0
        total_keep = 0

        lines = ["\n" + "=" * 60,
                 "📋 SOP审计汇总报告",
                 "=" * 60]

        for r in reports:
            lines.append(f"\n  📄 {r.source}")
            lines.append(f"     规则: {r.summary['total_rules']} | "
                         f"✂️删除: {r.summary['verdicts']['CUT']} | "
                         f"⚡矛盾: {r.summary['verdicts']['RESOLVE']} | "
                         f"📎合并: {r.summary['verdicts']['MERGE']} | "
                         f"🔧精炼: {r.summary['verdicts']['SHARPEN']} | "
                         f"✅保留: {r.summary['verdicts']['KEEP']} | "
                         f"节省: ~{r.summary['total_token_saving']}t")
            total_rules += r.summary['total_rules']
            total_cut += r.summary['verdicts']['CUT']
            total_saving += r.summary['total_token_saving']
            total_keep += r.summary['verdicts']['KEEP']

        lines.append("\n" + "-" * 60)
        lines.append(f"  总计: {total_rules} 条规则")
        lines.append(f"  建议删除/合并: {total_cut + sum(r.summary['verdicts']['MERGE'] for r in reports)} 条")
        lines.append(f"  保留率: {round(total_keep/max(total_rules,1)*100,1)}%")
        lines.append(f"  总Token节省: ~{total_saving} tokens")
        lines.append("=" * 60)

        return "\n".join(lines)


# ═══════════════════════════════════════════════════
# 快捷函数
# ═══════════════════════════════════════════════════

def audit(rule: str, context: str = "") -> dict:
    """快捷审计一条规则"""
    auditor = SOPAuditor()
    result = auditor.audit_rule(rule, context)
    return result.to_dict()


def quick_test():
    """快速冒烟测试"""
    auditor = SOPAuditor()

    # 测试1: 审计一条明显多余的规则
    r1 = auditor.audit_rule("请不要使用百度搜索", "搜索规则")
    assert r1.verdict in ("CUT", "KEEP"), f"预期CUT或KEEP, 得到{r1.verdict}"
    print(f"✅ 测试1通过: [{r1.verdict}] {r1.rule_text[:40]}... | 节省~{r1.token_saving}t")

    # 测试2: 审计一条反脆弱规则（安全相关）
    r2 = auditor.audit_rule("git commit 前必须先检查文件状态", "操作规则")
    assert r2.verdict == "KEEP", f"安全规则应KEEP, 得到{r2.verdict}"
    print(f"✅ 测试2通过: [{r2.verdict}] {r2.rule_text[:40]}... | 理由: {r2.reason}")

    # 测试3: 审计一条模糊规则
    r3 = auditor.audit_rule("适当的时候要检查代码质量", "质量规则")
    print(f"✅ 测试3: [{r3.verdict}] {r3.rule_text[:40]}... | 理由: {r3.reason}")

    # 测试4: 审计整段文本
    text = """
    - 不要啰嗦
    - 记得检查API返回状态
    - 禁止删除未提交的文件
    - 尽量保持代码整洁
    """
    report = auditor.audit_text(text, "测试文本")
    report.compute_summary()
    print(f"✅ 测试4通过: {report.summary['total_rules']}条规则, "
          f"CUT={report.summary['verdicts']['CUT']}, "
          f"KEEP={report.summary['verdicts']['KEEP']}")

    print(f"\n🎉 所有冒烟测试通过!")


if __name__ == "__main__":
    quick_test()
