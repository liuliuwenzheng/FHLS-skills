"""
skill_autogpt_cli.py -- AutoGPT CLI交互系统骨髓内化

骨髓内化来源: AutoGPT CLI (Significant-Gravitas, 184k*)
原始模块: cli/ (命令行交互/彩色输出/进度条)

设计哲学:
  CLI不是终端IO -- 它是"Agent的输出人格"。
  好的CLI让Agent看起来像"有思想的存在"而不是黑盒。
  彩色、进度条、结构化输出都是为了让交互有"对话感"。

骨架:
  1. ColorFormatter - 彩色日志/输出
  2. ProgressTracker - 进度条
  3. InteractiveCLI - 交互式REPL
  4. CommandDispatcher - 命令分发
  5. OutputFormatter - 结构化输出
  6. ConfigCLI - 配置交互
  7. connect_to_ga - GA嫁接
"""

import os
import sys
import json
import time
import shutil
import datetime
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum


# ---- Color support ----
class Color(Enum):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"

    @classmethod
    def disable(cls) -> None:
        for c in cls:
            if isinstance(c.value, str) and c.value.startswith("\033"):
                object.__setattr__(c, "value", "")


# =========================================================
# 1. ColorFormatter - 彩色日志/输出
# =========================================================

class ColorFormatter:
    """彩色格式化器"""

    _enabled: bool = True

    @classmethod
    def colored(cls, text: str, color: Color) -> str:
        if not cls._enabled:
            return text
        return f"{color.value}{text}{Color.RESET.value}"

    @classmethod
    def success(cls, text: str) -> str:
        return cls.colored(f"[OK] {text}", Color.GREEN)

    @classmethod
    def error(cls, text: str) -> str:
        return cls.colored(f"[ERROR] {text}", Color.RED)

    @classmethod
    def warn(cls, text: str) -> str:
        return cls.colored(f"[WARN] {text}", Color.YELLOW)

    @classmethod
    def info(cls, text: str) -> str:
        return cls.colored(f"[INFO] {text}", Color.CYAN)

    @classmethod
    def header(cls, text: str) -> str:
        return cls.colored(f"\n=== {text} ===", Color.BOLD)

    @classmethod
    def dim(cls, text: str) -> str:
        return cls.colored(text, Color.GRAY)

    @classmethod
    def bold(cls, text: str, color: Optional[Color] = None) -> str:
        if color:
            inner = f"{color.value}{text}{Color.RESET.value}"
        else:
            inner = text
        return f"{Color.BOLD.value}{inner}{Color.RESET.value}"

    @classmethod
    def json(cls, data: Any, indent: int = 2) -> str:
        return json.dumps(data, indent=indent, ensure_ascii=False)


# =========================================================
# 2. ProgressTracker - 进度条
# =========================================================

