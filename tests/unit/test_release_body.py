"""Tests for converting a release-notes page into a GitHub Release body."""

import importlib.util
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release_body.py"
spec = importlib.util.spec_from_file_location("release_body", SCRIPT)
if spec is None or spec.loader is None:
    msg = f"could not load release-body script at {SCRIPT}"
    raise ImportError(msg)
release_body = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_body)

PAGE = """---
title: Release 9.9.9
---

<table>
  <tbody>
    <tr><th>Release Number</th><td>9.9.9</td></tr>
  </tbody>
</table>

## Release summary

After upgrading, you can do things.

:::note What to expect after upgrading

Nothing changed.

- Review one thing.

:::

### A feature

Use [configuration](../references/configuration.mdx) and see [Upgrade notes](#upgrade-notes)
or [towncrier](https://towncrier.readthedocs.io/).

:::tip

Untitled tip.

:::

## Upgrade notes
"""


def test_drops_frontmatter_and_table() -> None:
    body = release_body.render(PAGE, "9.9.9")
    assert body.startswith("## Release summary\n")
    assert "title:" not in body
    assert "<table>" not in body


def test_admonitions_become_blockquotes() -> None:
    body = release_body.render(PAGE, "9.9.9")
    assert ":::" not in body
    assert "> **What to expect after upgrading**\n>\n> Nothing changed.\n>\n> - Review one thing." in body
    assert "> **Tip**\n>\n> Untitled tip." in body


def test_relative_links_reduced_to_text_others_kept() -> None:
    body = release_body.render(PAGE, "9.9.9")
    assert "Use configuration and" in body
    assert "[Upgrade notes](#upgrade-notes)" in body
    assert "[towncrier](https://towncrier.readthedocs.io/)" in body


def test_relative_images_left_intact() -> None:
    body = release_body.render("## h\n\n![arch](../assets/arch.png) and [cfg](../cfg.mdx)\n", "9.9.9")
    assert "![arch](../assets/arch.png) and cfg\n" in body


def test_compare_link_only_with_previous_tag() -> None:
    assert "Full Changelog" not in release_body.render(PAGE, "9.9.9")
    body = release_body.render(PAGE, "9.9.9", "v9.9.8")
    assert body.endswith(
        "\n---\n\n**Full Changelog**: https://github.com/opsmill/infrahub-mcp/compare/v9.9.8...v9.9.9\n"
    )


def test_page_without_heading_is_rejected() -> None:
    with pytest.raises(ValueError, match="has no '## ' heading"):
        release_body.render("---\ntitle: x\n---\n\nno heading\n", "9.9.9")


def test_bodyless_admonitions_become_blockquotes() -> None:
    body = release_body.render("## h\n\n:::tip Title\n:::\n\n:::note\n:::\n\ntext\n", "9.9.9")
    assert ":::" not in body
    assert "> **Title**\n\n> **Note**\n\ntext\n" in body


def test_bracketed_admonition_title_drops_delimiters() -> None:
    body = release_body.render("## h\n\n:::warning[Breaking change]\n\nBody.\n\n:::\n\n:::tip[]\n:::\n", "9.9.9")
    assert "> **Breaking change**\n>\n> Body.\n\n> **Tip**" in body
    assert "[" not in body


def test_unterminated_admonition_is_rejected() -> None:
    with pytest.raises(ValueError, match="unterminated or malformed admonition"):
        release_body.render("## h\n\n:::note\n\ndangling note\n", "9.9.9")


def test_marker_does_not_pair_past_another_admonition() -> None:
    with pytest.raises(ValueError, match="unterminated or malformed admonition"):
        release_body.render("## h\n\n:::note\n\ndangling\n\n:::tip\n\nok\n\n:::\n", "9.9.9")


def test_fenced_code_is_left_verbatim() -> None:
    code = "```markdown\n:::note\nnot an admonition\n\n[cfg](../cfg.mdx)\n```\n"
    tilde = "~~~~\n:::\n~~~\nstill code\n~~~~\n"
    body = release_body.render(f"## h\n\n{code}\n{tilde}\nafter [cfg](../cfg.mdx)\n", "9.9.9")
    assert f"## h\n\n{code}\n{tilde}\nafter cfg\n" == body


def test_unterminated_fence_runs_to_end() -> None:
    body = release_body.render("## h\n\n```\n:::note\n", "9.9.9")
    assert body == "## h\n\n```\n:::note\n"


def test_admonition_containing_fence_converts() -> None:
    page = "## h\n\n:::tip Example\n\nRun:\n\n```text\n:::\n\nvalue\n```\n\n:::\n"
    body = release_body.render(page, "9.9.9")
    assert body == "## h\n\n> **Example**\n>\n> Run:\n>\n> ```text\n> :::\n>\n> value\n> ```\n"


def test_inline_code_links_left_verbatim() -> None:
    body = release_body.render("## h\n\nWrite `[x](./y)` or ``[a](../b)``, not [cfg](../cfg.mdx).\n", "9.9.9")
    assert body == "## h\n\nWrite `[x](./y)` or ``[a](../b)``, not cfg.\n"


def test_nested_fences_left_verbatim() -> None:
    page = "## h\n\n- Step:\n\n    ```md\n    [cfg](../cfg.mdx)\n    ```\n\n> ```md\n> [cfg](../cfg.mdx)\n> ```\n"
    assert release_body.render(page, "9.9.9") == page


def test_every_published_page_renders() -> None:
    pages = sorted(release_body.NOTES_DIR.glob("release-*.mdx"))
    assert pages
    for page in pages:
        body = release_body.render(page.read_text(), "0.0.0")
        # Code samples are copied verbatim, so only prose outside them must be free of markup.
        prose, _ = release_body._protect_fences(body)  # noqa: SLF001
        prose = re.sub(r"(`+)[^\n]*?\1", "", prose)
        assert ":::" not in prose, page.name
        assert "](../" not in prose, page.name


def test_notes_path_maps_version_to_page_name() -> None:
    assert release_body.notes_path("1.2.0") == release_body.NOTES_DIR / "release-1_2_0.mdx"


def test_publish_workflow_uses_same_page_name() -> None:
    workflow = SCRIPT.parents[1] / ".github" / "workflows" / "release-publish.yml"
    assert 'release-notes/release-${VERSION//./_}.mdx"' in workflow.read_text()


def test_main_missing_page_returns_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(release_body, "NOTES_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["release_body.py", "1.2.0"])
    assert release_body.main() == 1
    out, err = capsys.readouterr()
    assert not out
    assert f"no release-notes page at {tmp_path / 'release-1_2_0.mdx'}" in err


def test_main_writes_rendered_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "release-9_9_9.mdx").write_text(PAGE)
    monkeypatch.setattr(release_body, "NOTES_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["release_body.py", "9.9.9", "--previous-tag", "v9.9.8"])
    assert release_body.main() == 0
    out, err = capsys.readouterr()
    assert out == release_body.render(PAGE, "9.9.9", "v9.9.8")
    assert not err


def test_main_malformed_page_returns_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "release-9_9_9.mdx").write_text("## h\n\n:::note\n\ndangling\n")
    monkeypatch.setattr(release_body, "NOTES_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["release_body.py", "9.9.9"])
    assert release_body.main() == 1
    out, err = capsys.readouterr()
    assert not out
    assert "unterminated or malformed admonition" in err
