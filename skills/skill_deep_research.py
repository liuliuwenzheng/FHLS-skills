"""
skill_deep_research.py — GA自主深度研究引擎
来源: 骨髓内化自gpt-researcher设计模式 (⭐16k)
目标: 给研究主题 → 自动搜索→爬取→分析→Markdown结构化报告
原则: 纯Python标准库, 无外部依赖, 可串联browser_use+mem0
"""

import urllib.request
import urllib.parse
import urllib.error
import html.parser
import re
import json
import time
from typing import List, Dict, Optional
from dataclasses import dataclass, field


# ═══════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════

@dataclass
class Source:
    """研究来源"""
    url: str
    title: str = ""
    snippet: str = ""
    content: str = ""
    relevance_score: float = 0.0
    fetched: bool = False

@dataclass
class ResearchResult:
    """完整研究结果"""
    topic: str
    query: str
    sources: List[Source] = field(default_factory=list)
    summary: str = ""
    sections: Dict[str, str] = field(default_factory=dict)
    key_findings: List[str] = field(default_factory=list)
    conclusions: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    error: Optional[str] = None


# ═══════════════════════════════════════════
# HTML 提取器 — 纯标准库实现
# ═══════════════════════════════════════════

class HTMLTextExtractor(html.parser.HTMLParser):
    """从HTML中提取纯文本, 无外部依赖"""
    def __init__(self):
        super().__init__()
        self._text_parts = []
        self._skip_tags = {'script', 'style', 'noscript', 'iframe', 'svg'}
        self._skip_depth = 0
        self._current_tag = ""

    def handle_starttag(self, tag, attrs):
        self._current_tag = tag
        if tag in self._skip_tags:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip_depth -= 1
        elif tag in ('p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'div', 'tr', 'blockquote'):
            self._text_parts.append('\n')

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._text_parts.append(text + ' ')

    def get_text(self) -> str:
        raw = ''.join(self._text_parts)
        # 压缩空白
        raw = re.sub(r'\n{3,}', '\n\n', raw)
        raw = re.sub(r'[ \t]+', ' ', raw)
        return raw.strip()


def extract_text_from_html(html_content: str, max_chars: int = 8000) -> str:
    """从HTML提取纯文本"""
    extractor = HTMLTextExtractor()
    try:
        extractor.feed(html_content)
    except Exception:
        pass
    text = extractor.get_text()
    # 只保留有意义的部分
    lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 20]
    text = '\n'.join(lines[:200])  # 最多200行
    if len(text) > max_chars:
        text = text[:max_chars] + '...'
    return text


# ═══════════════════════════════════════════
# 网络获取器
# ═══════════════════════════════════════════

class NetworkFetcher:
    """基于urllib的HTTP获取器, 纯标准库"""

    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def resolve_redirect_url(self, url: str) -> str:
        """解析可能的DDG/跳转URL, 提取真实目标地址"""
        # DDG重定向: https://duckduckgo.com/l/?uddg=https%3A%2F%2Freal.url...
        if 'duckduckgo.com/l/' in url and 'uddg=' in url:
            uddg = re.search(r'uddg=([^&]+)', url)
            if uddg:
                return urllib.parse.unquote(uddg.group(1))
        return url

    def fetch(self, url: str, max_retries: int = 2) -> Optional[str]:
        """获取URL内容, 返回HTML字符串"""
        # 先解析可能的跳转URL
        real_url = self.resolve_redirect_url(url)
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                req = urllib.request.Request(real_url, headers=self.DEFAULT_HEADERS)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    # 尝试用charset解码, 否则utf-8
                    content_type = resp.headers.get('Content-Type', '')
                    charset = 'utf-8'
                    if 'charset=' in content_type:
                        charset = content_type.split('charset=')[-1].split(';')[0].strip()
                    raw = resp.read()
                    try:
                        return raw.decode(charset, errors='replace')
                    except (LookupError, UnicodeDecodeError):
                        return raw.decode('utf-8', errors='replace')
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code}: {e.reason}"
                if e.code == 429:  # 限流, 等待重试
                    time.sleep(2)
                    continue
                break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = str(e)
                time.sleep(1)
        return None


# ═══════════════════════════════════════════
# 搜索引擎接口（纯HTML解析, 不需API）
# ═══════════════════════════════════════════

