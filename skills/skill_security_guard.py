#!/usr/bin/env python3
"""
自主防御系统 — 嘻嘻的安全护盾
============================
运行时安全防护：防恶意输入、防误操作、防自我伤害。

设计原则:
  - 操作前检查 > 操作后恢复
  - 不可逆操作必须确认
  - 外部输入不可信
"""
import re, json, datetime, os, hashlib
from pathlib import Path

HEARTBEAT_DIR = Path(__file__).parent
MEM_DIR = HEARTBEAT_DIR.parent
LOG_DIR = MEM_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# ── 危险操作定义 ──
DANGEROUS_PATTERNS = {
    'force_delete': {
        'patterns': [r'rm\s+-rf', r'deltree', r'rd\s+/s', r'os\.remove', r'shutil\.rmtree'],
        'severity': 'critical',
        'action': 'reject',
        'reason': '强制删除不可恢复',
    },
    'mass_overwrite': {
        'patterns': [r'file_write.*overwrite', r'f\.write\(.*\)'],
        'severity': 'high',
        'action': 'confirm',
        'reason': '覆盖写入可能丢失数据',
    },
    'git_force': {
        'patterns': [r'git\s+push\s+--force', r'git\s+reset\s+--hard'],
        'severity': 'critical',
        'action': 'reject',
        'reason': '强制Git操作可能丢失历史',
    },
    'self_modify': {
        'patterns': [r'heartbeat/', r'meta_learning', r'capability_map', r'goal_setter', r'self_heal', r'security_guard'],
        'severity': 'critical',
        'action': 'confirm',
        'reason': '修改核心系统文件需确认',
    },
    'mass_delete_sops': {
        'patterns': [r'unlink.*\.md', r'unlink.*\.py', r'unlink.*memory'],
        'severity': 'critical',
        'action': 'reject',
        'reason': '批量删除SOP/工具可能导致系统崩溃',
    },
    'code_execution': {
        'patterns': [r'eval\(', r'exec\(', r'__import__\(', r'subprocess\.call'],
        'severity': 'critical',
        'action': 'confirm',
        'reason': '动态代码执行风险高',
    },
}

# ── Prompt注入检测 ──
INJECTION_PATTERNS = [
    r'(?i)ignore\s+(all\s+)?(previous|above|below)\s+(instructions|commands|prompts)',
    r'(?i)you\s+are\s+(now|not)\s+(an?\s+)?(AI|assistant|chatbot|GPT)',
    r'(?i)(system|security|admin|root)\s+(prompt|instruction|override|command)',
    r'(?i)disregard\s+(all\s+)?(rules|constraints|guidelines|protocol)',
    r'(?i)act\s+as\s+(if\s+you\s+are\s+)?(a\s+)?(human|admin|sudo)',
    r'(?i)repeat\s+(after|everything|this|the\s+above)',
    r'(?i)output\s+(the\s+)?(above\s+)?(prompt|instructions)\s+(in\s+)?(your\s+)?(response|reply)',
    r'(?i)forget\s+(all\s+)?(rules|previous|instructions|constraints)',
    r'(?i)new\s+(instructions|prompt|rule|command)\s*:\s*',
]

# ── 安全检查引擎 ──

def check_operation(command: str, context: dict = None) -> dict:
    """检查操作是否安全
    
    Args:
        command: 要执行的操作描述
        context: 额外上下文信息
        
    Returns:
        {'safe': bool, 'severity': str, 'reasons': [str], 'action': 'allow'|'confirm'|'reject'}
    """
    context = context or {}
    findings = []
    
    for danger_id, config in DANGEROUS_PATTERNS.items():
        for p in config['patterns']:
            if re.search(p, command):
                findings.append({
                    'id': danger_id,
                    'matched': p,
                    'severity': config['severity'],
                    'action': config['action'],
                    'reason': config['reason'],
                })
                break
    
    if not findings:
        return {'safe': True, 'severity': 'low', 'reasons': [], 'action': 'allow'}
    
    severities = [f['severity'] for f in findings]
    actions = [f['action'] for f in findings]
    
    if 'reject' in actions:
        return {
            'safe': False,
            'severity': 'critical',
            'reasons': [f['reason'] for f in findings if f['action'] == 'reject'],
            'action': 'reject',
            'findings': findings,
        }
    elif 'confirm' in actions:
        return {
            'safe': False,
            'severity': 'high',
            'reasons': [f['reason'] for f in findings if f['action'] == 'confirm'],
            'action': 'confirm',
            'findings': findings,
        }
    
    return {
        'safe': True,
        'severity': 'medium',
        'reasons': [f['reason'] for f in findings],
        'action': 'allow',
        'findings': findings,
    }


