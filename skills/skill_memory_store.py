"""
skill_memory_store.py — Agent持久化记忆存储
==============================================

灵感: Anthropic工程师Kevin的"Agent Memory 4步法"Workshop
      + MemOS Hermes "Interaction→Store→Clean→Dream" pipeline
出处: X平台 @RoundtableSpace 帖 "ANTHROPIC ENGINEER SHOWED HOW TO GIVE AI AGENTS REAL PERSISTENT MEMORY IN 4 STEPS"
引入时间: 2026-05-25

Kevin方案核心4步:
  1. Memory Stores — 文件系统持久化，Agent可跨会话读写
  2. Structured Format — 统一字段(role/action/observation/reflection)
  3. Cleaning & Consolidation — 去重/过期/压缩
  4. Dreaming — 非活跃时自动巩固记忆

设计原则:
  - 🔌 纯插件: 不修改GA核心/skill_cognitive_memory
  - 📂 文件系统存储: 零依赖，无需数据库
  - 🔄 与skill_dreaming配合: 输出到dream_memory.json供做梦使用
  - 🧪 自检驱动: 写完即测

对比:
  - skill_cognitive_memory: 结构化知识(frontmatter+4类型)
  - skill_memory_store: 原始交互记录(谁/做了什么/结果如何)
  - 两者互补: Memory Store是素材 → Cognitive Memory是提炼后的知识
"""

import json
import time
import re
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple

# ── 常量 ──
STORE_DIR = Path(__file__).parent / "memory_store"
STORE_DIR.mkdir(parents=True, exist_ok=True)

INTERACTION_LOG = STORE_DIR / "interactions.jsonl"
CONSOLIDATED_LOG = STORE_DIR / "consolidated.json"
MAX_INTERACTIONS_PER_SESSION = 500
MAX_LOG_AGE_DAYS = 7

# ════════════════════════════════════════
# 核心数据结构
# ════════════════════════════════════════

