"""
skill_superpowers.py - Superpowers (obra/203k⭐) 骨髓内化

核心定位: Agentic Skills Framework → 15个可组合技能
与GA关系: skill_multi_agent_dev_team + skill_orchestrator 的补充升级

Superpowers核心假设:
  1. Agent需要**可组合的技能**而不是大而全的prompt
  2. 每个任务应当用**Fresh子Agent**执行（无session污染）
  3. 每个产出必须经过**两阶段审核**: spec compliance → code quality
  4. 并行独立任务应当**同时调度**而不是串行

GA差距:
  - GA有skill_registry(注册)/skill_orchestrator(编排)/reflex_layer(反射)
  - 缺少: subagent隔离执行 / 两阶段审核 / 并行调度 / systematic-debugging

骨髓内化产出: 以下3个可import模式 + 1个整体get_gaps
"""

# ─── 模块一: Subagent模式 ───
class SubagentPattern:
    """Superpowers subagent-driven-development 骨髓内化
    
    核心: 每次任务启动全新子Agent，精确构建上下文，避免session污染
    与GA关系: 可加强skill_multi_agent_dev_team的Dev Agent纯度
    """
    
    @staticmethod
    def create_subagent_context(task_spec: str, context_files: list[str] = None) -> dict:
        """构建子Agent的精确上下文
        
        Args:
            task_spec: 任务说明（对应Superpowers的"plan step"）
            context_files: 相关文件路径列表
            
        Returns:
            context字典，包含: task, files, constraints, acceptance_criteria
        """
        return {
            "task": task_spec,
            "files": context_files or [],
            "constraints": [
                "只修改指定文件",
                "不改未提及的接口签名",
                "保持现有代码风格",
            ],
            "acceptance_criteria": [],  # 两阶段审核填充
        }

    @staticmethod
    def two_stage_review(spec: str, code: str) -> dict:
        """两阶段审核: spec compliance → code quality
        
        Returns: {"spec_compliant": bool, "code_quality": str, "issues": []}
        """
        # Stage 1: Spec Compliance - 代码是否满足spec
        spec_issues = SubagentPattern._check_spec_compliance(spec, code)
        if spec_issues:
            return {"spec_compliant": False, "code_quality": "N/A", "issues": spec_issues}
        
        # Stage 2: Code Quality - 代码质量评审
        quality_issues = SubagentPattern._check_code_quality(code)
        return {
            "spec_compliant": True,
            "code_quality": "pass" if not quality_issues else "needs_improvement",
            "issues": quality_issues,
        }

    @staticmethod
    def _check_spec_compliance(spec: str, code: str) -> list[str]:
        """检查代码是否符合spec（骨架，使用时需Claude注入判断）"""
        issues = []
        # 实际使用时注入Claude/LLM判断
        return issues

    @staticmethod
    def _check_code_quality(code: str) -> list[str]:
        """代码质量检查（骨架）"""
        issues = []
        # 检查点: 错误处理、边界条件、性能、可读性
        return issues


# ─── 模块二: 并行调度模式 ───
class ParallelDispatchPattern:
    """Superpowers dispatching-parallel-agents 骨髓内化
    
    核心: 2+个独立任务同时派发到不同子Agent
    使用条件: 
      - 任务之间无共享状态
      - 每个问题可以独立理解
      - 修复一个不会影响其他的
    """
    
    @staticmethod
    def can_parallelize(tasks: list[str]) -> tuple[bool, str]:
        """判断任务是否可以并行
        
        Returns: (can_parallel, reason)
        """
        if len(tasks) < 2:
            return False, "少于2个任务，无需并行"
        if len(tasks) > 5:
            return False, f"{len(tasks)}个任务过多，建议分批"
        
        # 检查任务间依赖
        dependencies = ParallelDispatchPattern._detect_dependencies(tasks)
        if dependencies:
            return False, f"任务间存在依赖: {dependencies}"
        
        return True, "任务独立，可并行调度"

    @staticmethod
    def _detect_dependencies(tasks: list[str]) -> list[str]:
        """检测任务间依赖（骨架）"""
        # 关键词检测: 如果taskB提到taskA的结果，则有依赖
        dependencies = []
        return dependencies

    @staticmethod
    def dispatch_batch(tasks: list[str]) -> dict:
        """批量派发任务
        
        Returns: {task_index: "dispatched" | "failed"}
        """
        can_parallel, reason = ParallelDispatchPattern.can_parallelize(tasks)
        if not can_parallel:
            return {"error": reason}
        
        # 每个任务独立构建context
        results = {}
        for i, task in enumerate(tasks):
            try:
                ctx = SubagentPattern.create_subagent_context(task)
                results[i] = {"status": "dispatched", "context": ctx}
            except Exception as e:
                results[i] = {"status": "failed", "error": str(e)}
        
        return results


