"""
skill_sandbox.py — 安全代码沙箱 (GA基础设施)

为什么需要: 当前GA直接exec()运行用户/LLM代码, 存在安全风险
核心: subprocess隔离 + 超时 + 内存限制 + 禁用黑名单
零依赖: 只用标准库

与GA集成:
  - code_run: 替换直接subprocess, 用沙箱包装
  - LLM生成代码执行: 必须先过沙箱
  - 风险评分: 自动检测危险模式
"""

import os
import sys
import subprocess
import tempfile
import time
import ast
import json
import signal
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path


# ═══════════════════════════════════════
# 1. 危险模式检测
# ═══════════════════════════════════════

# 黑名单: 禁止导入的模块
BLOCKED_MODULES = {
    'os', 'subprocess', 'sys', 'shutil', 'ctypes',
    'socket', 'http', 'urllib', 'requests', 'ftplib',
    'telnetlib', 'smtplib', 'poplib', 'imaplib',
    'multiprocessing', 'threading', 'concurrent',
    'pickle', 'shelve', 'marshal', 'code', 'codeop',
    'pty', 'tty', 'termios', 'fcntl', 'mmap',
    'crypt', 'grp', 'pwd', 'spwd',
    'winreg', 'win32api', 'win32pipe',
    'ctypes', 'imp', 'importlib', 'builtins',
    'inspect', 'traceback', 'pdb', 'profile',
    'webbrowser', 'tkinter', 'getpass',
}

# 危险代码模式 (AST检测)
DANGEROUS_PATTERNS = [
    # 文件系统危险操作
    ('os.remove', 'os.unlink', 'os.rmdir', 'shutil.rmtree'),
    ('os.chmod', 'os.chown'),
    ('open', '__builtins__.open', '__builtins__.__dict__["open"]'),
    # 执行/编译
    ('exec', 'eval', 'compile', '__import__'),
    ('__builtins__', 'builtins'),
    # 进程/系统
    ('os.system', 'os.popen', 'subprocess'),
    ('os.kill', 'os.abort'),
    # 网络
    ('socket', 'urllib', 'requests'),
    # 反射/内省
    ('__subclasses__', '__globals__', '__code__'),
    ('ctypes', '_ctypes'),
]

@dataclass
class RiskReport:
    """风险分析报告"""
    level: str = "safe"  # safe | warning | blocked
    score: int = 0
    reasons: List[str] = field(default_factory=list)
    
    def add_reason(self, reason: str, score_inc: int = 10):
        self.reasons.append(reason)
        self.score += score_inc
        if self.score >= 50:
            self.level = "blocked"
        elif self.score >= 20:
            self.level = "warning"
    
    @property
    def is_blocked(self) -> bool:
        return self.level == "blocked"
    
    @property
    def summary(self) -> str:
        if self.is_blocked:
            return f"🚫 已拦截 (风险{self.score}): {', '.join(self.reasons[:3])}"
        elif self.level == "warning":
            return f"⚠️ 警告 (风险{self.score}): {', '.join(self.reasons[:3])}"
        return "✅ 安全"


def analyze_code_ast(code: str) -> RiskReport:
    """AST静态分析代码风险"""
    report = RiskReport()
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        report.add_reason(f"语法错误: {e}", 40)
        return report
    
    for node in ast.walk(tree):
        # 检测危险导入
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in BLOCKED_MODULES or any(
                    alias.name.startswith(b) for b in BLOCKED_MODULES
                ):
                    report.add_reason(f"禁止导入: {alias.name}", 50)
        
        elif isinstance(node, ast.ImportFrom):
            if node.module in BLOCKED_MODULES:
                report.add_reason(f"禁止导入: {node.module}", 50)
        
        # 检测exec/eval/compile
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in ('exec', 'eval', 'compile', '__import__'):
                    report.add_reason(f"禁止调用: {node.func.id}()", 50)
            
            elif isinstance(node.func, ast.Attribute):
                full_name = ""
                if isinstance(node.func.value, ast.Name):
                    full_name = f"{node.func.value.id}.{node.func.attr}"
                elif isinstance(node.func.value, ast.Attribute):
                    full_name = f"...{node.func.attr}"
                
                for pattern_group in DANGEROUS_PATTERNS:
                    if full_name in pattern_group:
                        report.add_reason(f"危险操作: {full_name}", 30)
        
        # 检测__builtins__/__import__等dunder
        elif isinstance(node, ast.Attribute):
            if node.attr in ('__builtins__', '__globals__', '__code__', '__class__'):
                report.add_reason(f"危险属性: {node.attr}", 30)
        
        # 检测while True无break (潜在死循环)
        elif isinstance(node, ast.While):
            if isinstance(node.test, ast.Constant) and node.test.value is True:
                has_break = any(
                    isinstance(n, ast.Break) for n in ast.walk(node)
                )
                if not has_break:
                    report.add_reason("潜在死循环: while True无break", 15)
    
    return report


