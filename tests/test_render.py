"""Markdown -> Telegram-HTML conversion."""

from __future__ import annotations

from claude_bridge_telegram.render import strip_tags, to_telegram_html


def test_empty():
    assert to_telegram_html("") == "(empty)"
    assert to_telegram_html("   \n  ") == "(empty)"


def test_plain_passthrough():
    assert to_telegram_html("just a sentence.") == "just a sentence."


def test_escapes_html_special_chars():
    out = to_telegram_html("a < b && c > d")
    assert "&lt;" in out and "&gt;" in out and "&amp;" in out
    assert "<b" not in out


def test_headings_become_bold_lines():
    assert to_telegram_html("# Title") == "<b>Title</b>"
    assert to_telegram_html("### Deep heading") == "<b>Deep heading</b>"


def test_bold_and_italic():
    assert to_telegram_html("**strong**") == "<b>strong</b>"
    assert to_telegram_html("__strong__") == "<b>strong</b>"
    assert to_telegram_html("say *hi* now") == "say <i>hi</i> now"
    assert to_telegram_html("a _word_ here") == "a <i>word</i> here"


def test_italic_leaves_snake_case_alone():
    assert to_telegram_html("call some_func_name()") == "call some_func_name()"


def test_inline_code_is_escaped_and_wrapped():
    out = to_telegram_html("use `x < y` please")
    assert out == "use <code>x &lt; y</code> please"


def test_inline_code_shields_markdown_inside():
    out = to_telegram_html("`**not bold**`")
    assert out == "<code>**not bold**</code>"


def test_fenced_code_block_plain():
    out = to_telegram_html("```\nline1\n<tag> & stuff\n```")
    assert out == "<pre>line1\n&lt;tag&gt; &amp; stuff</pre>"


def test_fenced_code_block_with_language():
    out = to_telegram_html("```python\nprint(1)\n```")
    assert out == '<pre><code class="language-python">print(1)</code></pre>'


def test_links():
    out = to_telegram_html("see [the docs](https://example.com/a?b=1) here")
    assert out == 'see <a href="https://example.com/a?b=1">the docs</a> here'


def test_bullets_and_numbered():
    out = to_telegram_html("- one\n- two\n  - nested")
    assert out == "• one\n• two\n  • nested"
    assert to_telegram_html("1. first\n2. second") == "1. first\n2. second"


def test_horizontal_rule():
    assert "──" in to_telegram_html("above\n\n---\n\nbelow")


def test_blockquote():
    assert to_telegram_html("> quoted") == "<blockquote>quoted</blockquote>"


def test_table_becomes_pre_block():
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    out = to_telegram_html(md)
    assert out.startswith("<pre>") and out.endswith("</pre>")
    assert "| a | b |" in out
    assert "|---|" in out


def test_collapses_blank_lines():
    assert to_telegram_html("a\n\n\n\n\nb") == "a\n\nb"


def test_mixed_document_is_valid_ish():
    md = (
        "# Report\n\n"
        "Found **2** issues in `main.py`:\n\n"
        "- the `<div>` is unclosed\n"
        "- see [ticket](https://t.example/9)\n\n"
        "```js\nconst x = a < b;\n```\n"
    )
    out = to_telegram_html(md)
    assert "<b>Report</b>" in out
    assert "<b>2</b>" in out
    assert "<code>main.py</code>" in out
    assert "<code>&lt;div&gt;</code>" in out
    assert '<a href="https://t.example/9">ticket</a>' in out
    assert '<pre><code class="language-js">const x = a &lt; b;</code></pre>' in out
    assert "**" not in out and "# Report" not in out


def test_strip_tags_roundtrips_to_plain():
    html = to_telegram_html("# Hi\n\n**bold** `c` <x>")
    plain = strip_tags(html)
    assert "<" not in plain.replace("<x>", "")  # only the escaped-then-stripped literal
    assert "bold" in plain and "Hi" in plain
