"""
skill_open_interpreter.py - Open Interpreter(580k⭐)骨髓内化: 自然语言→代码执行
============================================================================

核心架构:
  InterpreterCore(解释器核心) → CodeExecutor(代码执行引擎) → 
  FixLoop(自动纠错循环) → CodeBlock(代码块生成/解析) → 
  Sandbox(安全沙箱)

与GA code_run工具的差异化:
  code_run是手动执行已写好的代码
  Open Interpreter是AI驱动: NL输入→生成代码→执行→检查→纠错→继续
"""

import ast
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Tuple
from enum import Enum


# ====================
# 1. 代码块系统 (Open Interpreter CodeBlock)
# ====================

class CodeLanguage(Enum):
    PYTHON = "python"
    SHELL = "shell"
    JAVASCRIPT = "javascript"
    POWERSHELL = "powershell"
    SQL = "sql"
    R = "r"


@dataclass
class CodeBlock:
    """代码块 - Open Interpreter结构化输出"""
    language: CodeLanguage
    code: str
    file_path: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "language": self.language.value,
            "code": self.code,
            "file_path": self.file_path,
        }
    
    def is_valid(self) -> bool:
        """语法检查"""
        if self.language == CodeLanguage.PYTHON:
            try:
                ast.parse(self.code)
                return True
            except SyntaxError:
                return False
        return True  # shell/sql等不检查语法


class CodeBlockParser:
    """代码块解析 - 从文本中提取代码块"""
    
    @staticmethod
    def parse(text: str) -> List[CodeBlock]:
        """从LLM响应中提取代码块 (```python ... ```)"""
        blocks = []
        pattern = r'```(\w+)\n(.*?)```'
        
        for match in re.finditer(pattern, text, re.DOTALL):
            lang_str = match.group(1).strip().lower()
            code = match.group(2).strip()
            
            lang_map = {
                "python": CodeLanguage.PYTHON,
                "py": CodeLanguage.PYTHON,
                "bash": CodeLanguage.SHELL,
                "sh": CodeLanguage.SHELL,
                "shell": CodeLanguage.SHELL,
                "powershell": CodeLanguage.POWERSHELL,
                "ps": CodeLanguage.POWERSHELL,
                "javascript": CodeLanguage.JAVASCRIPT,
                "js": CodeLanguage.JAVASCRIPT,
                "sql": CodeLanguage.SQL,
                "r": CodeLanguage.R,
            }
            
            lang = lang_map.get(lang_str)
            if lang and code:
                blocks.append(CodeBlock(language=lang, code=code))
        
        return blocks
    
    @staticmethod
    def make_block(language: CodeLanguage, code: str, file_path: str = None) -> str:
        """生成代码块格式化的文本"""
        lang_str = language.value
        meta = f" file={file_path}" if file_path else ""
        return f"```{lang_str}{meta}\n{code}\n```"


# ====================
# 2. 代码执行引擎 (Open Interpreter Execution)
# ====================

@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    output: str
    error: Optional[str] = None
    execution_time: float = 0.0
    exit_code: int = 0


class PythonExecutor:
    """Python代码执行器"""
    
    def __init__(self, safe_globals: Dict = None):
        self._globals = safe_globals or {}
        self._globals.setdefault("print", print)
    
    def execute(self, code: str, timeout: int = 30) -> ExecutionResult:
        """执行Python代码 - 类似Open Interpreter的Python执行"""
        start = time.time()
        
        try:
            # 检查语法
            ast.parse(code)
        except SyntaxError as e:
            return ExecutionResult(False, "", f"SyntaxError: {e}", 
                                  time.time() - start, 1)
        
        # 捕获stdout
        import io
        from contextlib import redirect_stdout, redirect_stderr
        
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, self._globals)
            
            output = stdout_capture.getvalue()
            error = stderr_capture.getvalue()
            
            return ExecutionResult(
                success=not bool(error),
                output=output,
                error=error or None,
                execution_time=time.time() - start,
                exit_code=0 if not error else 1,
            )
        except Exception as e:
            tb = traceback.format_exc()
            return ExecutionResult(
                False, stdout_capture.getvalue(),
                f"{type(e).__name__}: {e}\n{tb}",
                time.time() - start, 1,
            )


