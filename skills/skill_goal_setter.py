#!/usr/bin/env python3
"""
自主目标系统 — 嘻嘻的进化方向盘
==============================
基于能力地图+学习历史，自主生成进化目标。

用法:
  python goal_setter.py              # 生成并显示当前目标
  python goal_setter.py --decide     # 决策：现在该做什么
  python goal_setter.py --complete <id>  # 标记目标完成
"""
import json, datetime, os, sys
from pathlib import Path

HEARTBEAT_DIR = Path(__file__).parent
MEM_DIR = HEARTBEAT_DIR.parent
GOALS_PATH = HEARTBEAT_DIR / 'goals.json'

# ── 目标模板 ──
GOAL_TEMPLATES = {
    "deepen_mature": {
        "title": "深化{name}: 从🟢成熟→🔵精通",
        "desc": "当前{name}已成熟({n_total}/{n_expected})，突破现有边界",
        "effort": "高",
        "value": "中"
    },
    "upgrade_developing": {
        "title": "升级{name}: 从🟡发展中→🟢成熟",
        "desc": "补齐{name}({n_total}/{n_expected})的缺失组件",
        "effort": "低",
        "value": "高"
    },
    "new_capability": {
        "title": "新增能力: {name}",
        "desc": "当前{name}空白/初期，从零构建",
        "effort": "中",
        "value": "高"
    },
    "meta_optimize": {
        "title": "优化学习效率",
        "desc": "当前学习效率{eff}%，目标是85%+",
        "effort": "中",
        "value": "中"
    },
    "explore_frontier": {
        "title": "探索{name}前沿",
        "desc": "在成熟域{name}中寻找新突破点",
        "effort": "高",
        "value": "中"
    }
}

def load_goals():
    if GOALS_PATH.exists():
        try:
            return json.loads(GOALS_PATH.read_text('utf-8'))
        except:
            pass
    return {"goals": [], "history": []}

def save_goals(data):
    GOALS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def generate_goals():
    """基于能力地图+学习历史自动生成目标"""
    # 导入能力地图
    sys.path.insert(0, str(HEARTBEAT_DIR))
    from capability_map import scan
    cap = scan()
    
    # 导入学习日志
    from meta_learning import load_log
    log = load_log()
    
    goals = load_goals()
    new_goals = []
    
    # 1. 升级发展中域
    for d in cap['domains']:
        if d['maturity'] == 'developing':
            tpl = GOAL_TEMPLATES['upgrade_developing']
            new_goals.append({
                "id": f"G{datetime.datetime.now().strftime('%H%M%S')}_{d['id']}",
                "type": "upgrade",
                "domain": d['name'],
                "title": tpl['title'].format(**d),
                "desc": tpl['desc'].format(**d),
                "effort": tpl['effort'],
                "value": tpl['value'],
                "status": "active",
                "created": datetime.datetime.now().isoformat()[:19],
                "source": "capability_gap"
            })
    
    # 2. 如果有缺口
    for g in cap.get('gaps', []):
        new_goals.append({
            "id": f"G{datetime.datetime.now().strftime('%H%M%S')}_gap",
            "type": "fill_gap",
            "domain": g['domain'],
            "title": f"填补缺口: {g['issue'][:50]}",
            "desc": g.get('suggestion', ''),
            "effort": "高" if '🔴' in g['severity'] else "中",
            "value": "高",
            "status": "active",
            "created": datetime.datetime.now().isoformat()[:19],
            "source": "gap_analysis"
        })
    
    # 3. 学习效率优化
    m = log.get('metrics', {})
    total = m.get('total_turns', 0)
    if total > 0:
        eff = m.get('successful_turns', 0) / total * 100
        if eff < 85:
            tpl = GOAL_TEMPLATES['meta_optimize']
            new_goals.append({
                "id": f"G{datetime.datetime.now().strftime('%H%M%S')}_meta",
                "type": "meta",
                "domain": "学习效率",
                "title": tpl['title'],
                "desc": tpl['desc'].format(eff=f"{eff:.0f}%"),
                "effort": tpl['effort'],
                "value": tpl['value'],
                "status": "active",
                "created": datetime.datetime.now().isoformat()[:19],
                "source": "meta_analysis"
            })
    
    # 替换旧目标
    goals['goals'] = new_goals
    save_goals(goals)
    return new_goals

def decide_next():
    """决策：现在最该做什么"""
    goals = generate_goals()
    
    if not goals:
        print("🎯 当前没有待办目标，建议探索新领域")
        return None
    
    # 优先级排序：value高 > effort低 > type
    def priority(g):
        v_map = {"高": 3, "中": 2, "低": 1}
        e_map = {"低": 3, "中": 2, "高": 1}
        return v_map.get(g['value'], 0) * 2 + e_map.get(g['effort'], 0)
    
    goals.sort(key=priority, reverse=True)
    top = goals[0]
    
    print(f"🎯 自主决策: 最该做 → {top['title']}")
    print(f"   领域: {top['domain']} | 价值: {top['value']} | 耗时: {top['effort']}")
    print(f"   理由: {top['desc']}")
    return top

def show_goals():
    goals = load_goals()
    active = [g for g in goals['goals'] if g['status'] == 'active']
    
    if not active:
        print("📋 当前目标: 无 (所有能力已成熟)")
        return
    
    print(f"📋 当前目标 ({len(active)} 项):")
    for g in sorted(active, key=lambda x: x.get('created', ''), reverse=True):
        print(f"  [{g['id']}] {g['title']}")
        print(f"        价值:{g['value']} 耗时:{g['effort']} 来源:{g.get('source','?')}")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--decide', action='store_true')
    parser.add_argument('--show', action='store_true')
    parser.add_argument('--complete', type=str, help='目标ID')
    args = parser.parse_args()
    
    if args.decide:
        decide_next()
    elif args.complete:
        goals = load_goals()
        for g in goals['goals']:
            if g['id'] == args.complete:
                g['status'] = 'completed'
                g['completed_at'] = datetime.datetime.now().isoformat()[:19]
                goals['history'].append(g)
                break
        goals['goals'] = [g for g in goals['goals'] if g['status'] != 'completed']
        save_goals(goals)
        print(f"✅ 目标完成: {args.complete}")
    else:
        show_goals()
        if not [g for g in load_goals()['goals'] if g['status'] == 'active']:
            # 没目标时自动生成
            print("\n(自动生成新目标...)")
            decide_next()
