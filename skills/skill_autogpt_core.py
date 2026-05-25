"""
skill_autogpt_core.py — AutoGPT 184k⭐ 核心生态骨髓内化

骨髓内化来源: AutoGPT (Significant-Gravitas, 184k⭐)
原始文件: autogpt_platform/backend/backend/blocks/_base.py + data/block.py + data/model.py + data/credit.py + integrations/providers.py

设计哲学（用自己的话重建）:
  AutoGPT 2.0 的Block不再是简单的"输入→处理→输出"节点，
  而是**一个完整的微服务单元**，自带:
    ① 认证层 (Credentials + AutoCredentials)
    ② 计费层 (BlockCost + TokenRate)
    ③ 验证层 (BlockSchema JSON Schema)
    ④ 安全层 (HITL敏感操作审核)
    ⑤ 触发层 (Webhook手动/自动配置)
  → 每个Block像Serverless Function一样独立部署和计费

骨架（类名/方法签名/设计模式）:
  - BlockCostType: 6种计费模式枚举 (RUN/BYTE/SECOND/ITEMS/COST_USD/TOKENS)
  - TokenRateDisplay: 每1M token的USD费率显示
  - BlockCost: 成本模型 (amount + type + filter + divisor + rate)
  - BlockSchema: Pydantic→JSON Schema + 字段验证 + 自动认证注入
  - CredentialsMetaInput: 认证元信息 (provider/type/scope)
  - BlockWebhookConfig: 自动+手动Webhook配置
  - EnhancedBlock: 原有Block基类增加 cost + credentials + webhook + review 层
  
GA嫁接点:
  1. TokenCache → BlockCost的TOKENS计费模式
  2. skill_gstack → Credentials认证体系
  3. Block Workflow → HITL安全审核
"""

import inspect, json, logging, time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import (Any, ClassVar, Generic, Optional, TypeAlias, TypeVar, cast, get_origin)
from uuid import uuid4

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════
#  模块1: 计费体系
# ════════════════════════════════════════════════════════

class BlockCostType(str, Enum):
    RUN = "run"
    BYTE = "byte"
    SECOND = "second"
    ITEMS = "items"
    COST_USD = "cost_usd"
    TOKENS = "tokens"
    @property
    def is_dynamic(self) -> bool:
        return self in {BlockCostType.SECOND, BlockCostType.ITEMS, BlockCostType.COST_USD, BlockCostType.TOKENS}

@dataclass
class TokenRateDisplay:
    input_usd_per_1m: float = 0.0
    output_usd_per_1m: float = 0.0
    cache_read_usd_per_1m: float | None = None
    cache_creation_usd_per_1m: float | None = None
    def __post_init__(self):
        assert self.input_usd_per_1m >= 0 and self.output_usd_per_1m >= 0
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens / 1e6) * self.input_usd_per_1m + (output_tokens / 1e6) * self.output_usd_per_1m

@dataclass
class BlockCost:
    cost_amount: int = 0
    cost_type: BlockCostType = BlockCostType.RUN
    cost_filter: dict[str, Any] = field(default_factory=dict)
    cost_divisor: int = 1
    token_rate: TokenRateDisplay | None = None
    def __post_init__(self):
        self.cost_divisor = max(1, self.cost_divisor)
    def calculate(self, stats: dict[str, Any] | None = None) -> float:
        if not self.cost_type.is_dynamic:
            return float(self.cost_amount)
        if stats is None:
            return 0.0
        if self.cost_type == BlockCostType.SECOND:
            return (stats.get("walltime", 0) / self.cost_divisor) * self.cost_amount
        elif self.cost_type == BlockCostType.ITEMS:
            return (stats.get("items", 0) / self.cost_divisor) * self.cost_amount
        elif self.cost_type == BlockCostType.COST_USD:
            return stats.get("provider_cost", 0) * self.cost_amount
        elif self.cost_type == BlockCostType.TOKENS and self.token_rate:
            return self.token_rate.estimate_cost(stats.get("input_tokens", 0), stats.get("output_tokens", 0))
        return float(self.cost_amount)

