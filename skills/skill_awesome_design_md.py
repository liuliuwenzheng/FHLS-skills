"""
skill_awesome_design_md — DESIGN.md设计系统 (骨髓内化: VoltAgent/awesome-design-md 81k⭐)

骨架优先原则: DesignToken → DesignSpec → ComponentGenerator → DesignSystem
零依赖: 纯Python实现, 读取DESIGN.md生成UI组件

用法:
    from memory.skill_awesome_design_md import DesignSystem, DesignSpec
    ds = DesignSystem()
    spec = ds.parse('DESIGN.md')
    html = ds.render_button(spec, 'primary')
"""

import re
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════
# [1] DesignToken — 设计原子
# ═══════════════════════════════════════════════

@dataclass
class ColorToken:
    """颜色令牌: 品牌色/中性色/语义色"""
    name: str
    hex: str
    category: str = 'brand'  # brand | neutral | semantic
    alias: Optional[str] = None

    def to_css(self) -> str:
        return f"--{self.name}: {self.hex};"


@dataclass
class TypographyToken:
    """字体令牌"""
    font_family: str
    font_size: str = '16px'  # 如 '16px', 默认16px
    font_weight: int = 400
    line_height: float = 1.5
    name: str = 'body'
    letter_spacing: str = '0'

    def to_css(self) -> str:
        return (
            f"--font-{self.name}: {self.font_family};\n"
            f"--font-size-{self.name}: {self.font_size};\n"
            f"--font-weight-{self.name}: {self.font_weight};"
        )


@dataclass
class SpacingToken:
    """间距令牌"""
    name: str
    value: str

    def to_css(self) -> str:
        return f"--spacing-{self.name}: {self.value};"


@dataclass
class ShadowToken:
    """阴影令牌"""
    name: str
    value: str  # like '0 2px 8px rgba(0,0,0,0.1)'

    def to_css(self) -> str:
        return f"--shadow-{self.name}: {self.value};"


@dataclass
class RadiusToken:
    """圆角令牌"""
    name: str
    value: str

    def to_css(self) -> str:
        return f"--radius-{self.name}: {self.value};"


# ═══════════════════════════════════════════════
# [2] DesignSpec — 完整设计规约
# ═══════════════════════════════════════════════

@dataclass
class DesignSpec:
    """
    从一个DESIGN.md解析出的完整设计规约
    
    品牌信息 + 设计令牌 + 组件规范 + 排版规则
    """
    brand_name: str = 'Default'
    colors: Dict[str, ColorToken] = field(default_factory=dict)
    typography: Dict[str, TypographyToken] = field(default_factory=dict)
    spacings: Dict[str, SpacingToken] = field(default_factory=dict)
    shadows: Dict[str, ShadowToken] = field(default_factory=dict)
    radii: Dict[str, RadiusToken] = field(default_factory=dict)
    components: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    raw_frontmatter: Dict[str, Any] = field(default_factory=dict)

    def to_css_variables(self) -> str:
        """将所有令牌转为CSS变量"""
        lines = [f"/* {self.brand_name} Design System */", ':root {']
        for token in self.colors.values():
            lines.append(f"  {token.to_css()}")
        for token in self.typography.values():
            for line in token.to_css().split('\n'):
                lines.append(f"  {line}")
        for token in self.spacings.values():
            lines.append(f"  {token.to_css()}")
        for token in self.shadows.values():
            lines.append(f"  {token.to_css()}")
        for token in self.radii.values():
            lines.append(f"  {token.to_css()}")
        lines.append('}')
        return '\n'.join(lines)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            'brand_name': self.brand_name,
            'colors': {k: {'hex': v.hex, 'category': v.category} for k, v in self.colors.items()},
            'typography': {k: {'font_family': v.font_family, 'font_size': v.font_size,
                               'font_weight': v.font_weight, 'line_height': v.line_height}
                           for k, v in self.typography.items()},
            'spacings': {k: v.value for k, v in self.spacings.items()},
            'shadows': {k: v.value for k, v in self.shadows.items()},
            'radii': {k: v.value for k, v in self.radii.items()},
            'component_count': len(self.components),
        }