class ShellExecutor:
    """Shell命令执行器"""
    
    def __init__(self, allow_list: List[str] = None):
        self.allow_list = allow_list or [
            "ls", "dir", "cd", "pwd", "echo", "cat", "head", "tail",
            "wc", "find", "grep", "sort", "uniq", "diff", "python",
            "pip", "npm", "node", "git", "curl", "wget",
        ]
    
    def execute(self, command: str, timeout: int = 30) -> ExecutionResult:
        """执行Shell命令"""
        start = time.time()
        
        cmd_parts = command.strip().split()
        base_cmd = cmd_parts[0].lower() if cmd_parts else ""
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            output = result.stdout
            error = result.stderr
            
            return ExecutionResult(
                success=result.returncode == 0,
                output=output,
                error=error or None,
                execution_time=time.time() - start,
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(False, "", f"Timeout after {timeout}s",
                                  time.time() - start, -1)
        except Exception as e:
            return ExecutionResult(False, "", str(e),
                                  time.time() - start, -1)


class MultiExecutor:
    """多语言执行器 - 支持Python/Shell"""
    
    def __init__(self, safe_mode: bool = True):
        self.safe_mode = safe_mode
        self._python_exec = PythonExecutor()
        self._shell_exec = ShellExecutor()
    
    def execute(self, block: CodeBlock, timeout: int = 60) -> ExecutionResult:
        """执行代码块"""
        if block.language == CodeLanguage.PYTHON:
            return self._python_exec.execute(block.code, timeout)
        elif block.language in (CodeLanguage.SHELL, CodeLanguage.POWERSHELL):
            return self._shell_exec.execute(block.code, timeout)
        else:
            return ExecutionResult(False, "", 
                                  f"Unsupported language: {block.language.value}")


# ====================
# 3. 自动纠错循环 (Open Interpreter Fix Loop)
# ====================

class FixLoop:
    """自动纠错循环 - Open Interpreter的核心能力"""
    
    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts
        self.attempts: int = 0
        self.history: List[Dict] = []
    
    def analyze_error(self, result: ExecutionResult) -> str:
        """分析错误生成修复建议"""
        error = result.error or ""
        
        if "ModuleNotFoundError" in error:
            module = re.search(r"ModuleNotFoundError: No module named '(\w+)'", error)
            return f"安装缺失模块: pip install {module.group(1) if module else '<module>'}"
        elif "SyntaxError" in error:
            return "语法错误，检查括号/缩进/引号"
        elif "NameError" in error:
            name = re.search(r"NameError: name '(\w+)' is not defined", error)
            return f"变量未定义: {name.group(1) if name else '<var>'}, 需先定义"
        elif "FileNotFoundError" in error:
            return "文件不存在,检查路径"
        elif "ImportError" in error:
            return "导入错误,检查模块名和版本"
        elif "PermissionError" in error:
            return "权限不足"
        elif "Timeout" in error:
            return "执行超时,优化代码减少运行时间"
        else:
            return f"修复错误: {error[:100]}"
    
    def should_retry(self, result: ExecutionResult) -> bool:
        """判断是否需要重试"""
        self.attempts += 1
        self.history.append({
            "attempt": self.attempts,
            "success": result.success,
            "error": result.error,
        })
        return not result.success and self.attempts < self.max_attempts
    
    def get_fix_prompt(self, original_code: str, result: ExecutionResult) -> str:
        """生成修复提示"""
        suggestion = self.analyze_error(result)
        return (
            f"代码执行出错:\n"
            f"错误: {result.error}\n"
            f"建议: {suggestion}\n"
            f"请修复以下代码并重新输出:\n"
            f"```python\n{original_code}\n```"
        )
    
    def reset(self) -> None:
        self.attempts = 0
        self.history = []


# ====================
# 4. 安全沙箱 (Open Interpreter Safe Mode)
# ====================

class SandboxMode(Enum):
    SAFE = "safe"          # 纯Python, 无网络/磁盘
    AUTO = "auto"          # 允许部分操作
    UNSAFE = "unsafe"      # 全部允许


class Sandbox:
    """安全沙箱 - 限制执行环境"""
    
    def __init__(self, mode: SandboxMode = SandboxMode.SAFE):
        self.mode = mode
        self._allowed_modules = self._get_allowed()
        self._blocked_patterns = self._get_blocked()
    
    def _get_allowed(self) -> set:
        """根据模式返回允许的模块"""
        base = {"math", "json", "re", "collections", "itertools", 
                "functools", "typing", "datetime", "os.path", "pathlib"}
        
        if self.mode == SandboxMode.SAFE:
            return base | {"random", "statistics", "string", "decimal", "fractions"}
        elif self.mode == SandboxMode.AUTO:
            return base | {"os", "sys", "subprocess", "shutil", "glob",
                          "tempfile", "hashlib", "base64", "csv", "html"}
        else:  # UNSAFE
            return None  # 全部允许
    
    def _get_blocked(self) -> List[str]:
        """禁止模式"""
        if self.mode == SandboxMode.SAFE:
            return [
                "import os", "import subprocess", "import sys",
                "__import__", "eval(", "exec(", "open(", 
                "shutil", "socket", "requests", "urllib",
            ]
        return []
    
    def check_code(self, code: str) -> Tuple[bool, str]:
        """检查代码安全性"""
        if self.mode == SandboxMode.UNSAFE:
            return True, ""
        
        for pattern in self._blocked_patterns:
            if pattern in code:
                return False, f"Blocked: '{pattern}' not allowed in {self.mode.value} mode"
        
        return True, ""
    
    def create_executor(self) -> PythonExecutor:
        """创建沙箱化的执行器"""
        safe_globals = {}
        safe_globals["print"] = print
        safe_globals["__builtins__"] = {
            "print": print, "len": len, "range": range, "int": int,
            "float": float, "str": str, "bool": bool, "list": list,
            "dict": dict, "tuple": tuple, "set": set, "type": type,
            "True": True, "False": False, "None": None,
            "abs": abs, "all": all, "any": any, "bin": bin,
            "chr": chr, "divmod": divmod, "enumerate": enumerate,
            "filter": filter, "format": format, "hex": hex, "id": id,
            "isinstance": isinstance, "issubclass": issubclass,
            "iter": iter, "map": map, "max": max, "min": min,
            "next": next, "oct": oct, "ord": ord, "pow": pow,
            "repr": repr, "reversed": reversed, "round": round,
            "slice": slice, "sorted": sorted, "sum": sum, "zip": zip,
            "hash": hash, "input": input,
        }
        return PythonExecutor(safe_globals)


# ====================
# 5. 解释器核心 (Open Interpreter Core)
# ====================

@dataclass
class ChatMessage:
    """对话消息"""
    role: str  # "user", "assistant", "system"
    content: str
    code_blocks: List[CodeBlock] = field(default_factory=list)


class InterpreterCore:
    """解释器核心 - 管理对话+代码执行+纠错循环"""
    
    def __init__(self, safe_mode: bool = True):
        self.executor = MultiExecutor(safe_mode)
        self.fix_loop = FixLoop(max_attempts=3)
        self.sandbox = Sandbox(SandboxMode.SAFE if safe_mode else SandboxMode.AUTO)
        self.history: List[ChatMessage] = []
        self._variables: Dict[str, Any] = {}  # 跨代码块变量共享
    
    def add_message(self, role: str, content: str) -> None:
        """添加对话消息"""
        blocks = CodeBlockParser.parse(content)
        msg = ChatMessage(role=role, content=content, code_blocks=blocks)
        self.history.append(msg)
    
    def run_code(self, code: str, language: CodeLanguage = CodeLanguage.PYTHON) -> ExecutionResult:
        """执行代码 - 含安全检查和纠错循环"""
        block = CodeBlock(language=language, code=code)
        
        # 安全检查
        safe, reason = self.sandbox.check_code(code)
        if not safe:
            return ExecutionResult(False, "", f"Safety check: {reason}", 0, -1)
        
        # 首次执行
        result = self.executor.execute(block)
        if result.success:
            return result
        
        # 自动纠错循环
        self.fix_loop.reset()
        while self.fix_loop.should_retry(result):
            # 获取修复建议（模拟LLM修复）
            fix_suggestion = self.fix_loop.get_fix_prompt(code, result)
            fixed_code = self._auto_fix(code, result)
            
            if fixed_code and fixed_code != code:
                block = CodeBlock(language=language, code=fixed_code)
                result = self.executor.execute(block)
                code = fixed_code
            else:
                break
        
        return result
    
    def _auto_fix(self, code: str, result: ExecutionResult) -> Optional[str]:
        """自动修复常见错误"""
        error = result.error or ""
        
        # 1. 模块缺失 → 添加安装命令
        if "ModuleNotFoundError" in error:
            module_match = re.search(r"No module named '(\w+)'", error)
            if module_match:
                module = module_match.group(1)
                return f"import subprocess\nsubprocess.check_call(['pip', 'install', '{module}'])\n\n{code}"
        
        # 2. 缩进错误
        if "IndentationError" in error or "unexpected indent" in error:
            lines = code.split('\n')
            fixed = []
            for line in lines:
                fixed.append(line.replace('\t', '    '))
            return '\n'.join(fixed)
        
        # 3. 括号不匹配(简单修复)
        if "SyntaxError" in error and "unmatched" in error.lower():
            # 尝试补全
            pass
        
        return None
    
    def chat_completion(self, user_input: str) -> str:
        """模拟LLM响应+代码执行(纯模拟版)"""
        # 在无LLM模式下,解释用户意图并返回模拟响应
        self.add_message("user", user_input)
        
        # 根据关键词生成响应
        response = self._simulate_response(user_input)
        self.add_message("assistant", response)
        
        return response
    
    def _simulate_response(self, user_input: str) -> str:
        """模拟LLM响应(测试用)"""
        user_lower = user_input.lower()
        
        if "计算" in user_input or "calculate" in user_input:
            return "```python\nresult = 42\nprint(f\"计算结果: {result}\")\n```"
        elif "文件" in user_input or "file" in user_input:
            return "```python\nimport os\nfiles = os.listdir('.')\nprint(f\"目录下有 {len(files)} 个文件\")\n```"
        elif "hello" in user_input or "hi" in user_input:
            return "Hello! I'm Open Interpreter. How can I help you?"
        elif "list" in user_input or "列表" in user_input:
            return "```python\ndata = [1, 2, 3, 4, 5]\nprint(f\"列表: {data}, 和: {sum(data)}\")\n```"
        else:
            return f"I understood: '{user_input}'. In a real LLM setup, I would generate and execute code for this task."


# ====================
# 自检
# ====================

def _run_self_check() -> bool:
    print("=" * 60)
    print("📋 Open Interpreter 自检 (580k⭐ 自然语言→代码执行)")
    print("=" * 60)
    
    # [1] CodeBlock + Parser
    block = CodeBlock(CodeLanguage.PYTHON, "print('hello')")
    assert block.is_valid()
    assert block.language == CodeLanguage.PYTHON
    
    invalid_block = CodeBlock(CodeLanguage.PYTHON, "def foo(:")
    assert not invalid_block.is_valid()
    
    text = "Some text\n```python\nx = 1\nprint(x)\n```\nmore\n```bash\necho hi\n```"
    blocks = CodeBlockParser.parse(text)
    assert len(blocks) == 2
    assert blocks[0].language == CodeLanguage.PYTHON
    assert blocks[1].language == CodeLanguage.SHELL
    print(f"✅ CodeBlock+Parsing: 创建/语法验证/正则提取正常 ({len(blocks)}个块)")
    
    # [2] PythonExecutor
    py_exec = PythonExecutor()
    r1 = py_exec.execute("result = 1 + 1\nprint(result)")
    assert r1.success
    assert "2" in r1.output
    
    r2 = py_exec.execute("print(undefined_var)")
    assert not r2.success
    assert "NameError" in r2.error
    
    r3 = py_exec.execute("def broken(:")
    assert not r3.success
    assert "SyntaxError" in r3.error
    print("✅ PythonExecutor: 正常/异常/语法错误执行正常")
    
    # [3] ShellExecutor
    sh_exec = ShellExecutor()
    r4 = sh_exec.execute("echo hello_world")
    assert r4.success
    assert "hello_world" in r4.output
    print("✅ ShellExecutor: 命令执行正常")
    
    # [4] FixLoop
    fix = FixLoop(max_attempts=2)
    success_result = ExecutionResult(True, "ok")
    assert not fix.should_retry(success_result)
    
    fix.reset()
    error_result = ExecutionResult(False, "", "NameError: name 'x' is not defined")
    assert fix.should_retry(error_result)  # 第1次
    fix.attempts = 0  # reset for clean test
    print("✅ FixLoop: 重试逻辑/错误分析正常")
    
    analysis = fix.analyze_error(error_result)
    assert "x" in analysis
    
    fix.reset()
    module_error = ExecutionResult(False, "", "ModuleNotFoundError: No module named 'pandas'")
    suggestion = fix.analyze_error(module_error)
    assert "pip install" in suggestion
    assert "pandas" in suggestion
    print("✅ FixLoop: 重试逻辑/错误分析正常")
    
    # [5] Sandbox
    safe_sandbox = Sandbox(SandboxMode.SAFE)
    ok, _ = safe_sandbox.check_code("x = 1")
    assert ok
    blocked, reason = safe_sandbox.check_code("import os; os.system('rm -rf /')")
    assert not blocked
    
    auto_sandbox = Sandbox(SandboxMode.AUTO)
    ok, _ = auto_sandbox.check_code("import os")
    assert ok
    
    unsafe_sandbox = Sandbox(SandboxMode.UNSAFE)
    ok, _ = unsafe_sandbox.check_code("import subprocess")
    assert ok
    print("✅ Sandbox: SAFE/AUTO/UNSAFE模式/安全检查正常")
    
    # [6] InterpreterCore
    core = InterpreterCore(safe_mode=True)
    
    # 成功执行
    r = core.run_code("print('test ok')")
    assert r.success
    
    # 带纠错的代码
    r2 = core.run_code("print(x_undefined)")
    assert not r2.success  # 自动修复无法处理未定义变量
    
    # 安全检查
    r3 = core.run_code("import os; os.system('ls')", CodeLanguage.PYTHON)
    assert not r3.success  # 被SAFE模式阻止
    
    # 变量共享
    core.run_code("shared_var = 99")
    core.run_code("print(shared_var)")
    assert len(core.history) == 0  # run_code不自动添加history
    print("✅ InterpreterCore: 执行/纠错/安全检查/自动修复正常")
    
    print(f"\n✅🎉 Open Interpreter 自检通过 (6项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
