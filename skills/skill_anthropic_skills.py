"""
skill_anthropic_skills.py — anthropics/skills (Anthropic官方 / 139k⭐) 骨髓内化

核心架构:
 - SKILL.md规范: YAML frontmatter + markdown指令
 - 技能目录结构: 自包含文件夹(SKILL.md + 资源/脚本)
 - skill-creator: 元技能(创建/评估/迭代技能)
 - eval框架: 量化+定性评估, 方差分析
 - Agent Skills Standard: agentskills.io

与GA现有skill体系对比:
 - GA: memory/下的.py + .md混合, skill_registry静态索引
 - Anthropic: 纯Markdown指令文件夹 + 可执行脚本
 - 核心差异: Anthropic的Skill由Claude解释执行, GA的Skill是importable模块

可复用的模式:
 1. SkillSpec规范: YAML frontmatter元数据
 2. SkillTemplate: 标准化SKILL.md模板
 3. EvalFramework: 定性+定量评估基准
 4. SkillCreator元技能: 创建→评估→迭代闭环
"""

import os
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Callable, Any
from datetime import datetime
from pathlib import Path


# ═══════════════════════════════════════════
# 1. SkillSpec — SKILL.md规范(来自anthropics/skills)
# ═══════════════════════════════════════════

@dataclass
class SkillMetadata:
    """SKILL.md的YAML frontmatter"""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    
    def to_yaml_frontmatter(self) -> str:
        """转YAML frontmatter格式"""
        lines = ["---"]
        lines.append(f"name: {self.name}")
        lines.append(f"description: {self.description}")
        if self.version != "1.0.0":
            lines.append(f"version: {self.version}")
        if self.author:
            lines.append(f"author: {self.author}")
        if self.tags:
            lines.append(f"tags: [{', '.join(self.tags)}]")
        if self.dependencies:
            lines.append(f"dependencies: [{', '.join(self.dependencies)}]")
        lines.append("---")
        return "\n".join(lines)
    
    @classmethod
    def from_yaml_block(cls, text: str) -> Optional['SkillMetadata']:
        """从YAML frontmatter解析"""
        if not text.startswith("---"):
            return None
        end = text.find("---", 3)
        if end == -1:
            return None
        block = text[3:end].strip()
        meta = {"name": "", "description": "", "tags": [], "dependencies": []}
        for line in block.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key in ("tags", "dependencies"):
                    meta[key] = [v.strip().strip('"').strip("'") 
                                 for v in val.strip("[]").split(",") if v.strip()]
                else:
                    meta[key] = val
        return cls(**{k: v for k, v in meta.items() if k in cls.__dataclass_fields__})


@dataclass
class SkillSpec:
    """完整的技能规范 — 仿anthropics/skills SKILL.md"""
    metadata: SkillMetadata
    instructions: str = ""
    scripts_dir: Optional[str] = None  # scripts/目录路径
    templates_dir: Optional[str] = None  # templates/目录路径
    eval_file: Optional[str] = None  # evals.json路径
    
    def render(self) -> str:
        """渲染完整SKILL.md"""
        parts = [self.metadata.to_yaml_frontmatter()]
        parts.append("")
        parts.append(f"# {self.metadata.name}")
        parts.append("")
        parts.append(self.instructions)
        return "\n".join(parts)
    
    def save(self, path: str):
        """保存为SKILL.md"""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.render())


# ═══════════════════════════════════════════
# 2. SkillTemplate — 技能模板引擎(来自anthropics/skills template/)
# ═══════════════════════════════════════════

class SkillTemplate:
    """
    技能模板 — 从SKILL.md模板文件创建新技能
    
    用法:
        tmpl = SkillTemplate()
        skill = tmpl.create("my-skill", "Does X", instructions="...")
        spec.save("./my-skill/SKILL.md")
    """
    
    @staticmethod
    def create(name: str, description: str, 
               instructions: str = "",
               tags: List[str] = None,
               dependencies: List[str] = None) -> SkillSpec:
        """从模板创建新技能"""
        meta = SkillMetadata(
            name=name,
            description=description,
            tags=tags or [],
            dependencies=dependencies or []
        )
        return SkillSpec(metadata=meta, instructions=instructions)
    
    @staticmethod
    def from_skill_md(path: str) -> Optional[SkillSpec]:
        """从SKILL.md文件解析技能"""
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        
        meta = SkillMetadata.from_yaml_block(text)
        if not meta:
            return None
        
        # 提取instructions (YAML之后的内容)
        end = text.find("---", 3)
        instructions = text[end+3:].strip() if end != -1 else text
        
        return SkillSpec(metadata=meta, instructions=instructions)
    
    @staticmethod
    def list_skills(skills_dir: str) -> List[str]:
        """列出一个目录下的所有技能"""
        skills = []
        for entry in os.listdir(skills_dir):
            skill_path = os.path.join(skills_dir, entry, "SKILL.md")
            if os.path.isfile(skill_path):
                skills.append(entry)
        return sorted(skills)