# ═══════════════════════════════════════════════
# [3] DesignSOPParser — DESIGN.md解析器
# ═══════════════════════════════════════════════

class DesignSOPParser:
    """
    解析DESIGN.md文件为DesignSpec
    
    支持格式:
    - YAML frontmatter (---\nkey: value\n---)
    - ## Colors / ## Typography / ## Spacing 等章节
    - `--color-primary: #3B82F6` 格式的令牌定义
    - 组件规范 (## Button / ## Card 等)
    """

    COLOR_PATTERN = re.compile(r'(?:--)?(?:color-)?([\w-]+):\s*(#[0-9a-fA-F]{3,8})', re.IGNORECASE)
    FONT_PATTERN = re.compile(r'(?:font|font-family)[:\s]+[\'"]([^\'"]+)[\'"]', re.IGNORECASE)
    SPACING_PATTERN = re.compile(r'(?:--)?(?:spacing-)?([\w-]+):\s*(\d+(?:px|rem|em|%))', re.IGNORECASE)
    SHADOW_PATTERN = re.compile(r'(?:shadow|box-shadow)[:\s]+(.+?)(?:;|$)', re.IGNORECASE)

    # 常见品牌名正则
    BRAND_PATTERNS = [
        (r'^#\s*([\w\s]+?)(?:\s*Design\s*System|\s*Design|\s*Theme)', 1),
        (r'brand[:\s]+[\'"]([^\'"]+)[\'"]', 1),
        (r'^#\s*(.+?)$', 1),
    ]

    @classmethod
    def parse(cls, content: str) -> DesignSpec:
        """解析DESIGN.md内容为DesignSpec"""
        spec = DesignSpec()

        # 提取品牌名（从第一个#标题）
        for pattern, group in cls.BRAND_PATTERNS:
            m = re.search(pattern, content, re.MULTILINE)
            if m:
                spec.brand_name = m.group(group).strip()
                break

        # 解析颜色
        for m in cls.COLOR_PATTERN.finditer(content):
            name = m.group(1).lower().replace(' ', '-')
            hex_val = m.group(2)
            cat = 'brand'
            if any(kw in name for kw in ['neutral', 'gray', 'grey', 'white', 'black', 'background']):
                cat = 'neutral'
            elif any(kw in name for kw in ['success', 'error', 'warning', 'info', 'danger']):
                cat = 'semantic'
            spec.colors[name] = ColorToken(name=name, hex=hex_val, category=cat)

        # 解析字体
        for m in cls.FONT_PATTERN.finditer(content):
            font_name = m.group(1)
            key = 'body' if not spec.typography else f'heading-{len(spec.typography)}'
            spec.typography[key] = TypographyToken(
                font_family=font_name, name=key
            )

        # 解析间距
        for m in cls.SPACING_PATTERN.finditer(content):
            name = m.group(1).replace(' ', '-').lower()
            spec.spacings[name] = SpacingToken(name=name, value=m.group(2))

        # 解析阴影
        for m in cls.SHADOW_PATTERN.finditer(content):
            val = m.group(1).strip()
            name = 'default'
            if 'small' in val.lower() or 'sm' in val.lower():
                name = 'sm'
            elif 'large' in val.lower() or 'lg' in val.lower():
                name = 'lg'
            spec.shadows[name] = ShadowToken(name=name, value=val)

        # 解析圆角（从border-radius）
        for m in re.finditer(r'(?:border-radius|radius)[:\s]+(\d+(?:px|rem|em|%))', content, re.IGNORECASE):
            val = m.group(1)
            name = 'default' if not spec.radii else f'r{len(spec.radii)}'
            spec.radii[name] = RadiusToken(name=name, value=val)

        # 解析组件章节 (## Button: / ## Card: / ### Primary Button 等)
        sections = re.split(r'^#{2,3}\s+', content, flags=re.MULTILINE)
        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue
            comp_match = re.match(r'([\w\s]+?)(?:\n|:)', sec)
            if comp_match:
                comp_name = comp_match.group(1).strip().lower().replace(' ', '_')
                comp_spec = cls._parse_component_section(sec)
                if comp_spec:
                    spec.components[comp_name] = comp_spec

        return spec

    @classmethod
    def _parse_component_section(cls, section: str) -> Optional[Dict[str, Any]]:
        """解析组件章节"""
        spec = {}
        lines = section.split('\n')
        for line in lines:
            line = line.strip()
            # 提取样式属性
            for attr in ['color', 'background', 'padding', 'margin',
                         'font-size', 'font-weight', 'border-radius', 'border']:
                m = re.search(rf'{attr}:\s*(.+?)(?:;|$)', line, re.IGNORECASE)
                if m:
                    spec[attr.replace('-', '_')] = m.group(1).strip()
        return spec if spec else None

    @classmethod
    def parse_file(cls, filepath: str) -> DesignSpec:
        """从文件路径解析DESIGN.md"""
        with open(filepath, 'r', encoding='utf-8') as f:
            return cls.parse(f.read())


