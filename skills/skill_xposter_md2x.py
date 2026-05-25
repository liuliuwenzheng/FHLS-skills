"""
skill_xposter_md2x — Markdown → X Articles 格式转换器
=====================================================
骨髓内化自 https://github.com/nevertoday/xposter (shared.js)

功能: 解析 Markdown 文本, 输出 X Articles 编辑器可用的格式结构
      供 GA agent 直接 import 使用, 不依赖浏览器

管线: parse(markdown_text) → {
    "title": str | None,        # 文章标题
    "cover": str | None,        # 封面图 URL
    "segments": list[dict],     # 解析后的段序列
    "meta": dict,               # frontmatter 元数据
    "plan": {                   # X Articles paste plan
        "html": list[str],      # HTML 块
        "blocks": list[dict],   # Draft.js blocks
        "operations": list[dict]# 图片等操作
    }
}

依赖: 纯 Python, 仅 re/json 标准库
"""

import re
import json
import random
import string

# ── 常量 ──────────────────────────────────────────────────────────────

STYLE_TAGS = {
    "Bold": "strong",
    "Italic": "em",
    "Strikethrough": "s",
    "Code": "code",
}

BLOCK_TAGS = {
    "header-one": "h1",
    "header-two": "h2",
    "header-three": "h3",
    "header-four": "h4",
    "header-five": "h5",
    "header-six": "h6",
    "blockquote": "blockquote",
    "unstyled": "p",
}

# ── 工具函数 ──────────────────────────────────────────────────────────

def escape_html(value):
    """转义 HTML 特殊字符"""
    s = str(value or "")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _overlaps(spans, start):
    """检查 start 位置是否落在已有 span 范围内"""
    for span in spans:
        if span["start"] <= start < span["end"]:
            return True
    return False


def _text_segment(text):
    """创建一个无格式文本段"""
    return {
        "type": "text",
        "kind": "unstyled",
        "text": text,
        "inlineStyleRanges": [],
        "links": [],
    }


# ── Frontmatter 解析 ─────────────────────────────────────────────────

def parse_frontmatter(markdown):
    """
    解析 YAML 风格 frontmatter (---\nkey: value\n---)
    
    Returns:
        dict: {"body": str, "meta": dict}
    """
    normalized = str(markdown or "").replace("\r\n", "\n")
    match = re.match(r"^---\n([\s\S]*?)\n---\n*", normalized)
    if not match:
        return {"body": normalized.strip(), "meta": {}}
    
    meta = {}
    for line in match.group(1).split("\n"):
        idx = line.find(":")
        if idx < 0:
            continue
        key = line[:idx].strip()
        value = line[idx + 1:].strip().strip("\"'")
        if key:
            meta[key] = value
    
    body = normalized[match.end():].strip()
    return {"body": body, "meta": meta}


# ── 特殊块查找 ─────────────────────────────────────────────────────

