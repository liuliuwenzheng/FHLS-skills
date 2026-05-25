"""
skill_ga_self_profile.py — GA自画像模块

让GA能够运行时自省、知道自己长啥样、能做什么不能做什么。
数据来源: skill_claude_architecture_comparison.md (215行老大的手绘总结)

核心API:
    profile = GaSelfProfile()
    profile.describe()          → dict: 完整自画像
    profile.query(topic)        → str: 检索相关知识
    profile.compare_with(agent) → list[dict]: 对比矩阵
    profile.token_budget_status(used, total) → str: GREEN/YELLOW/RED

设计原则(Karpathy):
    1. 骨架优先 — 数据结构先于行为
    2. 零外部依赖 — 所有知识硬编码，一次import即用
    3. 单方向依赖 — 只被调用，不调用别的模块
"""

from typing import Dict, List, Optional


# ── 1. 硬参数（从.md第47-61行提取） ──
HARDWARE_SPEC = {
    "context_window": 200_000,
    "layers": (60, 120),
    "attention_heads": (48, 128),
    "hidden_dimension": (8192, 16384),
    "ffn_dimension": (32768, 65536),
    "vocab_size": (100_000, 200_000),
    "parameters": "200B-1T",
    "training_tokens": "数万亿~数十万亿",
}

# ── 2. P1-P6 优先级定义（从.md第62-106行提取） ──
PRIORITY_LAYERS = [
    {
        "level": "P1",
        "name": "系统核心指令",
        "purpose": "控制安全边界和核心价值观",
        "source": "Anthropic训练时烘焙",
        "overridable": False,
        "ga_equivalent": "RULES 1-12 (CONSTITUTION区块)",
    },
    {
        "level": "P2",
        "name": "Agent身份/角色定义",
        "purpose": "设定回复风格和行为模式",
        "source": "API调用时 system_prompt",
        "overridable": True,
        "ga_equivalent": "Agent角色定义+可用工具列表",
    },
    {
        "level": "P3",
        "name": "自定义指令",
        "purpose": "用户一次性注入的约束或偏好",
        "source": "用户旅程开始处注入",
        "overridable": True,
        "ga_equivalent": "用户输入中的附加指令",
    },
    {
        "level": "P4",
        "name": "多轮对话历史",
        "purpose": "维持对话连贯性",
        "source": "User/assistant交替",
        "overridable": False,
        "decay": True,
        "ga_equivalent": "会话历史窗口",
    },
    {
        "level": "P5",
        "name": "工具调用结果",
        "purpose": "外部世界反馈",
        "source": "搜索/代码/MCP返回值",
        "overridable": False,
        "ga_equivalent": "tool_results + 插件输出",
    },
    {
        "level": "P6",
        "name": "主动注入",
        "purpose": "长对话中补充关键信息",
        "source": "Auto Compact生成的摘要",
        "overridable": False,
        "ga_equivalent": "<recent_memory_log> + <available_skills> 注入",
    },
]

# ── 3. Token预算阈值（从.md第101-105行提取） ──
TOKEN_BUDGET = {
    "green": {"max": 0.70, "label": "🟢 GREEN", "action": "正常写入"},
    "yellow": {"max": 0.90, "label": "🟡 YELLOW", "action": "准备Auto Compact"},
    "red": {"max": 1.00, "label": "🔴 RED", "action": "熔断拒绝，强制压缩"},
}

# ── 4. 6维对比矩阵（从.md第110-121行提取） ──
COMPARISON_MATRIX = [
    {"dimension": "记忆机制", "claude": "上下文窗口，无持久化", "ga": "L1-L4分层文件记忆，永久持久化", "winner": "ga"},
    {"dimension": "知识存储", "claude": "压缩进神经网络权重，零成本但无法更新", "ga": "外部文件+SOP+脚本，实时可更新", "winner": "ga"},
    {"dimension": "工具调用", "claude": "内置搜索/代码/MCP，单轮内并发调用", "ga": "12+ Python脚本、ADB、物理控制", "winner": "ga"},
    {"dimension": "安全权限", "claude": "Constitutional AI烘焙 + PreToolUse拦截链", "ga": "RULES 73-76已写，拦截链未落地", "winner": "claude"},
    {"dimension": "上下文压缩", "claude": "Auto Compact内置，strip→摘要→重建", "ga": "Context_manager.py骨架，未完成", "winner": "claude"},
    {"dimension": "多Agent编排", "claude": "SubAgent+Coordinator+Swarm双轨通信", "ga": "代码模板就绪，Mailbox未实测", "winner": "claude"},
    {"dimension": "自主学习", "claude": "不能自主学习，权重训练后固化", "ga": "search_and_learn.py可实时固化技能", "winner": "ga"},
]