# ═══════════════════════════════════════════════
# [4] ComponentGenerator — UI组件生成器
# ═══════════════════════════════════════════════

class ComponentGenerator:
    """
    根据DesignSpec生成UI组件
    
    支持: Button / Card / Input / Badge / Navbar 等基础组件
    输出: HTML + CSS 字符串
    """

    # 预设组件样式映射
    COMPONENT_TEMPLATES = {
        'button': {
            'html': '<button class="btn-{variant}">{label}</button>',
            'css': lambda s: (
                f".btn-{{variant}} {{\n"
                f"  font-family: var(--font-{next(iter(s.typography)) if s.typography else 'body'}, sans-serif);\n"
                f"  font-size: var(--font-size-body, 14px);\n"
                f"  padding: {s.spacings.get('md', s.spacings.get('default', SpacingToken('default', '8px 16px'))).value};\n"
                f"  border-radius: {s.radii.get('default', RadiusToken('default', '6px')).value};\n"
                f"  border: none;\n"
                f"  cursor: pointer;\n"
                f"  transition: all 0.2s ease;\n"
                f"}}\n"
                f".btn-primary {{\n"
                f"  background: {s.colors.get('primary', ColorToken('primary', '#3B82F6')).hex};\n"
                f"  color: #fff;\n"
                f"}}\n"
                f".btn-secondary {{\n"
                f"  background: {s.colors.get('secondary', s.colors.get('neutral-100', ColorToken('sec', '#E5E7EB'))).hex};\n"
                f"  color: {s.colors.get('primary', ColorToken('p', '#1F2937')).hex};\n"
                f"}}"
            ),
            'variants': ['primary', 'secondary', 'ghost'],
        },
        'card': {
            'html': '<div class="card">\n  <div class="card-header">{title}</div>\n  <div class="card-body">{content}</div>\n</div>',
            'css': lambda s: (
                f".card {{\n"
                f"  background: {s.colors.get('surface', s.colors.get('white', ColorToken('w', '#FFFFFF'))).hex};\n"
                f"  border-radius: {s.radii.get('lg', s.radii.get('default', RadiusToken('r', '12px'))).value};\n"
                f"  box-shadow: {s.shadows.get('default', ShadowToken('d', '0 2px 8px rgba(0,0,0,0.1)')).value};\n"
                f"  padding: {s.spacings.get('lg', s.spacings.get('default', SpacingToken('d', '24px'))).value};\n"
                f"  overflow: hidden;\n"
                f"}}\n"
                f".card-header {{\n"
                f"  font-size: {s.typography.get('heading', TypographyToken('sans-serif', '18px', 600)).font_size};\n"
                f"  font-weight: {s.typography.get('heading', TypographyToken('s', '18px', 600)).font_weight};\n"
                f"  margin-bottom: {s.spacings.get('sm', SpacingToken('s', '12px')).value};\n"
                f"}}"
            ),
        },
        'input': {
            'html': '<input class="input" type="text" placeholder="{placeholder}" />',
            'css': lambda s: (
                f".input {{\n"
                f"  font-family: var(--font-body, sans-serif);\n"
                f"  font-size: {s.typography.get('body', TypographyToken('sans-serif', '14px')).font_size};\n"
                f"  padding: {s.spacings.get('sm', SpacingToken('s', '8px 12px')).value};\n"
                f"  border: 1px solid {s.colors.get('border', s.colors.get('neutral-200', ColorToken('b', '#D1D5DB'))).hex};\n"
                f"  border-radius: {s.radii.get('default', RadiusToken('r', '6px')).value};\n"
                f"  outline: none;\n"
                f"  transition: border-color 0.2s;\n"
                f"}}\n"
                f".input:focus {{\n"
                f"  border-color: {s.colors.get('primary', ColorToken('p', '#3B82F6')).hex};\n"
                f"}}"
            ),
        },
        'badge': {
            'html': '<span class="badge badge-{variant}">{label}</span>',
            'css': lambda s: (
                f".badge {{\n"
                f"  display: inline-block;\n"
                f"  padding: {s.spacings.get('xs', SpacingToken('xs', '2px 8px')).value};\n"
                f"  border-radius: {s.radii.get('sm', RadiusToken('s', '4px')).value};\n"
                f"  font-size: 12px;\n"
                f"  font-weight: 500;\n"
                f"}}\n"
                f".badge-primary {{\n"
                f"  background: {s.colors.get('primary', ColorToken('p', '#3B82F6')).hex}20;\n"
                f"  color: {s.colors.get('primary', ColorToken('p', '#3B82F6')).hex};\n"
                f"}}\n"
                f".badge-success {{\n"
                f"  background: {s.colors.get('success', ColorToken('s', '#10B981')).hex}20;\n"
                f"  color: {s.colors.get('success', ColorToken('s', '#10B981')).hex};\n"
                f"}}\n"
                f".badge-error {{\n"
                f"  background: {s.colors.get('error', ColorToken('e', '#EF4444')).hex}20;\n"
                f"  color: {s.colors.get('error', ColorToken('e', '#EF4444')).hex};\n"
                f"}}"
            ),
            'variants': ['primary', 'success', 'error'],
        },
        'navbar': {
            'html': '<nav class="navbar">\n  <div class="navbar-brand">{brand}</div>\n  <div class="navbar-links">{links}</div>\n</nav>',
            'css': lambda s: (
                f".navbar {{\n"
                f"  display: flex;\n"
                f"  justify-content: space-between;\n"
                f"  align-items: center;\n"
                f"  padding: {s.spacings.get('md', SpacingToken('m', '12px 24px')).value};\n"
                f"  background: {s.colors.get('surface', s.colors.get('white', ColorToken('w', '#FFFFFF'))).hex};\n"
                f"  box-shadow: {s.shadows.get('sm', ShadowToken('s', '0 1px 3px rgba(0,0,0,0.1)')).value};\n"
                f"}}\n"
                f".navbar-brand {{\n"
                f"  font-size: {s.typography.get('heading', TypographyToken('s', '20px', 700)).font_size};\n"
                f"  font-weight: {s.typography.get('heading', TypographyToken('s', '20px', 700)).font_weight};\n"
                f"  color: {s.colors.get('primary', ColorToken('p', '#3B82F6')).hex};\n"
                f"}}\n"
                f".navbar-links a {{\n"
                f"  margin-left: {s.spacings.get('md', SpacingToken('m', '16px')).value};\n"
                f"  color: {s.colors.get('text', s.colors.get('neutral-700', ColorToken('t', '#374151'))).hex};\n"
                f"  text-decoration: none;\n"
                f"}}"
            ),
        },
    }

    def __init__(self, spec: DesignSpec):
        self.spec = spec

    def render_component(self, component_type: str, **kwargs) -> str:
        """渲染指定类型的组件HTML"""
        template = self.COMPONENT_TEMPLATES.get(component_type)
        if not template:
            return f"<!-- Unknown component type: {component_type} -->"

        html = template['html']
        if 'variants' in template:
            kwargs.setdefault('variant', template['variants'][0])
        kwargs.setdefault('label', component_type.title())
        kwargs.setdefault('title', 'Card Title')
        kwargs.setdefault('content', 'Card content goes here')
        kwargs.setdefault('placeholder', 'Enter text...')
        kwargs.setdefault('brand', 'Brand')
        kwargs.setdefault('links', '<a href="#">Home</a><a href="#">About</a>')

        return html.format(**kwargs)

    def render_css(self, component_type: str = None) -> str:
        """渲染组件CSS"""
        if component_type:
            template = self.COMPONENT_TEMPLATES.get(component_type)
            if template and callable(template['css']):
                return template['css'](self.spec)
            return ''
        # 全部组件CSS
        parts = [self.spec.to_css_variables()]
        for ctype, tpl in self.COMPONENT_TEMPLATES.items():
            if callable(tpl['css']):
                parts.append(tpl['css'](self.spec))
        return '\n\n'.join(parts)

    def render_full_page(self, brand: str = None, **kwargs) -> str:
        """渲染完整HTML页面"""
        spec = self.spec
        brand = brand or spec.brand_name

        btn = self.render_component('button', label='Get Started', variant='primary')
        card = self.render_component('card', title=f'Welcome to {brand}', content=kwargs.get('content', 'Beautiful design from a single markdown file.'))
        input_el = self.render_component('input', placeholder='Your email...')
        navbar = self.render_component('navbar', brand=brand)

        css = self.render_css()

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{brand}</title>
<style>
{css}
body {{ font-family: var(--font-body, sans-serif); margin: 0; padding: 0; background: {spec.colors.get('background', ColorToken('bg', '#F9FAFB')).hex}; color: {spec.colors.get('text', spec.colors.get('neutral-900', ColorToken('t', '#111827'))).hex}; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 48px 24px; }}
.hero {{ text-align: center; padding: 64px 0; }}
.hero h1 {{ font-size: 48px; margin-bottom: 16px; }}
.hero p {{ font-size: 18px; color: {spec.colors.get('text-secondary', spec.colors.get('neutral-500', ColorToken('ts', '#6B7280'))).hex}; margin-bottom: 24px; }}
.hero .input-wrapper {{ display: flex; gap: 8px; justify-content: center; margin-bottom: 16px; }}
.hero .input-wrapper input {{ width: 300px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px; margin-top: 48px; }}
</style>
</head>
<body>
{navbar}
<div class="container">
<div class="hero">
<h1>{brand}</h1>
<p>Design from a single markdown file — AI-friendly, version-controlled.</p>
<div class="input-wrapper">
{input_el}{btn.replace('btn-primary', 'btn-primary').replace('{variant}', 'primary')}
</div>
</div>
<div class="grid">
{card}
</div>
</div>
</body>
</html>"""
        return html


# ═══════════════════════════════════════════════
# [5] DesignSystem — 管理系统
# ═══════════════════════════════════════════════

class DesignSystem:
    """
    设计系统管理器
    
    管理多个品牌的设计规约, 支持导入/导出/合并
    """

    def __init__(self):
        self.specs: Dict[str, DesignSpec] = {}

    def parse(self, content: str, name: str = None) -> DesignSpec:
        """解析DESIGN.md内容"""
        spec = DesignSOPParser.parse(content)
        if name:
            spec.brand_name = name
        self.specs[spec.brand_name] = spec
        return spec

    def parse_file(self, filepath: str) -> DesignSpec:
        """从文件解析"""
        spec = DesignSOPParser.parse_file(filepath)
        self.specs[spec.brand_name] = spec
        return spec

    def add_spec(self, spec: DesignSpec):
        """直接添加规约"""
        self.specs[spec.brand_name] = spec

    def get_spec(self, name: str) -> Optional[DesignSpec]:
        return self.specs.get(name)

    def merge(self, *names: str) -> DesignSpec:
        """合并多个品牌的规约"""
        merged = DesignSpec(brand_name='Merged')
        for name in names:
            spec = self.specs.get(name)
            if not spec:
                continue
            merged.colors.update(spec.colors)
            merged.typography.update(spec.typography)
            merged.spacings.update(spec.spacings)
            merged.shadows.update(spec.shadows)
            merged.radii.update(spec.radii)
        return merged

    def list_brands(self) -> List[str]:
        return list(self.specs.keys())

    def export_all(self) -> str:
        """导出所有品牌规约为JSON"""
        return json.dumps(
            {name: spec.to_dict() for name, spec in self.specs.items()},
            indent=2, ensure_ascii=False
        )

    @classmethod
    def create_demo(cls) -> 'DesignSystem':
        """创建一个包含演示品牌的DesignSystem"""
        ds = cls()

        # 演示品牌: ModernTech
        modern = DesignSpec(brand_name='ModernTech')
        modern.colors = {
            'primary': ColorToken('primary', '#3B82F6', 'brand'),
            'secondary': ColorToken('secondary', '#8B5CF6', 'brand'),
            'neutral-50': ColorToken('neutral-50', '#F9FAFB', 'neutral'),
            'neutral-100': ColorToken('neutral-100', '#F3F4F6', 'neutral'),
            'neutral-200': ColorToken('neutral-200', '#E5E7EB', 'neutral'),
            'neutral-700': ColorToken('neutral-700', '#374151', 'neutral'),
            'neutral-900': ColorToken('neutral-900', '#111827', 'neutral'),
            'success': ColorToken('success', '#10B981', 'semantic'),
            'error': ColorToken('error', '#EF4444', 'semantic'),
            'background': ColorToken('background', '#F9FAFB', 'neutral'),
            'surface': ColorToken('surface', '#FFFFFF', 'neutral'),
            'text': ColorToken('text', '#111827', 'neutral'),
        }
        modern.typography = {
            'body': TypographyToken('Inter, system-ui, -apple-system, sans-serif', '14px', 400),
            'heading': TypographyToken('Inter, system-ui, sans-serif', '24px', 600),
        }
        modern.spacings = {
            'xs': SpacingToken('xs', '4px'),
            'sm': SpacingToken('sm', '8px'),
            'md': SpacingToken('md', '16px'),
            'lg': SpacingToken('lg', '24px'),
            'xl': SpacingToken('xl', '48px'),
        }
        modern.shadows = {
            'sm': ShadowToken('sm', '0 1px 3px rgba(0,0,0,0.1)'),
            'default': ShadowToken('default', '0 2px 8px rgba(0,0,0,0.1)'),
            'lg': ShadowToken('lg', '0 8px 32px rgba(0,0,0,0.12)'),
        }
        modern.radii = {
            'sm': RadiusToken('sm', '4px'),
            'default': RadiusToken('default', '8px'),
            'lg': RadiusToken('lg', '16px'),
        }
        ds.add_spec(modern)

        return ds

    def generate(self, brand: str = None) -> str:
        """生成完整页面"""
        if brand:
            spec = self.specs.get(brand)
            if not spec:
                return f"Brand '{brand}' not found"
        else:
            # 用第一个品牌
            spec = next(iter(self.specs.values())) if self.specs else DesignSpec()
        gen = ComponentGenerator(spec)
        return gen.render_full_page()


# ═══════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════

def self_check() -> List[str]:
    """
    自检: DesignToken → DesignSpec → ComponentGenerator → DesignSystem
    返回失败列表, 空列表=全通过
    """
    fails = []

    demo_md = """# ModernTech Design System