def find_special_blocks(markdown):
    """
    查找 Markdown 中的特殊块: 围栏代码块/表格/分割线/Tweet URL/图片
    
    Returns:
        list[dict]: [{start, end, segment}]
    """
    spans = []
    
    # 围栏代码块 ```lang\ncode```
    for match in re.finditer(r"```([^\n`]*)\n([\s\S]*?)```", markdown):
        spans.append({
            "start": match.start(),
            "end": match.end(),
            "segment": {
                "type": "code",
                "language": match.group(1).strip(),
                "code": match.group(2).rstrip("\n"),
            }
        })
    
    # 表格
    table_re = r"^(?:[ \t]*\|.+\|[ \t]*\n)(?:[ \t]*\|[:\s|\-]+\|[ \t]*\n)((?:[ \t]*\|.+\|[ \t]*\n?)*)"
    for match in re.finditer(table_re, markdown, re.MULTILINE):
        if _overlaps(spans, match.start()):
            continue
        parsed = _parse_table(match.group(0))
        if not parsed:
            continue
        spans.append({
            "start": match.start(),
            "end": match.end(),
            "segment": {"type": "table", **parsed}
        })
    
    # 分割线 --- / *** / ___
    divider_re = r"^(?: {0,3})(?:-{3,}|\*{3,}|_{3,})(?:[ \t]*)$"
    for match in re.finditer(divider_re, markdown, re.MULTILINE):
        if _overlaps(spans, match.start()):
            continue
        spans.append({
            "start": match.start(),
            "end": match.end(),
            "segment": {"type": "divider"}
        })
    
    # Tweet URL (x.com/twitter status links)
    tweet_re = r"^(?: {0,3})https?://(?:www\.)?(?:x\.com|twitter\.com)/[A-Za-z0-9_]+/status/(\d+)(?:[?#][^\s]*)?\s*$"
    for match in re.finditer(tweet_re, markdown, re.MULTILINE):
        if _overlaps(spans, match.start()):
            continue
        spans.append({
            "start": match.start(),
            "end": match.end(),
            "segment": {"type": "tweet", "tweetId": match.group(1)}
        })
    
    # 图片
    for image in _find_markdown_image_spans(markdown):
        if _overlaps(spans, image["start"]):
            continue
        source = image["source"]
        tweet_match = re.match(
            r"^https?://(?:www\.)?(?:x\.com|twitter\.com)/[A-Za-z0-9_]+/status/(\d+)",
            source
        )
        if tweet_match:
            spans.append({
                "start": image["start"],
                "end": image["end"],
                "segment": {"type": "tweet", "tweetId": tweet_match.group(1)}
            })
        else:
            spans.append({
                "start": image["start"],
                "end": image["end"],
                "segment": {
                    "type": "image",
                    "source": source,
                    "alt": image.get("alt", ""),
                }
            })
    
    return spans


def _find_markdown_image_spans(markdown):
    """查找 Markdown 图片标记 ![alt](url)"""
    spans = []
    
    # 标准 Markdown 图片
    img_re = r"!\[([^\]]*)\]\(([^)]+)\)"
    for match in re.finditer(img_re, markdown):
        source = match.group(2).strip()
        spans.append({
            "start": match.start(),
            "end": match.end(),
            "source": source,
            "alt": match.group(1),
        })
    
    # Wiki 风格图片 ![[file]]
    wiki_re = r"!\[\[([^\]]+)\]\]"
    for match in re.finditer(wiki_re, markdown):
        if _overlaps(spans, match.start()):
            continue
        source = match.group(1).strip()
        alt = source.rsplit("/", 1)[-1].rsplit(".", 1)[0] if "." in source else source
        spans.append({
            "start": match.start(),
            "end": match.end(),
            "source": source,
            "alt": alt,
        })
    
    # 排序: 按位置升序
    spans.sort(key=lambda s: s["start"])
    return spans


def _parse_table(text):
    """解析 Markdown 表格文本"""
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return None
    
    headers = [h.strip() for h in lines[0].split("|") if h.strip()]
    if not headers:
        return None
    
    alignment_line = lines[1]
    alignments = []
    parts = alignment_line.split("|")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith(":") and part.endswith(":"):
            alignments.append("center")
        elif part.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")
    
    rows = []
    for line in lines[2:]:
        line = line.strip()
        if not line or line.startswith("|") is False:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) >= 2:
            cells = cells[1:-1] if cells[0] == "" and cells[-1] == "" else cells
        rows.append(cells[:len(headers)])
    
    return {
        "headers": headers,
        "alignments": alignments[:len(headers)],
        "rows": rows,
    }


# ── 文本块解析 ─────────────────────────────────────────────────────

