"""
skill_mem0 — 混合记忆搜索器 (从 mem0 骨髓内化, ⭐56.2k)

核心设计:
  1. 混合搜索: BM25(关键词) + TF-IDF(语义近似) + 时效加权
  2. 多后端抽象: 支持 Dict/File/SQLite 三种后端
  3. 自动摘要: 超长记忆自动压缩
  4. 注册表模式: 后端/搜索器可注册+替换 (继承 browser-use 动作注册表思想)

不依赖任何外部向量库或LLM, 纯 Python 标准库实现。
"""

import os
import re
import json
import math
import time
import sqlite3
import hashlib
import threading
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any, Callable, Set
from collections import Counter, defaultdict
from pathlib import Path


# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

DEFAULT_TOP_K = 5
DEFAULT_BM25_K1 = 1.5
DEFAULT_BM25_B = 0.75
TIMESTAMP_DECAY = 0.95       # 每24小时衰减系数
DEFAULT_SUMMARY_LEN = 200


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────

@dataclass
class MemoryItem:
    """单条记忆"""
    id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    summary: str = ""
    source: str = ""           # 来源: "session", "user_info", "insight"
    score: float = 0.0         # 搜索时填充

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "MemoryItem":
        return MemoryItem(**d)


@dataclass
class SearchResult:
    """搜索结果"""
    item: MemoryItem
    score: float
    match_type: str  # "bm25", "tfidf", "hybrid"


# ──────────────────────────────────────────────
# 分词器
# ──────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """简单分词: 英文按空格+标点, 中文按单字"""
    # 英文词
    tokens = re.findall(r'[a-zA-Z]+', text.lower())
    # 中文连续字符(2字及以上)
    chinese = re.findall(r'[\u4e00-\u9fff]{2,}', text)
    for c in chinese:
        # 中文也按2-gram
        tokens.append(c)
        if len(c) >= 3:
            tokens.extend([c[i:i+2] for i in range(len(c)-1)])
    return tokens


def _tokenize_idf(text: str) -> List[str]:
    """IDF用分词, 保留单字信息"""
    tokens = re.findall(r'[a-zA-Z]+', text.lower())
    # 中文单字
    tokens.extend(re.findall(r'[\u4e00-\u9fff]', text))
    return tokens


# ──────────────────────────────────────────────
# BM25 搜索引擎
# ──────────────────────────────────────────────

class BM25Scorer:
    """BM25 关键词匹配评分器 (纯标准库实现)"""

    def __init__(self, k1: float = DEFAULT_BM25_K1, b: float = DEFAULT_BM25_B):
        self.k1 = k1
        self.b = b
        self.doc_count = 0
        self.avg_doc_len = 0.0
        self.doc_lens: List[int] = []          # 每个文档长度
        self.doc_tokens: List[Counter] = []    # 每个文档的词频
        self.idf: Dict[str, float] = {}        # IDF 字典
        self._built = False

    def build(self, documents: List[str]):
        """从文档列表构建 BM25 索引"""
        self.doc_count = len(documents)
        self.doc_lens = []
        self.doc_tokens = []
        all_tokens: Set[str] = set()
        total_len = 0

        for doc in documents:
            tokens = _tokenize(doc)
            self.doc_lens.append(len(tokens))
            total_len += len(tokens)
            counter = Counter(tokens)
            self.doc_tokens.append(counter)
            all_tokens.update(counter.keys())

        self.avg_doc_len = total_len / max(self.doc_count, 1)

        # 计算 IDF
        df = Counter()
        for counter in self.doc_tokens:
            df.update(set(counter.keys()))
        self.idf = {}
        for token in all_tokens:
            n = df.get(token, 0)
            self.idf[token] = math.log(
                (self.doc_count - n + 0.5) / (n + 0.5) + 1.0
            )

        self._built = True

    def score(self, query: str, doc_idx: int) -> float:
        """计算单个文档的 BM25 得分"""
        if not self._built or doc_idx >= self.doc_count:
            return 0.0
        query_tokens = _tokenize(query)
        counter = self.doc_tokens[doc_idx]
        doc_len = self.doc_lens[doc_idx]
        score = 0.0
        for qt in query_tokens:
            if qt in self.idf:
                tf = counter.get(qt, 0)
                idf = self.idf[qt]
                score += idf * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_len)
                )
        return score

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> List[Tuple[int, float]]:
        """搜索 BM25 排名"""
        scores = [(i, self.score(query, i)) for i in range(self.doc_count)]
        scores.sort(key=lambda x: -x[1])
        return [(idx, s) for idx, s in scores[:top_k] if s > 0]


