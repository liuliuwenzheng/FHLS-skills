"""
GA SOP: 反巨函数 — 代码质量红线
=================================
骨髓内化自 Claude Code print.ts 惨案（图4）
+ GitHub Issue #33949: SSE流挂起/无法取消(37评论/更新于2026-05-23)

print.ts: 3167行/12层嵌套/圈复杂度486/12个参数(实际options含16子属性)
         → 1人处理SIGINT/rate-limits/AWS/plugin/MCP/Worktree/team-lead polling
         → 拆成8-10个独立模块才是正解

GA Rule: 函数超过200行必须拆 | 每函数至多4个参数 | 嵌套不超过4层
"""

import ast, sys
from pathlib import Path
from typing import List, Tuple, Optional

# ============================================================
# 1. 反巨函数检查器 — 在代码提交前自动检测
# ============================================================

class GodFunctionDetector:
    """
    巨函数检测器 — 扫描Python文件检测"巨函数前兆"
    
    用法:
        detector = GodFunctionDetector()
        issues = detector.scan_file("my_module.py")
        for issue in issues:
            print(issue)
    """
    
    # 红线阈值（来自print.ts教训，更严格）
    THRESHOLDS = {
        "max_lines": 200,          # print.ts: 3167行 → 红线200
        "max_nesting": 4,          # print.ts: 12层嵌套 → 红线4
        "max_params": 4,           # print.ts: 12个参数 → 红线4
        "max_complexity": 15,      # print.ts: 圈复杂度486 → 红线15
        "max_inner_funcs": 5,      # print.ts: 21个内部函数 → 红线5
    }
    
    def __init__(self, thresholds: Optional[dict] = None):
        self.thresholds = {**self.THRESHOLDS, **(thresholds or {})}
    
    def scan_file(self, filepath: str) -> List[str]:
        """扫描单个文件"""
        issues = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                source = f.read()
            
            tree = ast.parse(source)
            lines = source.split('\n')
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_issues = self._check_function(node, lines, filepath)
                    issues.extend(func_issues)
                    
        except SyntaxError as e:
            issues.append(f"⚠️ 语法错误: {e}")
        except Exception as e:
            issues.append(f"❌ 扫描异常: {e}")
        
        return issues
    
    def _check_function(self, node: ast.FunctionDef, lines: list, filepath: str) -> List[str]:
        """检查单个函数是否违反红线"""
        issues = []
        name = node.name
        start_line = node.lineno
        end_line = getattr(node, 'end_lineno', start_line)
        func_lines = end_line - start_line + 1
        
        # 1. 行数检查
        if func_lines > self.thresholds["max_lines"]:
            issues.append(
                f"🚫 [{filepath}:{start_line}] {name}: {func_lines}行 "
                f"(红线{self.thresholds['max_lines']}行) → 必须拆分"
            )
        
        # 2. 参数检查
        params = len(node.args.args) + len(node.args.kwonlyargs) + (1 if node.args.vararg else 0)
        if params > self.thresholds["max_params"]:
            issues.append(
                f"⚠️ [{filepath}:{start_line}] {name}: {params}个参数 "
                f"(红线{self.thresholds['max_params']}个) → 考虑用dataclass/字典"
            )
        
        # 3. 嵌套深度检查
        depth = self._calc_nesting_depth(node)
        if depth > self.thresholds["max_nesting"]:
            issues.append(
                f"⚠️ [{filepath}:{start_line}] {name}: 嵌套{depth}层 "
                f"(红线{self.thresholds['max_nesting']}层) → 提前return/提取子函数"
            )
        
        # 4. 内部函数数量
        inner_funcs = [n for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n != node]
        if len(inner_funcs) > self.thresholds["max_inner_funcs"]:
            issues.append(
                f"⚠️ [{filepath}:{start_line}] {name}: {len(inner_funcs)}个内部函数 "
                f"(红线{self.thresholds['max_inner_funcs']}个) → 提取为模块级函数"
            )
        
        return issues
    
    def _calc_nesting_depth(self, node: ast.AST, depth: int = 0) -> int:
        """计算AST嵌套深度"""
        max_depth = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.With,
                                  ast.AsyncFor, ast.AsyncWith)):
                child_depth = self._calc_nesting_depth(child, depth + 1)
                max_depth = max(max_depth, child_depth)
            else:
                child_depth = self._calc_nesting_depth(child, depth)
                max_depth = max(max_depth, child_depth)
        return max_depth


# ============================================================
# 2. 代码拆分建议器 — 巨函数→模块分解
# ============================================================

class FunctionSplitter:
    """
    巨函数分解建议器
    基于print.ts教训: 1个3000行函数 → 8-10个独立模块
    """
    
    @staticmethod
    def suggest_split(func_name: str, responsibilities: List[str]) -> dict:
        """
        建议如何拆分解函数
        
        示例:
            suggestions = FunctionSplitter.suggest_split(
                "print_output", 
                ["SIGINT处理", "速率限制", "AWS lifecycle", "plugin认证", "MCP通信", "团队轮询"]
            )
        """
        if len(responsibilities) <= 3:
            return {"status": "可接受", "modules": [func_name]}
        
        # 按职责领域分组
        modules = {}
        for i, resp in enumerate(responsibilities):
            module_name = f"{func_name}_{self._to_snake(resp)}"
            modules[module_name] = resp
        
        return {
            "status": "建议拆分",
            "original": func_name,
            "suggested_modules": list(modules.keys()),
            "split_count": len(modules),
            "rule": f"1个函数处理{len(responsibilities)}个职责 → 拆成{len(modules)}个模块"
        }
    
    @staticmethod
    def _to_snake(name: str) -> str:
        return re.sub(r'[^a-zA-Z0-9]', '_', name.lower()).strip('_')


# ============================================================
# 3. GA代码质量宪法 — 新增条款
# ============================================================

CODE_QUALITY_CONSTITUTION = [
    "【R20-单函数红线】函数不超过200行。print.ts 3167行是反面教材",
    "【R21-参数红线】函数参数不超过4个。超过用dataclass/配置对象",
    "【R22-嵌套红线】嵌套不超过4层。超过是代码坏味道",
    "【R23-内部函数红线】内部函数不超过5个。超过提取为模块级",
    "【R24-单一职责】一个函数只做一件事。多件事→多函数/多模块",
    "【R25-拆解时机】当第2人看不懂你的函数时，就该拆分了",
    "【R26-提交前自检】每次提交前用GodFunctionDetector扫描变更文件",
]


import re  # 给FunctionSplitter用

if __name__ == "__main__":
    # 自检
    detector = GodFunctionDetector()
    this_file = __file__
    issues = detector.scan_file(this_file)
    
    if issues:
        print(f"⚠️ {this_file} 检测到 {len(issues)} 个问题:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print(f"✅ {this_file} 通过反巨函数检查")
    
    print("\n📋 代码质量宪法:")
    for rule in CODE_QUALITY_CONSTITUTION:
        print(f"  {rule}")