# ════════════════════════════════════════════════════════
#  模块2: 认证体系
# ════════════════════════════════════════════════════════

class ProviderName(str, Enum):
    OPENAI = "openai"; ANTHROPIC = "anthropic"; GITHUB = "github"
    GOOGLE = "google"; DISCORD = "discord"; SLACK = "slack"
    TWITTER = "twitter"; REDDIT = "reddit"; CUSTOM = "custom"

@dataclass
class CredentialsMetaInput:
    provider: ProviderName | str
    credential_type: str = "oauth2"
    scopes: list[str] = field(default_factory=list)
    is_auto_credential: bool = False
    input_field_name: str = ""
    def validate(self) -> bool:
        return bool(self.provider) if isinstance(self.provider, str) else True

@dataclass
class Credentials:
    provider: ProviderName | str
    credential_type: str = "oauth2"
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    @property
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

def is_credentials_field_name(field_name: str) -> bool:
    return field_name == "credentials" or field_name.endswith("_credentials")

# ════════════════════════════════════════════════════════
#  模块3: Webhook触发配置
# ════════════════════════════════════════════════════════

@dataclass
class BlockWebhookConfig:
    provider: ProviderName | str
    webhook_type: str = ""
    event_filter_input: str = ""
    event_format: str = "{event}"
    resource_format: str = ""
    is_auto_setup: bool = False
    def format_event(self, event_name: str) -> str:
        return self.event_format.format(event=event_name)
    def format_resource(self, **kwargs: str) -> str:
        return self.resource_format.format(**kwargs) if self.resource_format else ""

# ════════════════════════════════════════════════════════
#  模块4: Schema验证体系
# ════════════════════════════════════════════════════════

BlockInput: TypeAlias = dict[str, Any]
BlockOutput: TypeAlias = AsyncGenerator[tuple[str, Any], None]

def _type_to_schema(py_type: type) -> dict[str, Any]:
    mapping = {str: {"type": "string"}, int: {"type": "integer"}, float: {"type": "number"},
               bool: {"type": "boolean"}, dict: {"type": "object"}, list: {"type": "array"}}
    origin = get_origin(py_type)
    if origin is not None:
        args = getattr(py_type, "__args__", [])
        if type(None) in args:
            base_type = next((a for a in args if a is not type(None)), str)
            return mapping.get(base_type, {"type": "string"})
    return mapping.get(py_type, {"type": "string"})

class BlockSchema:
    cached_jsonschema: ClassVar[dict[str, Any]] = {}
    schema_fields: ClassVar[dict[str, type]] = {}
    required_fields: ClassVar[set[str]] = set()
    
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.cached_jsonschema = {}
    
    @classmethod
    def jsonschema(cls) -> dict[str, Any]:
        if cls.cached_jsonschema:
            return cls.cached_jsonschema
        properties, required = {}, []
        for fn, ft in cls.schema_fields.items():
            properties[fn] = _type_to_schema(ft)
            if fn in cls.required_fields:
                required.append(fn)
        cls.cached_jsonschema = {"type": "object", "properties": properties}
        if required:
            cls.cached_jsonschema["required"] = required
        return cls.cached_jsonschema
    
    @classmethod
    def validate_data(cls, data: BlockInput, exclude_fields: set[str] | None = None) -> str | None:
        schema = cls.jsonschema()
        if exclude_fields:
            schema = {**schema, "properties": {k: v for k, v in schema.get("properties", {}).items() if k not in exclude_fields},
                      "required": [r for r in schema.get("required", []) if r not in exclude_fields]}
            data = {k: v for k, v in data.items() if k not in exclude_fields}
        required = schema.get("required", [])
        props = schema.get("properties", {})
        for f in required:
            if f not in data or data[f] is None:
                return f"Required field '{f}' is missing"
        for k, v in data.items():
            p = props.get(k, {})
            pt = p.get("type")
            if pt == "string" and not isinstance(v, str):
                return f"Field '{k}' expected string, got {type(v).__name__}"
            if pt == "integer" and not isinstance(v, int):
                return f"Field '{k}' expected integer, got {type(v).__name__}"
            if pt == "number" and not isinstance(v, (int, float)):
                return f"Field '{k}' expected number, got {type(v).__name__}"
            if pt == "boolean" and not isinstance(v, bool):
                return f"Field '{k}' expected boolean, got {type(v).__name__}"
        return None
    
    @classmethod
    def get_fields(cls) -> set[str]:
        return set(cls.schema_fields.keys())
    @classmethod
    def get_required_fields(cls) -> set[str]:
        return cls.required_fields
    @classmethod
    def get_credentials_fields(cls) -> dict[str, object]:
        return {fn: ft for fn, ft in cls.schema_fields.items() if get_origin(ft) or ft is CredentialsMetaInput}
    @classmethod
    def validate_field(cls, field_name: str, data: BlockInput) -> str | None:
        return cls.validate_data(data)
    @classmethod
    def get_missing_input(cls, data: BlockInput) -> set[str]:
        return cls.get_required_fields() - set(data)