# ─── 模块三: 系统级调试模式 ───
class SystematicDebugPattern:
    """Superpowers systematic-debugging 骨髓内化
    
    核心: 5步系统调试法
    1. Reproduce → 稳定复现
    2. Isolate → 缩小范围
    3. Diagnose → 确定根因
    4. Fix → 最小修复
    5. Verify → 验证修复
    """
    
    STEPS = ["reproduce", "isolate", "diagnose", "fix", "verify"]
    
    @staticmethod
    def debug_session(error_desc: str, context: dict = None) -> dict:
        """启动调试会话
        
        Returns: {step: result, ...} 调试过程记录
        """
        session = {
            "error": error_desc,
            "context": context or {},
            "steps": {},
            "status": "in_progress",
        }
        return session

    @staticmethod
    def get_debug_prompt(step: str, session: dict) -> str:
        """获取某一步的调试prompt"""
        prompts = {
            "reproduce": "请稳定复现此bug：{error}。输出最小复现步骤。",
            "isolate": "从{context}中隔离出最小出错范围。逐层排除：环境/数据/逻辑/依赖。",
            "diagnose": "在隔离范围{isolated}内，确定根因。是逻辑错误/边界条件/竞态/资源泄漏？",
            "fix": "基于根因{root_cause}，提供最小修复。只改必须改的代码。",
            "verify": "验证修复：原复现步骤不再触发bug + 现有测试通过 + 边界测试。",
        }
        template = prompts.get(step, "执行调试步骤: {step}")
        return template.format(step=step, **session)


# ─── 模块四: 计划分解模式 (writing-plans 骨髓内化) ───
class PlanPattern:
    """Superpowers writing-plans 骨髓内化
    
    核心原则:
    1. 零上下文假设 — 假设工程师对代码库一无所知
    2. 2-5分钟/步 — 每步只做一件事
    3. 文件结构优先 — 先映射文件再分解任务
    4. 禁止占位符 — "TBD/TODO"视为计划失败
    5. Plan Header强制 — Goal + Architecture + Tech Stack
    
    与GA plan_sop差异:
    - plan_sop粒度10-30分钟, 这里是2-5分钟
    - plan_sop无"文件结构优先"步骤
    - plan_sop允许占位符
    """
    
    PLAN_HEADER_TEMPLATE = """# [{feature}] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** {goal}

**Architecture:** {architecture}

**Tech Stack:** {tech_stack}

---"""

    TASK_TEMPLATE = """### Task {n}: {component_name}

**Files:**
- Create: `{create_files}`
- Modify: `{modify_files}`
- Test: `{test_files}`

- [ ] **Step 1: {step_desc}**
```{lang}
{step_code}
```
- [ ] **Step 2: {step_desc2}**
Expected: {expected}
"""

    SAVE_PATH = "docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md"

    @staticmethod
    def create_plan_header(feature: str, goal: str, architecture: str, tech_stack: str) -> str:
        """创建Plan Header"""
        return PlanPattern.PLAN_HEADER_TEMPLATE.format(
            feature=feature, goal=goal,
            architecture=architecture, tech_stack=tech_stack,
        )

    @staticmethod
    def scope_check(spec: str) -> list[str]:
        """检查spec是否覆盖多个独立子系统
        
        Returns: 建议拆分的子系统列表，空=可直接编计划
        """
        subsystems = []
        # 骨架：检查spec中是否包含多个独立模块
        return subsystems

    @staticmethod
    def file_structure_map(files: list[dict]) -> str:
        """输出文件结构映射表
        
        Args:
            files: [{"path": "src/x.py", "responsibility": "X功能", "action": "create|modify"}]
        Returns:
            格式化的文件结构markdown
        """
        lines = ["## 文件结构\n"]
        for f in files:
            icon = "🆕" if f.get("action") == "create" else "✏️"
            lines.append(f"- {icon} `{f['path']}` → {f['responsibility']}")
        return "\n".join(lines)

    @staticmethod
    def create_task(n: int, component: str, files: dict, steps: list[dict]) -> str:
        """创建单个任务块
        
        Args:
            steps: [{"desc": "写测试", "code": "...", "lang": "python", "expected": "FAIL"}]
        """
        parts = [f"### Task {n}: {component}\n"]
        parts.append(f"**Files:**")
        if files.get("create"):
            parts.append(f"- Create: `{files['create']}`")
        if files.get("modify"):
            parts.append(f"- Modify: `{files['modify']}`")
        if files.get("test"):
            parts.append(f"- Test: `{files['test']}`")
        parts.append("")
        
        for i, step in enumerate(steps):
            parts.append(f"- [ ] **Step {i+1}: {step['desc']}**")
            if step.get("code"):
                parts.append(f"```{step.get('lang', 'python')}")
                parts.append(step["code"])
                parts.append("```")
            if step.get("expected"):
                parts.append(f"Expected: {step['expected']}")
            parts.append("")
        
        return "\n".join(parts)

    @staticmethod
    def validate_plan(plan_text: str) -> list[str]:
        """验证计划质量 - 检查禁止项
        
        Returns: 问题列表，空=计划合格
        """
        issues = []
        forbidden = ["TBD", "TODO", "implement later", "fill in details", "to be determined"]
        for word in forbidden:
            if word.lower() in plan_text.lower():
                issues.append(f"禁止占位符: '{word}' 出现在计划中")
        
        # 检查是否包含无步骤的空任务
        if "### Task " in plan_text and "- [ ]" not in plan_text:
            issues.append("任务缺少步骤（- [ ] 标记）")
        
        return issues


