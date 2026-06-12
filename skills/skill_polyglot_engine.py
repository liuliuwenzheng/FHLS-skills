#!/usr/bin/env python3
"""
多语言引擎 — 嘻嘻的万能工具箱
============================
突破Python限制，按需选用最优语言：
  - Rust → 性能密集型（编译到原生，比Python快10-100x）
  - Node → Web/网络/异步
  - Python → AI/数据分析/胶水
  - PowerShell → Windows系统操作
"""
import subprocess, tempfile, time, shutil, os, sys
from pathlib import Path

HEARTBEAT_DIR = Path(__file__).parent
TEMP_DIR = HEARTBEAT_DIR / 'polyglot_cache'
TEMP_DIR.mkdir(exist_ok=True)

# ── 运行时检测 ──
def detect_runtimes():
    """扫描可用语言运行时"""
    result = {}
    # Python
    result['python'] = {'available': True, 'version': sys.version.split()[0], 'path': sys.executable}
    # Node
    node = shutil.which('node')
    if node:
        try:
            ver = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=3).stdout.strip()
            result['node'] = {'available': True, 'version': ver, 'path': node}
        except:
            result['node'] = {'available': False}
    else:
        result['node'] = {'available': False}
    # Rust
    rustc = shutil.which('rustc')
    cargo = shutil.which('cargo')
    if rustc:
        try:
            ver = subprocess.run([rustc, '--version'], capture_output=True, text=True, timeout=3).stdout.strip()
            result['rust'] = {'available': True, 'version': ver, 'path': rustc, 'cargo': bool(cargo)}
        except:
            result['rust'] = {'available': False}
    else:
        result['rust'] = {'available': False}
    # PowerShell
    pwsh = shutil.which('pwsh') or shutil.which('powershell')
    if pwsh:
        result['powershell'] = {'available': True, 'path': pwsh}
    else:
        result['powershell'] = {'available': False}
    return result

RUNTIMES = detect_runtimes()

def suggest_language(task_description: str) -> str:
    """根据任务描述推荐最佳语言"""
    task_lower = task_description.lower()
    
    # 性能密集型
    perf_keywords = ['计算', '排序', '搜索', 'loop', '循环', 'benchmark', 'parse', '解析大文件',
                     '加密', 'compression', '压缩', '图像处理', '数值计算', 'matrix', '矩阵']
    if any(k in task_lower for k in perf_keywords) and RUNTIMES.get('rust', {}).get('available'):
        return 'rust'
    
    # Web/网络
    web_keywords = ['http', 'fetch', '网络', 'web', 'api', 'json', '爬虫', 'scrape', 'server',
                    'async', '异步', 'url', 'request', 'rest']
    if any(k in task_lower for k in web_keywords) and RUNTIMES.get('node', {}).get('available'):
        return 'node'
    
    # 系统操作
    sys_keywords = ['文件', '进程', '注册表', 'service', '服务', 'window', 'windows',
                    'system', '系统', 'disk', '磁盘', 'registry']
    if any(k in task_lower for k in sys_keywords) and RUNTIMES.get('powershell', {}).get('available'):
        return 'powershell'
    
    # 默认Python
    return 'python'

# ── Rust执行器 ──
_rust_counter = 0

def run_rust(code: str) -> dict:
    """编译并运行Rust代码"""
    global _rust_counter
    _rust_counter += 1
    
    # 只编译main.rs，不依赖外部crate
    src = TEMP_DIR / f'rust_src_{_rust_counter}'
    src.mkdir(exist_ok=True)
    
    main_rs = src / 'main.rs'
    main_rs.write_text(code, encoding='utf-8')
    
    binary = src / 'main.exe'
    
    # 编译
    compile_start = time.time()
    comp = subprocess.run(
        [str(RUNTIMES['rust']['path']), str(main_rs), '-o', str(binary), '--edition', '2021'],
        capture_output=True, text=True, timeout=60
    )
    compile_time = time.time() - compile_start
    
    if comp.returncode != 0:
        return {
            'success': False,
            'error': comp.stderr[:500],
            'compile_time': compile_time,
            'language': 'rust'
        }
    
    # 运行
    run_start = time.time()
    proc = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    run_time = time.time() - run_start
    
    result = {
        'success': proc.returncode == 0,
        'stdout': proc.stdout,
        'stderr': proc.stderr[:200] if proc.stderr else '',
        'compile_time': round(compile_time, 3),
        'run_time': round(run_time, 3),
        'language': 'rust'
    }
    
    # 清理
    try:
        for f in src.iterdir():
            f.unlink()
        src.rmdir()
    except:
        pass
    
    return result

# ── Node执行器 ──
_node_counter = 0