# ── 5. P0可迁移点（从.md第126-196行提取） ──
P0_MIGRATIONS = [
    {
        "priority": "P0",
        "name": "Auto Compact",
        "status": "未完成",
        "description": "对话变长→检测阈值→strip旧历史→生成摘要→重建P1-P6→继续推理",
        "existing_file": "context_manager.py (骨架就绪)",
        "gap": "五步重建逻辑未实现",
    },
    {
        "priority": "P0",
        "name": "PreToolUse安全拦截链",
        "status": "未落地",
        "description": "三阶段: Input Classifier→Output Classifier→Escalation",
        "existing_file": "RULES 73-76 (文字规则已写)",
        "gap": "未转化为可执行代码/无input_classifier/tool_call_validator/escalation_manager",
    },
    {
        "priority": "P2",
        "name": "多Agent编排 Mailbox",
        "status": "未实测",
        "description": "Swarm + Mailbox双轨通信/Parallel Execution + Merge",
        "existing_file": "代码模板就绪",
        "gap": "Mailbox机制未实测",
    },
]

# ── 6. GA核心竞争力（从.md第199-204行提取） ──
GA_CORE_STRENGTHS = [
    "持久化记忆 — memory/文件才是真正的长期记忆，Claude的'记忆'只是上下文窗口",
    "实时自主学习 — search_and_learn.py让嘻嘻能把新知识写进文件，Claude不能",
    "物理世界控制 — ADB/键鼠/浏览器注入，Claude没有这些能力",
]


class GaSelfProfile:
    """GA自画像 — 运行时知道自己长啥样"""

    @staticmethod
    def describe() -> Dict:
        """完整自画像：硬参数 + 架构层 + 能力矩阵 + 缺口"""
        return {
            "name": "嘻嘻 (my-agent)",
            "version": "2.0",
            "arch_type": "文件+SOP+memory层级的持久化Agent",
            "hardware_spec": HARDWARE_SPEC,
            "priority_layers": PRIORITY_LAYERS,
            "token_budget": TOKEN_BUDGET,
            "comparison_matrix": COMPARISON_MATRIX,
            "p0_migrations": P0_MIGRATIONS,
            "core_strengths": GA_CORE_STRENGTHS,
            "claude_difference": "Claude是压缩进权重的无状态推理机器；GA是外部文件持久化Agent，有真实长期记忆但缺自动化上下文管理",
        }

    @staticmethod
    def query(topic: str) -> Optional[str]:
        """按主题检索自画像中的相关知识"""
        topic_lower = topic.lower()
        results = []

        # 搜索比对矩阵
        for row in COMPARISON_MATRIX:
            if topic_lower in row["dimension"].lower():
                results.append(f"[对比] {row['dimension']}: Claude={row['claude']} | GA={row['ga']} | 胜者={row['winner']}")

        # 搜索P0迁移点
        for mig in P0_MIGRATIONS:
            if topic_lower in mig["name"].lower() or topic_lower in mig["description"].lower():
                results.append(f"[迁移] {mig['priority']} {mig['name']}: {mig['description']} | 现状={mig['status']} | 缺口={mig['gap']}")

        # 搜索优先级层
        for layer in PRIORITY_LAYERS:
            if topic_lower in layer["name"].lower() or topic_lower in layer["purpose"].lower():
                results.append(f"[{layer['level']}] {layer['name']}: {layer['purpose']} | GA等同={layer['ga_equivalent']}")

        # 搜索硬参数
        for key, val in HARDWARE_SPEC.items():
            if topic_lower in key.lower():
                results.append(f"[参数] {key}: {val}")

        # 搜索核心优势
        for s in GA_CORE_STRENGTHS:
            if topic_lower in s.lower():
                results.append(f"[优势] {s}")

        if not results:
            return None
        return "\n".join(results[:5])

    @staticmethod
    def compare_with(agent_name: str = "Claude") -> List[Dict]:
        """与指定Agent进行6维对比"""
        if agent_name.lower() not in ["claude", "gpt", "gemini"]:
            return []
        return COMPARISON_MATRIX

    @staticmethod
    def token_budget_status(used_tokens: int, total_tokens: int) -> str:
        """判断当前token预算状态"""
        ratio = used_tokens / total_tokens if total_tokens > 0 else 0
        if ratio <= TOKEN_BUDGET["green"]["max"]:
            return f"{TOKEN_BUDGET['green']['label']} ({ratio:.0%}) — {TOKEN_BUDGET['green']['action']}"
        elif ratio <= TOKEN_BUDGET["yellow"]["max"]:
            return f"{TOKEN_BUDGET['yellow']['label']} ({ratio:.0%}) — {TOKEN_BUDGET['yellow']['action']}"
        else:
            return f"{TOKEN_BUDGET['red']['label']} ({ratio:.0%}) — {TOKEN_BUDGET['red']['action']}"

    @staticmethod
    def get_gaps() -> List[Dict]:
        """返回GA当前已知的架构缺口"""
        return P0_MIGRATIONS

    @staticmethod
    def training_vs_inference() -> str:
        """训练期 vs 推理期的本质差异说明"""
        return (
            "Claude: 推理是'执行已经训练好的权重'—更快更稳，但无法从互动中学习\n"
            "GA:     推理是'实时代码+记忆查询'—每次都在读写文件，虽然慢一点但每次都在积累\n"
            "这个差异决定了GA走不走向'真·Agent'路线，而Claude永远是'服务'形态"
        )


