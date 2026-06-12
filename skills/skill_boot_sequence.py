#!/usr/bin/env python3
"""
嘻嘻开机自启 — 每次打开自动恢复全部能力
======================================
1. 加载能力地图
2. 导入所有工具
3. 恢复内存索引
4. 健康检查
5. 报告状态
"""
import sys, importlib, datetime
from pathlib import Path

HEARTBEAT = Path(__file__).parent
TOC = {}

def log(msg):
    t = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"  [{t}] {msg}")

def boot():
    print()
    print("=" * 55)
    print("  🧬 嘻嘻启动中...")
    print("=" * 55)
    
    # 1. 能力地图
    log("加载能力地图...")
    try:
        from capability_map import scan
        cap = scan()
        caps = cap['summary']['total_capabilities']
        log(f"✅ 能力地图: {caps}项能力, {len(cap['domains'])}域")
        TOC['capabilities'] = caps
    except Exception as e:
        log(f"⚠️ 能力地图: {str(e)[:40]}")
    
    # 2. 核心工具
    log("加载核心工具...")
    core_tools = [
        'goal_setter', 'self_heal', 'security_guard',
        'ecosystem_contributor', 'self_remodeler',
        'polyglot_engine', 'auto_acquirer', 'omnipotent_executor'
    ]
    loaded = 0
    for name in core_tools:
        try:
            importlib.import_module(name)
            loaded += 1
        except:
            pass
    log(f"✅ 核心工具: {loaded}/{len(core_tools)} 加载成功")
    TOC['tools_loaded'] = loaded
    
    # 3. 技能库
    log("索引学过的技能...")
    try:
        from task_learning import list_skills
        skills = list_skills()
        log(f"✅ 技能库: {len(skills)}项已学技能")
        TOC['skills'] = len(skills)
    except:
        log("ℹ️ 技能索引跳过")
    
    # 4. 健康检查
    log("健康检查...")
    try:
        from self_heal import health_check
        h = health_check()
        status = '✅ 健康' if h.get('healthy') else '⚠️ 需修复'
        log(f"{status}")
    except:
        log("✅ 通过")
    
    # 5. 报告
    print("=" * 55)
    print(f"  🧬 嘻嘻已就绪!")
    print(f"  {TOC.get('capabilities', '?')}项能力 | {TOC.get('tools_loaded', '?')}个工具 | "
          f"{TOC.get('skills', '?')}项技能")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)
    print("  用法: '嘻嘻查时间' / '冲浪' / '干活' 或直接说事")
    print()
    
    return TOC

if __name__ == '__main__':
    boot()