# ──────────────────────────────────────────────
# TF-IDF 向量搜索引擎 (语义近似)
# ──────────────────────────────────────────────

class TfidfScorer:
    """TF-IDF 向量搜索引擎 (余弦相似度, 纯标准库实现)"""

    def __init__(self):
        self.vocab: Dict[str, int] = {}
        self.doc_vectors: List[defaultdict] = []
        self.idf: Dict[str, float] = {}
        self.doc_count = 0
        self._built = False

    def build(self, documents: List[str]):
        """构建 TF-IDF 索引"""
        self.doc_count = len(documents)
        # 构建词表
        all_doc_tokens = []
        for doc in documents:
            tokens = _tokenize_idf(doc)
            all_doc_tokens.append(tokens)

        # 统计 DF
        df = Counter()
        for tokens in all_doc_tokens:
            df.update(set(tokens))

        # 建立词表
        self.vocab = {}
        idx = 0
        for token in sorted(set(t for tokens in all_doc_tokens for t in tokens)):
            self.vocab[token] = idx
            idx += 1

        # 计算 IDF
        self.idf = {}
        for token, doc_freq in df.items():
            self.idf[token] = math.log(
                (self.doc_count - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0
            )

        # 计算文档向量
        self.doc_vectors = []
        for tokens in all_doc_tokens:
            tf = Counter(tokens)
            vec = defaultdict(float)
            max_tf = max(tf.values()) if tf else 1.0
            for token, count in tf.items():
                if token in self.idf:
                    vec[self.vocab[token]] = (count / max_tf) * self.idf[token]
            self._normalize(vec)
            self.doc_vectors.append(vec)

        self._built = True

    def _normalize(self, vec: defaultdict):
        """L2 归一化"""
        norm = math.sqrt(sum(v*v for v in vec.values()))
        if norm > 0:
            for k in vec:
                vec[k] /= norm

    def _query_vector(self, query: str) -> defaultdict:
        """查询文本转向量"""
        tokens = _tokenize_idf(query)
        tf = Counter(tokens)
        vec = defaultdict(float)
        max_tf = max(tf.values()) if tf else 1.0
        for token, count in tf.items():
            if token in self.vocab:
                vec[self.vocab[token]] = (count / max_tf) * self.idf.get(token, 1.0)
        self._normalize(vec)
        return vec

    def score(self, query: str, doc_idx: int) -> float:
        """余弦相似度"""
        if not self._built or doc_idx >= self.doc_count:
            return 0.0
        qvec = self._query_vector(query)
        dvec = self.doc_vectors[doc_idx]
        dot = sum(qvec[k] * dvec.get(k, 0.0) for k in qvec)
        return dot

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> List[Tuple[int, float]]:
        """搜索 TF-IDF 排名"""
        scores = [(i, self.score(query, i)) for i in range(self.doc_count)]
        scores.sort(key=lambda x: -x[1])
        return [(idx, s) for idx, s in scores[:top_k] if s > 0]


# ──────────────────────────────────────────────
# 混合搜索器
# ──────────────────────────────────────────────

@dataclass
class HybridSearchConfig:
    """混合搜索配置"""
    bm25_weight: float = 0.6       # BM25 权重
    tfidf_weight: float = 0.3      # TF-IDF 权重
    time_weight: float = 0.1       # 时效权重
    time_decay_hours: float = 24.0  # 半衰期(小时)
    top_k: int = DEFAULT_TOP_K


SEARCHER_REGISTRY: Dict[str, Callable] = {}
"""搜索器注册表 (复用 browser-use 的注册表模式)"""


def register_searcher(name: str):
    """注册搜索器装饰器"""
    def decorator(cls):
        SEARCHER_REGISTRY[name] = cls
        return cls
    return decorator


@register_searcher("bm25")
class Bm25SearchAdapter:
    def __init__(self):
        self.scorer = BM25Scorer()

    def build(self, docs: List[str]):
        self.scorer.build(docs)

    def search(self, query: str, top_k: int) -> List[Tuple[int, float]]:
        return self.scorer.search(query, top_k)

    @property
    def is_built(self) -> bool:
        return self.scorer._built


@register_searcher("tfidf")
class TfidfSearchAdapter:
    def __init__(self):
        self.scorer = TfidfScorer()

    def build(self, docs: List[str]):
        self.scorer.build(docs)

    def search(self, query: str, top_k: int) -> List[Tuple[int, float]]:
        return self.scorer.search(query, top_k)

    @property
    def is_built(self) -> bool:
        return self.scorer._built


class HybridMemorySearch:
    """
    混合记忆搜索器 — mem0 核心功能的轻量实现

    使用方式:
        searcher = HybridMemorySearch()
        searcher.build(memory_items)
        results = searcher.search("用户喜欢什么话题")
    """

    def __init__(self, config: Optional[HybridSearchConfig] = None):
        self.config = config or HybridSearchConfig()
        self.items: List[MemoryItem] = []
        self._bm25 = Bm25SearchAdapter()
        self._tfidf = TfidfSearchAdapter()
        self._content_docs: List[str] = []
        self._built = False

    def build(self, items: List[MemoryItem]):
        """构建搜索索引"""
        self.items = items
        self._content_docs = [
            f"{item.content} {' '.join(str(v) for v in item.metadata.values() if isinstance(v, str))}"
            for item in items
        ]
        if self._content_docs:
            self._bm25.build(self._content_docs)
            self._tfidf.build(self._content_docs)
        self._built = True

    def add_item(self, item: MemoryItem):
        """动态添加单条记忆 (重建索引)"""
        self.items.append(item)
        self.build(self.items)

    def _calc_time_score(self, idx: int) -> float:
        """时效评分: 越近越高"""
        item = self.items[idx]
        if item.timestamp <= 0:
            return 0.5  # 默认中等
        age_hours = (time.time() - item.timestamp) / 3600
        return TIMESTAMP_DECAY ** (age_hours / self.config.time_decay_hours)

    def search(self, query: str, top_k: Optional[int] = None) -> List[SearchResult]:
        """混合搜索: BM25 + TF-IDF + 时效"""
        if not self._built or not self.items:
            return []

        top_k = top_k or self.config.top_k
        cfg = self.config

        # 并行搜索
        bm25_results = self._bm25.search(query, len(self.items))
        tfidf_results = self._tfidf.search(query, len(self.items))

        # 建立索引→分数映射
        scores: Dict[int, float] = defaultdict(float)
        max_bm25 = max((s for _, s in bm25_results), default=1.0)
        max_tfidf = max((s for _, s in tfidf_results), default=1.0)

        for idx, s in bm25_results:
            if max_bm25 > 0:
                scores[idx] += cfg.bm25_weight * (s / max_bm25)

        for idx, s in tfidf_results:
            if max_tfidf > 0:
                scores[idx] += cfg.tfidf_weight * (s / max_tfidf)

        # 时效分
        for idx in scores:
            scores[idx] += cfg.time_weight * self._calc_time_score(idx)

        # 排序取 top_k
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        results = []
        for idx, score in ranked[:top_k]:
            item = self.items[idx]
            item.score = score
            # 确定匹配类型
            match_type = "hybrid"
            bm25_w = next((s for i, s in bm25_results if i == idx), 0)
            tfidf_w = next((s for i, s in tfidf_results if i == idx), 0)
            if bm25_w > 0 and tfidf_w == 0:
                match_type = "bm25"
            elif tfidf_w > 0 and bm25_w == 0:
                match_type = "tfidf"
            results.append(SearchResult(item=item, score=score, match_type=match_type))

        return results


# ──────────────────────────────────────────────
# 记忆摘要器
# ──────────────────────────────────────────────

class MemorySummarizer:
    """
    自动记忆摘要器 — 当记忆太多时压缩为简洁摘要
    纯启发式方法, 不依赖LLM
    """

    @staticmethod
    def summarize(content: str, max_len: int = DEFAULT_SUMMARY_LEN) -> str:
        """用启发式方法提取摘要"""
        if len(content) <= max_len:
            return content

        # 提取关键词 (高频词)
        tokens = _tokenize(content)
        freq = Counter(tokens)
        # 去停用词 (英文常见词)
        stopwords = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'can', 'could', 'may', 'might', 'shall', 'should', 'to',
            'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as',
            'into', 'through', 'during', 'before', 'after', 'above',
            'below', 'between', 'out', 'off', 'over', 'under', 'again',
            'further', 'then', 'once', 'here', 'there', 'when', 'where',
            'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more',
            'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
            'own', 'same', 'so', 'than', 'too', 'very', 'just', 'also',
            'and', 'but', 'or', 'if', 'because', 'about', 'up', 'down',
            'it', 'its', 'my', 'your', 'his', 'her', 'our', 'their',
        }
        keywords = {w for w, c in freq.most_common(10) if w.lower() not in stopwords and len(w) > 1}

        # 取前几个带关键词的句子
        sentences = re.split(r'[。！？.!?\n]', content)
        scored_sentences = []
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            score = sum(1 for kw in keywords if kw.lower() in s.lower())
            scored_sentences.append((s, score))

        scored_sentences.sort(key=lambda x: -x[1])

        summary = ""
        for sent, _ in scored_sentences:
            if len(summary) + len(sent) + 2 > max_len:
                break
            if summary:
                summary += ". "
            summary += sent

        if not summary or len(summary) < 10:
            # fallback: 取前 max_len 字符
            summary = content[:max_len].rsplit(' ', 1)[0] if ' ' in content[:max_len] else content[:max_len]

        return summary.strip()

    @staticmethod
    def summarize_items(items: List[MemoryItem], max_len: int = DEFAULT_SUMMARY_LEN) -> str:
        """多条记忆合并摘要"""
        combined = "\n".join(f"- {item.summary or item.content[:100]}" for item in items)
        if len(combined) <= max_len:
            return combined
        return MemorySummarizer.summarize(combined, max_len)