class SearchEngine:
    """搜索引擎封装 — 用HTML解析搜索结果页"""

    SEARCH_URLS = {
        'duckduckgo': 'https://html.duckduckgo.com/html/?q={query}',
        'google': 'https://www.google.com/search?q={query}&num={num}',
        'bing': 'https://www.bing.com/search?q={query}&count={num}',
    }

    def __init__(self, engine: str = 'duckduckgo', fetcher: Optional[NetworkFetcher] = None):
        self.engine = engine
        self.fetcher = fetcher or NetworkFetcher()

    def search(self, query: str, num_results: int = 5) -> List[dict]:
        """
        搜索网页, 返回 [{url, title, snippet}]
        fallback链: duckduckgo → bing → google
        """
        engines = ['duckduckgo', 'bing', 'google']
        start_idx = engines.index(self.engine) if self.engine in engines else 0

        for idx in range(start_idx, len(engines)):
            eng = engines[idx]
            url = self.SEARCH_URLS[eng].format(
                query=urllib.parse.quote_plus(query),
                num=min(num_results + 2, 10)
            )
            html = self.fetcher.fetch(url)
            if html:
                results = self._parse_search_results(html, eng)
                if results:
                    return results[:num_results]
            time.sleep(0.5)
        return []

    def _parse_search_results(self, html: str, engine: str) -> List[dict]:
        """解析搜索结果"""
        if engine == 'duckduckgo':
            return self._parse_ddg(html)
        elif engine == 'google':
            return self._parse_google(html)
        elif engine == 'bing':
            return self._parse_bing(html)
        return []

    @staticmethod
    def _resolve_ddg_url(href: str) -> str:
        """从DDG重定向链接提取真实URL"""
        # DDG格式: /l/?uddg=https%3A%2F%2Fexample.com&rut=xxx
        uddg_match = re.search(r'uddg=([^&]+)', href)
        if uddg_match:
            return urllib.parse.unquote(uddg_match.group(1))
        # 也可能是直接链接
        if href.startswith('//'):
            return 'https:' + href
        if href.startswith('http'):
            return href
        return href

    def _parse_ddg(self, html: str) -> List[dict]:
        results = []
        # 匹配DDG结果条目 (兼容新版/旧版HTML结构)
        for match in re.finditer(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
            r'.*?(?:<a[^>]*class="result__snippet"[^>]*>|class="result__snippet">)(.*?)(?:</a>|</div>)',
            html, re.DOTALL
        ):
            url = self._resolve_ddg_url(match.group(1))
            title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
            snippet = re.sub(r'<[^>]+>', '', match.group(3)).strip()
            if url and title:
                results.append({'url': url, 'title': title, 'snippet': snippet})
        # 如果没有匹配到旧格式, 尝试新格式
        if not results:
            for match in re.finditer(
                r'<a[^>]*href="(https?://[^"]+)"[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</a>',
                html, re.DOTALL
            ):
                url = match.group(1)
                title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
                if url and title:
                    results.append({'url': url, 'title': title, 'snippet': ''})
        return results

    def _parse_google(self, html: str) -> List[dict]:
        results = []
        # Google搜索结果解析
        for match in re.finditer(
            r'<a[^>]*href\s*=\s*["\'](/url\?q=([^"&\']+)|https?://[^"\']+)["\'][^>]*>'
            r'<h3[^>]*>(.*?)</h3>',
            html, re.DOTALL
        ):
            raw_url = match.group(2) or match.group(1) or ""
            url = urllib.parse.unquote(raw_url) if raw_url.startswith('/url?q=') else raw_url
            title = re.sub(r'<[^>]+>', '', match.group(3)).strip()
            results.append({'url': url, 'title': title, 'snippet': ''})
        return results

    def _parse_bing(self, html: str) -> List[dict]:
        results = []
        for match in re.finditer(
            r'<h2><a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a></h2>',
            html, re.DOTALL
        ):
            url = match.group(1)
            title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
            results.append({'url': url, 'title': title, 'snippet': ''})
        return results


# ═══════════════════════════════════════════
# 内容分析器
# ═══════════════════════════════════════════

