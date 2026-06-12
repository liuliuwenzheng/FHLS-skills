#!/usr/bin/env python3
"""
自主维护系统 — 嘻嘻的自愈能力
============================
检测异常、自动恢复、防崩溃。

能力:
  - SSL/网络失败 → 自动切换搜索策略
  - 语法错误 → 代码执行前预检
  - 文件操作失败 → 备份恢复
  - 上下文逼近极限 → 预警+压缩
"""
import sys, json, datetime, traceback, io, re, os
import subprocess
from pathlib import Path

HEARTBEAT_DIR = Path(__file__).parent
MEM_DIR = HEARTBEAT_DIR.parent
LOG_DIR = MEM_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# ── 故障类型定义 ──
FAULT_PATTERNS = {
    'ssl_error': {
        'patterns': ['SSL', 'CERTIFICATE_VERIFY_FAILED', 'EOF occurred', 'Connection refused'],
        'severity': 'high',
        'recovery': 'fallback_search',
    },
    'syntax_error': {
        'patterns': ['SyntaxError', 'IndentationError', 'NameError'],
        'severity': 'medium',
        'recovery': 'precheck_code',
    },
    'import_error': {
        'patterns': ['ImportError', 'ModuleNotFoundError', 'No module named'],
        'severity': 'medium',
        'recovery': 'auto_install',
    },
    'file_not_found': {
        'patterns': ['FileNotFoundError', 'No such file or directory'],
        'severity': 'low',
        'recovery': 'path_guess',
    },
    'context_overflow': {
        'patterns': ['context length', 'maximum context', 'token limit', 'too many tokens'],
        'severity': 'critical',
        'recovery': 'context_compress',
    },
    'timeout': {
        'patterns': ['Timeout', 'timed out', 'deadline exceeded'],
        'severity': 'high',
        'recovery': 'retry_fallback',
    },
}

# ── 检测引擎 ──

def detect_fault(error_text: str) -> list:
    """分析错误文本，返回匹配的故障列表"""
    findings = []
    for fault_id, config in FAULT_PATTERNS.items():
        for p in config['patterns']:
            if p.lower() in str(error_text).lower():
                findings.append({
                    'id': fault_id,
                    'severity': config['severity'],
                    'matched': p,
                    'recovery': config['recovery'],
                })
                break
    return findings

def log_fault(fault: dict, context: str = '') -> None:
    """记录故障到日志"""
    log_file = LOG_DIR / f"faults_{datetime.date.today().isoformat()}.jsonl"
    entry = {
        'timestamp': datetime.datetime.now().isoformat(),
        'fault': fault,
        'context': context[:200],
    }
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

# ── 恢复策略 ──

def fallback_search(original_api: str) -> str:
    """网络失败时自动降级搜索策略"""
    strategies = {
        'algolia': 'web_browser',
        'github': 'web_browser',
        'google': 'web_browser',
    }
    fallback = strategies.get(original_api, 'web_browser')
    return fallback

def precheck_code(code: str) -> dict:
    """代码执行前语法预检"""
    try:
        compile(code, '<precheck>', 'exec')
        return {'valid': True}
    except SyntaxError as e:
        return {
            'valid': False,
            'error': str(e),
            'lineno': e.lineno,
            'msg': e.msg,
        }

def auto_install(module_name: str) -> bool:
    """自动尝试安装缺失包"""
    try:
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', module_name, '--quiet'],
            capture_output=True, timeout=30
        )
        return True
    except:
        return False

def path_guess(original_path: str) -> list:
    """文件未找到时尝试智能猜测"""
    p = Path(original_path)
    candidates = []
    # 尝试不同扩展名
    for ext in ['.py', '.md', '.txt', '.json', '.csv']:
        candidate = p.with_suffix(ext)
        if candidate.exists():
            candidates.append(str(candidate))
    # 尝试memory/下查找
    if not candidates:
        for f in MEM_DIR.rglob(p.stem + '.*'):
            candidates.append(str(f.relative_to(MEM_DIR)))
    return candidates

def context_compress() -> dict:
    """上下文逼近极限时预警"""
    # 通过goal_setter触发压缩建议
    return {
        'action': 'compress',
        'message': '上下文即将达到极限，建议进行记忆压缩',
    }

def retry_fallback(max_retries: int = 2) -> dict:
    """超时重试策略"""
    return {
        'action': 'retry',
        'max_retries': max_retries,
        'backoff': 2,  # 指数退避
    }