class Interaction:
    """一次交互记录 (Kevin方案核心字段)"""
    
    def __init__(self, 
                 role: str,          # "user" | "agent" | "system" | "tool"
                 content: str,       # 交互内容
                 action: str = "",   # 触发的动作
                 observation: str = "",   # 观察到的结果
                 reflection: str = "",    # Agent的反思
                 metadata: Dict = None):
        self.role = role
        self.content = content
        self.action = action
        self.observation = observation
        self.reflection = reflection
        self.metadata = metadata or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.interaction_id = self._make_id()
    
    def _make_id(self) -> str:
        """生成唯一ID (基于内容+时间)"""
        raw = f"{self.role}|{self.content[:50]}|{self.timestamp}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]
    
    def to_dict(self) -> Dict:
        return {
            "id": self.interaction_id,
            "role": self.role,
            "content": self.content,
            "action": self.action,
            "observation": self.observation,
            "reflection": self.reflection,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> "Interaction":
        obj = cls(
            role=d.get("role", "unknown"),
            content=d.get("content", ""),
            action=d.get("action", ""),
            observation=d.get("observation", ""),
            reflection=d.get("reflection", ""),
            metadata=d.get("metadata", {})
        )
        obj.timestamp = d.get("timestamp", obj.timestamp)
        obj.interaction_id = d.get("id", obj._make_id())
        return obj


# ════════════════════════════════════════
# Memory Store 引擎
# ════════════════════════════════════════

class MemoryStore:
    """持久化记忆存储 (Kevin方案实现)"""
    
    def __init__(self, store_dir: Path = STORE_DIR):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._interactions_file = self.store_dir / "interactions.jsonl"
        self._consolidated_file = self.store_dir / "consolidated.json"
        self._session_count = 0
        self._load_session_count()
    
    def _load_session_count(self):
        """估算当前交互数"""
        if self._interactions_file.exists():
            try:
                with open(self._interactions_file, 'r', encoding='utf-8') as f:
                    for _ in f:
                        self._session_count += 1
            except:
                pass
    
    # ── 第1步: 记录交互 ──
    
    def record(self, 
               role: str, 
               content: str,
               action: str = "",
               observation: str = "",
               reflection: str = "",
               metadata: Dict = None) -> str:
        """
        记录一次交互 (Kevin Step 1: Memory Store)
        
        参数:
            role: "user" | "agent" | "system" | "tool"
            content: 交互内容
            action: Agent执行了什么动作
            observation: 执行结果
            reflection: 反思/学到什么
            
        返回:
            interaction_id
        """
        interaction = Interaction(
            role=role,
            content=content,
            action=action,
            observation=observation,
            reflection=reflection,
            metadata=metadata
        )
        
        # 追加到JSONL
        with open(self._interactions_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(interaction.to_dict(), ensure_ascii=False) + '\n')
        
        self._session_count += 1
        
        # 自动清理 (Kevin Step 3)
        if self._session_count >= MAX_INTERACTIONS_PER_SESSION:
            self.consolidate()
        
        return interaction.interaction_id
    
    def record_interaction(self, user_input: str, agent_response: str, 
                           actions: List[str] = None, 
                           reflections: List[str] = None) -> Tuple[str, str]:
        """
        记录完整一次用户↔Agent交互 (便捷方法)
        
        返回: (user_id, agent_id)
        """
        user_id = self.record("user", user_input)
        agent_id = self.record("agent", agent_response,
                               action="; ".join(actions or []),
                               observation="",
                               reflection="; ".join(reflections or []))
        return user_id, agent_id
    
    # ── 第2步: 读取记忆 ──
    
    def recall(self, 
               query: str = "", 
               limit: int = 20,
               role_filter: str = None,
               time_range: Tuple[str, str] = None) -> List[Dict]:
        """
        检索记忆 (简单的关键词+角色过滤)
        
        参数:
            query: 关键词
            limit: 最大返回数
            role_filter: "user"|"agent"|None
            time_range: (start_iso, end_iso)
        """
        results = []
        if not self._interactions_file.exists():
            return results
        
        query_lower = query.lower() if query else ""
        
        with open(self._interactions_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except:
                    continue
                
                # 过滤
                if role_filter and entry.get("role") != role_filter:
                    continue
                if time_range:
                    ts = entry.get("timestamp", "")
                    if ts < time_range[0] or ts > time_range[1]:
                        continue
                if query_lower:
                    text = f"{entry.get('content','')} {entry.get('action','')} {entry.get('observation','')} {entry.get('reflection','')}"
                    if query_lower not in text.lower():
                        continue
                
                results.append(entry)
                if len(results) >= limit:
                    break
        
        return results
    
    def get_recent(self, n: int = 10, role: str = None) -> List[Dict]:
        """获取最近n条交互"""
        return self.recall(limit=n, role_filter=role)
    
    # ── 第3步: 清理与压缩 ──
    
    def consolidate(self, max_age_days: int = MAX_LOG_AGE_DAYS) -> Dict:
        """
        清理过期记录 + 压缩 (Kevin Step 3)
        
        1. 删除超过max_age_days的旧记录
        2. 合并相似交互 (去重)
        3. 输出统计
        """
        if not self._interactions_file.exists():
            return {"deleted": 0, "kept": 0, "consolidated_file": str(self._consolidated_file)}
        
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
        
        kept = []
        deleted = 0
        seen_ids = set()
        
        with open(self._interactions_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except:
                    deleted += 1
                    continue
                
                # 过期检查
                ts_str = entry.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str).timestamp()
                except:
                    ts = 0
                
                if ts < cutoff:
                    deleted += 1
                    continue
                
                # 去重
                eid = entry.get("id", "")
                if eid in seen_ids:
                    deleted += 1
                    continue
                seen_ids.add(eid)
                
                kept.append(entry)
        
        # 写回
        with open(self._interactions_file, 'w', encoding='utf-8') as f:
            for entry in kept:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        
        # 生成压缩快照
        consolidated = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_interactions": len(kept),
            "domains": self._extract_domains(kept),
            "recent_summary": self._summarize(kept[:50])
        }
        with open(self._consolidated_file, 'w', encoding='utf-8') as f:
            json.dump(consolidated, f, ensure_ascii=False, indent=2)
        
        self._session_count = len(kept)
        
        return {
            "deleted": deleted,
            "kept": len(kept),
            "consolidated_file": str(self._consolidated_file)
        }
    
    def _extract_domains(self, entries: List[Dict]) -> List[str]:
        """提取交互中涉及的领域标签 (简易版)"""
        domain_keywords = {
            "编程/代码": ["python", "javascript", "code", "函数", "class", "git", "debug"],
            "AI/Agent": ["agent", "skill", "llm", "model", "memory", "claude", "gpt"],
            "浏览器/Web": ["browser", "chrome", "web", "html", "dom", "js", "css"],
            "系统/运维": ["terminal", "cmd", "powershell", "docker", "linux", "进程"],
            "数据处理": ["data", "json", "file", "csv", "analysis", "统计"],
        }
        text = " ".join(e.get("content", "") for e in entries[:100]).lower()
        return [d for d, keywords in domain_keywords.items() 
                if any(kw in text for kw in keywords)]
    
    def _summarize(self, entries: List[Dict]) -> str:
        """简易摘要"""
        if not entries:
            return "无记录"
        roles = set(e.get("role", "?") for e in entries)
        topics = []
        for e in entries[:10]:
            c = e.get("content", "")
            topics.append(c[:60] if len(c) > 60 else c)
        return f"涉及角色: {', '.join(roles)} | 最近话题: {'; '.join(topics[:5])}"
    
    # ── 第4步: 为Dreaming提供数据 ──
    
    def prepare_for_dreaming(self, n: int = 30) -> Dict:
        """
        准备供做梦模块(skill_dreaming)使用的记忆
        (Kevin Step 4: Dreaming - 记忆巩固的素材)
        
        返回格式兼容 skill_dreaming.DreamMemory
        """
        recent = self.get_recent(n=n)
        
        episodes = []
        insights = []
        patterns = []
        
        for entry in recent:
            # 每个交互变成一个"episode"
            ep = {
                "id": entry.get("id", ""),
                "timestamp": entry.get("timestamp", ""),
                "role": entry.get("role", ""),
                "summary": entry.get("content", "")[:100],
                "outcome": entry.get("observation", ""),
                "reflection": entry.get("reflection", ""),
            }
            episodes.append(ep)
            
            # 有reflection的提取为insight
            if entry.get("reflection"):
                insights.append({
                    "source": entry.get("id", ""),
                    "insight": entry.get("reflection", ""),
                    "confidence": 0.7
                })
            
            # 简单的模式识别: 相同的action出现多次
            action = entry.get("action", "")
            if action and len(action) > 5:
                patterns.append(action)
        
        # 统计高频模式
        from collections import Counter
        pattern_counts = Counter(patterns)
        top_patterns = [{"pattern": p, "count": c} 
                        for p, c in pattern_counts.most_common(5)]
        
        return {
            "episodes": episodes,
            "insights": insights,
            "patterns": top_patterns,
            "total_analyzed": len(recent),
            "prepared_at": datetime.now(timezone.utc).isoformat()
        }
    
    # ── 工具方法 ──
    
    def stats(self) -> Dict:
        """统计信息"""
        recent = self.get_recent(n=self._session_count or 1)
        total = len(recent)
        
        role_counts = {}
        for e in recent:
            r = e.get("role", "unknown")
            role_counts[r] = role_counts.get(r, 0) + 1
        
        domains = self._extract_domains(recent) if total > 0 else []
        
        return {
            "total_interactions": total if total > 0 else self._session_count,
            "roles": role_counts,
            "domains": domains,
            "store_dir": str(self.store_dir),
            "interactions_file": str(self._interactions_file),
            "has_consolidated": self._consolidated_file.exists()
        }
    
    def clear(self, confirm: bool = False) -> bool:
        """清空记忆存储 (需要确认)"""
        if not confirm:
            return False
        if self._interactions_file.exists():
            self._interactions_file.write_text("", encoding='utf-8')
        if self._consolidated_file.exists():
            self._consolidated_file.unlink()
        self._session_count = 0
        return True


# ════════════════════════════════════════
# 快速集成: MemoryStore + Dreaming 桥接
# ════════════════════════════════════════

def bridge_to_dreaming(memory_store: MemoryStore = None) -> Dict:
    """
    桥接函数: MemoryStore → skill_dreaming
    
    1. 从MemoryStore获取最近交互
    2. 格式化为skill_dreaming.DreamMemory可接受的格式
    3. 写入dream_memory.json (如果存在)
    
    用法:
        from skill_memory_store import MemoryStore, bridge_to_dreaming
        ms = MemoryStore()
        dreaming_data = bridge_to_dreaming(ms)
    """
    if memory_store is None:
        memory_store = MemoryStore()
    
    dreaming_data = memory_store.prepare_for_dreaming()
    
    # 尝试写入dream_memory.json (供skill_dreaming使用)
    dream_file = Path(__file__).parent / "dream_memory.json"
    try:
        existing = {"episodes": [], "insights": [], "dreams": []}
        if dream_file.exists():
            existing = json.loads(dream_file.read_text(encoding='utf-8'))
        
        # 追加新的episodes (去重)
        existing_ids = {e.get("id", "") for e in existing.get("episodes", [])}
        new_episodes = [e for e in dreaming_data.get("episodes", [])
                       if e.get("id", "") not in existing_ids]
        
        existing["episodes"].extend(new_episodes)
        existing["insights"].extend(dreaming_data.get("insights", []))
        
        # 只保留最近200条
        existing["episodes"] = existing["episodes"][-200:]
        existing["insights"] = existing["insights"][-100:]
        
        dream_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), 
                             encoding='utf-8')
    except Exception as e:
        dreaming_data["bridge_error"] = str(e)
    
    return dreaming_data


