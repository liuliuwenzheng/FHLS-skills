"""
GA Skill: 上下文压缩策略
========================
骨髓内化自 Claude Code 会话压缩算法（图2）
骨架优先: 7级优先级+自适应压缩策略
GA可import: 压缩/恢复/统计
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import IntEnum
import json, time

# ============================================================
# 1. 压缩优先级定义（图2核心: 7级不可逆优先级）
# ============================================================

class Priority(IntEnum):
    """压缩保留优先级 — 数字越小越优先保留"""
    USER_MESSAGES = 1      # 用户消息: 100%完整保留
    KEY_DECISIONS = 2      # 关键决策: 架构/技术选型
    CODE_CHANGES = 3       # 代码变更: 内容+原因
    TOOL_CALLS = 4         # 工具调用链: 目的+参数+结果
    TECH_CONTEXT = 5       # 技术上下文: 概念/框架/API
    PLANS_GOALS = 6        # 计划与目标: 里程碑/待办
    RECENT_ROUNDS = 7      # 最近N轮: 默认保留5轮


@dataclass
class CompressedSession:
    """压缩后的会话 — 只保留高优先级信息"""
    user_messages: List[str] = field(default_factory=list)
    key_decisions: List[Dict] = field(default_factory=list)
    code_changes: List[Dict] = field(default_factory=list)
    tool_call_trail: List[Dict] = field(default_factory=list)
    tech_context: List[str] = field(default_factory=list)
    plans_goals: List[str] = field(default_factory=list)
    recent_rounds: List[str] = field(default_factory=list)
    
    compression_ratio: float = 1.0  # 压缩比: 原大小/压缩后大小
    compressed_at: float = 0.0


class ContextCompressor:
    """
    上下文压缩器 — GA版
    
    用法:
        compressor = ContextCompressor(max_recent_rounds=5)
        compressed = compressor.compress(session_history)
    """
    
    def __init__(self, max_recent_rounds: int = 5, min_compression_ratio: float = 2.0):
        self.max_recent_rounds = max_recent_rounds
        self.min_compression_ratio = min_compression_ratio
    
    def compress(self, history: List[Dict]) -> CompressedSession:
        """按7级优先级压缩会话历史"""
        session = CompressedSession()
        session.compressed_at = time.time()
        
        original_size = len(json.dumps(history, ensure_ascii=False))
        
        for msg in history:
            role = msg.get('role', '')
            content = msg.get('content', '')
            priority = self._classify(msg)
            
            if role == 'user':
                session.user_messages.append(content)  # P1: 100%保留
            elif priority == Priority.KEY_DECISIONS:
                session.key_decisions.append(self._extract_decision(msg))  # P2: 保留决策
            elif priority == Priority.CODE_CHANGES:
                session.code_changes.append(self._extract_code_change(msg))  # P3: 保留代码变更
            elif priority == Priority.TOOL_CALLS:
                session.tool_call_trail.append(self._extract_tool_call(msg))  # P4: 保留工具调用
            elif priority == Priority.TECH_CONTEXT:
                session.tech_context.append(content[:500])  # P5: 截断到500字
            elif priority == Priority.PLANS_GOALS:
                session.plans_goals.append(content[:300])  # P6: 截断到300字
            elif priority <= Priority.RECENT_ROUNDS and len(session.recent_rounds) < self.max_recent_rounds:
                session.recent_rounds.append(content[:200])  # P7: 最近N轮截断
        
        compressed_size = len(json.dumps(session.__dict__, ensure_ascii=False))
        if original_size > 0:
            session.compression_ratio = round(original_size / max(compressed_size, 1), 2)
        
        return session
    
    def _classify(self, msg: Dict) -> Priority:
        """对消息进行优先级分类 — 关键词匹配+启发式"""
        content = str(msg.get('content', '')).lower()
        role = msg.get('role', '')
        
        # P1: 用户消息
        if role == 'user':
            return Priority.USER_MESSAGES
        
        # P2: 关键决策
        decision_keywords = ['决定', '选择', '采用', '方案', '架构', '技术选型',
                            'decide', 'choose', 'architecture', 'migration']
        if any(kw in content for kw in decision_keywords):
            return Priority.KEY_DECISIONS
        
        # P3: 代码变更
        if '```' in content or msg.get('tool_calls') or msg.get('function_call'):
            return Priority.CODE_CHANGES
        
        # P4: 工具调用
        if role == 'tool' or msg.get('tool_call_id'):
            return Priority.TOOL_CALLS
        
        # P5: 技术上下文
        tech_keywords = ['框架', '库', 'api', 'sdk', '协议', '配置',
                        'framework', 'library', 'protocol', 'config']
        if any(kw in content for kw in tech_keywords):
            return Priority.TECH_CONTEXT
        
        # P6: 计划目标
        plan_keywords = ['计划', '目标', '待办', 'todo', 'milestone', 'deadline',
                        '接下来', '下一步', 'next']
        if any(kw in content for kw in plan_keywords):
            return Priority.PLANS_GOALS
        
        # P7: 最近轮次
        return Priority.RECENT_ROUNDS
    
    def _extract_decision(self, msg: Dict) -> Dict:
        """提取决策信息"""
        return {
            "decision": msg.get('content', '')[:200],
            "timestamp": time.strftime('%H:%M:%S'),
        }
    
    def _extract_code_change(self, msg: Dict) -> Dict:
        """提取代码变更 — 保留文件名+变更摘要"""
        content = msg.get('content', '')
        lines = content.split('\n')
        files_changed = [l for l in lines if l.strip().startswith(('+', '-')) and '.' in l]
        return {
            "summary": content[:150],
            "files": files_changed[:5],
            "tool_calls": len(msg.get('tool_calls', [])),
        }
    
    def _extract_tool_call(self, msg: Dict) -> Dict:
        """提取工具调用链"""
        return {
            "name": msg.get('name', ''),
            "args_keys": list(msg.get('args', {}).keys()) if isinstance(msg.get('args'), dict) else [],
            "result_preview": str(msg.get('content', ''))[:100],
        }


# ============================================================
# 2. GA 压缩宪法 — 融入GA执行者宪法
# ============================================================

COMPRESSION_CONSTITUTION = """
【GA上下文压缩宪法】