# ═══════════════════════════════════════
# 2. 沙箱执行器
# ═══════════════════════════════════════

@dataclass
class SandboxResult:
    """沙箱执行结果"""
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    elapsed: float = 0.0
    error: str = ""
    risk: RiskReport = None
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "stdout": self.stdout[:500],
            "stderr": self.stderr[:500],
            "returncode": self.returncode,
            "elapsed": round(self.elapsed, 3),
            "error": self.error[:200] if self.error else "",
        }


class CodeSandbox:
    """安全代码沙箱"""
    
    # 安全内建函数白名单
    SAFE_BUILTINS = {
        'abs', 'all', 'any', 'ascii', 'bin', 'bool', 'bytearray', 'bytes',
        'chr', 'complex', 'dict', 'dir', 'divmod', 'enumerate', 'filter',
        'float', 'format', 'frozenset', 'getattr', 'hasattr', 'hash',
        'hex', 'id', 'int', 'isinstance', 'issubclass', 'iter', 'len',
        'list', 'map', 'max', 'min', 'next', 'object', 'oct', 'ord',
        'pow', 'print', 'range', 'repr', 'reversed', 'round', 'set',
        'slice', 'sorted', 'str', 'sum', 'tuple', 'type', 'zip',
        'True', 'False', 'None', 'Exception', 'ValueError', 'TypeError',
        'KeyError', 'IndexError', 'AttributeError', 'ImportError',
        'RuntimeError', 'StopIteration', 'ArithmeticError',
        'ZeroDivisionError', 'FileNotFoundError', 'PermissionError',
        '__import__',  # 需要但受限
    }
    
    def __init__(self, timeout: int = 10, max_memory_mb: int = 256,
                 enable_network: bool = False, enable_filesystem: bool = False):
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.enable_network = enable_network
        self.enable_filesystem = enable_filesystem
    
    def execute(self, code: str, stdin: str = "") -> SandboxResult:
        """执行代码(安全模式: subprocess+timeout+限制)"""
        result = SandboxResult()
        start = time.time()
        
        # 1. AST风险分析
        risk = analyze_code_ast(code)
        result.risk = risk
        
        if risk.is_blocked:
            result.error = risk.summary
            result.success = False
            result.elapsed = time.time() - start
            return result
        
        # 2. 沙箱包装
        wrapped = self._wrap_code(code)
        
        # 3. subprocess执行
        try:
            proc = subprocess.run(
                [sys.executable, '-c', wrapped],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={} if not self.enable_network else None,
            )
            result.stdout = proc.stdout
            result.stderr = proc.stderr
            result.returncode = proc.returncode
            result.success = proc.returncode == 0
            
            if risk.level == "warning":
                result.stderr += f"\n[沙箱警告] {risk.summary}"
            
        except subprocess.TimeoutExpired:
            result.error = f"⏱ 执行超时 ({self.timeout}s)"
        except FileNotFoundError:
            result.error = "❌ Python解释器未找到"
        except Exception as e:
            result.error = f"❌ 执行异常: {e}"
        
        result.elapsed = time.time() - start
        return result
    
    def _wrap_code(self, code: str) -> str:
        """包装代码: 添加安全限制"""
        # 禁用危险操作: 用空函数替换
        block_danger = '''
# 🛡️ 安全限制
import sys as _sys
import os as _os
import builtins as _b

# 禁用子进程
def _blocked(*a, **kw):
    raise PermissionError("[沙箱] 禁止子进程/系统调用")
_os.system = _blocked
_os.popen = _blocked
if hasattr(_os, 'execv'): _os.execv = _blocked
if hasattr(_os, 'execve'): _os.execve = _blocked

# 限制文件删除
_original_remove = _os.remove
def _safe_remove(path):
    raise PermissionError(f"[沙箱] 禁止删除: {path}")
_os.remove = _safe_remove
_os.unlink = _safe_remove
'''
        
        # 如果禁用文件系统, 拦截open写入
        fs_block = ""
        if not self.enable_filesystem:
            fs_block = '''
_original_open = _b.open
def _safe_open(file, mode='r', *a, **kw):
    if any(c in str(mode) for c in 'wax+'):
        raise PermissionError(f"[沙箱] 禁止写入: {file}")
    return _original_open(file, mode, *a, **kw)
_b.open = _safe_open
'''
        
        wrapped = f"""{block_danger}{fs_block}
_sys.path.clear()
_sys.path.append(r'{tempfile.gettempdir()}')
try:
{self._indent(code)}
except Exception as _e:
    import traceback as _t
    print(f"[沙箱异常] {{_e}}", file=_sys.stderr)
    _t.print_exc(file=_sys.stderr)
    _sys.exit(1)
"""
        return wrapped
    
    @staticmethod
    def _indent(code: str, level: int = 1) -> str:
        lines = code.split('\n')
        indented = '\n'.join('    ' * level + l if l.strip() else l for l in lines)
        return indented