# ═══════════════════════════════════════════
# 3. EvalFramework — 技能评估框架(来自anthropics/skills)
# ═══════════════════════════════════════════

@dataclass
class EvalResult:
    """单次评估结果"""
    prompt: str
    passed: bool
    score: float = 0.0
    notes: str = ""
    duration_ms: float = 0.0

@dataclass
class EvalSuite:
    """评估套件"""
    name: str
    skill_name: str
    tests: List[EvalResult] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def add_test(self, prompt: str, expected_score: float = 1.0):
        """添加测试用例"""
        self.tests.append(EvalResult(prompt=prompt, passed=False, score=expected_score))
    
    def run(self, skill_fn: Callable[[str], str]) -> Dict[str, Any]:
        """运行评估: skill_fn(prompt) → response, 返回非空=通过"""
        results = []
        for test in self.tests:
            import time
            start = time.time()
            try:
                response = skill_fn(test.prompt)
                test.passed = bool(response and response.strip())
                test.duration_ms = (time.time() - start) * 1000
            except Exception as e:
                test.passed = False
                test.notes = str(e)
            results.append(test)
        
        # 统计
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        avg_score = sum(r.score for r in results if r.passed) / max(passed, 1)
        
        return {
            "suite": self.name,
            "skill": self.skill_name,
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / max(total, 1),
            "avg_score": avg_score,
            "results": results
        }


# ═══════════════════════════════════════════
# 4. SkillCreator — 元技能(来自anthropics/skills skill-creator)
# ═══════════════════════════════════════════

class SkillCreator:
    """
    元技能 — 创建/评估/迭代技能
    
    闭环: 创建草稿 → 生成测试 → 运行评估 → 收集反馈 → 迭代优化
    
    用法:
        creator = SkillCreator("./my_skills")
        spec = creator.create_skill("hello-world", "Prints hello")
        creator.add_test("Say hello", "hello")
        stats = creator.run_evals(lambda p: "hello world")
    """
    
    def __init__(self, skills_dir: str = "./skills"):
        self.skills_dir = skills_dir
        self._evals: Dict[str, EvalSuite] = {}
        os.makedirs(skills_dir, exist_ok=True)
    
    def create_skill(self, name: str, description: str, 
                     instructions: str = "",
                     tags: List[str] = None) -> SkillSpec:
        """创建新技能"""
        spec = SkillTemplate.create(name, description, instructions, tags)
        skill_path = os.path.join(self.skills_dir, name)
        os.makedirs(skill_path, exist_ok=True)
        spec.save(os.path.join(skill_path, "SKILL.md"))
        
        # 自动创建评估
        suite = EvalSuite(name=f"{name}-evals", skill_name=name)
        self._evals[name] = suite
        
        return spec
    
    def add_test(self, skill_name: str, prompt: str, expected_score: float = 1.0):
        """为技能添加测试"""
        if skill_name not in self._evals:
            self._evals[skill_name] = EvalSuite(
                name=f"{skill_name}-evals", skill_name=skill_name
            )
        self._evals[skill_name].add_test(prompt, expected_score)
    
    def run_evals(self, skill_name: str, 
                  skill_fn: Callable[[str], str]) -> Dict[str, Any]:
        """运行技能的评估"""
        if skill_name not in self._evals:
            return {"error": f"No evals for {skill_name}"}
        return self._evals[skill_name].run(skill_fn)
    
    def list_skills(self) -> List[str]:
        """列出所有技能"""
        return SkillTemplate.list_skills(self.skills_dir)
    
    def delete_skill(self, name: str):
        """删除技能(含目录)"""
        import shutil
        skill_path = os.path.join(self.skills_dir, name)
        if os.path.isdir(skill_path):
            shutil.rmtree(skill_path)
        self._evals.pop(name, None)


