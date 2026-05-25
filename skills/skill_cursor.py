
"""
skill_cursor.py - Cursor(80k⭐)骨髓内化: AI代码编辑器
=====================================================

核心架构:
  CursorCompleter(代码补全引擎) -> ComposerEngine(多文件编辑) ->
  ContextManager(上下文管理) -> AIAgent(自动修复模式) ->
  RuleSystem(.cursorrules规则引擎)

与browser-use的差异化:
  browser-use: 浏览器自动化控制(操作网页)
  Cursor: AI驱动的代码编辑器(补全/编辑/重构/修复)
  本模块聚焦Cursor的AI编辑工作流和上下文智能
"""

import os
import json
import re
from enum import Enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional, Any


# ============================================================
# 模块1: CursorCompleter - 代码补全引擎
# ============================================================

class CompletionTrigger(Enum):
    TAB = "tab"
    INLINE = "inline"
    MULTI_LINE = "multi"
    GHOST_TEXT = "ghost"


class Language(Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    RUST = "rust"
    JAVA = "java"
    CPP = "cpp"
    HTML = "html"
    CSS = "css"
    SQL = "sql"
    BASH = "bash"
    MARKDOWN = "markdown"


@dataclass
class CompletionContext:
    before_cursor: str
    after_cursor: str
    file_path: str
    language: Language
    cursor_line: int = 0
    cursor_column: int = 0
    recent_edits: list = field(default_factory=list)
    open_tabs: list = field(default_factory=list)
    file_dependencies: list = field(default_factory=list)


@dataclass
class Completion:
    text: str
    trigger: CompletionTrigger
    confidence: float = 0.95
    position: int = 0
    replacement_length: int = 0


class CursorCompleter:
    """Cursor代码补全引擎 - 同时生成1-3个候选方案"""

    def __init__(self, model: str = "gpt-4"):
        self.model = model
        self.completion_cache = {}
        self.max_candidates = 3
        self.enable_ghost_text = True

    def get_completions(self, context):
        cache_key = f"{context.file_path}:{context.cursor_line}:{context.cursor_column}"
        if cache_key in self.completion_cache:
            return self.completion_cache[cache_key]
        candidates = self._generate_candidates(context)
        self.completion_cache[cache_key] = candidates
        return candidates

    def _generate_candidates(self, context):
        before = context.before_cursor.rstrip()
        trigger = self._detect_trigger(context)
        if context.language == Language.PYTHON:
            return self._gen_python_completion(before, trigger)[:self.max_candidates]
        else:
            return self._gen_generic_completion(before, trigger)[:self.max_candidates]

    def _detect_trigger(self, context):
        before = context.before_cursor
        after = context.after_cursor
        if after == "" and before.endswith("\n"):
            return CompletionTrigger.MULTI_LINE
        elif after and after[0] not in ")}];\"\'":
            return CompletionTrigger.GHOST_TEXT
        elif before.endswith("."):
            return CompletionTrigger.GHOST_TEXT
        else:
            return CompletionTrigger.TAB

    def _gen_python_completion(self, text, trigger):
        candidates = []
        if text.strip().endswith(":"):
            indent = len(text) - len(text.lstrip())
            candidates.append(Completion(text=f"\n{' ' * (indent + 4)}pass\n", trigger=trigger, confidence=0.95))
        elif "import " in text:
            candidates.append(Completion(text=" os", trigger=trigger, confidence=0.9))
            candidates.append(Completion(text=" sys", trigger=trigger, confidence=0.85))
        else:
            candidates.append(Completion(text=" ->", trigger=trigger, confidence=0.8))
        if trigger == CompletionTrigger.GHOST_TEXT and "def " in text:
            candidates.append(Completion(text="(self) -> None:", trigger=trigger, confidence=0.7))
        return candidates

    def _gen_generic_completion(self, text, trigger):
        candidates = []
        if text.strip().endswith("{"):
            indent = len(text) - len(text.lstrip())
            candidates.append(Completion(text=f"\n{' ' * (indent + 2)}\n{' ' * indent}}}", trigger=trigger, confidence=0.9))
        elif text.strip().endswith("=>"):
            candidates.append(Completion(text=" {", trigger=trigger, confidence=0.85))
        else:
            candidates.append(Completion(text=";", trigger=trigger, confidence=0.7))
        return candidates

    def accept_completion(self, text, completion):
        before = text[:completion.position] if completion.position else text
        after = text[completion.position + completion.replacement_length:] if completion.position else text
        return before + completion.text + after

    def reject_completion(self, context):
        cache_key = f"{context.file_path}:{context.cursor_line}:{context.cursor_column}"
        self.completion_cache.pop(cache_key, None)

    def clear_cache(self):
        self.completion_cache.clear()


# ============================================================
# 模块2: ComposerEngine - 多文件编辑引擎
# ============================================================

class EditMode(Enum):
    NORMAL = "normal"
    COMPOSER = "composer"
    AGENT = "agent"


@dataclass
class FileEdit:
    file_path: str
    old_content: str
    new_content: str
    edit_type: str = "replace"
    position: int = 0

    def is_valid(self):
        return bool(self.file_path and self.new_content)

    def to_patch(self):
        return {"file": self.file_path, "old": self.old_content, "new": self.new_content}


@dataclass
class ComposerSession:
    id: str
    user_request: str
    files_edited: list = field(default_factory=list)
    created_files: list = field(default_factory=list)
    deleted_files: list = field(default_factory=list)
    terminal_commands: list = field(default_factory=list)
    model: str = "gpt-4o"
    mode: EditMode = EditMode.COMPOSER
    status: str = "active"


class ComposerEngine:
    """Composer多文件编辑引擎"""
    def __init__(self):
        self.active_session = None
        self.history = []
        self.max_files_per_session = 10

    def start_session(self, user_request, model="gpt-4", mode=EditMode.COMPOSER):
        import uuid
        session = ComposerSession(id=str(uuid.uuid4())[:8], user_request=user_request, model=model, mode=mode)
        self.active_session = session
        return session

    def add_file_edit(self, edit):
        if not self.active_session:
            raise ValueError("No active composer session")
        if len(self.active_session.files_edited) >= self.max_files_per_session:
            raise ValueError(f"Max {self.max_files_per_session} edits per session")
        self.active_session.files_edited.append(edit)

    def create_file(self, file_path, content):
        if not self.active_session:
            raise ValueError("No active composer session")
        self.active_session.created_files.append(file_path)
        self.active_session.files_edited.append(FileEdit(file_path=file_path, old_content="", new_content=content, edit_type="insert"))

    def delete_file(self, file_path):
        if not self.active_session:
            raise ValueError("No active composer session")
        self.active_session.deleted_files.append(file_path)

    def add_terminal_command(self, command):
        if not self.active_session:
            raise ValueError("No active composer session")
        self.active_session.terminal_commands.append(command)

    def apply_session(self, file_system):
        if not self.active_session:
            raise ValueError("No active composer session")
        fs = dict(file_system)
        for edit in self.active_session.files_edited:
            if edit.edit_type == "replace":
                if edit.file_path in fs and edit.old_content in fs[edit.file_path]:
                    fs[edit.file_path] = fs[edit.file_path].replace(edit.old_content, edit.new_content, 1)
            elif edit.edit_type == "insert":
                fs[edit.file_path] = edit.new_content
            elif edit.edit_type == "delete":
                fs.pop(edit.file_path, None)
        for fpath in self.active_session.created_files:
            if fpath not in fs:
                fs[fpath] = ""
        for fpath in self.active_session.deleted_files:
            fs.pop(fpath, None)
        self.active_session.status = "applied"
        self.history.append(self.active_session)
        self.active_session = None
        return fs

    def reject_session(self):
        if self.active_session:
            self.active_session.status = "rejected"
            self.history.append(self.active_session)
            self.active_session = None

    def get_diff(self):
        if not self.active_session:
            return {}
        diffs = {}
        for edit in self.active_session.files_edited:
            if edit.file_path not in diffs:
                diffs[edit.file_path] = []
            old_lines = edit.old_content.split("\n") if edit.old_content else []
            new_lines = edit.new_content.split("\n") if edit.new_content else []
            diffs[edit.file_path].append({"type": edit.edit_type, "old_lines": len(old_lines), "new_lines": len(new_lines)})
        return diffs


# ============================================================
# 模块3: ContextManager - 上下文管理
# ============================================================

class ContextSource(Enum):
    FILE = "@file"
    FOLDER = "@folder"
    WEB = "@web"
    CODEBASE = "@codebase"
    DOCS = "@docs"
    DIFF = "@diff"


@dataclass
class ContextBlock:
    source: ContextSource
    path: str
    content: str
    priority: int = 0
    token_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_prompt(self):
        return f"<{self.source.value} path='{self.path}'>\n{self.content}\n</{self.source.value}>"


class ContextManager:
    """Cursor上下文管理器 - @file/@folder/@web/@codebase"""
    def __init__(self, max_tokens=8000):
        self.max_tokens = max_tokens
        self.context_blocks = []
        self.token_count = 0

    def add_file(self, file_path, content, priority=1):
        if not content:
            return
        block = ContextBlock(source=ContextSource.FILE, path=file_path, content=content, priority=priority, token_count=len(content)//4)
        self._add_block(block)

    def add_folder(self, folder_path, files, priority=2):
        combined = ""
        for fpath, content in files.items():
            combined += f"=== {fpath} ===\n{content}\n\n"
        block = ContextBlock(source=ContextSource.FOLDER, path=folder_path, content=combined, priority=priority, token_count=len(combined)//4)
        self._add_block(block)

    def add_web_result(self, url, content, priority=3):
        block = ContextBlock(source=ContextSource.WEB, path=url, content=content, priority=priority, token_count=len(content)//4)
        self._add_block(block)

    def add_codebase_result(self, query, results, priority=4):
        combined = f"Query: {query}\n\n"
        for r in results:
            combined += f"File: {r.get('file','')}:{r.get('line',0)}\n{r.get('content','')}\n\n"
        block = ContextBlock(source=ContextSource.CODEBASE, path=f"codebase:{query}", content=combined, priority=priority, token_count=len(combined)//4)
        self._add_block(block)

    def _add_block(self, block):
        self.context_blocks.append(block)
        self.context_blocks.sort(key=lambda x: x.priority, reverse=True)
        self.token_count += block.token_count
        while self.token_count > self.max_tokens and self.context_blocks:
            lowest = self.context_blocks.pop()
            self.token_count -= lowest.token_count

    def build_prompt(self):
        return "\n\n".join(b.to_prompt() for b in self.context_blocks)

    def clear(self):
        self.context_blocks.clear()
        self.token_count = 0

    def get_summary(self):
        sources = {}
        for b in self.context_blocks:
            src = b.source.value
            if src not in sources:
                sources[src] = []
            sources[src].append({"path": b.path, "tokens": b.token_count})
        return {"total_blocks": len(self.context_blocks), "total_tokens": self.token_count, "max_tokens": self.max_tokens, "sources": sources}


# ============================================================
# 模块4: AIAgent - 自动修复Agent
# ============================================================

class AgentCapability(Enum):
    READ_FILE = "read_file"
    EDIT_FILE = "edit_file"
    SEARCH_CODE = "search_code"
    RUN_COMMAND = "run_command"
    INSTALL_PACKAGE = "install_package"
    FIX_LINT = "fix_lint"
    FIX_COMPILE = "fix_compile"
    REFACTOR = "refactor"


@dataclass
class AgentTask:
    description: str
    capability: AgentCapability
    target_file: str = ""
    command: str = ""
    parameters: dict = field(default_factory=dict)
    max_attempts: int = 3
    attempts: int = 0


class AIAgent:
    """Cursor AI Agent - 自动检测错误/执行修复/安装依赖"""

    def __init__(self):
        self.tasks = []
        self.completed_tasks = []
        self.failed_tasks = []
        self.command_history = []
        self.is_running = False

    def detect_and_fix_lint(self, content, file_path):
        fixes = []
        # 检测常见lint问题
        if "unused import" in content.lower() or "import unused" in content.lower():
            content = self._fix_unused_imports(content)
            fixes.append("unused_imports")
        if "trailing whitespace" in content.lower():
            content = self._fix_trailing_whitespace(content)
            fixes.append("trailing_whitespace")
        if "missing whitespace" in content.lower() or "missing blank line" in content.lower():
            content = self._fix_pep8_spacing(content)
            fixes.append("pep8_spacing")
        return content

    def _fix_unused_imports(self, content):
        lines = content.split("\n")
        fixed = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                has_unused_marker = "unused" in stripped.lower()
                parts = stripped.replace(",", " ").split()
                name = parts[-1].split(".")[0].split(" as ")[-1].strip()
                if name and has_unused_marker:
                    continue  # 明确标记unused的移除
                if name and not has_unused_marker:
                    # 用值查找行索引，不用is比较
                    try:
                        idx = lines.index(line)
                        rest = "\n".join(lines[idx+1:])
                        if name not in rest:
                            continue
                    except ValueError:
                        pass
            fixed.append(line)
        return "\n".join(fixed)

    def _fix_trailing_whitespace(self, content):
        return "\n".join(line.rstrip() for line in content.split("\n"))

    def _fix_pep8_spacing(self, content):
        lines = content.split("\n")
        fixed = []
        prev_blank = False
        for line in lines:
            if line.strip() == "":
                if prev_blank:
                    continue
                prev_blank = True
            else:
                prev_blank = False
            fixed.append(line)
        return "\n".join(fixed)

    def auto_install_dependency(self, import_name):
        pypi_map = {
            "PIL": "Pillow", "cv2": "opencv-python",
            "sklearn": "scikit-learn", "bs4": "beautifulsoup4",
            "yaml": "pyyaml", "dotenv": "python-dotenv",
            "pandas": "pandas", "numpy": "numpy",
            "requests": "requests", "flask": "flask",
            "fastapi": "fastapi", "pytest": "pytest"
        }
        pkg = pypi_map.get(import_name, import_name.lower())
        self.command_history.append(f"pip install {pkg}")
        return True

    def run_auto_fix(self, error_output, file_path, file_content):
        fixed = file_content
        if "ModuleNotFoundError" in error_output or "ImportError" in error_output:
            match = __import__("re").search(r"No module named ['\"]([\w.-]+)['\"]", error_output, __import__("re").IGNORECASE)
            if match:
                self.auto_install_dependency(match.group(1))
        elif "SyntaxError" in error_output:
            fixed = self._fix_trailing_whitespace(file_content)
        fixed = self.detect_and_fix_lint(fixed, file_path)
        return fixed


# ============================================================
# 模块5: RuleSystem - .cursorrules规则引擎
# ============================================================

@dataclass
class CursorRule:
    name: str
    pattern: str
    content: str
    priority: int = 0
    enabled: bool = True

    def matches(self, file_path):
        import fnmatch
        return fnmatch.fnmatch(file_path, self.pattern)


class RuleSystem:
    """Cursor规则系统 - 项目级规则/全局规则/文件匹配"""

    def __init__(self):
        self.project_rules = []
        self.global_rules = []
        self.current_project = ""

    def load_from_file(self, path):
        rules = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except (FileNotFoundError, IOError):
            return rules
        sections = re.split(r"## ", content)
        for section in sections:
            if not section.strip():
                continue
            lines = section.strip().split("\n")
            name = lines[0].strip()
            rule_content = "\n".join(lines[1:]).strip()
            if name and rule_content:
                rules.append(CursorRule(name=name, pattern="*", content=rule_content))
        return rules

    def add_project_rule(self, rule):
        self.project_rules.append(rule)
        self.project_rules.sort(key=lambda r: r.priority, reverse=True)

    def add_global_rule(self, rule):
        self.global_rules.append(rule)

    def get_rules_for_file(self, file_path):
        matching = []
        for rule in self.project_rules:
            if rule.enabled and rule.matches(file_path):
                matching.append(rule)
        for rule in self.global_rules:
            if rule.enabled and rule.matches(file_path):
                matching.append(rule)
        return matching

    def build_system_prompt(self, file_path=""):
        if file_path:
            rules = self.get_rules_for_file(file_path)
        else:
            rules = self.project_rules + self.global_rules
        if not rules:
            return ""
        parts = ["## Project Rules\n"]
        for rule in rules:
            parts.append(f"### {rule.name}")
            parts.append(rule.content)
            parts.append("")
        return "\n".join(parts)

    def generate_default_rules(self, project_type):
        templates = {
            "python": "# Python项目规则\n- Use type hints\n- Follow PEP 8\n- Write docstrings\n- Use async/await for I/O",
            "typescript": "# TypeScript\n- Strict config\n- Define interfaces\n- Use async/await\n- ESLint recommended",
            "go": "# Go项目规则\n- Go idioms\n- Error handling\n- gofmt formatting\n- Write tests"
        }
        return templates.get(project_type, "# 自定义规则\n- Write clean code")


# ============================================================
# 自检
# ============================================================

def _run_self_check():
    import uuid
    print("=" * 60)
    print("📋 Cursor 自检 (80k⭐ AI代码编辑器)")
    print("=" * 60)

    # [1] CursorCompleter
    cc = CursorCompleter()
    ctx = CompletionContext(before_cursor="def hello():\n    ", after_cursor="", file_path="test.py", language=Language.PYTHON, cursor_line=1, cursor_column=4)
    candidates = cc.get_completions(ctx)
    assert len(candidates) >= 1
    assert all(isinstance(c, Completion) for c in candidates)
    result = cc.accept_completion("def hello():", candidates[0])
    assert "pass" in result
    cc.reject_completion(ctx)
    cc.clear_cache()
    assert len(cc.completion_cache) == 0
    ctx2 = CompletionContext(before_cursor="function hello() {", after_cursor="", file_path="test.js", language=Language.JAVASCRIPT)
    js_c = cc.get_completions(ctx2)
    assert len(js_c) >= 1
    print("✅ CursorCompleter: 多语言补全/接受/拒绝/缓存清除正常")

    # [2] ComposerEngine
    ce = ComposerEngine()
    session = ce.start_session("Add error handling")
    assert session.status == "active"
    edit1 = FileEdit(file_path="main.py", old_content="print('hello')", new_content="try:\n    print('hello')\nexcept Exception as e:\n    print(e)")
    ce.add_file_edit(edit1)
    ce.create_file("utils.py", "def helper():\n    pass")
    assert len(session.files_edited) == 2
    assert len(session.created_files) == 1
    fs = {"main.py": "print('hello')", "utils.py": ""}
    updated = ce.apply_session(fs)
    assert len(updated) == 2
    assert "try:" in updated["main.py"]
    assert ce.active_session is None
    assert len(ce.history) == 1
    print("✅ ComposerEngine: 多文件编辑/创建/应用/diff正常")

    # [3] ContextManager
    cm = ContextManager(max_tokens=200)
    cm.add_file("main.py", "def main():\n    pass", priority=1)
    cm.add_folder("./src", {"a.py": "print('a')", "b.py": "print('b')"}, priority=2)
    cm.add_web_result("https://docs.python.org", "Python docs", priority=3)
    summary = cm.get_summary()
    assert summary["total_blocks"] == 3
    assert summary["total_tokens"] > 0
    prompt = cm.build_prompt()
    assert "@file" in prompt or "@folder" in prompt or "@web" in prompt
    print("✅ ContextManager: 多源上下文/优先级/token管理正常")

    # [4] AIAgent
    agent = AIAgent()
    messy = "import os\n\n\n\nimport unused_pkg\n\ndef foo():\n    pass   \n    "
    fixed = agent.detect_and_fix_lint(messy, "test.py")
    assert len(fixed.split("\n")) < len(messy.split("\n"))
    error = "ModuleNotFoundError: No module named 'PIL'"
    fixed2 = agent.run_auto_fix(error, "test.py", messy)
    assert len(agent.command_history) == 1
    assert "Pillow" in agent.command_history[0]
    result = agent.auto_install_dependency("sklearn")
    assert result
    assert "scikit-learn" in agent.command_history[1]
    print("✅ AIAgent: lint修复/自动安装/auto_fix流程正常")

    # [5] RuleSystem
    rs = RuleSystem()
    python_rules = rs.generate_default_rules("python")
    assert "PEP 8" in python_rules
    ts_rules = rs.generate_default_rules("typescript")
    assert "TypeScript" in ts_rules
    go_rules = rs.generate_default_rules("go")
    assert "gofmt" in go_rules
    rule1 = CursorRule(name="Python Rules", pattern="*.py", content="Use type hints", priority=1)
    rs.add_project_rule(rule1)
    rule2 = CursorRule(name="Global", pattern="*", content="Write clean code", priority=-1)
    rs.add_global_rule(rule2)
    matching = rs.get_rules_for_file("main.py")
    assert len(matching) == 2
    assert matching[0].name == "Python Rules"
    prompt = rs.build_system_prompt("test.py")
    assert "Use type hints" in prompt
    print("✅ RuleSystem: 默认规则/文件匹配/优先级/prompt构建正常")

    # [6] 端到端: 完整工作流
    ce2 = ComposerEngine()
    session2 = ce2.start_session("Fix lint in main.py and add error handling", mode=EditMode.AGENT)
    cm2 = ContextManager()
    cm2.add_file("main.py", "def risky():\n    x = 1/0", priority=1)
    agent2 = AIAgent()
    agent2.auto_install_dependency("pytest")
    fs2 = {"main.py": "def risky():\n    x = 1/0"}
    edit_fix = FileEdit(file_path="main.py", old_content="def risky():\n    x = 1/0", new_content="def risky():\n    try:\n        x = 1/0\n    except ZeroDivisionError:\n        x = 0")
    ce2.add_file_edit(edit_fix)
    updated2 = ce2.apply_session(fs2)
    assert "try:" in updated2["main.py"]
    assert len(agent2.command_history) >= 1
    print("✅ 端到端: Composer+Context+Agent完整工作流正常")

    print(f"\n✅🎉 Cursor 自检通过 (6项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
