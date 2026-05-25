"""
skill_rule_engine.py — GA规则碎片系统

骨髓内化来源: cc-best (Claude Code最佳实践模板, 44⭐)
核心设计: 将cc-best的rules/目录模式映射到GA
          "出错→写规则"循环 → 每次失败自动生成可复用规则

核心功能:
  1. Rule — 规则数据结构（trigger/severity/behavior）
  2. RuleLoader — 从memory/rules/加载规则文件
  3. RuleMatcher — 根据上下文匹配规则
  4. RuleGenerator — 从错误记录自动生成规则
  5. RuleEngine — 统一入口: 加载→匹配→注入→生成

用法:
    from memory.skill_rule_engine import rule_engine
    re = rule_engine()
    re.load_all()                # 加载rules/目录全部规则
    matched = re.match("调API超时")  # 匹配规则
    re.inject_to_prompt()        # 生成注入文本
    re.generate_rule(...)        # 从错误生成规则
"""

import os
import re
import datetime
import json
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════
# 规则数据结构
# ═══════════════════════════════════════════════════

@dataclass
class Rule:
    """一条规则"""
    rule_id: str               # 规则ID: R001, R002, ...
    title: str                 # 标题
    trigger: str               # 触发关键词
    behavior: str              # 应该怎么做
    severity: str = "medium"   # high/medium/low
    source: str = "manual"     # manual|reflection|constitution
    created: str = ""          # 创建日期
    examples: list = field(default_factory=list)  # 正反示例
    hit_count: int = 0         # 匹配次数

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "trigger": self.trigger,
            "behavior": self.behavior,
            "severity": self.severity,
            "source": self.source,
            "created": self.created,
            "examples": self.examples,
            "hit_count": self.hit_count,
        }


# ═══════════════════════════════════════════════════
# RuleLoader — 规则加载
# ═══════════════════════════════════════════════════

_RULES_DIR = os.path.join(os.path.dirname(__file__), "rules")

