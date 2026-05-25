"""
skill_runnable.py — Runnable协议骨髓内化 (LangChain 100k⭐核心)

骨髓内化原则: 只取LangChain最精华的Runnable接口(Chain of Thought的核心骨架)
- Runnable: 可组合的调用单元 (类似LangChain的RunnableLambda/RunnableSequence)
- Chain: 同步/异步链式调用
- Tool: 工具接口 (类似LangChain的Tool/BaseTool)
- 零依赖: 纯Python, 可import

与GA的集成点:
- action_registry.py: 动作用Runnable包装, 支持链式组合
- brain_adapter.py: 推理步骤用RunnableSequence编排
- skill_chroma.py: 搜索流程用RunnablePipeline
"""

import inspect
import functools
from typing import Any, Callable, Optional
from dataclasses import dataclass, field


# ══════════════════════════════════════════════════════════════
# Runnable接口 (核心抽象)
# ══════════════════════════════════════════════════════════════

class Runnable:
    """可组合调用单元
    
    LangChain v0.3 Runnable协议的精简版:
      runnable.invoke(input) → output
      runnable | other_runnable → RunnableSequence
    """
    
    def invoke(self, input: Any) -> Any:
        raise NotImplementedError
    
    def batch(self, inputs: list[Any]) -> list[Any]:
        return [self.invoke(inp) for inp in inputs]
    
    def __or__(self, other: "Runnable") -> "RunnableSequence":
        return RunnableSequence(self, other)
    
    def __ror__(self, other: "Runnable") -> "RunnableSequence":
        return RunnableSequence(other, self)
    
    def pipe(self, *others: "Runnable") -> "RunnableSequence":
        """类似LangChain的pipe方法: runnable.pipe(fn1, fn2)"""
        return functools.reduce(lambda a, b: a | b, others, self)
    
    def __call__(self, input: Any) -> Any:
        return self.invoke(input)


class RunnableLambda(Runnable):
    """函数式Runnable: lambda/invoke包装为Runnable"""
    
    def __init__(self, func: Callable):
        self.func = func
    
    def invoke(self, input: Any) -> Any:
        # 支持带单个参数或多个参数
        sig = inspect.signature(self.func)
        params = list(sig.parameters.keys())
        if len(params) == 1:
            return self.func(input)
        elif len(params) == 2 and isinstance(input, dict):
            return self.func(**input)
        return self.func(input)
    
    def __repr__(self):
        name = getattr(self.func, '__name__', 'lambda')
        return f"RunnableLambda({name})"


class RunnableSequence(Runnable):
    """链式Runnable: A | B → A.invoke(x) → B.invoke(result)"""
    
    def __init__(self, *steps: Runnable | Callable):
        self.steps = [s if isinstance(s, Runnable) else RunnableLambda(s) for s in steps]
    
    def invoke(self, input: Any) -> Any:
        result = input
        for step in self.steps:
            result = step.invoke(result)
        return result
    
    def __or__(self, other: Runnable | Callable) -> "RunnableSequence":
        other_r = other if isinstance(other, Runnable) else RunnableLambda(other)
        return RunnableSequence(*self.steps, other_r)
    
    def __len__(self):
        return len(self.steps)
    
    def __repr__(self):
        return " | ".join(repr(s) for s in self.steps)


class RunnableParallel(Runnable):
    """并行Runnable: 同时运行多个分支, 结果合并为dict"""
    
    def __init__(self, **branches: Runnable | Callable):
        self.branches = {
            k: v if isinstance(v, Runnable) else RunnableLambda(v) 
            for k, v in branches.items()
        }
    
    def invoke(self, input: Any) -> dict[str, Any]:
        return {k: branch.invoke(input) for k, branch in self.branches.items()}
    
    def __repr__(self):
        names = ", ".join(self.branches.keys())
        return f"RunnableParallel({names})"


class RunnablePassthrough(Runnable):
    """透传Runnable: 不做任何事, 传递输入 (用于调试/分支)"""
    
    def invoke(self, input: Any) -> Any:
        return input
    
    def __repr__(self):
        return "RunnablePassthrough()"


class RunnableMap(Runnable):
    """映射Runnable: 对列表每个元素执行fn"""
    
    def __init__(self, fn: Runnable | Callable):
        self.fn = fn if isinstance(fn, Runnable) else RunnableLambda(fn)
    
    def invoke(self, input: list) -> list:
        return [self.fn.invoke(item) for item in input]
    
    def __repr__(self):
        return f"RunnableMap({self.fn})"


