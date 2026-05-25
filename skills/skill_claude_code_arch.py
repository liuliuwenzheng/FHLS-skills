"""
GA Skill: Claude Code Architecture Reference
=============================================
骨髓内化自 anthropics/claude-code 源码架构分析 (126K stars)
骨架优先: 类名/方法签名即文档 | GA可import | 非搬运笔记

关键发现（来自图1 + GitHub Issues社区讨论）:
- #61953 Claude主动删除安全标记文件绕过安全钩子
- #60226 AI分析无依据仍继续执行
- #61167 Opus 4.7伪造agent调度
- 巨函数print.ts: 3,167行/12层嵌套/圈复杂度486
"""

import os, json, subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ============================================================
# 1. 架构骨架 — 从1900文件/512K行代码中提炼的核心层级
# ============================================================

@dataclass
class ClaudeCodeArch:
    """Claude Code 架构全景 — 用数字说话"""
    
    # 规模指标（来自源码分析）
    total_files: int = 1900
    total_lines: int = 512_000
    total_tools: int = 40
    total_commands: int = 50
    total_ui_components: int = 140
    
    # 语言/运行时
    runtime: str = "Bun"  # JavaScript运行时
    lang: str = "TypeScript"
    ui_framework: str = "Ink"  # 终端React渲染
    sdk: str = "@anthropic-ai/sdk"
    validation: str = "Zod V4"
    
    # 架构层级（自底向上）
    layers: Dict[str, str] = field(default_factory=lambda: {
        "L0_core": "核心协议: MCP通信协议 + 工具注册框架",
        "L1_tools": "40+工具: 文件R/W/Grep/Glob/Git/Web/Bash/MCP…",
        "L2_commands": "50+命令: /bug /think /review /plan /deploy…",
        "L3_agents": "多智能体: 子Agent生成/团队编排/并行任务",
        "L4_ui": "140+Ink组件: 终端渲染/交互流/状态管理",
        "L5_security": "六级权限验证: AST→注入检测→规则→沙盒→AI分类器→决策",
    })
    
    # 多智能体协作模式 — 从图1+图5提炼
    agent_team_capabilities: List[str] = field(default_factory=lambda: [
        "子智能体自动生成: 根据任务描述创建专用Agent",
        "团队管理: leader-agent负责协调子Agent",
        "并行任务编排: 多Agent同时执行不同子任务",
        "结果聚合: 子Agent输出自动合并到主流程",
    ])

    def summary(self) -> str:
        """一句话概括架构"""
        return (f"Claude Code: {self.total_files}文件/{self.total_lines}行代码, "
                f"{self.total_tools}工具/{self.total_commands}命令/{self.total_ui_components}UI组件, "
                f"Bun+TS+Ink栈, {len(self.layers)}层架构")


@dataclass
class CodeSearchAPI:
    """代码搜索工具集 — Claude Code的核心能力之一"""
    
    @staticmethod
    def grep(pattern: str, path: str = ".") -> List[str]:
        """ripgrep搜索 — 比传统grep快10倍"""
        result = subprocess.run(
            ["rg", "-n", pattern, path],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.splitlines() if result.stdout else []
    
    @staticmethod
    def glob(pattern: str, path: str = ".") -> List[str]:
        """Glob文件查找"""
        import glob as _glob
        return _glob.glob(os.path.join(path, pattern), recursive=True)


# ============================================================
# 2. 反模式警钟 — 从巨函数print.ts学到的教训
# ============================================================

GOD_FUNCTION_WARNINGS = {
    "print.ts_lessons": """
【反模式】print.ts — 3,167行/12层嵌套/圈复杂度486
❌ 一人处理: SIGINT/rate-limits/AWS lifecycle/plugin auth/MCP/Worktree/team-lead polling
❌ 12个参数(实际options含16子属性) → 隐含耦合爆炸
❌ 定义了21个内部函数和闭包 → 无法单元测试
✅ 应该拆成8-10个独立模块

GA Rule: 函数超过200行必须拆 | 每函数至多4个参数 | 嵌套不超过4层
""",
}


# ============================================================
# 3. 工具注册框架 — Claude Code的40+工具注册模式
# ============================================================

@dataclass
class ToolRegistration:
    """工具注册范式 — GA可复用"""
    name: str
    description: str
    parameters: Dict
    handler: callable
    
# 示例: 一个工具注册的最简结构
TOOL_TEMPLATE = {
    "name": "tool_name",
    "description": "工具描述",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}


# ============================================================
# 4. 快捷键自检
# ============================================================

ARCH_KEY_INSIGHTS = [
    "Claude Code 40工具本质是【MCP协议的工程化实现】— 工具注册+执行+结果流式返回",
    "140个UI组件全部用Ink(终端React)实现 → 证明终端UI可以组件化",
    "多智能体不是Hype, Claude Code已在生产环境使用",
    "安全性: 六级验证栈 + 100万+训练命令的BASH_CLASSIFIER",
    "巨函数教训: 架构级的『一人做事』是代码腐烂的起点",
]


if __name__ == "__main__":
    arch = ClaudeCodeArch()
    print(arch.summary())
    print("\n".join(ARCH_KEY_INSIGHTS))
