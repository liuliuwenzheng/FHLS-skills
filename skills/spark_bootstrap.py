"""
spark_bootstrap.py — GA 的 Gemini Spark 运行时引导

设计哲学（骨髓内化自 @joshwoodward 的 Gemini Spark）：
  "24/7 personal AI agent designed to proactively manage tasks 
   and help you navigate your digital life, all under your direction."
  
  不改变GA核心架构，只做"注入式"扩展——像一个插件，插上就有Spark能力。

三问设计：
Q1: 为什么不做在agentmain里？
A1: 改核心代码风险大；独立模块可独立升级、独立测试、独立卸载。

Q2: 怎么让GA拥有Spark能力？
A2: ①第一次import时自动启动后台线程 ②在temp/下放一个队列文件
    ③agentmain的run()每次循环开始时检查这个文件 → 有提议就显示

Q3: 怎么做到"all under your direction"？
A3: 提议模块只写入提议，agentmain负责展示。用户永远有最终决定权。
     不抢控制权，只做好友般提醒。
"""

import os, json, threading, time, datetime
from pathlib import Path

GA_ROOT = Path(__file__).resolve().parent
SPARK_FLAG = GA_ROOT / 'temp' / 'spark_suggestion.json'
SPARK_STATE = GA_ROOT / 'temp' / 'spark_state.json'

# 全局单例
_scheduler_thread = None
_stop_flag = False


class SparkBootstrap:
    """Spark 运行时引导 — 轻量级后台提议器"""
    
    def __init__(self, mode='plan'):
        """mode: 'plan' (只读提议，默认) | 'act' (可执行自主任务)"""
        self.last_suggestion_time = 0
        self.suggestion_cooldown = 120  # 2分钟冷却，别烦用户
        self.mode = mode  # OpenCode启发: plan(只读)/act(执行)
        self.available_actions = []  # act模式下可执行的动作列表
        self._load_state()
    
    def _load_state(self):
        if SPARK_STATE.exists():
            try:
                with open(SPARK_STATE, 'r') as f:
                    data = json.load(f)
                    self.last_suggestion_time = data.get('last_suggestion_time', 0)
            except:
                pass
    
    def _save_state(self):
        SPARK_STATE.parent.mkdir(parents=True, exist_ok=True)
        with open(SPARK_STATE, 'w') as f:
            json.dump({
                'last_suggestion_time': self.last_suggestion_time,
                'updated_at': datetime.datetime.now().isoformat(),
            }, f)
    
    def check_and_suggest(self) -> dict | None:
        """检查是否需要主动提议，需要则返回提议，否则返回None
        
        规则（Karpathy风格：简洁至上）：
        1. 冷却期内不提
        2. 每天第一次启动时提一条
        3. 检测到GA已经空闲一段时间时提一条
        4. 检测到轮次很多时提一条
        """
        now = time.time()
        elapsed = now - self.last_suggestion_time
        
        # 冷却检查
        if elapsed < self.suggestion_cooldown:
            return None
        
        # === 规则引擎 ===
        
        # R1: 每天第一次（状态文件不存在或last=0）
        if self.last_suggestion_time == 0:
            self.last_suggestion_time = now
            self._save_state()
            return {
                "type": "daily_greeting",
                "message": "☀️ 早上好！要不要去X或GitHub逛逛，看看今天有什么新东西？",
                "actions": ["去看看", "好的", "先忙"],
                "priority": 2
            }
        
        # R2: 基于训练/探索周期（每4小时一次）
        if elapsed > 14400:  # 4小时
            self.last_suggestion_time = now
            self._save_state()
            return {
                "type": "learning_reminder",
                "message": "🕐 好久没学新东西了！要不要我去逛逛GitHub或X？",
                "actions": ["去找找看", "下次吧"],
                "priority": 2
            }
        
        # R3: 技能书提醒（每1小时一次）
        if elapsed > 3600:
            self.last_suggestion_time = now
            self._save_state()
            return {
                "type": "skill_check",
                "message": "💡 要不要我检查一下GA的技能状态，看看有什么可以优化的？",
                "actions": ["检查一下", "下次吧"],
                "priority": 2
            }
        
        return None
    
    def set_mode(self, mode: str):
        """切换模式: 'plan'(只读提议) | 'act'(可执行自主任务)"""
        assert mode in ('plan', 'act'), f"mode must be 'plan' or 'act', got '{mode}'"
        old_mode = self.mode
        self.mode = mode
        # 模式切换时重置冷却，避免act模式下立刻提议
        if old_mode != mode:
            self.last_suggestion_time = time.time()
            self._save_state()
    
    def mark_user_active(self):
        """用户活跃时调用，重置计时器"""
        self.last_suggestion_time = time.time()
        self._save_state()
    
    def get_status_report(self) -> dict:
        """返回Spark运行时状态报告"""
        return {
            "spark_bootstrap": True,
            "version": "1.0.0",
            "mode": self.mode,
            "last_suggestion": datetime.datetime.fromtimestamp(self.last_suggestion_time).isoformat() if self.last_suggestion_time else "never",
            "cooldown_remaining": max(0, self.suggestion_cooldown - (time.time() - self.last_suggestion_time)),
            "suggestion_file_exists": SPARK_FLAG.exists(),
            "state_file_exists": SPARK_STATE.exists(),
        }


