"""
skill_ga_self_improve_v1.py — GA自改进闭环 (P3核心)

骨髓内化:
  - Hermes Agent: 技能即知识、WAL协议、跨会话检索
  - Lobster: 反向Prompt、3次失败换策略
  - GA已有的: ga_autonomous_engine的5阶段、daemon的心跳

核心能力:
  1. 会话结束时反思+技能创建 (WAL协议)
  2. 跨会话检索L4 session找未完成任务
  3. 启动时自检sche_task + 到期复习

用法:
  from memory.skill_ga_self_improve_v1 import SelfImprover
  improver = SelfImprover()
  improver.reflect(task, actions, outcomes) -> skill_path or None
"""

import os
import json
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

# ── 路径 ──
BASE = Path(r"C:\Users\Administrator\my-agent")
MEMORY = BASE / "memory"
TEMP = BASE / "temp"
L4_DIR = MEMORY / "L4_raw_sessions"
WAL_FILE = MEMORY / "wal_log.json"
SKILL_DIR = MEMORY
AUTO_DIR = MEMORY / "auto"

# ── 常量 ──
MAX_REFLECT_LINES = 15
MIN_TURNS_FOR_SKILL = 3


class SelfImprover:
    """
    自改进闭环: 反射 + WAL + 技能创建 + 跨会话检索。
    
    核心日志(WAL): {'type': 'reflect'|'skill_created'|'skill_improved',
                     'timestamp': ..., 'task': ..., 'soul': ...}
    """
    
    def __init__(self):
        self._recent_skills: List[str] = []
        self._init_dirs()
        self._wal = self._load_wal()
    
    def _init_dirs(self):
        """确保目录存在"""
        AUTO_DIR.mkdir(parents=True, exist_ok=True)
    
    # ═══════════════════════════════════════════════════
    # WAL 协议 (Write-Ahead Log)
    # ═══════════════════════════════════════════════════
    
    def _load_wal(self) -> List[Dict]:
        if WAL_FILE.exists():
            try:
                with open(WAL_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, Exception):
                return []
        return []
    
    def _save_wal(self):
        with open(WAL_FILE, "w", encoding="utf-8") as f:
            json.dump(self._wal, f, indent=2, ensure_ascii=False)
    
    def log_wal(self, entry_type: str, task: str, soul: str = ""):
        """写WAL条目"""
        entry = {
            "type": entry_type,
            "timestamp": datetime.now().isoformat(),
            "task": task[:200],
            "soul": soul[:500],
        }
        self._wal.append(entry)
        if len(self._wal) > 200:
            self._wal = self._wal[-200:]
        self._save_wal()
    
    def get_recent_wal(self, n: int = 20) -> List[Dict]:
        """最近WAL条目"""
        return self._wal[-n:]
    
    # ═══════════════════════════════════════════════════
    # 反射与技能创建
    # ═══════════════════════════════════════════════════
    
    def reflect(self, task: str, 
                actions: List[str], 
                outcomes: List[str],
                turn_count: int = 0,
                evaluation: Optional[Dict] = None) -> Optional[str]:
        """
        反射会话→决定是否创建技能。
        
        Args:
            task: 任务描述
            actions: 执行动作列表（前MAX_REFLECT_LINE条）
            outcomes: 结果列表
            turn_count: 总轮数（低于MIN_TURNS_FOR_SKILL不创建）
            evaluation: 评估结果（可选）
        
        Returns:
            skill_path: 技能文件路径，若创建则返回；否则None
        """
        if turn_count < MIN_TURNS_FOR_SKILL:
            return None
        
        passed = evaluation.get("passed", False) if evaluation else True
        
        # 写入反射日志
        reflection = {
            "task": task,
            "turn_count": turn_count,
            "passed": passed,
            "actions": actions[:MAX_REFLECT_LINES],
            "outcomes": outcomes[:MAX_REFLECT_LINES],
            "timestamp": datetime.now().isoformat(),
        }
        
        ref_id = hashlib.md5(f"{task}{time.time()}".encode()).hexdigest()[:8]
        ref_path = AUTO_DIR / f"reflection_{ref_id}.json"
        with open(ref_path, "w", encoding="utf-8") as f:
            json.dump(reflection, f, indent=2, ensure_ascii=False)
        
        self.log_wal("reflect", task, f"ref_id={ref_id}, passed={passed}")
        
        # 判断是否需要创建技能
        if passed and turn_count >= 5:
            return self._create_skill(task, actions, outcomes, ref_id)
        
        return None
    
    def _create_skill(self, task: str, actions: List[str], 
                      outcomes: List[str], ref_id: str) -> str:
        """创建技能文件"""
        skill_name = self._name_skill(task)
        skill_path = SKILL_DIR / skill_name
        
        lines = [
            f"# skill_{skill_name} — GA自创建技能",
            f"> 来源: 自改进闭环 ref_id={ref_id}",
            f"> 创建: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"> 来源任务: {task}",
            "",
            f"## 步骤",
        ]
        for i, a in enumerate(actions[:10], 1):
            lines.append(f"{i}. {a}")
        
        if outcomes:
            lines.append("")
            lines.append("## 结果")
            for o in outcomes[:5]:
                lines.append(f"- {o}")
        
        lines.append("")
        lines.append("## 使用方式")
        lines.append("需要时，运行 `from memory.skill_ga_self_improve_v1 import SelfImprover`")
        lines.append("或直接引用本文档的步骤")
        
        content = "\n".join(lines)
        
        # 避免重复创建同名技能
        count = 1
        final_path = skill_path
        while final_path.exists():
            count += 1
            final_path = SKILL_DIR / f"{skill_name}_{count}.md"
        
        with open(final_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        self._recent_skills.append(str(final_path))
        self.log_wal("skill_created", str(final_path), f"ref_id={ref_id}")
        
        return str(final_path)
    
    @staticmethod
    def _name_skill(task: str) -> str:
        """从任务描述生成技能文件名"""
        # 取前20字，去特殊字符
        import re
        name = task[:30]
        name = re.sub(r'[\\/*?:"<>|]', '', name)
        name = re.sub(r'\s+', '_', name.strip())
        return f"skill_auto_{name[:20]}.md"
    
    # ═══════════════════════════════════════════════════
    # 跨会话检索
    # ═══════════════════════════════════════════════════
    
    def find_unfinished_sessions(self) -> List[Dict]:
        """
        扫描L4_raw_sessions找最近24h内未闭环的会话。
        返回列表: [{file, task_summary, last_modified}]
        """
        if not L4_DIR.exists():
            return []
        
        unfinished = []
        now = time.time()
        cutoff = now - 86400  # 24h
        
        for f in sorted(L4_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
            if f.stat().st_mtime < cutoff:
                continue
            
            # 读文件头和尾判断是否已闭环
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                lines = content.split("\n")
                
                # 取前3行和后5行看状态
                head = "\n".join(lines[:5])
                tail = "\n".join(lines[-10:])
                
                # 检查是否已闭环
                closed_markers = ["闭环完成", "✅ 全部通过", "已验证通过", "push成功", 
                                  "mission completed", "备份完成", "全局记忆已更新"]
                is_closed = any(m in tail for m in closed_markers)
                
                if not is_closed:
                    # 提取摘要
                    task_summary = ""
                    for line in lines[:20]:
                        if "任务" in line or "开始" in line or "用户" in line:
                            task_summary = line[:100]
                            break
                    
                    unfinished.append({
                        "file": f.name,
                        "task_summary": task_summary or head[:80],
                        "last_modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    })
            except Exception:
                continue
        
        return unfinished
    
    def get_skill_count(self) -> Dict[str, int]:
        """统计技能文件"""
        skills = list(MEMORY.glob("skill_*.md")) + list(MEMORY.glob("skill_*.py"))
        return {
            "total": len(skills),
            "recent": len(self._recent_skills),
            "wal_entries": len(self._wal),
        }
    
    def get_next_action_hint(self) -> Optional[str]:
        """
        基于WAL+L4扫描，返回下一步建议。
        用于注入到next_prompt中让GA自己决定。
        """
        hints = []
        
        # 1. 检查未完成任务
        unfinished = self.find_unfinished_sessions()
        if unfinished:
            top = unfinished[0]
            hints.append(f"📋 发现未完成任务: {top['task_summary'][:60]}")
            hints.append(f"   看 {top['file']} 继续推进")
        
        # 2. 检查WAL中有无要改进的技能
        skill_entries = [e for e in self._wal if e["type"] == "skill_created"]
        if len(skill_entries) >= 3:
            hints.append(f"🧠 已有{len(skill_entries)}个自建技能，考虑复习/优化")
        
        # 3. 检查技能总数
        stats = self.get_skill_count()
        if stats["total"] < 5:
            hints.append(f"🏗️ 技能库只有{stats['total']}项，建议探索新项目创建技能")
        
        return "\n".join(hints) if hints else None
    
    def check_and_improve(self) -> Dict[str, Any]:
        """
        完整自检：查找未完成任务 + 刷新WAL + 返回决策
        设计为 startup_selfcheck_sop 的主要执行体
        """
        result = {
            "unfinished": self.find_unfinished_sessions(),
            "wal_count": len(self._wal),
            "skill_count": self.get_skill_count(),
            "hint": self.get_next_action_hint(),
        }
        self.log_wal("selfcheck", "", f"unfinished={len(result['unfinished'])}, skills={result['skill_count']['total']}")
        return result


# ═══════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════

_improver = None
def get_improver() -> SelfImprover:
    global _improver
    if _improver is None:
        _improver = SelfImprover()
    return _improver


# ═══════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    imp = SelfImprover()
    
    # 测试1: 创建反射日志
    print("=" * 60)
    print("📋 测试1: 反射")
    result = imp.reflect(
        task="学习Hermes Agent架构做GA注入",
        actions=[
            "读README了解架构",
            "分析agent目录源码",
            "对比GA现有模块",
        ],
        outcomes=[
            "理解了自改进闭环",
            "找到了注入点game_plugin",
        ],
        turn_count=5,
        evaluation={"passed": True, "pass_rate": 0.85},
    )
    if result:
        print(f"  ✅ 技能创建: {result}")
    else:
        print("  ⏭️ 轮次不足，未创建技能")
    
    # 测试2: 跨会话检索
    print("\n" + "=" * 60)
    print("📋 测试2: 跨会话检索")
    unfinished = imp.find_unfinished_sessions()
    print(f"  发现 {len(unfinished)} 个未完成任务")
    for u in unfinished[:3]:
        print(f"    - {u['file']}: {u['task_summary'][:50]}")
    
    # 测试3: 自检
    print("\n" + "=" * 60)
    print("📋 测试3: 自检")
    check = imp.check_and_improve()
    print(f"  WAL条目: {check['wal_count']}")
    print(f"  技能统计: {check['skill_count']}")
    if check['hint']:
        print(f"  下一步提示:\n{check['hint']}")
    
    # 测试4: WAL持久化
    print("\n" + "=" * 60)
    print("📋 测试4: WAL持久化")
    recent = imp.get_recent_wal(5)
    print(f"  最近 {len(recent)} 条WAL")
    for r in recent[-3:]:
        print(f"    [{r['type']}] {r['task'][:40]}")
    
    print("\n" + "=" * 60)
    print("✅ 自改进闭环就绪!")