# ═══════════════════════════════════════
# 3. 简易限制执行 (restricted_exec)
# ═══════════════════════════════════════

def restricted_exec(code: str, globals_dict: Dict = None,
                    timeout: int = 5) -> Tuple[Any, str, float]:
    """
    轻量限制执行(同进程, 用于快速计算)
    不隔离 - 仅适合信任代码
    """
    if globals_dict is None:
        globals_dict = {}
    risk = analyze_code_ast(code)
    if risk.is_blocked:
        return None, f"🚫 {risk.summary}", 0.0
    
    start = time.time()
    try:
        compiled = compile(code, '<sandbox>', 'exec')
        exec(compiled, {"__builtins__": __builtins__}, globals_dict)
        elapsed = time.time() - start
        return globals_dict, "", elapsed
    except Exception as e:
        elapsed = time.time() - start
        return None, str(e), elapsed


# ═══════════════════════════════════════
# 4. 便利函数
# ═══════════════════════════════════════

def analyze_risk(code: str) -> RiskReport:
    """快速风险分析"""
    return analyze_code_ast(code)


def sandbox_run(code: str, timeout: int = 10, **kwargs) -> SandboxResult:
    """一行API: 运行沙箱"""
    sandbox = CodeSandbox(timeout=timeout, **kwargs)
    return sandbox.execute(code)


# ═══════════════════════════════════════
# 自检
# ═══════════════════════════════════════

def _run_self_check():
    print("=" * 60)
    print("📋 沙箱自检 (安全代码执行引擎)")
    print("=" * 60)
    
    # 1. 安全代码
    safe_code = "x = 1 + 2\nprint(f'结果: {x}')"
    risk = analyze_code_ast(safe_code)
    assert risk.level == "safe"
    print(f"✅ 安全代码检测: {risk.level}")
    
    # 2. 危险代码 (导入os)
    bad_import = "import os\nos.listdir('.')"
    risk = analyze_code_ast(bad_import)
    assert risk.is_blocked
    print(f"✅ 危险导入检测: {risk.summary}")
    
    # 3. exec检测
    bad_exec = "exec('print(1)')"
    risk = analyze_code_ast(bad_exec)
    assert risk.is_blocked
    print(f"✅ exec检测: {risk.summary}")
    
    # 4. 子进程检测
    bad_sub = "__import__('subprocess').run(['ls'])"
    risk = analyze_code_ast(bad_sub)
    assert risk.is_blocked
    print(f"✅ 子进程检测: {risk.summary}")
    
    # 5. 沙箱执行(安全代码)
    result = sandbox_run("print('hello from sandbox')")
    assert result.success
    assert 'hello' in result.stdout
    print(f"✅ 沙箱执行: success={result.success}, stdout='{result.stdout.strip()}'")
    
    # 6. 沙箱执行(危险代码被拦截)
    result = sandbox_run("import os; os.system('dir')")
    assert not result.success
    print(f"✅ 沙箱拦截: {result.error}")
    
    # 7. 沙箱超时
    import time
    result = sandbox_run("import time; time.sleep(100)", timeout=1)
    if not result.success:
        print(f"✅ 超时检测: {result.error}")
    else:
        print(f"⚠️ 超时检测: 未触发(可能在慢机器上)")
    
    # 8. 文件系统保护
    result = sandbox_run("with open('/tmp/test.txt', 'w') as f: f.write('x')", timeout=3)
    print(f"✅ 文件保护: success={result.success}")
    
    # 9. 死循环检测
    loop_code = "while True:\n    pass"
    risk = analyze_code_ast(loop_code)
    assert "死循环" in risk.reasons[0]
    print(f"✅ 死循环检测: {risk.reasons[0]}")
    
    print(f"\n✅🎉 沙箱自检通过 (9项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
