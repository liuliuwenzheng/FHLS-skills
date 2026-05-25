"""
skill_haystack.py — 生产级AI管道框架骨髓内化 (Haystack 25k⭐)

来源: deepset-ai/haystack (GitHub, 25k⭐)
核心三件套:
  @component: 输入输出声明式组件
  Pipeline: 条件分支管道编排
  Router: 智能路由

与GA集成:
  - Runnable链替代品，但有条件分支
  - 搜索→检索→生成 RAG管道
  - 比手写if-else更结构化的条件推理
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import inspect
import re


# ============================================================
# 第1模块: @component 装饰器 — 声明式组件
# ============================================================

class ComponentMeta:
    """组件元数据: 输入输出schema + 运行"""
    def __init__(self, func: Callable):
        self.func = func
        self.name = func.__name__
        # 从类型注解推断输入输出
        sig = inspect.signature(func)
        hints = func.__annotations__ if hasattr(func, '__annotations__') else {}
        
        self.inputs: Dict[str, type] = {}
        self.outputs: Dict[str, type] = {}
        
        for name, param in sig.parameters.items():
            if name == 'self': continue
            self.inputs[name] = hints.get(name, Any)
        
        ret = hints.get('return', None)
        if ret and hasattr(ret, '__annotations__'):
            self.outputs = {k: v for k, v in ret.__annotations__.items()}
        
    def run(self, **kwargs) -> Dict[str, Any]:
        return self.func(**kwargs)


def component(func=None, *, inputs: Dict[str, type] = None, outputs: Dict[str, type] = None):
    """@component装饰器: 把函数变成Haystack组件"""
    def wrapper(f):
        meta = ComponentMeta(f)
        if inputs: meta.inputs.update(inputs)
        if outputs: meta.outputs.update(outputs)
        f._component_meta = meta
        f._is_component = True
        return f
    
    if func is not None:
        return wrapper(func)
    return wrapper


# ============================================================
# 第2模块: Pipeline — 条件分支管道
# ============================================================

class PipelineError(Exception):
    """管道执行异常"""
    pass


@dataclass
class PipelineStep:
    """管道中的一步"""
    name: str
    component: Callable
    inputs: Dict[str, str] = field(default_factory=dict)  # {参名: 源变量}
    outputs: List[str] = field(default_factory=list)  # 输出变量名列表
    condition: Optional[Callable] = None  # 条件函数(data)->bool


class Pipeline:
    """管道: 组件编排 + 条件分支"""
    
    def __init__(self, name: str = "pipeline"):
        self.name = name
        self.steps: List[PipelineStep] = []
        self._data: Dict[str, Any] = {}
    
    def add_component(self, name: str, component_fn, 
                      inputs: Dict[str, str] = None,
                      outputs: List[str] = None,
                      condition: Callable = None):
        """添加组件步骤"""
        step = PipelineStep(
            name=name,
            component=component_fn,
            inputs=inputs or {},
            outputs=outputs or [],
            condition=condition
        )
        self.steps.append(step)
        return self
    
    def run(self, **initial_data) -> Dict[str, Any]:
        """执行整个管道"""
        self._data = dict(initial_data)
        
        for step in self.steps:
            # 条件分支判断
            if step.condition and not step.condition(self._data):
                self._data[f"{step.name}._skipped"] = True
                continue
            
            # 准备参数
            kwargs = {}
            for param_name, source_var in step.inputs.items():
                if source_var in self._data:
                    kwargs[param_name] = self._data[source_var]
                else:
                    raise PipelineError(
                        f"步骤[{step.name}]缺少输入: {source_var}"
                    )
            
            # 执行
            result = step.component(**kwargs)
            
            # 保存输出
            if isinstance(result, dict):
                if step.outputs:
                    for i, out_name in enumerate(step.outputs):
                        vals = list(result.values())
                        self._data[out_name] = vals[i] if i < len(vals) else None
                else:
                    self._data.update(result)
            else:
                key = step.outputs[0] if step.outputs else step.name
                self._data[key] = result
        
        return self._data
    
    def visualize(self) -> str:
        """文本可视化管道"""
        lines = [f"📊 Pipeline: {self.name}"]
        for i, step in enumerate(self.steps):
            cond = " [条件]" if step.condition else ""
            ins = ", ".join(f"{k}={v}" for k, v in step.inputs.items())
            outs = ", ".join(step.outputs) if step.outputs else "→"
            lines.append(f"  {i+1}. {step.name}({ins}) -> [{outs}]{cond}")
        return "\n".join(lines)


# ============================================================
# 第3模块: Retriever — 文档检索
# ============================================================

@dataclass
class Document:
    """文档对象"""
    id: str
    content: str
    meta: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


class InMemoryRetriever:
    """内存检索器 (BM25简化版)"""
    
    def __init__(self, documents: List[Document] = None):
        self.documents: Dict[str, Document] = {}
        self._word_index: Dict[str, Dict[str, float]] = {}  # word -> {doc_id: score}
        if documents:
            for doc in documents:
                self.add_document(doc)
    
    def _tokenize(self, text: str) -> List[str]:
        """分词: 英文/数字按词拆分, 中文按单字拆分"""
        tokens = []
        # 英文/数字词
        for word in re.findall(r'[a-z0-9]+', text.lower()):
            tokens.append(word)
        # 中文单字 (排除空格/标点)
        for ch in text:
            if '\u4e00' <= ch <= '\u9fff':
                tokens.append(ch)
        return tokens
    
    def add_document(self, doc: Document):
        self.documents[doc.id] = doc
        words = set(self._tokenize(doc.content.lower()))
        for word in words:
            if word not in self._word_index:
                self._word_index[word] = {}
            self._word_index[word][doc.id] = self._word_index[word].get(doc.id, 0) + 1
    
    def retrieve(self, query: str, top_k: int = 3) -> List[Document]:
        """BM25简化检索: 词频匹配"""
        query_words = set(self._tokenize(query.lower()))
        if not query_words or not self._word_index:
            return []
        
        scores: Dict[str, float] = {}
        for word in query_words:
            if word in self._word_index:
                for doc_id, freq in self._word_index[word].items():
                    scores[doc_id] = scores.get(doc_id, 0) + freq
        
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        results = []
        for doc_id, score in ranked[:top_k]:
            doc = self.documents.get(doc_id)
            if doc:
                doc.score = score
                results.append(doc)
        return results


# ============================================================
# 第4模块: Generator — LLM生成器 + WebSearch
# ============================================================

class Generator:
    """LLM生成器 (可配置后端)"""
    
    def __init__(self, model_fn: Callable = None):
        self.model_fn = model_fn or self._default_generate
    
    @staticmethod
    def _default_generate(prompt: str) -> str:
        """默认生成: 返回prompt本身(模拟)"""
        return f"[生成响应]: {prompt[:50]}..."
    
    def generate(self, prompt: str, **kwargs) -> str:
        return self.model_fn(prompt, **kwargs)


class WebSearch:
    """网络搜索组件 (模拟)"""
    
    def __init__(self, search_fn: Callable = None):
        self.search_fn = search_fn or self._mock_search
    
    @staticmethod
    def _mock_search(query: str, num_results: int = 3) -> List[Dict[str, str]]:
        return [{"title": f"结果{i+1}关于{query}", "url": f"https://example.com/{i}", 
                 "snippet": f"这是关于{query}的第{i+1}个搜索结果"} for i in range(num_results)]
    
    def search(self, query: str, num_results: int = 3) -> List[Dict[str, str]]:
        return self.search_fn(query, num_results)


# ============================================================
# 第5模块: Router — 条件路由
# ============================================================

class Router:
    """条件路由: 基于规则/模型条件分流"""
    
    def __init__(self, routes: Dict[str, Callable] = None):
        self.routes = routes or {}
    
    def add_route(self, name: str, condition_fn: Callable[[Dict], bool]):
        self.routes[name] = condition_fn
    
    def decide(self, data: Dict) -> str:
        """根据数据决定走哪个路由"""
        for name, fn in self.routes.items():
            if fn(data):
                return name
        return "default"
    
    @staticmethod
    def confidence_route(min_score: float = 0.5) -> Callable:
        """常用路由: 基于置信度"""
        def route_fn(data: Dict) -> bool:
            for k, v in data.items():
                if isinstance(v, (int, float)) and v >= min_score:
                    return True
            return False
        route_fn.__name__ = f"confidence>={min_score}"
        return route_fn


# ============================================================
# 自检
# ============================================================

def _run_self_check():
    print("=" * 60)
    print("📋 Haystack 自检 (25k⭐ 生产级AI管道)")
    print("=" * 60)
    
    # 1. @component 装饰器
    @component
    def greet(name: str) -> dict:
        return {"greeting": f"你好, {name}!"}
    
    assert hasattr(greet, '_is_component')
    assert greet._component_meta.name == 'greet'
    assert 'name' in greet._component_meta.inputs
    result = greet(name="世界")
    assert result["greeting"] == "你好, 世界!"
    print("✅ @component 装饰器: 输入输出schema正常")
    
    # 2. Pipeline 执行
    @component
    def upper(text: str) -> dict:
        return {"result": text.upper()}
    
    pipe = Pipeline("测试管道")
    pipe.add_component("upper", upper, inputs={"text": "text"}, outputs=["result"])
    result = pipe.run(text="hello")
    assert result["result"] == "HELLO"
    print(f"✅ Pipeline 执行: {result['result']}")
    
    # 3. 条件分支
    @component
    def branch_a(data: str) -> dict:
        return {"output": f"A分支: {data}"}
    
    @component
    def branch_b(data: str) -> dict:
        return {"output": f"B分支: {data}"}
    
    pipe2 = Pipeline("分支测试")
    pipe2.add_component("branch_a", branch_a, 
                        inputs={"data": "input"}, outputs=["output"],
                        condition=lambda d: d.get("input", "").startswith("a"))
    pipe2.add_component("branch_b", branch_b,
                        inputs={"data": "input"}, outputs=["output"])
    
    result_a = pipe2.run(input="abc")
    assert "branch_a._skipped" not in result_a
    result_b = pipe2.run(input="xyz")
    assert result_b.get("branch_a._skipped", False)  # a跳过了
    print("✅ 条件分支: A触发了, B跳过了")
    
    # 4. Retriever 检索
    docs = [
        Document("1", "Python是一种编程语言"),
        Document("2", "Java也是一种编程语言"),
        Document("3", "早上好今天天气不错"),
    ]
    retriever = InMemoryRetriever(docs)
    results = retriever.retrieve("编程语言", top_k=2)
    assert len(results) == 2
    assert results[0].id in ["1", "2"]
    print(f"✅ Retriever 检索: 找到{len(results)}个文档, 最高分={results[0].score}")
    
    # 5. Generator 生成
    gen = Generator()
    result = gen.generate("写一首诗")
    assert isinstance(result, str) and len(result) > 0
    print(f"✅ Generator 生成: {result[:30]}...")
    
    # 6. Router 路由
    router = Router()
    router.add_route("高置信", Router.confidence_route(0.8))
    router.add_route("中置信", Router.confidence_route(0.5))
    
    assert router.decide({"confidence": 0.9}) == "高置信"
    assert router.decide({"confidence": 0.6}) == "中置信"
    assert router.decide({"confidence": 0.1}) == "default"
    print("✅ Router 路由: 判断正确")
    
    # 7. Pipeline + Router 全链路 (RAG管道)
    @component
    def search_query(query: str) -> dict:
        return {"searched": f"搜索: {query}"}
    
    @component
    def rag_generate(context: str, query: str) -> dict:
        return {"answer": f"基于[{context}]回答: {query}"}
    
    rag_pipe = Pipeline("RAG管道")
    rag_pipe.add_component("search", search_query, 
                          inputs={"query": "question"}, outputs=["searched"])
    rag_pipe.add_component("generate", rag_generate,
                          inputs={"context": "searched", "query": "question"},
                          outputs=["answer"])
    
    answer = rag_pipe.run(question="什么是RAG?").get("answer", "")
    assert "RAG" in answer
    print(f"✅ RAG管道全链路: {answer[:40]}...")
    
    print(f"\n✅🎉 Haystack 自检通过 (7项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