def run_node(code: str) -> dict:
    """运行Node.js代码"""
    global _node_counter
    _node_counter += 1
    
    js_file = TEMP_DIR / f'node_src_{_node_counter}.js'
    js_file.write_text(code, encoding='utf-8')
    
    start = time.time()
    proc = subprocess.run([str(RUNTIMES['node']['path']), str(js_file)],
                          capture_output=True, text=True, timeout=30)
    run_time = time.time() - start
    
    js_file.unlink(missing_ok=True)
    
    return {
        'success': proc.returncode == 0,
        'stdout': proc.stdout,
        'stderr': proc.stderr[:200] if proc.stderr else '',
        'run_time': round(run_time, 3),
        'language': 'node'
    }

# ── 统一执行接口 ──
def execute(code: str, language: str = None, task_desc: str = None) -> dict:
    """万能执行器：自动选语言或指定语言"""
    if not language and task_desc:
        language = suggest_language(task_desc)
    if not language:
        language = 'python'
    
    if language == 'rust' and RUNTIMES.get('rust', {}).get('available'):
        return run_rust(code)
    elif language == 'node' and RUNTIMES.get('node', {}).get('available'):
        return run_node(code)
    elif language == 'powershell' and RUNTIMES.get('powershell', {}).get('available'):
        # PowerShell通过subprocess运行
        start = time.time()
        proc = subprocess.run(
            [str(RUNTIMES['powershell']['path']), '-Command', code],
            capture_output=True, text=True, timeout=30
        )
        return {
            'success': proc.returncode == 0,
            'stdout': proc.stdout,
            'stderr': proc.stderr[:200] if proc.stderr else '',
            'run_time': round(time.time() - start, 3),
            'language': 'powershell'
        }
    else:
        # Python: 用当前进程的exec
        import io, contextlib
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        start = time.time()
        try:
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                exec(code)
            success = True
        except Exception as e:
            stderr_capture.write(str(e))
            success = False
        return {
            'success': success,
            'stdout': stdout_capture.getvalue(),
            'stderr': stderr_capture.getvalue()[:200],
            'run_time': round(time.time() - start, 3),
            'language': 'python'
        }

# ── 性能对比基准 ──
def benchmark(task: str = 'loop') -> dict:
    """多语言性能对比"""
    results = {}
    
    if task == 'loop' or task == '计算':
        # Python
        py_code = """
n = 10000000
total = 0
for i in range(n):
    total += i
print(total)
"""
        if RUNTIMES.get('python'):
            results['python'] = execute(py_code, 'python')
        
        # Rust
        rs_code = """
fn main() {
    let n = 10_000_000u64;
    let total: u64 = (0..n).sum();
    println!("{}", total);
}
"""
        if RUNTIMES.get('rust', {}).get('available'):
            results['rust'] = execute(rs_code, 'rust')
        
        # Node
        js_code = """
let n = 10000000;
let total = 0;
for (let i = 0; i < n; i++) total += i;
console.log(total);
"""
        if RUNTIMES.get('node', {}).get('available'):
            results['node'] = execute(js_code, 'node')
    
    return results

# ── CLI ──
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--benchmark', action='store_true', help='运行性能对比')
    parser.add_argument('--detect', action='store_true', help='检测可用运行时')
    parser.add_argument('--suggest', type=str, help='为任务推荐语言')
    parser.add_argument('--run', type=str, help='执行代码文件')
    parser.add_argument('--lang', type=str, default=None, help='指定语言')
    args = parser.parse_args()
    
    if args.detect:
        runtimes = detect_runtimes()
        print("可用运行时:")
        for name, info in runtimes.items():
            status = f"✅ {info['version']}" if info.get('available') else '❌ 未安装'
            print(f"  {name:12s}: {status}")
    
    if args.benchmark:
        print("📊 性能对比 (1000万次循环加法)\n")
        results = benchmark()
        base_time = None
        for lang, r in results.items():
            if r['success']:
                t = r.get('run_time', r.get('compile_time', 0) + r.get('run_time', 0))
                if base_time is None:
                    base_time = t
                ratio = base_time / t if t > 0 else 0
                print(f"  {lang:10s}: {t:.3f}s (x{ratio:.1f} vs Python)")
            else:
                print(f"  {lang:10s}: ❌ {r.get('error','')[:50]}")
    
    if args.suggest:
        lang = suggest_language(args.suggest)
        print(f"推荐语言: {lang}")
        print(f"可用: {'✅' if RUNTIMES.get(lang,{}).get('available') else '❌'}")
    
    if args.run:
        code = Path(args.run).read_text(encoding='utf-8')
        result = execute(code, language=args.lang, task_desc=args.run)
        print(f"语言: {result['language']}")
        print(f"成功: {'✅' if result['success'] else '❌'}")
        print(f"耗时: {result.get('run_time',0):.3f}s")
        print(f"输出: {result['stdout'][:500]}")
        if result.get('stderr'):
            print(f"错误: {result['stderr'][:200]}")
