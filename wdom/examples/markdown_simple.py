#!/usr/bin/env python3
# -*- coding: utf-8 -*-

try:
    import misaka as m
except ImportError:
    print('ERROR: Install `misaka` before run this example, '
          'by `pip install misaka`.')
    exit()
from pygments import highlight
from pygments.styles import get_all_styles
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from wdom.document import get_document
from wdom.node import RawHtml
from wdom.themes.bootstrap3 import css_files, js_files
from wdom.themes.bootstrap3 import Div, Textarea, Col6, Row, H1, Hr
from wdom.themes.bootstrap3 import Select, Option, Style


src = '''
## Source Code Example

```py
from collections import OrderedDict

class MyDict(OrderedDict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print('Create my dict')
```
'''


class HighlighterRenderer(m.HtmlRenderer):
    def blockcode(self, text, lang):
        if not lang:
            return '\n<pre><code>{}</code></pre>\n'.format(text.strip())
        lexer = get_lexer_by_name(lang)
        formatter = HtmlFormatter()
        return highlight(text, lexer, formatter)


class Editor(Row):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.md = m.Markdown(HighlighterRenderer(),
                             extensions=('fenced-code',))
        self.css = Style(parent=self)

        self.setAttribute('style', 'height: 80vh;')
        editor_col = Col6(parent=self)
        self.editor = Textarea(parent=editor_col)
        self.editor.setAttribute('style', 'height: 80vh')

        viewer_col = Col6(parent=self)

        self.style_selector = Select()
        styles = sorted(get_all_styles())
        styles.remove('default')
        self.style_selector.appendChild(
            Option('default', value='default', selected=True))
        for style in styles:
            self.style_selector.appendChild(Option(style, value=style))
        self.style_selector.addEventListener(
            'change', lambda event: self.set_style(event.currentTarget.value))

        self.viewer = Div()
        self.viewer.setAttribute(
            'style',
            '''
            height: 100%;
            min-height: 80vh;
            padding: 1em 2em;
            border: 1px solid #ddd;
            border-radius: 3px;
            ''',
        )

        viewer_col.appendChild(self.style_selector)
        viewer_col.appendChild(self.viewer)

        self.editor.addEventListener('input', self.render)
        self.editor.addEventListener('change', self.render)

        self.set_style('default')
        self.editor.textContent = src
        self.viewer.innerHTML = self.md(src)
        # TIPS: Wen just showing HTML, `appendChild(RawHTML(html))` is better
        # than innerHTML on performance since it skips parse process.
        # self.viewer.appendChild(RawHtml(self.md(src)))

    def render(self, event):
        content = event.currentTarget.textContent
        self.viewer.innerHTML = self.md(content)
        # TIPS: Same as above reason, RawHtml is also better here
        # self.viewer.empty()
        # self.viewer.appendChild(RawHtml(self.md(content)))

    def set_style(self, style: str):
        self.css.innerHTML = HtmlFormatter(style=style).get_style_defs()


def sample_page(**kwargs):
    doc = get_document(**kwargs)
    for js in js_files:
        doc.add_jsfile(js)
    for css in css_files:
        doc.add_cssfile(css)
    app = Div(style='width: 90vw; margin: auto')
    title = H1('Simple Markdown Editor', class_='text-center')
    app.appendChild(title)
    app.appendChild(Hr())
    app.appendChild(Editor())
    return app


if __name__ == '__main__':
    from wdom.document import set_app
    from wdom import server
    set_app(sample_page())
    server.start()
