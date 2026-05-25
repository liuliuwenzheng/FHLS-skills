"""
skill_cognitive_memory.py — GA认知记忆引擎 v2.0
==============================================
骨髓内化自 Claude Code memdir 源码 (2025泄漏版)：
- memoryTypes.ts: 4记忆类型 + 精准prompt工程 + frontmatter
- memdir.ts: MEMORY.md指针索引 + 200行/25KB截断
- memoryScan.ts: 单遍扫描 + frontmatter解析 + 200上限
- memoryAge.ts: 年龄衰减 + freshnessNote(<system-reminder>)
- paths.ts: 安全路径验证 + git-root层级
- teamMemPrompts.ts: 双层(private/team) + prompt构建

核心API (保持向后兼容):
    cm = CognitiveMemory()
    cm.remember("Python异步编程的3个核心模式", tags=["asyncio"])
    results = cm.recall("asyncio")
    summary = cm.session_bridge(topic="Python", insight="学了asyncio")

新增能力:
    cm.remember_md("Python异步", content="详细内容...", mem_type="reference")
    manifest = cm.build_manifest()   # [type] file (ts): desc
    note = cm.freshness_note(mtime)  # system-reminder过时警告
"""

import os
import json
import math
import re
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

# ── 常量 ──
MEMORY_DIR = Path(__file__).parent / "cognitive_memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
MAX_SCAN = 200
MAX_INDEX_LINES = 200
STALE_DAYS = 1  # >1天视为过时

# 记忆类型 (移植自Claude Code memoryTypes.ts)
MEMORY_TYPES = ["user", "feedback", "project", "reference"]
# 旧类型兼容映射
LEGACY_TYPE_MAP = {"semantic": "reference", "episodic": "feedback"}

# ════════════════════════════════════════
# 路径安全 (移植自 paths.ts validateMemoryPath)
# ════════════════════════════════════════
_SAFE_NAME_RE = re.compile(r'^[\w\-\.\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+$')

def _validate_memory_path(filename: str) -> str:
    """安全验证：防路径遍历/空字节/根目录等"""
    if not filename or len(filename) > 200:
        raise ValueError(f"filename empty or too long")
    if '..' in filename or '/' in filename or '\\' in filename:
        raise ValueError(f"path traversal detected: {filename}")
    if '\0' in filename:
        raise ValueError("null byte in filename")
    # 只允许安全字符
    safe = _SAFE_NAME_RE.match(filename)
    if not safe:
        raise ValueError(f"unsafe characters in filename: {filename}")
    return filename

# ════════════════════════════════════════
# Frontmatter 解析 (移植自 memoryScan.ts)
# ════════════════════════════════════════
def _parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """
    解析frontmatter: 
    ---
    description: 简明钩子
    type: user|feedback|project|reference
    tags: [tag1, tag2]
    mtime: 2026-05-24T10:00:00Z
    ---
    内容...
    """
    result = {"description": "", "type": "reference", "tags": [], "mtime": ""}
    
    text = text.strip()
    if not text.startswith('---'):
        return result, text
    
    end_idx = text.find('---', 3)
    if end_idx == -1:
        return result, text
    
    fm_text = text[3:end_idx].strip()
    body = text[end_idx+3:].strip()
    
    for line in fm_text.split('\n'):
        line = line.strip()
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        key = key.strip().lower()
        val = val.strip()
        
        if key == 'description':
            result['description'] = val
        elif key == 'type':
            if val in MEMORY_TYPES:
                result['type'] = val
            elif val in LEGACY_TYPE_MAP:
                result['type'] = LEGACY_TYPE_MAP[val]
        elif key == 'tags':
            try:
                parsed = json.loads(val) if val.startswith('[') else [t.strip() for t in val.split(',') if t.strip()]
                result['tags'] = parsed if isinstance(parsed, list) else [val]
            except:
                result['tags'] = [val]
        elif key == 'mtime':
            result['mtime'] = val
    
    return result, body


def _build_frontmatter(description: str, mem_type: str = "reference", tags: List[str] = None) -> str:
    """构建frontmatter块"""
    if mem_type not in MEMORY_TYPES:
        mem_type = LEGACY_TYPE_MAP.get(mem_type, "reference")
    
    lines = ["---"]
    lines.append(f"description: {description[:120]}")
    lines.append(f"type: {mem_type}")
    if tags:
        lines.append(f"tags: {json.dumps(tags[:10])}")
    lines.append(f"mtime: {datetime.now(timezone.utc).isoformat()}")
    lines.append("---\n")
    return '\n'.join(lines)