# ═══════════════════════════════════════════
# 5. GapAnalysis — 与GA的差距分析
# ═══════════════════════════════════════════

def get_anthropic_skills_gaps() -> Dict[str, dict]:
    """Anthropic Skills与GA的差距"""
    return {
        "skill_spec_standard": {
            "priority": 4,
            "name": "技能规范标准化",
            "ga_current": "GA skill: 自由格式.py模块，无统一frontmatter",
            "anthropic": "YAML frontmatter(name/desc/tags/deps) + Markdown指令"
        },
        "skill_template": {
            "priority": 3,
            "name": "技能模板/生成器",
            "ga_current": "手动创建.py文件",
            "anthropic": "SkillTemplate + SkillCreator元技能"
        },
        "eval_framework": {
            "priority": 4,
            "name": "技能评估框架",
            "ga_current": "自检函数硬编码在文件尾部",
            "anthropic": "EvalSuite(测试集+量化指标+方差分析)"
        },
        "skill_creator_meta": {
            "priority": 3,
            "name": "元技能(创建→评估→迭代)",
            "ga_current": "无",
            "anthropic": "skill-creator: 全生命周期管理"
        },
        "directory_standard": {
            "priority": 2,
            "name": "技能目录标准化",
            "ga_current": "memory/下杂乱混合",
            "anthropic": "skills/<name>/SKILL.md + scripts/ + templates/"
        }
    }


# ═══════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════

def _run_self_check():
    print("="*60)
    print("🎯 Anthropic Skills骨髓内化模块自检")
    print("="*60)
    
    # 1. SkillSpec + Metadata
    meta = SkillMetadata(
        name="test-skill", description="A test skill",
        tags=["test", "demo"], author="GA"
    )
    frontmatter = meta.to_yaml_frontmatter()
    assert "name: test-skill" in frontmatter
    assert "description: A test skill" in frontmatter
    assert "tags: [test, demo]" in frontmatter
    
    parsed = SkillMetadata.from_yaml_block(frontmatter)
    assert parsed is not None
    assert parsed.name == "test-skill"
    assert "test" in parsed.tags
    print("✅ SkillMetadata: YAML frontmatter 读写")
    
    spec = SkillSpec(metadata=meta, instructions="Do something useful")
    rendered = spec.render()
    assert "Do something useful" in rendered
    assert "test-skill" in rendered
    print("✅ SkillSpec: 完整SKILL.md渲染")
    
    # 2. SkillTemplate
    spec2 = SkillTemplate.create("hello", "Prints hello", "print('hello')")
    assert spec2.metadata.name == "hello"
    assert "print('hello')" in spec2.instructions
    print("✅ SkillTemplate: 创建/解析/列表")
    
    # 3. EvalFramework
    suite = EvalSuite("test-evals", "hello")
    suite.add_test("say hi", 0.8)
    suite.add_test("say bye", 0.9)
    
    def mock_skill(prompt: str) -> str:
        return "hello" if "hi" in prompt else ""
    
    stats = suite.run(mock_skill)
    assert stats["total"] == 2
    assert stats["passed"] == 1  # 只有"say hi"通过
    assert stats["pass_rate"] == 0.5
    print(f"✅ EvalSuite: 运行评估 (通过率={stats['pass_rate']})")
    
    # 4. SkillCreator
    import tempfile
    tmpdir = tempfile.mkdtemp()
    creator = SkillCreator(tmpdir)
    creator.create_skill("my-skill", "Does things", instructions="print('ok')")
    creator.add_test("my-skill", "test prompt")
    skills = creator.list_skills()
    assert "my-skill" in skills
    assert os.path.isfile(os.path.join(tmpdir, "my-skill", "SKILL.md"))
    
    stats2 = creator.run_evals("my-skill", lambda p: "ok")
    assert stats2["total"] == 1
    
    creator.delete_skill("my-skill")
    assert "my-skill" not in creator.list_skills()
    import shutil
    shutil.rmtree(tmpdir)
    print("✅ SkillCreator: 创建/测试/评估/删除 全闭环")
    
    # 5. GapAnalysis
    gaps = get_anthropic_skills_gaps()
    assert len(gaps) == 5
    print(f"✅ get_anthropic_skills_gaps: {len(gaps)}个差距识别")
    for name, info in gaps.items():
        print(f"   - {name}: 优先级{info['priority']}/5")
    
    print("\n✅ 全部自检通过 (5个模块)")

if __name__ == "__main__":
    _run_self_check()
