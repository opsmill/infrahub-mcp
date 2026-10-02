# Changelog

All notable changes to this extension will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-05-01

### Added

- Initial release of Session Summary extension.
- Command: `/speckit.summary.run` — flow-level summary of the
  current Claude Code session.
- Optional `--since <commit|time>` argument to bound the summary
  window.
- Output at `FEATURE_DIR/sessions/session-YYYY-MM-DD-HHMM.md`, next
  to `spec.md` / `plan.md`.
- Three-section output: executive summary, chronological timeline,
  outcomes.
- Manual-only invocation — no hooks. A session boundary is a human
  judgment call.

### Requirements

- Spec Kit: >=0.1.0