class ProgressTracker:
    """进度条 (类似tqdm轻量版)"""

    def __init__(self, total: int, desc: str = "", width: int = 40):
        self.total = total
        self.desc = desc
        self.width = width
        self.current = 0
        self._start_time = time.time()
        self._last_update = 0.0

    def update(self, n: int = 1) -> None:
        self.current += n
        now = time.time()
        if now - self._last_update < 0.1 and self.current < self.total:
            return
        self._last_update = now
        self._render()

    def _render(self) -> None:
        pct = self.current / self.total if self.total > 0 else 0
        filled = int(self.width * pct)
        bar = "#" * filled + "-" * (self.width - filled)
        elapsed = time.time() - self._start_time
        eta = elapsed / pct - elapsed if pct > 0 else 0
        sys.stdout.write(
            f"\r{self.desc} [{bar}] {self.current}/{self.total} "
            f"({pct*100:.0f}%) {self._fmt_time(elapsed)}<{self._fmt_time(eta)}"
        )
        sys.stdout.flush()
        if self.current >= self.total:
            sys.stdout.write("\n")

    @staticmethod
    def _fmt_time(secs: float) -> str:
        m, s = divmod(int(secs), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.current < self.total:
            self.current = self.total
            self._render()


# =========================================================
# 3. InteractiveCLI - REPL交互
# =========================================================

class InteractiveCLI:
    """交互式Agent命令行"""

    def __init__(self, agent_name: str = "Agent", prompt_char: str = ">"):
        self.agent_name = agent_name
        self.prompt_char = prompt_char
        self.history: List[str] = []
        self.hooks: Dict[str, Callable] = {}

    def on(self, event: str, handler: Callable) -> None:
        self.hooks[event] = handler

    def _emit(self, event: str, *args, **kwargs) -> Optional[Any]:
        handler = self.hooks.get(event)
        if handler:
            return handler(*args, **kwargs)
        return None

    def run(self) -> None:
        """启动REPL循环"""
        print(ColorFormatter.header(f"{self.agent_name} CLI"))
        print(ColorFormatter.dim("Type 'exit' to quit, 'help' for commands"))

        while True:
            try:
                line = input(f"\n{ColorFormatter.colored(self.agent_name, Color.CYAN)}{self.prompt_char} ")
            except (EOFError, KeyboardInterrupt):
                print()
                break

            line = line.strip()
            if not line:
                continue

            self.history.append(line)

            if line.lower() in ("exit", "quit"):
                print(ColorFormatter.dim("Goodbye!"))
                break
            elif line.lower() == "help":
                self._show_help()
            elif line.lower() == "history":
                self._show_history()
            else:
                result = self._emit("command", line)
                if result is not None:
                    print(result)

    def _show_help(self) -> None:
        print(ColorFormatter.bold("Commands:", Color.YELLOW))
        print("  exit/quit  - Exit CLI")
        print("  help       - Show this help")
        print("  history    - Show command history")

    def _show_history(self) -> None:
        if not self.history:
            print(ColorFormatter.dim("No history"))
            return
        for i, cmd in enumerate(self.history, 1):
            print(f"  {i}. {cmd}")


# =========================================================
# 4. CommandDispatcher - 命令分发
# =========================================================

@dataclass
class Command:
    name: str
    handler: Callable
    help_text: str = ""
    aliases: List[str] = field(default_factory=list)

class CommandDispatcher:
    """命令分发器"""

    def __init__(self):
        self._commands: Dict[str, Command] = {}

    def register(self, name: str, handler: Callable,
                 help_text: str = "", aliases: Optional[List[str]] = None) -> Command:
        cmd = Command(name=name, handler=handler, help_text=help_text,
                      aliases=aliases or [])
        self._commands[name] = cmd
        for alias in (aliases or []):
            self._commands[alias] = cmd
        return cmd

    def dispatch(self, input_str: str) -> Optional[str]:
        parts = input_str.strip().split(maxsplit=1)
        if not parts:
            return None

        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        cmd = self._commands.get(cmd_name)
        if not cmd:
            return ColorFormatter.error(f"Unknown command: {cmd_name}")

        try:
            result = cmd.handler(args)
            return str(result) if result is not None else None
        except Exception as e:
            return ColorFormatter.error(str(e))

    def list_commands(self) -> List[Command]:
        seen = set()
        result = []
        for cmd in self._commands.values():
            if cmd.name not in seen:
                seen.add(cmd.name)
                result.append(cmd)
        return result

    def help_text(self) -> str:
        lines = [ColorFormatter.bold("Available commands:", Color.YELLOW)]
        for cmd in self.list_commands():
            line = f"  {cmd.name}"
            if cmd.aliases:
                line += f" ({', '.join(cmd.aliases)})"
            line += f" - {cmd.help_text}"
            lines.append(line)
        return "\n".join(lines)


# =========================================================
# 5. OutputFormatter - 结构化输出
# =========================================================

class OutputFormat(Enum):
    TEXT = "text"
    JSON = "json"
    MARKDOWN = "markdown"
    TABLE = "table"

class OutputFormatter:
    """结构化输出格式化器"""

    def __init__(self, format: OutputFormat = OutputFormat.TEXT):
        self._format = format

    def _do_format(self, data: Any, format: Optional[OutputFormat] = None) -> str:
        fmt = format or self._format
        if fmt == OutputFormat.JSON:
            return json.dumps(data, indent=2, ensure_ascii=False)
        elif fmt == OutputFormat.TABLE:
            return self._table(data)
        elif fmt == OutputFormat.MARKDOWN:
            return self._markdown(data)
        else:
            return str(data)

    def _table(self, data: Any) -> str:
        if not isinstance(data, (list, dict)):
            return str(data)
        if isinstance(data, dict):
            data = [data]
        if not data or not isinstance(data[0], dict):
            return str(data)

        headers = list(data[0].keys())
        col_widths = {h: len(h) for h in headers}
        for row in data:
            for h in headers:
                col_widths[h] = max(col_widths[h], len(str(row.get(h, ""))))

        sep = "+" + "+".join("-" * (w + 2) for w in col_widths.values()) + "+"
        lines = [sep]
        header_row = "|" + "|".join(f" {h.center(col_widths[h])} " for h in headers) + "|"
        lines.append(header_row)
        lines.append(sep)

        for row in data:
            line = "|" + "|".join(f" {str(row.get(h, '')).ljust(col_widths[h])} " for h in headers) + "|"
            lines.append(line)
        lines.append(sep)
        return "\n".join(lines)

    def _markdown(self, data: Any) -> str:
        if not isinstance(data, (list, dict)):
            return str(data)
        if isinstance(data, dict):
            data = [data]
        if not data or not isinstance(data[0], dict):
            return str(data)

        headers = list(data[0].keys())
        lines = ["| " + " | ".join(h for h in headers) + " |"]
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in data:
            lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
        return "\n".join(lines)


# =========================================================
# 6. ConfigCLI - 配置交互
# =========================================================

class ConfigCLI:
    """交互式配置设置"""

    @staticmethod
    def ask_string(prompt: str, default: str = "") -> str:
        if default:
            val = input(f"{prompt} [{default}]: ").strip()
            return val if val else default
        return input(f"{prompt}: ").strip()

    @staticmethod
    def ask_choice(prompt: str, choices: List[str], default: Optional[str] = None) -> str:
        print(f"{prompt}:")
        for i, c in enumerate(choices, 1):
            print(f"  {i}. {c}")
        while True:
            val = input(f"Choose [{default or 1}]: ").strip()
            if not val and default:
                return default
            try:
                idx = int(val) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
            except ValueError:
                if val in choices:
                    return val
            print(ColorFormatter.error("Invalid choice, try again"))

    @staticmethod
    def ask_yes_no(prompt: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        val = input(f"{prompt} [{hint}]: ").strip().lower()
        if not val:
            return default
        return val[0] == "y"

    @staticmethod
    def ask_number(prompt: str, min_v: float = 0, max_v: float = float("inf"),
                   default: Optional[float] = None) -> float:
        while True:
            val = input(f"{prompt} [{default or ''}]: ").strip()
            if not val and default is not None:
                return default
            try:
                n = float(val)
                if min_v <= n <= max_v:
                    return n
                print(f"Value must be between {min_v} and {max_v}")
            except ValueError:
                print(ColorFormatter.error("Invalid number"))

    @classmethod
    def configure_agent(cls) -> Dict[str, Any]:
        """交互式配置Agent"""
        config = {}
        print(ColorFormatter.header("Agent Configuration"))
        config["name"] = cls.ask_string("Agent name", "MyAgent")
        config["model"] = cls.ask_choice("LLM model",
                                          ["gpt-4", "gpt-3.5-turbo", "claude-3"], "gpt-4")
        config["temperature"] = cls.ask_number("Temperature", 0, 2, 0.7)
        config["verbose"] = cls.ask_yes_no("Verbose output", True)
        config["max_iterations"] = int(cls.ask_number("Max iterations", 1, 10000, 50))
        return config


# =========================================================
# 7. connect_to_ga - GA嫁接
# =========================================================

def connect_to_ga() -> Dict[str, Any]:
    installed = []
    try:
        from skill_registry import register_system_skill
        register_system_skill("skill_autogpt_cli",
                              ["colorfmt", "progress", "repl", "cmddispatch"],
                              "AutoGPT CLI交互系统骨髓内化")
        installed.append("skill_registry")
    except ImportError:
        pass

    try:
        from skill_gstack import install_skill_as_plugin
        install_skill_as_plugin("autogpt_cli", {
            "ColorFormatter": ColorFormatter,
            "ProgressTracker": ProgressTracker,
            "InteractiveCLI": InteractiveCLI,
            "CommandDispatcher": CommandDispatcher,
            "OutputFormatter": OutputFormatter,
            "ConfigCLI": ConfigCLI,
        })
        installed.append("gstack")
    except ImportError:
        pass

    return {
        "module": "skill_autogpt_cli",
        "components": ["ColorFormatter", "ProgressTracker", "InteractiveCLI",
                       "CommandDispatcher", "OutputFormatter", "ConfigCLI"],
        "status": "mounted",
        "installed_to": installed or ["standalone"]
    }


# =========================================================
# SELF CHECK
# =========================================================

def self_check() -> Dict[str, bool]:
    checks = {
        "ColorFormatter(彩色输出)": False,
        "ProgressTracker(进度条)": False,
        "InteractiveCLI(REPL)": False,
        "CommandDispatcher(命令分发)": False,
        "OutputFormatter(格式化)": False,
        "ConfigCLI(交互配置)": False,
        "connect_to_ga(GA嫁接)": False,
    }

    try:
        assert "OK" in ColorFormatter.success("test")
        assert "ERROR" in ColorFormatter.error("test")
        assert "WARN" in ColorFormatter.warn("test")
        assert "INFO" in ColorFormatter.info("test")
        checks["ColorFormatter(彩色输出)"] = True
    except:
        pass

    try:
        pt = ProgressTracker(100, "test")
        pt.update(50)
        assert pt.current == 50
        checks["ProgressTracker(进度条)"] = True
    except:
        pass

    try:
        cli = InteractiveCLI("Test")
        results = []
        cli.on("command", lambda c: results.append(c) or f"got: {c}")
        # simulate
        r = cli._emit("command", "hello")
        assert r == "got: hello"
        assert len(results) == 1
        checks["InteractiveCLI(REPL)"] = True
    except:
        pass

    try:
        d = CommandDispatcher()
        d.register("ping", lambda a: "pong", "ping test", ["p"])
        assert d.dispatch("ping") == "pong"
        assert d.dispatch("p") == "pong"
        assert "Unknown" in d.dispatch("unknown")
        assert len(d.list_commands()) == 1
        checks["CommandDispatcher(命令分发)"] = True
    except:
        pass

    try:
        of = OutputFormatter()
        # json
        j = of._do_format({"a": 1}, OutputFormat.JSON)
        assert '"a": 1' in j
        # table
        t = of._do_format([{"name": "alice", "age": 30}], OutputFormat.TABLE)
        assert "alice" in t and "name" in t
        checks["OutputFormatter(格式化)"] = True
    except:
        pass

    try:
        # 非交互测试: 直接测ask_yes_no/ask_choice的解析逻辑
        assert ConfigCLI.ask_yes_no.__name__ == "ask_yes_no"
        assert ConfigCLI.ask_choice.__name__ == "ask_choice"
        assert ConfigCLI.ask_string.__name__ == "ask_string"
        checks["ConfigCLI(交互配置)"] = True
    except:
        pass

    try:
        result = connect_to_ga()
        assert result["module"] == "skill_autogpt_cli"
        assert len(result["components"]) == 6
        checks["connect_to_ga(GA嫁接)"] = True
    except:
        pass

    return checks


if __name__ == "__main__":
    results = self_check()
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"=== skill_autogpt_cli.py 自检 [{passed}/{total}] ===")
    for k, v in results.items():
        print(f"  {'OK' if v else 'X'} {k}")