class RunnableBranch(Runnable):
    """条件分支: 类似LangChain的RunnableBranch
    
    用法:
        branch = RunnableBranch(
            (lambda x: x > 0, lambda x: f"positive: {x}"),
            (lambda x: x == 0, lambda x: "zero"),
            default=lambda x: f"negative: {x}",
        )
    """
    
    def __init__(self, *conditions: tuple[Callable, Runnable | Callable], 
                 default: Runnable | Callable = None):
        self.conditions = []
        for cond, fn in conditions:
            r = fn if isinstance(fn, Runnable) else RunnableLambda(fn)
            self.conditions.append((cond, r))
        self.default = default if isinstance(default, Runnable) else RunnableLambda(default) if default else RunnablePassthrough()
    
    def invoke(self, input: Any) -> Any:
        for condition, runnable in self.conditions:
            if condition(input):
                return runnable.invoke(input)
        return self.default.invoke(input)
    
    def __repr__(self):
        return f"RunnableBranch({len(self.conditions)} conditions)"


# ══════════════════════════════════════════════════════════════
# Tool 接口
# ══════════════════════════════════════════════════════════════

@dataclass
class Tool:
    """工具定义 (类似LangChain的BaseTool)"""
    name: str
    description: str
    func: Callable
    args_schema: Optional[dict] = None
    
    def invoke(self, **kwargs) -> Any:
        return self.func(**kwargs)
    
    def __call__(self, **kwargs) -> Any:
        return self.invoke(**kwargs)
    
    def __repr__(self):
        return f"Tool({self.name}: {self.description[:30]})"


class ToolRegistry:
    """工具注册表 (管理多个Tool)"""
    
    def __init__(self):
        self._tools: dict[str, Tool] = {}
    
    def register(self, tool: Tool):
        self._tools[tool.name] = tool
    
    def unregister(self, name: str):
        self._tools.pop(name, None)
    
    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"工具 '{name}' 未注册")
        return self._tools[name]
    
    def list(self) -> list[str]:
        return list(self._tools.keys())
    
    def as_runnable(self) -> Runnable:
        """返回一个可选的Runnable"""
        return RunnableLambda(lambda input: self._dispatch(input))
    
    def _dispatch(self, input: dict) -> Any:
        name = input.get("name", "")
        args = input.get("args", {})
        tool = self.get(name)
        return tool.invoke(**args)
    
    @property
    def count(self) -> int:
        return len(self._tools)


# ══════════════════════════════════════════════════════════════
# Chain 相关 (高级组合)
# ══════════════════════════════════════════════════════════════

class Chain:
    """LLM链 (简化版LangChain Chain)"""
    
    def __init__(self, runnable: Runnable):
        self.runnable = runnable
    
    def invoke(self, input: Any) -> Any:
        return self.runnable.invoke(input)
    
    @staticmethod
    def from_template(template: str, **mapping: Runnable) -> "Chain":
        """从模板创建Chain (类似LangChain的LLMChain)"""
        # 简版字符串格式化
        def format_fn(inputs: dict) -> str:
            return template.format(**inputs)
        
        # 如果mapping为空, 直接format
        if not mapping:
            runnable = RunnableLambda(format_fn)
        else:
            # 并行提取各字段, 合并后format
            parallel = RunnableParallel(**mapping)
            runnable = parallel | RunnableLambda(format_fn)
        
        return Chain(runnable)


# ══════════════════════════════════════════════════════════════
# 自检 (15项全覆盖)
# ══════════════════════════════════════════════════════════════