第1条 用户消息神圣不可侵犯
    用户原始消息100%保留，绝不压缩。任何压缩算法不得裁减用户输入。

第2条 关键决策必须存档
    架构选型、技术方案选择、依赖升级等关键决策，必须保留决策理由。

第3条 代码变更要有"为什么"
    记录代码变更时，必须同时记录变更原因，而非仅记录变更内容。

第4条 工具调用链只留路标
    工具调用的完整参数不保留，但必须保留「调用了什么工具+为什么+结果如何」。

第5条 技术上下文轻量化
    概念解释保留不超过500字，API文档保留引用链接而非全文。

第6条 计划只保留未完成的
    已完成的里程碑自动归档，只保留进行中+未开始的待办项。

第7条 最近5轮完整保留
    最后5轮用户-Agent对话不压缩，确保连续性。
"""


if __name__ == "__main__":
    # 测试压缩
    test_history = [
        {"role": "user", "content": "帮我设计一个数据库迁移方案"},
        {"role": "assistant", "content": "我决定采用PostgreSQL + Flyway进行渐进式迁移"},
        {"role": "assistant", "content": "```python\n# migrate.py\n...\n```"},
        {"role": "tool", "content": "迁移成功", "name": "run_sql", "tool_call_id": "call_1"},
        {"role": "user", "content": "下一步做什么？"},
    ]
    
    compressor = ContextCompressor()
    result = compressor.compress(test_history)
    print(f"压缩比: {result.compression_ratio}x")
    print(f"用户消息保留: {len(result.user_messages)}条")
    print(f"关键决策: {len(result.key_decisions)}条")
    print(f"代码变更: {len(result.code_changes)}条")
    print(f"工具调用: {len(result.tool_call_trail)}条")
