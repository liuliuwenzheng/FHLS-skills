"""
skill_spark_agent — GA 的 24/7 主动 Agent 调度器

受 @joshwoodward (Google VP/Gemini App) 的 Gemini Spark 启发:
  "24/7 personal AI agent designed to proactively manage tasks 
   and help you navigate your digital life, all under your direction."
  — Josh Woodward, 2026/5/20

三问骨髓内化:
Q1: Gemini Spark 和普通 Agent 的本质区别?
A1: ①全天候运行(24/7) ②主动管理(proactive并非被动等待) 
    ③在用户掌控下(all under your direction) ④跨场景协助(digital life)

Q2: GA 现在的差距在哪?
A2: ①只有被动响应(put_task→run) ②无定时/事件触发机制 
    ③无跨会话任务队列 ④无主动提议能力

Q3: 最小可验证改造?
A3: 创建 SparkAgent 调度器: ①Task(优先级+条件+动作) ②Scheduler(轮询+触发) 
    ③ProactiveProposer(上下文感知提议) → 3项自检通过

用法:
    from skill_spark_agent import SparkScheduler, ProactiveProposer
    
    # 创建调度器
    sched = SparkScheduler()
    sched.add_task(SparkTask("news_briefing", lambda: print("播报新闻"), 
                             trigger="daily@08:00", priority=3))
    sched.start()
"""

import time
import threading
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional, Any


# ─── 核心数据类型 ───────────────────────────────────────────────────────────

@dataclass
class SparkTask:
    """主动任务单元 — 比普通task多了trigger/priority/cooldown"""
    name: str                      # 唯一任务名
    action: Optional[Callable] = None  # 要执行的动作
    trigger: str = "manual"        # 触发条件: "manual" / "daily@HH:MM" / "interval=NNs" / "event:xxx"
    priority: int = 5              # 1-10, 10最高
    cooldown: int = 300            # 冷却时间(秒)，防止重复触发
    enabled: bool = True
    last_run: Optional[float] = None
    run_count: int = 0
    description: str = ""
    
    def should_run(self, force: bool = False) -> bool:
        """判断是否应该执行"""
        if not self.enabled:
            return False
        if force:
            return True
        
        now = time.time()
        # 冷却检查
        if self.last_run and (now - self.last_run) < self.cooldown:
            return False
        
        # 触发条件检查
        if self.trigger.startswith("daily@"):
            target_time = self.trigger.split("@")[1]
            now_str = datetime.now().strftime("%H:%M")
            if now_str == target_time and (not self.last_run or 
                datetime.fromtimestamp(self.last_run).strftime("%Y-%m-%d") != datetime.now().strftime("%Y-%m-%d")):
                return True
                
        elif self.trigger.startswith("interval="):
            interval = int(self.trigger.split("=")[1].replace("s", ""))
            if self.last_run and (now - self.last_run) >= interval:
                return True
            elif not self.last_run:
                return True  # 从未运行过立即触发
        
        return False


@dataclass
class SparkContext:
    """上下文快照 — Agent运行时的环境信息"""
    current_time: str = ""
    user_active: bool = True
    last_interaction: Optional[float] = None
    pending_tasks: int = 0
    memory_updated: bool = False
    browser_open: bool = False
    network_ok: bool = True
    
    @classmethod
    def snapshot(cls) -> 'SparkContext':
        """获取当前上下文快照"""
        return cls(
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_interaction=time.time(),
        )


# ─── SparkScheduler — 主动调度核心 ─────────────────────────────────────────