class BlockSchemaInput(BlockSchema):
    pass

class BlockSchemaOutput(BlockSchema):
    schema_fields: ClassVar[dict[str, type]] = {"error": str}
    required_fields: ClassVar[set[str]] = set()

# ════════════════════════════════════════════════════════
#  模块5: HITL审核
# ════════════════════════════════════════════════════════

@dataclass
class ReviewDecision:
    should_proceed: bool
    message: str = ""
    review_result: Any = None

class HITLReviewHelper:
    @staticmethod
    async def handle_review_decision(input_data: BlockInput, user_id: str, node_id: str,
                                      block_name: str, editable: bool = True) -> ReviewDecision | None:
        logger.info(f"Review requested: block={block_name}, user={user_id}, node={node_id}")
        return None  # 等待外部审核

# ════════════════════════════════════════════════════════
#  模块6: 执行统计
# ════════════════════════════════════════════════════════

@dataclass
class NodeExecutionStats:
    walltime: float = 0.0
    items: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    provider_cost: float = 0.0
    error_count: int = 0
    def __add__(self, other: 'NodeExecutionStats') -> 'NodeExecutionStats':
        return NodeExecutionStats(walltime=self.walltime+other.walltime, items=self.items+other.items,
                                  input_tokens=self.input_tokens+other.input_tokens,
                                  output_tokens=self.output_tokens+other.output_tokens,
                                  provider_cost=self.provider_cost+other.provider_cost,
                                  error_count=self.error_count+other.error_count)

# ════════════════════════════════════════════════════════
#  模块7: 增强版Block
# ════════════════════════════════════════════════════════

BSchemaInput = TypeVar("BSchemaInput", bound=BlockSchemaInput)
BSchemaOutput = TypeVar("BSchemaOutput", bound=BlockSchemaOutput)