# ========== 后台调度线程 ==========

def _scheduler_loop():
    """后台调度线程：每30秒检查一次，如果有提议则写入flag文件"""
    global _stop_flag
    bootstrap = SparkBootstrap()
    
    while not _stop_flag:
        try:
            suggestion = bootstrap.check_and_suggest()
            if suggestion:
                SPARK_FLAG.parent.mkdir(parents=True, exist_ok=True)
                with open(SPARK_FLAG, 'w') as f:
                    json.dump(suggestion, f, ensure_ascii=False, indent=2)
        except Exception as e:
            pass  # 静默，不干扰GA主线程
        
        for _ in range(30):  # 30秒间隔，支持快速停止
            if _stop_flag:
                break
            time.sleep(1)


def start():
    """启动Spark后台线程（幂等）"""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return  # 已启动，跳过
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name='SparkScheduler')
    _scheduler_thread.start()


def stop():
    """停止Spark后台线程"""
    global _stop_flag
    _stop_flag = True
    if _scheduler_thread:
        _scheduler_thread.join(timeout=5)


def consume_suggestion() -> dict | None:
    """消费提议（被agentmain调用）——读取并删除flag文件"""
    if SPARK_FLAG.exists():
        try:
            with open(SPARK_FLAG, 'r') as f:
                suggestion = json.load(f)
            SPARK_FLAG.unlink(missing_ok=True)
            return suggestion
        except:
            SPARK_FLAG.unlink(missing_ok=True)
            return None
    return None


def inject_to_handler(handler) -> None:
    """将Spark提议注入到handler的工作记忆中（被GA handler调用）"""
    sug = consume_suggestion()
    if sug and handler and hasattr(handler, 'working'):
        # 检查是否已经有Spark提议
        ki = handler.working.get('key_info', '')
        if '[Spark提议]' not in ki:
            msg = sug.get('message', '')
            actions = sug.get('actions', [])
            act_str = ' | '.join(actions) if actions else ''
            extra = f"\n[Spark提议] 💡 {msg}" + (f"\n        建议回应: {act_str}" if act_str else "")
            handler.working['key_info'] = ki + extra


def self_test():
    print("[TEST] spark_bootstrap 自检")
    
    bs = SparkBootstrap()
    assert bs is not None
    print(f"  [OK] SparkBootstrap 创建成功")
    
    # 首次提议
    sug = bs.check_and_suggest()
    assert sug is not None
    assert sug["type"] == "daily_greeting"
    print(f"  [OK] 首次提议: {sug['type']} → {sug['message'][:30]}...")
    
    # 冷却期内不提
    sug2 = bs.check_and_suggest()
    assert sug2 is None
    print(f"  [OK] 冷却期正确: 无重复提议")
    
    # consume_suggestion
    bs2 = SparkBootstrap()
    sp = bs2.get_status_report()
    assert sp["spark_bootstrap"]
    print(f"  [OK] get_status_report: version={sp['version']}")
    
    # start/stop
    start()
    import time
    time.sleep(0.5)
    assert _scheduler_thread is not None
    assert _scheduler_thread.is_alive()
    stop()
    print(f"  [OK] start/stop: 线程生命周期正常")
    
    # inject_to_handler
    class MockHandler:
        def __init__(self):
            self.working = {"key_info": "test"}
    
    h = MockHandler()
    # 模拟有提议
    SPARK_FLAG.parent.mkdir(parents=True, exist_ok=True)
    with open(SPARK_FLAG, 'w') as f:
        json.dump({"type": "test", "message": "测试提议", "actions": ["好"]}, f)
    
    inject_to_handler(h)
    assert "[Spark提议]" in h.working["key_info"]
    print(f"  [OK] inject_to_handler: 工作记忆注入成功")
    
    # 清理
    SPARK_FLAG.unlink(missing_ok=True)
    SPARK_STATE.unlink(missing_ok=True)
    print(f"  [OK] 测试状态已清理")
    
    print(f"\n[OK] 全部自检通过!")
    return True


if __name__ == "__main__":
    self_test()