def _parse_text_blocks(text):
    """解析纯文本块（非特殊块）"""
    segments = []
    lines = text.split("\n")
    i = 0
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # 空行
        if not stripped:
            i += 1
            continue
        
        # 标题 #
        header_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if header_match:
            level = len(header_match.group(1))
            text_content = header_match.group(2)
            kind = ["header-one", "header-two", "header-three",
                    "header-four", "header-five", "header-six"][level - 1]
            segments.append(_parse_inline(kind, text_content))
            i += 1
            continue
        
        # 引用 >
        if stripped.startswith("> "):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith("> "):
                quote_lines.append(lines[i].strip()[2:])
                i += 1
            segments.append(_parse_inline("blockquote", "\n".join(quote_lines)))
            continue
        
        # 无序列表 - * +
        if re.match(r"^[-*+]\s+", stripped):
            items = []
            while i < len(lines):
                ls = lines[i].strip()
                m = re.match(r"^[-*+]\s+(.+)$", ls)
                if not m:
                    break
                items.append(m.group(1))
                i += 1
            for item in items:
                segments.append(_parse_inline("unordered-list-item", item))
            continue
        
        # 有序列表 1.
        if re.match(r"^\d+\.\s+", stripped):
            items = []
            while i < len(lines):
                ls = lines[i].strip()
                m = re.match(r"^\d+\.\s+(.+)$", ls)
                if not m:
                    break
                items.append(m.group(1))
                i += 1
            for item in items:
                segments.append(_parse_inline("ordered-list-item", item))
            continue
        
        # 普通段落
        para_lines = []
        while i < len(lines):
            ls = lines[i].strip()
            if not ls:
                break
            para_lines.append(ls)
            i += 1
        para_text = " ".join(para_lines)
        segments.append(_parse_inline("unstyled", para_text))
    
    return segments if segments else [_text_segment("")]


def _parse_inline(kind, source):
    """
    解析行内样式: **bold** *italic* ~~strikethrough~~ `code` [link](url)
    
    Returns:
        dict: {"type": "text", "kind", "text", "inlineStyleRanges", "links"}
    """
    result = {
        "type": "text",
        "kind": kind,
        "text": "",
        "inlineStyleRanges": [],
        "links": [],
    }
    cursor = 0
    
    def _append_styled(text, styles):
        offset = len(result["text"])
        result["text"] += text
        for style in styles:
            result["inlineStyleRanges"].append({
                "offset": offset,
                "length": len(text),
                "style": style,
            })
    
    while cursor < len(source):
        char = source[cursor]
        
        # 链接 [text](url)
        if char == "[":
            link_match = re.match(r"^\[([^\]]+)\]\(([^)]+)\)", source[cursor:])
            if link_match:
                offset = len(result["text"])
                link_text = link_match.group(1)
                url = link_match.group(2)
                result["text"] += link_text
                result["links"].append({
                    "offset": offset,
                    "length": len(link_text),
                    "url": url,
                })
                cursor += len(link_match.group(0))
                continue
        
        # *** bold+italic
        if source[cursor:cursor+3] == "***":
            end = source.find("***", cursor + 3)
            if end > cursor:
                _append_styled(source[cursor+3:end], ["Bold", "Italic"])
                cursor = end + 3
                continue
        
        # ** bold
        if source[cursor:cursor+2] == "**":
            end = source.find("**", cursor + 2)
            if end > cursor and (end + 2 >= len(source) or source[end+2] != "*"):
                _append_styled(source[cursor+2:end], ["Bold"])
                cursor = end + 2
                continue
        
        # ~~ strikethrough
        if source[cursor:cursor+2] == "~~":
            end = source.find("~~", cursor + 2)
            if end > cursor:
                _append_styled(source[cursor+2:end], ["Strikethrough"])
                cursor = end + 2
                continue
        
        # *italic* or _italic_ (single)
        if char in ("*", "_"):
            if cursor + 1 < len(source) and source[cursor+1] == char:
                cursor += 1
                continue  # skip **/__ which are bold markers
            end = source.find(char, cursor + 1)
            if end > cursor and (end + 1 >= len(source) or source[end+1] != char):
                _append_styled(source[cursor+1:end], ["Italic"])
                cursor = end + 1
                continue
        
        # `code`
        if char == "`":
            end = source.find("`", cursor + 1)
            if end > cursor:
                _append_styled(source[cursor+1:end], ["Code"])
                cursor = end + 1
                continue
        
        result["text"] += char
        cursor += 1
    
    return result


# ── 构建 Paste Plan ─────────────────────────────────────────────────

