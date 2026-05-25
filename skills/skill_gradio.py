"""
skill_gradio.py — WebUI引擎骨髓内化 (Gradio 35k⭐)

来源: gradio-app/gradio (GitHub, 35k⭐)
核心: Interface(单页) + Blocks(多组件布局) + 事件驱动(输入变化→输出更新)
本实现: 零依赖纯Python WebUI (用内置http.server + 前端模板字符串)

与GA集成:
 - brain_adapter: 显示推理状态/记忆图谱
 - action_registry: 动作树浏览/触发
 - skill_cognitive_memory: 记忆热力图
"""

import json
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Any, Callable


# ══════════════════════════════════════════════════════════════
# 前端模板 (内联HTML/CSS/JS, 零外部依赖)
# ══════════════════════════════════════════════════════════════

_TEMPLATE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#0f172a; color:#e2e8f0; max-width:1200px; margin:0 auto; padding:20px; }}
h1 {{ font-size:1.5rem; margin-bottom:20px; color:#38bdf8; }}
.container {{ display:flex; flex-wrap:wrap; gap:16px; }}
.card {{ background:#1e293b; border-radius:12px; padding:16px; flex:1; min-width:300px; }}
.card-title {{ font-size:0.85rem; color:#64748b; margin-bottom:8px; text-transform:uppercase; }}
input, select, textarea {{ background:#0f172a; border:1px solid #334155; border-radius:6px; 
       color:#e2e8f0; padding:8px 12px; width:100%; margin-bottom:8px; font-size:0.9rem; }}
button {{ background:#2563eb; color:white; border:none; border-radius:6px; padding:8px 16px;
        cursor:pointer; font-size:0.9rem; transition:background 0.2s; }}
button:hover {{ background:#1d4ed8; }}
.output {{ background:#0f172a; border:1px solid #334155; border-radius:6px; padding:12px; 
         min-height:40px; font-size:0.9rem; white-space:pre-wrap; overflow-x:auto; }}
.row {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="container" id="app">{components}</div>
<script>
const api = (path, data) => fetch(path, {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify(data||{{}})
}}).then(r=>r.json());

{handlers}
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════
# 组件系统
# ══════════════════════════════════════════════════════════════

class Component:
    """UI组件基类"""
    def __init__(self, id: str, label: str = ""):
        self.id = id
        self.label = label or id
        self._value = None
        self._change_handlers: list[Callable] = []
    
    def change(self, fn: Callable):
        """注册变化处理器"""
        self._change_handlers.append(fn)
        return fn
    
    def to_html(self) -> str:
        raise NotImplementedError
    
    def set_value(self, value: Any):
        self._value = value


class Textbox(Component):
    """文本输入框"""
    def __init__(self, id: str, label: str = "", value: str = "", 
                 lines: int = 1, placeholder: str = ""):
        super().__init__(id, label)
        self._value = value
        self.lines = lines
        self.placeholder = placeholder
    
    def to_html(self) -> str:
        if self.lines > 1:
            return f'''<div class="card"><div class="card-title">{self.label}</div>
<textarea id="{self.id}" rows="{self.lines}" placeholder="{self.placeholder}">{self._value or ""}</textarea>
<div id="out_{self.id}" class="output"></div></div>'''
        return f'''<div class="card"><div class="card-title">{self.label}</div>
<div class="row">
<input id="{self.id}" type="text" value="{self._value or ""}" placeholder="{self.placeholder}">
<button onclick="handle_{self.id}()">提交</button>
</div>
<div id="out_{self.id}" class="output"></div></div>'''


class Button(Component):
    """按钮"""
    def __init__(self, id: str, label: str = "点击", variant: str = "primary"):
        super().__init__(id, label)
        self.variant = variant
    
    def to_html(self) -> str:
        return f'''<div class="card"><div class="card-title">{self.label}</div>
<button id="{self.id}" onclick="handle_{self.id}()">{self.label}</button>
<div id="out_{self.id}" class="output"></div></div>'''


class Markdown(Component):
    """Markdown显示"""
    def __init__(self, id: str, value: str = ""):
        super().__init__(id, "")
        self._value = value
    
    def to_html(self) -> str:
        # 简化版md转html (仅支持粗体和换行)
        html = self._value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html = html.replace("\n", "<br>")
        import re
        html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html)
        html = re.sub(r'__(.+?)__', r'<b>\1</b>', html)
        return f'''<div class="card"><div id="{self.id}">{html}</div></div>'''
    
    def set_value(self, value: str):
        self._value = value


class Row:
    """横向布局容器"""
    def __init__(self, *components: Component):
        self.components = components
    
    def to_html(self) -> str:
        html = '<div class="row">'
        for c in self.components:
            html += c.to_html()
        html += '</div>'
        return html


# ══════════════════════════════════════════════════════════════
# Interface (单页应用)
# ══════════════════════════════════════════════════════════════

class Interface:
    """Web应用主类 (类似 gradio.Interface + gradio.Blocks)
    
    用法:
        ui = Interface("GA状态面板")
        
        input_box = Textbox("query", "查询", placeholder="输入搜索词...")
        output_box = Textbox("result", "结果", lines=5)
        
        @input_box.change
        def search(query):
            return f"搜索: {query}"
        
        ui.add(input_box, output_box)
        ui.launch()
    """
    
    def __init__(self, title: str = "GA WebUI"):
        self.title = title
        self.components: list[Component | Row] = []
        self._server = None
        self._thread = None
        self._port = 7860
    
    def add(self, *components: Component | Row):
        """添加组件"""
        for c in components:
            self.components.append(c)
    
    def _build_html(self) -> tuple[str, str]:
        """生成HTML和JS处理器"""
        components_html = ""
        js_handlers = []
        
        for comp_or_row in self.components:
            if isinstance(comp_or_row, Row):
                row_html = ""
                for c in comp_or_row.components:
                    row_html += c.to_html()
                components_html += f'<div class="row">{row_html}</div>'
            else:
                components_html += comp_or_row.to_html()
                if isinstance(comp_or_row, (Textbox, Button)):
                    # 生成JS点击处理函数
                    fn_body = ""
                    if comp_or_row._change_handlers:
                        fn = comp_or_row._change_handlers[0]
                        # 注册到后端路由
                        route = f"/api/{comp_or_row.id}"
                        self._register_route(route, fn, comp_or_row)
                        fn_body = f"const val = document.getElementById('{comp_or_row.id}').value;\n"
                        fn_body += f"const res = await api('{route}', {{value: val}});\n"
                        fn_body += f"document.getElementById('out_{comp_or_row.id}').textContent = JSON.stringify(res.result, null, 2);"
                    
                    js_handlers.append(f"""
async function handle_{comp_or_row.id}() {{
    {fn_body}
}}""")
        
        html = _TEMPLATE.format(
            title=self.title,
            components=components_html,
            handlers="\n".join(js_handlers),
        )
        return html, ""
    
    def _register_route(self, path: str, fn: Callable, comp: Component):
        """注册API路由"""
        if not hasattr(self, '_routes'):
            self._routes = {}
        self._routes[path] = (fn, comp)
    
    # ──── 组件快捷方法 ────
    
    def textbox(self, label: str = "", value: str = "", lines: int = 1, 
                placeholder: str = "") -> Textbox:
        """快捷创建文本框"""
        import uuid
        uid = f"tb_{uuid.uuid4().hex[:6]}"
        tb = Textbox(uid, label, value, lines, placeholder)
        self.add(tb)
        return tb
    
    def button(self, label: str = "点击") -> Button:
        """快捷创建按钮"""
        import uuid
        uid = f"btn_{uuid.uuid4().hex[:6]}"
        btn = Button(uid, label)
        self.add(btn)
        return btn
    
    def markdown(self, text: str = "") -> Markdown:
        """快捷创建Markdown"""
        import uuid
        uid = f"md_{uuid.uuid4().hex[:6]}"
        md = Markdown(uid, text)
        self.add(md)
        return md
    
    def row(self) -> "RowBuilder":
        """快捷创建行布局"""
        return RowBuilder(self)
    
    def launch(self, port: int = 7860, open_browser: bool = True):
        """启动Web服务器"""
        self._port = port
        
        # 生成HTML
        html_content, _ = self._build_html()
        self._html_content = html_content
        
        # 启动服务器
        self._server = _GradioServer(port, self)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        
        url = f"http://localhost:{port}"
        print(f"🚀 GA WebUI 已启动: {url}")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        return url
    
    def close(self):
        """关闭服务器"""
        if self._server:
            self._server.shutdown()


class RowBuilder:
    """行布局构建器"""
    def __init__(self, interface: Interface):
        self.interface = interface
        self._components = []
    
    def add(self, component: Component):
        self._components.append(component)
        return self
    
    def end(self):
        """结束行布局, 添加到interface"""
        self.interface.add(Row(*self._components))


# ══════════════════════════════════════════════════════════════
# HTTP服务器
# ══════════════════════════════════════════════════════════════

class _GradioHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""
    
    def log_message(self, format, *args):
        pass  # 静默日志
    
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html()
        else:
            self.send_error(404)
    
    def _send_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        interface = self.server.interface  # type: ignore
        self.wfile.write(interface._html_content.encode("utf-8"))
    
    def do_POST(self):
        parsed = urlparse(self.path)
        routes = getattr(self.server.interface, '_routes', {})  # type: ignore
        
        if parsed.path in routes:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            data = json.loads(body) if body else {}
            
            fn, comp = routes[parsed.path]
            try:
                result = fn(data.get("value", ""))
                response = {"status": "ok", "result": result}
            except Exception as e:
                response = {"status": "error", "result": str(e)}
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_error(404)


class _GradioServer(HTTPServer):
    """自定义HTTPServer, 携带interface引用"""
    def __init__(self, port: int, interface: Interface):
        super().__init__(("0.0.0.0", port), _GradioHandler)
        self.interface = interface


# ══════════════════════════════════════════════════════════════
# 自检 (10项全覆盖)
# ══════════════════════════════════════════════════════════════

def _run_self_check():
    import time
    import uuid
    
    print("=" * 60)
    print("📋 Gradio 自检 (35k⭐ WebUI引擎)")
    print("=" * 60)
    
    # 1. 创建Interface
    ui = Interface("GA自检面板")
    assert ui.title == "GA自检面板"
    print("✅ Interface创建: " + ui.title)
    
    # 2. 快捷创建组件
    tb = ui.textbox("输入", placeholder="测试")
    assert isinstance(tb, Textbox)
    assert tb.label == "输入"
    print(f"✅ Textbox快捷: id={tb.id}, label={tb.label}")
    
    # 3. Button快捷创建
    btn = ui.button("点击测试")
    assert isinstance(btn, Button)
    print(f"✅ Button快捷: id={btn.id}, label={btn.label}")
    
    # 4. Markdown快捷创建
    md = ui.markdown("**粗体**文本")
    assert isinstance(md, Markdown)
    print(f"✅ Markdown快捷: value={md._value[:10]}...")
    
    # 5. 事件绑定
    @tb.change
    def on_input(value):
        return f"收到: {value}"
    
    assert len(tb._change_handlers) == 1
    result = tb._change_handlers[0]("你好世界")
    assert result == "收到: 你好世界"
    print(f"✅ 事件绑定: '{result}'")
    
    # 6. 多行Textbox
    tb2 = Textbox("multi", "多行", value="行1\n行2", lines=5)
    assert tb2.lines == 5
    print(f"✅ 多行Textbox: {tb2.lines}行")
    
    # 7. Button事件
    @btn.change
    def on_click(value):
        return "按钮被点击!"
    
    assert len(btn._change_handlers) == 1
    click_result = btn._change_handlers[0]("")
    assert click_result == "按钮被点击!"
    print(f"✅ Button事件: '{click_result}'")
    
    # 8. Row布局
    row_comp = Row(tb, btn)
    row_html = row_comp.to_html()
    assert 'class="row"' in row_html
    print(f"✅ Row布局: 含{len(row_comp.components)}个组件")
    
    # 9. RowBuilder链式
    rb = RowBuilder(ui)
    rb.add(tb).add(btn).end()
    assert len(ui.components) > 0
    print(f"✅ RowBuilder链式: end后ui有{len(ui.components)}个组件")
    
    # 10. 服务器启动/关闭
    import socket
    def find_free_port():
        with socket.socket() as s:
            s.bind(('', 0))
            return s.getsockname()[1]
    
    test_port = find_free_port()
    url = ui.launch(port=test_port, open_browser=False)
    assert url == f"http://localhost:{test_port}"
    time.sleep(0.3)  # 等服务器启动
    
    # 验证HTML生成
    assert hasattr(ui, '_html_content')
    assert 'GA自检面板' in ui._html_content
    assert 'textbox' in ui._html_content.lower() or 'input' in ui._html_content
    
    # API路由
    assert hasattr(ui, '_routes')
    route_key = f"/api/{tb.id}"
    assert route_key in ui._routes, f"路由 {route_key} 未注册, 已有: {list(ui._routes.keys())}"
    
    ui.close()
    print(f"✅ 服务器启动/关闭: port={test_port}")
    
    print(f"\n✅🎉 Gradio 自检通过 (10项)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    _run_self_check()