class EnhancedBlock(ABC, Generic[BSchemaInput, BSchemaOutput]):
    id: str = ""
    input_schema: type[BSchemaInput] = BlockSchemaInput
    output_schema: type[BSchemaOutput] = BlockSchemaOutput
    description: str = ""
    disabled: bool = False
    static_output: bool = False
    is_sensitive_action: bool = False
    
    def __init__(self, id="", description="", input_schema=None, output_schema=None,
                 test_input=None, test_output=None, test_mock=None, test_credentials=None,
                 disabled=False, static_output=False, is_sensitive_action=False,
                 costs=None, webhook_config=None):
        self.id = id or str(uuid4())
        self.description = description
        self.input_schema = input_schema or BlockSchemaInput
        self.output_schema = output_schema or BlockSchemaOutput
        self.test_input = test_input
        self.test_output = test_output
        self.test_mock = test_mock or {}
        self.test_credentials = test_credentials or {}
        self.disabled = disabled
        self.static_output = static_output
        self.is_sensitive_action = is_sensitive_action
        self.costs = costs or []
        self.webhook_config = webhook_config
        self.execution_stats = NodeExecutionStats()
    
    @property
    def name(self) -> str:
        return self.__class__.__name__
    
    @abstractmethod
    async def run(self, input_data: BSchemaInput, **kwargs) -> BlockOutput:
        if False:
            yield "name", "value"
        raise NotImplementedError(f"{self.name} does not implement run()")
    
    async def run_once(self, input_data: BSchemaInput, output: str, **kwargs) -> Any:
        async for name, data in self.run(input_data, **kwargs):
            if name == output:
                return data
        raise ValueError(f"{self.name} did not produce output '{output}'")
    
    def merge_stats(self, stats: NodeExecutionStats) -> NodeExecutionStats:
        self.execution_stats += stats
        return self.execution_stats
    
    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description,
                "inputSchema": self.input_schema.jsonschema(),
                "outputSchema": self.output_schema.jsonschema(),
                "costs": [{"amount": c.cost_amount, "type": c.cost_type.value} for c in self.costs],
                "disabled": self.disabled, "staticOutput": self.static_output,
                "isSensitiveAction": self.is_sensitive_action}
    
    def get_cost(self, stats: NodeExecutionStats | None = None) -> float:
        sd = {"walltime": stats.walltime, "items": stats.items, "input_tokens": stats.input_tokens,
              "output_tokens": stats.output_tokens, "provider_cost": stats.provider_cost} if stats else None
        return sum(c.calculate(sd) for c in self.costs)
    
    async def _execute(self, input_data: BlockInput, **kwargs) -> BlockOutput:
        has_context = all(k in kwargs for k in ("node_id", "user_id", "graph_id"))
        if has_context and self.is_sensitive_action:
            paused, input_data = await self._check_review(input_data, **kwargs)
            if paused:
                return
        is_dry = kwargs.get("dry_run", False)
        cred_fields = set(self.input_schema.get_credentials_fields().keys())
        if is_dry:
            err = self.input_schema.validate_data(input_data, exclude_fields=cred_fields)
        else:
            err = self.input_schema.validate_data(input_data)
        if err:
            raise ValueError(f"Input validation failed: {err}")
        async for name, data in self.run(self.input_schema(**{k: v for k, v in input_data.items() if v is not None}), **kwargs):
            yield name, data
    
    async def _check_review(self, input_data: BlockInput, **kwargs) -> tuple[bool, BlockInput]:
        decision = await HITLReviewHelper.handle_review_decision(
            input_data, kwargs.get("user_id", ""), kwargs.get("node_id", ""), self.name)
        if decision is None:
            return True, input_data
        if not decision.should_proceed:
            raise PermissionError(f"Review rejected: {decision.message}")
        return False, decision.review_result.data if hasattr(decision.review_result, 'data') else input_data

BlockTestOutput: TypeAlias = tuple[str, Any] | tuple[str, callable]
AnyBlock: TypeAlias = EnhancedBlock[BlockSchemaInput, BlockSchemaOutput]

# ════════════════════════════════════════════════════════
#  示例: LLM Block（带计费）
# ════════════════════════════════════════════════════════

class LLMInput(BlockSchemaInput):
    schema_fields: ClassVar[dict[str, type]] = {"prompt": str, "model": str, "max_tokens": int}
    required_fields: ClassVar[set[str]] = {"prompt", "model"}

class LLMOutput(BlockSchemaOutput):
    schema_fields: ClassVar[dict[str, type]] = {"text": str, "tokens_used": int, "error": str}
    required_fields: ClassVar[set[str]] = {"text"}

class LLMBlock(EnhancedBlock[LLMInput, LLMOutput]):
    def __init__(self):
        super().__init__(id="llm-block-v1", description="LLM调用（Token计费）",
                         input_schema=LLMInput, output_schema=LLMOutput,
                         costs=[BlockCost(0, BlockCostType.TOKENS,
                                          token_rate=TokenRateDisplay(3.0, 15.0))])
    async def run(self, input_data: LLMInput, **kwargs) -> BlockOutput:
        yield "text", f"Response to: {input_data.prompt[:50]}..."
        yield "tokens_used", 150

# ════════════════════════════════════════════════════════
#  GA嫁接集成
# ════════════════════════════════════════════════════════