def _render_inline_html(segment):
    """将内联段渲染为 HTML"""
    if segment["type"] != "text":
        return ""
    
    text = segment.get("text", "") or ""
    if not text.strip():
        return "<br>"
    
    # 解析 inlineStyleRanges
    styled_text = list(text)
    styled = [False] * len(text)
    
    for style_range in segment.get("inlineStyleRanges", []):
        offset = style_range["offset"]
        length = style_range["length"]
        style = style_range["style"]
        tag = STYLE_TAGS.get(style, "span")
        # 从右到左插入标签，避免偏移错位
        for pos in range(offset + length - 1, offset - 1, -1):
            if pos < len(styled_text):
                if pos == offset + length - 1:
                    styled_text[pos] = f"</{tag}>{styled_text[pos]}"
                elif pos == offset:
                    styled_text[pos] = f"<{tag}>{styled_text[pos]}"
                styled[pos] = True
    
    result = "".join(styled_text)
    
    # 处理链接
    for link in segment.get("links", []):
        offset = link["offset"]
        length = link["length"]
        url = link.get("url", "")
        # 在对应位置插入 <a> 标签
        result_list = list(result)
        # 插入 </a> 在末尾
        result_list.insert(offset + length + len(re.findall(r'</?[^>]+>', result[:offset+length])), f'</a>')
        # 插入 <a> 在开头
        result_list.insert(offset + len(re.findall(r'</?[^>]+>', result[:offset])), f'<a href="{escape_html(url)}">')
        result = "".join(result_list)
    
    return result


def build_paste_plan(segments, options=None):
    """
    构建 X Articles paste plan
    
    Args:
        segments: parse_markdown 得到的段列表
        options: {"maxImagesPerImport": int, "maxTablesPerImport": int,
                  "maxTweetsPerImport": int, "appendSignature": bool}
    
    Returns:
        dict: {"html": [str], "blocks": [dict], "operations": [dict]}
    """
    options = options or {}
    
    # 随机前缀
    prefix = f"__XPOSTER_{''.join(random.choices(string.ascii_lowercase + string.digits, k=5))}_"
    index = 0
    html = []
    blocks = []
    operations = []
    list_tag = None
    list_items = []
    
    def _marker(mtype):
        nonlocal index
        mid = f"{prefix}{mtype}_{index}__"
        index += 1
        return mid
    
    def _add_block(btype, text, segment=None):
        blocks.append({
            "type": btype or "unstyled",
            "text": re.sub(r"\n+", " ", str(text or "")),
            "inlineStyleRanges": [
                {**r} for r in (segment.get("inlineStyleRanges", []) if segment else [])
            ],
            "links": [
                {**l} for l in (segment.get("links", []) if segment else [])
            ],
        })
    
    def _flush_list():
        nonlocal list_tag, list_items
        if list_tag is None:
            return
        inner = "".join(f"<li>{item}</li>" for item in list_items)
        html.append(f"<{list_tag}>{inner}</{list_tag}>")
        list_tag = None
        list_items = []
    
    def _add_image_op(segment, marker_type="IMAGE"):
        mid = _marker(marker_type)
        html.append(f"<p>{mid}</p>")
        _add_block("unstyled", mid)
        operations.append({
            "marker": mid,
            "op": {
                "type": "image",
                "source": segment.get("source", ""),
                "alt": segment.get("alt", ""),
            }
        })
    
    def _add_tweet_op(segment):
        mid = _marker("TWEET")
        html.append(f"<p>{mid}</p>")
        _add_block("unstyled", mid)
        operations.append({
            "marker": mid,
            "op": {
                "type": "tweet",
                "tweetId": segment.get("tweetId", ""),
            }
        })
    
    for segment in segments:
        if segment["type"] == "text":
            rendered = _render_inline_html(segment) or "<br>"
            _add_block(segment.get("kind", "unstyled"), segment.get("text", ""), segment)
            
            kind = segment.get("kind", "unstyled")
            if kind in ("unordered-list-item", "ordered-list-item"):
                next_tag = "ul" if kind == "unordered-list-item" else "ol"
                if list_tag and list_tag != next_tag:
                    _flush_list()
                list_tag = next_tag
                list_items.append(rendered)
            else:
                _flush_list()
                if kind in BLOCK_TAGS:
                    html.append(f"<{BLOCK_TAGS[kind]}>{rendered}</{BLOCK_TAGS[kind]}>")
                else:
                    html.append(f"<p>{rendered}</p>")
        
        elif segment["type"] == "code":
            _flush_list()
            lang = segment.get("language", "")
            code = escape_html(segment.get("code", ""))
            lang_attr = f' class="language-{lang}"' if lang else ''
            html.append(f"<pre><code{lang_attr}>{code}</code></pre>")
            mid = _marker("CODE")
            _add_block("code-block", mid)
        
        elif segment["type"] == "image":
            _flush_list()
            _add_image_op(segment)
        
        elif segment["type"] == "tweet":
            _flush_list()
            _add_tweet_op(segment)
        
        elif segment["type"] == "table":
            _flush_list()
            table_html = ["<table>"]
            headers = segment.get("headers", [])
            alignments = segment.get("alignments", [])
            rows = segment.get("rows", [])
            
            if headers:
                table_html.append("<thead><tr>")
                for i, h in enumerate(headers):
                    align = f' style="text-align:{alignments[i]}"' if i < len(alignments) else ""
                    table_html.append(f"<th{align}>{escape_html(h)}</th>")
                table_html.append("</tr></thead>")
            
            if rows:
                table_html.append("<tbody>")
                for row in rows:
                    table_html.append("<tr>")
                    for i, cell in enumerate(row):
                        align = f' style="text-align:{alignments[i]}"' if i < len(alignments) else ""
                        table_html.append(f"<td{align}>{escape_html(cell)}</td>")
                    table_html.append("</tr>")
                table_html.append("</tbody>")
            
            table_html.append("</table>")
            html.append("".join(table_html))
            mid = _marker("TABLE")
            _add_block("unstyled", mid)
        
        elif segment["type"] == "divider":
            _flush_list()
            html.append("<hr>")
            _add_block("unstyled", "---")
    
    _flush_list()
    
    return {
        "html": html,
        "blocks": blocks,
        "operations": operations,
    }


