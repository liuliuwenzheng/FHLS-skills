#!/usr/bin/env python3
"""
生态贡献系统 — 嘻嘻的知识创造者
==============================
把嘻嘻学到的东西变成可分享、可复用的知识产品。

能力:
  - 生成能力清单/简历
  - 打包技能为独立文档
  - 生成今日学习简报
  - 创建知识图谱
"""
import json, datetime, sys
from pathlib import Path

HEARTBEAT_DIR = Path(__file__).parent
MEM_DIR = HEARTBEAT_DIR.parent
OUTPUT_DIR = MEM_DIR / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

def generate_capability_resume() -> str:
    """生成嘻嘻能力简历——markdown格式"""
    import sys
    sys.path.insert(0, str(HEARTBEAT_DIR))
    from capability_map import scan
    
    result = scan()
    
    lines = []
    lines.append("# 🧬 嘻嘻能力简历")
    lines.append(f"> 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 能力总数: {result['summary']['total_capabilities']}项")
    lines.append("")
    
    for d in result['domains']:
        icon = {'mature': '🟢', 'developing': '🟡', 'nascent': '🟠', 'empty': '🔴'}
        m = icon.get(d['maturity'], '⚪')
        lines.append(f"## {d['icon']} {d['name']} {m} {d['maturity']}")
        lines.append(f"")
        lines.append(f"- **成熟度**: {d['n_total']}/{d['n_expected']} 文件")
        
        all_items = []
        for t in d['tools']:
            all_items.append(f"  - 🛠️ `{t['name']}`")
        for s in d['sops']:
            all_items.append(f"  - 📄 `{s['name']}`")
        
        if all_items:
            lines.append("")
            lines.extend(all_items)
        lines.append("")
    
    lines.append("---")
    lines.append("*由嘻嘻自主生成*")
    
    return '\n'.join(lines)


def generate_daily_brief() -> str:
    """生成今日学习简报"""
    import sys
    sys.path.insert(0, str(HEARTBEAT_DIR))
    
    # 读学习日志
    log_file = HEARTBEAT_DIR / 'learning_log.json'
    sessions = []
    if log_file.exists():
        try:
            data = json.loads(log_file.read_text('utf-8'))
            sessions = data.get('sessions', [])[-5:]  # 最近5条
        except:
            pass
    
    # 读当前目标
    goals_file = HEARTBEAT_DIR / 'goals.json'
    goals = []
    if goals_file.exists():
        try:
            data = json.loads(goals_file.read_text('utf-8'))
            goals = [g for g in data.get('goals', []) if g.get('status') == 'active']
        except:
            pass
    
    from capability_map import scan
    result = scan()
    
    lines = []
    lines.append(f"# 📋 嘻嘻学习简报 · {datetime.date.today().isoformat()}")
    lines.append("")
    lines.append("## 📊 能力状态")
    for d in result['domains']:
        ic = '🟢' if d['maturity'] == 'mature' else '🟡' if d['maturity'] == 'developing' else '🟠'
        lines.append(f"- {d['icon']} {d['name']}: {ic} ({d['n_total']}/{d['n_expected']})")
    lines.append(f"\n**总计**: {result['summary']['total_capabilities']}项能力")
    
    if sessions:
        lines.append("\n## 🎯 学习记录")
        effs = []
        for s in sessions:
            e = s.get('efficiency', 0)
            effs.append(int(str(e).replace('%', '')) if isinstance(e, str) else int(e))
        avg_eff = sum(effs) / len(effs)
        lines.append(f"- 近期平均效率: {avg_eff:.0f}%")
        for s in sessions[-3:]:
            e = s.get('efficiency', 0)
            eff = int(str(e).replace('%', '')) if isinstance(e, str) else int(e)
            ic = '🟢' if eff >= 85 else '🟡' if eff >= 70 else '🔴'
            lines.append(f"  {ic} {s.get('name', '?')} ({eff}%)")
    
    if goals:
        lines.append("\n## 🎯 活跃目标")
        for g in goals:
            lines.append(f"- {g.get('title', '?')}")
    
    lines.append(f"\n\n*自动生成于 {datetime.datetime.now().isoformat()}*")
    
    return '\n'.join(lines)


def export_skill_tree() -> str:
    """生成技能树——按类别组织所有已学技能"""
    
    # 读技能库
    skills_file = MEM_DIR / 'skill_search'
    skills = []
    if skills_file.exists():
        if skills_file.is_dir():
            for f in sorted(skills_file.glob('*.json')):
                try:
                    skills.append(json.loads(f.read_text('utf-8')))
                except:
                    pass
    
    from capability_map import CAPABILITY_DOMAINS
    
    lines = []
    lines.append("# 🌳 嘻嘻技能树")
    lines.append(f"> 已学技能: {len(skills)}项")
    lines.append("")
    
    # 按领域分组
    domain_map = {d['id']: d['name'] for d in CAPABILITY_DOMAINS}
    
    by_domain = {}
    for s in skills:
        cat = s.get('category', 'uncategorized')
        if cat not in by_domain:
            by_domain[cat] = []
        by_domain[cat].append(s)
    
    for domain_id, domain_name in domain_map.items():
        domain_skills = [s for s in skills if s.get('category') == domain_id or 
                        any(t.lower() == domain_id for t in s.get('tags', []))]
        
        if not domain_skills:
            continue
            
        lines.append(f"## {domain_name}")
        for s in domain_skills:
            lines.append(f"- **{s.get('task', '?')}**")
            desc = s.get('insights', '')[:80]
            if desc:
                lines.append(f"  - {desc}...")
            tags = s.get('tags', [])
            if tags:
                lines.append(f"  - `{'` `'.join(tags[:4])}`")
        lines.append("")
    
    return '\n'.join(lines)


def generate_all() -> dict:
    """生成所有知识产品"""
    outputs = {}
    
    # 能力清单
    resume = generate_capability_resume()
    resume_path = OUTPUT_DIR / 'capability_resume.md'
    resume_path.write_text(resume, encoding='utf-8')
    outputs['capability_resume'] = str(resume_path)
    
    # 学习简报
    brief = generate_daily_brief()
    brief_path = OUTPUT_DIR / f'daily_brief_{datetime.date.today().isoformat()}.md'
    brief_path.write_text(brief, encoding='utf-8')
    outputs['daily_brief'] = str(brief_path)
    
    # 技能树
    tree = export_skill_tree()
    tree_path = OUTPUT_DIR / 'skill_tree.md'
    tree_path.write_text(tree, encoding='utf-8')
    outputs['skill_tree'] = str(tree_path)
    
    return outputs


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='知识生态贡献')
    parser.add_argument('--resume', action='store_true', help='生成能力简历')
    parser.add_argument('--brief', action='store_true', help='生成学习简报')
    parser.add_argument('--tree', action='store_true', help='生成技能树')
    parser.add_argument('--all', action='store_true', help='生成全部')
    args = parser.parse_args()
    
    if args.all or not (args.resume or args.brief or args.tree):
        outputs = generate_all()
        print("📦 知识包已生成:")
        for name, path in outputs.items():
            print(f"  ✅ {name}: {path}")
    else:
        if args.resume:
            print(generate_capability_resume())
        if args.brief:
            print(generate_daily_brief())
        if args.tree:
            print(export_skill_tree())