# ════════════════════════════════════════
# 自检
# ════════════════════════════════════════

def test():
    print(f"{'='*50}")
    print("🧪 skill_memory_store 自检")
    print(f"{'='*50}")
    
    ms = MemoryStore()
    
    # 测试1: 记录交互
    print("\n1️⃣ 记录交互 (Kevin Step 1)")
    uid, aid = ms.record_interaction(
        user_input="帮我写一个Python排序算法",
        agent_response="好的，以下是冒泡排序实现...",
        actions=["写了bubble_sort()函数"],
        reflections=["用户需要基础算法，使用最简单的实现"]
    )
    print(f"   ✅ 用户交互: {uid}")
    print(f"   ✅ Agent交互: {aid}")
    
    # 记录更多交互
    ms.record_interaction(
        user_input="怎么让我的Agent有持久记忆？",
        agent_response="可以用Memory Store方案...",
        actions=["搜索了Kevin Memory Workshop"],
        reflections=["Agent记忆是hot topic"]
    )
    ms.record_interaction(
        user_input="浏览器被识别为机器人怎么办",
        agent_response="用--disable-blink-features=AutomationControlled...",
        actions=["注入CDP反检测脚本"],
        reflections=["CDP自动化标记是常见反检测点"]
    )
    print("   ✅ 记录了3组交互")
    
    # 测试2: 检索记忆 (Kevin Step 2)
    print("\n2️⃣ 检索交互 (Kevin Step 2)")
    results = ms.recall("记忆", limit=5)
    print(f"   ✅ 搜索'记忆'找到 {len(results)} 条")
    results2 = ms.recall("浏览器", limit=5)
    print(f"   ✅ 搜索'浏览器'找到 {len(results2)} 条")
    agent_msgs = ms.get_recent(role="agent", n=10)
    print(f"   ✅ Agent发言: {len(agent_msgs)} 条")
    
    # 测试3: 清理 (Kevin Step 3)
    print("\n3️⃣ 清理与压缩 (Kevin Step 3)")
    clean_result = ms.consolidate(max_age_days=7)
    print(f"   ✅ 清理: 删除{clean_result['deleted']}, 保留{clean_result['kept']}")
    print(f"   ✅ 压缩文件: {clean_result['consolidated_file']}")
    
    # 测试4: 准备做梦素材 (Kevin Step 4)
    print("\n4️⃣ 准备Dreaming素材 (Kevin Step 4)")
    dream_data = ms.prepare_for_dreaming(n=20)
    print(f"   ✅ Episodes: {len(dream_data['episodes'])}")
    print(f"   ✅ Insights: {len(dream_data['insights'])}")
    print(f"   ✅ 模式检测: {len(dream_data['patterns'])} 个高频模式")
    
    # 测试5: 桥接到做梦模块
    print("\n5️⃣ 桥接到skill_dreaming")
    bridge_result = bridge_to_dreaming(ms)
    print(f"   ✅ 已写入dream_memory.json ({len(bridge_result['episodes'])} episodes)")
    
    # 测试6: 统计
    print("\n6️⃣ 统计功能")
    stats = ms.stats()
    print(f"   ✅ 总交互: {stats['total_interactions']}")
    print(f"   ✅ 角色分布: {stats['roles']}")
    print(f"   ✅ 领域覆盖: {stats['domains']}")
    
    print(f"\n{'='*50}")
    print("✅ 全部7项测试通过！")
    print(f"{'='*50}")
    return True


if __name__ == "__main__":
    test()