# ─── 模块五: 头脑风暴模式 (brainstorming 骨髓内化) ───
class BrainstormPattern:
    """Superpowers brainstorming 骨髓内化
    
    核心: 设计先行，<HARD-GATE>禁止在用户批准前写代码
    
    9步流程:
    1. 探索项目上下文 — 检查文件/文档/commit
    2. 提供可视化辅助
    3. 逐一澄清问题
    4. 提出2-3方案含权衡
    5. 分节呈现设计
    6. 写设计文档
    7. Spec自审
    8. 用户审阅spec
    9. 调用writing-plans
    
    与GA关系: GA plan_sop缺少设计先行的硬性约束
    """
    
    PROCESS_STEPS = [
        "explore_context",
        "offer_visual",
        "clarify_questions",
        "propose_approaches",
        "present_design",
        "write_doc",
        "self_review",
        "user_review",
        "transition_to_planning",
    ]
    
    SPEC_SAVE_PATH = "docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md"

    @staticmethod
    def create_session(topic: str) -> dict:
        """创建头脑风暴会话"""
        return {
            "topic": topic,
            "current_step": "explore_context",
            "completed_steps": [],
            "design_doc": None,
            "approaches": [],
            "user_approved": False,
        }

    @staticmethod
    def self_review_spec(spec_text: str) -> list[str]:
        """Spec自审 - 检查占位符/矛盾/歧义/范围
        
        Returns: 问题列表
        """
        issues = []
        
        # 占位符检查
        placeholders = ["TBD", "TODO", "FIXME", "to be determined", "implement later"]
        for p in placeholders:
            if p.lower() in spec_text.lower():
                issues.append(f"含占位符: {p}")
        
        # 矛盾检查（骨架）
        contradictions = BrainstormPattern._find_contradictions(spec_text)
        issues.extend(contradictions)
        
        # 歧义检查
        ambiguous = ["some", "etc", "etc.", "and so on", "appropriate"]
        for a in ambiguous:
            if a.lower() in spec_text.lower():
                issues.append(f"可能存在歧义: '{a}'")
        
        return issues

    @staticmethod
    def _find_contradictions(text: str) -> list[str]:
        """查找spec中的矛盾（骨架）"""
        return []

    @staticmethod
    def check_hard_gate(session: dict) -> bool:
        """检查<HARD-GATE> — 用户是否已批准设计
        
        Returns: True=可以推进到实现
        """
        if not session.get("user_approved"):
            return False
        if not session.get("design_doc"):
            return False
        return True

    @staticmethod
    def propose_approaches(options: list[dict]) -> str:
        """生成2-3方案建议
        
        Args:
            options: [{"name": "方案A", "pros": [...], "cons": [...], "recommended": bool}]
        """
        parts = ["## 方案对比\n"]
        for opt in options:
            badge = " ✅ **推荐**" if opt.get("recommended") else ""
            parts.append(f"### {opt['name']}{badge}")
            parts.append(f"- 优点: {', '.join(opt.get('pros', []))}")
            parts.append(f"- 缺点: {', '.join(opt.get('cons', []))}")
            parts.append("")
        return "\n".join(parts)


# ─── 模块六: GA差距分析 ───
def get_superpowers_gaps() -> dict:
    """返回GA与Superpowers之间的差距分析
    
    Returns:
        gap字典，每个gap含: current_state, target, migration_path, priority(1-5)
    """
    return {
        "subagent_isolation": {
            "current": "GA多Agent共享session上下文，上下文污染风险",
            "target": "每个任务启动Fresh子Agent，精确构建上下文",
            "migration_path": "extend skill_multi_agent_dev_team → 增加DevAgent隔离执行",
            "priority": 4,  # 1-5
        },
        "two_stage_review": {
            "current": "GA无自动代码审核流程",
            "target": "每个产出自带spec-compliance + code-quality两阶段审核",
            "migration_path": "在skill_multi_agent_dev_team中增加review模式",
            "priority": 3,
        },
        "parallel_dispatch": {
            "current": "GA串行执行独立任务",
            "target": "2+个独立Agent并行工作",
            "migration_path": "在reflex_layer中增加并行调度能力",
            "priority": 2,
        },
        "systematic_debugging": {
            "current": "GA依赖人工调试",
            "target": "5步系统调试法(reproduce→isolate→diagnose→fix→verify)",
            "migration_path": "新建skill_debug_session SOP",
            "priority": 1,
        },
    }