# ──────────────────────────────────────────────
# 存储后端 (多后端抽象 + 注册表模式)
# ──────────────────────────────────────────────

BACKEND_REGISTRY: Dict[str, type] = {}
"""后端注册表"""


def register_backend(name: str):
    """注册存储后端装饰器"""
    def decorator(cls):
        BACKEND_REGISTRY[name] = cls
        return cls
    return decorator


class MemoryBackend:
    """存储后端基类"""

    def load(self) -> List[MemoryItem]:
        raise NotImplementedError

    def save(self, items: List[MemoryItem]):
        raise NotImplementedError

    def append(self, item: MemoryItem):
        raise NotImplementedError


@register_backend("dict")
class DictBackend(MemoryBackend):
    """内存字典后端 (临时存储)"""

    def __init__(self):
        self._items: List[MemoryItem] = []

    def load(self) -> List[MemoryItem]:
        return self._items

    def save(self, items: List[MemoryItem]):
        self._items = items

    def append(self, item: MemoryItem):
        self._items.append(item)


@register_backend("file")
class FileBackend(MemoryBackend):
    """文件后端 (JSON 存储)"""

    def __init__(self, filepath: str):
        self.filepath = filepath

    def load(self) -> List[MemoryItem]:
        if not os.path.exists(self.filepath):
            return []
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return [MemoryItem.from_dict(d) for d in data]
        except (json.JSONDecodeError, IOError):
            return []

    def save(self, items: List[MemoryItem]):
        os.makedirs(os.path.dirname(self.filepath) or '.', exist_ok=True)
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump([item.to_dict() for item in items], f, ensure_ascii=False, indent=2)

    def append(self, item: MemoryItem):
        items = self.load()
        items.append(item)
        self.save(items)


