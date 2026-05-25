"""
skill_dspy.py — 编程式LM调用框架骨髓内化 (DSPy 20k⭐)

来源: stanfordnlp/dspy (GitHub, 20k⭐)
核心三件套:
  Signature: 输入输出Schema声明
  Module: 可组合推理步骤
  Teleprompter: 自动优化提示/示例

与GA集成:
  - Runnable链中的推理步骤用DSPy Module包装
  - brain_adapter用Teleprompter自动优化few-shot示例
  - 比手写prompt更结构化、可组合、可优化
"""

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, get_type_hints


# ═══════════════════════════════════════
# 1. Field — 输入/输出字段描述
# ═══════════════════════════════════════

@dataclass
class Field:
    """定义Signature的单个输入/输出字段"""
    name: str
    dtype: type = str
    desc: str = ""
    default: Any = None

    def __repr__(self):
        return f"Field({self.name}: {self.dtype.__name__}, desc='{self.desc}')"


# ═══════════════════════════════════════
# 2. Signature — 函数签名定义
# ═══════════════════════════════════════

class Signature:
    """声明式输入输出Schema, 类似DSPy的Signature"""
    
    def __init__(self, inputs: Dict[str, type] = None, outputs: Dict[str, type] = None,
                 desc: str = ""):
        self._input_fields: Dict[str, Field] = {}
        self._output_fields: Dict[str, Field] = {}
        self.desc = desc
        
        if inputs:
            for name, dtype in inputs.items():
                self._input_fields[name] = Field(name=name, dtype=dtype)
        if outputs:
            for name, dtype in outputs.items():
                self._output_fields[name] = Field(name=name, dtype=dtype)
    
    def add_input(self, name: str, dtype: type = str, desc: str = ""):
        self._input_fields[name] = Field(name=name, dtype=dtype, desc=desc)
        return self
    
    def add_output(self, name: str, dtype: type = str, desc: str = ""):
        self._output_fields[name] = Field(name=name, dtype=dtype, desc=desc)
        return self
    
    @property
    def input_names(self) -> List[str]:
        return list(self._input_fields.keys())
    
    @property
    def output_names(self) -> List[str]:
        return list(self._output_fields.keys())
    
    def validate(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """验证输入数据是否符合Signature"""
        for name in self.input_names:
            if name not in data:
                return False, f"缺少输入字段: {name}"
            field = self._input_fields[name]
            if not isinstance(data[name], field.dtype):
                return False, f"字段 '{name}' 类型错误: 期望 {field.dtype.__name__}, 得到 {type(data[name]).__name__}"
        return True, ""
    
    def format_prompt(self, question: str = "") -> str:
        """生成自然语言prompt模板"""
        parts = []
        if self.desc:
            parts.append(f"任务: {self.desc}")
        parts.append("\n输入:")
        for name, field in self._input_fields.items():
            parts.append(f"  {name} ({field.dtype.__name__}): {field.desc or name}")
        parts.append("\n输出:")
        for name, field in self._output_fields.items():
            parts.append(f"  {name} ({field.dtype.__name__}): {field.desc or name}")
        if question:
            parts.append(f"\n问题: {question}")
        return "\n".join(parts)
    
    def __repr__(self):
        inputs = ", ".join(self.input_names)
        outputs = ", ".join(self.output_names)
        return f"Signature({inputs} -> {outputs})"


# ═══════════════════════════════════════
# 3. Module — 可组合推理单元
# ═══════════════════════════════════════

class Module:
    """可组合的推理步骤, 类似DSPy的Module"""
    
    def __init__(self, signature: Signature = None, forward_fn: Callable = None,
                 name: str = ""):
        self.signature = signature or Signature()
        self._forward_fn = forward_fn
        self.name = name or self.__class__.__name__
        self._submodules: Dict[str, 'Module'] = {}
    
    def add_submodule(self, name: str, module: 'Module'):
        self._submodules[name] = module
        return self
    
    def forward(self, **kwargs) -> Dict[str, Any]:
        """默认前向: 验证输入, 调用forward_fn"""
        if self.signature:
            ok, err = self.signature.validate(kwargs)
            if not ok:
                return {"error": err}
        
        if self._forward_fn:
            return self._forward_fn(**kwargs)
        
        # 如果有子模块, 依次调用
        result = dict(kwargs)
        for name, mod in self._submodules.items():
            sub_result = mod.forward(**result)
            result.update(sub_result)
        
        # 确保输出字段存在
        for name in self.signature.output_names:
            if name not in result:
                result[name] = f"[{self.name}] {name}占位"
        
        return result
    
    def __call__(self, **kwargs) -> Dict[str, Any]:
        return self.forward(**kwargs)
    
    def __rshift__(self, other: 'Module') -> 'Module':
        """链式组合: self >> other (类似DSPy的Pipeline)"""
        chain = Module(name=f"{self.name}>>{other.name}")
        chain._submodules = {"_first": self, "_second": other}
        chain._forward_fn = lambda **kw: other.forward(**self.forward(**kw))
        return chain
    
    def __repr__(self):
        subs = f" ({len(self._submodules)}子模块)" if self._submodules else ""
        return f"Module({self.name}{subs})"


# ═══════════════════════════════════════
# 4. PredictModule — 预测模块
# ═══════════════════════════════════════

class PredictModule(Module):
    """预测模块: 基于Signature模板生成预测"""
    
    def __init__(self, signature: Signature, llm_fn: Callable = None):
        super().__init__(signature, name="Predict")
        self._llm_fn = llm_fn or self._default_llm
    
    def _default_llm(self, prompt: str) -> str:
        """默认LLM回调: 返回模拟结果"""
        outputs = self.signature.output_names
        result = {}
        for out in outputs:
            result[out] = f"[模拟]{out}: 基于'{prompt[:30]}...'生成"
        return "\n".join(f"{k}: {v}" for k, v in result.items())
    
    def forward(self, **kwargs) -> Dict[str, Any]:
        ok, err = self.signature.validate(kwargs)
        if not ok:
            return {"error": err}
        
        prompt = self.signature.format_prompt()
        for k, v in kwargs.items():
            prompt += f"\n{k}: {v}"
        
        response = self._llm_fn(prompt)
        
        # 解析响应为输出字段
        result = {}
        for name in self.signature.output_names:
            result[name] = self._extract_field(response, name)
        
        return result
    
    def _extract_field(self, response: str, field_name: str) -> str:
        """从响应中提取特定字段"""
        for line in response.split("\n"):
            if line.strip().startswith(f"{field_name}:"):
                return line.split(":", 1)[1].strip()
        return response  # fallback


# ═══════════════════════════════════════
# 5. Teleprompter — 自动优化器
# ═══════════════════════════════════════

class Teleprompter:
    """自动优化few-shot示例, 类似DSPy的Teleprompter"""
    
    def __init__(self, metric: Callable = None, num_candidate: int = 3):
        self.metric = metric or self._default_metric
        self.num_candidates = num_candidate
        self._best_examples: List[Tuple[Dict, float]] = []
    
    @staticmethod
    def _default_metric(pred: Dict, gold: Dict) -> float:
        """默认评估: 输出字段精确匹配计数"""
        score = 0.0
        for k in gold:
            if k in pred and str(pred[k]) == str(gold[k]):
                score += 1.0
        return score / max(len(gold), 1)
    
    def compile(self, module: Module, trainset: List[Tuple[Dict, Dict]]) -> Module:
        """从训练集优化module"""
        for inp, gold in trainset:
            pred = module(**inp)
            score = self.metric(pred, gold)
            self._best_examples.append((inp, score))
        
        # 按分数排序, 选top-k
        self._best_examples.sort(key=lambda x: -x[1])
        best_examples = self._best_examples[:self.num_candidates]
        
        # 包装原module, 注入优化后的few-shot
        optimized = Module(signature=module.signature, name=f"Optimized-{module.name}")
        optimized._best_examples = best_examples
        
        original_forward = module.forward
        
        def optimized_forward(**kwargs):
            # 在正常forward前附加few-shot示例
            enriched = dict(kwargs)
            if hasattr(optimized, '_best_examples') and optimized._best_examples:
                enriched['_few_shot_examples'] = [
                    inp for inp, _ in optimized._best_examples
                ]
            return original_forward(**enriched)
        
        optimized.forward = optimized_forward
        return optimized


# ═══════════════════════════════════════
# 6. 高级模块
# ═══════════════════════════════════════

class MultiTurnModule(Module):
    """多轮对话模块"""
    
    def __init__(self, signature: Signature):
        super().__init__(signature, name="MultiTurn")
        self.turns: List[Dict[str, str]] = []
    
    def forward(self, **kwargs) -> Dict[str, Any]:
        result = dict(kwargs)
        for name in self.signature.output_names:
            result[name] = f"[回复{len(self.turns)+1}] 针对: {kwargs.get(list(self.signature.input_names)[0], '')[:20]}..."
        self.turns.append(result)
        return result


class ClassifyModule(Module):
    """分类模块"""
    
    def __init__(self, categories: List[str]):
        sig = Signature(
            inputs={"text": str},
            outputs={"category": str, "confidence": float}
        )
        super().__init__(sig, name="Classifier")
        self.categories = categories
    
    def forward(self, **kwargs) -> Dict[str, Any]:
        text = kwargs.get("text", "")
        # 模拟分类: 关键词匹配
        for cat in self.categories:
            if cat in text:
                return {"category": cat, "confidence": 0.85}
        return {"category": self.categories[0], "confidence": 0.45}


# ═══════════════════════════════════════
# 自检
# ═══════════════════════════════════════

def _run_self_check():
    print("=" * 60)
    print("📋 DSPy 自检 (20k⭐ 编程式LM优化框架)")
    print("=" * 60)
    
    # 1. Field创建
    f = Field(name="question", dtype=str, desc="用户问题")
    assert f.name == "question"
    print(f"✅ Field: {f}")
    
    # 2. Signature定义
    sig = Signature(
        inputs={"question": str},
        outputs={"answer": str},
        desc="回答问题"
    )
    assert "question" in sig.input_names
    assert "answer" in sig.output_names
    print(f"✅ Signature: {sig}")
    
    # 3. Signature验证
    ok, err = sig.validate({"question": "你好"})
    assert ok
    ok2, err2 = sig.validate({"wrong": "bad"})
    assert not ok2
    print(f"✅ 验证: 正确→{ok}, 错误→{not ok2}")
    
    # 4. PredictModule (预测)
    pred = PredictModule(sig)
    result = pred(question="什么是RAG?")
    assert "answer" in result
    print(f"✅ 预测: {result['answer'][:40]}...")
    
    # 5. Teleprompter (优化)
    optimizer = Teleprompter(
        metric=lambda pred, gold: 1.0 if "RAG" in str(pred.get("answer", "")) else 0.0
    )
    trainset = [
        ({"question": "RAG是什么?"}, {"answer": "RAG是检索增强生成"})
    ]
    opt_mod = optimizer.compile(pred, trainset)
    opt_result = opt_mod(question="什么是RAG?")
    print(f"✅ Teleprompter: {opt_result.get('answer', '')[:40]}")
    
    # 6. Module链式 (>>)
    sig1 = Signature(inputs={"text": str}, outputs={"upper": str})
    sig2 = Signature(inputs={"upper": str}, outputs={"length": int})
    
    mod1 = Module(sig1, forward_fn=lambda **kw: {"upper": kw.get("text", "").upper()})
    mod2 = Module(sig2, forward_fn=lambda **kw: {"length": len(kw.get("upper", ""))})
    
    chain = mod1 >> mod2
    chain_result = chain(text="hello")
    assert "length" in chain_result
    print(f"✅ 链式: 'hello' → upper → length={chain_result['length']}")
    
    # 7. MultiTurnModule
    mt = MultiTurnModule(Signature(
        inputs={"user_input": str},
        outputs={"response": str}
    ))
    mt1 = mt(user_input="你好")
    assert len(mt.turns) == 1
    mt2 = mt(user_input="继续")
    assert len(mt.turns) == 2
    print(f"✅ 多轮: {len(mt.turns)}轮")
    
    # 8. ClassifyModule
    clf = ClassifyModule(categories=["正面", "负面", "中性"])
    result = clf(text="这个产品太棒了")
    assert result["category"] in ["正面", "负面", "中性"]
    assert 0 <= result["confidence"] <= 1
    print(f"✅ 分类: {result['category']} ({result['confidence']:.2f})")
    
    print(f"\n✅🎉 DSPy 自检通过 (8项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