class RuleLoader:
    """从rules/目录加载规则文件"""

    @staticmethod
    def list_rules() -> list[str]:
        """列出所有规则文件"""
        if not os.path.isdir(_RULES_DIR):
            return []
        files = os.listdir(_RULES_DIR)
        return sorted([f for f in files if f.endswith('.md') and f != 'README.md'])

    @staticmethod
    def load(filepath: str) -> Optional[Rule]:
        """从单个规则文件解析Rule对象"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return None

        # 解析frontmatter
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
        if not match:
            return None

        frontmatter = match.group(1)
        body = match.group(2).strip()

        # 解析YAML-like frontmatter（简单解析，不依赖pyyaml）
        meta = {}
        for line in frontmatter.split('\n'):
            m = re.match(r'(\w+):\s*"?(.+?)"?\s*$', line)
            if m:
                meta[m.group(1)] = m.group(2).strip('"').strip("'")

        # 从body提取标题
        title_match = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
        title = title_match.group(1) if title_match else meta.get('title', '')

        # 从body提取behavior（"## 行为"后的第一段）
        behav_match = re.search(r'## 行为\s*\n(.*?)(?:\n##|\Z)', body, re.DOTALL)
        behavior = behav_match.group(1).strip() if behav_match else body[:200]

        # 提取示例
        examples = []
        ex_section = re.search(r'## 正反示例\s*\n(.*?)(?:\n##|\Z)', body, re.DOTALL)
        if ex_section:
            for line in ex_section.group(1).split('\n'):
                line = line.strip()
                if line.startswith('- ✅'):
                    examples.append(("✅ 好", line[3:].strip()))
                elif line.startswith('- ❌'):
                    examples.append(("❌ 坏", line[3:].strip()))

        return Rule(
            rule_id=meta.get('rule_id', 'R000'),
            title=title,
            trigger=meta.get('trigger', ''),
            behavior=behavior,
            severity=meta.get('severity', 'medium'),
            source=meta.get('source', 'manual'),
            created=meta.get('created', ''),
            examples=examples,
        )

    @staticmethod
    def load_all() -> list[Rule]:
        """加载所有规则"""
        rules = []
        for filename in RuleLoader.list_rules():
            filepath = os.path.join(_RULES_DIR, filename)
            rule = RuleLoader.load(filepath)
            if rule:
                rules.append(rule)
        return rules


# ═══════════════════════════════════════════════════
# RuleMatcher — 规则匹配
# ═══════════════════════════════════════════════════

class RuleMatcher:
    """根据上下文匹配规则"""

    @staticmethod
    def match(context: str, rules: list[Rule]) -> list[Rule]:
        """匹配规则，按severity排序"""
        matched = []
        for rule in rules:
            if not rule.trigger:
                continue
            # 简单关键词匹配（大小写不敏感）
            if rule.trigger.lower() in context.lower():
                rule.hit_count += 1
                matched.append(rule)

        # 按严重度排序
        severity_order = {"high": 0, "medium": 1, "low": 2}
        matched.sort(key=lambda r: severity_order.get(r.severity, 99))
        return matched

    @staticmethod
    def match_by_tags(tags: list[str], rules: list[Rule]) -> list[Rule]:
        """按标签匹配"""
        matched = []
        for rule in rules:
            for tag in tags:
                if tag.lower() in rule.trigger.lower() or \
                   tag.lower() in rule.title.lower():
                    rule.hit_count += 1
                    matched.append(rule)
                    break
        return matched


# ═══════════════════════════════════════════════════
# RuleGenerator — 从错误自动生成规则
# ═══════════════════════════════════════════════════

class RuleGenerator:
    """从错误记录/反射日志自动生成规则文件"""

    _counter = 0

    @classmethod
    def next_id(cls) -> str:
        cls._counter += 1
        return f"R{cls._counter:03d}"

    @classmethod
    def generate(cls, error_context: str, root_cause: str,
                 behavior: str = "", severity: str = "medium",
                 source: str = "reflection") -> Rule:
        """
        从错误上下文自动生成规则

        参数:
            error_context: 错误发生的场景描述
            root_cause: 根因分析
            behavior: 应该怎么做（建议）
            severity: high/medium/low
            source: 来源
        """
        rule_id = cls.next_id()
        now = datetime.date.today().isoformat()

        # 从错误中提取关键词作为trigger — 中文逗号拼接(保留原始语义)
        words = re.findall(r'[\u4e00-\u9fff\w]+', error_context[:100])
        trigger = "，".join(words[:5]) if words else error_context[:30]

        if not behavior:
            behavior = f"避免{root_cause[:60]}。替代方案需验证后再执行。"

        return Rule(
            rule_id=rule_id,
            title=f"从错误中学习: {root_cause[:40]}",
            trigger=trigger,
            behavior=behavior,
            severity=severity,
            source=source,
            created=now,
            examples=[
                ("✅ 好", f"先诊断{root_cause[:20]}再操作"),
                ("❌ 坏", "直接重试相同方案"),
            ],
        )

    @classmethod
    def save_rule(cls, rule: Rule) -> Optional[str]:
        """保存规则到rules/目录"""
        os.makedirs(_RULES_DIR, exist_ok=True)
        # Windows文件名不能含 : / \ ? * < > |
        safe_title = rule.title[:20].replace(' ', '_')
        safe_title = re.sub(r'[<>:"/\\|?*]', '', safe_title)
        # 确保文件名以.md结尾
        filename = f"{rule.rule_id}_{safe_title}.md"
        filepath = os.path.join(_RULES_DIR, filename)

        ex_lines = []
        for label, text in rule.examples:
            ex_lines.append(f"- {label} {text}")

        content = f"""---
rule_id: {rule.rule_id}
trigger: "{rule.trigger}"
severity: "{rule.severity}"
created: "{rule.created}"
source: "{rule.source}"
---

# {rule.title}

## 上下文
{rule.trigger}

## 行为
{rule.behavior}

## 正反示例
{chr(10).join(ex_lines)}
"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return filepath
        except Exception as e:
            return None


# ═══════════════════════════════════════════════════
# RuleEngine — 统一入口
# ═══════════════════════════════════════════════════

