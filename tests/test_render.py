"""Markdown -> Telegram-HTML conversion."""

from __future__ import annotations

from claude_bridge_telegram.render import strip_tags, tidy_prompt, to_telegram_html


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


def test_table_becomes_aligned_pre_block():
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    out = to_telegram_html(md)
    assert out == "<pre>a  b\n-  -\n1  2</pre>"


def test_table_columns_align_on_display_width():
    md = (
        "| 이름 | qty |\n"
        "|---|---:|\n"
        "| alpha | 3 |\n"
        "| 긴 이름 | 1200 |\n"
    )
    out = to_telegram_html(md)
    body = out.removeprefix("<pre>").removesuffix("</pre>").split("\n")
    # every rendered row is the same display width (columns line up)
    from claude_bridge_telegram.render import _disp_width

    assert len({_disp_width(line) for line in body}) == 1
    assert "1200" in out and "  3" in out  # right-aligned numeric column


def test_ragged_table_falls_back_to_raw_pre():
    md = "| a | b | c |\n|---|---|\n| 1 | 2 | 3 |"  # header 3 cols, separator 2
    out = to_telegram_html(md)
    assert out.startswith("<pre>") and "| a | b | c |" in out


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


# --- tidy_prompt -------------------------------------------------------------

def test_tidy_plain_prompt_passes_through():
    assert tidy_prompt("복구 진행해") == ("user", "복구 진행해")


def test_tidy_task_notification_to_one_liner():
    payload = (
        "<task-notification>\n"
        "<task-id>bp6unl86s</task-id>\n"
        "<tool-use-id>toolu_01WoVA</tool-use-id>\n"
        "<output-file>/tmp/x/bp6unl86s.output</output-file>\n"
        "<status>completed</status>\n"
        '<summary>Background command "Test restore of competition" completed (exit code 0)</summary>\n'
        "</task-notification>"
    )
    role, text = tidy_prompt(payload)
    assert role == "event"
    assert text == "Test restore of competition — completed (exit code 0)"
    assert "<task-id>" not in text and "output-file" not in text


def test_tidy_slash_command():
    p = "<command-name>diff</command-name><command-message>diff</command-message><command-args>HEAD~1</command-args>"
    assert tidy_prompt(p) == ("event", "/diff HEAD~1")


def test_tidy_skips_pure_ui_commands():
    assert tidy_prompt("<command-name>usage</command-name><command-args></command-args>") is None


def test_tidy_skips_lone_context_block():
    assert tidy_prompt("<system-reminder>be nice</system-reminder>") is None
    assert tidy_prompt("<local-command-stdout></local-command-stdout>") is None


def test_tidy_keeps_real_text_around_a_context_block():
    role, text = tidy_prompt("<system-reminder>ctx</system-reminder>\n\nfix the bug")
    assert role == "user"
    assert text == "fix the bug"
