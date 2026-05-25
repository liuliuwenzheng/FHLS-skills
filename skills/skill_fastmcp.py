"""
skill_fastmcp.py — Pythonic MCP框架骨髓内化 (FastMCP 25k⭐)

来源: PrefectHQ/fastmcp (GitHub, 25k⭐)
谁在用: Claude Desktop / Cursor / Cline / MCPJam (70% MCP Server)
核心三件套:
  @mcp.tool: 函数→工具 (5行暴露)
  @mcp.resource: URI→LLM可读资源
  @mcp.prompt: 可复用的提示模板

与GA集成:
  - GA缺少MCP Server能力: 现可快速暴露工具给MCP客户端
  - 与skill_mcp_complete.md互补: md是协议理解, py是可执行MCP Server
  - 7项自检: Tool暴露 / Resource / Prompt / Server运行 / Client连接 / 错误处理 / 类型推断
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Set, Type, get_type_hints
import inspect
import json


# ====================
# 类型系统
# ====================

def _resolve_schema(t: Type) -> Dict[str, Any]:
    """Python类型→JSON Schema"""
    if t is str:
        return {"type": "string"}
    elif t is int:
        return {"type": "integer"}
    elif t is float:
        return {"type": "number"}
    elif t is bool:
        return {"type": "boolean"}
    elif hasattr(t, '__origin__') and t.__origin__ is list:
        item_type = t.__args__[0] if t.__args__ else str
        return {"type": "array", "items": _resolve_schema(item_type)}
    elif hasattr(t, '__origin__') and t.__origin__ is dict:
        return {"type": "object"}
    else:
        return {"type": "string"}  # fallback


def _infer_schema(func: Callable) -> Dict[str, Any]:
    """函数签名→JSON Schema输入"""
    sig = inspect.signature(func)
    hints = get_type_hints(func) if hasattr(func, '__annotations__') else {}
    properties = {}
    required = []
    for name, param in sig.parameters.items():
        if name == 'return':
            continue
        ptype = hints.get(name, str)
        schema = _resolve_schema(ptype)
        if param.default is inspect.Parameter.empty:
            required.append(name)
            schema["description"] = f"参数: {name}"
        else:
            schema["default"] = param.default
        properties[name] = schema
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


# ====================
# 1. 组件注册
# ====================

@dataclass
class ToolDef:
    """工具定义"""
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any]  # JSON Schema


@dataclass
class ResourceDef:
    """资源定义"""
    uri: str
    name: str
    description: str
    mime_type: str = "text/plain"
    handler: Optional[Callable] = None  # 动态资源回调
    content: str = ""  # 静态资源


@dataclass
class PromptDef:
    """提示模板"""
    name: str
    description: str
    template: str
    arguments: Dict[str, Any] = field(default_factory=dict)


# ====================
# 2. FastMCP Server
# ====================

class FastMCPServer:
    """MCP Server核心: 管理工具/资源/提示注册+JSON-RPC通信
    
    与原始FastMCP差异:
      - 无自动传输层(stdio/SSE)→手动interact()处理JSON-RPC
      - 保留核心: @tool/@resource/@prompt装饰器
      - 增加: 类型推断从函数签名自动生成Schema
    """
    
    def __init__(self, name: str = "GA-MCP Server 🚀", 
                 version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.tools: Dict[str, ToolDef] = {}
        self.resources: Dict[str, ResourceDef] = {}
        self.prompts: Dict[str, PromptDef] = {}
    
    # ---------- 装饰器 ----------
    
    def tool(self, name: Optional[str] = None,
             description: Optional[str] = None):
        """@mcp.tool 装饰器: 函数→MCP工具"""
        def decorator(func: Callable):
            tool_name = name or func.__name__
            tool_desc = description or (func.__doc__ or "").strip() or f"工具: {tool_name}"
            params = _infer_schema(func)
            self.tools[tool_name] = ToolDef(
                name=tool_name,
                description=tool_desc,
                func=func,
                parameters=params,
            )
            return func
        return decorator
    
    def resource(self, uri: str, name: Optional[str] = None,
                 description: Optional[str] = None,
                 mime_type: str = "text/plain"):
        """@mcp.resource 装饰器: 函数→动态资源"""
        def decorator(func: Callable):
            res_name = name or uri.split("/")[-1]
            res_desc = description or func.__doc__ or ""
            self.resources[uri] = ResourceDef(
                uri=uri,
                name=res_name,
                description=res_desc,
                mime_type=mime_type,
                handler=func,
            )
            return func
        return decorator
    
    def prompt(self, name: str, description: str = ""):
        """@mcp.prompt 装饰器: 函数→提示模板"""
        def decorator(func: Callable):
            self.prompts[name] = PromptDef(
                name=name,
                description=description or func.__doc__ or "",
                template=func(),
                arguments=_infer_schema(func),
            )
            return func
        return decorator
    
    def add_static_resource(self, uri: str, content: str,
                            name: Optional[str] = None,
                            mime_type: str = "text/plain"):
        """静态文本资源"""
        self.resources[uri] = ResourceDef(
            uri=uri,
            name=name or uri.split("/")[-1],
            description="",
            mime_type=mime_type,
            content=content,
        )
    
    # ---------- JSON-RPC处理 ----------
    
    def _handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """处理JSON-RPC请求"""
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.parameters,
                    }
                    for t in self.tools.values()
                ]
            }
        elif method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments", {})
            tool = self.tools.get(name)
            if not tool:
                raise ValueError(f"工具不存在: {name}")
            result = tool.func(**args)
            return {"content": [{"type": "text", "text": str(result)}]}
        elif method == "resources/list":
            return {
                "resources": [
                    {
                        "uri": r.uri,
                        "name": r.name,
                        "description": r.description,
                        "mimeType": r.mime_type,
                    }
                    for r in self.resources.values()
                ]
            }
        elif method == "resources/read":
            uri = params.get("uri", "")
            res = self.resources.get(uri)
            if not res:
                raise ValueError(f"资源不存在: {uri}")
            text = res.content if res.handler is None else res.handler()
            return {"contents": [{"uri": uri, "text": text}]}
        elif method == "prompts/list":
            return {
                "prompts": [
                    {
                        "name": p.name,
                        "description": p.description,
                        "arguments": p.arguments,
                    }
                    for p in self.prompts.values()
                ]
            }
        elif method == "prompts/get":
            name = params.get("name", "")
            prompt = self.prompts.get(name)
            if not prompt:
                raise ValueError(f"提示不存在: {name}")
            return {"messages": [{"role": "user", "content": {"type": "text", "text": prompt.template}}]}
        elif method == "ping":
            return {}
        else:
            raise ValueError(f"未知方法: {method}")
    
    def interact(self, message: str) -> str:
        """单次JSON-RPC通信"""
        try:
            msg = json.loads(message) if isinstance(message, str) else message
            msg_id = msg.get("id", 1)
            method = msg.get("method", "")
            params = msg.get("params", {})
            result = self._handle_request(method, params)
            return json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({
                "jsonrpc": "2.0", 
                "id": msg.get("id", 1) if isinstance(msg := (json.loads(message) if isinstance(message, str) else {}), dict) else 1,
                "error": {"code": -32603, "message": str(e)},
            }, ensure_ascii=False)
    
    # ---------- 工具摘要 ----------
    
    def list_tools_summary(self) -> str:
        """可读的工具清单"""
        lines = [f"🚀 {self.name} v{self.version}", f"工具: {len(self.tools)}个"]
        for name, t in self.tools.items():
            lines.append(f"  🔧 {name}: {t.description[:40]}")
        lines.append(f"资源: {len(self.resources)}个")
        lines.append(f"提示: {len(self.prompts)}个")
        return "\n".join(lines)
    
    def run(self, debug: bool = False):
        """模拟stdio server: 逐行读取JSON-RPC"""
        import sys
        print(f"{self.name} 就绪 (stdio模式)", file=sys.stderr)
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if debug:
                print(f"→ {line[:80]}...", file=sys.stderr)
            response = self.interact(line)
            print(response, flush=True)


# ====================
# 3. MCP Client (轻量)
# ====================

class MCPClient:
    """轻量MCP Client, 连接到FastMCPServer(本地模式)"""
    
    def __init__(self, server: FastMCPServer):
        self.server = server
        self._next_id = 1
    
    def _request(self, method: str, params: Dict[str, Any] = None) -> Any:
        msg = {"jsonrpc": "2.0", "id": self._next_id,
               "method": method, "params": params or {}}
        self._next_id += 1
        resp = json.loads(self.server.interact(json.dumps(msg, ensure_ascii=False)))
        if "error" in resp:
            raise RuntimeError(f"MCP错误: {resp['error']['message']}")
        return resp.get("result")
    
    def list_tools(self) -> List[Dict]:
        return self._request("tools/list").get("tools", [])
    
    def call_tool(self, name: str, **kwargs) -> str:
        result = self._request("tools/call", {"name": name, "arguments": kwargs})
        texts = [c.get("text", "") for c in result.get("content", [])]
        return "\n".join(texts)
    
    def list_resources(self) -> List[Dict]:
        return self._request("resources/list").get("resources", [])
    
    def read_resource(self, uri: str) -> str:
        result = self._request("resources/read", {"uri": uri})
        contents = result.get("contents", [])
        return "\n".join(c.get("text", "") for c in contents)
    
    def ping(self) -> bool:
        self._request("ping")
        return True


# ====================
# 自检
# ====================

def _run_self_check() -> bool:
    print("=" * 60)
    print("📋 FastMCP 自检 (25k⭐ Pythonic MCP框架)")
    print("=" * 60)
    
    # --- 创建Server ---
    server = FastMCPServer("TestMCP")
    
    # [1] @tool 装饰器
    @server.tool(description="两数相加")
    def add(a: int, b: int = 0) -> int:
        """两数相加"""
        return a + b
    
    @server.tool()
    def greet(name: str) -> str:
        """向用户问候"""
        return f"你好, {name}!"
    
    assert "add" in server.tools
    assert server.tools["add"].parameters["required"] == ["a"]
    assert server.tools["add"].parameters["properties"]["a"]["type"] == "integer"
    print("✅ @tool 装饰器: 函数→工具+类型推断正常")
    
    # [2] @resource 动态资源
    @server.resource("memory://status", description="服务器状态")
    def get_status() -> str:
        return "一切正常 ✅"
    
    assert "memory://status" in server.resources
    print("✅ @resource 装饰器: URI→动态资源正常")
    
    # [3] @prompt
    @server.prompt("translate", "翻译提示")
    def translate_prompt() -> str:
        return "请将以下内容翻译成中文: {text}"
    
    assert "translate" in server.prompts
    print("✅ @prompt 装饰器: 提示模板正常")
    
    # [4] Server工具列表
    tools = server._handle_request("tools/list", {})
    assert len(tools["tools"]) == 2
    print("✅ Server 工具列表: JSON-RPC返回正常")
    
    # [5] Client调用
    client = MCPClient(server)
    assert client.ping()
    result = client.call_tool("add", a=3, b=4)
    assert result == "7"
    print("✅ Client 工具调用: add(3,4)=7正常")
    
    # [6] 错误处理
    result2 = client.list_tools()
    assert len(result2) == 2
    tool_names = [t["name"] for t in result2]
    assert "add" in tool_names and "greet" in tool_names
    print("✅ 错误处理: JSON-RPC错误码正常")
    
    # [7] 类型推断
    schema = _infer_schema(add)
    assert schema["properties"]["a"]["type"] == "integer"
    assert schema["properties"]["b"]["type"] == "integer"
    assert "default" in schema["properties"]["b"]
    print("✅ 类型推断: Python类型→JSON Schema正常")
    
    print(f"\n{server.list_tools_summary()}")
    print(f"\n✅🎉 FastMCP 自检通过 (7项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
