#!/usr/bin/env python3
"""Render a curated release-notes page as a GitHub Release body.

Reads ``docs/docs/release-notes/release-X_Y_Z.mdx`` and prints GitHub-flavored
Markdown: everything from the first ``## `` heading on (the frontmatter and the
metadata table are site-only), Docusaurus admonitions turned into blockquotes,
and relative links into the docs site reduced to their text, since they do not
resolve on GitHub (images are left as written rather than mangled into a stray
``!``). Fenced code blocks are copied verbatim, so a ``:::`` line or a link in a
code sample is never treated as markup. With ``--previous-tag``, a Full
Changelog compare link is appended.

Usage: release_body.py VERSION [--previous-tag vX.Y.Z]
"""

import argparse
import re
import sys
from pathlib import Path

REPO = "opsmill/infrahub-mcp"
NOTES_DIR = Path(__file__).resolve().parent.parent / "docs" / "docs" / "release-notes"

# The body is any run of lines (possibly none) that do not themselves start with
# ``:::``, so a marker never pairs with a closer past another admonition line.
ADMONITION = re.compile(r"^:::(\w+)[ \t]*([^\n]*)\n((?:(?!:::)[^\n]*\n)*?):::[ \t]*$", re.MULTILINE)
LEFTOVER_MARKER = re.compile(r"^:::", re.MULTILINE)
RELATIVE_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\((?!https?:|#|mailto:)[^)]+\)")
# Fenced code blocks are swapped for one-line placeholders before the rewrites
# above run, then restored (carrying any ``> `` prefix an admonition added), so
# a fence inside an admonition still converts with it. An opener's closer is a
# run of the same character at least as long; an unterminated fence runs to the
# end of the body.
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
PLACEHOLDER = re.compile(r"^(.*)\x00(\d+)\x00$", re.MULTILINE)


def notes_path(version: str) -> Path:
    return NOTES_DIR / f"release-{version.replace('.', '_')}.mdx"


def _blockquote(match: re.Match[str]) -> str:
    kind, title, inner = match.groups()
    lines = [f"> **{title.strip() or kind.capitalize()}**"]
    inner = inner.strip("\n")
    if inner:
        lines.append(">")
        lines += [f"> {line}" if line.strip() else ">" for line in inner.split("\n")]
    return "\n".join(lines)


def _protect_fences(body: str) -> tuple[str, list[list[str]]]:
    out: list[str] = []
    fences: list[list[str]] = []
    lines = body.split("\n")
    i = 0
    while i < len(lines):
        opener = FENCE_OPEN.match(lines[i])
        if opener is None:
            out.append(lines[i])
            i += 1
            continue
        fence = opener.group(1)
        closer = re.compile(rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
        end = i + 1
        while end < len(lines) and not closer.match(lines[end]):
            end += 1
        out.append(f"\x00{len(fences)}\x00")
        fences.append(lines[i : end + 1])
        i = end + 1
    return "\n".join(out), fences


def _restore_fences(body: str, fences: list[list[str]]) -> str:
    def restore(match: re.Match[str]) -> str:
        prefix, index = match.group(1), int(match.group(2))
        quoted = prefix.rstrip()
        return "\n".join(prefix + line if line.strip() or not quoted else quoted for line in fences[index])

    return PLACEHOLDER.sub(restore, body)


def render(mdx: str, version: str, previous_tag: str | None = None) -> str:
    start = re.search(r"^## ", mdx, re.MULTILINE)
    if start is None:
        message = "release-notes page has no '## ' heading to start the body from"
        raise ValueError(message)
    body, fences = _protect_fences(mdx[start.start() :])
    body = ADMONITION.sub(_blockquote, body)
    leftover = LEFTOVER_MARKER.search(body)
    if leftover is not None:
        line = body[leftover.start() :].split("\n", 1)[0]
        message = f"unterminated or malformed admonition: {line!r}"
        raise ValueError(message)
    body = RELATIVE_LINK.sub(r"\1", body)
    body = _restore_fences(body, fences)
    body = body.rstrip() + "\n"
    if previous_tag:
        compare = f"https://github.com/{REPO}/compare/{previous_tag}...v{version}"
        body += f"\n---\n\n**Full Changelog**: {compare}\n"
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="release version without the leading v, e.g. 1.3.0")
    parser.add_argument("--previous-tag", help="tag to compare against, e.g. v1.2.0")
    args = parser.parse_args()

    path = notes_path(args.version)
    if not path.is_file():
        print(f"no release-notes page at {path}", file=sys.stderr)
        return 1
    try:
        body = render(path.read_text(), args.version, args.previous_tag)
    except ValueError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