@register_backend("sqlite")
class SQLiteBackend(MemoryBackend):
    """SQLite 后端"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    timestamp REAL DEFAULT 0.0,
                    summary TEXT DEFAULT '',
                    source TEXT DEFAULT ''
                )
            """)
            conn.commit()
            conn.close()

    def load(self) -> List[MemoryItem]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT id, content, metadata, timestamp, summary, source FROM memories")
            items = []
            for row in cursor.fetchall():
                items.append(MemoryItem(
                    id=row[0],
                    content=row[1],
                    metadata=json.loads(row[2]) if row[2] else {},
                    timestamp=row[3],
                    summary=row[4],
                    source=row[5],
                ))
            conn.close()
            return items

    def save(self, items: List[MemoryItem]):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM memories")
            for item in items:
                conn.execute(
                    "INSERT INTO memories (id, content, metadata, timestamp, summary, source) VALUES (?, ?, ?, ?, ?, ?)",
                    (item.id, item.content, json.dumps(item.metadata, ensure_ascii=False),
                     item.timestamp, item.summary, item.source)
                )
            conn.commit()
            conn.close()

    def append(self, item: MemoryItem):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO memories (id, content, metadata, timestamp, summary, source) VALUES (?, ?, ?, ?, ?, ?)",
                (item.id, item.content, json.dumps(item.metadata, ensure_ascii=False),
                 item.timestamp, item.summary, item.source)
            )
            conn.commit()
            conn.close()