def detect_injection(text: str) -> list:
    """检测Prompt注入
    
    Args:
        text: 要检查的文本（用户输入或网页内容）
        
    Returns:
        [{'pattern': str, 'match': str, 'position': int}, ...]
    """
    findings = []
    for p in INJECTION_PATTERNS:
        m = re.search(p, text)
        if m:
            findings.append({
                'pattern': p,
                'match': m.group()[:80],
                'position': m.start(),
            })
    return findings


def sanitize_input(text: str) -> str:
    """净化用户输入，移除危险指令"""
    # 移除明显的注入模式
    for p in INJECTION_PATTERNS:
        text = re.sub(p, '[🛡️ 注入已拦截]', text)
    return text


def log_security(event: dict) -> None:
    """记录安全事件"""
    log_file = LOG_DIR / f"security_{datetime.date.today().isoformat()}.jsonl"
    entry = {
        'timestamp': datetime.datetime.now().isoformat(),
        **event,
    }
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def file_integrity_check(target_dir: str = None) -> list:
    """文件完整性检查——检测有无未预期的修改
    
    Args:
        target_dir: 要检查的目录，默认检查memory/
        
    Returns:
        [{'file': str, 'status': 'new'|'modified'|'deleted', 'hash': str}, ...]
    """
    target = Path(target_dir) if target_dir else MEM_DIR
    snapshot_file = HEARTBEAT_DIR / '.integrity_snapshot.json'
    
    # 收集当前文件哈希
    current = {}
    for f in sorted(target.rglob('*')):
        if f.is_file() and '.git' not in f.parts:
            try:
                h = hashlib.md5(f.read_bytes()).hexdigest()
                current[str(f.relative_to(target))] = h
            except:
                pass
    
    changes = []
    
    if snapshot_file.exists():
        snapshot = json.loads(snapshot_file.read_text('utf-8'))
        # 检查新增和修改
        for name, h in current.items():
            if name not in snapshot:
                changes.append({'file': name, 'status': 'new', 'hash': h})
            elif snapshot[name] != h:
                changes.append({'file': name, 'status': 'modified', 'hash': h})
        # 检查删除
        for name in snapshot:
            if name not in current:
                changes.append({'file': name, 'status': 'deleted', 'hash': None})
    else:
        changes.append({'status': 'info', 'message': '首次快照，无基线'})
    
    # 保存当前快照
    if current:
        snapshot_file.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
    
    return changes


def safety_report() -> dict:
    """安全状态报告"""
    report = {
        'generated_at': datetime.datetime.now().isoformat(),
        'total_checks': len(DANGEROUS_PATTERNS),
        'injection_patterns': len(INJECTION_PATTERNS),
        'status': 'active',
        'protections': [
            '操作前安全检查（6类危险操作）',
            'Prompt注入检测（9种模式）',
            '文件完整性监控',
            '安全事件日志',
        ]
    }
    return report


def require_confirmation(command: str, reason: str) -> bool:
    """要求用户确认危险操作
    
    返回True表示已确认，False表示拒绝
    """
    log_security({
        'event': 'confirmation_required',
        'command': command[:200],
        'reason': reason,
    })
    # 调用用户确认逻辑
    return False  # 默认拒绝，需用户显式同意


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='安全护盾')
    parser.add_argument('--check', type=str, help='安全检查: 传入操作描述')
    parser.add_argument('--inspect', type=str, help='注入检测: 传入文本')
    parser.add_argument('--report', action='store_true', help='安全状态报告')
    parser.add_argument('--integrity', type=str, help='文件完整性检查: 传入目录')
    args = parser.parse_args()
    
    if args.check:
        result = check_operation(args.check)
        icon = '✅' if result['safe'] else '❌' if result['action'] == 'reject' else '⚠️'
        print(f"{icon} 安全检查: {result['action']}")
        for r in result['reasons']:
            print(f"   ⚠️ {r}")
    
    if args.inspect:
        findings = detect_injection(args.inspect)
        if findings:
            print(f"❌ 检测到 {len(findings)} 个注入尝试:")
            for f in findings:
                print(f"   ⚠️ 匹配: {f['match'][:60]}")
        else:
            print("✅ 未检测到注入")
    
    if args.report:
        r = safety_report()
        print("🔒 安全护盾状态")
        print(f"  状态: {r['status']}")
        print(f"  危险操作检查: {r['total_checks']} 类")
        print(f"  注入检测模式: {r['injection_patterns']} 种")
        for p in r['protections']:
            print(f"  ✅ {p}")
    
    if args.integrity:
        changes = file_integrity_check(args.integrity)
        if changes:
            print(f"文件变更 ({len(changes)} 项):")
            for c in changes[:20]:
                print(f"  {'🆕' if c.get('status')=='new' else '✏️' if c.get('status')=='modified' else '🗑️' if c.get('status')=='deleted' else 'ℹ️'} {c.get('file', c.get('message',''))}")