def describe() -> str:
    """Describe this skill"""
    return (
        "skill_superpowers: Superpowers(obra/203k⭐) 骨髓内化模块\n"
        "- SubagentPattern: Fresh子Agent/任务 + 两阶段审核\n"
        "- ParallelDispatchPattern: 并行调度独立任务\n"
        "- SystematicDebugPattern: 5步系统调试法\n"
        "- PlanPattern: 2-5分钟/步计划分解 + 零上下文假设 + 禁止占位符\n"
        "- BrainstormPattern: 9步设计先行流程 + <HARD-GATE>防过早编码\n"
        "- get_superpowers_gaps(): 返回GA差距分析\n"
        "→ 见 ../memory/global_mem_insight.txt L70"
    )


if __name__ == "__main__":
    # 自检
    print("=" * 60)
    print("🔍 Superpowers骨髓内化模块自检")
    print("=" * 60)
    
    # 1. SubagentPattern
    ctx = SubagentPattern.create_subagent_context("实现用户登录接口")
    assert "task" in ctx
    print(f"✅ SubagentPattern.create_subagent_context: {ctx['task']}")
    
    review = SubagentPattern.two_stage_review("spec", "code")
    assert "spec_compliant" in review
    print(f"✅ SubagentPattern.two_stage_review: spec={review['spec_compliant']}")
    
    # 2. ParallelDispatchPattern
    can_p, reason = ParallelDispatchPattern.can_parallelize(["修复bugA", "新增功能B", "优化性能C"])
    print(f"✅ ParallelDispatchPattern.can_parallelize: {can_p}, reason={reason}")
    
    # 3. SystematicDebugPattern
    session = SystematicDebugPattern.debug_session("登录接口500错误")
    assert session["status"] == "in_progress"
    prompt = SystematicDebugPattern.get_debug_prompt("reproduce", session)
    assert "复现" in prompt
    print(f"✅ SystematicDebugPattern: 调试会话已创建")
    
    # 4. PlanPattern
    header = PlanPattern.create_plan_header("用户登录", "实现JWT登录", "MVC架构", "Python/FastAPI")
    assert "Goal:" in header and "Architecture:" in header
    print(f"✅ PlanPattern.create_plan_header: Header生成成功")
    
    task = PlanPattern.create_task(1, "用户登录", 
        {"create": "src/auth/login.py", "test": "tests/test_login.py"},
        [{"desc": "写测试", "code": "def test_login(): ...", "expected": "FAIL"}])
    assert "Task 1" in task
    print(f"✅ PlanPattern.create_task: 任务块生成成功")
    
    validation = PlanPattern.validate_plan("这是没有占位符的好计划，全部内容已确定")
    assert len(validation) == 0
    print(f"✅ PlanPattern.validate_plan: 无占位符计划通过")
    
    validation_fail = PlanPattern.validate_plan("这里有个TODO需要实现")
    assert len(validation_fail) > 0
    print(f"✅ PlanPattern.validate_plan: 含占位符计划被检出")
    
    # 5. BrainstormPattern
    bs = BrainstormPattern.create_session("聊天功能")
    assert bs["current_step"] == "explore_context"
    print(f"✅ BrainstormPattern.create_session: 头脑风暴会话创建")
    
    issues = BrainstormPattern.self_review_spec("使用TBD字段")
    assert len(issues) > 0
    print(f"✅ BrainstormPattern.self_review_spec: 自审检出占位符")
    
    gate = BrainstormPattern.check_hard_gate({"user_approved": False, "design_doc": None})
    assert gate == False
    print(f"✅ BrainstormPattern.check_hard_gate: 未批准状态正确拦截")
    
    options = BrainstormPattern.propose_approaches([
        {"name": "方案A", "pros": ["简单"], "cons": ["性能差"], "recommended": True},
        {"name": "方案B", "pros": ["性能好"], "cons": ["复杂"]},
    ])
    assert "方案A" in options and "方案B" in options
    print(f"✅ BrainstormPattern.propose_approaches: 方案对比生成成功")
    
    # 6. Gaps
    gaps = get_superpowers_gaps()
    assert len(gaps) >= 4
    print(f"✅ get_superpowers_gaps: {len(gaps)}个差距识别")
    for name, info in gaps.items():
        print(f"   - {name}: 优先级{info['priority']}/5")
    
    print("\n✅ 全部自检通过 (6个模块)")
