"""Render Claude's Markdown-ish output into the small HTML subset Telegram accepts.

Telegram `parse_mode="HTML"` supports only: ``<b> <i> <u> <s> <a href> <code>
<pre> <blockquote>``. Constructs we can't map degrade to readable plain text
instead of leaking Markdown punctuation: headings become bold lines, GFM tables
become a space-aligned monospace grid inside ``<pre>`` (column widths measured in
display cells, so CJK lines up), nested lists keep their indent. Only ``< > &``
are escaped in body text.

The caller sends the result with ``parse_mode="HTML"`` and, if Telegram still
rejects the markup, retries the same chunk tag-stripped via `strip_tags` — so a
converter bug can never drop a message, only un-style it.
"""

from __future__ import annotations

import html
import re
import unicodedata

_FENCE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(\S(?:.*?\S)?)\*\*|__(\S(?:.*?\S)?)__")
_ITALIC = re.compile(
    r"(?<![*\w])\*(\S(?:[^*\n]*?\S)?)\*(?![*\w])"
    r"|(?<![_\w])_(\S(?:[^_\n]*?\S)?)_(?![_\w])"
)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_HR = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_QUOTE = re.compile(r"^\s{0,3}(?:&gt;|>)\s?(.*)$")  # runs after html.escape
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")

_SENTINEL_RE = re.compile("\x00(\\d+)\x00")