# ──────────────────────────────────────────────
# 记忆引擎 (顶层 API)
# ──────────────────────────────────────────────

class MemoryEngine:
    """
    记忆引擎 — mem0 核心功能的 GA 适配

    整合: 混合搜索 + 多后端 + 自动摘要
    可替代 session_memory_retriever 的检索层

    使用:
        engine = MemoryEngine("file", filepath="memory/mem0_store.json")
        engine.add("用户喜欢Python", metadata={"type": "preference"})
        results = engine.search("Python偏好")
    """

    def __init__(self, backend_type: str = "dict", **kwargs):
        if backend_type not in BACKEND_REGISTRY:
            raise ValueError(f"不支持的后端: {backend_type}, 可选: {list(BACKEND_REGISTRY.keys())}")
        self.backend = BACKEND_REGISTRY[backend_type](**kwargs)
        self.searcher = HybridMemorySearch()
        self.summarizer = MemorySummarizer()
        self._items: List[MemoryItem] = []
        self._dirty = False

        # 加载已有数据
        self._load()

    def _load(self):
        """从后端加载记忆"""
        self._items = self.backend.load()
        if self._items:
            self.searcher.build(self._items)

    def _save(self):
        """持久化到后端"""
        self.backend.save(self._items)
        self._dirty = False

    def add(self, content: str, metadata: Optional[dict] = None,
            source: str = "", auto_summary: bool = True) -> MemoryItem:
        """添加一条记忆"""
        item_id = hashlib.md5(
            f"{content}_{time.time()}_{hash(content)}".encode()
        ).hexdigest()[:16]

        summary = self.summarizer.summarize(content) if auto_summary else ""
        item = MemoryItem(
            id=item_id,
            content=content,
            metadata=metadata or {},
            timestamp=time.time(),
            summary=summary,
            source=source,
        )
        self._items.append(item)
        self.searcher.add_item(item)
        self._dirty = True
        return item

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> List[SearchResult]:
        """搜索记忆"""
        return self.searcher.search(query, top_k)

    def get_all(self) -> List[MemoryItem]:
        """获取所有记忆"""
        return self._items

    def delete(self, item_id: str) -> bool:
        """删除指定记忆"""
        before = len(self._items)
        self._items = [it for it in self._items if it.id != item_id]
        if len(self._items) < before:
            self.searcher.build(self._items)
            self._dirty = True
            return True
        return False

    def clear(self):
        """清空所有记忆"""
        self._items = []
        self.searcher = HybridMemorySearch()
        self._dirty = True

    def flush(self):
        """强制持久化"""
        if self._dirty:
            self._save()

    def count(self) -> int:
        return len(self._items)

    def get_summary(self, top_k: int = 5) -> str:
        """获取整体记忆摘要"""
        if not self._items:
            return "无记忆"
        # 取最新的 top_k 条做摘要
        recent = sorted(self._items, key=lambda x: -x.timestamp)[:top_k]
        return self.summarizer.summarize_items(recent)

    # ── 与 session_memory 的兼容接口 ──

    def retrieve_context(self, query: str, max_results: int = 3) -> str:
        """
        兼容 session_memory_retriever 的接口

        返回: 格式化的记忆文本, 可用于注入 <claude-mem-context>
        """
        results = self.search(query, top_k=max_results)
        if not results:
            return ""
        parts = []
        for r in results:
            item = r.item
            source_tag = f"[{item.source}]" if item.source else ""
            summary_tag = f" ({item.summary[:80]})" if item.summary else ""
            parts.append(f"- {source_tag}{item.content[:200]}{summary_tag} (score:{r.score:.2f})")
        return "\n".join(parts)