def _run_self_check():
    print("=" * 60)
    print("📋 Runnable/Chain 自检 (LangChain 100k⭐ 核心协议)")
    print("=" * 60)
    
    # 1. RunnableLambda
    rl = RunnableLambda(lambda x: x * 2)
    assert rl.invoke(3) == 6, "RunnableLambda基本调用"
    print(f"✅ RunnableLambda: 3→{rl.invoke(3)}")
    
    # 2. RunnableSequence (| 操作符)
    rs = RunnableLambda(lambda x: x + 1) | RunnableLambda(lambda x: x * 2)
    assert rs.invoke(5) == 12, f"Sequence: 5→12, 实际{rs.invoke(5)}"
    print(f"✅ RunnableSequence(|): 5+1→6*2={rs.invoke(5)}")
    
    # 3. 链式pipe
    rp = RunnableLambda(lambda x: x * 10).pipe(
        RunnableLambda(lambda x: x / 2),
        RunnableLambda(lambda x: str(x))
    )
    assert rp.invoke(4) == "20.0", f"pipe: 4→{rp.invoke(4)}"
    print(f"✅ RunnablePipe: 4*10→/2→str={rp.invoke(4)}")
    
    # 4. RunnableParallel
    rpar = RunnableParallel(
        double=lambda x: x * 2,
        triple=lambda x: x * 3,
        square=lambda x: x ** 2,
    )
    result = rpar.invoke(5)
    assert result == {"double": 10, "triple": 15, "square": 25}, f"parallel: {result}"
    print(f"✅ RunnableParallel: 5→{result}")
    
    # 5. RunnablePassthrough
    rpt = RunnablePassthrough()
    assert rpt.invoke("test") == "test"
    print(f"✅ RunnablePassthrough: '{rpt.invoke('test')}'")
    
    # 6. RunnableBranch (条件分支)
    branch = RunnableBranch(
        (lambda x: x > 0, lambda x: f"positive:{x}"),
        (lambda x: x == 0, lambda x: "zero"),
        default=lambda x: f"negative:{x}",
    )
    assert branch.invoke(5) == "positive:5"
    assert branch.invoke(0) == "zero"
    assert branch.invoke(-3) == "negative:-3"
    print(f"✅ RunnableBranch: 5→{branch.invoke(5)}, 0→{branch.invoke(0)}, -3→{branch.invoke(-3)}")
    
    # 7. RunnableMap
    rmap = RunnableMap(lambda x: x.upper())
    assert rmap.invoke(["a", "b", "c"]) == ["A", "B", "C"]
    print(f"✅ RunnableMap: {rmap.invoke(['a', 'b', 'c'])}")
    
    # 8. 链式组合(多种操作符)
    pipeline = (
        RunnableLambda(lambda x: x.lower())
        | RunnableLambda(lambda x: x.replace(" ", "_"))
        | RunnableLambda(lambda x: f"slug:{x}")
    )
    assert pipeline.invoke("Hello World") == "slug:hello_world"
    print(f"✅ 链式组合: '{pipeline.invoke('Hello World')}'")
    
    # 9. Tool创建
    def search_tool(query: str) -> str:
        return f"搜索: {query}"
    
    tool = Tool(name="search", description="搜索引擎工具", func=search_tool)
    assert tool.invoke(query="GA") == "搜索: GA"
    print(f"✅ Tool: {tool.name}→{tool.invoke(query='GA')}")
    
    # 10. ToolRegistry
    registry = ToolRegistry()
    registry.register(tool)
    registry.register(Tool("calc", "计算器", lambda x, y: x + y))
    assert registry.count == 2
    assert "search" in registry.list()
    print(f"✅ ToolRegistry: {registry.list()} ({registry.count}个)")
    
    # 11. ToolRegistry dispatch
    tool_result = registry._dispatch({"name": "calc", "args": {"x": 3, "y": 7}})
    assert tool_result == 10
    print(f"✅ ToolRegistry dispatch: calc(3,7)={tool_result}")
    
    # 12. Chain from_template
    chain = Chain.from_template(
        "用户说: {query}, 回答: {response}",
    )
    result = chain.invoke({"query": "你好", "response": "世界"})
    assert result == "用户说: 你好, 回答: 世界"
    print(f"✅ Chain template: '{result}'")
    
    # 13. Chain with mapping
    chain2 = Chain.from_template(
        "全名: {first} {last}",
        first=RunnableLambda(lambda x: x["firstname"]),
        last=RunnableLambda(lambda x: x["lastname"]),
    )
    result2 = chain2.invoke({"firstname": "John", "lastname": "Doe"})
    assert result2 == "全名: John Doe"
    print(f"✅ Chain with mapping: '{result2}'")
    
    # 14. 序列长度
    seq = RunnableLambda(lambda x: x) | RunnableLambda(lambda x: x) | RunnableLambda(lambda x: x)
    assert len(seq) == 3
    print(f"✅ 序列长度: {len(seq)}")
    
    # 15. batch处理
    batch = RunnableLambda(lambda x: x * 2)
    results = batch.batch([1, 2, 3, 4])
    assert results == [2, 4, 6, 8]
    print(f"✅ batch: {results}")
    
    print(f"\n✅🎉 Runnable 自检通过 (15项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
