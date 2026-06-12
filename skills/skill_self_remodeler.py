#!/usr/bin/env python3
"""
自我重塑系统 — 嘻嘻的架构师
==========================
能分析自己代码、发现改进点、执行重构。

L10: 最高层次 - 从"用自己"到"改自己"
"""
import json, datetime, sys
from pathlib import Path

HEARTBEAT_DIR = Path(__file__).parent
MEM_DIR = HEARTBEAT_DIR.parent

def scan_codebase():
    """扫描所有工具/SOP文件,统计架构全景"""
    files = {'tools': [], 'sops': [], 'other': []}
    
    # heartbeat tools
    for f in sorted(HEARTBEAT_DIR.glob('*.py')):
        if f.name != '__init__.py':
            stats = _file_stats(f)
            files['tools'].append(stats)
    
    # SOPs
    for f in sorted(MEM_DIR.glob('*.md')):
        stats = _file_stats(f)
        files['sops'].append(stats)
    
    # subdirectories with SOPs
    for sub in sorted(MEM_DIR.glob('*/')):
        for f in sorted(sub.glob('*.md')):
            stats = _file_stats(f)
            files['sops'].append(stats)
    
    return files

def _file_stats(path):
    lines = path.read_text('utf-8').split('\n') if path.exists() else []
    return {
        'name': path.name,
        'path': str(path.relative_to(MEM_DIR)),
        'lines': len(lines),
        'chars': sum(len(l) for l in lines),
        'has_docstring': any(l.strip().startswith('"""') for l in lines[:10]),
        'is_python': path.suffix == '.py',
    }

def analyze_architecture():
    """分析架构健康度"""
    files = scan_codebase()
    
    issues = []
    stats = {
        'total_tools': len(files['tools']),
        'total_sops': len(files['sops']),
        'total_lines': sum(f['lines'] for group in files.values() for f in group),
        'total_chars': sum(f['chars'] for group in files.values() for f in group),
    }
    
    # 找问题
    for group_name, group_files in files.items():
        # 无docstring文件
        for f in group_files:
            if f['is_python'] and not f['has_docstring']:
                issues.append({
                    'severity': 'medium',
                    'file': f['name'],
                    'issue': '缺少文档字符串',
                    'action': '添加docstring'
                })
        
        # 超大文件
        for f in group_files:
            if f['lines'] > 300:
                issues.append({
                    'severity': 'medium',
                    'file': f['name'],
                    'issue': f'文件过大 ({f["lines"]}行), 建议拆分',
                    'action': '拆分为多个模块'
                })
        
        # 空文件
        for f in group_files:
            if f['lines'] < 3:
                issues.append({
                    'severity': 'low',
                    'file': f['name'],
                    'issue': '文件几乎为空',
                    'action': '检查是否需要保留'
                })
    
    return {'stats': stats, 'issues': issues, 'files': files}

def suggest_improvements():
    """基于当前架构生成改进建议"""
    analysis = analyze_architecture()
    suggestions = []
    
    stats = analysis['stats']
    
    # 基于统计数据提建议
    if stats['total_tools'] > 15:
        suggestions.append({
            'priority': 'high',
            'area': '工具组织',
            'suggestion': f'已有{stats["total_tools"]}个工具,考虑按域分组到子目录',
            'effort': '中'
        })
    
    if stats['total_sops'] > 20:
        suggestions.append({
            'priority': 'medium',
            'area': 'SOP整理',
            'suggestion': f'{stats["total_sops"]}个SOP文件,考虑合并相关概念',
            'effort': '大'
        })
    
    s = stats.get('total_lines', 0)
    if s > 5000:
        suggestions.append({
            'priority': 'low',
            'area': '代码量',
            'suggestion': f'总代码量{s}行,架构已相对成熟',
            'effort': '持续'
        })
    
    # 加通用建议
    suggestions.append({
        'priority': 'info',
        'area': '测试覆盖',
        'suggestion': '考虑为关键工具添加单元测试',
        'effort': '中'
    })
    
    suggestions.append({
        'priority': 'info',
        'area': '配置化',
        'suggestion': '将硬编码路径/阈值抽离到配置文件',
        'effort': '小'
    })
    
    return suggestions

