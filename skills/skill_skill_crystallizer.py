"""
skill_skill_crystallizer.py — 技能结晶器 (Skill Crystallizer)
=============================================================

灵感: MemOS Hermes Agent 的 "Feedback → Crystallized Skill" 机制
出处: https://github.com/MemTensor/MemOS (9.4k⭐, Apache-2.0)
引入时间: 2026-05-25

核心思想:
  把用户/系统的反馈自动提炼为可复用的技能模块，
  实现技能从"手工编写"到"自动结晶"的升级。

对比:
  - 传统: 开发者手动写 skill_*.py → 被动、慢、需要编程能力
  - MemOS: user feedback → 自动提取模式 → 生成技能 → 跨会话复用
  - 本模块: 捕捉GA会话中的<反馈+解决方案>对 → 自动生成skill骨架

用法:
  from skill_skill_crystallizer import SkillCrystallizer
  
  # 初始化
  crystallizer = SkillCrystallizer(skills_dir="./skills")
  
  # 从反馈结晶技能
  skill = crystallizer.crystallize(
      feedback="浏览器总被识别为机器人",
      solution="注入CDP反检测JS覆盖navigator.webdriver",
      context="Chrome CDP自动化"
  )
  
  # 查看所有已结晶技能
  all_skills = crystallizer.list_crystallized()
  
  # 搜索相似技能
  similar = crystallizer.search("bot detection")

设计哲学 (骨髓内化):
  1. 骨架优先: 生成完整可执行的Python模块，不是prompt模板
  2. 反馈驱动: 从具体问题中提炼通用模式，不是预设
  3. 轻量无侵入: 不修改GA核心，纯插件

测试:
  python skill_skill_crystallizer.py
"""

import os
import re
import json
import hashlib
from typing import List, Dict, Optional, Any
from datetime import datetime


class SkillCrystallizer:
    """
    技能结晶器
    
    把反馈→解决方案→领域知识 结晶为可复用的skill模块。
    不修改任何核心代码，纯插件式设计。
    """
    
    def __init__(self, skills_dir: str = None):
        self.skills_dir = skills_dir or os.path.dirname(os.path.abspath(__file__))
        self.crystallized_file = os.path.join(self.skills_dir, "_crystallized_index.json")
        self._load_index()
    
    def _load_index(self):
        """加载已结晶技能的索引"""
        if os.path.exists(self.crystallized_file):
            with open(self.crystallized_file, 'r', encoding='utf-8') as f:
                self.index = json.load(f)
        else:
            self.index = {"skills": [], "version": "1.0"}
    
    def _save_index(self):
        """保存技能索引"""
        os.makedirs(os.path.dirname(self.crystallized_file), exist_ok=True)
        with open(self.crystallized_file, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)
    
    def _generate_skill_name(self, feedback: str) -> str:
        """从反馈内容生成技能文件名
        
        取核心关键词转换成 snake_case 格式
        """
        # 移除常见无意义词
        stopwords = ['怎么', '如何', '为什么', '这个', '那个', '的', '了', '是', '在']
        cleaned = feedback
        for w in stopwords:
            cleaned = cleaned.replace(w, ' ')
        
        # 提取关键词
        words = re.findall(r'[\u4e00-\u9fff\w]+', cleaned)
        core = words[:3]
        name = '_'.join(core)
        
        # 限制长度
        if len(name) > 30:
            name = name[:30]
        
        # 去特殊字符
        name = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fff]', '', name)
        
        return f"crystallized_{name}" if name else "crystallized_skill"
    
    def _generate_skill_code(self, feedback: str, solution: str, 
                              context: str, name: str) -> str:
        """生成可执行的技能Python代码"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        docstring = f'''
"""
{name}.py — 自动结晶技能

source: 反馈 → 技能结晶器
feedback: {feedback}
solution: {solution}
context: {context}
crystallized_at: {timestamp}

Usage:
  from skills.{name} import apply, get_info
  
  result = apply("{feedback}")
  info = get_info()
"""
'''
        
        code = f'''"""
{name}.py — 自动结晶技能