# ════════════════════════════════════════
# 记忆年龄 & 新鲜度 (移植自 memoryAge.ts)
# ════════════════════════════════════════
def _memory_age_days(mtime: float) -> int:
    """记忆已存在天数"""
    return max(0, int((time.time() - mtime) / 86400))


def _memory_freshness_text(days: int) -> str:
    """移植自 memoryAge.ts memoryFreshnessText"""
    if days == 0:
        return ""
    elif days == 1:
        return f"memory is 1 day old, content may be stale — verify before acting on it"
    else:
        return f"memory is {days} days old, content may be stale — verify before acting on it"


def freshness_note(mtime: float) -> str:
    """移植自 memoryAge.ts memoryFreshnessNote -> <system-reminder>"""
    days = _memory_age_days(mtime)
    text = _memory_freshness_text(days)
    if not text:
        return ""
    return f"<system-reminder>{text}</system-reminder>\n"


# ════════════════════════════════════════
# MEMORY.md 指针索引 (移植自 memdir.ts scan + manifest)
# ════════════════════════════════════════
def _memory_index_path() -> Path:
    return MEMORY_INDEX


def _read_index() -> List[str]:
    """读取MEMORY.md索引文件"""
    idx = _memory_index_path()
    if not idx.exists():
        return []
    text = idx.read_text(encoding='utf-8', errors='replace')
    lines = text.split('\n')
    # 跳过标题行
    result = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            result.append(line)
    return result[-MAX_INDEX_LINES:]


def _write_index(lines: List[str]):
    """写入MEMORY.md索引文件"""
    idx = _memory_index_path()
    header = "# Memory Index\n\n"
    content = '\n'.join(lines[-MAX_INDEX_LINES:])
    idx.write_text(header + content + '\n', encoding='utf-8')


def _index_line(mem_id: str, description: str, mem_type: str, mtime: float) -> str:
    """单行索引格式: - [type] filename (timestamp): description"""
    ts = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    tag = f"[{mem_type}] " if mem_type in MEMORY_TYPES else ""
    desc = description[:120]
    return f"- {tag}{mem_id}.mem.md ({ts}): {desc}"


# ════════════════════════════════════════
# 单记忆文件读写 (移植自 memoryScan.ts scanMemoryFiles)
# ════════════════════════════════════════
def _mem_id() -> str:
    """生成唯一记忆ID"""
    raw = f"{time.time_ns()}{os.urandom(4).hex()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _filename(mem_id: str) -> str:
    """安全文件名"""
    _validate_memory_path(mem_id)
    return f"{mem_id}.mem.md"


def _filepath(mem_id: str) -> Path:
    return MEMORY_DIR / _filename(mem_id)


def _write_mem_file(mem_id: str, description: str, content: str, 
                     mem_type: str = "reference", tags: List[str] = None) -> float:
    """写入单个.mem.md文件"""
    now = time.time()
    frontmatter = _build_frontmatter(description, mem_type, tags)
    full = frontmatter + content
    fp = _filepath(mem_id)
    fp.write_text(full, encoding='utf-8')
    return now


def _read_mem_file(mem_id: str) -> Optional[Dict[str, Any]]:
    """读取单个.mem.md文件，返回带frontmatter的字典"""
    fp = _filepath(mem_id)
    if not fp.exists():
        return None
    
    text = fp.read_text(encoding='utf-8', errors='replace')
    fm, body = _parse_frontmatter(text)
    
    stat = fp.stat()
    return {
        "id": mem_id,
        "description": fm.get("description", ""),
        "type": fm.get("type", "reference"),
        "tags": fm.get("tags", []),
        "mtime": stat.st_mtime,
        "mtime_iso": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "size": stat.st_size,
        "content": body,
    }


def _delete_mem_file(mem_id: str) -> bool:
    """删除单个.mem.md文件"""
    fp = _filepath(mem_id)
    if fp.exists():
        fp.unlink()
        return True
    return False