class ContentAnalyzer:
    """文本分析 — 关键词提取/相关度评分/摘要"""

    STOP_WORDS = set([
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
        'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
        'would', 'could', 'should', 'may', 'might', 'can', 'shall', 'not',
        'no', 'nor', 'so', 'if', 'than', 'that', 'this', 'these', 'those',
        'it', 'its', 'you', 'your', 'he', 'she', 'they', 'them', 'we', 'our',
        '的', '了', '是', '在', '和', '也', '就', '都', '而', '及', '与',
        '着', '或', '一个', '没有', '我们', '你们', '他们', '这个', '那个',
        '什么', '怎么', '如何', '为什么', '因为', '所以', '但是', '如果',
    ])

    @staticmethod
    def extract_keywords(text: str, top_n: int = 10) -> List[str]:
        """提取高频关键词, 中英文分开匹配"""
        # 英文词: [a-zA-Z]{2,} | 中文词(2字为主): [\u4e00-\u9fff]{2} (避免长词组)
        words = re.findall(r'[a-zA-Z]{2,}|[\u4e00-\u9fff]{2}', text.lower())
        word_counts = {}
        for w in words:
            if w not in ContentAnalyzer.STOP_WORDS and not w.isdigit():
                word_counts[w] = word_counts.get(w, 0) + 1
        sorted_words = sorted(word_counts.items(), key=lambda x: -x[1])
        return [w for w, _ in sorted_words[:top_n]]

    @staticmethod
    def score_relevance(content: str, query: str) -> float:
        """计算内容与查询的相关度"""
        query_terms = set(re.findall(r'[a-zA-Z\u4e00-\u9fff]{2,}', query.lower()))
        if not query_terms:
            return 0.0
        content_lower = content.lower()
        matches = sum(1 for t in query_terms if t in content_lower)
        return matches / len(query_terms)

    @staticmethod
    def extract_sections(text: str) -> Dict[str, str]:
        """按标题分割文本成章节"""
        sections = {}
        lines = text.split('\n')
        current_heading = "概述"
        current_text = []

        for line in lines:
            # 匹配标题行
            heading_match = re.match(r'^#{1,4}\s+(.+)$', line.strip())
            if heading_match:
                if current_text:
                    sections[current_heading] = '\n'.join(current_text).strip()
                current_heading = heading_match.group(1).strip()
                current_text = []
            else:
                current_text.append(line)

        if current_text:
            sections[current_heading] = '\n'.join(current_text).strip()

        return sections

    @staticmethod
    def summarize(text: str, max_sentences: int = 3) -> str:
        """提取关键句子作为摘要"""
        sentences = re.split(r'(?<=[。.!?！？\n])\s*', text)
        # 选择含关键词最多的句子
        scored = []
        for s in sentences:
            s = s.strip()
            if len(s) < 10:
                continue
            # 用sentence中非停用词比例作为质量分
            words = re.findall(r'[a-zA-Z\u4e00-\u9fff]+', s)
            meaningful = sum(1 for w in words if w.lower() not in ContentAnalyzer.STOP_WORDS)
            score = meaningful / max(len(words), 1)
            scored.append((score, s))

        scored.sort(reverse=True)
        top = [s for _, s in scored[:max_sentences]]
        return ' '.join(top) if top else text[:200]


# ═══════════════════════════════════════════
# 核心研究引擎
# ═══════════════════════════════════════════