class RuleEngine:
    """规则引擎——加载→匹配→注入→生成"""

    def __init__(self):
        self._rules: list[Rule] = []
        self._loader = RuleLoader()
        self._matcher = RuleMatcher()
        self._generator = RuleGenerator()

    def load_all(self) -> int:
        """加载全部规则"""
        self._rules = self._loader.load_all()
        return len(self._rules)

    def match(self, context: str) -> list[Rule]:
        """匹配规则"""
        return self._matcher.match(context, self._rules)

    def match_by_tags(self, tags: list[str]) -> list[Rule]:
        """按标签匹配"""
        return self._matcher.match_by_tags(tags, self._rules)

    def generate_rule(self, error_context: str, root_cause: str,
                      behavior: str = "", severity: str = "medium",
                      source: str = "reflection") -> Rule:
        """从错误生成规则"""
        rule = self._generator.generate(
            error_context, root_cause, behavior, severity, source)
        return rule

    def save_rule(self, rule: Rule) -> Optional[str]:
        """保存规则到文件"""
        return self._generator.save_rule(rule)

    def from_reflection(self, error_context: str, root_cause: str,
                        behavior: str = "") -> str:
        """
        从反射日志自动生成并保存规则（一键操作）

        返回: 保存的规则文件路径 或 错误信息
        """
        rule = self.generate_rule(error_context, root_cause, behavior,
                                  severity="medium", source="reflection")
        filepath = self.save_rule(rule)
        if filepath:
            # 自动重新加载
            self.load_all()
            return filepath
        return "保存失败"

    def inject_to_prompt(self, max_rules: int = 5) -> str:
        """生成可注入提示的规则摘要"""
        if not self._rules:
            return "[规则系统] 无规则已加载"

        # 取最高严重度的规则
        severity_order = {"high": 0, "medium": 1, "low": 2}
        sorted_rules = sorted(self._rules,
                              key=lambda r: severity_order.get(r.severity, 99))

        lines = [f"[规则系统] {len(self._rules)}条规则已加载"]
        for rule in sorted_rules[:max_rules]:
            lines.append(
                f"  [{rule.severity}] {rule.title[:35]} → {rule.behavior[:50]}"
            )
        if len(self._rules) > max_rules:
            lines.append(f"  ... 还有{len(self._rules) - max_rules}条规则")

        return "\n".join(lines)

    def summary(self) -> str:
        """引擎状态摘要"""
        sev_count = {"high": 0, "medium": 0, "low": 0}
        src_count = {}
        for r in self._rules:
            sev_count[r.severity] = sev_count.get(r.severity, 0) + 1
            src_count[r.source] = src_count.get(r.source, 0) + 1

        return (
            f"📋 规则引擎状态\n"
            f"  规则总数: {len(self._rules)}条\n"
            f"  严重度: {sev_count}\n"
            f"  来源: {src_count}\n"
            f"  平均命中: {sum(r.hit_count for r in self._rules) / max(len(self._rules), 1):.1f}次/条"
        )


# ═══════════════════════════════════════════════════
# 单例工厂
# ═══════════════════════════════════════════════════

_engine_instance: Optional[RuleEngine] = None

def rule_engine() -> RuleEngine:
    """获取单例规则引擎"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RuleEngine()
    return _engine_instance


# ═══════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════

def self_test() -> dict:
    """执行全部自检"""
    results = {}

    # 1. 初始化
    re = rule_engine()
    results["init"] = isinstance(re, RuleEngine)

    # 2. 加载规则（空目录）
    count = re.load_all()
    results["load_empty"] = count >= 0

    # 3. 生成规则（模拟错误→规则）
    rule = re.generate_rule(
        "调用API超时，重试3次后放弃",
        "未设置正确超时时间",
        behavior="调用API前先查文档确认超时参数"
    )
    results["generate_rule"] = rule.rule_id.startswith("R") and rule.trigger != ""

    # 4. 保存规则
    path = re.save_rule(rule)
    results["save_rule"] = path is not None and os.path.isfile(path)

    # 5. 重新加载（应该有1条）
    count2 = re.load_all()
    results["load_with_rules"] = count2 == 1

    # 6. 匹配（context匹配trigger关键词）
    matched = re.match("调用API超时，重试3次后放弃")
    results["match"] = len(matched) >= 1

    # 7. 注入提示
    prompt = re.inject_to_prompt()
    results["inject"] = "规则系统" in prompt

    # 8. 从反射日志生成
    ref_path = re.from_reflection(
        "重复尝试相同失败方案3次",
        "未记录失败原因就重试",
        "失败后先分析根因再决定重试"
    )
    results["from_reflection"] = ref_path is not None and os.path.isfile(ref_path) if isinstance(ref_path, str) and not ref_path.startswith("保存失败") else False

    # 9. 再次加载（应有2条）
    count3 = re.load_all()
    results["load_generated"] = count3 == 2

    # 清理测试生成的文件 — 用save_rule相同逻辑构建文件名
    import re as _re
    for r in [rule]:
        safe_title = r.title[:20].replace(' ', '_')
        safe_title = _re.sub(r'[<>:"/\\|?*]', '', safe_title)
        fpath = os.path.join(_RULES_DIR, f"{r.rule_id}_{safe_title}.md")
        if os.path.isfile(fpath):
            os.remove(fpath)

    # 清理from_reflection生成的文件
    for f in os.listdir(_RULES_DIR):
        if f != 'README.md':
            fpath = os.path.join(_RULES_DIR, f)
            try:
                os.remove(fpath)
            except:
                pass

    all_pass = all(results.values())
    return {
        "pass": all_pass,
        "results": results,
        "details": {
            "rules_count": count3,
            "inject_len": len(prompt),
        }
    }


if __name__ == "__main__":
    result = self_test()
    status = "✅ ALL PASS" if result["pass"] else "❌ FAILED"
    print(f"  [{status}] skill_rule_engine.py 自检")
    for k, v in result["results"].items():
        print(f"    {'✅' if v else '❌'} {k}")
    print(f"  详情: {result['details']}")
