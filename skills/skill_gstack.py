"""
skill_gstack.py — gstack 骨髓内化 (garrytan, 101k⭐)
Claude Code AI工程工作流配置管理器
核心哲学: 角色即技能(SKILL.md), 工作流即slash命令, 浏览器长驻

架构:
  StackConfig    → gstack配置解析 (CLAUDE.md/roles/skills)
  SkillRegistry  → 技能注册/查找/执行 (/slash命令)
  RoleManager    → 角色切换 (CEO/EM/Designer/QA/Security/Release等)
  PluginManager  → 插件扫描/依赖解析/安装
  HookSystem     → pre/post hook链
  GStackEngine   → 统一入口

参考: github.com/garrytan/gstack (101k⭐, YC CEO Garry Tan)
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


# ──────────────────────────────────────────────
# [1] StackConfig — gstack配置解析
# ──────────────────────────────────────────────

@dataclass
class StackConfig:
    """
    gstack配置根
    解析CLAUDE.md + 目录结构的配置聚合
    """
    root: Union[str, Path] = '.'
    roles: Dict[str, 'SkillDef'] = field(default_factory=dict)
    skills: Dict[str, 'SkillDef'] = field(default_factory=dict)
    hooks: Dict[str, list] = field(default_factory=dict)
    plugins: List[str] = field(default_factory=list)
    browser_port: int = 9222

    @classmethod
    def from_dir(cls, path: Union[str, Path] = '.') -> 'StackConfig':
        """扫描目录, 自动发现配置"""
        path = Path(path)
        cfg = cls(root=path)

        # 扫描skills/目录
        for sd in [path / '.agents' / 'skills', path / 'skills']:
            if sd.exists():
                for f in sd.glob('*.md'):
                    name = f.stem.lstrip('/')
                    cfg.skills[name] = SkillDef(name=name, path=str(f))

        # 扫描agents/
        agents_dir = path / 'agents'
        if agents_dir.exists():
            for f in agents_dir.glob('*.yaml') if agents_dir.exists() else []:
                pass
            for f in agents_dir.glob('*.json') if agents_dir.exists() else []:
                cfg._load_agent_config(f)

        # 读取CLAUDE.md
        claude_md = path / 'CLAUDE.md'
        if claude_md.exists():
            cfg._parse_claude_md(claude_md)

        return cfg

    def _load_agent_config(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            for k, v in data.items() if isinstance(data, dict) else []:
                if isinstance(v, dict):
                    self.roles[k] = SkillDef(
                        name=k, description=v.get('description', ''),
                        template=v.get('template', ''), source='agent')
        except Exception:
            pass

    def _parse_claude_md(self, path: Path) -> None:
        content = path.read_text(encoding='utf-8')
        for s in re.findall(r'`(/[\w-]+)`', content):
            name = s.lstrip('/')
            if name not in self.skills:
                self.skills[name] = SkillDef(
                    name=name, description='Referenced in CLAUDE.md',
                    source='claude_md')


@dataclass
class SkillDef:
    """技能定义, 对应一个SKILL.md文件"""
    name: str
    description: str = ''
    template: str = ''
    path: str = ''
    source: str = 'file'
    metadata: dict = field(default_factory=dict)


# ──────────────────────────────────────────────
# [2] SkillRegistry — 技能注册/查找/执行
# ──────────────────────────────────────────────

class SkillExecutionError(Exception):
    pass


@dataclass
class SkillContext:
    """技能执行上下文"""
    args: List[str] = field(default_factory=list)
    kwargs: Dict[str, str] = field(default_factory=dict)
    env: Dict[str, str] = field(default_factory=dict)
    working_dir: str = ''
    stdin: str = ''


@dataclass
class SkillResult:
    """技能执行结果"""
    success: bool
    output: str = ''
    error: str = ''
    duration_ms: float = 0.0


class Skill:
    """技能基类"""
    name: str = ''
    description: str = ''
    usage: str = ''

    def __init__(self, name: str = '', description: str = ''):
        if name:
            self.name = name
        if description:
            self.description = description

    def execute(self, context: SkillContext) -> SkillResult:
        raise NotImplementedError


class FileSkill(Skill):
    """基于文件的技能 (SKILL.md)"""

    def __init__(self, skill_def: SkillDef):
        super().__init__(skill_def.name, skill_def.description)
        self.skill_def = skill_def

    def execute(self, context: SkillContext) -> SkillResult:
        if self.skill_def.path and os.path.exists(self.skill_def.path):
            try:
                with open(self.skill_def.path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return SkillResult(success=True, output=content)
            except Exception as e:
                return SkillResult(success=False, error=str(e))
        return SkillResult(
            success=True,
            output=f"Skill '{self.name}': no file, using inline template")


class SkillRegistry:
    """
    技能注册表
    对应gstack中SKILL.md文件体系 + Claude Code /slash命令
    """

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._aliases: Dict[str, str] = {}

    def register(self, name: str, skill: Skill,
                 alias: Optional[str] = None) -> None:
        """注册技能"""
        name = name.lstrip('/')
        self._skills[name] = skill
        self._aliases[name] = name
        if alias:
            self._aliases[alias.lstrip('/')] = name

    def unregister(self, name: str) -> None:
        name = name.lstrip('/')
        self._skills.pop(name, None)
        self._aliases = {k: v for k, v in self._aliases.items() if v != name}

    def get(self, name: str) -> Optional[Skill]:
        key = name.lstrip('/')
        if key in self._skills:
            return self._skills[key]
        if key in self._aliases:
            return self._skills.get(self._aliases[key])
        return None

    def find(self, query: str) -> List[Tuple[str, Skill]]:
        q = query.lower()
        return [(n, s) for n, s in self._skills.items()
                if q in n.lower() or q in s.description.lower()]

    def list(self) -> List[str]:
        return sorted(self._skills.keys())

    def execute(self, name: str,
                context: Optional[SkillContext] = None) -> SkillResult:
        skill = self.get(name)
        if not skill:
            return SkillResult(
                success=False,
                error=f"Skill '{name}' not found. Available: {', '.join(self.list()[:10])}...")
        ctx = context or SkillContext()
        try:
            result = skill.execute(ctx)
            return result if isinstance(result, SkillResult) else SkillResult(success=True, output=str(result))
        except Exception as e:
            return SkillResult(success=False, error=f"Execution error: {e}")


# ──────────────────────────────────────────────
# [3] RoleManager — 角色切换
# ──────────────────────────────────────────────

class RoleType(Enum):
    """gstack核心角色类型 (23 specialists)"""
    CEO = 'ceo'
    ENG_MANAGER = 'eng-manager'
    DESIGNER = 'designer'
    DEVELOPER_EXPERIENCE = 'devex'
    REVIEWER = 'reviewer'
    CODE_AUDITOR = 'codex'
    DEBUGGER = 'investigate'
    DESIGN_REVIEWER = 'design-review'
    QA = 'qa'
    SECURITY = 'security'
    RELEASE = 'release'
    OFFICE_HOURS = 'office-hours'


@dataclass
class RoleConfig:
    """角色配置"""
    type: RoleType
    system_prompt: str = ''
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: List[str] = field(default_factory=list)
    context_files: List[str] = field(default_factory=list)


class RoleManager:
    """
    角色管理器
    对应gstack roles.json 23 specialists
    """

    _default_roles = {
        RoleType.CEO: {
            'prompt': (
                "You are a CEO-level reviewer. Find the 10-star product in the request.\n"
                "Rules: 1) Rethink product direction 2) Focus on user value 3) Challenge assumptions\n"
                "Output: Product improvement suggestions + priority"),
            'temperature': 0.8, 'tools': ['plan', 'review'],
        },
        RoleType.ENG_MANAGER: {
            'prompt': (
                "You are an eng manager. Lock architecture, data flow, edge cases.\n"
                "Rules: 1) Review design before code 2) Find data flow issues 3) Verify test coverage\n"
                "Output: Architecture review + specific changes"),
            'temperature': 0.3, 'tools': ['review', 'plan', 'analyze'],
        },
        RoleType.DESIGNER: {
            'prompt': (
                "You are a designer. Rate each design dimension 0-10.\n"
                "Dimensions: visual hierarchy, interaction, consistency, accessibility, responsive\n"
                "Output: Scores + what a 10 looks like"),
            'temperature': 0.6, 'tools': ['design-review'],
        },
        RoleType.REVIEWER: {
            'prompt': (
                "You are a strict code reviewer. Find bugs that pass CI but break in prod.\n"
                "Check: race conditions, error handling, edge cases, security, performance\n"
                "Output: Severity + fix suggestions"),
            'temperature': 0.2, 'tools': ['review'],
        },
        RoleType.QA: {
            'prompt': (
                "You are a QA engineer. End-to-end testing + edge case exploration.\n"
                "Method: normal flow, error flow, boundary values, concurrency\n"
                "Output: Test cases + bugs found"),
            'temperature': 0.5, 'tools': ['test', 'browser'],
        },
        RoleType.SECURITY: {
            'prompt': (
                "You are a security engineer. OWASP Top 10 + STRIDE audit.\n"
                "Check: XSS, CSRF, SQL injection, auth bypass, data exposure\n"
                "Output: Risk matrix + fix priority"),
            'temperature': 0.2, 'tools': ['security-scan'],
        },
        RoleType.RELEASE: {
            'prompt': (
                "You are a release engineer. Safe release process.\n"
                "Steps: version, changelog, tag, build, deploy, monitor\n"
                "Output: Release checklist + confirmation"),
            'temperature': 0.1, 'tools': ['git', 'deploy'],
        },
        RoleType.DEBUGGER: {
            'prompt': (
                "You are a root-cause debugger. Find bug cause systematically.\n"
                "Rules: 1) Investigate before fixing 2) Build hypothesis tree 3) Verify with minimal repro\n"
                "Output: Root cause analysis report"),
            'temperature': 0.3, 'tools': ['investigate', 'debug'],
        },
        RoleType.OFFICE_HOURS: {
            'prompt': (
                "You are a product mentor. Reframe the product idea before writing code.\n"
                "Framework: 1) Who's the user 2) What's the pain 3) Why now 4) Success criteria\n"
                "Output: One-pager + key assumptions"),
            'temperature': 0.9, 'tools': ['think', 'plan'],
        },
    }

    def __init__(self):
        self._roles: Dict[RoleType, RoleConfig] = {}
        self._active_role: Optional[RoleType] = None
        self._initialize_defaults()

    def _initialize_defaults(self) -> None:
        for rt, cfg in self._default_roles.items():
            self._roles[rt] = RoleConfig(
                type=rt, system_prompt=cfg['prompt'],
                temperature=cfg['temperature'], tools=cfg['tools'])

    def register_role(self, role: RoleConfig) -> None:
        self._roles[role.type] = role

    def get_role(self, role_type: Union[RoleType, str]) -> Optional[RoleConfig]:
        if isinstance(role_type, str):
            for rt in RoleType:
                if rt.value == role_type:
                    role_type = rt
                    break
            else:
                return None
        return self._roles.get(role_type)

    def list_roles(self) -> List[str]:
        return [rt.value for rt in self._roles.keys()]

    def switch_to(self, role_type: Union[RoleType, str]) -> RoleConfig:
        config = self.get_role(role_type)
        if not config:
            raise ValueError(f"Role '{role_type}' not found. Available: {', '.join(self.list_roles())}")
        self._active_role = config.type
        return config

    @property
    def active_role(self) -> Optional[RoleType]:
        return self._active_role

    def get_system_prompt(self) -> str:
        if not self._active_role:
            return ''
        config = self._roles.get(self._active_role)
        return config.system_prompt if config else ''

    def generate_role_instruction(self) -> str:
        if not self._active_role:
            return ''
        config = self._roles.get(self._active_role)
        if not config:
            return ''
        return (
            f"## Role: {config.type.value}\n\n"
            f"{config.system_prompt}\n\n"
            f"### Tools: {', '.join(config.tools)}\n")


# ──────────────────────────────────────────────
# [4] PluginManager — 插件扫描/依赖解析/安装
# ──────────────────────────────────────────────

@dataclass
class PluginInfo:
    name: str
    version: str = ''
    description: str = ''
    dependencies: List[str] = field(default_factory=list)
    entry_point: str = ''
    install_path: str = ''
    config: dict = field(default_factory=dict)
    requires: List[str] = field(default_factory=list)


class DependencyError(Exception):
    pass


class PluginManager:
    """
    插件管理器
    对应Claude Code /plugin install命令
    功能: 扫描 → 依赖解析 → 安装 → 注册
    """

    def __init__(self, plugins_dir: Optional[str] = None):
        self._plugins: Dict[str, PluginInfo] = {}
        self._installed: Set[str] = set()
        self._plugins_dir = plugins_dir or self._default_plugins_dir()

    @staticmethod
    def _default_plugins_dir() -> str:
        if sys.platform == 'win32':
            base = os.environ.get('APPDATA', os.path.expanduser('~'))
        else:
            base = os.path.expanduser('~')
        return os.path.join(base, '.claude', 'plugins')

    def discover(self, scan_path: Optional[str] = None) -> List[PluginInfo]:
        discovered = []
        paths = [scan_path] if scan_path else [os.getcwd(), self._plugins_dir]
        for base in paths:
            if not base or not os.path.isdir(base):
                continue
            for entry in os.listdir(base):
                full = os.path.join(base, entry)
                if os.path.isdir(full):
                    info = self._scan_plugin_dir(full)
                    if info:
                        discovered.append(info)
                        self._plugins[info.name] = info
        return discovered

    def _scan_plugin_dir(self, path: str) -> Optional[PluginInfo]:
        name = os.path.basename(path)
        for cfg_file in ['plugin.json', 'package.json', 'pyproject.toml']:
            cfg_path = os.path.join(path, cfg_file)
            if os.path.exists(cfg_path):
                try:
                    return self._parse_plugin_config(cfg_path, name)
                except Exception:
                    continue
        return PluginInfo(name=name, install_path=path)

    def _parse_plugin_config(self, path: str, default_name: str) -> PluginInfo:
        with open(path, 'r', encoding='utf-8') as f:
            if path.endswith('.json'):
                data = json.load(f)
            else:
                return PluginInfo(name=default_name)
        return PluginInfo(
            name=data.get('name', default_name),
            version=data.get('version', ''),
            description=data.get('description', ''),
            dependencies=data.get('dependencies', []),
            entry_point=data.get('main', data.get('entry_point', '')),
            install_path=os.path.dirname(path),
            config=data,
            requires=data.get('requires', []),
        )

    def resolve_dependencies(self, plugin_name: str) -> List[PluginInfo]:
        """拓扑排序依赖解析"""
        visited: Set[str] = set()
        resolved: List[PluginInfo] = []

        def _resolve(name: str, chain: List[str]) -> None:
            if name in visited:
                return
            if name in chain:
                raise DependencyError(f"Circular dependency: {' -> '.join(chain + [name])}")
            plugin = self._plugins.get(name)
            if not plugin:
                return
            chain.append(name)
            for dep in plugin.dependencies:
                _resolve(dep, chain)
            chain.pop()
            visited.add(name)
            resolved.append(plugin)

        _resolve(plugin_name, [])
        return resolved

    def install(self, plugin_name: str, source: Optional[str] = None) -> bool:
        if plugin_name in self._installed:
            return True
        deps = self.resolve_dependencies(plugin_name)
        for dep in deps:
            self._installed.add(dep.name)
        self._installed.add(plugin_name)
        return True

    def uninstall(self, plugin_name: str) -> bool:
        return bool(self._installed.discard(plugin_name))

    def is_installed(self, plugin_name: str) -> bool:
        return plugin_name in self._installed

    def list_installed(self) -> List[PluginInfo]:
        return [self._plugins[n] for n in self._installed if n in self._plugins]


# ──────────────────────────────────────────────
# [5] HookSystem — pre/post hook链
# ──────────────────────────────────────────────

class HookPoint(Enum):
    """hook触发点"""
    PRE_SKILL = 'pre-skill'
    POST_SKILL = 'post-skill'
    PRE_ROLE_SWITCH = 'pre-role-switch'
    POST_ROLE_SWITCH = 'post-role-switch'
    PRE_PLUGIN_INSTALL = 'pre-plugin-install'
    POST_PLUGIN_INSTALL = 'post-plugin-install'
    ON_ERROR = 'on-error'


@dataclass
class Hook:
    name: str
    hook_point: HookPoint
    handler: Callable
    priority: int = 0
    enabled: bool = True
    metadata: dict = field(default_factory=dict)


@dataclass
class HookContext:
    hook_point: HookPoint
    data: dict = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    abort: bool = False


class HookSystem:
    """pre/post hook链"""

    def __init__(self):
        self._hooks: Dict[HookPoint, List[Hook]] = {hp: [] for hp in HookPoint}

    def register(self, hook_point: HookPoint, handler: Callable,
                 name: str = '', priority: int = 0) -> Hook:
        hook = Hook(name=name or f"hook_{len(self._hooks[hook_point])}",
                    hook_point=hook_point, handler=handler, priority=priority)
        self._hooks[hook_point].append(hook)
        self._hooks[hook_point].sort(key=lambda h: h.priority)
        return hook

    def unregister(self, hook_point: HookPoint, name: str) -> bool:
        hooks = self._hooks[hook_point]
        for i, h in enumerate(hooks):
            if h.name == name:
                hooks.pop(i)
                return True
        return False

    def execute(self, hook_point: HookPoint,
                context: Optional[HookContext] = None) -> HookContext:
        ctx = context or HookContext(hook_point=hook_point)
        for hook in self._hooks[hook_point]:
            if not hook.enabled:
                continue
            try:
                hook.handler(ctx)
                if ctx.abort:
                    break
            except Exception as e:
                ctx.errors.append(f"Hook '{hook.name}': {e}")
        return ctx

    def list_hooks(self, hook_point: Optional[HookPoint] = None) -> List[Hook]:
        if hook_point:
            return self._hooks[hook_point]
        return [h for hooks in self._hooks.values() for h in hooks]

    def enable(self, hook_point: HookPoint, name: str) -> bool:
        for h in self._hooks[hook_point]:
            if h.name == name:
                h.enabled = True
                return True
        return False

    def disable(self, hook_point: HookPoint, name: str) -> bool:
        for h in self._hooks[hook_point]:
            if h.name == name:
                h.enabled = False
                return True
        return False


# ──────────────────────────────────────────────
# [6] GStackEngine — 统一入口
# ──────────────────────────────────────────────

@dataclass
class GStackState:
    active_role: Optional[str] = None
    active_skills: List[str] = field(default_factory=list)
    installed_plugins: List[str] = field(default_factory=list)
    config_path: str = ''
    browser_running: bool = False


class GStackEngine:
    """
    gstack统一引擎入口
    对应: gstack CLI + Claude Code 集成层

    用法:
        engine = GStackEngine()
        engine.load_config('/path/to/gstack')
        engine.switch_role('ceo')
        result = engine.execute_skill('review')
        engine.install_plugin('gstack-browser')
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config = StackConfig()
        self.skill_registry = SkillRegistry()
        self.role_manager = RoleManager()
        self.plugin_manager = PluginManager()
        self.hook_system = HookSystem()
        self.state = GStackState()
        self._register_core_skills()
        if config_path:
            self.load_config(config_path)

    def load_config(self, path: Union[str, Path]) -> None:
        self.config = StackConfig.from_dir(path)
        self.state.config_path = str(path)
        for name, skill_def in self.config.skills.items():
            self.skill_registry.register(name, FileSkill(skill_def))

    def switch_role(self, role_name: str) -> str:
        pre_ctx = HookContext(hook_point=HookPoint.PRE_ROLE_SWITCH,
                              data={'from': self.state.active_role, 'to': role_name})
        self.hook_system.execute(HookPoint.PRE_ROLE_SWITCH, pre_ctx)
        if pre_ctx.abort:
            raise RuntimeError(f"Role switch blocked: {pre_ctx.errors}")
        config = self.role_manager.switch_to(role_name)
        self.state.active_role = role_name
        post_ctx = HookContext(hook_point=HookPoint.POST_ROLE_SWITCH,
                               data={'role': role_name})
        self.hook_system.execute(HookPoint.POST_ROLE_SWITCH, post_ctx)
        return self.role_manager.generate_role_instruction()

    def get_current_role_prompt(self) -> str:
        return self.role_manager.generate_role_instruction()

    def list_available_roles(self) -> List[str]:
        return self.role_manager.list_roles()

    def execute_skill(self, skill_name: str,
                      args: Optional[List[str]] = None,
                      kwargs: Optional[Dict[str, str]] = None) -> SkillResult:
        ctx = SkillContext(args=args or [], kwargs=kwargs or {})
        pre_ctx = HookContext(hook_point=HookPoint.PRE_SKILL,
                              data={'skill': skill_name, 'context': ctx})
        self.hook_system.execute(HookPoint.PRE_SKILL, pre_ctx)
        if pre_ctx.abort:
            return SkillResult(success=False, error=f"Blocked: {pre_ctx.errors}")
        result = self.skill_registry.execute(skill_name, ctx)
        post_ctx = HookContext(hook_point=HookPoint.POST_SKILL,
                               data={'skill': skill_name, 'result': result})
        self.hook_system.execute(HookPoint.POST_SKILL, post_ctx)
        if not result.success:
            self.hook_system.execute(
                HookPoint.ON_ERROR,
                HookContext(hook_point=HookPoint.ON_ERROR,
                            data={'skill': skill_name, 'error': result.error}))
        return result

    def scan_plugins(self, path: Optional[str] = None) -> List[PluginInfo]:
        return self.plugin_manager.discover(path)

    def install_plugin(self, plugin_name: str,
                       source: Optional[str] = None) -> bool:
        pre_ctx = HookContext(hook_point=HookPoint.PRE_PLUGIN_INSTALL,
                              data={'plugin': plugin_name, 'source': source})
        self.hook_system.execute(HookPoint.PRE_PLUGIN_INSTALL, pre_ctx)
        if pre_ctx.abort:
            return False
        success = self.plugin_manager.install(plugin_name, source)
        if success:
            self.state.installed_plugins.append(plugin_name)
        post_ctx = HookContext(hook_point=HookPoint.POST_PLUGIN_INSTALL,
                               data={'plugin': plugin_name, 'success': success})
        self.hook_system.execute(HookPoint.POST_PLUGIN_INSTALL, post_ctx)
        return success

    def get_status(self) -> dict:
        return {
            'active_role': self.state.active_role,
            'roles_count': len(self.role_manager.list_roles()),
            'skills_count': len(self.skill_registry.list()),
            'plugins_installed': len(self.state.installed_plugins),
            'hooks_registered': len(self.hook_system.list_hooks()),
            'config_path': self.state.config_path,
        }

    def _register_core_skills(self) -> None:
        """注册内置核心技能"""

        class OfficeHoursSkill(Skill):
            name = 'office-hours'
            description = 'Reframes your product idea before you write code.'
            usage = '/office-hours'
            def execute(self, ctx):
                return SkillResult(success=True, output=(
                    "### Office Hours\n\nBefore writing code, clarify:\n"
                    "1. **Who's the user?** Target persona\n"
                    "2. **What's the pain?** Current solution\n"
                    "3. **Why now?** Market timing\n"
                    "4. **Success criteria?** Measurable metrics"))

        class ReviewSkill(Skill):
            name = 'review'
            description = 'Pre-landing PR review. Finds bugs that pass CI but break in prod.'
            usage = '/review [files...]'
            def execute(self, ctx):
                files = ctx.args if ctx.args else ['all']
                return SkillResult(success=True, output=(
                    f"### Code Review\n\nReviewing: {', '.join(files)}\n"
                    "Checking: race conditions, error handling, edge cases, security, performance"))

        class AutoPlanSkill(Skill):
            name = 'autoplan'
            description = 'One command runs CEO → design → eng → DX review.'
            usage = '/autoplan'
            def execute(self, ctx):
                return SkillResult(success=True, output=(
                    "### Autoplan\n\nRunning review pipeline:\n"
                    "1. CEO review: product direction\n"
                    "2. Design review: UX dimensions\n"
                    "3. Eng review: architecture\n"
                    "4. DX review: developer experience"))

        class InvestigateSkill(Skill):
            name = 'investigate'
            description = 'Systematic root-cause debugging.'
            usage = '/investigate [issue]'
            def execute(self, ctx):
                return SkillResult(success=True, output=(
                    "### Investigation\n\n"
                    "1. Reproduce the issue\n"
                    "2. Build hypothesis tree\n"
                    "3. Verify each hypothesis\n"
                    "4. Isolate root cause\n"
                    "5. Minimal repro case"))

        for s in [OfficeHoursSkill(), ReviewSkill(), AutoPlanSkill(), InvestigateSkill()]:
            self.skill_registry.register(s.name, s)

    # ──────────────────────────────────────────
    # [7] GA集成层 — 对接my-agent生态
    # ──────────────────────────────────────────

    def connect_to_ga(self, ga_root: Optional[str] = None) -> bool:
        """
        连接到my-agent运行环境
        
        自动发现:
          - GA的 skill_registry.py (P2元数据层)
          - plugins/ 目录
          - memory/ 下的所有 skill_*.py 文件
        
        用法:
            engine = GStackEngine()
            engine.connect_to_ga()  # 自动检测GA根目录
            engine.install_ga_skills()  # 安装所有GA技能为插件
        """
        if ga_root is None:
            # 向上回溯找到GA根目录 (含agentmain.py)
            cwd = os.getcwd()
            for p in [cwd] + [os.path.dirname(cwd)] + [os.path.dirname(os.path.dirname(cwd))]:
                if os.path.isfile(os.path.join(p, 'agentmain.py')):
                    ga_root = p
                    break
            if ga_root is None:
                ga_root = cwd  # fallback
        
        self._ga_root = ga_root
        self.state.config_path = ga_root
        self._scan_ga_plugins(ga_root)
        self._scan_ga_skills(ga_root)
        return True

    def _scan_ga_plugins(self, ga_root: str) -> None:
        """扫描GA plugins/ 目录"""
        plugins_dir = os.path.join(ga_root, 'plugins')
        if os.path.isdir(plugins_dir):
            discovered = self.plugin_manager.discover(plugins_dir)
            for p in discovered:
                self.state.installed_plugins.append(p.name)

    def _scan_ga_skills(self, ga_root: str) -> int:
        """扫描GA memory/ 下skill_*.py文件并注册为技能"""
        memory_dir = os.path.join(ga_root, 'memory')
        if not os.path.isdir(memory_dir):
            return 0
        
        count = 0
        for f in sorted(os.listdir(memory_dir)):
            if f.startswith('skill_') and f.endswith('.py'):
                skill_name = f[:-3]  # 去掉 .py
                abs_path = os.path.join(memory_dir, f)
                try:
                    # 提取第一段docstring作为描述
                    desc = ''
                    with open(abs_path, 'r', encoding='utf-8') as fh:
                        first = fh.read(500)
                    if '"""' in first:
                        desc = first.split('"""')[1].split('\n')[0].strip()[:100]
                    
                    self.skill_registry.register(
                        skill_name,
                        FileSkill(SkillDef(
                            name=skill_name,
                            description=desc or f'GA skill: {skill_name}',
                            path=abs_path,
                            source='ga_memory',
                        ))
                    )
                    count += 1
                except Exception:
                    continue
        return count

    def install_ga_skills(self, ga_root: Optional[str] = None) -> List[Tuple[str, PluginInfo]]:
        """
        一键安装GA所有技能为插件
        
        返回: [(skill_name, PluginInfo), ...]
        
        等同于gstack的 /plugin install ga-all-skills
        """
        if not getattr(self, '_ga_root', None):
            self.connect_to_ga(ga_root)
        
        installed = []
        for name in self.skill_registry.list():
            # 跳过核心技能 (已内置)
            if name in ('office-hours', 'review', 'autoplan', 'investigate'):
                continue
            skill_obj = self.skill_registry.get(name)
            if not skill_obj:
                continue
            
            info = PluginInfo(
                name=name,
                description=getattr(skill_obj, 'description', '')[:100],
                entry_point=getattr(skill_obj, 'skill_def', None) and 
                           getattr(skill_obj.skill_def, 'path', '') or '',
                install_path=self._ga_root if hasattr(self, '_ga_root') else '',
            )
            self.plugin_manager._plugins[name] = info
            self.plugin_manager.install(name)
            self.state.installed_plugins.append(name)
            installed.append((name, info))
        
        return installed