## Colors
--color-primary: #3B82F6
--color-neutral-100: #F3F4F6
--color-success: #10B981

## Typography
font-family: 'Inter, sans-serif'

## Spacing
--spacing-md: 16px
--spacing-lg: 24px

## Shadows
box-shadow: 0 2px 8px rgba(0,0,0,0.1)

## Components
### Button
background: --color-primary
color: #FFFFFF
border-radius: 8px
padding: 8px 16px
"""

    spec = None
    gen = None

    # [1] ColorToken
    try:
        c = ColorToken('primary', '#3B82F6', 'brand')
        assert c.to_css() == '--primary: #3B82F6;', f"ColorToken.to_css: {c.to_css()}"
    except Exception as e:
        fails.append(f"[1] ColorToken: {e}")

    # [2] TypographyToken
    try:
        t = TypographyToken('Inter, sans-serif', '16px', 400, name='body')
        css = t.to_css()
        assert '--font-body' in css
        assert '--font-size-body' in css
    except Exception as e:
        fails.append(f"[2] TypographyToken: {e}")

    # [3] DesignSOPParser — 解析DESIGN.md
    try:
        spec = DesignSOPParser.parse(demo_md)
        assert spec.brand_name == 'ModernTech', f"brand_name: {spec.brand_name!r}"
        assert len(spec.colors) >= 1
        assert 'primary' in spec.colors
        assert spec.typography
    except Exception as e:
        fails.append(f"[3] DesignSOPParser: {e}")

    # [4] ComponentGenerator
    try:
        gen = ComponentGenerator(spec)
        html = gen.render_component('button', label='Click Me')
        assert '<button' in html
        assert 'Click Me' in html
        css = gen.render_css('button')
        assert 'btn-' in css
    except Exception as e:
        fails.append(f"[4] ComponentGenerator.render: {e}")

    # [5] ComponentGenerator — 完整页面
    try:
        page = gen.render_full_page()
        assert '<!DOCTYPE html>' in page
        assert '</html>' in page
        assert spec.brand_name in page
    except Exception as e:
        fails.append(f"[5] ComponentGenerator.full_page: {e}")

    # [6] DesignSystem
    try:
        ds = DesignSystem.create_demo()
        assert len(ds.list_brands()) == 1
        page = ds.generate()
        assert '</html>' in page
        # parse
        spec2 = ds.parse(demo_md, name='Custom')
        assert 'Custom' in ds.list_brands()
    except Exception as e:
        fails.append(f"[6] DesignSystem: {e}")

    # [7] DesignSpec — to_css_variables
    try:
        css_vars = spec.to_css_variables()
        assert ':root {' in css_vars
        assert '--primary:' in css_vars or '--color-primary:' in css_vars or '#' in css_vars
    except Exception as e:
        fails.append(f"[7] DesignSpec.to_css_variables: {e}")

    return fails


if __name__ == '__main__':
    fails = self_check()
    if fails:
        print(f"❌ 自检失败 ({len(fails)}):")
        for f in fails:
            print(f"  - {f}")
    else:
        print("✅ skill_awesome_design_md 全部7/7自检通过!")
        print(f"  - 模块: ColorToken / TypographyToken / DesignSOPParser / ComponentGenerator / DesignSystem")
        print(f"  - 解析器: 颜色/字体/间距/阴影/圆角/组件规格 6维解析")
        print(f"  - 组件: Button / Card / Input / Badge / Navbar (含变体)")
        print(f"  - DesignSystem: 品牌管理/合并/导出/演示品牌")
        print(f"  - 演示: 一键生成完整HTML页面")

        # 演示
        ds = DesignSystem.create_demo()
        page = ds.generate()
        print(f"\n📄 演示页 HTML 大小: {len(page)} 字符")
