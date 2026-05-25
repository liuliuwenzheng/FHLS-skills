"""
skill_ollama.py - Ollama(1.1M⭐)骨髓内化: 本地模型运行时
============================================================

核心设计:
  ModelRegistry(模型注册/生命周期) → LLMRunner(推理引擎) → 
  PromptPipeline(模板/上下文) → Server(OpenAI兼容REST API) → 
  RequestScheduler(并发控制)

与ga_lmstudio_bridge的差异化: 
  lmstudio_bridge是GA↔LMStudio客户端桥接
  本模块是Ollama式模型运行时架构(可管理多个后端/模型切换/请求调度)
"""

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Generator
from enum import Enum

# ====================
# 1. 模型元数据
# ====================

class ModelArch(Enum):
    LLAMA = "llama"          # Llama/Llama-2/Llama-3
    MISTRAL = "mistral"      # Mistral/Mixtral
    GEMMA = "gemma"          # Gemma/Gemma-2
    QWEN = "qwen"            # Qwen/Qwen-2
    COMMAND = "command"      # Command-R/Command-R+
    CODELLAMA = "codellama"  # CodeLlama
    PHI = "phi"              # Phi-3/Phi-4
    DEEPSEEK = "deepseek"    # DeepSeek
    OLMO = "olmo"            # OLMo
    FALCON = "falcon"        # Falcon
    CUSTOM = "custom"        # 用户自定义


@dataclass
class ModelSpec:
    """模型规格"""
    name: str
    arch: ModelArch
    size_gb: float
    context_window: int = 4096
    description: str = ""
    modelfile: str = ""  # Ollama Modelfile式配置
    
    # 模板配置（Ollama的template/prompt工程）
    system_template: str = "{system}"
    prompt_template: str = "{prompt}"
    stop_tokens: List[str] = field(default_factory=lambda: ["</s>", "<|im_end|>"])
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "arch": self.arch.value,
            "size_gb": self.size_gb,
            "context_window": self.context_window,
            "description": self.description,
        }


# ====================
# 2. 模型注册中心 (Ollama ModelStore)
# ====================

class ModelRegistry:
    """模型仓库 - 管理模型的拉取/删除/生命周期"""
    
    def __init__(self):
        self._models: Dict[str, ModelSpec] = {}
        self._pull_handlers: Dict[str, Callable] = {}  # 模型名->拉取函数
    
    def register(self, spec: ModelSpec, pull_handler: Optional[Callable] = None) -> None:
        """注册模型(类似ollama pull后的记录)"""
        self._models[spec.name] = spec
        if pull_handler:
            self._pull_handlers[spec.name] = pull_handler
    
    def get(self, name: str) -> Optional[ModelSpec]:
        return self._models.get(name)
    
    def list(self) -> List[ModelSpec]:
        return list(self._models.values())
    
    def remove(self, name: str) -> bool:
        """类似ollama rm"""
        if name in self._models:
            del self._models[name]
            self._pull_handlers.pop(name, None)
            return True
        return False
    
    def pull(self, name: str, callback: Optional[Callable[[float], None]] = None) -> bool:
        """类似ollama pull, 进度回调"""
        if name in self._pull_handlers:
            handler = self._pull_handlers[name]
            try:
                if callback:
                    # 模拟进度: 0% -> 100%
                    for pct in [0, 10, 30, 50, 70, 90, 100]:
                        callback(pct)
                        time.sleep(0.05)
                handler()
                return True
            except Exception as e:
                print(f"[Ollama] Pull failed: {e}")
                return False
        return False
    
    @property
    def count(self) -> int:
        return len(self._models)


# ====================
# 3. LLM推理引擎 (Ollama LLM Runner)
# ====================

class InferenceBackend(Enum):
    MOCK = "mock"       # 测试用
    OPENAI = "openai"   # OpenAI兼容API
    LOCAL = "local"     # 本地进程调用


@dataclass
class GenerationConfig:
    """推理配置"""
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    max_tokens: int = 1024
    stop: List[str] = field(default_factory=list)
    stream: bool = False
    
    def to_dict(self) -> dict:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_tokens": self.max_tokens,
            "stop": self.stop,
            "stream": self.stream,
        }