# ──────────────────────────────────────────────
# 自检
# ──────────────────────────────────────────────

from typing import List as _List


def self_check() -> _List[str]:
    fails = []

    # [1] StackConfig
    try:
        cfg = StackConfig.from_dir('.')
        assert cfg.root is not None
        assert cfg.browser_port == 9222
    except Exception as e:
        fails.append(f"[1] StackConfig: {e}")

    # [2] SkillRegistry
    try:
        reg = SkillRegistry()
        reg.register('test', OfficeHoursSkill() if False else type('TS', (Skill,), {
            'execute': lambda self, ctx: SkillResult(success=True, output='ok')})())
        assert reg.get('test') is not None
        assert reg.get('/test') is not None
        r = reg.execute('test')
        assert r.success
    except Exception as e:
        fails.append(f"[2] SkillRegistry: {e}")

    # [3] RoleManager
    try:
        rm = RoleManager()
        assert len(rm.list_roles()) >= 8
        cfg = rm.switch_to('ceo')
        assert cfg.temperature == 0.8
        assert rm.active_role.value == 'ceo'
        prompt = rm.generate_role_instruction()
        assert 'Role:' in prompt and 'Tools:' in prompt
        # 切换不存在的角色
        try:
            rm.switch_to('nonexistent')
            fails.append("[3] 应抛出ValueError")
        except ValueError:
            pass
    except Exception as e:
        fails.append(f"[3] RoleManager: {e}")

    # [4] PluginManager
    try:
        pm = PluginManager()
        info = PluginInfo(name='test-plugin', version='1.0',
                          dependencies=['dep-a', 'dep-b'])
        pm._plugins['test-plugin'] = info
        pm._plugins['dep-a'] = PluginInfo(name='dep-a')
        pm._plugins['dep-b'] = PluginInfo(name='dep-b')
        deps = pm.resolve_dependencies('test-plugin')
        assert len(deps) == 3  # dep-a + dep-b + test-plugin
        assert pm.install('test-plugin')
        assert pm.is_installed('test-plugin')
        assert pm.is_installed('dep-a')
        pm.uninstall('test-plugin')
        assert not pm.is_installed('test-plugin')
    except Exception as e:
        fails.append(f"[4] PluginManager: {e}")

    # [5] HookSystem
    try:
        hs = HookSystem()
        calls = []
        def handler(ctx):
            calls.append(ctx.hook_point.value)
        hs.register(HookPoint.PRE_SKILL, handler, 'test-hook')
        hs.execute(HookPoint.PRE_SKILL)
        assert len(calls) == 1
        assert calls[0] == 'pre-skill'
        # abort test
        def abort_handler(ctx):
            ctx.abort = True
        hs.register(HookPoint.PRE_ROLE_SWITCH, abort_handler, 'abort-hook')
        ctx = hs.execute(HookPoint.PRE_ROLE_SWITCH)
        assert ctx.abort
    except Exception as e:
        fails.append(f"[5] HookSystem: {e}")

    # [6] GStackEngine 端到端
    try:
        engine = GStackEngine()
        assert engine.get_status()['roles_count'] >= 8
        assert engine.get_status()['skills_count'] >= 4  # core skills

        # 角色切换
        instruction = engine.switch_role('ceo')
        assert 'CEO' in instruction.upper() or 'Role:' in instruction

        # 技能执行
        result = engine.execute_skill('office-hours')
        assert result.success

        # 技能未找到
        result2 = engine.execute_skill('nonexistent')
        assert not result2.success

        # 插件扫描 (当前目录)
        plugins = engine.scan_plugins()
        assert isinstance(plugins, list)

        # 状态报告
        status = engine.get_status()
        assert all(k in status for k in [
            'active_role', 'roles_count', 'skills_count',
            'plugins_installed', 'hooks_registered', 'config_path'])
    except Exception as e:
        fails.append(f"[6] GStackEngine: {e}")

    return fails