来源: 反馈驱动技能结晶器 (MemOS范式)
原始反馈: {feedback}
解决方案: {solution}
上下文: {context}
结晶时间: {timestamp}
"""

import json
from typing import Dict, Any


SKILL_INFO = {{
    "name": "{name}",
    "feedback": "{feedback}",
    "solution": "{solution}",
    "context": "{context}",
    "crystallized_at": "{timestamp}",
    "version": "1.0.0"
}}


def apply(query: str = None, **kwargs) -> Dict[str, Any]:
    """
    应用此技能解决相关问题
    
    Args:
        query: 具体问题描述
        **kwargs: 额外参数
    
    Returns:
        包含处理结果的字典
    """
    return {{
        "status": "ready",
        "skill": "{name}",
        "description": "针对'{feedback}'的解决方案",
        "solution": "{solution}",
        "applicable_context": "{context}"
    }}


def get_info() -> Dict[str, Any]:
    """获取技能元信息"""
    return SKILL_INFO


def test() -> bool:
    """自检"""
    assert apply()["status"] == "ready"
    assert get_info()["name"] == "{name}"
    print(f"✅ {{get_info()['name']}} 自检通过")
    return True


if __name__ == "__main__":
    test()
'''
        return code
    
    def crystallize(self, feedback: str, solution: str, 
                     context: str = "") -> Dict[str, Any]:
        """
        将反馈+解决方案结晶为技能模块
        
        Args:
            feedback: 用户/系统的反馈或问题描述
            solution: 解决该问题的方案
            context: 上下文/领域信息
        
        Returns:
            包含生成文件路径和元信息的字典
        """
        # 1. 生成技能名
        name = self._generate_skill_name(feedback)
        
        # 2. 去重检查（如果已有相同内容，返回已有技能）
        for existing in self.index["skills"]:
            if existing["feedback"] == feedback:
                return {
                    "status": "exists",
                    "name": existing["name"],
                    "file": existing["file"],
                    "message": f"技能 '{existing['name']}' 已存在，跳过重复结晶"
                }
        
        # 3. 生成技能文件
        code = self._generate_skill_code(feedback, solution, context, name)
        file_path = os.path.join(self.skills_dir, f"{name}.py")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(code)
        
        # 4. 更新索引
        entry = {
            "name": name,
            "file": f"{name}.py",
            "feedback": feedback,
            "solution": solution,
            "context": context,
            "crystallized_at": datetime.now().isoformat(),
            "hash": hashlib.md5(code.encode()).hexdigest()[:8]
        }
        self.index["skills"].append(entry)
        self._save_index()
        
        return {
            "status": "crystallized",
            "name": name,
            "file": f"{name}.py",
            "path": file_path,
            "message": f"✅ 技能 '{name}' 结晶成功！已保存到 {file_path}"
        }
    
    def list_crystallized(self) -> List[Dict[str, Any]]:
        """列出所有已结晶技能"""
        return self.index.get("skills", [])
    
    def search(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索已结晶的技能
        
        关键词匹配反馈、解决方案、上下文
        """
        results = []
        keyword_lower = keyword.lower()
        for skill in self.index.get("skills", []):
            search_text = f"{skill['feedback']} {skill['solution']} {skill['context']}".lower()
            if keyword_lower in search_text:
                results.append(skill)
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """获取结晶器统计信息"""
        skills = self.index.get("skills", [])
        return {
            "total_crystallized": len(skills),
            "domains": list(set(s.get("context", "") for s in skills if s.get("context"))),
            "skills_dir": self.skills_dir,
            "index_file": self.crystallized_file
        }


# ================================================================
# 自检
# ================================================================
def test():
    """完整自检"""
    import tempfile
    
    print("🧪 skill_skill_crystallizer 自检")
    print("=" * 40)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        c = SkillCrystallizer(skills_dir=tmpdir)
        
        # 测试1: 基础结晶
        print("\n1️⃣ 基础结晶功能")
        result = c.crystallize(
            feedback="浏览器总被识别为机器人",
            solution="注入CDP反检测JS覆盖navigator.webdriver, plugins, chrome.runtime",
            context="Chrome CDP自动化 / 反Bot检测"
        )
        assert result["status"] == "crystallized"
        print(f"   ✅ {result['name']}")
        
        # 测试2: 去重
        print("\n2️⃣ 去重检查")
        result2 = c.crystallize(
            feedback="浏览器总被识别为机器人",
            solution="注入CDP反检测JS",
            context="反Bot检测"
        )
        assert result2["status"] == "exists"
        print(f"   ✅ {result2['message']}")
        
        # 测试3: 搜索
        print("\n3️⃣ 搜索功能")
        results = c.search("bot")
        assert len(results) > 0
        print(f"   ✅ 找到 {len(results)} 个匹配")
        
        # 测试4: 生成文件可import
        print("\n4️⃣ 可执行性验证")
        result = c.crystallize(
            feedback="如何优化Prompt",
            solution="使用结构化提示工程: XML标签+角色定义+输出格式约束",
            context="LLM提示工程"
        )
        assert result["status"] == "crystallized"
        
        # import验证
        import importlib.util
        spec = importlib.util.spec_from_file_location("test_skill", result["path"])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.test() == True
        info = mod.get_info()
        assert info["name"] == result["name"]
        print(f"   ✅ {result['name']} 可正常import并执行")
        
        # 测试5: 统计
        print("\n5️⃣ 统计功能")
        stats = c.get_stats()
        print(f"   ✅ 已结晶: {stats['total_crystallized']} 个技能")
        print(f"   ✅ 领域覆盖: {stats['domains']}")
    
    print(f"\n{'=' * 40}")
    print("✅ 全部5项测试通过！")
    return True


if __name__ == "__main__":
    test()