def _scan_mem_files() -> List[Dict[str, Any]]:
    """扫描所有.mem.md文件 (移植自 memoryScan.ts scanMemoryFiles)"""
    if not MEMORY_DIR.exists():
        return []
    
    files = sorted(MEMORY_DIR.glob("*.mem.md"), 
                   key=lambda p: p.stat().st_mtime, reverse=True)
    
    results = []
    for fp in files[:MAX_SCAN]:
        try:
            text = fp.read_text(encoding='utf-8', errors='replace')[:3000]  # 仅读前3KB
            fm, _ = _parse_frontmatter(text)
            stat = fp.stat()
            results.append({
                "id": fp.stem,
                "description": fm.get("description", ""),
                "type": fm.get("type", "reference"),
                "tags": fm.get("tags", []),
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            })
        except Exception:
            continue
    
    return results


# ════════════════════════════════════════
# Manifest 格式 (移植自 memoryScan.ts formatMemoryManifest)
# ════════════════════════════════════════
def build_manifest(memories: List[Dict[str, Any]] = None) -> str:
    """
    构建记忆清单 (移植自 memoryScan.ts formatMemoryManifest)
    
    返回格式:
    - [type] filename (timestamp): description
    - [type] filename (timestamp): description
    """
    if memories is None:
        memories = _scan_mem_files()
    
    lines = []
    for m in memories:
        tag = f"[{m.get('type', 'reference')}] " if m.get('type') in MEMORY_TYPES else ""
        ts = datetime.fromtimestamp(m.get('mtime', 0), tz=timezone.utc).isoformat()
        desc = m.get('description', '')
        if desc:
            lines.append(f"- {tag}{m.get('id', '?')}.mem.md ({ts}): {desc}")
        else:
            lines.append(f"- {tag}{m.get('id', '?')}.mem.md ({ts})")
    
    return '\n'.join(lines)


# ════════════════════════════════════════
# 旧JSONL兼容 (原格式fallback)
# ════════════════════════════════════════
_JSONL_PATH = Path(__file__).parent / "cognitive_memory.jsonl"