if __name__ == '__main__':
    fails = self_check()
    if fails:
        print(f"❌ 自检失败 ({len(fails)}):")
        for f in fails:
            print(f"  - {f}")
    else:
        print("🎉 skill_gstack.py 全部6/6自检通过!")

    print("\n=== gstack 演示 ===")
    engine = GStackEngine()
    print(f"可用角色: {', '.join(engine.list_available_roles())}")
    print(f"可用技能: {', '.join(engine.skill_registry.list())}")
    print(f"\n状态: {json.dumps(engine.get_status(), indent=2)}")

    # ── GA插件安装演示 ──
    GA_DIR = r'C:\Users\Administrator\my-agent'
    print("\n=== GA插件安装器演示 ===")
    ga_engine = GStackEngine()
    ga_engine.connect_to_ga(GA_DIR)
    print(f"已发现: GA根目录={ga_engine._ga_root}")
    print(f"  技能数: {len(ga_engine.skill_registry.list())}")
    installed = ga_engine.install_ga_skills(GA_DIR)
    print(f"已安装 {len(installed)} 个GA技能插件:")
    for name, info in installed[:10]:
        print(f"  ✅ {name}")
    if len(installed) > 10:
        print(f"  ... 及 {len(installed)-10} 个更多")
    print(f"\n最终状态: {json.dumps(ga_engine.get_status(), indent=2)}")
