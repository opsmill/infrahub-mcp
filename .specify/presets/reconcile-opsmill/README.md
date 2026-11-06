# reconcile-opsmill

A spec-kit preset that **overrides** `speckit.reconcile.run` — the drift-fixing command provided by the [stn1slv/spec-kit-reconcile](https://github.com/stn1slv/spec-kit-reconcile) extension — with the OpsMill-maintained command body. The command is a post-implementation gap closer: it takes a natural-language gap report, surgically updates the feature's `spec.md` and `plan.md`, and appends remediation tasks (`T###`) to `tasks.md`.

The preset exists so OpsMill can adapt the command body to its repo structure without forking the upstream extension. Its first release is `1.1.0`, versioned to match the preset collection. The command body started as a verbatim lift of the upstream body — preserved as the baseline commit in this preset's git history — with the OpsMill adaptations layered on top:

- **Phase-block task placement** — remediation tasks land under existing `## Phase <N>:` blocks or a new `## Phase <max+1>: Remediation — Gap Report` block, never under non-phase headings (which the [`taskstoissues-jira`](../taskstoissues-jira/README.md) fan-out would silently skip).
- **Core `[P]` semantics** — `[P]` means "can run in parallel" (spec-kit core), not upstream's priority/urgency flag.
- **OpsMill compliance gate** — the CRITICAL-conflict check loads MUSTs from `dev/guidelines/` and decisions from `dev/adr/` in addition to `.specify/memory/constitution.md`.
- **Jira-aware Next Step** — when `dev/jira.yml` exists, the Sync Impact Report notes the remediation tasks have no Jira issue yet and warns against wholesale re-runs of `/speckit.taskstoissues`.

## Prerequisite: the `reconcile` extension

Preset overrides of extension commands only register when the target extension is installed (`specify` checks for `.specify/extensions/reconcile/`). Install the upstream extension first:

```bash
specify extension add reconcile \
  --from https://github.com/stn1slv/spec-kit-reconcile/archive/886f1dd.zip
```

If the extension is absent when the preset is added, the `speckit.reconcile.run` override is silently skipped, and nothing re-applies it when the extension arrives later — the preset reads as installed while the extension's own command body stays active. Install the extension first. To recover from a wrong-order install, re-register the preset once the extension is present:

```bash
specify preset remove reconcile-opsmill
specify preset add --dev opsmill-speckit/presets/reconcile-opsmill
```

## Install

```bash
git clone -b v1.3.2 https://github.com/opsmill/opsmill-speckit
specify preset add --dev opsmill-speckit/presets/reconcile-opsmill
```

Or from an existing working tree:

```bash
specify preset add --dev ./presets/reconcile-opsmill
```

After install, the preset's files live at `.specify/presets/reconcile-opsmill/` in the consumer repo, and `/speckit.reconcile.run` resolves to this preset's command body instead of the extension's.

## Usage

Provide a plain-text gap report describing the implementation drift:

```bash
/speckit.reconcile.run "Backend exists, but React screen is unreachable; need sidebar link and route"
```

Optional scope flags: `--spec-only`, `--plan-only`, `--tasks-only`.

## Provenance

The command body is derived from `commands/reconcile.md` in
[stn1slv/spec-kit-reconcile](https://github.com/stn1slv/spec-kit-reconcile)
at commit `886f1dd`, lifted verbatim as this preset's baseline commit and
then adapted (released as preset `1.1.0`) — the per-commit history on this
directory documents each divergence from upstream. Upstream is MIT-licensed by
Stanislav Deviatov; the license ships alongside in
[`LICENSE`](LICENSE).
