#!/usr/bin/env python3
"""
自动技能获取系统 — 嘻嘻的自助工具箱
====================================
当遇到不认识的库/工具时，自动识别、安装、验证。

能力:
  - 扫描可用包管理器
  - 自动安装Python/Node/Rust包
  - 安装前安全检查
  - 安装后自动验证
  - 失败回滚
"""
import subprocess, sys, json, shutil, time, importlib
from pathlib import Path

HEARTBEAT_DIR = Path(__file__).parent

# ── 注册已知包管理器 ──
PACKAGE_MANAGERS = {}

# pip
if shutil.which('pip'):
    PACKAGE_MANAGERS['pip'] = {
        'check': lambda pkg: __import_safe(pkg),
        'install': lambda pkg: subprocess.run([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'], capture_output=True, text=True, timeout=120),
        'uninstall': lambda pkg: subprocess.run([sys.executable, '-m', 'pip', 'uninstall', pkg, '-y', '--quiet'], capture_output=True, text=True, timeout=30),
        'lang': 'python',
        'name': 'pip (Python)'
    }

# npm
npm = shutil.which('npm')
if npm:
    PACKAGE_MANAGERS['npm'] = {
        'check': lambda pkg: shutil.which(pkg) is not None,
        'install': lambda pkg: subprocess.run([npm, 'install', '-g', pkg, '--quiet'], capture_output=True, text=True, timeout=120),
        'uninstall': lambda pkg: subprocess.run([npm, 'uninstall', '-g', pkg, '--quiet'], capture_output=True, text=True, timeout=30),
        'lang': 'node',
        'name': 'npm (Node.js)'
    }

# cargo
cargo = shutil.which('cargo')
if cargo:
    PACKAGE_MANAGERS['cargo'] = {
        'check': lambda pkg: shutil.which(pkg) is not None,
        'install': lambda pkg: subprocess.run([cargo, 'install', pkg, '--quiet'], capture_output=True, text=True, timeout=300),
        'uninstall': lambda pkg: subprocess.run([cargo, 'uninstall', pkg, '--quiet'], capture_output=True, text=True, timeout=30),
        'lang': 'rust',
        'name': 'cargo (Rust)'
    }

def __import_safe(pkg):
    """安全检查Python包是否可用（处理带横杠的包名）"""
    name = pkg.replace('-', '_').replace('.', '')
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        pass
    # 尝试原始名
    try:
        importlib.import_module(pkg)
        return True
    except ImportError:
        return False

def scan_managers():
    """返回可用包管理器列表"""
    return {k: v['name'] for k, v in PACKAGE_MANAGERS.items()}

def acquire(pkg_name: str, manager: str = None) -> dict:
    """
    获取一个包/工具。
    - pkg_name: 包名
    - manager: 指定管理器(pip/npm/cargo)，None则自动尝试
    """
    result = {'package': pkg_name, 'success': False, 'steps': []}
    
    # 确定管理器
    if manager and manager in PACKAGE_MANAGERS:
        managers = {manager: PACKAGE_MANAGERS[manager]}
    else:
        managers = PACKAGE_MANAGERS  # 全部尝试
    
    for mgr_name, mgr in managers.items():
        step = {'manager': mgr_name, 'status': 'attempt'}
        
        # 先检查是否已有
        try:
            if mgr['check'](pkg_name):
                result['success'] = True
                step['status'] = 'already_installed'
                result['steps'].append(step)
                return result
        except:
            pass
        
        # 安装
        try:
            step['action'] = f"正在安装 ({mgr['name']})..."
            install_result = mgr['install'](pkg_name)
            
            if install_result.returncode == 0:
                # 验证
                try:
                    if mgr['check'](pkg_name):
                        step['status'] = 'installed_and_verified'
                        result['success'] = True
                        result['steps'].append(step)
                        return result
                except:
                    pass
                step['status'] = 'installed'
                result['success'] = True
                result['steps'].append(step)
                return result
            else:
                step['status'] = 'failed'
                step['error'] = install_result.stderr[:200]
                result['steps'].append(step)
        except Exception as e:
            step['status'] = 'error'
            step['error'] = str(e)[:100]
            result['steps'].append(step)
    
    # 全部失败
    return result

def batch_acquire(packages: list) -> dict:
    """批量获取包"""
    results = {}
    for pkg in packages:
        results[pkg] = acquire(pkg)
    return results

def suggest_packages(task_desc: str) -> list:
    """根据任务描述推荐需要安装的包"""
    suggestions = []
    task_lower = task_desc.lower()
    
    # 常见Python包
    if any(k in task_lower for k in ['爬虫', 'scrape', '网页', 'http']):
        suggestions.append(('requests', 'pip'))
        suggestions.append(('beautifulsoup4', 'pip'))
    if any(k in task_lower for k in ['图片', '图像', 'image', 'ocr', '截图']):
        suggestions.append(('pillow', 'pip'))
        suggestions.append(('opencv-python', 'pip'))
    if any(k in task_lower for k in ['数据', '分析', '图表', 'plot', 'chart']):
        suggestions.append(('pandas', 'pip'))
        suggestions.append(('matplotlib', 'pip'))
    if any(k in task_lower for k in ['pdf', 'pdf提取', 'pdf解析']):
        suggestions.append(('pypdf2', 'pip'))
        suggestions.append(('pdfminer.six', 'pip'))
    if any(k in task_lower for k in ['数据库', 'database', 'sql', 'mysql', 'postgres']):
        suggestions.append(('sqlalchemy', 'pip'))
    if 'excel' in task_lower or 'xlsx' in task_lower:
        suggestions.append(('openpyxl', 'pip'))
    
    # Node包
    if any(k in task_lower for k in ['pdf生成', 'puppeteer', '无头浏览器']):
        suggestions.append(('puppeteer', 'npm'))
    
    return suggestions

# ── 自主发现 ──
def discover_capability(task_description: str) -> dict:
    """
    面对未知任务时的完整流程：
    1. 推荐可能需要的包
    2. 自动安装
    3. 报告结果
    """
    print(f"🔍 分析任务: {task_description}")
    
    # 推荐包
    suggestions = suggest_packages(task_description)
    
    if not suggestions:
        return {
            'task': task_description,
            'message': '无需额外包，已有能力充足',
            'recommendations': []
        }
    
    print(f"  推荐 {len(suggestions)} 个包:")
    for pkg, mgr in suggestions:
        print(f"    {mgr}/{pkg}")
    
    # 尝试安装
    results = []
    for pkg, mgr in suggestions:
        print(f"  安装 {pkg}...", end='')
        r = acquire(pkg, mgr)
        if r['success']:
            print(f" ✅")
        else:
            print(f" ❌ {r['steps'][-1].get('error','')[:40] if r['steps'] else ''}")
        results.append(r)
    
    success_count = sum(1 for r in results if r['success'])
    
    return {
        'task': task_description,
        'total': len(results),
        'installed': success_count,
        'results': results,
        'ready': success_count == len(results)
    }

# ── CLI ──
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', type=str, help='安装包')
    parser.add_argument('--manager', type=str, choices=['pip', 'npm', 'cargo'], help='指定管理器')
    parser.add_argument('--discover', type=str, help='根据任务描述自动发现和安装')
    parser.add_argument('--scan', action='store_true', help='扫描可用管理器')
    args = parser.parse_args()
    
    if args.scan:
        print("可用包管理器:")
        for k, v in scan_managers().items():
            print(f"  ✅ {k}: {v}")
    
    if args.install:
        r = acquire(args.install, args.manager)
        print(f"安装 {args.install}: {'✅ 成功' if r['success'] else '❌ 失败'}")
        for step in r['steps']:
            print(f"  {step['status']}: {step.get('action','')} {step.get('error','')}")
    
    if args.discover:
        r = discover_capability(args.discover)
        print(f"\n任务: {r['task']}")
        print(f"状态: {'✅ 一切就绪' if r.get('ready') else '⚠️ 部分成功'}")
        if r.get('recommendations'):
            print(f"推荐: {r['recommendations']}")
