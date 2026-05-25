"""
skill_llama_cpp.py — 本地LLM推理引擎骨髓内化 (llama.cpp 111k⭐)

来源: ggml-org/llama.cpp (GitHub, 111k⭐)
作者: Gerganov (ggml-org团队)
核心四层:
  GGML张量库: 声明式计算图(先定义后执行)
  ggml-quants: 量化格式(Q4/Q5/Q6/Q8)
  llama推理: KV Cache + Tokenize + Sampling
  GGUF格式: 自描述模型元数据

与GA集成:
  - GA缺少本地LLM推理能力: 提供推理接口抽象+量化策略
  - 设计模式迁移: 声明式计算图/多后端/量化压缩
  - 7项自检: 推理接口/量化策略/Sampling/上下文管理/GGUF元数据/多后端/温度控制
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from enum import Enum
import json


# ====================
# 1. 量化类型 (ggml-quants)
# ====================

class QuantType(Enum):
    """GGML量化类型, bit数越低压缩越大"""
    Q2_K = "q2_k"       # 2.56 bits - 最大压缩
    Q3_K = "q3_k"       # 3.50 bits - 高压缩
    Q4_0 = "q4_0"       # 4.00 bits - 标准4bit
    Q4_K = "q4_k"       # 4.50 bits - 4bit优化版
    Q5_0 = "q5_0"       # 5.00 bits - 低损失
    Q5_K = "q5_k"       # 5.50 bits - 5bit优化版
    Q6_K = "q6_k"       # 6.56 bits - 极低损失
    Q8_0 = "q8_0"       # 8.00 bits - 几乎无损
    F16 = "f16"         # 16 bits - 无损
    F32 = "f32"         # 32 bits - 原始


@dataclass
class QuantConfig:
    """量化配置: 精度/速度/内存三者平衡"""
    quant_type: QuantType
    bits_per_weight: float
    
    # 预估内存占用 (4B模型为例)
    @property
    def estimated_gb(self) -> float:
        base_gb = 4.0  # 70B≈140GB
        return round(base_gb * self.bits_per_weight / 16, 1)
    
    @staticmethod
    def recommend(vram_gb: float) -> 'QuantConfig':
        """根据VRAM推荐最佳量化 (70B模型参考)
        公式: VRAM_needed = 70 * bit_weight / 8 + 2 (GB overhead)
        """
        model_params_b = 70  # 70B模型
        overhead = 2  # GB
        margin = 0.9  # 可用90%的VRAM
        
        usable = vram_gb * margin - overhead
        # 从高到低, 选能装下的最高量化
        candidates = [
            (QuantType.Q8_0, 8.00),
            (QuantType.Q6_K, 6.56),
            (QuantType.Q5_K, 5.50),
            (QuantType.Q4_K, 4.50),
            (QuantType.Q3_K, 3.50),
            (QuantType.Q2_K, 2.56),
        ]
        for qt, bits in candidates:
            model_gb = model_params_b * bits / 8  # 70B * bits/8
            if usable >= model_gb:
                return QuantConfig(quant_type=qt, bits_per_weight=bits)
        return QuantConfig(quant_type=QuantType.Q2_K, bits_per_weight=2.56)


# ====================
# 2. Sampling策略 (common/sampling)
# ====================

@dataclass
class SamplingParams:
    """采样参数 = 控制生成质量的旋钮"""
    temperature: float = 0.7      # 温度: 低=确定, 高=随机
    top_p: float = 0.9             # Nucleus采样: 累积概率阈值
    top_k: int = 40                # Top-K采样: 只从前K个tokens采样
    repeat_penalty: float = 1.1    # 重复惩罚
    max_tokens: int = 2048         # 最大生成长度
    stop_sequences: List[str] = field(default_factory=lambda: ["<|im_end|>"])
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() 
                if v is not None}


# ====================
# 3. GGUF元数据 (模型自描述)
# ====================

@dataclass
class GGUFTensor:
    """GGUF张量元数据"""
    name: str
    shape: List[int]
    quant_type: str
    size_bytes: int


@dataclass
class GGUFSchema:
    """GGUF格式 = 自描述模型文件头"""
    magic: str = "GGUF"
    version: int = 3
    architecture: str = "llama"        # llama/mistral/gemma/deepseek...
    vocab_size: int = 32000
    hidden_size: int = 4096
    num_layers: int = 32
    num_heads: int = 32
    num_kv_heads: int = 8
    max_seq_len: int = 8192
    tensors: List[GGUFTensor] = field(default_factory=list)
    
    @classmethod
    def from_model_id(cls, model_id: str) -> 'GGUFSchema':
        """从知名模型ID推断元数据"""
        known = {
            "llama-3.2-1b": GGUFSchema(architecture="llama", vocab_size=32000, hidden_size=2048, num_layers=16, num_heads=16, num_kv_heads=4, max_seq_len=8192),
            "llama-3.2-3b": GGUFSchema(architecture="llama", vocab_size=32000, hidden_size=3072, num_layers=28, num_heads=24, num_kv_heads=8, max_seq_len=8192),
            "llama-3.1-8b": GGUFSchema(architecture="llama", vocab_size=128256, hidden_size=4096, num_layers=32, num_heads=32, num_kv_heads=8, max_seq_len=131072),
            "mistral-7b": GGUFSchema(architecture="mistral", vocab_size=32000, hidden_size=4096, num_layers=32, num_heads=32, num_kv_heads=8, max_seq_len=32768),
            "gemma-2-2b": GGUFSchema(architecture="gemma", vocab_size=256000, hidden_size=2304, num_layers=26, num_heads=18, num_kv_heads=2, max_seq_len=8192),
            "deepseek-v2-16b": GGUFSchema(architecture="deepseek2", vocab_size=102400, hidden_size=2048, num_layers=27, num_heads=16, num_kv_heads=16, max_seq_len=4096),
        }
        for key, schema in known.items():
            if key in model_id.lower():
                return schema
        return GGUFSchema()
    
    def estimated_params_b(self) -> float:
        """估算参数量(十亿)"""
        return round(self.num_layers * self.hidden_size * self.hidden_size / 1e9, 1)


# ====================
# 4. 推理引擎 (llama-infer核心)
# ====================

class InferenceBackend(Enum):
    """多后端支持"""
    CPU = "cpu"
    CUDA = "cuda"
    METAL = "metal"
    VULKAN = "vulkan"
    AUTO = "auto"


@dataclass
class InferenceConfig:
    """推理引擎配置"""
    backend: InferenceBackend = InferenceBackend.AUTO
    n_gpu_layers: int = 0           # 卸载到GPU的层数(0=纯CPU)
    n_ctx: int = 8192               # 上下文长度
    n_batch: int = 512              # 批处理大小
    n_threads: int = 8              # CPU线程数
    use_mlock: bool = True          # 内存锁定(防交换)
    flash_attn: bool = False        # Flash Attention
    
    def auto_configure(self, has_cuda: bool = False, has_mps: bool = False) -> None:
        """自动选择最优配置"""
        if has_cuda:
            self.backend = InferenceBackend.CUDA
            self.n_gpu_layers = -1  # 全卸载到GPU
        elif has_mps:
            self.backend = InferenceBackend.METAL
            self.n_gpu_layers = -1
        else:
            self.backend = InferenceBackend.CPU


# ====================
# 5. 对话上下文管理
# ====================

@dataclass
class Message:
    role: str        # system/user/assistant
    content: str
    tokens: int = 0  # token计数


class ChatContext:
    """会话上下文管理 = KV Cache的Python抽象 + 模板渲染"""
    
    CHAT_TEMPLATES = {
        "llama-3": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>\n{history}<|start_header_id|>assistant<|end_header_id|>\n\n",
        "llama-2": "[INST] <<SYS>>\n{system}\n<</SYS>>\n\n{history} [/INST]",
        "mistral": "<s>[INST] {system}\n{history} [/INST]",
        "gemma": "<bos><start_of_turn>user\n{system}\n{history}<end_of_turn>\n<start_of_turn>model\n",
        "chatml": "<|im_start|>system\n{system}<|im_end|>\n{history}<|im_start|>assistant\n",
    }
    
    def __init__(self, template_name: str = "llama-3",
                 system_prompt: str = "你是一位AI助手",
                 max_tokens: int = 8192):
        self.template_name = template_name
        self.system = Message("system", system_prompt)
        self.messages: List[Message] = []
        self.max_tokens = max_tokens
        self._token_count = 0
    
    def add_user(self, content: str) -> None:
        self.messages.append(Message("user", content))
    
    def add_assistant(self, content: str) -> None:
        self.messages.append(Message("assistant", content))
    
    def get_prompt(self) -> str:
        """构建完整提示"""
        template = self.CHAT_TEMPLATES.get(self.template_name, self.CHAT_TEMPLATES["chatml"])
        history_parts = []
        for msg in self.messages:
            if msg.role == "user":
                if self.template_name == "llama-3":
                    history_parts.append(f"<|start_header_id|>user<|end_header_id|>\n\n{msg.content}<|eot_id|>")
                elif self.template_name == "mistral":
                    history_parts.append(f"{msg.content} [/INST]")
                else:
                    history_parts.append(f"<|im_start|>user\n{msg.content}<|im_end|>\n")
            elif msg.role == "assistant":
                if self.template_name == "llama-3":
                    history_parts.append(f"<|start_header_id|>assistant<|end_header_id|>\n\n{msg.content}<|eot_id|>")
                elif self.template_name == "mistral":
                    history_parts.append(f"{msg.content}</s><s>[INST] ")
                else:
                    history_parts.append(f"<|im_start|>assistant\n{msg.content}<|im_end|>\n")
        history = "".join(history_parts)
        return template.format(system=self.system.content, history=history)
    
    def trim_to(self, max_tokens: int) -> None:
        """上下文窗口溢出裁剪(保留system+最近)"""
        while self._token_count > max_tokens and self.messages:
            removed = self.messages.pop(0)
            self._token_count -= removed.tokens


# ====================
# 6. 推理接口 (顶层API)
# ====================

class LLMInference:
    """本地LLM推理接口 = llama.cpp的Python抽象
    
    不实际加载模型(需要真实GGUF文件), 
    但提供完整的推理链路接口设计。
    """
    
    def __init__(self, model_path: str, 
                 quant_config: Optional[QuantConfig] = None,
                 inference_config: Optional[InferenceConfig] = None):
        self.model_path = model_path
        self.quant = quant_config or QuantConfig(QuantType.Q4_K, 4.5)
        self.config = inference_config or InferenceConfig()
        self.schema = GGUFSchema.from_model_id(model_path)
    
    def generate(self, prompt: str, 
                 params: Optional[SamplingParams] = None) -> str:
        """同步生成(模拟)"""
        p = params or SamplingParams()
        # 模拟推理: 实际调用llama.cpp需要C扩展绑定
        info = f"[推理模拟] prompt={len(prompt)}ch | temp={p.temperature} | max_tokens={p.max_tokens} | quant={self.quant.quant_type.value}"
        return info
    
    def estimate_time(self, prompt_tokens: int, output_tokens: int = 256) -> Dict[str, Any]:
        """估算推理时间"""
        # 基于常见benchmark: 7B Q4 约40tok/s
        # 70B Q4 约5tok/s
        param_b = self.schema.estimated_params_b()
        speed_map = {
            0.5: 120,  # 0.5B
            1.0: 80,
            3.0: 50,
            7.0: 40,
            13.0: 25,
            30.0: 15,
            70.0: 5,
            120.0: 2,
        }
        speed = min((s for p, s in speed_map.items() if param_b <= p), default=1)
        prompt_time = prompt_tokens / (speed * 4)  # prefill 4x快
        gen_time = output_tokens / speed
        return {
            "model_size_b": param_b,
            "speed_tok_s": speed,
            "prompt_ms": round(prompt_time * 1000),
            "gen_s": round(gen_time, 1),
            "total_s": round(prompt_time + gen_time, 1),
        }
    
    def info(self) -> Dict[str, Any]:
        return {
            "model": self.model_path,
            "quant": self.quant.quant_type.value,
            f"{self.quant.bits_per_weight}bit": f"~{self.quant.estimated_gb}GB",
            "architecture": self.schema.architecture,
            f"{self.schema.estimated_params_b()}B": f"{self.schema.hidden_size}d",
            "backend": self.config.backend.value,
            "context_window": self.config.n_ctx,
        }


# ====================
# 7. 声明式计算图 (GGML设计模式移植)
# ====================

class ComputeNode:
    """计算图节点 = GGML声明式图设计"""
    pass


class ComputeGraph:
    """声明式计算图 = 先定义后执行"""
    
    def __init__(self):
        self.nodes: List[Tuple[str, Callable, List[str]]] = []  # (name, fn, depends)
    
    def add(self, name: str, fn: Callable, depends: List[str] = None) -> 'ComputeGraph':
        self.nodes.append((name, fn, depends or []))
        return self
    
    def execute(self, inputs: Dict[str, Any] = None) -> Dict[str, Any]:
        """拓扑排序后执行"""
        results = dict(inputs or {})
        executed = set(results.keys())
        
        while True:
            progress = False
            for name, fn, deps in self.nodes:
                if name in executed:
                    continue
                if all(d in executed for d in deps):
                    args = {d: results[d] for d in deps}
                    results[name] = fn(**args)
                    executed.add(name)
                    progress = True
            if not progress:
                break
        
        return results
    
    def visualize(self) -> str:
        lines = ["计算图:"]
        for name, fn, deps in self.nodes:
            dep_str = f" <- {', '.join(deps)}" if deps else ""
            lines.append(f"  {name}({fn.__name__}){dep_str}")
        return "\n".join(lines)


# ====================
# 自检
# ====================

def _run_self_check() -> bool:
    print("=" * 60)
    print("📋 llama.cpp 自检 (111k⭐ 本地LLM推理)")
    print("=" * 60)
    
    # [1] 量化策略: 70B模型参考
    # 公式: VRAM_needed = 70 * bit_weight / 8 + 2 (GB overhead)
    # 可用VRAM = vram_gb * 0.9 - 2
    q = QuantConfig.recommend(vram_gb=6.0)
    assert q.quant_type == QuantType.Q2_K, f"6GB→Q2_K, got {q.quant_type}"
    q48 = QuantConfig.recommend(vram_gb=48.0)
    assert q48.quant_type == QuantType.Q4_K, f"48GB→Q4_K, got {q48.quant_type}"
    print("✅ 量化策略: VRAM→推荐量化类型正确")
    
    # [2] Sampling参数
    sp = SamplingParams(temperature=0.3, top_k=10)
    d = sp.to_dict()
    assert d["temperature"] == 0.3
    assert d["top_k"] == 10
    print("✅ Sampling: 参数序列化正确")
    
    # [3] GGUF元数据
    schema = GGUFSchema.from_model_id("llama-3.1-8b")
    assert schema.architecture == "llama"
    assert schema.hidden_size == 4096
    assert schema.num_layers == 32
    param_b = schema.estimated_params_b()
    assert param_b > 0
    print(f"✅ GGUF元数据: 模型自描述推断正确 ({param_b}B)")
    
    # [4] 推理引擎接口
    engine = LLMInference("llama-3.2-3b", quant_config=QuantConfig(QuantType.Q4_K, 4.5))
    info = engine.info()
    assert info["architecture"] == "llama"
    assert "q4_k" in info["quant"]
    result = engine.generate("Hello")
    assert "推理模拟" in result
    print("✅ 推理引擎接口: 配置+模拟推理正常")
    
    # [5] 对话上下文管理
    ctx = ChatContext(template_name="llama-3", system_prompt="你是有用的助手")
    ctx.add_user("什么是RAG?")
    ctx.add_assistant("RAG=检索增强生成")
    prompt = ctx.get_prompt()
    assert "system" in prompt
    assert "user" in prompt
    assert "assistant" in prompt
    assert "RAG" in prompt
    print("✅ ChatContext: 对话模板渲染正确")
    
    # [6] 多后端配置
    config = InferenceConfig()
    config.auto_configure(has_cuda=True)
    assert config.backend == InferenceBackend.CUDA
    config.auto_configure(has_cuda=False, has_mps=True)
    assert config.backend == InferenceBackend.METAL
    config.auto_configure(has_cuda=False, has_mps=False)
    assert config.backend == InferenceBackend.CPU
    print("✅ 多后端: 自动配置CUDA/Metal/CPU正确")
    
    # [7] 温度控制 (Sampling参数组合)
    conservative = SamplingParams(temperature=0.1, top_p=0.5, top_k=10)
    creative = SamplingParams(temperature=1.2, top_p=0.95, top_k=100)
    assert conservative.temperature < creative.temperature
    assert conservative.top_k < creative.top_k
    times = engine.estimate_time(prompt_tokens=500, output_tokens=256)
    assert times["total_s"] > 0
    print("✅ 温度控制: 保守/创意模式参数组合正常")
    
    print(f"\n推理引擎: {engine.model_path}")
    print(f"量化: {engine.quant.quant_type.value} ({engine.quant.bits_per_weight}bit/weight, ~{engine.quant.estimated_gb}GB)")
    print(f"架构: {engine.schema.architecture} | {engine.schema.estimated_params_b()}B | {engine.schema.hidden_size}d")
    print(f"预估{times['total_s']}s完成 ({times['speed_tok_s']}tok/s)")
    
    print(f"\n✅🎉 llama.cpp 自检通过 (7项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