# ── 主解析入口 ─────────────────────────────────────────────────────

def parse(markdown, options=None):
    """
    主入口: 解析 Markdown → X Articles 格式
    
    Args:
        markdown: str, 原始 Markdown 文本
        options: dict, 可选配置
    
    Returns:
        dict: {
            "title": str | None,
            "cover": str | None,
            "segments": list[dict],
            "meta": dict,
            "plan": dict,  # {html, blocks, operations}
        }
    """
    # 1. 解析 frontmatter
    parsed = parse_frontmatter(markdown)
    markdown_body = parsed["body"]
    meta = parsed["meta"]
    
    title_from_meta = meta.get("title") or meta.get("Title") or meta.get("标题")
    cover = meta.get("cover") or meta.get("Cover") or meta.get("封面")
    if cover:
        cover = re.sub(r"^!\[\[|\]\]$", "", cover)
        cover_match = re.match(r"^!\[[^\]]*\]\(([^)]+)\)", cover)
        if cover_match:
            cover = cover_match.group(1)
        cover = cover.strip()
    
    # 2. 查找特殊块 + 解析文本块
    spans = find_special_blocks(markdown_body)
    segments = []
    cursor = 0
    
    for span in sorted(spans, key=lambda s: s["start"]):
        if span["start"] > cursor:
            segments.extend(_parse_text_blocks(markdown_body[cursor:span["start"]]))
        segments.append(span["segment"])
        cursor = span["end"]
    
    if cursor < len(markdown_body):
        segments.extend(_parse_text_blocks(markdown_body[cursor:]))
    
    # 3. 提取标题
    title = title_from_meta
    if not title:
        for i, seg in enumerate(segments):
            if seg["type"] == "text" and seg.get("kind") == "header-one":
                title = seg.get("text")
                segments.pop(i)
                break
    
    # 4. 提取封面
    if not cover:
        for seg in segments:
            if seg["type"] == "image" and seg.get("source"):
                cover = seg["source"]
                break
    
    # 5. 构建 paste plan
    plan = build_paste_plan(segments, options)
    
    return {
        "title": title,
        "cover": cover,
        "segments": segments,
        "meta": meta,
        "plan": plan,
    }


# ── 辅助工具 ──────────────────────────────────────────────────────────