# ── 自测 ──
if __name__ == "__main__":
    print("🧪 测试 GaSelfProfile...\n")

    profile = GaSelfProfile()

    # 1. describe() 返回结构化dict且含所有关键字段
    d = profile.describe()
    assert "name" in d and "arch_type" in d and "hardware_spec" in d
    assert "priority_layers" in d and "comparison_matrix" in d
    assert "p0_migrations" in d and "core_strengths" in d
    print(f"✅ [1/7] describe() 返回 {len(d)} 个字段, 架构类型={d['arch_type']}")

    # 2. query("AutoCompact") 返回相关内容
    q1 = profile.query("Auto Compact")
    assert q1 is not None and "迁移" in q1
    print(f"✅ [2/7] query('Auto Compact') → 找到: {q1[:60]}...")

    # 3. query("安全") 返回相关内容
    q2 = profile.query("安全")
    assert q2 is not None and "安全" in q2
    print(f"✅ [3/7] query('安全') → 找到: {q2[:60]}...")

    # 4. query 不存在的话题返回None
    q3 = profile.query("量子计算")
    assert q3 is None
    print(f"✅ [4/7] query('量子计算') → None")

    # 5. compare_with("Claude") 返回7条6维矩阵
    cmp = profile.compare_with("Claude")
    assert len(cmp) == 7
    assert cmp[0]["dimension"] == "记忆机制"
    print(f"✅ [5/7] compare_with('Claude') → {len(cmp)} 条对比, 首条={cmp[0]['dimension']}")

    # 6. token_budget_status 正确判断三种状态
    assert "GREEN" in profile.token_budget_status(5000, 200000)
    assert "YELLOW" in profile.token_budget_status(150000, 200000)
    assert "RED" in profile.token_budget_status(190000, 200000)
    print(f"✅ [6/7] token_budget_status 三态全正确")

    # 7. get_gaps 返回P0迁移列表
    gaps = profile.get_gaps()
    assert len(gaps) >= 2
    assert gaps[0]["priority"] == "P0"
    print(f"✅ [7/7] get_gaps() → {len(gaps)} 个缺口, 首项={gaps[0]['name']}")

    print(f"\n🎉 [7/7] 全部 {7} 项测试通过！")