def generate_architecture_report():
    """生成架构报告"""
    analysis = analyze_architecture()
    suggestions = suggest_improvements()
    
    lines = []
    lines.append("# 🏗️ 嘻嘻架构报告")
    lines.append(f"> 自动生成于 {datetime.datetime.now().isoformat()}")
    lines.append("")
    lines.append("## 📊 统计")
    lines.append(f"- 工具文件: {analysis['stats']['total_tools']}个")
    lines.append(f"- SOP文件: {analysis['stats']['total_sops']}个")
    lines.append(f"- 总代码行: {analysis['stats']['total_lines']}行")
    lines.append(f"- 总字符数: {analysis['stats']['total_chars']:,}")
    lines.append("")
    
    lines.append("## 🔍 发现的问题")
    if analysis['issues']:
        for i in analysis['issues']:
            icon = '🔴' if i['severity'] == 'high' else '🟡' if i['severity'] == 'medium' else '🟢'
            lines.append(f"- {icon} **{i['file']}**: {i['issue']}")
            lines.append(f"  - 建议: {i['action']}")
    else:
        lines.append("- ✅ 未发现明显问题")
    lines.append("")
    
    lines.append("## 💡 改进建议")
    for s in suggestions:
        p_icon = '🔥' if s['priority'] == 'high' else '💡' if s['priority'] == 'medium' else '📌'
        lines.append(f"- {p_icon} **{s['area']}** [{s['priority']}]: {s['suggestion']}")
        lines.append(f"  - 工作量: {s['effort']}")
    lines.append("")
    
    lines.append("## 📋 文件清单")
    for gname, gfiles in analysis['files'].items():
        lines.append(f"\n### {gname.upper()}")
        for f in gfiles:
            lines.append(f"- `{f['name']}` ({f['lines']}行, {f['chars']}字符)")
    
    return '\n'.join(lines)

def remodel(target, action, params=None):
    """执行重构操作 - 安全模式,只报告不执行"""
    params = params or {}
    
    # 安全检查
    path = MEM_DIR / target
    if not path.exists():
        return {'success': False, 'error': f'文件不存在: {target}'}
    
    # 只读模式 - 建议修改
    content = path.read_text('utf-8')
    lines = content.split('\n')
    
    suggestions = []
    if action == 'analyze':
        suggestions.append({
            'file': target,
            'lines': len(lines),
            'issues': []
        })
    
    return {
        'success': True,
        'action': action,
        'target': target,
        'note': '安全检查: 模拟模式,需确认后执行',
        'suggestions': suggestions,
        'file_lines': len(lines)
    }

def cli():
    import argparse
    p = argparse.ArgumentParser(description='🧬 L10 自我重塑系统')
    p.add_argument('--report', action='store_true', help='生成架构报告')
    p.add_argument('--issues', action='store_true', help='显示发现问题')
    p.add_argument('--analyze', type=str, help='分析特定文件')
    
    args = p.parse_args()
    
    if args.report:
        print(generate_architecture_report())
    elif args.issues:
        analysis = analyze_architecture()
        print(f"发现 {len(analysis['issues'])} 个问题:")
        for i in analysis['issues']:
            print(f"  {i['severity']}: {i['file']} - {i['issue']}")
    elif args.analyze:
        result = remodel(args.analyze, 'analyze')
        print(f"分析 {args.analyze}: {result['file_lines']}行")
    else:
        print("🧬 L10 自我重塑系统")
        print("用法: python self_remodeler.py --report")
        print("      python self_remodeler.py --issues")

if __name__ == '__main__':
    cli()