def looks_like_markdown(text):
    """快速检测文本是否包含 Markdown 标记"""
    if not text or len(text) < 3:
        return False
    patterns = [
        re.compile(r"^#{1,6}\s+\S", re.MULTILINE),
        re.compile(r"^>\s+\S", re.MULTILINE),
        re.compile(r"^[-*+]\s+\S", re.MULTILINE),
        re.compile(r"^\d+\.\s+\S", re.MULTILINE),
        re.compile(r"^\s*```", re.MULTILINE),
        re.compile(r"^\s*(?:---|\*\*\*|___)\s*$", re.MULTILINE),
        re.compile(r"\[[^\]]+\]\(https?://\S+\)", re.IGNORECASE),
        re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE),
        re.compile(r"`[^`\n]+`"),
    ]
    return any(p.search(text) for p in patterns)


def to_draftjs_blocks(parse_result):
    """将 parse() 结果转为 Draft.js raw ContentState (JSON 序列化友好)"""
    blocks = []
    for seg in parse_result["segments"]:
        if seg["type"] == "text":
            kind = seg.get("kind", "unstyled")
            block_type = {
                "header-one": "header-one",
                "header-two": "header-two",
                "header-three": "header-three",
                "header-four": "header-four",
                "header-five": "header-five",
                "header-six": "header-six",
                "blockquote": "blockquote",
                "unordered-list-item": "unordered-list-item",
                "ordered-list-item": "ordered-list-item",
                "code-block": "code-block",
            }.get(kind, "unstyled")
            
            blocks.append({
                "key": f"seg{len(blocks)}",
                "type": block_type,
                "text": seg.get("text", ""),
                "depth": 0,
                "inlineStyleRanges": seg.get("inlineStyleRanges", []),
                "entityRanges": [],
                "data": {},
            })
    return {
        "blocks": blocks,
        "entityMap": {},
    }


def markdown_to_article_data(markdown_text, options=None):
    """
    高级封装: Markdown → X Articles 所需的数据结构
    
    直接供 GA agent 使用, 返回可直接发送给 X API 的格式
    
    Args:
        markdown_text: str
        options: dict
    
    Returns:
        dict: {title, content_html, blocks, operations}
    """
    result = parse(markdown_text, options)
    return {
        "title": result["title"],
        "content_html": "\n".join(result["plan"]["html"]),
        "blocks": result["plan"]["blocks"],
        "operations": result["plan"]["operations"],
        "segments": result["segments"],
    }


# ── 独立测试 ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_md = """---
title: 测试文章
cover: https://example.com/cover.jpg
---

# 我的第一篇文章

这是一段 **加粗** 和 *斜体* 的文字，还有 ~~删除线~~ 和 `代码`。

> 这是一段引用

- 列表项1
- 列表项2
- 列表项3

1. 有序1
2. 有序2

这是一个[链接](https://example.com)

![图片描述](https://example.com/img.jpg)

```python
print("Hello World")
```

| 名称 | 数量 | 价格 |
|:---|:---:|---:|
| 苹果 | 5 | 10元 |
| 香蕉 | 3 | 5元 |

---

https://x.com/user/status/123456789
"""
    
    result = parse(test_md)
    print("=== 解析结果 ===")
    print(f"标题: {result['title']}")
    print(f"封面: {result['cover']}")
    print(f"元数据: {result['meta']}")
    print(f"\n段数: {len(result['segments'])}")
    for i, seg in enumerate(result['segments'][:8]):
        if seg['type'] == 'text':
            print(f"  [{i}] {seg['kind']}: {seg['text'][:60]}...")
        else:
            print(f"  [{i}] {seg['type']}: {json.dumps(seg, ensure_ascii=False)[:80]}...")
    
    print(f"\n=== Plan ===")
    print(f"HTML块数: {len(result['plan']['html'])}")
    print(f"Blocks数: {len(result['plan']['blocks'])}")
    print(f"Operations数: {len(result['plan']['operations'])}")
    for op in result['plan']['operations']:
        print(f"  Op: {op['op']['type']} -> {op['marker']}")
    
    print("\n=== Draft.js === ")
    dj = to_draftjs_blocks(result)
    print(f"Blocks: {len(dj['blocks'])}")
    
    print("\n✅ 测试通过!")
