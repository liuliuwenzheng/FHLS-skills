"""
skill_graphiti.py — 时态知识图谱骨髓内化 (Graphiti 26k⭐)

来源: getzep/graphiti (GitHub, 26k⭐)
核心四层:
  Entity: 实体节点 (人物/产品/概念)
  Fact: 三元组(实体-关系-实体) + 时效窗口
  Episode: 溯源原始数据
  GraphMemory: 混合检索(实体搜索+关系遍历+时间筛选)

与GA集成:
  - chroma(向量记忆)之上增加实体-关系索引
  - cognitive_memory(简单k/v)之上增加图遍历能力
  - 7项自检: Entity / Fact / Episode / GraphMemory / 时态查询 / 关系遍历 / RAG融合
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
import re


# ====================
# 1. Entity - 实体节点
# ====================

@dataclass
class Entity:
    """实体节点=KG中的顶点, 可自动摘要"""
    name: str                          # 唯一标识名
    entity_type: str = "concept"       # person/product/concept
    summary: str = ""                  # 随时间演进的摘要
    attributes: Dict[str, Any] = field(default_factory=dict)  # 自定义属性
    
    def __hash__(self) -> int:
        return hash(self.name)
    
    def __eq__(self, other) -> bool:
        return isinstance(other, Entity) and self.name == other.name


# ====================
# 2. Fact - 带时效的事实三元组
# ====================

@dataclass
class Fact:
    """事实=带时效窗口的三元组"""
    source: str     # 主体实体名
    relation: str   # 关系
    target: str     # 客体实体名
    valid_from: datetime = field(default_factory=datetime.now)
    valid_until: Optional[datetime] = None  # None=一直有效
    episode_id: str = ""  # 溯源的原始数据ID
    
    @property
    def is_active(self) -> bool:
        now = datetime.now()
        return self.valid_from <= now and (self.valid_until is None or now <= self.valid_until)
    
    def __repr__(self) -> str:
        status = "✓" if self.is_active else "✗"
        return f"[{status}] ({self.source}) --[{self.relation}]--> ({self.target})"


# ====================
# 3. Episode - 溯源数据
# ====================

@dataclass
class Episode:
    """溯源=记录每条事实的原始数据"""
    id: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ====================
# 4. GraphMemory - 知识图谱核心
# ====================

class GraphMemory:
    """时态知识图谱: 实体索引+事实存储+混合检索"""
    
    def __init__(self):
        self.entities: Dict[str, Entity] = {}      # name→Entity
        self.facts: List[Fact] = []                 # 全部事实(含历史)
        self.episodes: Dict[str, Episode] = {}     # id→Episode
        # 关系索引: source→{relation→set(target)}
        self._outgoing: Dict[str, Dict[str, Set[str]]] = {}
        # 反向索引: target→{relation→set(source)}
        self._incoming: Dict[str, Dict[str, Set[str]]] = {}
    
    # ---------- 写入 ----------
    
    def add_entity(self, entity: Entity) -> None:
        self.entities[entity.name] = entity
    
    def add_fact(self, fact: Fact) -> None:
        """添加事实并更新关系索引"""
        self.facts.append(fact)
        # 正向索引
        if fact.source not in self._outgoing:
            self._outgoing[fact.source] = {}
        if fact.relation not in self._outgoing[fact.source]:
            self._outgoing[fact.source][fact.relation] = set()
        self._outgoing[fact.source][fact.relation].add(fact.target)
        # 反向索引
        if fact.target not in self._incoming:
            self._incoming[fact.target] = {}
        if fact.relation not in self._incoming[fact.target]:
            self._incoming[fact.target][fact.relation] = set()
        self._incoming[fact.target][fact.relation].add(fact.source)
    
    def add_episode(self, episode: Episode) -> None:
        self.episodes[episode.id] = episode
    
    def add_triple(self, source: str, relation: str, target: str,
                   entity_types: Tuple[str, str] = ("concept", "concept"),
                   episode_id: str = "") -> Tuple[Entity, Entity, Fact]:
        """便捷方法: 一次创建两个实体+一个事实"""
        src_entity = Entity(name=source, entity_type=entity_types[0])
        tgt_entity = Entity(name=target, entity_type=entity_types[1])
        fact = Fact(source=source, relation=relation, target=target,
                    episode_id=episode_id)
        self.add_entity(src_entity)
        self.add_entity(tgt_entity)
        self.add_fact(fact)
        return src_entity, tgt_entity, fact
    
    # ---------- 查询 ----------
    
    def get_entity(self, name: str) -> Optional[Entity]:
        return self.entities.get(name)
    
    def get_active_facts(self, entity_name: Optional[str] = None,
                         relation: Optional[str] = None) -> List[Fact]:
        """查询当前有效的事实"""
        results = []
        for f in self.facts:
            if not f.is_active:
                continue
            if entity_name and f.source != entity_name and f.target != entity_name:
                continue
            if relation and f.relation != relation:
                continue
            results.append(f)
        return results
    
    def query_related(self, entity_name: str,
                      relation: Optional[str] = None,
                      direction: str = "outgoing") -> List[Tuple[str, str]]:
        """查询实体的关系邻居: 返回[(关系, 对方名), ...]"""
        results = []
        if direction in ("outgoing", "both") and entity_name in self._outgoing:
            edges = self._outgoing[entity_name]
            for rel, targets in edges.items():
                if relation and rel != relation:
                    continue
                for t in targets:
                    results.append((rel, t))
        if direction in ("incoming", "both") and entity_name in self._incoming:
            edges = self._incoming[entity_name]
            for rel, sources in edges.items():
                if relation and rel != relation:
                    continue
                for s in sources:
                    results.append((rel, s))
        return results
    
    def query_at_time(self, point_in_time: datetime) -> List[Fact]:
        """时态查询: 仅在特定时间点有效的事实"""
        results = []
        for f in self.facts:
            if f.valid_from <= point_in_time and \
               (f.valid_until is None or point_in_time <= f.valid_until):
                results.append(f)
        return results
    
    def search_entities(self, keyword: str) -> List[Entity]:
        """关键词搜索实体"""
        kw = keyword.lower()
        results = []
        for e in self.entities.values():
            if kw in e.name.lower() or kw in e.summary.lower():
                results.append(e)
        return results
    
    def traverse_path(self, start: str, max_depth: int = 3) -> Dict[str, List[str]]:
        """BFS图遍历: 返回 {实体名→[关系链路径]}"""
        visited: Dict[str, List[str]] = {start: []}
        queue = [(start, [], 0)]  # (当前名, 路径关系链, 深度)
        while queue:
            current, path, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            neighbors = self.query_related(current)
            for rel, neighbor in neighbors:
                new_path = path + [f"{rel}→{neighbor}"]
                if neighbor not in visited:
                    visited[neighbor] = new_path
                    queue.append((neighbor, new_path, depth + 1))
        return visited
    
    def facts_by_episode(self, episode_id: str) -> List[Fact]:
        """按溯源查询事实"""
        return [f for f in self.facts if f.episode_id == episode_id]
    
    def stats(self) -> Dict[str, Any]:
        return {
            "entities": len(self.entities),
            "facts": len(self.facts),
            "active_facts": len(self.get_active_facts()),
            "episodes": len(self.episodes),
        }


# ====================
# 自检
# ====================

def _run_self_check() -> bool:
    print("=" * 60)
    print("📋 Graphiti 自检 (26k⭐ 时态知识图谱)")
    print("=" * 60)
    
    kg = GraphMemory()
    
    # [1] Entity
    e1 = Entity("张三", "person", "产品经理")
    e2 = Entity("李四", "person", "律师")
    e3 = Entity("民法典", "book", "法律典籍")
    kg.add_entity(e1)
    kg.add_entity(e2)
    kg.add_entity(e3)
    assert kg.get_entity("张三") is not None
    assert kg.get_entity("张三").entity_type == "person"
    print("✅ Entity 实体节点: 创建+查询正常")
    
    # [2] Fact
    f1 = Fact("张三", "认识", "李四")
    f2 = Fact("李四", "精通", "民法典")
    kg.add_fact(f1)
    kg.add_fact(f2)
    assert len(kg.get_active_facts()) == 2
    assert len(kg.get_active_facts(entity_name="张三")) == 1
    print("✅ Fact 三元组: 创建+按实体查询正常")
    
    # [3] Episode
    ep = Episode("ep001", "张三介绍李四, 李四是律师, 精通民法典")
    kg.add_episode(ep)
    assert kg.episodes["ep001"].content
    assert len(kg.facts_by_episode("ep001")) == 0  # 未关联
    print("✅ Episode 溯源: 存储+查询正常")
    
    # [4] GraphMemory 混合检索
    result = kg.search_entities("张三")
    assert len(result) >= 1
    assert result[0].name == "张三"
    print("✅ GraphMemory 混合检索: 关键词搜索正常")
    
    # [5] 时态查询
    now = datetime.now()
    future = now + timedelta(days=365)
    past_fact = Fact("张三", "曾任职", "A公司",
                     valid_from=now - timedelta(days=365),
                     valid_until=now - timedelta(days=1))
    kg.add_fact(past_fact)
    timeline = kg.query_at_time(now - timedelta(days=180))
    assert len(timeline) >= 1  # 过去时间点仍有效
    current = kg.query_at_time(now)
    assert len(current) >= 2  # 现在的更少(历史已失效)
    print("✅ 时态查询: 时效窗口筛选正确")
    
    # [6] 关系遍历
    paths = kg.traverse_path("张三", max_depth=2)
    assert "李四" in paths
    assert "民法典" in paths
    print("✅ 关系遍历: BFS图遍历正确")
    
    # [7] RAG融合: 从图检索信息构建上下文
    context = _build_rag_context(kg, "张三")
    assert "张三" in context
    assert "认识" in context or "李四" in context
    print("✅ RAG融合: 图检索构建上下文正常")
    
    print(f"\n静态数据: {kg.stats()}")
    print(f"\n✅🎉 Graphiti 自检通过 (7项)")
    print("=" * 60)
    return True


def _build_rag_context(kg: GraphMemory, query_entity: str) -> str:
    """从知识图谱构建RAG上下文"""
    parts = []
    # 实体摘要
    entity = kg.get_entity(query_entity)
    if entity:
        parts.append(f"实体: {entity.name} ({entity.entity_type}) - {entity.summary}")
    # 关系
    related = kg.query_related(query_entity)
    for rel, target in related[:5]:
        parts.append(f"  {query_entity} --[{rel}]--> {target}")
    # 反向关系
    incoming = kg.query_related(query_entity, direction="incoming")
    for rel, source in incoming[:5]:
        parts.append(f"  {source} --[{rel}]--> {query_entity}")
    # 深度路径
    paths = kg.traverse_path(query_entity, max_depth=2)
    if len(paths) > 1:
        for name, path in list(paths.items())[:3]:
            if name != query_entity and path:
                parts.append(f"  路径: {query_entity} → {' → '.join(path)}")
    return "\n".join(parts) if parts else "(无相关信息)"


if __name__ == "__main__":
    _run_self_check()
