"""
skill_pretext.py — Pretext 骨髓内化 (chenglou, 47.5k⭐)
Pure Python text measurement & layout engine (DOM-free)
核心哲学: prepare(预处理+测量) → layout(纯算术断行), 避免reflow

架构:
  TextMeasurer   → 字体测量抽象 (PIL/系统)
  TextSegmenter  → 文本分段/标准化/Unicode断行规则
  TextLayouter   → 行布局核心
  RichInline     → 富文本行内布局
  PretextEngine  → 统一入口 prepare/layout API

依赖: Pillow (测量), unicodedata2 (断行,可选)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

try:
    from PIL import ImageFont, ImageDraw, Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ──────────────────────────────────────────────
# [1] TextMeasurer — 字体测量抽象层
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class FontSpec:
    """字体规格, 等同CSS font shorthand"""
    family: str        # 如 'Inter', 'sans-serif'
    size: float        # px
    weight: int = 400  # 100-900
    italic: bool = False

    def to_css(self) -> str:
        w = f"{self.weight} " if self.weight != 400 else ""
        i = "italic " if self.italic else ""
        return f"{i}{w}{self.size}px {self.family}"

    def to_pil_font_path(self) -> Optional[str]:
        """尝试匹配系统字体路径"""
        return None  # 由外部注册


class TextMeasurer:
    """
    文本测量抽象层
    pretext用Canvas measureText做ground truth
    Python侧: 优先PIL ImageFont.getbbox, 回退字符宽度估算
    """

    _pil_fonts: dict = {}  # cache: font_key -> ImageFont.FreeTypeFont

    @classmethod
    def measure_text(cls, text: str, font_spec: Union[str, FontSpec],
                     letter_spacing: float = 0) -> float:
        """
        测量单行文本像素宽度
        对应pretext Canvas measureText
        """
        if isinstance(font_spec, str):
            font_spec = cls._parse_font_string(font_spec)

        if HAS_PIL:
            try:
                font = cls._get_pil_font(font_spec)
                bbox = font.getbbox(text)
                w = bbox[2] - bbox[0]
                if letter_spacing and len(text) > 1:
                    w += letter_spacing * (len(text) - 1)
                return w
            except Exception:
                pass

        # 回退: 字符级宽度估算 (拉丁 0.6em, CJK 1em)
        return cls._estimate_width(text, font_spec.size)

    @classmethod
    def _parse_font_string(cls, s: str) -> FontSpec:
        """解析 'italic 700 16px Inter' 格式"""
        italic = 'italic' in s
        w = 400
        for part in s.split():
            if part.isdigit() and 100 <= int(part) <= 900:
                w = int(part)
        # 提取size和family
        m = re.search(r'(\d+(?:\.\d+)?)px\s+(.+)', s)
        if m:
            size = float(m.group(1))
            family = m.group(2).strip().strip("'\"")
        else:
            size = 16
            family = s.split()[-1] if s.split() else 'sans-serif'
        return FontSpec(family, size, weight=w, italic=italic)

    @classmethod
    def _get_pil_font(cls, spec: FontSpec) -> ImageFont.FreeTypeFont:
        key = spec.to_css()
        if key not in cls._pil_fonts:
            # 尝试系统字体 + 默认回退
            path = cls._find_font_path(spec.family)
            try:
                cls._pil_fonts[key] = ImageFont.truetype(path or "arial.ttf",
                                                         int(spec.size))
            except Exception:
                cls._pil_fonts[key] = ImageFont.load_default()
        return cls._pil_fonts[key]

    @staticmethod
    def _find_font_path(family: str) -> Optional[str]:
        """搜索系统字体路径 (简化版)"""
        if not HAS_PIL:
            return None
        # 常用字体映射
        common = {
            'arial': 'arial.ttf',
            'sans-serif': 'arial.ttf',
            'serif': 'times.ttf',
            'monospace': 'cour.ttf',
        }
        base = common.get(family.lower())
        if base:
            import os
            for d in ['C:\\Windows\\Fonts', '/usr/share/fonts',
                      '/System/Library/Fonts']:
                p = os.path.join(d, base)
                if os.path.exists(p):
                    return p
        return None

    @staticmethod
    def _estimate_width(text: str, font_size: float) -> float:
        """字符宽度估算"""
        w = 0.0
        for ch in text:
            cp = ord(ch)
            if cp <= 0x7F:
                w += 0.6  # ASCII近似0.6em
            elif 0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F:
                w += 1.0  # CJK 1em
            elif 0x0600 <= cp <= 0x06FF:
                w += 0.7  # Arabic
            else:
                w += 0.65
        return w * font_size


# ──────────────────────────────────────────────
# [2] TextSegmenter — 文本分段/标准化/断行规则
# ──────────────────────────────────────────────

# Unicode行断属性 (精简版, 完整见UAX #14)
LB_MANDATORY = {0x000A, 0x000B, 0x000C, 0x000D, 0x0085, 0x2028, 0x2029}
LB_GLUE = {0x00A0, 0x202F, 0x2060}  # 不换行空格
LB_OPEN = set()   # 开括号 (简化)
LB_CLOSE = set()  # 闭括号 (简化)


@dataclass
class TextSegment:
    """文本段落中的一个segment"""
    text: str
    width: float       # 测量宽度
    is_break: bool = False   # 是否断行点
    is_mandatory: bool = False  # 强制换行


class TextSegmenter:
    """
    文本分段/标准化 + Unicode断行规则
    对应pretext analysis.ts + line-break.ts
    
    prepare阶段: 
      1. 标准化空白 (whitespace normalization)
      2. 分段 (grapheme/word segmentation)
      3. 测量每个segment的宽度
      4. 应用glue规则
    """

    def __init__(self, measurer: Optional[TextMeasurer] = None):
        self.measurer = measurer or TextMeasurer()

    def normalize_whitespace(self, text: str,
                             white_space: str = 'normal') -> str:
        """
        标准化空白
        white_space='normal': 合并空格, 忽略首尾, tab→space
        white_space='pre-wrap': 保留换行, 合并空格
        """
        if white_space == 'normal':
            # 折叠空白
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n+', ' ', text)
            return text.strip()
        elif white_space == 'pre-wrap':
            # 保留换行, 折叠水平空白
            text = re.sub(r'[ \t]+', ' ', text)
            return text
        return text

    def segment(self, text: str, font_spec: FontSpec,
                options: Optional[dict] = None) -> List[TextSegment]:
        """
        对应pretext prepare()核心逻辑
        返回TextSegment列表, 每个segment含宽度
        """
        opts = options or {}
        white_space = opts.get('whiteSpace', 'normal')
        word_break = opts.get('wordBreak', 'normal')
        letter_spacing = opts.get('letterSpacing', 0)

        text = self.normalize_whitespace(text, white_space)

        segments: List[TextSegment] = []

        # 强制断行分段 (硬换行)
        hard_lines = text.split('\n')

        for li, line in enumerate(hard_lines):
            if li > 0:
                segments.append(TextSegment('\n', 0, is_break=True,
                                            is_mandatory=True))

            if not line:
                continue

            # word分段: 按空白/标点切分
            words = self._split_words(line, word_break)

            for wi, word in enumerate(words):
                if wi > 0:
                    # 插入空格segment
                    space_w = self.measurer.measure_text(
                        ' ', font_spec, letter_spacing)
                    segments.append(TextSegment(' ', space_w))

                if word:
                    word_w = self.measurer.measure_text(
                        word, font_spec, letter_spacing)
                    segments.append(TextSegment(word, word_w))

        return segments

    def _split_words(self, text: str,
                     word_break: str = 'normal') -> List[str]:
        """按空白/标点分word"""
        if word_break == 'keep-all':
            # CJK不按字断行
            return re.findall(r'[\u4e00-\u9fff]+|[^\u4e00-\u9fff\s]+|\s+', text)
        # normal: 空格 + 可选标点
        return re.findall(r'\S+\s*', text) or [text]


# ──────────────────────────────────────────────
# [3] TextLayouter — 行布局核心
# ──────────────────────────────────────────────

@dataclass
class LayoutLine:
    """布局结果的一行"""
    text: str
    width: float       # 行实际宽度 (px)
    start_offset: int = 0   # 在原文中的起始偏移
    end_offset: int = 0     # 结束偏移
    segments: list = field(default_factory=list)


@dataclass
class LayoutResult:
    """完整布局结果"""
    height: float     # 总高度 (px)
    line_count: int
    lines: List[LayoutLine] = field(default_factory=list)
    max_line_width: float = 0.0


class TextLayouter:
    """
    纯算术行布局核心
    对应pretext layout.ts
    
    核心假设: prepare()后 segments宽度已知
    layout()只做纯算术 → 快, 无DOM reflow
    """

    def __init__(self, measurer: Optional[TextMeasurer] = None):
        self.measurer = measurer or TextMeasurer()

    def layout(self, segments: List[TextSegment],
               max_width: float, line_height: float) -> LayoutResult:
        """
        对应pretext layout()
        纯算术: 把segment逐个装入行, 超宽就断行
        """
        lines: List[LayoutLine] = []
        cur_line = ''
        cur_width = 0.0
        cur_segs: list = []
        start_offset = 0
        offset = 0
        max_line_w = 0.0

        for seg in segments:
            if seg.is_mandatory:
                # 强制换行
                if cur_line or cur_segs:
                    lines.append(LayoutLine(
                        text=cur_line.strip(),
                        width=cur_width,
                        start_offset=start_offset,
                        end_offset=start_offset + len(cur_line.rstrip()),
                        segments=list(cur_segs),
                    ))
                    max_line_w = max(max_line_w, cur_width)
                cur_line = ''
                cur_width = 0.0
                cur_segs = []
                start_offset = offset
                continue

            # 尝试加入当前行
            if seg.text == ' ' and not cur_line:
                # 行首空格跳过
                offset += 1
                continue

            new_width = cur_width + seg.width if cur_line else seg.width

            if new_width > max_width and cur_line:
                # 断行
                lines.append(LayoutLine(
                    text=cur_line.strip(),
                    width=cur_width,
                    start_offset=start_offset,
                    end_offset=start_offset + len(cur_line.rstrip()),
                    segments=list(cur_segs),
                ))
                max_line_w = max(max_line_w, cur_width)
                cur_line = seg.text if seg.text != ' ' else ''
                cur_width = seg.width if seg.text != ' ' else 0.0
                cur_segs = [seg] if seg.text != ' ' else []
                start_offset = offset
            else:
                cur_line += seg.text
                cur_width = new_width
                cur_segs.append(seg)

            offset += len(seg.text)

        # 最后一行
        if cur_line:
            lines.append(LayoutLine(
                text=cur_line.strip(),
                width=cur_width,
                start_offset=start_offset,
                end_offset=start_offset + len(cur_line.rstrip()),
                segments=list(cur_segs),
            ))
            max_line_w = max(max_line_w, cur_width)

        height = len(lines) * line_height if lines else 0.0
        return LayoutResult(
            height=height,
            line_count=len(lines),
            lines=lines,
            max_line_width=max_line_w,
        )

    def layout_next_line(self, segments: List[TextSegment],
                         cursor_idx: int,
                         max_width: float) -> Tuple[Optional[LayoutLine], int]:
        """
        逐行布局 (流式排版)
        对应pretext layoutNextLineRange
        用于: 环绕浮动元素, 可变宽度排版
        """
        if cursor_idx >= len(segments):
            return None, cursor_idx

        line = ''
        width = 0.0
        line_segs: list = []
        i = cursor_idx

        while i < len(segments):
            seg = segments[i]
            if seg.is_mandatory:
                i += 1
                break
            if seg.text == ' ' and not line:
                i += 1
                continue
            nw = width + seg.width if line else seg.width
            if nw > max_width and line:
                break
            line += seg.text
            width = nw
            line_segs.append(seg)
            i += 1

        if not line:
            # 单个word超宽 → 强制插入
            if i < len(segments) and segments[i].text != ' ':
                seg = segments[i]
                line = seg.text
                width = seg.width
                line_segs.append(seg)
                i += 1

        if line:
            return LayoutLine(
                text=line.strip(),
                width=width,
                segments=line_segs,
            ), i
        return None, cursor_idx


# ──────────────────────────────────────────────
# [4] RichInline — 富文本行内布局
# ──────────────────────────────────────────────

@dataclass
class RichInlineItem:
    """富文本文段, 对应pretext RichInlineItem"""
    text: str
    font: Union[str, FontSpec]  # CSS font 或 FontSpec
    break_: str = 'normal'      # 'normal' | 'never'
    extra_width: float = 0.0    # 额外chrome宽度 (chip/pill)


@dataclass
class RichInlineFragment:
    """行内片段"""
    item_index: int
    text: str
    width: float
    gap_before: float = 0.0


@dataclass
class RichInlineLine:
    """富文本行"""
    fragments: List[RichInlineFragment]
    width: float


class RichInlineLayouter:
    """
    富文本行内布局
    对应pretext rich-inline.ts
    
    支持: 多字体混合, break:never (chip/pill), extraWidth
    """

    def __init__(self, measurer: Optional[TextMeasurer] = None):
        self.measurer = measurer or TextMeasurer()

    def prepare(self, items: List[RichInlineItem],
                options: Optional[dict] = None) -> list:
        """预处理所有富文本文段, 测量每个字符"""
        prepared = []
        for item in items:
            font_spec = (self.measurer._parse_font_string(item.font)
                         if isinstance(item.font, str) else item.font)
            chars = []
            for ch in item.text:
                w = self.measurer.measure_text(ch, font_spec)
                chars.append({'char': ch, 'width': w})
            prepared.append({
                'item': item,
                'font_spec': font_spec,
                'chars': chars,
                'total_width': sum(c['width'] for c in chars),
            })
        return prepared

    def layout(self, prepared: list, max_width: float,
               line_height: float) -> List[RichInlineLine]:
        """布局富文本"""
        lines: List[RichInlineLine] = []
        cur_frags: List[RichInlineFragment] = []
        cur_width = 0.0

        for pi, p in enumerate(prepared):
            item = p['item']
            if item.break_ == 'never':
                # 原子item, 不断行
                total_w = p['total_width'] + item.extra_width
                if cur_width + total_w > max_width and cur_frags:
                    lines.append(RichInlineLine(list(cur_frags), cur_width))
                    cur_frags = []
                    cur_width = 0.0
                cur_frags.append(RichInlineFragment(
                    pi, item.text, total_w))
                cur_width += total_w
            else:
                # 可断行: 逐字符尝试
                for ch in p['chars']:
                    ch_w = ch['width']
                    if cur_width + ch_w > max_width and cur_frags:
                        lines.append(RichInlineLine(
                            list(cur_frags), cur_width))
                        cur_frags = []
                        cur_width = 0.0
                    if not cur_frags or cur_frags[-1].item_index != pi:
                        cur_frags.append(RichInlineFragment(
                            pi, ch['char'], ch_w))
                    else:
                        cur_frags[-1].text += ch['char']
                        cur_frags[-1].width += ch_w
                    cur_width += ch_w

        if cur_frags:
            lines.append(RichInlineLine(list(cur_frags), cur_width))

        return lines


# ──────────────────────────────────────────────
# [5] PretextEngine — 统一入口API
# ──────────────────────────────────────────────

class PretextEngine:
    """
    统一入口: prepare() + layout()
    对应pretext @chenglou/pretext 顶层API
    
    用法:
        engine = PretextEngine()
        p = engine.prepare("Hello 世界", "16px Inter")
        r = engine.layout(p, 320, 24)
        print(f"高度{r.height}px, {r.line_count}行")
    """

    def __init__(self):
        self.measurer = TextMeasurer()
        self.segmenter = TextSegmenter(self.measurer)
        self.layouter = TextLayouter(self.measurer)
        self._cache: dict = {}

    def prepare(self, text: str, font: Union[str, FontSpec],
                options: Optional[dict] = None) -> dict:
        """
        对应pretext prepare()
        一次性预处理+测量, 返回opaque handle
        
        Args:
            text: 待测量文本
            font: CSS font字符串 或 FontSpec
            options: {whiteSpace, wordBreak, letterSpacing}
        Returns:
            dict: prepared handle (传给layout)
        """
        if isinstance(font, str):
            font = self.measurer._parse_font_string(font)

        segments = self.segmenter.segment(text, font, options)
        total_width = sum(s.width for s in segments if not s.is_mandatory)

        handle = {
            'text': text,
            'font': font,
            'options': options or {},
            'segments': segments,
            'total_width': total_width,
            'segment_count': len([s for s in segments if not s.is_mandatory]),
        }
        return handle

    def layout(self, prepared: dict, max_width: float,
               line_height: float) -> LayoutResult:
        """
        对应pretext layout()
        纯算术, 无DOM reflow
        
        Args:
            prepared: prepare()的返回值
            max_width: 最大行宽 (px)
            line_height: 行高 (px)
        Returns:
            LayoutResult: {height, line_count, lines, max_line_width}
        """
        segments = prepared['segments']
        return self.layouter.layout(segments, max_width, line_height)

    def prepare_with_segments(self, text: str, font: Union[str, FontSpec],
                              options: Optional[dict] = None) -> dict:
        """返回含segment详情的prepared handle"""
        handle = self.prepare(text, font, options)
        handle['with_segments'] = True
        return handle

    def layout_with_lines(self, prepared: dict, max_width: float,
                          line_height: float) -> LayoutResult:
        """layout并返回lines详情"""
        result = self.layout(prepared, max_width, line_height)
        return result

    def measure_line_stats(self, prepared: dict,
                           max_width: float) -> dict:
        """只统计行数/最大宽度, 不构建字符串"""
        segments = prepared['segments']
        result = self.layouter.layout(segments, max_width, 1)
        return {
            'line_count': result.line_count,
            'max_line_width': result.max_line_width,
        }

    def clear_cache(self) -> None:
        """清除内部缓存"""
        self._cache.clear()
        if HAS_PIL:
            TextMeasurer._pil_fonts.clear()

    def set_locale(self, locale: Optional[str] = None) -> None:
        """设置locale (骨架)"""
        self.clear_cache()
        self._locale = locale


# ──────────────────────────────────────────────
# 自检函数
# ──────────────────────────────────────────────

from typing import List as _List


def self_check() -> _List[str]:
    """
    自检: FontSpec → TextMeasurer → TextSegmenter → TextLayouter → PretextEngine
    返回失败列表, 空列表=全通过
    """
    fails = []

    # [1] FontSpec + TextMeasurer
    try:
        fs = FontSpec('Inter', 16, weight=500)
        assert fs.to_css() == '500 16px Inter', f"to_css: {fs.to_css()}"
        # 估算宽度
        w = TextMeasurer.measure_text('Hello', '16px Inter')
        assert w > 0, f"measure_text returned {w}"
    except Exception as e:
        fails.append(f"[1] TextMeasurer: {e}")

    # [2] TextSegmenter
    try:
        seg = TextSegmenter()
        tokens = seg.segment('Hello World', FontSpec('Arial', 16))
        assert len(tokens) >= 2, f"segment returned {len(tokens)}"
        # pre-wrap
        tokens2 = seg.segment('Hello\nWorld', FontSpec('Arial', 16),
                              {'whiteSpace': 'pre-wrap'})
        has_break = any(t.is_mandatory for t in tokens2)
        assert has_break, "pre-wrap 应含\\n强制断行"
    except Exception as e:
        fails.append(f"[2] TextSegmenter: {e}")

    # [3] TextLayouter
    try:
        seg = TextSegmenter()
        segments = seg.segment('Hello World This Is A Test',
                               FontSpec('Arial', 16))
        lay = TextLayouter()
        result = lay.layout(segments, 100, 24)
        assert result.line_count >= 2, f"layout returned {result.line_count}行"
        assert result.height > 0
    except Exception as e:
        fails.append(f"[3] TextLayouter: {e}")

    # [4] RichInline
    try:
        rl = RichInlineLayouter()
        items = [
            RichInlineItem('Hello ', '16px Arial'),
            RichInlineItem('World', 'bold 16px Arial', extra_width=10),
        ]
        prepared = rl.prepare(items)
        assert len(prepared) == 2
        lines = rl.layout(prepared, 200, 24)
        assert len(lines) >= 1
    except Exception as e:
        fails.append(f"[4] RichInline: {e}")

    # [5] PretextEngine 端到端
    try:
        engine = PretextEngine()
        p = engine.prepare('AGI 春天到了 🚀', '16px Inter')
        assert 'segments' in p
        assert p['segment_count'] > 0

        r = engine.layout(p, 200, 24)
        assert r.line_count >= 1
        assert r.height > 0

        # 空字符串
        p2 = engine.prepare('', '16px Inter')
        r2 = engine.layout(p2, 200, 24)
        assert r2.line_count == 0
        assert r2.height == 0

        # prepare_with_segments + layout_with_lines
        p3 = engine.prepare_with_segments('Multi\nLine Text', '16px Arial',
                                          {'whiteSpace': 'pre-wrap'})
        r3 = engine.layout_with_lines(p3, 200, 24)
        assert r3.line_count >= 2

        # measure_line_stats
        stats = engine.measure_line_stats(p, 200)
        assert 'line_count' in stats
        assert 'max_line_width' in stats

        # clear_cache
        engine.clear_cache()
    except Exception as e:
        fails.append(f"[5] PretextEngine: {e}")

    return fails


if __name__ == '__main__':
    fails = self_check()
    if fails:
        print(f"❌ 自检失败 ({len(fails)}):")
        for f in fails:
            print(f"  - {f}")
    else:
        print("🎉 skill_pretext.py 全部5/5自检通过!")

    # 演示
    print("\n=== Pretext 演示 ===")
    engine = PretextEngine()
    text = "Pretext is a pure JavaScript/TypeScript library for multiline text measurement & layout. Fast, accurate & supports all the languages you didn't even know about."
    p = engine.prepare(text, '16px Inter')
    r = engine.layout(p, 320, 24)
    print(f"文本: {text[:50]}...")
    print(f"   宽度320px, 行高24px → {r.line_count}行, 高度{r.height}px")
    print(f"   最宽行: {r.max_line_width:.1f}px")
    for i, line in enumerate(r.lines[:3]):
        print(f"   第{i+1}行: \"{line.text[:40]:40s}\" {line.width:.1f}px")