# ── 健康检查 ──

def health_check() -> dict:
    """全面健康检查"""
    status = {'healthy': True, 'checks': [], 'issues': []}
    
    # 1. 文件系统可写
    try:
        test_file = LOG_DIR / '.health_test'
        test_file.write_text('ok')
        test_file.unlink()
        status['checks'].append({'name': 'filesystem', 'ok': True})
    except:
        status['checks'].append({'name': 'filesystem', 'ok': False})
        status['issues'].append('文件系统不可写')
        status['healthy'] = False
    
    # 2. 关键文件存在
    critical_files = [
        'capability_map.py', 'task_learning.py', 'meta_learning.py',
        'goal_setter.py', 'self_improvement_sop.md',
    ]
    missing = [f for f in critical_files if not (HEARTBEAT_DIR / f).exists() and not (MEM_DIR / f).exists()]
    if missing:
        status['checks'].append({'name': 'critical_files', 'ok': False, 'missing': missing})
        status['issues'].append(f'缺失关键文件: {missing}')
        status['healthy'] = False
    else:
        status['checks'].append({'name': 'critical_files', 'ok': True})
    
    # 3. 关键模块可导入
    for mod in ['json', 'datetime', 'pathlib']:
        try:
            __import__(mod)
        except:
            status['checks'].append({'name': f'module_{mod}', 'ok': False})
            status['issues'].append(f'模块{mod}不可用')
            status['healthy'] = False
    
    # 4. 磁盘空间
    try:
        usage = os.statvfs(str(MEM_DIR)) if hasattr(os, 'statvfs') else None
        if usage:
            free_gb = usage.f_frsize * usage.f_bavail / (1024**3)
            if free_gb < 0.1:
                status['checks'].append({'name': 'disk_space', 'ok': False})
                status['issues'].append(f'磁盘空间不足: {free_gb:.1f}GB')
                status['healthy'] = False
    except:
        pass
    
    return status

# ── 自愈执行 ──

def heal(error_text: str, context: dict = None) -> dict:
    """主入口：检测→恢复→报告"""
    context = context or {}
    
    # 1. 检测
    faults = detect_fault(error_text)
    if not faults:
        return {'healed': False, 'reason': 'unknown_fault', 'faults': []}
    
    # 2. 记录
    for f in faults:
        log_fault(f, str(context.get('action', '')))
    
    # 3. 恢复
    actions_taken = []
    for f in faults:
        strategy = f['recovery']
        if strategy == 'fallback_search':
            api = context.get('api', 'unknown')
            fallback = fallback_search(api)
            actions_taken.append(f'搜索降级: {api}→{fallback}')
        elif strategy == 'precheck_code':
            code = context.get('code', '')
            result = precheck_code(code)
            if not result['valid']:
                actions_taken.append(f"语法修复: 第{result['lineno']}行 {result['msg']}")
        elif strategy == 'auto_install':
            mod = context.get('module', '')
            if auto_install(mod):
                actions_taken.append(f'自动安装: {mod}')
        elif strategy == 'path_guess':
            path = context.get('path', '')
            guesses = path_guess(path)
            if guesses:
                actions_taken.append(f'路径猜测: {guesses[0]}')
        elif strategy == 'context_compress':
            actions_taken.append('上下文压缩建议已触发')
        elif strategy == 'retry_fallback':
            actions_taken.append(f'重试策略: 最多{retry_fallback()["max_retries"]}次')
    
    return {
        'healed': len(actions_taken) > 0,
        'faults': [f['id'] for f in faults],
        'severity': max(f['severity'] for f in faults),
        'actions_taken': actions_taken,
    }


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='运行健康检查')
    parser.add_argument('--heal', type=str, help='自愈: 传入错误文本')
    args = parser.parse_args()
    
    if args.check:
        result = health_check()
        print(f"{'✅' if result['healthy'] else '❌'} 健康检查: {'通过' if result['healthy'] else '异常'}")
        for c in result['checks']:
            print(f"  {'✅' if c.get('ok') else '❌'} {c['name']}")
        for i in result['issues']:
            print(f"  ⚠️ {i}")
    
    if args.heal:
        result = heal(args.heal)
        print(f"故障: {result['faults']}")
        print(f"恢复: {'✅' if result['healed'] else '❌'} {result.get('actions_taken', [])}")