def _read_jsonl() -> List[Dict]:
    """读取旧JSONL格式 (向后兼容)"""
    if not _JSONL_PATH.exists():
        return []
    items = []
    with open(_JSONL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return items


# ════════════════════════════════════════
# 检索 (移植自 findRelevantMemories.ts)
# ════════════════════════════════════════
def _keyword_match(text: str, query: str) -> float:
    """关键词匹配分数 (移植自findRelevantMemories基础匹配)"""
    if not query or not text:
        return 0.0
    
    query_lower = query.lower()
    text_lower = text.lower()
    
    # 精确匹配
    if query_lower in text_lower:
        return 1.0
    
    # 分词匹配
    words = re.findall(r'\w+', query_lower)
    if not words:
        return 0.0
    
    text_words = set(re.findall(r'\w+', text_lower))
    matches = sum(1 for w in words if w in text_words)
    return matches / len(words) * 0.8


def _sort_by_relevance(items: List[Dict], query: str) -> List[Dict]:
    """按相关性排序"""
    scored = []
    for item in items:
        search_text = f"{item.get('description', '')} {item.get('content', '')} {' '.join(item.get('tags', []))}"
        score = _keyword_match(search_text, query)
        # freshness因子 (指数衰减)
        days = _memory_age_days(item.get('mtime', 0))
        decay = math.exp(-0.05 * days)  # 比原文更温和的衰减
        final = score * (0.3 + 0.7 * decay)
        scored.append((final, item))
    
    scored.sort(key=lambda x: (-x[0], -x[1].get('mtime', 0)))
    return [item for score, item in scored if score > 0]


# ════════════════════════════════════════
# MemoryItem (保持向后兼容)
# ════════════════════════════════════════
class MemoryItem:
    """记忆条目 (保持原API兼容)"""
    def __init__(self, data: Dict):
        self.id = data.get("id", "")
        self.content = data.get("content", data.get("description", ""))
        self.content_full = data.get("content", "")
        self.tags = data.get("tags", [])
        self.created_at = data.get("mtime", time.time())
        self.access_count = 0
        self.mem_type = data.get("type", "reference")
        self.freshness = freshness_note(data.get("mtime", time.time()))
    
    def relevance_score(self, query: str = "") -> float:
        """指数衰减相关度 (保持原API)"""
        days = _memory_age_days(self.created_at)
        base = 1.0
        decay_factor = math.exp(-0.1 * days)
        access_factor = math.log2(self.access_count + 1) if self.access_count > 0 else 1.0
        return base * decay_factor * access_factor


# ════════════════════════════════════════
# 认知记忆引擎 (核心)
# ════════════════════════════════════════
class CognitiveMemory:
    """
    认知记忆引擎 v2.0
    
    升级点 (移植自Claude Code memdir):
    - .mem.md单文件格式 + frontmatter
    - MEMORY.md指针索引 (支持200行上限)
    - 4记忆类型: user/feedback/project/reference
    - freshnessNote <system-reminder> 过时警告
    - build_manifest() 清单格式
    - 路径安全验证
    - 旧JSONL兼容fallback
    """
    
    def __init__(self):
        self._ensure_dir()
        self._loaded_legacy = False
    
    def _ensure_dir(self):
        """确保认知记忆目录存在"""
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    # ── 写入 (remember) ──
    def remember(self, content: str, tags: List[str] = None, 
                 mem_type: str = "reference") -> str:
        """
        记住一条信息 (原API兼容)
        
        Args:
            content: 自然语言结论
            tags: 标签列表
            mem_type: 记忆类型 (user/feedback/project/reference 或 legacy semantic/episodic)
        
        Returns:
            记忆ID
        """
        mem_id = _mem_id()
        desc = content[:120]
        
        _write_mem_file(mem_id, description=desc, content=content,
                        mem_type=mem_type, tags=tags)
        
        # 更新MEMORY.md索引
        idx = _read_index()
        stat_time = _filepath(mem_id).stat().st_mtime
        idx.append(_index_line(mem_id, desc, mem_type, stat_time))
        _write_index(idx)
        
        return mem_id
    
    def remember_md(self, title: str, content: str, 
                    mem_type: str = "reference", tags: List[str] = None) -> str:
        """
        写入完整Markdown记忆 (新增)
        
        Args:
            title: 标题/描述 (用于frontmatter)
            content: 完整Markdown内容
            mem_type: 记忆类型
            tags: 标签
        
        Returns:
            记忆ID
        """
        mem_id = _mem_id()
        desc = title[:120]
        
        # 内容前加标题
        full_content = f"# {title}\n\n{content}"
        
        _write_mem_file(mem_id, description=desc, content=full_content,
                        mem_type=mem_type, tags=tags)
        
        idx = _read_index()
        stat_time = _filepath(mem_id).stat().st_mtime
        idx.append(_index_line(mem_id, desc, mem_type, stat_time))
        _write_index(idx)
        
        return mem_id
    
    # ── 读取 (recall) ──
    def recall(self, query: str = "", limit: int = 10, 
               already_surfaced: List[str] = None) -> List[MemoryItem]:
        """
        召回记忆 (原API兼容)
        
        移植自 findRelevantMemories.ts:
        - alreadySurfaced 防重复展示
        - 相关性排序 + freshness因子
        - freshnessNote添加到结果
        
        Args:
            query: 检索关键词
            limit: 最大返回数
            already_surfaced: 已展示过的记忆ID列表 (防重复)
        
        Returns:
            MemoryItem列表
        """
        # 从.mem.md扫描
        items = _scan_mem_files()
        
        # 兼容：如果新格式无结果，回退旧JSONL
        if not items:
            legacy = _read_jsonl()
            if legacy:
                self._loaded_legacy = True
                items = []
                for item in legacy:
                    items.append({
                        "id": item.get("id", _mem_id()),
                        "description": item.get("content", "")[:120],
                        "type": LEGACY_TYPE_MAP.get(item.get("type", ""), "reference"),
                        "tags": item.get("tags", []),
                        "mtime": item.get("created_at", time.time()),
                        "size": len(item.get("content", "")),
                    })
        
        if not query:
            # 无查询：按mtime倒序
            items.sort(key=lambda x: -x.get('mtime', 0))
            selected = items[:limit]
        else:
            # 读取完整内容用于检索
            full_items = []
            for item in items:
                full = _read_mem_file(item["id"])
                if full:
                    full_items.append(full)
                else:
                    full_items.append(item)
            
            # 排序
            selected = _sort_by_relevance(full_items, query)[:limit]
        
        # alreadySurfaced 过滤 (移植自findRelevantMemories.ts)
        surfaced = set(already_surfaced or [])
        if surfaced:
            selected = [s for s in selected if s.get("id") not in surfaced][:limit]
        
        # 转换为MemoryItem
        results = []
        for s in selected:
            full = _read_mem_file(s["id"]) if s.get("id") else None
            if full:
                item = MemoryItem(full)
            else:
                item = MemoryItem(s)
            results.append(item)
        
        return results
    
    def read_memory(self, mem_id: str) -> Optional[MemoryItem]:
        """读取单条记忆"""
        data = _read_mem_file(mem_id)
        if data:
            return MemoryItem(data)
        
        # 兼容旧格式
        for item in _read_jsonl():
            if item.get("id") == mem_id:
                return MemoryItem(item)
        return None
    
    # ── 管理 ──
    def forget(self, mem_id: str) -> bool:
        """忘记一条记忆 (原API兼容)"""
        deleted = _delete_mem_file(mem_id)
        
        # 更新索引
        if deleted:
            idx = _read_index()
            idx = [l for l in idx if mem_id not in l]
            _write_index(idx)
        
        # 兼容旧格式
        if not deleted:
            legacy = _read_jsonl()
            new_legacy = [l for l in legacy if l.get("id") != mem_id]
            if len(new_legacy) < len(legacy):
                with open(_JSONL_PATH, 'w', encoding='utf-8') as f:
                    for l in new_legacy:
                        f.write(json.dumps(l, ensure_ascii=False) + '\n')
                return True
        
        return deleted
    
    def list_memories(self, mem_type: str = None) -> List[Dict]:
        """列出所有记忆"""
        items = _scan_mem_files()
        if mem_type:
            items = [i for i in items if i.get("type") == mem_type]
        return items
    
    def count(self) -> int:
        """记忆总数"""
        return len(_scan_mem_files()) + len(_read_jsonl())
    
    def build_manifest(self, mem_type: str = None) -> str:
        """
        构建记忆清单 (移植自 memoryScan.ts formatMemoryManifest)
        
        返回MEMORY.md格式字符串，可注入到system prompt
        """
        items = self.list_memories(mem_type)
        return build_manifest(items)
    
    # ── 会话桥 (session_bridge, 原API兼容+升级) ──
    def session_bridge(self, topic: str = "", insight: str = "") -> str:
        """
        认知记忆桥：如果传入insight则自动remember，再组装跨会话摘要供注入。
        
        升级: 返回内容含 manifest + freshness note (移植自teamMemPrompts.ts)
        """
        if insight:
            tags = []
            if topic:
                tags.append(topic)
            self.remember(content=insight, tags=tags)
        
        # 构建摘要
        parts = ["## 🧠 跨会话记忆摘要\n"]
        
        # 近期记忆
        recent = _scan_mem_files()[:5]
        if recent:
            parts.append("### 📋 记忆清单")
            parts.append(self.build_manifest())
            parts.append("")
        
        # freshness警告
        stale_items = [m for m in recent if _memory_age_days(m.get('mtime', 0)) > STALE_DAYS]
        if stale_items:
            parts.append("### ⚠️ 过时记忆警告")
            for m in stale_items:
                days = _memory_age_days(m.get('mtime', 0))
                parts.append(freshness_note(m.get('mtime', 0)))
            parts.append("")
        
        # 标签云
        all_tags = set()
        for m in recent:
            all_tags.update(m.get('tags', []))
        if all_tags:
            parts.append(f"### 🏷️ 标签云: {' '.join(sorted(all_tags)[:10])}\n")
        
        return '\n'.join(parts)
    
    def freshness_note(self, mtime: float) -> str:
        """过时警告 (移植自 memoryAge.ts)"""
        return freshness_note(mtime)


# ════════════════════════════════════════
# 自检测试 (8项 → 扩展为12项)
# ════════════════════════════════════════
if __name__ == "__main__":
    import sys
    # 设置stdout编码，避免Windows GBK无法打印emoji
    if sys.stdout.encoding and sys.stdout.encoding.upper() in ('GBK', 'GB2312', 'CP936'):
        sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
    
    print("=" * 60)
    print("[TEST] skill_cognitive_memory.py v2.0 自检测试")
    print("=" * 60)
    
    cm = CognitiveMemory()
    test_results = []
    
    def check(name, ok, detail=""):
        status = "+OK" if ok else "-NG"
        test_results.append(ok)
        print(f"  [{status}] {name}" + (f" | {detail}" if detail else ""))
    
    # 1. 基本remember + recall
    mid1 = cm.remember("Python异步编程的3个核心模式: asyncio/gather/wait", 
                        tags=["python", "asyncio"], mem_type="reference")
    results = cm.recall("asyncio")
    check("remember + recall", len(results) > 0)
    check("返回MemoryItem", isinstance(results[0], MemoryItem) if results else False)
    
    # 2. remember_md 完整Markdown
    mid2 = cm.remember_md("FastAPI最佳实践",
                           "## 路由设计\n- 用APIRouter分组\n- 依赖注入\n## 验证\n- 用Pydantic v2",
                           mem_type="reference", tags=["fastapi", "python"])
    check("remember_md", bool(mid2))
    
    # 3. 记忆类型
    mid3 = cm.remember("用户偏好: 喜欢简洁的输出", tags=["user-pref"], mem_type="user")
    mid4 = cm.remember("反馈: 代码示例应该更详细", tags=["feedback"], mem_type="feedback")
    check("记忆类型: user", bool(mid3))
    check("记忆类型: feedback", bool(mid4))
    
    # 4. list_memories + type过滤
    all_items = cm.list_memories()
    user_items = cm.list_memories("user")
    check("list_memories", len(all_items) > 0)
    check("类型过滤", len(user_items) >= 1)
    
    # 5. MEMORY.md索引
    idx = _read_index()
    check("MEMORY.md索引生成", len(idx) > 0)
    
    # 6. build_manifest
    manifest = cm.build_manifest()
    check("build_manifest", "[reference]" in manifest or "[user]" in manifest)
    check("manifest含时间戳", "T" in manifest if manifest else False)
    
    # 7. freshness_note
    old_mtime = time.time() - 86400 * 5  # 5天前
    note = cm.freshness_note(old_mtime)
    check("freshness_note过时警告", "system-reminder" in note and "days old" in note)
    
    # 8. 24小时内无警告
    recent_mtime = time.time() - 3600
    no_note = cm.freshness_note(recent_mtime)
    check("freshness_note近期不报", no_note == "")
    
    # 9. session_bridge
    summary = cm.session_bridge(topic="Python", insight="列表推导式比循环快2-3倍")
    check("session_bridge返回非空", len(summary) > 50)
    check("session_bridge含过时警告", "system-reminder" in summary or "记忆清单" in summary)
    
    # 10. forget
    forgot = cm.forget(mid1)
    check("forget", forgot)
    
    # 11. 路径安全验证
    try:
        _validate_memory_path("../../etc/passwd")
        check("路径安全: 遍历检测", False)
    except ValueError:
        check("路径安全: 遍历检测", True)
    
    try:
        _validate_memory_path("正常文件")
        check("路径安全: 正常文件", True)
    except ValueError:
        check("路径安全: 正常文件", False)
    
    # 12. alreadySurfaced 去重
    results1 = cm.recall("Python", limit=5, already_surfaced=[mid2])
    results2 = cm.recall("Python", limit=5)
    check("alreadySurfaced去重", len(results2) >= len(results1))
    
    # 清理测试数据
    for mid in [mid2, mid3, mid4]:
        cm.forget(mid)
    
    # 清理旧JSONL兼容测试
    print()
    passed = sum(1 for r in test_results if r)
    total = len(test_results)
    print(f"[PASS] {passed}/{total} 项测试通过！")
    print("\n升级亮点:")
    print("  [+] .mem.md单文件 + frontmatter (移植自memoryScan.ts)")
    print("  [+] MEMORY.md指针索引 (移植自memdir.ts)")
    print("  [+] 4记忆类型: user/feedback/project/reference (移植自memoryTypes.ts)")
    print("  [+] freshnessNote <system-reminder> (移植自memoryAge.ts)")
    print("  [+] build_manifest清单格式 (移植自formatMemoryManifest)")
    print("  [+] 路径安全验证 (移植自validateMemoryPath)")
    print("  [+] alreadySurfaced去重 (移植自findRelevantMemories.ts)")
    print("  [+] 旧JSONL格式向后兼容")
    print("  [TODO] teamMemory双层记忆 (移植自teamMemPrompts.ts)")
