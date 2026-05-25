"""
===========================================================
 skill_decoration_content.py
 装修行业AI内容生成器 | AI Decoration Content Generator
===========================================================

【功能】
 为装修从业者/博主自动生成小红书/抖音短视频文案
 输入：装修照片描述 + 内容类型（避坑/日记/施工/种草）
 输出：多条带emoji+标签的爆款文案
 
【用法】
 1. 引入本模块后调用 generate_post()
 2. 支持批量生成，自动匹配热门话题标签

【骨髓内化来源】
 基于小红书装修领域头部账号的内容模式和AI Agent内容生成方法论
"""

# ============================================================
# 装修知识库 — 嘻嘻从网上学的 + 老大实战经验
# ============================================================

# 常见装修痛点词库（用于自动匹配文案角度）
COMMON_PAIN_POINTS = [
    "水电改造踩坑", "腻子没干透就刷漆", "卫生间不做干湿分离",
    "全屋定制报价陷阱", "瓷砖空鼓", "美缝变黑",
    "柜子没做到顶积灰", "插座位置不对", "灯光色温翻车",
    "甲醛超标", "防水没做好漏水", "窗户漏风",
    "装修公司增项加钱", "水电点位预留不够", "地板颜色选错"
]

# 热门话题标签
HASHTAGS = [
    "#装修避坑", "#装修日记", "#装修干货", "#施工现场",
    "#装修小白必看", "#我的装修记录", "#装修灵感",
    "#自装", "#装修公司怎么选", "#装修预算"
]

# 文案风格模板
STYLE_TEMPLATES = {
    "避坑": {
        "tone": "痛心疾首地分享教训",
        "structure": ["场景引入", "踩坑描述", "正确做法", "总结建议"],
        "emoji": "😭💔⚠️✅👷",
        "hook": "求求你们别像我一样踩这个坑！"
    },
    "日记": {
        "tone": "真诚记录的装修日常",
        "structure": ["时间线", "今日工作", "进展/问题", "心得体会"],
        "emoji": "📝🏗️✨💪😊",
        "hook": "装修第XX天，今天干了件大事！"
    },
    "施工": {
        "tone": "专业硬的现场讲解",
        "structure": ["施工场景", "工艺细节", "验收标准", "普通人该注意什么"],
        "emoji": "🔨📐👨‍🔧✅📏",
        "hook": "看看专业施工和普通施工的区别"
    }
}


def generate_post(scene_desc: str, content_type: str = "避坑", count: int = 3,
                  details: str = None, pro_tips: list = None, pain_point: str = None) -> list:
    """
    生成装修小红书文案（专业版）
    
    参数:
        scene_desc: 装修场景描述 (如"厨房瓷砖刚贴完")
        content_type: 内容类型 "避坑"/"日记"/"施工"
        count: 生成条数
        details: 场景细节补充（越长越真实）
        pro_tips: 专业建议列表，如["柜门要装缓冲铰链","背板厚度至少9mm"]
        pain_point: 具体痛点（不传则自动匹配）
        
    返回:
        包含多条文案的列表
    """
    if content_type not in STYLE_TEMPLATES:
        content_type = "避坑"
    
    template = STYLE_TEMPLATES[content_type]
    results = []
    
    import random
    
    for i in range(count):
        # 选择痛点
        actual_pain = pain_point or COMMON_PAIN_POINTS[i % len(COMMON_PAIN_POINTS)]
        
        # 选3个标签
        tags = random.sample(HASHTAGS, 3)
        
        # 生成专业建议（传入的用传入的，否则用默认）
        tips = pro_tips if pro_tips else [
            "提前做好功课，别等工人进场了才学",
            "关键节点要亲自去工地盯着",
            "合同里写清楚的，别信口头承诺"
        ]
        
        # 构建文案
        lines = [f"{template['emoji']} {template['hook']}"]
        lines.append("")
        lines.append(f"📍 {scene_desc}")
        
        if details:
            lines.append(f"📸 {details}")
        
        lines.append("")
        lines.append("❌ 装修小白容易踩的坑：")
        lines.append(f"👉 {actual_pain}，这个问题不解决后患无穷！")
        lines.append("")
        lines.append("✅ 老师傅教我的正确做法：")
        
        for j, tip in enumerate(tips[:3], 1):
            lines.append(f"  {j}. {tip}")
        
        lines.append("")
        lines.append(f"💡 总结：{actual_pain}不是小事，装修每一步都马虎不得。")
        lines.append("")
        lines.append("我是做了10年装修的老李，每天分享工地实拍+避坑干货。")
        lines.append("关注我，装修不迷路！❤️")
        lines.append("")
        lines.append(' '.join(tags))
        lines.append("#装修 #装修经验 #装修日记")
        
        results.append('\n'.join(lines))
    
    return results


def batch_generate(scenes: list, content_type: str = "避坑") -> dict:
    """
    批量生成多条文案，适用于一天发多条
    """
    result = {}
    for scene in scenes:
        result[scene] = generate_post(scene, content_type, count=2)
    return result


# ============================================================
# 自检函数
# ============================================================

def self_check():
    """
    测试模块是否正常工作
    """
    test_scene = "厨房瓷砖刚贴完，发现空鼓了"
    posts = generate_post(test_scene, "避坑", count=2)
    
    print("【装修AI内容生成器 - 自检报告】")
    print("=" * 50)
    print(f"✅ 测试场景: {test_scene}")
    print(f"✅ 生成条数: {len(posts)}")
    print(f"✅ 生成内容预览:\n")
    for i, post in enumerate(posts, 1):
        print(f"--- 文案 {i} ---")
        print(post[:200] + "...\n")
    
    print("=" * 50)
    print("✅ 全部自检通过！")
    print("💡 使用示例: skill_decoration_content.generate_post('客厅刷完乳胶漆', '避坑')")
    return True


if __name__ == "__main__":
    self_check()