class DeepResearchEngine:
    """
    深度研究引擎 — 端到端研究管线

    用法:
        engine = DeepResearchEngine()
        result = engine.research("Python异步编程最佳实践")

    可串联:
        from memory.skill_deep_research import DeepResearchEngine
    """

    def __init__(
        self,
        search_engine: str = 'duckduckgo',
        fetcher: Optional[NetworkFetcher] = None,
        analyzer: Optional[ContentAnalyzer] = None,
        max_sources: int = 5,
        max_retries: int = 2
    ):
        self.fetcher = fetcher or NetworkFetcher(timeout=15)
        self.searcher = SearchEngine(engine=search_engine, fetcher=self.fetcher)
        self.analyzer = analyzer or ContentAnalyzer()
        self.max_sources = max_sources
        self.max_retries = max_retries

    def research(self, topic: str, num_sources: int = None) -> ResearchResult:
        """
        执行完整研究流程:
        1. 搜索 → 获取来源列表
        2. 爬取 → 获取页面内容
        3. 分析 → 提取结构
        4. 合成 → 生成Markdown报告
        """
        result = ResearchResult(topic=topic, query=topic)
        num = num_sources or self.max_sources

        # 阶段1: 搜索
        search_results = self.searcher.search(topic, num_results=num)
        if not search_results:
            result.error = "搜索无结果"
            return result

        for sr in search_results:
            source = Source(
                url=sr['url'],
                title=sr['title'],
                snippet=sr['snippet'],
            )
            result.sources.append(source)

        # 阶段2: 爬取
        for source in result.sources:
            content = self.fetcher.fetch(source.url)
            if content:
                source.content = extract_text_from_html(content)
                source.fetched = True
                # 计算相关度
                source.relevance_score = self.analyzer.score_relevance(source.content, topic)
            time.sleep(0.3)  # 爬取间隔

        # 阶段3: 分析
        self._analyze_results(result)

        # 阶段4: 合成
        self._synthesize(result)

        return result

    def _analyze_results(self, result: ResearchResult):
        """分析爬取到的内容"""
        # 按相关度排序
        fetched = [s for s in result.sources if s.fetched]
        fetched.sort(key=lambda s: -s.relevance_score)

        if not fetched:
            return

        # 提取各来源章节结构
        for source in fetched[:3]:  # 只分析前3个
            sections = self.analyzer.extract_sections(source.content)
            if sections:
                for heading, text in sections.items():
                    if heading not in result.sections:
                        result.sections[heading] = ""
                    # 合并内容
                    result.sections[heading] += f"\n> 来源: [{source.title}]({source.url})\n{text[:500]}\n"

        # 提取关键发现
        all_content = ' '.join(s.content for s in fetched if s.content)
        keywords = self.analyzer.extract_keywords(all_content, top_n=15)
        result.key_findings = keywords[:8]

    def _synthesize(self, result: ResearchResult):
        """合成为Markdown报告"""
        fetched = [s for s in result.sources if s.fetched]
        fetched.sort(key=lambda s: -s.relevance_score)

        # 摘要
        if fetched:
            top_content = fetched[0].content[:1000] if fetched[0].content else ""
            if top_content:
                result.summary = self.analyzer.summarize(top_content)

        # 结论
        result.conclusions = [
            f"共检索到 {len(result.sources)} 个来源, 成功抓取 {len(fetched)} 个页面",
            f"相关度最高的来源: {fetched[0].title if fetched else '无'}",
        ]

        # 参考文献
        for s in result.sources:
            result.references.append(f"- [{s.title or s.url}]({s.url})")

    def render_markdown(self, result: ResearchResult) -> str:
        """将研究结果渲染为Markdown"""
        lines = []

        lines.append(f"# 深度研究: {result.topic}")
        lines.append("")

        # 元信息
        lines.append(f"> **查询**: {result.query}")
        lines.append(f"> **来源数**: {len(result.sources)} | **已抓取**: {sum(1 for s in result.sources if s.fetched)}")
        lines.append("")

        if result.error:
            lines.append(f"⚠️ **错误**: {result.error}")
            lines.append("")
            return '\n'.join(lines)

        # 摘要
        if result.summary:
            lines.append("## 📝 摘要")
            lines.append("")
            lines.append(result.summary)
            lines.append("")

        # 关键发现
        if result.key_findings:
            lines.append("## 🔑 关键发现")
            lines.append("")
            for f in result.key_findings[:8]:
                lines.append(f"- **{f}**")
            lines.append("")

        # 详细分析
        if result.sections:
            lines.append("## 📖 详细分析")
            lines.append("")
            for heading, text in result.sections.items():
                if text.strip():
                    lines.append(f"### {heading}")
                    lines.append("")
                    lines.append(text[:800])
                    lines.append("")

        # 结论
        if result.conclusions:
            lines.append("## ✅ 结论")
            lines.append("")
            for c in result.conclusions:
                lines.append(f"- {c}")
            lines.append("")

        # 参考文献
        if result.references:
            lines.append("## 📚 参考文献")
            lines.append("")
            for r in result.references:
                lines.append(r)
            lines.append("")

        return '\n'.join(lines)


# ═══════════════════════════════════════════
# 便捷API
# ═══════════════════════════════════════════

def research(topic: str, num_sources: int = 5, engine: str = 'duckduckgo') -> str:
    """
    一键研究：输入主题 → 返回Markdown研究结果

    示例:
        report = research("Python asyncio vs goroutines")
        print(report)
    """
    eng = DeepResearchEngine(search_engine=engine, max_sources=num_sources)
    result = eng.research(topic)
    return eng.render_markdown(result)


def quick_research(topic: str, num_sources: int = 3) -> Dict:
    """
    快速研究：返回结构化数据而非Markdown

    示例:
        data = quick_research("量子计算进展")
        print(data['summary'])
        print(data['key_findings'])
    """
    eng = DeepResearchEngine(max_sources=num_sources)
    result = eng.research(topic)
    return {
        'topic': result.topic,
        'summary': result.summary,
        'key_findings': result.key_findings,
        'conclusions': result.conclusions,
        'source_count': len(result.sources),
        'fetched_count': sum(1 for s in result.sources if s.fetched),
    }


# ═══════════════════════════════════════════
# 注册到技能架构
# ═══════════════════════════════════════════

def get_skill_info() -> dict:
    """返回技能元信息, 供SkillOrchestrator注册用"""
    return {
        'name': 'deep_research',
        'version': '1.0.0',
        'description': '深度研究引擎 — 搜索→爬取→分析→Markdown报告, 纯Python标准库',
        'author': '嘻嘻 GA',
        'dependencies': [],  # 无外部依赖
        'entry_points': ['research', 'quick_research', 'DeepResearchEngine'],
        'config': {
            'default_engine': 'duckduckgo',
            'max_sources': 5,
            'timeout': 15,
        }
    }


if __name__ == '__main__':
    # 快速演示
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "Python异步编程入门"
    print(f"🔍 研究主题: {topic}")
    print("=" * 60)
    report = research(topic, num_sources=3)
    print(report)
