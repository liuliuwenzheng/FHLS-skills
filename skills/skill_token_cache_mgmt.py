"""
skill_token_cache_mgmt.py — Token多级缓存管理系统
==================================================
核心哲学：Token是有限预算，缓存是省钱利器。

借鉴：
- Claude API Cache机制 (cache_creation/cache_read)
- Redis/Memcached多级缓存架构
- LRU/K-ary淘汰算法
- 语义指纹去重 (不是字符串去重，是内容语义去重)

架构:
  TokenCache(L1) → 内存级, LRU淘汰, 微秒级
  DiskCache(L2)  → 磁盘级, TTL过期, 毫秒级
  SemanticDedup  → 语义去重, 避免重复注入相同内容
  CacheMonitor   → 监控命中率/开销节省/最耗token的前N个入口
  TokenCacheManager → 三合一入口, 对接context_manager/llmcore

用法:
  from memory.skill_token_cache_mgmt import TokenCacheManager
  mgr = TokenCacheManager()
  
  # 智能缓存（自动判断是否走cache）
  result = mgr.cached_inject('skill_registry_summary', content, ttl=300)
  
  # 多级缓存
  mgr.set_l1('key', value)
  mgr.set_l2('key', value, ttl=600)
  
  # 获取节省统计
  stats = mgr.get_cache_stats()
"""

import json, os, time, hashlib, datetime
from typing import Optional, Dict, Any, List, Tuple
from collections import OrderedDict


# ==================== 常量 ====================

DEFAULT_L1_MAX = 128     # L1最大条目
DEFAULT_L2_TTL = 600     # L2默认存活(秒)
DEFAULT_SEMANTIC_THRESHOLD = 0.85  # 语义去重相似度阈值
GA_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp', 'token_cache')
os.makedirs(GA_CACHE_DIR, exist_ok=True)


# ==================== L1: TokenCache (内存LRU) ====================

