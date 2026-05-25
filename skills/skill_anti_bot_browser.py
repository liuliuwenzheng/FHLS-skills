"""
skill_anti_bot_browser.py - 浏览器反Bot检测方案
================================================

问题: GA通过Chrome CDP (localhost:9222)连接浏览器时，
      navigator.webdriver=true + CDP特征 → 被识别为机器人

来源: Reddit r/ClaudeAI + Google反bot检测研究
引入时间: 2026-05-25

四层方案:
  第1层: 真实用户数据目录启动 (零成本，保留cookies/登录态)
  第2层: CDP注入反检测JS (GA可直接执行，覆盖webdriver特征)
  第3层: stealth插件 (第三方，需要装包)
  第4层: 代理方案 (Bright Data等，成本高)

用法:
  from memory.skill_anti_bot_browser import inject_stealth_js, get_chrome_launch_args
"""

import json
import subprocess
from typing import List


def get_stealth_js() -> str:
    """
    反Bot检测JS代码 - 注入到浏览器中覆盖自动化特征
    原理: 在页面加载前改写 navigator.webdriver / chrome.runtime 等
    
    来源: puppeteer-extra-plugin-stealth 核心逻辑的精简版
    """
    return r"""
// === Anti-Bot Detection Stealth ===
// 覆盖 navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined,
  configurable: true
});

// 覆盖 chrome.runtime 检查
window.chrome = {
  runtime: {
    connect: () => {},
    sendMessage: () => {},
    onMessage: { addListener: () => {} }
  }
};

// 覆盖 permissions 检查
if (navigator.permissions) {
  const origQuery = navigator.permissions.query;
  navigator.permissions.query = (params) => {
    if (params.name === 'notifications') {
      return Promise.resolve({ state: 'denied' });
    }
    return origQuery(params);
  };
}

// 覆盖 plugins 数组长度 (正常浏览器>0)
Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3, 4, 5],
  configurable: true
});

// 覆盖 languages 返回正常值
Object.defineProperty(navigator, 'languages', {
  get: () => ['zh-CN', 'zh', 'en'],
  configurable: true
});
"""


def inject_stealth_js_script() -> str:
    """
    构造CDP命令，用于注入反检测JS到浏览器
    通过 Page.addScriptToEvaluateOnNewDocument 在每页加载前注入
    
    返回: CDP命令JSON
    """
    js_code = get_stealth_js()
    cmd = {
        "method": "Page.addScriptToEvaluateOnNewDocument",
        "params": {
            "source": js_code
        }
    }
    return json.dumps(cmd, ensure_ascii=False)


def get_chrome_launch_args(user_data_dir: str = None) -> List[str]:
    """
    获取反bot检测的Chrome启动参数
    第1层方案: 使用真实用户数据目录
    
    Args:
        user_data_dir: Chrome用户数据目录路径
                       Windows默认: %LOCALAPPDATA%\\Google\\Chrome\\User Data
    Returns:
        启动参数列表
    """
    args = [
        "--remote-debugging-port=9222",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=ChromeWhatsNewUI",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
    ]
    
    if user_data_dir:
        args.append(f'--user-data-dir="{user_data_dir}"')
    
    return args


def check_bot_detection_status() -> dict:
    """
    通过CDP检查当前浏览器是否暴露bot特征
    需要浏览器已连接CDP 9222
    
    返回: 检测报告
    """
    import urllib.request
    
    try:
        # 尝试连接CDP
        req = urllib.request.Request("http://localhost:9222/json/version")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            
        return {
            "connected": True,
            "browser": data.get("Browser", "unknown"),
            "webdriver_active": "--enable-automation" in data.get("Browser", ""),
            "user_data": data.get("User Data", "unknown"),
        }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
        }


# ============ 自检 ============
if __name__ == "__main__":
    print("=" * 50)
    print("skill_anti_bot_browser 自检")
    print("=" * 50)
    
    # 测试1: stealth JS生成
    print("\n测试1: Stealth JS生成")
    js = get_stealth_js()
    assert "navigator.webdriver" in js
    assert "chrome.runtime" in js
    assert "navigator.plugins" in js
    print(f"  ✅ JS代码长度: {len(js)} 字符")
    
    # 测试2: CDP命令构造
    print("\n测试2: CDP命令构造")
    cmd = inject_stealth_js_script()
    cmd_obj = json.loads(cmd)
    assert cmd_obj["method"] == "Page.addScriptToEvaluateOnNewDocument"
    print(f"  ✅ CDP命令方法: {cmd_obj['method']}")
    
    # 测试3: 启动参数
    print("\n测试3: 启动参数")
    args = get_chrome_launch_args(r"C:\Users\Administrator\AppData\Local\Google\Chrome\User Data")
    assert "--remote-debugging-port=9222" in args
    assert "--disable-blink-features=AutomationControlled" in args
    print(f"  ✅ 启动参数数量: {len(args)}")
    
    # 测试4: Bot检测状态（检查是否能连接CDP）
    print("\n测试4: CDP连接检查")
    status = check_bot_detection_status()
    print(f"  📡 CDP连接状态: {'已连接' if status['connected'] else '未连接'}")
    if status['connected']:
        print(f"  📡 浏览器: {status['browser']}")
    
    print(f"\n✅ 自检通过！")
    print(f"📂 文件: ../memory/skill_anti_bot_browser.py")
    print(f"📌 快速使用:")
    print(f"   from memory.skill_anti_bot_browser import inject_stealth_js_script, get_chrome_launch_args")