def to_telegram_html(md: str) -> str:
    if not md or not md.strip():
        return "(empty)"

    kept: list[str] = []

    def keep(rendered: str) -> str:
        kept.append(rendered)
        return f"\x00{len(kept) - 1}\x00"

    md = md.replace("\r\n", "\n").replace("\r", "\n")

    # 1. fenced code -> <pre>, sealed off from every later rule
    def _fence(m: re.Match) -> str:
        lang = m.group(1).strip()
        body = html.escape(m.group(2).strip("\n"), quote=False)
        if lang:
            return keep(f'<pre><code class="language-{html.escape(lang, quote=False)}">{body}</code></pre>')
        return keep(f"<pre>{body}</pre>")

    md = _FENCE.sub(_fence, md)

    # 2. GFM tables -> a monospace <pre> block (Telegram has no table support)
    md = _tables_to_pre(md, keep)

    # 3. body text: escape, then line- and inline-level rules
    md = html.escape(md, quote=False)

    lines: list[str] = []
    for line in md.split("\n"):
        if _HR.match(line):
            lines.append("──────────")
            continue
        m = _HEADING.match(line)
        if m:
            lines.append(f"<b>{m.group(1).strip('*_ ')}</b>" if m.group(1).strip("*_ ") else "")
            continue
        m = _QUOTE.match(line)
        if m:
            lines.append(f"<blockquote>{m.group(1)}</blockquote>")
            continue
        m = _BULLET.match(line)
        if m:
            lines.append(f"{' ' * len(m.group(1))}• {m.group(2)}")
            continue
        m = _ORDERED.match(line)
        if m:
            lines.append(f"{' ' * len(m.group(1))}{m.group(2)}. {m.group(3)}")
            continue
        lines.append(line)
    md = "\n".join(lines)

    md = _INLINE_CODE.sub(lambda m: keep(f"<code>{m.group(1)}</code>"), md)
    md = _LINK.sub(lambda m: keep(f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>'), md)
    md = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", md)
    md = _ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", md)
    md = md.replace("<b><b>", "<b>").replace("</b></b>", "</b>")
    md = md.replace("<i><i>", "<i>").replace("</i></i>", "</i>")

    # 4. restore sealed spans, tidy whitespace
    md = _SENTINEL_RE.sub(lambda m: kept[int(m.group(1))], md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md or "(empty)"


def _tables_to_pre(md: str, keep) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if (
            _TABLE_LINE.match(lines[i])
            and i + 1 < len(lines)
            and _TABLE_SEP.match(lines[i + 1])
        ):
            block = [lines[i]]
            i += 1
            while i < len(lines) and _TABLE_LINE.match(lines[i]):
                block.append(lines[i])
                i += 1
            grid = _align_table(block) or "\n".join(block)
            out.append(keep("<pre>" + html.escape(grid, quote=False) + "</pre>"))
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


_SEP_CELL = re.compile(r"^:?-+:?$")


def _disp_width(s: str) -> int:
    """Column width of a string in a monospace block: CJK / fullwidth glyphs
    take two cells, everything else one."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def _align_table(block: list[str]) -> str | None:
    """Reformat a GFM table into a space-aligned monospace grid so it lines up
    in Telegram's <pre> font. Returns None if the block doesn't parse cleanly."""
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in block]
    if len(rows) < 2:
        return None
    ncol = len(rows[0])
    seps = rows[1]
    if len(seps) != ncol or not all(_SEP_CELL.match(s or "-") for s in seps):
        return None

    aligns = [
        "center" if s.startswith(":") and s.endswith(":")
        else "right" if s.endswith(":")
        else "left"
        for s in seps
    ]

    def fit(r: list[str]) -> list[str]:
        return (r + [""] * ncol)[:ncol]

    header, body = fit(rows[0]), [fit(r) for r in rows[2:]]
    width = [max(_disp_width(r[i]) for r in (header, *body)) for i in range(ncol)]

    def cell(text: str, i: int) -> str:
        gap = width[i] - _disp_width(text)
        if gap <= 0:
            return text
        if aligns[i] == "right":
            return " " * gap + text
        if aligns[i] == "center":
            return " " * (gap // 2) + text + " " * (gap - gap // 2)
        return text + " " * gap

    def line(r: list[str]) -> str:
        return "  ".join(cell(c, i) for i, c in enumerate(r)).rstrip()

    return "\n".join(
        [line(header), "  ".join("-" * w for w in width), *(line(r) for r in body)]
    )


def strip_tags(s: str) -> str:
    """HTML -> plain text, for the caller's fallback send."""
    return html.unescape(re.sub(r"<[^>]+>", "", s))


# --------------------------------------------------------------------------
# synthetic UserPromptSubmit payloads
#
# Claude Code fires UserPromptSubmit not just for what the user typed but also
# for machine-generated turns: a finished background task, a locally-run slash
# command, injected context blocks. Mirrored verbatim these are XML noise, so
# `tidy_prompt` rewrites the ones we recognise and drops the ones that carry
# nothing worth showing.
# --------------------------------------------------------------------------

_TASK_NOTIF = re.compile(r"^\s*<task-notification>(.*)</task-notification>\s*$", re.DOTALL)
_BG_CMD = re.compile(r'^Background command "(.+?)" (.+)$', re.DOTALL)
_CMD_WRAPPER = re.compile(r"^\s*<command-(name|message|args)>", re.DOTALL)
_STRIP_BLOCKS = re.compile(
    r"<(system-reminder|local-command-stdout|command-message|command-args)>.*?</\1>"
    r"|</?command-name>",
    re.DOTALL,
)
# slash commands that are pure local UI — not worth a line in the topic
_SKIP_COMMANDS = {"usage", "cost", "help", "clear", "config", "status"}

# A message the user sent from Telegram comes back through UserPromptSubmit wrapped
# in this preamble. user_prompt_submit.py already drops it; this is the backstop.
_PEER_ECHO_PREFIXES = (
    "Another Claude session sent a message",
    "A peer session sent a message",
)


def _inner(s: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", s, re.DOTALL)
    return m.group(1).strip() if m else ""


def tidy_prompt(text: str) -> tuple[str, str] | None:
    """Map a UserPromptSubmit payload to (role, text) for mirroring, or None to
    skip it. `role` is "user" for real input, "event" for machine-generated
    turns (rendered with a 🔔 prefix)."""
    s = text.strip()

    if s.startswith(_PEER_ECHO_PREFIXES):
        return None

    m = _TASK_NOTIF.match(s)
    if m:
        body = m.group(1)
        summary = _inner(body, "summary") or "background task finished"
        status = _inner(body, "status")
        bg = _BG_CMD.match(summary)
        line = f"{bg.group(1)} — {bg.group(2)}" if bg else summary
        if status and status not in line:
            line = f"{line} [{status}]"
        return ("event", line)

    if _CMD_WRAPPER.match(s):
        name = _inner(s, "command-name")
        if not name or name in _SKIP_COMMANDS:
            return None
        args = _inner(s, "command-args")
        return ("event", f"/{name} {args}".rstrip())

    stripped = _STRIP_BLOCKS.sub("", s).strip()
    if not stripped:
        return None
    if stripped != s:
        return ("user", stripped)
    return ("user", text)