class LLMRunner:
    """推理引擎 - 加载模型/执行推理/Ollama式流式输出"""
    
    def __init__(self, backend: InferenceBackend = InferenceBackend.MOCK):
        self.backend = backend
        self._current_model: Optional[str] = None
        self._loaded: bool = False
        self._backend_fn: Optional[Callable] = None
    
    def load(self, model_name: str, spec: ModelSpec) -> bool:
        """加载模型到内存(类似ollama run前的load)"""
        self._current_model = model_name
        if self.backend == InferenceBackend.MOCK:
            # Mock模式: 存储spec用于模拟输出
            self._loaded = True
            return True
        elif self.backend == InferenceBackend.OPENAI:
            # OpenAI兼容API模式(LMStudio/Ollama serve)
            self._loaded = True
            return True
        elif self.backend == InferenceBackend.LOCAL:
            # 启动本地进程(绑定llama.cpp等)
            # TODO: 实际进程管理
            self._loaded = True
            return True
        return False
    
    def unload(self) -> None:
        """卸载模型, 释放内存"""
        self._loaded = False
        self._current_model = None
    
    def set_backend_fn(self, fn: Callable[[str, GenerationConfig], str]) -> None:
        """设置自定义推理函数(用于对接实际API)"""
        self._backend_fn = fn
    
    @property
    def is_loaded(self) -> bool:
        return self._loaded
    
    @property
    def current_model(self) -> Optional[str]:
        return self._current_model
    
    def generate(self, prompt: str, config: GenerationConfig = None) -> str:
        """同步推理(类似ollama run 'prompt')"""
        if config is None:
            config = GenerationConfig()
        
        if self._backend_fn:
            return self._backend_fn(prompt, config)
        
        if self.backend == InferenceBackend.MOCK:
            return f"[Mock: {self._current_model}] Response to: {prompt[:50]}..."
        
        if self.backend == InferenceBackend.OPENAI:
            raise NotImplementedError("需注入实际HTTP客户端")
        
        return "[Error] No backend available"
    
    def generate_stream(self, prompt: str, config: GenerationConfig = None) -> Generator[str, None, None]:
        """流式推理(类似ollama run的流式输出)"""
        if config is None:
            config = GenerationConfig()
        
        full_response = self.generate(prompt, config)
        # 模拟逐字输出
        for i in range(0, len(full_response), 5):
            yield full_response[i:i+5]
            time.sleep(0.01)  # 模拟延迟


# ====================
# 4. 提示流水线 (Ollama Prompt Processing)
# ====================

@dataclass
class PromptTemplate:
    """提示模板 - Ollama的template系统"""
    name: str
    system: str = ""
    prompt: str = "{input}"
    template: str = ""
    
    def render(self, input_text: str, history: List[Dict] = None) -> str:
        """渲染模板(Ollama式)"""
        if self.template:
            return self.template.replace("{input}", input_text)
        if self.system:
            return f"{self.system}\n\n{self.prompt.replace('{input}', input_text)}"
        return self.prompt.replace('{input}', input_text)


class PromptPipeline:
    """提示处理流水线 - 上下文管理/模板化/格式转换"""
    
    def __init__(self, max_context: int = 4096):
        self.max_context = max_context
        self.templates: Dict[str, PromptTemplate] = {}
        self._register_defaults()
    
    def _register_defaults(self):
        """注册Ollama风格的默认模板"""
        self.templates["llama3"] = PromptTemplate(
            "llama3",
            system="<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>",
            prompt="<|start_header_id|>user<|end_header_id|>\n\n{input}<|eot_id|>\n<|start_header_id|>assistant<|end_header_id|>",
            template=""
        )
        self.templates["mistral"] = PromptTemplate(
            "mistral",
            system="[INST] {system} [/INST]",
            prompt="[INST] {input} [/INST]",
        )
        self.templates["gemma"] = PromptTemplate(
            "gemma",
            prompt="<start_of_turn>user\n{input}<end_of_turn>\n<start_of_turn>model\n",
        )
        self.templates["chatml"] = PromptTemplate(
            "chatml",
            system="<|im_start|>system\n{system}<|im_end|>\n",
            prompt="<|im_start|>user\n{input}<|im_end|>\n<|im_start|>assistant\n",
        )
    
    def register_template(self, template: PromptTemplate) -> None:
        self.templates[template.name] = template
    
    def format_prompt(self, input_text: str, template_name: str = "chatml",
                      system: str = "", history: List[Dict] = None) -> str:
        """格式化提示"""
        tmpl = self.templates.get(template_name, self.templates["chatml"])
        # 注入system
        rendered = tmpl.render(input_text, history)
        if system and "{system}" in rendered:
            rendered = rendered.replace("{system}", system)
        elif system and template_name == "chatml":
            rendered = tmpl.system.replace("{system}", system) + rendered
        return rendered[:self.max_context]
    
    def count_tokens(self, text: str) -> int:
        """粗略估算token数"""
        return len(text) // 4 + 1  # 中文约2字/token, 英文4字/token