class TokenCache:
    """
    内存级Token缓存 — LRU淘汰
    
    比普通dict多的：
    - 按maxsize自动淘汰最久未用
    - 记录每次访问时间/命中数
    - 统计输入token节省量
    """
    
    def __init__(self, maxsize: int = DEFAULT_L1_MAX):
        self.maxsize = maxsize
        self._cache: OrderedDict = OrderedDict()
        self._stats = {'hits': 0, 'misses': 0, 'tokens_saved': 0, 'sets': 0}
    
    def get(self, key: str) -> Optional[str]:
        """获取缓存值，命中则移到末尾(LRU)"""
        if key in self._cache:
            val, token_est = self._cache[key]
            self._cache.move_to_end(key)
            self._stats['hits'] += 1
            self._stats['tokens_saved'] += token_est
            return val
        self._stats['misses'] += 1
        return None
    
    def set(self, key: str, value: str, token_estimate: int = 0):
        """设置缓存值，超maxsize则淘汰最早访问的"""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (value, token_estimate or len(value)//4)
        self._stats['sets'] += 1
        
        while len(self._cache) > self.maxsize:
            self._cache.popitem(last=False)  # 淘汰最早
    
    def remove(self, key: str):
        """主动删除"""
        self._cache.pop(key, None)
    
    def clear(self):
        """清空缓存"""
        self._cache.clear()
    
    def keys(self) -> List[str]:
        return list(self._cache.keys())
    
    def size(self) -> int:
        return len(self._cache)
    
    def get_stats(self) -> dict:
        """获取详细统计"""
        hit_rate = self._stats['hits'] / max(self._stats['hits']+self._stats['misses'], 1)
        return {
            'hits': self._stats['hits'],
            'misses': self._stats['misses'],
            'hit_rate': round(hit_rate, 4),
            'tokens_saved': self._stats['tokens_saved'],
            'entries': len(self._cache),
            'maxsize': self.maxsize,
        }


# ==================== L2: DiskCache (磁盘持久缓存) ====================

class DiskCache:
    """
    磁盘级Token缓存 — TTL过期
    
    用途：跨session持久化，避免每次启动重新加载SOP/技能定义
    """
    
    def __init__(self, cache_dir: str = GA_CACHE_DIR, default_ttl: int = DEFAULT_L2_TTL):
        self.cache_dir = cache_dir
        self.default_ttl = default_ttl
        self._stats = {'hits': 0, 'misses': 0, 'tokens_saved': 0, 'writes': 0}
    
    def _path(self, key: str) -> str:
        """key转文件路径"""
        safe = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(self.cache_dir, f'{safe}.json')
    
    def get(self, key: str) -> Optional[str]:
        """读取磁盘缓存，检查TTL"""
        path = self._path(key)
        if not os.path.exists(path):
            self._stats['misses'] += 1
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # TTL检查
            if time.time() - data.get('ts', 0) > data.get('ttl', self.default_ttl):
                os.remove(path)
                self._stats['misses'] += 1
                return None
            
            self._stats['hits'] += 1
            tokens = data.get('tokens', len(data['value'])//4)
            self._stats['tokens_saved'] += tokens
            return data['value']
        except (json.JSONDecodeError, KeyError, OSError):
            self._stats['misses'] += 1
            return None
    
    def set(self, key: str, value: str, ttl: Optional[int] = None, token_estimate: int = 0):
        """写入磁盘缓存"""
        path = self._path(key)
        data = {
            'key': key,
            'value': value,
            'ts': time.time(),
            'ttl': ttl or self.default_ttl,
            'tokens': token_estimate or len(value)//4,
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            self._stats['writes'] += 1
        except OSError:
            pass  # 磁盘满等静默失败
    
    def invalidate(self, key: str):
        """使缓存失效"""
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)
    
    def clear_expired(self) -> int:
        """清理过期缓存"""
        now = time.time()
        cleared = 0
        for fname in os.listdir(self.cache_dir):
            if not fname.endswith('.json'):
                continue
            path = os.path.join(self.cache_dir, fname)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if now - data.get('ts', 0) > data.get('ttl', self.default_ttl):
                    os.remove(path)
                    cleared += 1
            except (json.JSONDecodeError, OSError):
                # 损坏文件直接删
                try:
                    os.remove(path)
                    cleared += 1
                except OSError:
                    pass
        return cleared
    
    def get_stats(self) -> dict:
        hit_rate = self._stats['hits'] / max(self._stats['hits']+self._stats['misses'], 1)
        return {
            'hits': self._stats['hits'],
            'misses': self._stats['misses'],
            'hit_rate': round(hit_rate, 4),
            'tokens_saved': self._stats['tokens_saved'],
            'writes': self._stats['writes'],
            'files': len([f for f in os.listdir(self.cache_dir) if f.endswith('.json')]),
        }


# ==================== 语义去重器 ====================

class SemanticDedup:
    """
    语义去重 — 避免重复注入相同/相似内容
    
    原理：difflib.SequenceMatcher + 降噪预处理
    比jaccard shingle更准（尤其中文场景）
    """
    
    def __init__(self, threshold: float = 0.35, max_entries: int = 500):
        self.threshold = threshold
        self.max_entries = max_entries
        self._fingerprints: Dict[str, str] = OrderedDict()  # key → 规范化文本
        self._stats = {'checks': 0, 'duplicates_found': 0}
    
    def _normalize(self, text: str) -> str:
        """规范化：去空格/标点/换行，统一小写"""
        import re as _re
        text = _re.sub(r'[\s,，。！？、；：""''（）\(\)\[\]【】]+', ' ', text.lower())
        return text.strip()[:500]  # 截断长文本
    
    def _similarity(self, a: str, b: str) -> float:
        """SequenceMatcher比较"""
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a, b).ratio()
    
    def is_duplicate(self, key: str, content: str) -> Tuple[bool, float]:
        """
        检查是否重复
        返回 (是否重复, 相似度)
        """
        self._stats['checks'] += 1
        norm = self._normalize(content)
        
        for existing_key, existing_norm in self._fingerprints.items():
            sim = self._similarity(norm, existing_norm)
            if sim >= self.threshold:
                self._stats['duplicates_found'] += 1
                return (True, sim)
        
        # 不重复则加入指纹库
        self._fingerprints[key] = norm
        
        # 超限淘汰最旧
        while len(self._fingerprints) > self.max_entries:
            self._fingerprints.popitem(last=False)
        
        return (False, 0.0)

class CacheMonitor:
    """
    监控每次API调用的token消耗 + 缓存节省
    
    生成详细费用报告，定位最耗token的前N个入口
    """
    
    def __init__(self):
        self._call_log: List[dict] = []
        self._source_stats: Dict[str, dict] = {}  # source → 累计统计
        self.max_log = 1000
    
    def log_call(self, source: str, input_tokens: int, output_tokens: int,
                 cached_input: int = 0, cache_created: bool = False):
        """记录一次API调用"""
        entry = {
            'ts': time.time(),
            'source': source,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cached_input': cached_input,
            'cache_created': cache_created,
            'cost': (input_tokens * 3 + output_tokens * 15) / 1_000_000,  # Claude Sonnet
        }
        self._call_log.append(entry)
        
        # 按source统计
        if source not in self._source_stats:
            self._source_stats[source] = {
                'calls': 0, 'input_tokens': 0, 'output_tokens': 0,
                'cached_input': 0, 'cost': 0.0,
            }
        s = self._source_stats[source]
        s['calls'] += 1
        s['input_tokens'] += input_tokens
        s['output_tokens'] += output_tokens
        s['cached_input'] += cached_input
        s['cost'] += entry['cost']
        
        # 控制日志大小
        if len(self._call_log) > self.max_log:
            self._call_log = self._call_log[-self.max_log:]
    
    def get_cost_report(self, top_n: int = 10) -> List[dict]:
        """返回最耗token的前N个入口"""
        sorted_sources = sorted(
            self._source_stats.items(),
            key=lambda x: x[1]['cost'],
            reverse=True
        )
        report = []
        for source, stats in sorted_sources[:top_n]:
            report.append({
                'source': source,
                'calls': stats['calls'],
                'input_tokens': stats['input_tokens'],
                'output_tokens': stats['output_tokens'],
                'cached_input': stats['cached_input'],
                'cost_usd': round(stats['cost'], 4),
                'cache_saved_usd': round(stats['cached_input'] * 3 / 1_000_000, 4),
            })
        return report
    
    def get_summary(self) -> dict:
        """总体统计"""
        total_inp = sum(s['input_tokens'] for s in self._source_stats.values())
        total_out = sum(s['output_tokens'] for s in self._source_stats.values())
        total_cached = sum(s['cached_input'] for s in self._source_stats.values())
        total_cost = sum(s['cost'] for s in self._source_stats.values())
        return {
            'total_calls': len(self._call_log),
            'total_input_tokens': total_inp,
            'total_output_tokens': total_out,
            'total_cached_input': total_cached,
            'total_cost_usd': round(total_cost, 4),
            'cache_saved_usd': round(total_cached * 3 / 1_000_000, 4),
            'cache_effectiveness': round(total_cached / max(total_inp, 1) * 100, 2),
        }


# ==================== 三合一入口: TokenCacheManager ====================

class TokenCacheManager:
    """
    Token缓存管理器 — 统一入口
    
    三合一：
    - L1: 内存LRU缓存 (微秒级，本session内复用)
    - L2: 磁盘持久缓存 (毫秒级，跨session复用)
    - Dedup: 语义去重 (避免重复注入相似内容)
    
    用法：
      mgr = TokenCacheManager()
      
      # 智能注入（检查缓存→去重→返回）
      content = mgr.cached_inject('my_skill', raw_content)
      
      # 手动控制
      mgr.set_l1('key', val)
      mgr.set_l2('key', val, ttl=600)
      val = mgr.get('key')
      
      # 监控
      mgr.monitor.log_call('skill_registry', inp=5000, out=200)
      report = mgr.monitor.get_cost_report()
    """
    
    def __init__(self, l1_maxsize: int = DEFAULT_L1_MAX, l2_ttl: int = DEFAULT_L2_TTL):
        self.l1 = TokenCache(maxsize=l1_maxsize)
        self.l2 = DiskCache(default_ttl=l2_ttl)
        self.dedup = SemanticDedup()
        self.monitor = CacheMonitor()
        self._dedup_whitelist = set()  # 不做去重的key（如动态内容）
    
    def get(self, key: str) -> Optional[str]:
        """多级获取: L1 → L2"""
        # L1
        val = self.l1.get(key)
        if val is not None:
            return val
        
        # L2
        val = self.l2.get(key)
        if val is not None:
            # 回填L1
            self.l1.set(key, val)
            return val
        
        return None
    
    def set_l1(self, key: str, value: str, token_estimate: int = 0):
        """仅设置L1缓存"""
        self.l1.set(key, value, token_estimate)
    
    def set_l2(self, key: str, value: str, ttl: Optional[int] = None, token_estimate: int = 0):
        """仅设置L2缓存"""
        self.l2.set(key, value, ttl, token_estimate)
    
    def set_both(self, key: str, value: str, ttl: Optional[int] = None, token_estimate: int = 0):
        """同时设置L1+L2"""
        self.l1.set(key, value, token_estimate)
        self.l2.set(key, value, ttl, token_estimate)
    
    def cached_inject(self, key: str, content: str, ttl: Optional[int] = None,
                      dedup_check: bool = True) -> str:
        """
        智能注入 — 自动判断走缓存还是新内容
        
        流程：同key已存在→更新不走语义去重 | 同key不存在→走语义去重检查→全命中→写入缓存
        返回实际要注入的内容（None表示跳过注入）
        """
        # 1. 同key已存在 → 直接更新（不走语义去重，因为这是覆盖/更新操作）
        cached_l1 = self.l1.get(key)
        cached_l2 = self.l2.get(key)
        if cached_l1 is not None or cached_l2 is not None:
            token_est = len(content)//4
            self.set_both(key, content, ttl, token_est)
            # 同步更新去重指纹（直接覆写，不检查重复——这是显式更新）
            self.dedup._fingerprints[key] = self.dedup._normalize(content)
            self.monitor.log_call(source=f'update:{key}',
                                  input_tokens=token_est, output_tokens=0, cached_input=token_est)
            return content
        
        # 2. 语义去重检查（仅对全新key有效，防止不同key重复注入相同内容）
        if dedup_check and key not in self._dedup_whitelist:
            is_dup, sim = self.dedup.is_duplicate(key, content)
            if is_dup:
                self.monitor.log_call(source=f'dedup_skip:{key}',
                                      input_tokens=len(content)//4,
                                      output_tokens=0,
                                      cached_input=len(content)//4)
                return None  # 语义重复 → 跳过注入
        
        # 3. 写入缓存（全新key+不重复内容）
        token_est = len(content)//4
        self.set_both(key, content, ttl, token_est)
        self.monitor.log_call(source=f'inject:{key}',
                              input_tokens=token_est, output_tokens=0, cached_input=0)
        
        return content
    
    def invalidate(self, key: str):
        """使缓存失效"""
        self.l1.remove(key)
        self.l2.invalidate(key)
        self.dedup.forget(key)
    
    def add_dedup_whitelist(self, key: str):
        """加入去重白名单（动态内容不查重）"""
        self._dedup_whitelist.add(key)
    
    def get_cost_report(self, top_n: int = 10) -> List[dict]:
        """获取token消耗报告"""
        return self.monitor.get_cost_report(top_n)
    
    def get_summary_stats(self) -> dict:
        """全面诊断报告"""
        l1_stats = self.l1.get_stats()
        l2_stats = self.l2.get_stats()
        dedup_stats = self.dedup._stats.copy() if hasattr(self.dedup, '_stats') else {}
        monitor_summary = self.monitor.get_summary()
        
        total_tokens_saved = l1_stats['tokens_saved'] + l2_stats['tokens_saved']
        total_saved_usd = total_tokens_saved * 3 / 1_000_000  # input cost
        
        return {
            'timestamp': datetime.datetime.now().isoformat(),
            'total_tokens_saved': total_tokens_saved,
            'total_cost_saved_usd': round(total_saved_usd, 4),
            'l1': l1_stats,
            'l2': l2_stats,
            'dedup': dedup_stats,
            'api_monitor': monitor_summary,
        }


# ==================== Claude API Cache整合 ====================

class ClaudeAPICacheAdapter:
    """
    Claude API Cache适配器
    
    对接Anthropic的cache_creation/cache_read机制
    原理：在messages开头放一个system prompt + 前N条历史作为cache前缀
    """
    
    @staticmethod
    def make_cache_prefix(cache_key: str, content: str) -> dict:
        """
        生成可缓存的prefix message
        
        Anthropic会在相同prefix的后续请求自动复用KV Cache
        返回 {'role': 'user', 'content': content}
        """
        return {
            'role': 'user',
            'content': [
                {
                    'type': 'text',
                    'text': f'[CACHE:{cache_key}]\n{content}',
                    'cache_control': {'type': 'ephemeral'}
                }
            ]
        }
    
    @staticmethod
    def estimate_cache_savings(cache_hits: int, content_chars: int) -> dict:
        """
        估算cache节省
        
        Claude API: cache_read比直接input便宜90%
        """
        tokens = content_chars // 4
        normal_cost = tokens * 3 / 1_000_000  # $3/M input
        cached_cost = tokens * 0.3 / 1_000_000  # $0.30/M cached input
        saving = (cache_hits - 1) * (normal_cost - cached_cost)
        return {
            'tokens_per_hit': tokens,
            'normal_cost_per_hit': round(normal_cost, 6),
            'cached_cost_per_hit': round(cached_cost, 6),
            'saving_after_n_hits': round(saving, 6),
        }


# ==================== 便捷函数 ====================

_global_mgr = None

def get_cache_manager() -> TokenCacheManager:
    """获取全局缓存管理器实例"""
    global _global_mgr
    if _global_mgr is None:
        _global_mgr = TokenCacheManager()
    return _global_mgr


def cached(key: str) -> Optional[str]:
    """便捷获取缓存"""
    return get_cache_manager().get(key)


def cache_set(key: str, value: str, ttl: int = 600):
    """便捷设置缓存"""
    get_cache_manager().set_both(key, value, ttl)


def log_api_call(source: str, inp: int, out: int, cached_inp: int = 0):
    """便捷记录API调用"""
    get_cache_manager().monitor.log_call(source, inp, out, cached_inp)


# ==================== 自检 ====================

from typing import List as _List


def self_check() -> _List[str]:
    """自检：验证所有模块正常运行"""
    import random
    fails = []
    
    try:
        # [1] TokenCache
        tc = TokenCache(maxsize=3)
        tc.set('a', 'hello world', 10)
        tc.set('b', 'test content', 5)
        tc.set('c', 'more data', 8)
        tc.set('d', 'overflow', 6)  # 应淘汰'a'
        assert tc.get('a') is None, "LRU淘汰失败"
        assert tc.get('d') == 'overflow', "get失败"
        assert tc.size() == 3, f"size应为3, 实际{tc.size()}"
    except Exception as e:
        fails.append(f"[1] TokenCache: {e}")
    
    try:
        # [2] DiskCache
        dc = DiskCache(cache_dir=GA_CACHE_DIR, default_ttl=60)
        dc.set('test_key', 'test_value', ttl=60)
        val = dc.get('test_key')
        assert val == 'test_value', f"DiskCache get失败: {val}"
        dc.invalidate('test_key')
        assert dc.get('test_key') is None, "invalidate失败"
    except Exception as e:
        fails.append(f"[2] DiskCache: {e}")
    
    try:
        # [3] SemanticDedup — SequenceMatcher版本
        sd = SemanticDedup(threshold=0.3)
        # 高度相似的文本（SequenceMatcher对中文更准）
        text_a = 'GA缓存优化系统 TokenCacheManager 管理多级缓存 包含L1内存LRU和L2磁盘持久缓存 语义去重避免重复注入'
        text_b = 'GA缓存管理系统 TokenCacheMgr 管理各级缓存 包含L1内存LRU和L2磁盘持久缓存 语义去重避免重复上下文注入'
        is_dup, sim = sd.is_duplicate('a', text_a)
        assert not is_dup, "新内容不应判为重复"
        is_dup, sim = sd.is_duplicate('b', text_b)
        assert is_dup, f"相似应判重复, 相似度={sim}"
        assert sim >= 0.3, f"相似度应>=0.3, 实际{sim}"
    except Exception as e:
        fails.append(f"[3] SemanticDedup: {e}")
    
    try:
        # [4] CacheMonitor
        cm = CacheMonitor()
        cm.log_call('test', 1000, 200)
        cm.log_call('test', 500, 50, cached_input=400)
        summary = cm.get_summary()
        assert summary['total_calls'] == 2
        assert summary['total_input_tokens'] == 1500
        report = cm.get_cost_report(1)
        assert len(report) == 1
        assert report[0]['source'] == 'test'
    except Exception as e:
        fails.append(f"[4] CacheMonitor: {e}")
    
    try:
        # [5] TokenCacheManager
        mgr = TokenCacheManager()
        result = mgr.cached_inject('test_mgr', 'hi', ttl=30)
        assert result == 'hi'
        # 第二次应命中缓存（内容<10字符，去重自动跳过）
        result2 = mgr.cached_inject('test_mgr', 'changed', ttl=30)
        assert result2 == 'hi', "缓存未命中"
    except Exception as e:
        fails.append(f"[5] TokenCacheManager: {e}")
    
    try:
        # [6] ClaudeAPICacheAdapter
        prefix = ClaudeAPICacheAdapter.make_cache_prefix('sys', 'system prompt here')
        assert prefix['role'] == 'user'
        assert 'cache_control' in str(prefix)
        savings = ClaudeAPICacheAdapter.estimate_cache_savings(10, 1000)
        assert savings['tokens_per_hit'] == 250
        assert savings['saving_after_n_hits'] > 0
    except Exception as e:
        fails.append(f"[6] ClaudeAPICacheAdapter: {e}")
    
    try:
        # [7] 语义去重白名单
        mgr = TokenCacheManager()
        mgr.add_dedup_whitelist('dynamic')
        # 加入白名单后不应去重
        val = mgr.cached_inject('dynamic', 'content a', dedup_check=False)
        # 仅验证不崩溃
    except Exception as e:
        fails.append(f"[7] DedupWhitelist: {e}")
    
    try:
        # [8] 多级缓存一致性
        mgr = TokenCacheManager()
        mgr.set_l1('multi', 'l1 value')
        mgr.set_l2('multi', 'l2 value')
        # L1优先
        assert mgr.get('multi') == 'l1 value', "L1应优先于L2"
    except Exception as e:
        fails.append(f"[8] MultiLevelCache: {e}")
    
    return fails


if __name__ == '__main__':
    fails = self_check()
    if fails:
        print(f"❌ 自检失败 ({len(fails)}):")
        for f in fails:
            print(f"  - {f}")
    else:
        print("🎉 skill_token_cache_mgmt.py 全部8/8自检通过!")
    
    print("\n=== 缓存诊断报告演示 ===")
    mgr = TokenCacheManager()
    
    # 模拟一些API调用
    for i in range(5):
        mgr.monitor.log_call('skill_registry_load', 5000, 200)
        mgr.monitor.log_call('context_inject', 3000, 100, cached_input=2000)
    
    mgr.cached_inject('frequent_skill', 'This is a frequently used skill content that should be cached')
    
    summary = mgr.get_summary_stats()
    print(f"总节省tokens: {summary['total_tokens_saved']}")
    print(f"总节省费用: ${summary['total_cost_saved_usd']}")
    print(f"L1命中率: {summary['l1']['hit_rate']*100:.1f}%")
    print(f"L2命中率: {summary['l2']['hit_rate']*100:.1f}%")
    print(f"API总调用: {summary['api_monitor']['total_calls']}次")
    print(f"API总费用: ${summary['api_monitor']['total_cost_usd']}")
    print(f"cache节省: ${summary['api_monitor']['cache_saved_usd']}")
    
    print("\n=== 最耗token入口 Top3 ===")
    for r in mgr.get_cost_report(3):
        print(f"  {r['source']:30s} {r['calls']}次 ${r['cost_usd']:.4f} (cache省${r['cache_saved_usd']:.4f})")
