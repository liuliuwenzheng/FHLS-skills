
"""
skill_on_demand_scheduler.py — P8 按需技能调度器（骨髓内化版）

核心哲学: 不把所有能力放上下文，按需精准匹配。
用法:
  from memory.skill_on_demand_scheduler import OnDemandScheduler
  sd = OnDemandScheduler()
  result = sd.dispatch("用浏览器搜索karpathy")
  print(sd.suggest("写电商文案"))
"""

import re
from typing import List, Dict, Optional, Tuple

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]+")
_ENGLISH_RE = re.compile(r"[a-zA-Z][a-z]{2,}")

def _tokenize(text: str) -> set:
    chinese = _CHINESE_RE.findall(text)
    english = _ENGLISH_RE.findall(text)
    return set(w.lower() for w in chinese) | set(w.lower() for w in english)

def _build_token_profile(text: str) -> Tuple[set, str]:
    """返回 (tokens, lower_text) 用于快速匹配"""
    return _tokenize(text), text.lower()


class OnDemandScheduler:
    """按需技能调度器 — 纯元数据匹配，不扫描文件系统。"""
    
    _registry = {}
    
    @classmethod
    def register(cls, name: str, core: str, tags: list, scenes: list, module: str):
        """注册一个技能"""
        cls._registry[name] = {
            "core": core,
            "tags": tags,
            "scenes": scenes,
            "module": module,
        }
    
    @classmethod
    def register_from_dict(cls, skills: dict):
        """批量注册"""
        for name, info in skills.items():
            cls.register(name, info["core"], info["tags"], info["scenes"], info["module"])
    
    def __init__(self):
        # 默认加载内置技能集
        if not self._registry:
            self._load_defaults()
        self._total = len(self._registry)
        # 预计算所有技能的token profile (加速)
        self._profiles = {}
        for name, info in self._registry.items():
            core_tokens, core_lower = _build_token_profile(info["core"])
            scene_tokens, _ = _build_token_profile(" ".join(info["scenes"]))
            all_text = " ".join(info["tags"] + info["scenes"])
            _, all_lower = _build_token_profile(all_text)
            self._profiles[name] = {
                "core_tokens": core_tokens,
                "scene_tokens": scene_tokens,
                "all_lower": all_lower,
                "name_lower": name.lower(),
            }

    def match(self, task: str, top_k: int = 3) -> List[Tuple[str, float, str]]:
        """
        多路加权匹配:
          tag精确匹配: +5/命中 (最重要的语义分类)
          scene token交: +2/词 (场景定位)
          core token交: +1/词 (广覆盖)
          name精确: +8 (精准命中)
          tag子串: +3 (部分匹配)
        """
        task_lower = task.lower()
        task_tokens = _tokenize(task_lower)
        
        scored = []
        for name, info in self._registry.items():
            score = 0.0
            prof = self._profiles.get(name, {})
            
            # 1. tag匹配 (精确+子串)
            for tag in info["tags"]:
                tag_l = tag.lower()
                if tag_l in task_lower:
                    score += 5.0
                # tag是任务token的一部分
                if tag_l in task_tokens:
                    score += 3.0
            
            # 2. scene匹配
            for scene in info["scenes"]:
                s_tokens = _tokenize(scene.lower())
                overlap = task_tokens & s_tokens
                score += len(overlap) * 2.0
            
            # 3. core匹配
            core_overlap = task_tokens & (prof.get("core_tokens") or set())
            score += len(core_overlap) * 1.0
            
            # 4. name精准匹配
            name_l = prof.get("name_lower", name.lower())
            if name_l in task_lower:
                score += 8.0
            if task_lower in name_l:
                score += 4.0
            
            if score > 0:
                scored.append((name, score, info["core"]))
        
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:top_k]

    def dispatch(self, task: str, top_k: int = 3) -> dict:
        matched = self.match(task, top_k=top_k)
        return {
            "task": task,
            "matched_skills": [
                {
                    "name": name,
                    "score": round(score, 1),
                    "module": self._registry[name]["module"],
                    "core": self._registry[name]["core"][:80],
                }
                for name, score, _ in matched
            ],
            "total_skills": self._total,
            "loaded": len(matched),
            "load_ratio": f"{len(matched)}/{self._total}",
        }

    def suggest(self, task: str, top_k: int = 3) -> str:
        matched = self.match(task, top_k=top_k)
        if not matched:
            return ""
        lines = ["[SkillDispatch] 基于当前任务推荐:"] + [
            f"  . {name} ({score}pts): {core[:60]}..."
            for name, score, core in matched
        ]
        return "\n".join(lines)

    def _load_defaults(self):
        """加载内置技能集"""
        from .skill_on_demand_data import ALL_SKILLS
        self.register_from_dict(ALL_SKILLS)


# 快捷函数
def schedule_skills(task: str) -> str:
    return OnDemandScheduler().suggest(task)

def skill_dispatch(task: str) -> dict:
    return OnDemandScheduler().dispatch(task)


if __name__ == "__main__":
    sd = OnDemandScheduler()
    test_tasks = [
        "用浏览器搜索GitHub上karpathy的nanoGPT项目",
        "生成一份小红书风格的PDF笔记",
        "搭建一个微信机器人连接AI",
        "做电商运营数据分析",
        "写一个MCP Server连接外部工具",
        "系统学习量化交易策略",
        "我需要GA自我改进",
        "帮我分析这个商业问题",
        "做一个AI微信机器人自动回复",
        "在浏览器里打开百度搜索",
        "帮我规划学习路径",
    ]
    for task in test_tasks:
        print("\n" + "=" * 60)
        print(f"\U0001f4cb 任务: {task}")
        result = sd.dispatch(task)
        for s in result["matched_skills"]:
            print(f"  \u2713 {s['name']} ({s['score']}pts) \u2192 {s['module']}")
        print(f"  \U0001f4ca  {result['load_ratio']}")