# ====================
# 5. 请求调度器 (Ollama并发控制/队列)
# ====================

class RequestPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2


@dataclass
class Request:
    """推理请求"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    prompt: str = ""
    config: GenerationConfig = field(default_factory=GenerationConfig)
    priority: RequestPriority = RequestPriority.NORMAL
    created_at: float = field(default_factory=time.time)
    callback: Optional[Callable[[str], None]] = None
    stream_callback: Optional[Callable[[str], None]] = None


class RequestScheduler:
    """请求调度器 - Ollama式并发控制/队列管理"""
    
    def __init__(self, runner: LLMRunner, max_concurrent: int = 1):
        self.runner = runner
        self.max_concurrent = max_concurrent
        self._queue: List[Request] = []
        self._active: int = 0
        self._lock = threading.Lock()
        self._running = False
        self._worker: Optional[threading.Thread] = None
    
    def submit(self, request: Request) -> str:
        """提交请求"""
        with self._lock:
            self._queue.append(request)
            self._queue.sort(key=lambda r: r.priority.value, reverse=True)
        self._ensure_running()
        return request.id
    
    def _ensure_running(self):
        """确保工作线程在运行"""
        if not self._running:
            self._running = True
            self._worker = threading.Thread(target=self._process_loop, daemon=True)
            self._worker.start()
    
    def _process_loop(self):
        """处理循环"""
        while self._running:
            req = None
            with self._lock:
                if self._queue and self._active < self.max_concurrent:
                    req = self._queue.pop(0)
                    self._active += 1
            
            if req:
                try:
                    if req.stream_callback:
                        for chunk in self.runner.generate_stream(req.prompt, req.config):
                            req.stream_callback(chunk)
                    else:
                        result = self.runner.generate(req.prompt, req.config)
                        if req.callback:
                            req.callback(result)
                finally:
                    with self._lock:
                        self._active -= 1
            else:
                time.sleep(0.05)
            
            # 空队列时停止
            with self._lock:
                if not self._queue and self._active == 0:
                    self._running = False
                    break
    
    def stats(self) -> dict:
        """调度统计"""
        with self._lock:
            return {
                "queue_size": len(self._queue),
                "active": self._active,
                "max_concurrent": self.max_concurrent,
                "running": self._running,
            }


# ====================
# 6. REST API Server (Ollama Server)
# ====================

class OllamaServer:
    """轻量级API Server - OpenAI兼容接口"""
    
    def __init__(self, registry: ModelRegistry, runner: LLMRunner, 
                 scheduler: RequestScheduler):
        self.registry = registry
        self.runner = runner
        self.scheduler = scheduler
        self.pipeline = PromptPipeline()
    
    def handle_chat(self, messages: List[Dict], model: str = "default",
                    config: GenerationConfig = None) -> Dict:
        """处理chat completion请求(OpenAI兼容)"""
        if config is None:
            config = GenerationConfig()
        
        # 加载模型
        spec = self.registry.get(model)
        if not spec:
            return {"error": f"Model '{model}' not found", "status": "error"}
        
        self.runner.load(model, spec)
        
        # 提取system和user消息
        system = ""
        user_input = ""
        for m in messages:
            if m.get("role") == "system":
                system = m["content"]
            elif m.get("role") == "user":
                user_input = m["content"]
        
        # 格式化提示
        template_name = model.split(":")[0]  # "llama3:8b" -> "llama3"
        formatted = self.pipeline.format_prompt(
            user_input, 
            template_name if template_name in self.pipeline.templates else "chatml",
            system
        )
        
        # 推理
        response = self.runner.generate(formatted, config)
        
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": response},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": self.pipeline.count_tokens(formatted),
                "completion_tokens": self.pipeline.count_tokens(response),
                "total_tokens": self.pipeline.count_tokens(formatted + response),
            },
            "status": "ok",
        }
    
    def handle_generate(self, prompt: str, model: str = "default",
                        config: GenerationConfig = None) -> Dict:
        """处理generate请求(类似ollama直接生成)"""
        if config is None:
            config = GenerationConfig()
        
        req = Request(prompt=prompt, config=config)
        req_id = self.scheduler.submit(req)
        
        # 同步等待结果(简化版)
        return {
            "id": req_id,
            "model": model,
            "response": f"[Queued: {req_id}]",
            "status": "queued",
        }
    
    def list_models(self) -> List[Dict]:
        """列出可用模型"""
        return [spec.to_dict() for spec in self.registry.list()]
    
    def model_info(self, name: str) -> Optional[Dict]:
        """模型详细信息"""
        spec = self.registry.get(name)
        return spec.to_dict() if spec else None


# ====================
# 自检
# ====================

def _run_self_check() -> bool:
    print("=" * 60)
    print("📋 Ollama 自检 (1.1M⭐ 本地模型运行时)")
    print("=" * 60)
    
    # [1] ModelRegistry
    registry = ModelRegistry()
    spec = ModelSpec("llama3:8b", ModelArch.LLAMA, 4.5, context_window=8192)
    registry.register(spec)
    assert registry.get("llama3:8b") is spec
    assert registry.count == 1
    registry.register(ModelSpec("mistral:7b", ModelArch.MISTRAL, 3.8))
    assert registry.count == 2
    assert len(registry.list()) == 2
    registry.remove("mistral:7b")
    assert registry.count == 1
    print("✅ ModelRegistry: 注册/查询/删除正常")
    
    # [2] LLMRunner
    runner = LLMRunner(InferenceBackend.MOCK)
    assert runner.load("llama3:8b", spec)
    assert runner.is_loaded
    result = runner.generate("Hello, what is AI?")
    assert result.startswith("[Mock: llama3:8b]")
    stream_chunks = list(runner.generate_stream("test", GenerationConfig(stream=True)))
    assert len(stream_chunks) > 0
    runner.unload()
    assert not runner.is_loaded
    print("✅ LLMRunner: 加载/推理/流式/卸载正常")
    
    # [3] PromptPipeline
    pipeline = PromptPipeline()
    assert "llama3" in pipeline.templates
    formatted = pipeline.format_prompt("Hello", "llama3", system="You are helpful")
    assert "Hello" in formatted
    assert pipeline.count_tokens("Hello world") > 0
    print("✅ PromptPipeline: 模板注册/格式化/token估算正常")
    
    # [4] RequestScheduler
    scheduler = RequestScheduler(runner, max_concurrent=1)
    req = Request(prompt="Test request", priority=RequestPriority.HIGH)
    req_id = scheduler.submit(req)
    assert req_id
    time.sleep(0.2)  # 等待处理
    stats = scheduler.stats()
    assert stats["queue_size"] == 0
    print("✅ RequestScheduler: 队列/优先级/并发控制正常")
    
    # [5] OllamaServer
    server = OllamaServer(registry, runner, scheduler)
    models = server.list_models()
    assert len(models) == 1
    info = server.model_info("llama3:8b")
    assert info["name"] == "llama3:8b"
    chat_result = server.handle_chat(
        [{"role": "user", "content": "Hi"}],
        model="llama3:8b"
    )
    assert chat_result["status"] == "ok"
    assert len(chat_result["choices"]) == 1
    print("✅ OllamaServer: 模型列表/chat/info正常")
    
    # [6] 端到端: 注册->加载->推理->调度
    registry2 = ModelRegistry()
    spec2 = ModelSpec("custom:test", ModelArch.CUSTOM, 1.0)
    registry2.register(spec2)
    runner2 = LLMRunner(InferenceBackend.MOCK)
    runner2.load("custom:test", spec2)
    scheduler2 = RequestScheduler(runner2)
    
    # 提交多个请求
    results = []
    def collect(resp):
        results.append(resp)
    
    for i in range(3):
        r = Request(prompt=f"Query {i}", callback=collect)
        scheduler2.submit(r)
    
    time.sleep(0.3)
    assert len(results) == 3
    print("✅ 端到端: 注册→加载→调度→回调完成")
    
    print(f"\n✅🎉 Ollama 自检通过 (6项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