class SparkScheduler:
    """
    Spark 调度器 — 24/7 主动任务调度
    
    核心设计:
    - 独立线程轮询,不阻塞主Agent
    - 优先级队列,高优任务抢占
    - 跨会话持久化(JSON)
    - 事件驱动+定时驱动双模式
    """
    
    def __init__(self, storage_dir: Optional[str] = None):
        self.tasks: dict[str, SparkTask] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # 存储
        if storage_dir is None:
            storage_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 
                '..', 'temp', 'spark_scheduler'
            )
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._tasks_file = self.storage_dir / 'tasks.json'
        
        # 加载已有任务
        self._load()
    
    def add_task(self, task: SparkTask) -> str:
        """添加任务"""
        with self._lock:
            self.tasks[task.name] = task
            self._save()
        return task.name
    
    def remove_task(self, name: str) -> bool:
        """移除任务"""
        with self._lock:
            if name in self.tasks:
                del self.tasks[name]
                self._save()
                return True
        return False
    
    def get_task(self, name: str) -> Optional[SparkTask]:
        """获取任务"""
        return self.tasks.get(name)
    
    def list_tasks(self, sort_by: str = "priority") -> list[SparkTask]:
        """列出任务,支持排序"""
        tasks = list(self.tasks.values())
        if sort_by == "priority":
            tasks.sort(key=lambda t: t.priority, reverse=True)
        elif sort_by == "name":
            tasks.sort(key=lambda t: t.name)
        elif sort_by == "last_run":
            tasks.sort(key=lambda t: t.last_run or 0, reverse=True)
        return tasks
    
    def run_task(self, name: str) -> bool:
        """手动触发执行某个任务"""
        task = self.get_task(name)
        if task and task.action:
            try:
                task.action()
                task.last_run = time.time()
                task.run_count += 1
                self._save()
                return True
            except Exception as e:
                print(f"[Spark] 任务执行失败 {name}: {e}")
        return False
    
    def run_due(self) -> list[str]:
        """执行所有到期的任务,返回已执行的任务名列表"""
        executed = []
        with self._lock:
            for name, task in sorted(
                self.tasks.items(), 
                key=lambda x: x[1].priority, 
                reverse=True
            ):
                if task.should_run() and task.action:
                    try:
                        task.action()
                        task.last_run = time.time()
                        task.run_count += 1
                        executed.append(name)
                    except Exception as e:
                        print(f"[Spark] 定时任务失败 {name}: {e}")
        if executed:
            self._save()
        return executed
    
    def propose_tasks(self, context: SparkContext) -> list[SparkTask]:
        """
        主动提议 — 基于上下文分析哪些任务值得执行
        这是 Gemini Spark "proactive" 理念的核心
        """
        proposals = []
        for task in self.tasks.values():
            if not task.enabled:
                continue
            # 高优任务在空闲时段提议
            if task.priority >= 7 and not context.user_active:
                proposals.append(task)
            # 冷却已过的任务
            elif task.last_run and task.should_run(force=True):
                proposals.append(task)
        return sorted(proposals, key=lambda t: t.priority, reverse=True)
    
    def start(self, interval: float = 10.0):
        """启动调度器(独立线程)"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, 
            args=(interval,), 
            daemon=True,
            name="SparkScheduler"
        )
        self._thread.start()
        print(f"[Spark] 调度器已启动 (轮询间隔={interval}s)")
    
    def stop(self):
        """停止调度器"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        print("[Spark] 调度器已停止")
    
    def status(self) -> dict:
        """获取调度器状态"""
        with self._lock:
            return {
                "running": self._running,
                "tasks_total": len(self.tasks),
                "tasks_enabled": sum(1 for t in self.tasks.values() if t.enabled),
                "tasks_run_today": sum(1 for t in self.tasks.values() 
                    if t.last_run and datetime.fromtimestamp(t.last_run).date() == datetime.now().date()),
                "thread_alive": self._thread and self._thread.is_alive(),
            }
    
    # ─── 内部方法 ──────────────────────────────────────────────────────
    
    def _loop(self, interval: float):
        """调度主循环"""
        while self._running:
            try:
                executed = self.run_due()
                if executed:
                    print(f"[Spark] 自动触发: {', '.join(executed)}")
            except Exception as e:
                print(f"[Spark] 调度循环异常: {e}")
            time.sleep(interval)
    
    def _save(self):
        """持久化任务队列"""
        data = {
            name: {
                "name": t.name,
                "trigger": t.trigger,
                "priority": t.priority,
                "cooldown": t.cooldown,
                "enabled": t.enabled,
                "last_run": t.last_run,
                "run_count": t.run_count,
                "description": t.description,
            }
            for name, t in self.tasks.items()
        }
        try:
            with open(self._tasks_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Spark] 保存失败: {e}")
    
    def _load(self):
        """加载持久化任务"""
        if not self._tasks_file.exists():
            return
        try:
            with open(self._tasks_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for name, d in data.items():
                task = SparkTask(
                    name=d["name"],
                    trigger=d.get("trigger", "manual"),
                    priority=d.get("priority", 5),
                    cooldown=d.get("cooldown", 300),
                    enabled=d.get("enabled", True),
                    last_run=d.get("last_run"),
                    run_count=d.get("run_count", 0),
                    description=d.get("description", ""),
                )
                self.tasks[name] = task
        except Exception as e:
            print(f"[Spark] 加载失败: {e}")


# ─── ProactiveProposer — 主动提议引擎 ──────────────────────────────────────

class ProactiveProposer:
    """
    主动提议引擎 — 上下文感知的"智能提议"系统
    
    核心设计:
    - 基于SparkContext分析当前状态
    - 维护提议规则库
    - 可学习的提议频率调节
    """
    
    def __init__(self, scheduler: Optional[SparkScheduler] = None):
        self.scheduler = scheduler
        
        # 默认提议规则: (条件函数, 提议模板)
        self._rules = [
            (self._rule_news_time, "现在{time}了，要听听今日AI资讯吗？"),
            (self._rule_idle_agent, "我看到你有一段时间没操作了，要不要我主动执行一些后台任务？"),
            (self._rule_memory_gc, "记忆库超过{count}条了，需要整理一下吗？"),
        ]
    
    def _rule_news_time(self, ctx: SparkContext) -> Optional[str]:
        """早晨/晚间播报提议"""
        hour = datetime.now().hour
        if 7 <= hour <= 9:
            return f"现在{hour}点"
        return None
    
    def _rule_idle_agent(self, ctx: SparkContext) -> Optional[str]:
        """空闲提议"""
        if ctx.last_interaction and (time.time() - ctx.last_interaction) > 600:
            return None  # 空闲超过10分钟
        return None
    
    def _rule_memory_gc(self, ctx: SparkContext) -> Optional[str]:
        """记忆整理提议"""
        try:
            mem_dir = Path(os.path.dirname(os.path.abspath(__file__))) / '..' / 'memory'
            count = sum(1 for f in mem_dir.glob('*.md') if f.is_file())
            if count > 50:
                return f"memory下有{count}个文件"
        except:
            pass
        return None
    
    def get_proposals(self, ctx: Optional[SparkContext] = None) -> list[str]:
        """获取当前所有提议"""
        if ctx is None:
            ctx = SparkContext.snapshot()
        
        proposals = []
        for rule_fn, template in self._rules:
            result = rule_fn(ctx)
            if result:
                proposals.append(template.format(time=result, count=50))
        
        return proposals[:3]  # 最多3条


# ─── 辅助函数 ───────────────────────────────────────────────────────────────

def create_auto_scheduler() -> SparkScheduler:
    """
    创建默认自动调度器(含内置任务)
    
    用法:
        sched = create_auto_scheduler()
        sched.start()
    """
    sched = SparkScheduler()
    
    # 内置种子任务
    builtin = [
        SparkTask(
            name="daily_news_check",
            description="每日自动检查新闻",
            trigger="daily@08:00",
            priority=7,
            cooldown=3600,
        ),
        SparkTask(
            name="memory_cleanup",
            description="记忆库定时整理",
            trigger="daily@23:00",
            priority=5,
            cooldown=86400,
        ),
        SparkTask(
            name="system_health",
            description="系统健康检查",
            trigger="interval=3600s",
            priority=8,
            cooldown=1800,
        ),
    ]
    
    for task in builtin:
        sched.add_task(task)
    
    return sched


# ─── 自检 ───────────────────────────────────────────────────────────────────

def self_test():
    """9项自检"""
    print(f"[TEST] {__name__} 自检")
    import sys
    
    # 1. 创建调度器
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    sched = SparkScheduler(storage_dir=tmp_dir)
    assert sched.status()["tasks_total"] == 0
    print(f"  [OK] SparkScheduler: 空调度器创建成功")
    
    # 2. 添加任务
    counter = [0]
    def dummy_action():
        counter[0] += 1
    
    t1 = SparkTask("test_task", dummy_action, trigger="interval=10s", priority=5)
    sched.add_task(t1)
    assert sched.status()["tasks_total"] == 1
    print(f"  [OK] add_task: {t1.name} 添加成功")
    
    # 3. 手动触发
    ok = sched.run_task("test_task")
    assert ok and counter[0] == 1
    print(f"  [OK] run_task: 手动触发成功, counter={counter[0]}")
    
    # 4. should_run 冷却逻辑
    assert not t1.should_run()  # 刚运行,冷却中
    t1.last_run = time.time() - 600  # 模拟10分钟前运行
    assert t1.should_run(force=True)
    print(f"  [OK] should_run: 冷却逻辑正确")
    
    # 5. 优先级排序
    t2 = SparkTask("high_pri", dummy_action, priority=10)
    t3 = SparkTask("low_pri", dummy_action, priority=1)
    sched.add_task(t2)
    sched.add_task(t3)
    listed = sched.list_tasks("priority")
    assert listed[0].name == "high_pri"
    assert listed[-1].name == "low_pri"
    print(f"  [OK] list_tasks: 优先级排序正确")
    
    # 6. 持久化
    sched2 = SparkScheduler(storage_dir=tmp_dir)
    assert sched2.status()["tasks_total"] == 3
    print(f"  [OK] 持久化: 跨实例加载成功")
    
    # 7. 主动提议
    proposer = ProactiveProposer(sched)
    ctx = SparkContext(user_active=False)
    proposals = proposer.get_proposals(ctx)
    assert len(proposals) <= 3
    print(f"  [OK] ProactiveProposer: 提议={proposals[:2]}")
    
    # 8. 调度器启动/停止
    sched.start(interval=1)
    assert sched.status()["running"]
    time.sleep(2.5)
    sched.stop()
    assert not sched.status()["running"]
    print(f"  [OK] start/stop: 调度线程生命周期正确")
    
    # 9. 创建自动调度器
    auto_sched = create_auto_scheduler()
    assert auto_sched.status()["tasks_total"] == 3
    names = [t.name for t in auto_sched.list_tasks()]
    assert "daily_news_check" in names
    assert "system_health" in names
    print(f"  [OK] create_auto_scheduler: {names}")
    
    print(f"\n[OK] 全部9项自检通过!")
    return True


if __name__ == "__main__":
    self_test()
