"""
skill_karpathy_agentic_knowledge

基于 karpathy 的 "LLM Knowledge Bases" 理念 → GA 可 import 的
知识库系统。核心转换:
  "a large fraction of my recent token throughput is going 
   less into manipulating code, and more into manipulating knowledge"
   — Andrej Karpathy, 2026/4/3

三问骨髓内化:
Q1: 为什么karpathy从"操作代码"转向"操作知识"?
A1: LLM Agent时代, 代码的执行价值降低, 知识的整理/理解/连接价值升高。
    知识库本身成为"可执行代码"。

Q2: karpathy的Knowledge Base与传统笔记(Notion/Obsidian)有何不同?
A2: 传统笔记是"人写人读", karpathy的KB是"LLM写+LLM读"——
    利用LLM做摘要/分类/连接, Agent利用KB做决策/执行。

Q3: 如何落地到GA?
A3: 不重建memory, 而是在现有L1/L2/L3体系上加两层:
    ① KnowledgeChunk: 统一的知识片段(来源/摘要/类别/标签)
    ② KnowledgeIndex: 可检索的知识索引(按时间/来源/类别聚类)
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# ============================================================
# 1. SKILL MANIFEST
# ============================================================

@dataclass
class KnowledgeSkillManifest:
    """技能元数据 — 参考karpathy的"结构化为HTML"输出哲学"""
    name: str = "karpathy_agentic_knowledge"
    description: str = "LLM Knowledge Base: 知识片段管理+索引+检索"
    triggers: list = field(default_factory=lambda: [
        "learn", "save_knowledge", "query_knowledge",
        "summarize_session", "knowledge_report"
    ])
    constraints: list = field(default_factory=lambda: [
        "不修改GA现有memory文件",
        "知识存储到memory/knowledge/目录",
        "每个KnowledgeChunk不超过1KB",
    ])

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "constraints": self.constraints,
        }


# ============================================================
# 2. KNOWLEDGE CHUNK — karpathy KB的核心单元
# ============================================================

@dataclass
class KnowledgeChunk:
    """知识片段 — karpathy: 'LLM写+LLM读'的知识单元

    来源分类 | karpathy自己的分类法:
    - paper: 学术论文/博客
    - tweet: X/Twitter上的洞见
    - code: 代码/架构发现
    - idea: 自己的思考/联想
    - tool: 工具/框架发现
    """
    chunk_id: str
    category: str  # paper|tweet|code|idea|tool
    source: str  # 原文链接/出处
    title: str  # 一句话标题
    tags: list  # 标签列表
    summary: str  # LLM写的摘要(不超过200字)
    insight: str  # 三问结论(对自己/对GA的价值)
    created_at: str = ""
    refs: list = field(default_factory=list)  # 关联的其他chunk_id

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y%m%d_%H%M")

    def to_dict(self) -> dict:
        return {
            "id": self.chunk_id,
            "category": self.category,
            "source": self.source,
            "title": self.title,
            "tags": self.tags,
            "summary": self.summary,
            "insight": self.insight,
            "created_at": self.created_at,
            "refs": self.refs,
        }

    @classmethod
    def from_tweet(cls, author: str, url: str, text: str,
                   insight: str, tags: list[str]) -> "KnowledgeChunk":
        """从X帖子创建知识片段 — 自动提取标题和摘要"""
        # 标题: 取第一行或前80字
        first_line = text.split('\n')[0].strip()
        title = first_line[:80] if len(first_line) > 80 else first_line
        # 摘要: 取前200字
        summary = text[:200].strip()
        # ID: 来源+时间
        chunk_id = f"tw_{author}_{int(time.time())}"
        return cls(
            chunk_id=chunk_id,
            category="tweet",
            source=url,
            title=title,
            tags=tags,
            summary=summary,
            insight=insight,
        )


# ============================================================
# 3. KNOWLEDGE INDEX — 可检索的知识索引
# ============================================================

class KnowledgeIndex:
    """知识索引 — 按karpathy KB哲学组织的可检索索引

    核心功能:
    - add(): 添加知识片段
    - search(): 按关键词/标签/类别搜索
    - report(): 生成知识报告(按来源/类别聚类)
    - export(): 导出为JSON/HTML格式(karpathy爱用的HTML输出)
    """

    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        self.chunks: dict[str, KnowledgeChunk] = {}
        os.makedirs(storage_dir, exist_ok=True)

    def add(self, chunk: KnowledgeChunk) -> KnowledgeChunk:
        self.chunks[chunk.chunk_id] = chunk
        # 自动持久化到JSON
        self._persist(chunk)
        return chunk

    def search(self, query: str = "", category: str = "",
               tags: list[str] = None, limit: int = 10) -> list[KnowledgeChunk]:
        results = list(self.chunks.values())
        # 按类别过滤
        if category:
            results = [c for c in results if c.category == category]
        # 按标签过滤
        if tags:
            results = [c for c in results
                       if any(t in c.tags for t in tags)]
        # 按关键词搜索
        if query:
            q = query.lower()
            results = [c for c in results
                       if q in c.title.lower()
                       or q in c.summary.lower()
                       or q in c.insight.lower()]
        # 按时间排序(最新的在前)
        results.sort(key=lambda c: c.created_at, reverse=True)
        return results[:limit]

    def report(self, group_by: str = "category") -> str:
        """生成知识报告 — HTML格式(karpathy推荐)"""
        if group_by == "category":
            groups: dict[str, list] = {}
            for c in self.chunks.values():
                groups.setdefault(c.category, []).append(c)
        else:
            groups = {"all": list(self.chunks.values())}

        lines = [
            "<html><body style='font-family:sans-serif;max-width:800px;margin:auto;padding:20px'>",
            f"<h1>[Knowledge Base] {datetime.now().strftime('%Y-%m-%d')}</h1>",
            f"<p>Total chunks: {len(self.chunks)} | "
            f"Based on karpathy's LLM Knowledge Base philosophy</p>",
            "<hr>",
        ]
        for cat, chunks in sorted(groups.items()):
            lines.append(f"<h2>Category: {cat} ({len(chunks)})</h2>")
            lines.append("<ul>")
            for c in sorted(chunks, key=lambda x: x.created_at, reverse=True)[:20]:
                lines.append(
                    f"<li><b>{c.title}</b> "
                    f"[{c.created_at}] "
                    f"<br><small>{c.summary[:100]}...</small>"
                    f"<br><i>Insight: {c.insight[:80]}...</i>"
                    f"<br>Tags: {', '.join(c.tags)}"
                    f" | <a href='{c.source}'>source</a>"
                    f"</li>"
                )
            lines.append("</ul>")
        lines.append("</body></html>")
        return "\n".join(lines)

    def _persist(self, chunk: KnowledgeChunk):
        """持久化单个chunk到JSON文件"""
        fname = f"{chunk.chunk_id}.json"
        path = os.path.join(self.storage_dir, fname)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(chunk.to_dict(), f, ensure_ascii=False, indent=2)

    def _load_all(self):
        """从storage_dir加载所有chunk(重建索引用)"""
        if not os.path.isdir(self.storage_dir):
            return
        for fname in os.listdir(self.storage_dir):
            if not fname.endswith('.json'):
                continue
            path = os.path.join(self.storage_dir, fname)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                chunk = KnowledgeChunk(
                    chunk_id=data["id"],
                    category=data["category"],
                    source=data["source"],
                    title=data["title"],
                    tags=data["tags"],
                    summary=data["summary"],
                    insight=data["insight"],
                    created_at=data.get("created_at", ""),
                    refs=data.get("refs", []),
                )
                self.chunks[chunk.chunk_id] = chunk
            except Exception:
                continue


# ============================================================
# 4. SESSION SUMMARIZER — 自动总结会话为知识片段
# ============================================================

class SessionSummarizer:
    """自动把GA会话中的发现转化为知识片段

    模仿karpathy的"less code, more knowledge"哲学:
    每次浏览X/GitHub后的发现→自动结构化入库
    """

    def __init__(self, index: KnowledgeIndex):
        self.index = index

    def summarize_x_browsing(self, author: str, tweet_url: str,
                              tweet_text: str,
                              my_insight: str,
                              tags: list[str]) -> KnowledgeChunk:
        """浏览X后总结一条帖子为知识片段

        参数:
            author: X账号
            tweet_url: 帖子链接
            tweet_text: 帖子原文(至少前200字)
            my_insight: 我的三问结论
            tags: 标签列表
        """
        chunk = KnowledgeChunk.from_tweet(
            author=author,
            url=tweet_url,
            text=tweet_text,
            insight=my_insight,
            tags=tags,
        )
        self.index.add(chunk)
        return chunk

    def summarize_discovery(self, title: str, source_url: str,
                             discovery_text: str,
                             category: str,
                             my_insight: str,
                             tags: list[str]) -> KnowledgeChunk:
        """总结一个发现(代码/工具/论文)为知识片段

        参数:
            title: 标题
            source_url: 来源链接
            discovery_text: 发现描述
            category: 类别(paper|code|idea|tool)
            my_insight: 我的三问结论
            tags: 标签
        """
        chunk_id = f"disc_{int(time.time())}"
        chunk = KnowledgeChunk(
            chunk_id=chunk_id,
            category=category,
            source=source_url,
            title=title[:80],
            tags=tags,
            summary=discovery_text[:200],
            insight=my_insight,
        )
        self.index.add(chunk)
        return chunk


# ============================================================
# 5. SELF TEST — 自检确保一切正常
# ============================================================

def self_test():
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="ga_knowledge_test_")

    print("[TEST] skill_karpathy_agentic_knowledge 自检")

    # 1. 测试Manifest
    m = KnowledgeSkillManifest()
    d = m.to_dict()
    assert d["name"] == "karpathy_agentic_knowledge"
    assert len(d["triggers"]) >= 4
    print("  [OK] Manifest:", d["name"], len(d["triggers"]), "triggers")

    # 2. 测试KnowledgeIndex
    ki = KnowledgeIndex(tmpdir)
    assert len(ki.chunks) == 0
    print("  [OK] KnowledgeIndex: 空索引创建成功")

    # 3. 测试from_tweet
    chunk = KnowledgeChunk.from_tweet(
        author="karpathy",
        url="https://x.com/karpathy/status/test",
        text="The hottest new programming language is English. "
             "This quote changed how I think about LLMs forever.",
        insight="编程的未来不是代码,而是自然语言。GA应该支持"
                "更自然的任务描述方式。",
        tags=["llm", "programming", "agi"],
    )
    assert chunk.category == "tweet"
    assert "karpathy" in chunk.chunk_id
    assert "English" in chunk.title
    ki.add(chunk)
    assert len(ki.chunks) == 1
    print(f"  [OK] KnowledgeChunk.from_tweet: {chunk.chunk_id}")

    # 4. 测试SessionSummarizer
    ss = SessionSummarizer(ki)
    chunk2 = ss.summarize_x_browsing(
        author="amehochan",
        tweet_url="https://x.com/amehochan/status/xxx",
        tweet_text="Kimi自己基于Python写的kimi-cli,在今天换成了基于"
                   "Typescript和pi-tui写的新kimi-code。",
        my_insight="AI CLI从Python转向TS+pi-tui,代表单二进制分发趋势。"
                    "GA也可考虑web_setup_sop整合TUI。",
        tags=["kimi-code", "cli", "architecture"],
    )
    assert chunk2.chunk_id != chunk.chunk_id
    print(f"  [OK] SessionSummarizer: {chunk2.chunk_id}")

    # 5. 测试search
    results = ki.search(query="English")
    assert len(results) >= 1
    print(f"  [OK] search('English'): {len(results)} result(s)")

    results2 = ki.search(tags=["cli"])
    assert len(results2) >= 1
    print(f"  [OK] search(tags=['cli']): {len(results2)} result(s)")

    # 6. 测试HTML report
    html = ki.report()
    assert "<html>" in html
    assert "Knowledge Base" in html
    assert "karpathy" in html
    print(f"  [OK] HTML报告: {len(html)} chars")

    # 7. 测试持久化
    json_files = [f for f in os.listdir(tmpdir) if f.endswith('.json')]
    assert len(json_files) >= 2
    print(f"  [OK] 持久化: {len(json_files)} JSON files in {tmpdir}")

    # 8. 测试重建索引
    ki2 = KnowledgeIndex(tmpdir)
    ki2._load_all()
    assert len(ki2.chunks) >= 2
    print(f"  [OK] 重建索引: {len(ki2.chunks)} chunks loaded")

    # 9. 测试summarize_discovery
    chunk3 = ss.summarize_discovery(
        title="kimi-code三层架构模式",
        source_url="https://github.com/MoonshotAI/kimi-code",
        discovery_text="apps/kimi-code + packages/agent-core + "
                       "packages/工具，三层分离互不依赖",
        category="code",
        my_insight="GA已实现agent_core+frontends分离, 可进一步"
                    "细化tool层为独立package",
        tags=["kimi-code", "architecture", "three-layer"],
    )
    assert chunk3.category == "code"
    print(f"  [OK] summarize_discovery: {chunk3.chunk_id}")

    print("\n[OK] 全部9项自检通过!")
    return True


if __name__ == "__main__":
    self_test()