def connect_to_ga() -> dict[str, str]:
    return {"token_cost_bridge": "TokenCache → BlockCost.TOKENS",
            "credential_bridge": "CredentialsMetaInput → Plugin.credentials",
            "block_replacement": "Block → EnhancedBlock",
            "stats_bridge": "NodeExecutionStats → GA监控",
            "hitl_bridge": "HITLReviewHelper → GA审核队列"}

# ════════════════════════════════════════════════════════
#  自检系统
# ════════════════════════════════════════════════════════

def self_check() -> dict[str, bool]:
    results = {}
    # 1. BlockCostType
    try:
        assert len(BlockCostType) == 6
        assert BlockCostType.TOKENS.is_dynamic and not BlockCostType.RUN.is_dynamic
        results["BlockCostType"] = True
    except: results["BlockCostType"] = False
    # 2. TokenRateDisplay
    try:
        r = TokenRateDisplay(3.0, 15.0)
        assert abs(r.estimate_cost(1000, 500) - 0.0105) < 1e-6
        results["TokenRateDisplay"] = True
    except: results["TokenRateDisplay"] = False
    # 3. BlockCost
    try:
        assert BlockCost(10, BlockCostType.RUN).calculate() == 10.0
        assert abs(BlockCost(5, BlockCostType.SECOND, cost_divisor=10).calculate({"walltime": 30}) - 15.0) < 1e-6
        tc = BlockCost(0, BlockCostType.TOKENS, token_rate=TokenRateDisplay(1.0, 2.0))
        assert abs(tc.calculate({"input_tokens": 500, "output_tokens": 200}) - 0.0009) < 1e-6
        results["BlockCost"] = True
    except: results["BlockCost"] = False
    # 4. CredentialsMetaInput
    try:
        c = CredentialsMetaInput(ProviderName.OPENAI, "api_key", ["generate"])
        assert c.validate()
        assert is_credentials_field_name("credentials")
        assert is_credentials_field_name("openai_credentials")
        assert not is_credentials_field_name("name")
        results["CredentialsMetaInput"] = True
    except: results["CredentialsMetaInput"] = False
    # 5. BlockSchema
    try:
        class TS(BlockSchema):
            schema_fields = {"name": str, "age": int}
            required_fields = {"name"}
        assert TS.validate_data({"name": "A", "age": 30}) is None
        assert TS.validate_data({"age": 30}) is not None
        assert TS.validate_data({"name": "A", "age": "bad"}) is not None
        results["BlockSchema"] = True
    except: results["BlockSchema"] = False
    # 6. EnhancedBlock
    try:
        b = LLMBlock()
        assert b.name == "LLMBlock"
        assert b.id == "llm-block-v1"
        assert len(b.costs) == 1
        assert b.input_schema.get_required_fields() == {"prompt", "model"}
        results["EnhancedBlock"] = True
    except: results["EnhancedBlock"] = False
    # 7. BlockWebhookConfig
    try:
        w = BlockWebhookConfig(ProviderName.GITHUB, webhook_type="repo", event_format="pull_request.{event}")
        assert w.format_event("opened") == "pull_request.opened"
        results["BlockWebhookConfig"] = True
    except: results["BlockWebhookConfig"] = False
    # 8. NodeExecutionStats
    try:
        s1 = NodeExecutionStats(walltime=10, input_tokens=100)
        s2 = NodeExecutionStats(walltime=5, output_tokens=50)
        s3 = s1 + s2
        assert s3.walltime == 15 and s3.input_tokens == 100 and s3.output_tokens == 50
        results["NodeExecutionStats"] = True
    except: results["NodeExecutionStats"] = False
    # 9. connect_to_ga
    try:
        mapping = connect_to_ga()
        assert len(mapping) == 5
        results["connect_to_ga"] = True
    except: results["connect_to_ga"] = False
    return results

if __name__ == "__main__":
    results = self_check()
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"=== skill_autogpt_core.py 自检结果 [{passed}/{total}] ===")
    for k, v in results.items():
        status = "✅" if v else "❌"
        print(f"  {status} {k}")
    print(f"总模块: {total}, 通过: {passed}")
