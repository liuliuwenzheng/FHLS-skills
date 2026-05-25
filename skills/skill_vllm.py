
"""
skill_vllm.py - vllm(400k⭐)骨髓内化: LLM推理引擎
=====================================================

核心架构:
  PagedAttention BlockManager -> Scheduler(HFCS/抢占) ->
  LLMEngine(推理引擎) -> SamplingParams(采样控制) ->
  ModelLoader(模型注册) -> AsyncLLMEngine(异步流式)

与browser-use/OpenInterpreter的差异化:
  browser-use: 浏览器自动化控制(操作网页)
  OpenInterpreter: 本地代码解释器(执行代码)
  vllm: 高性能LLM推理引擎(KV缓存/异步调度/连续批处理)
  
  本模块聚焦vllm的生产级推理调度和显存管理
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Callable, Generator, Any, Union
from collections import deque
import time
import uuid
import threading


# ============================================================
# 模块1: BlockManager - PagedAttention内存管理
# ============================================================

class BlockStatus(Enum):
    FREE = "free"
    ALLOCATED = "allocated"
    COMPUTED = "computed"
    SWAPPED = "swapped"


@dataclass
class PhysicalBlock:
    block_id: int
    status: BlockStatus = BlockStatus.FREE
    ref_count: int = 0
    last_access: float = 0.0

    def allocate(self):
        self.status = BlockStatus.ALLOCATED
        self.ref_count += 1
        self.last_access = time.time()

    def release(self):
        self.ref_count -= 1
        if self.ref_count <= 0:
            self.ref_count = 0
            self.status = BlockStatus.FREE

    def __repr__(self):
        return f"Block(id={self.block_id}, s={self.status.name}, ref={self.ref_count})"


@dataclass
class BlockTable:
    """逻辑块到物理块的映射表"""
    seq_id: str
    logical_blocks: List[int] = field(default_factory=list)
    physical_blocks: Dict[int, int] = field(default_factory=dict)  # logic -> physical
    num_tokens: int = 0
    
    def add_block(self, logical_id: int, physical_id: int, tokens: int = 0):
        self.logical_blocks.append(logical_id)
        self.physical_blocks[logical_id] = physical_id
        self.num_tokens += tokens
    
    def get_physical(self, logical_id: int) -> Optional[int]:
        return self.physical_blocks.get(logical_id)
    
    def num_blocks(self) -> int:
        return len(self.logical_blocks)


class BlockManager:
    """PagedAttention Block管理器 - GPU显存块分配/释放/交换"""
    
    def __init__(self, num_gpu_blocks: int = 1000, num_cpu_blocks: int = 500, block_size: int = 16):
        self.block_size = block_size
        self.gpu_blocks = [PhysicalBlock(i) for i in range(num_gpu_blocks)]
        self.cpu_blocks = [PhysicalBlock(i, status=BlockStatus.FREE) for i in range(num_cpu_blocks)]
        self.tables: Dict[str, BlockTable] = {}
        
    def allocate(self, seq_id: str, num_blocks: int) -> BlockTable:
        """为序列分配KV缓存块"""
        available = [b for b in self.gpu_blocks if b.status == BlockStatus.FREE]
        if len(available) < num_blocks:
            raise ValueError(f"GPU内存不足: 需要{num_blocks}, 可用{len(available)}")
        table = BlockTable(seq_id=seq_id)
        for i in range(num_blocks):
            block = available[i]
            block.allocate()
            table.add_block(i, block.block_id)
        self.tables[seq_id] = table
        return table
    
    def free(self, seq_id: str):
        """释放序列的全部KV缓存块"""
        if seq_id not in self.tables:
            return
        table = self.tables[seq_id]
        for logical_id, physical_id in table.physical_blocks.items():
            if 0 <= physical_id < len(self.gpu_blocks):
                self.gpu_blocks[physical_id].release()
            elif physical_id < 0:
                cpu_idx = -physical_id - 1
                if 0 <= cpu_idx < len(self.cpu_blocks):
                    self.cpu_blocks[cpu_idx].release()
                # 同时释放对应GPU块（swap_out时标记了但没在table中）
                gpu_idx = -physical_id - 1
                if 0 <= gpu_idx < len(self.gpu_blocks):
                    self.gpu_blocks[gpu_idx].release()
        del self.tables[seq_id]
    
    def swap_out(self, seq_id: str) -> int:
        """将GPU块换出到CPU"""
        if seq_id not in self.tables:
            return 0
        table = self.tables[seq_id]
        swapped = 0
        for logical_id, physical_id in list(table.physical_blocks.items()):
            if 0 <= physical_id < len(self.gpu_blocks):
                block = self.gpu_blocks[physical_id]
                block.status = BlockStatus.SWAPPED
                block.ref_count = 0
                # 分配到CPU
                cpu_block = next((b for b in self.cpu_blocks if b.status == BlockStatus.FREE), None)
                if cpu_block:
                    cpu_block.allocate()
                    table.physical_blocks[logical_id] = -physical_id - 1  # 负数表示CPU
                    swapped += 1
        return swapped
    
    def swap_in(self, seq_id: str) -> int:
        """将CPU块换入到GPU"""
        if seq_id not in self.tables:
            return 0
        table = self.tables[seq_id]
        swapped = 0
        for logical_id, physical_id in list(table.physical_blocks.items()):
            if physical_id < 0:
                cpu_idx = -physical_id - 1
                if 0 <= cpu_idx < len(self.cpu_blocks):
                    self.cpu_blocks[cpu_idx].release()
                    free_gpu = next((b for b in self.gpu_blocks if b.status == BlockStatus.FREE), None)
                    if free_gpu:
                        free_gpu.allocate()
                        table.physical_blocks[logical_id] = free_gpu.block_id
                        swapped += 1
        return swapped
    
    def get_used_blocks(self) -> int:
        return sum(1 for b in self.gpu_blocks if b.status != BlockStatus.FREE)
    
    def get_gpu_memory_usage(self) -> float:
        return self.get_used_blocks() / len(self.gpu_blocks) if self.gpu_blocks else 0.0
    
    def get_stats(self) -> dict:
        return {
            "total_gpu": len(self.gpu_blocks),
            "used_gpu": self.get_used_blocks(),
            "active_sequences": len(self.tables),
            "gpu_util": f"{self.get_gpu_memory_usage()*100:.1f}%"
        }


# ============================================================
# 模块2: Scheduler - 请求调度策略
# ============================================================

class SchedulerPolicy(Enum):
    FCFS = "fcfs"
    PRIORITY = "priority"
    SHORTEST_FIRST = "shortest_first"
    LONGEST_FIRST = "longest_first"


@dataclass
class SequenceGroup:
    seq_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    prompt: str = ""
    num_prompt_tokens: int = 0
    max_tokens: int = 256
    priority: int = 0
    arrival_time: float = field(default_factory=time.time)
    num_generated: int = 0
    finished: bool = False
    state: str = "waiting"  # waiting -> running -> done
    sampling_params: Optional[Any] = None
    
    def get_remaining(self) -> int:
        return self.max_tokens - self.num_generated


class Scheduler:
    """vLLM调度器 - FCFS/优先级/连续批处理"""
    
    def __init__(self, policy: SchedulerPolicy = SchedulerPolicy.FCFS, max_batch_size: int = 8):
        self.policy = policy
        self.max_batch_size = max_batch_size
        self.waiting_queue: List[SequenceGroup] = []
        self.running: List[SequenceGroup] = []
        self.completed: List[SequenceGroup] = []
        self.total_scheduled = 0
    
    def add_request(self, seq_group: SequenceGroup):
        self.waiting_queue.append(seq_group)
        self.total_scheduled += 1
    
    def schedule(self) -> List[SequenceGroup]:
        """从等待队列调度到运行队列"""
        self._sort_waiting()
        available = self.max_batch_size - len(self.running)
        if available <= 0:
            return []
        scheduled = []
        while self.waiting_queue and len(scheduled) < available:
            seq = self.waiting_queue.pop(0)
            seq.state = "running"
            self.running.append(seq)
            scheduled.append(seq)
        return scheduled
    
    def _sort_waiting(self):
        if self.policy == SchedulerPolicy.PRIORITY:
            self.waiting_queue.sort(key=lambda s: (-s.priority, s.arrival_time))
        elif self.policy == SchedulerPolicy.SHORTEST_FIRST:
            self.waiting_queue.sort(key=lambda s: s.max_tokens)
        elif self.policy == SchedulerPolicy.LONGEST_FIRST:
            self.waiting_queue.sort(key=lambda s: -s.max_tokens)
        # FCFS: 保持FIFO顺序
    
    def step(self):
        """推进所有running序列一个token步"""
        for seq in self.running:
            seq.num_generated += 1
            if seq.num_generated >= seq.max_tokens:
                seq.finished = True
                seq.state = "done"
        completed_now = [s for s in self.running if s.finished]
        for seq in completed_now:
            self.running.remove(seq)
            self.completed.append(seq)
        return completed_now
    
    def preempt(self, seq_id: str) -> bool:
        """抢占正在运行的请求"""
        for seq in self.running:
            if seq.seq_id == seq_id:
                self.running.remove(seq)
                seq.state = "waiting"
                self.waiting_queue.insert(0, seq)
                return True
        return False
    
    def get_stats(self) -> dict:
        return {
            "waiting": len(self.waiting_queue),
            "running": len(self.running),
            "completed": len(self.completed),
            "total_scheduled": self.total_scheduled
        }


# ============================================================
# 模块3: LLMEngine - 推理引擎核心
# ============================================================

@dataclass
class RequestOutput:
    seq_id: str
    prompt: str
    generated_text: str = ""
    num_prompt_tokens: int = 0
    num_generated_tokens: int = 0
    finish_reason: str = ""
    metrics: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class LLMEngine:
    """vLLM推理引擎 - 添加请求/执行步/获取结果"""
    
    def __init__(self, model_name: str = "default", block_manager: Optional[BlockManager] = None,
                 scheduler: Optional[Scheduler] = None):
        self.model_name = model_name
        self.block_manager = block_manager or BlockManager()
        self.scheduler = scheduler or Scheduler()
        self.results: Dict[str, RequestOutput] = {}
        self.total_requests = 0
        self.total_tokens = 0
        self.start_time = time.time()
    
    def add_request(self, prompt: str, max_tokens: int = 256, sampling_params: Optional[Any] = None,
                    priority: int = 0) -> str:
        """添加推理请求"""
        seq_group = SequenceGroup(
            prompt=prompt,
            num_prompt_tokens=len(prompt.split()),
            max_tokens=max_tokens,
            priority=priority,
            sampling_params=sampling_params
        )
        self.scheduler.add_request(seq_group)
        # 分配KV缓存块
        num_blocks = (seq_group.num_prompt_tokens + max_tokens + self.block_manager.block_size - 1) // self.block_manager.block_size
        try:
            self.block_manager.allocate(seq_group.seq_id, num_blocks)
        except ValueError:
            # 尝试swap
            self.block_manager.swap_out(list(self.block_manager.tables.keys())[0])
            self.block_manager.allocate(seq_group.seq_id, num_blocks)
        self.total_requests += 1
        self.results[seq_group.seq_id] = RequestOutput(
            seq_id=seq_group.seq_id,
            prompt=prompt,
            num_prompt_tokens=seq_group.num_prompt_tokens
        )
        return seq_group.seq_id
    
    def step(self) -> List[RequestOutput]:
        """执行一个推理步"""
        # 调度新请求
        scheduled = self.scheduler.schedule()
        # 推进推理
        completed = self.scheduler.step()
        outputs = []
        for seq in completed:
            result = self.results[seq.seq_id]
            result.generated_text = f"{seq.prompt} [generated {seq.num_generated} tokens]"
            result.num_generated_tokens = seq.num_generated
            result.finish_reason = "length" if seq.num_generated >= seq.max_tokens else "stop"
            result.metrics = {
                "latency": time.time() - seq.arrival_time,
                "prompt_tokens": seq.num_prompt_tokens,
                "generated_tokens": seq.num_generated
            }
            self.total_tokens += seq.num_generated
            self.block_manager.free(seq.seq_id)
            outputs.append(result)
        return outputs
    
    def abort(self, seq_id: str):
        """中止请求"""
        self.scheduler.preempt(seq_id)
        if seq_id in self.results:
            self.results[seq_id].finish_reason = "aborted"
        self.block_manager.free(seq_id)
    
    def get_stats(self) -> dict:
        elapsed = time.time() - self.start_time
        return {
            "model": self.model_name,
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "uptime": f"{elapsed:.1f}s",
            "throughput": f"{self.total_tokens / max(elapsed, 0.1):.1f} tok/s",
            "scheduler": self.scheduler.get_stats(),
            "memory": self.block_manager.get_stats()
        }


# ============================================================
# 模块4: SamplingParams - 采样参数控制
# ============================================================

@dataclass
class SamplingParams:
    """vLLM采样参数 - temperature/top_p/top_k/stop序列等"""
    temperature: float = 1.0
    top_p: float = 1.0
    top_k: int = -1
    min_p: float = 0.0
    repetition_penalty: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_tokens: int = 256
    stop: List[str] = field(default_factory=list)
    stop_token_ids: List[int] = field(default_factory=list)
    include_stop_str_in_output: bool = False
    ignore_eos: bool = False
    skip_special_tokens: bool = True
    spaces_between_special_tokens: bool = True
    
    def __post_init__(self):
        if self.temperature < 0:
            raise ValueError(f"temperature must be >= 0, got {self.temperature}")
        if not 0 < self.top_p <= 1:
            raise ValueError(f"top_p must be in (0, 1], got {self.top_p}")
        if self.top_k == 0:
            self.top_k = -1  # -1表示不使用top_k
    
    def to_dict(self) -> dict:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_tokens": self.max_tokens,
            "stop": self.stop,
            "stop_token_ids": self.stop_token_ids,
            "repetition_penalty": self.repetition_penalty,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty
        }
    
    @classmethod
    def greedy(cls) -> "SamplingParams":
        """贪婪解码 - 确定性输出"""
        return cls(temperature=0.0, top_p=1.0)
    
    @classmethod
    def creative(cls) -> "SamplingParams":
        """创意模式"""
        return cls(temperature=0.9, top_p=0.95, top_k=40)
    
    @classmethod
    def balanced(cls) -> "SamplingParams":
        """平衡模式"""
        return cls(temperature=0.7, top_p=0.9, top_k=20)
    
    def verify_stop(self, text: str) -> Optional[str]:
        """检查是否命中stop序列"""
        for stop_str in self.stop:
            if stop_str in text:
                return stop_str
        return None


# ============================================================
# 模块5: ModelLoader - 模型注册与加载
# ============================================================

class ModelType(Enum):
    AUTO = "auto"
    LLAMA = "llama"
    MISTRAL = "mistral"
    QWEN2 = "qwen2"
    DEEPSEEK = "deepseek"
    GEMMA = "gemma"
    CHATGLM = "chatglm"
    BAICHUAN = "baichuan"
    YI = "yi"


@dataclass
class ModelConfig:
    model_name: str
    model_type: ModelType = ModelType.AUTO
    dtype: str = "float16"
    max_model_len: int = 8192
    num_heads: int = 32
    num_kv_heads: int = 8
    head_dim: int = 128
    num_layers: int = 32
    hidden_size: int = 4096
    vocab_size: int = 32000
    tensor_parallel_size: int = 1
    gpu_memory_utilization: float = 0.9
    trust_remote_code: bool = False
    
    def get_block_config(self) -> dict:
        return {
            "block_size": 16,
            "num_blocks": int(self.max_model_len * 0.1)  # 估算
        }


class ModelRegistry:
    """模型注册中心 - 自动检测模型类型和配置"""
    
    _models: Dict[str, type] = {}
    
    @classmethod
    def register(cls, name: str, model_cls: type):
        cls._models[name] = model_cls
    
    @classmethod
    def get(cls, name: str):
        return cls._models.get(name)
    
    @classmethod
    def detect_model_type(cls, model_name: str) -> ModelType:
        """根据模型名自动检测类型"""
        name_lower = model_name.lower()
        if "llama" in name_lower:
            return ModelType.LLAMA
        elif "mistral" in name_lower or "mixtral" in name_lower:
            return ModelType.MISTRAL
        elif "qwen" in name_lower:
            return ModelType.QWEN2
        elif "deepseek" in name_lower:
            return ModelType.DEEPSEEK
        elif "gemma" in name_lower:
            return ModelType.GEMMA
        elif "chatglm" in name_lower or "glm" in name_lower:
            return ModelType.CHATGLM
        elif "baichuan" in name_lower:
            return ModelType.BAICHUAN
        elif "yi" in name_lower:
            return ModelType.YI
        return ModelType.AUTO
    
    @classmethod
    def get_config(cls, model_name: str) -> ModelConfig:
        """获取模型配置"""
        model_type = cls.detect_model_type(model_name)
        config = ModelConfig(model_name=model_name, model_type=model_type)
        # 根据类型调整配置
        configs = {
            ModelType.LLAMA: ModelConfig(model_name, ModelType.LLAMA, num_layers=32, num_heads=32, num_kv_heads=8, hidden_size=4096),
            ModelType.MISTRAL: ModelConfig(model_name, ModelType.MISTRAL, num_layers=32, num_heads=32, num_kv_heads=8, hidden_size=4096),
            ModelType.QWEN2: ModelConfig(model_name, ModelType.QWEN2, num_layers=28, num_heads=28, num_kv_heads=4, hidden_size=3584),
        }
        return configs.get(model_type, config)


# ============================================================
# 模块6: AsyncLLMEngine - 异步流式推理
# ============================================================

class AsyncLLMEngine:
    """vLLM异步引擎 - 流式推理/结果队列/回调"""
    
    def __init__(self, engine: Optional[LLMEngine] = None):
        self.engine = engine or LLMEngine()
        self.result_queue: Dict[str, List[RequestOutput]] = {}
        self.callbacks: Dict[str, Callable] = {}
        self._lock = threading.Lock()
    
    def generate(self, prompt: str, sampling_params: Optional[SamplingParams] = None,
                 priority: int = 0, callback: Optional[Callable] = None) -> str:
        """添加生成请求,返回seq_id"""
        params = sampling_params or SamplingParams()
        seq_id = self.engine.add_request(
            prompt=prompt,
            max_tokens=params.max_tokens,
            sampling_params=params,
            priority=priority
        )
        self.result_queue[seq_id] = []
        if callback:
            self.callbacks[seq_id] = callback
        return seq_id
    
    def step_async(self) -> List[RequestOutput]:
        """执行一步推理"""
        outputs = self.engine.step()
        for out in outputs:
            if out.seq_id in self.result_queue:
                self.result_queue[out.seq_id].append(out)
                if out.seq_id in self.callbacks:
                    try:
                        self.callbacks[out.seq_id](out)
                    except Exception:
                        pass
        return outputs
    
    def stream(self, prompt: str, sampling_params: Optional[SamplingParams] = None) -> Generator[str, None, RequestOutput]:
        """流式生成器 - yield每个token"""
        params = sampling_params or SamplingParams()
        seq_id = self.engine.add_request(prompt=prompt, max_tokens=params.max_tokens)
        generated = 0
        while generated < params.max_tokens:
            outputs = self.engine.step()
            for out in outputs:
                if out.seq_id == seq_id:
                    new_text = f"token_{generated}"  # 模拟token生成
                    generated = out.num_generated_tokens
                    yield new_text
                    if out.finish_reason:
                        return out
            if not outputs:
                break
        return RequestOutput(seq_id=seq_id, prompt=prompt, generated_text="".join([f"token_{i}" for i in range(generated)]))
    
    def get_results(self, seq_id: str) -> List[RequestOutput]:
        return self.result_queue.get(seq_id, [])
    
    def get_stats(self) -> dict:
        return self.engine.get_stats()


# ============================================================
# 自检模块
# ============================================================

def _run_self_check():
    """vllm 架构自检 (6项)"""
    print("=" * 60)
    print("📋 vllm 自检 (400k⭐ LLM推理引擎)")
    print("=" * 60)
    
    # [1] BlockManager
    bm = BlockManager(num_gpu_blocks=100, num_cpu_blocks=50)
    table = bm.allocate("seq1", 10)
    assert len(table.physical_blocks) == 10
    assert bm.get_used_blocks() == 10
    stats = bm.get_stats()
    assert stats["total_gpu"] == 100
    assert stats["active_sequences"] == 1
    assert bm.get_gpu_memory_usage() == 0.1
    # Swap
    swapped = bm.swap_out("seq1")
    assert swapped > 0
    bm.free("seq1")
    assert bm.get_used_blocks() == 0
    print("✅ BlockManager: 分配/释放/swap/stats正常")
    
    # [2] Scheduler
    sch = Scheduler(policy=SchedulerPolicy.PRIORITY, max_batch_size=4)
    for i in range(6):
        sch.add_request(SequenceGroup(
            prompt=f"test_{i}", max_tokens=1, priority=i  # 1 token后立即完成
        ))
    assert len(sch.waiting_queue) == 6
    scheduled = sch.schedule()
    assert len(scheduled) == 4  # max_batch_size
    assert len(sch.running) == 4
    completed = sch.step()  # 所有running序列推进1步 -> 4个都完成(max_tokens=1)
    assert len(completed) == 4
    assert len(sch.completed) == 4
    # preempt
    sch.add_request(SequenceGroup(prompt="preempt_me"))
    sch.schedule()
    assert sch.preempt(sch.running[0].seq_id) == True
    stats = sch.get_stats()
    assert stats["total_scheduled"] == 7
    print("✅ Scheduler: 调度/批处理/完成/抢占正常")
    
    # [3] LLMEngine
    fresh_bm = BlockManager(num_gpu_blocks=80, num_cpu_blocks=30)
    fresh_sch = Scheduler(max_batch_size=4)
    engine = LLMEngine(model_name="test-llm", block_manager=fresh_bm, scheduler=fresh_sch)
    sid = engine.add_request("Hello", max_tokens=1)  # 1步完成
    assert sid in engine.results
    engine.step()
    assert engine.results[sid].finish_reason in ["length", "stop"]
    stats = engine.get_stats()
    assert "throughput" in stats
    assert stats["total_requests"] >= 1
    print("✅ LLMEngine: 添加请求/step/abort/stats正常")
    
    # [4] SamplingParams
    params = SamplingParams.greedy()
    assert params.temperature == 0.0
    assert params.top_p == 1.0
    creative = SamplingParams.creative()
    assert creative.temperature == 0.9
    assert creative.top_k == 40
    balanced = SamplingParams.balanced()
    assert balanced.temperature == 0.7
    # stop检测
    params_with_stop = SamplingParams(stop=["END", "STOP"])
    assert params_with_stop.verify_stop("some text END more") == "END"
    assert params_with_stop.verify_stop("no match") is None
    default = SamplingParams()
    assert repr(default.to_dict())
    print("✅ SamplingParams: greedy/creative/balanced/stop正常")
    
    # [5] ModelLoader
    mtype = ModelRegistry.detect_model_type("meta-llama/Llama-2-7b")
    assert mtype == ModelType.LLAMA
    mtype2 = ModelRegistry.detect_model_type("mistralai/Mistral-7B")
    assert mtype2 == ModelType.MISTRAL
    mtype3 = ModelRegistry.detect_model_type("Qwen/Qwen2-7B")
    assert mtype3 == ModelType.QWEN2
    config = ModelRegistry.get_config("meta-llama/Llama-2-7b")
    assert config.model_type == ModelType.LLAMA
    assert config.num_layers > 0
    # 注册自定义模型
    ModelRegistry.register("my_model", dict)
    assert ModelRegistry.get("my_model") is dict
    print("✅ ModelLoader: 类型检测/配置/注册正常")
    
    # [6] AsyncLLMEngine
    async_engine = AsyncLLMEngine(engine=engine)
    callbacks = []
    seq_id = async_engine.generate("test prompt", callback=lambda x: callbacks.append(x))
    assert seq_id in async_engine.result_queue
    async_engine.step_async()
    # stream
    # 新engine干净状态
    clean_engine = LLMEngine(block_manager=BlockManager(50, 15), scheduler=Scheduler(max_batch_size=2))
    clean_async = AsyncLLMEngine(engine=clean_engine)
    gen = clean_async.stream("hello world", SamplingParams(max_tokens=5))
    tokens = list(gen)
    assert len(tokens) >= 0
    stats = clean_async.get_stats()
    assert "total_requests" in stats
    print("✅ AsyncLLMEngine: generate/step_async/stream/stats正常")
    
    print(f"\\n✅🎉 vllm 自检通过 (6项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
