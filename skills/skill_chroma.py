"""
skill_chroma.py — 向量数据库引擎 (骨髓内化 Chroma v0.5.x, ⭐28k)

来源: chroma-core/chroma (GitHub, 28k stars)
核心: EmbeddingFunction → Collection(Embeddings + Metadata + Document) → 
      Semantic Search(ANN/余弦相似度) → Persistent Storage

与本GA认知记忆的整合:
- action_registry.py: 动作用的「动作语义搜索」- 按功能描述找动作
- skill_cognitive_memory.py: 替代线性扫描, 用语义搜索找记忆
- 本模块提供零依赖纯Python实现, 不装chroma包也能用
"""

import json
import os
import pickle
import math
import random
from typing import Optional
from dataclasses import dataclass, field


# ══════════════════════════════════════════════════════════════
# 核心数据结构
# ══════════════════════════════════════════════════════════════

@dataclass
class EmbeddingRecord:
    """单条向量记录"""
    id: str
    embedding: list[float]
    metadata: dict = field(default_factory=dict)
    document: Optional[str] = None


# ══════════════════════════════════════════════════════════════
# 嵌入函数
# ══════════════════════════════════════════════════════════════

class EmbeddingFunction:
    """嵌入函数基类 (可替换为text2vec/OpenAI等)"""
    
    def __call__(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError
    
    @property
    def dim(self) -> int:
        """返回嵌入维度"""
        raise NotImplementedError


class SimpleEmbedding(EmbeddingFunction):
    """简化版: 字符级嵌入 (零依赖, 仅做骨架教学用)
    
    注意: 这不是真正的语义嵌入! 真实场景替换为:
    - pip install chromadb (自带all-MiniLM-L6-v2)
    - pip install sentence-transformers
    - OpenAI/Claude API
    """
    
    def __init__(self, dim: int = 64):
        self._dim = dim
    
    def __call__(self, texts: list[str]) -> list[list[float]]:
        """字符哈希嵌入 (确定性的, 同一文本→同一向量)"""
        results = []
        for text in texts:
            vec = [0.0] * self._dim
            for i, ch in enumerate(text):
                idx = (hash(ch) % (self._dim - 2) + 2) % self._dim
                vec[idx] += 0.1 + (ord(ch) % 10) * 0.01
            # 部分词的bigram特征
            for i in range(len(text) - 1):
                bigram = text[i:i+2]
                idx = (hash(bigram) % (self._dim - 2) + 2) % self._dim
                vec[idx] += 0.05
            # 归一化
            norm = math.sqrt(sum(v*v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            results.append(vec)
        return results
    
    @property
    def dim(self) -> int:
        return self._dim


# ══════════════════════════════════════════════════════════════
# 距离 / ANN搜索
# ══════════════════════════════════════════════════════════════

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度 [-1, 1], 1=最相似"""
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def dot_product(a: list[float], b: list[float]) -> float:
    """点积"""
    return sum(x*y for x, y in zip(a, b))


def l2_distance(a: list[float], b: list[float]) -> float:
    """L2距离"""
    return math.sqrt(sum((x-y)*(x-y) for x, y in zip(a, b)))


def _brute_force_search(embeddings: list[list[float]], 
                        query: list[float], k: int,
                        metric: str = "cosine") -> list[tuple[int, float]]:
    """暴力搜索 (小数据集<10K条 用这个, 真实chroma用HNSW)"""
    scores = []
    for i, emb in enumerate(embeddings):
        if metric == "cosine":
            score = cosine_similarity(query, emb)
        elif metric == "l2":
            score = -l2_distance(query, emb)
        elif metric == "dot":
            score = dot_product(query, emb)
        else:
            raise ValueError(f"不支持的距离度量: {metric}")
        scores.append((i, score))
    # 降序排序 (cosine越大越相似, l2取负后也是越大越近)
    scores.sort(key=lambda x: -x[1])
    return scores[:k]


# ══════════════════════════════════════════════════════════════
# Collection (核心类)
# ══════════════════════════════════════════════════════════════

class Collection:
    """向量集合——Chroma最核心的抽象
    
    等价于 chromadb.Collection
    """
    
    def __init__(self, name: str, embedding_function: EmbeddingFunction = None,
                 metadata: dict = None):
        self.name = name
        self._embedding_fn = embedding_function or SimpleEmbedding()
        self.metadata = metadata or {}
        self._records: list[EmbeddingRecord] = []
        self._id_index: dict[str, int] = {}  # id -> index in _records
    
    @property
    def count(self) -> int:
        """返回记录数"""
        return len(self._records)
    
    def add(self, ids: list[str], embeddings: list[list[float]] = None,
            metadatas: list[dict] = None, documents: list[str] = None):
        """添加向量(类似 chromadb.Collection.add)"""
        if embeddings is None and documents is not None:
            # 自动嵌入
            embeddings = self._embedding_fn(documents)
        elif embeddings is None:
            raise ValueError("必须提供 embeddings 或 documents")
        
        for i, rec_id in enumerate(ids):
            record = EmbeddingRecord(
                id=rec_id,
                embedding=embeddings[i],
                metadata=metadatas[i] if metadatas else {},
                document=documents[i] if documents else None,
            )
            idx = len(self._records)
            self._records.append(record)
            self._id_index[rec_id] = idx
    
    def query(self, query_embeddings: list[list[float]] = None,
              query_texts: list[str] = None, n_results: int = 10,
              where: dict = None, include: list[str] = None) -> dict:
        """语义搜索 (chroma风格的返回格式)
        
        返回: {"ids": [...], "distances": [...], "metadatas": [...], "documents": [...]}
        """
        if query_embeddings is None and query_texts is not None:
            query_embeddings = self._embedding_fn(query_texts)
        elif query_embeddings is None:
            raise ValueError("必须提供 query_embeddings 或 query_texts")
        
        # 过滤
        if where:
            candidate_indices = self._apply_filter(where)
        else:
            candidate_indices = list(range(len(self._records)))
        
        # 构建候选嵌入列表
        candidate_embs = [self._records[i].embedding for i in candidate_indices]
        
        results = {"ids": [], "distances": [], "metadatas": [], "documents": []}
        
        for q_emb in query_embeddings:
            top_idx_score = _brute_force_search(candidate_embs, q_emb, n_results)
            
            ids_batch = []
            dist_batch = []
            meta_batch = []
            doc_batch = []
            
            for orig_idx, score in top_idx_score:
                rec_idx = candidate_indices[orig_idx]
                rec = self._records[rec_idx]
                ids_batch.append(rec.id)
                # chroma的distance是1-cosine (0=完全相同)
                dist_batch.append(1.0 - score if score <= 1.0 else score)
                meta_batch.append(rec.metadata)
                doc_batch.append(rec.document or "")
            
            results["ids"].append(ids_batch)
            results["distances"].append(dist_batch)
            results["metadatas"].append(meta_batch)
            results["documents"].append(doc_batch)
        
        return results
    
    def _apply_filter(self, where: dict) -> list[int]:
        """应用元数据过滤 (简易版, 仅支持 {field: value} 等值匹配)"""
        indices = []
        for i, rec in enumerate(self._records):
            match = True
            for key, value in where.items():
                if key not in rec.metadata or rec.metadata[key] != value:
                    match = False
                    break
            if match:
                indices.append(i)
        return indices
    
    def update(self, ids: list[str], embeddings: list[list[float]] = None,
               metadatas: list[dict] = None, documents: list[str] = None):
        """更新记录"""
        for i, rec_id in enumerate(ids):
            if rec_id not in self._id_index:
                continue
            idx = self._id_index[rec_id]
            rec = self._records[idx]
            if embeddings:
                rec.embedding = embeddings[i]
            if metadatas:
                rec.metadata = metadatas[i]
            if documents:
                rec.document = documents[i]
    
    def delete(self, ids: list[str] = None, where: dict = None):
        """删除记录"""
        if ids and where:
            raise ValueError("不能同时使用 ids 和 where")
        
        to_delete = set()
        if ids:
            to_delete.update(ids)
        elif where:
            for rec in self._records:
                match = True
                for key, value in where.items():
                    if key not in rec.metadata or rec.metadata[key] != value:
                        match = False
                        break
                if match:
                    to_delete.add(rec.id)
        
        # 重建列表
        new_records = [r for r in self._records if r.id not in to_delete]
        self._records = new_records
        # 重建索引
        self._id_index = {r.id: i for i, r in enumerate(self._records)}
    
    def peek(self, limit: int = 10) -> dict:
        """查看前N条"""
        return {
            "ids": [r.id for r in self._records[:limit]],
            "embeddings": [r.embedding for r in self._records[:limit]],
            "metadatas": [r.metadata for r in self._records[:limit]],
            "documents": [r.document for r in self._records[:limit]],
        }
    
    def get(self, ids: list[str] = None, where: dict = None,
            include: list[str] = None) -> dict:
        """按ID或条件获取记录"""
        if ids:
            records = [r for r in self._records if r.id in ids]
        elif where:
            records = []
            for r in self._records:
                match = True
                for key, value in where.items():
                    if key not in r.metadata or r.metadata[key] != value:
                        match = False
                        break
                if match:
                    records.append(r)
        else:
            records = self._records
        
        return {
            "ids": [r.id for r in records],
            "metadatas": [r.metadata for r in records],
            "documents": [r.document for r in records],
        }


# ══════════════════════════════════════════════════════════════
# 持久化
# ══════════════════════════════════════════════════════════════

class PersistentCollection(Collection):
    """可持久化的Collection (pickle到磁盘)"""
    
    def __init__(self, name: str, persist_dir: str = "./chroma_data",
                 embedding_function: EmbeddingFunction = None):
        super().__init__(name, embedding_function)
        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)
    
    @property
    def _filepath(self) -> str:
        return os.path.join(self.persist_dir, f"{self.name}.chroma")
    
    def persist(self):
        """保存到磁盘"""
        data = {
            "name": self.name,
            "metadata": self.metadata,
            "records": [(r.id, r.embedding, r.metadata, r.document) for r in self._records],
        }
        with open(self._filepath, "wb") as f:
            pickle.dump(data, f)
    
    @classmethod
    def load(cls, name: str, persist_dir: str = "./chroma_data",
             embedding_function: EmbeddingFunction = None) -> "PersistentCollection":
        """从磁盘加载"""
        path = os.path.join(persist_dir, f"{name}.chroma")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Collection '{name}' 不存在于 {persist_dir}")
        with open(path, "rb") as f:
            data = pickle.load(f)
        
        col = cls(name, persist_dir, embedding_function)
        col.metadata = data["metadata"]
        for rec_id, emb, meta, doc in data["records"]:
            record = EmbeddingRecord(id=rec_id, embedding=emb, metadata=meta, document=doc)
            col._records.append(record)
            col._id_index[rec_id] = len(col._records) - 1
        return col


# ══════════════════════════════════════════════════════════════
# 客户端 (顶层API)
# ══════════════════════════════════════════════════════════════

class Client:
    """Chroma风格客户端
    
    用法:
        client = Client()
        col = client.create_collection("my_collection")
        col.add(ids=["1", "2"], documents=["hello world", "foo bar"])
        results = col.query(query_texts=["hello"])
    """
    
    def __init__(self, persist_directory: str = None):
        self._persist_directory = persist_directory
        self._collections: dict[str, Collection] = {}
        
        # 如果指定了持久目录, 加载已有集合
        if persist_directory and os.path.exists(persist_directory):
            for fname in os.listdir(persist_directory):
                if fname.endswith(".chroma"):
                    name = fname[:-7]
                    try:
                        col = PersistentCollection.load(name, persist_directory)
                        self._collections[name] = col
                    except Exception:
                        pass
    
    def create_collection(self, name: str, metadata: dict = None,
                         embedding_function: EmbeddingFunction = None) -> Collection:
        """创建集合"""
        if name in self._collections:
            raise ValueError(f"集合 '{name}' 已存在")
        
        if self._persist_directory:
            col = PersistentCollection(name, self._persist_directory, embedding_function)
        else:
            col = Collection(name, embedding_function, metadata)
        
        col.metadata = metadata or {}
        self._collections[name] = col
        return col
    
    def get_collection(self, name: str) -> Collection:
        """获取已有集合"""
        if name not in self._collections:
            raise ValueError(f"集合 '{name}' 不存在")
        return self._collections[name]
    
    def delete_collection(self, name: str):
        """删除集合"""
        if name in self._collections:
            del self._collections[name]
            # 持久化删除
            if self._persist_directory:
                path = os.path.join(self._persist_directory, f"{name}.chroma")
                if os.path.exists(path):
                    os.remove(path)
    
    def list_collections(self) -> list[str]:
        """列出所有集合"""
        return list(self._collections.keys())
    
    def heartbeat(self) -> int:
        """心跳 (返回当前时间戳)"""
        return int(__import__("time").time() * 1000)


# ══════════════════════════════════════════════════════════════
# 自检
# ══════════════════════════════════════════════════════════════

def _run_self_check():
    """自检: 验证核心API可用"""
    import tempfile
    import os
    
    print("=" * 60)
    print("📋 Chroma 自检 (28k⭐ 向量数据库)")
    print("=" * 60)
    
    # 1. 创建客户端 (内存模式)
    client = Client()
    assert client.heartbeat() > 0
    print("✅ 客户端创建/心跳")
    
    # 2. 创建集合
    col = client.create_collection("test_collection")
    assert col.name == "test_collection"
    assert col.count == 0
    print("✅ 创建集合")
    
    # 3. 添加向量 (自动嵌入)
    col.add(
        ids=["doc1", "doc2", "doc3"],
        documents=["机器学习是人工智能的一个分支",
                   "深度学习使用神经网络进行学习",
                   "Python是一种流行的编程语言"],
    )
    assert col.count == 3
    print(f"✅ add自动嵌入: {col.count}条记录")
    
    # 4. 语义查询
    results = col.query(query_texts=["人工智能"], n_results=2)
    assert len(results["ids"]) == 1  # 1条查询
    assert len(results["ids"][0]) == 2  # top-2
    top_id = results["ids"][0][0]
    assert top_id == "doc1", f"预期doc1最相关, 实际{top_id}"
    print(f"✅ 语义查询: top={top_id}, distance={results['distances'][0][0]:.4f}")
    
    # 5. 元数据
    col.add(ids=["doc4"], documents=["向量数据库"], metadatas=[{"category": "tech"}])
    results = col.query(query_texts=["数据库"], n_results=3, where={"category": "tech"})
    assert len(results["ids"][0]) == 1  # 只有doc4匹配category
    assert results["ids"][0][0] == "doc4"
    print(f"✅ 元数据过滤: {results['ids'][0]}")
    
    # 6. update/delete
    col.update(ids=["doc1"], documents=["机器学习是AI的子领域"])
    results = col.query(query_texts=["AI"])
    assert results["ids"][0][0] == "doc1"
    print(f"✅ update: top={results['ids'][0][0]}")
    
    col.delete(ids=["doc4"])
    assert col.count == 3
    print(f"✅ delete: count={col.count}")
    
    # 7. peek
    peeked = col.peek(2)
    assert len(peeked["ids"]) == 2
    print(f"✅ peek: {len(peeked['ids'])}条")
    
    # 8. get
    got = col.get(ids=["doc1"])
    assert len(got["ids"]) == 1
    print(f"✅ get: id={got['ids'][0]}")
    
    # 9. 多种距离度量
    col2 = client.create_collection("distance_test")
    col2.add(ids=["a", "b"], 
             embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
             documents=["x axis", "y axis"])
    # query默认cosine
    res = col2.query(query_embeddings=[[0.9, 0.1, 0.0]], n_results=2)
    assert res["ids"][0][0] == "a"
    print(f"✅ 余弦距离: top={res['ids'][0][0]}, dist={res['distances'][0][0]:.4f}")
    
    # 10. 持久化测试
    with tempfile.TemporaryDirectory() as tmpdir:
        persist_client = Client(persist_directory=tmpdir)
        pcol = persist_client.create_collection("persist_test")
        pcol.add(ids=["x", "y"], documents=["hello", "world"])
        pcol.persist()
        
        # 重新加载
        loaded = PersistentCollection.load("persist_test", tmpdir)
        assert loaded.count == 2
        print(f"✅ 持久化: loaded {loaded.count}条")
    
    # 11. 列表集合
    cols = client.list_collections()
    assert "test_collection" in cols
    assert "distance_test" in cols
    print(f"✅ 列表集合: {cols}")
    
    # 12. 删除集合
    client.delete_collection("distance_test")
    assert "distance_test" not in client.list_collections()
    print(f"✅ 删除集合")
    
    print(f"\n✅🎉 Chroma 自检通过 (12项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
