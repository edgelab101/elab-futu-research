# Changelog

## 1.3.0 — 2026-07-23

Added:

- Multi-platform adapter architecture: `CaptureAdapter` base class with platform-specific implementations; URL domain dispatcher auto-routes `laohu8.com` → `TigerAdapter`, `q.futunn.com` / numeric UID → `FutuAdapter`.
- `TigerAdapter`: pure-stdlib HTML parser for laohu8.com community profiles; extracts post text, timestamps, interaction counts, and `$Name(CODE)$`-format stock symbols from Tiger posts.
- Tiger platform support via `--profile "https://www.laohu8.com/personal/<uid>/"` — downstream `prepare`, `market`, `report`, and `export-authors` steps reuse unchanged.

Changed:

- Crawl audit now validates against `adapter.expected_streams` rather than hardcoding "dynamics + columns"; Tiger archives pass with dynamics-only stream.
- Monthly markdown titles and report headers use platform-neutral wording (no Futu-specific labels).
- `export-authors` homepage link uses the platform URL recorded in each author's archive entry, not a hardcoded Futu URL pattern.

## 1.2.1 — 2026-07-23

Added:

- `export-authors` subcommand, also run automatically at the end of `report` (and therefore `run`): splits the combined archive into one readable markdown file per blogger under `archive/by-author/<author-name>_<uid>.md`, plus an `index.md` sorted by post count. Posts are newest-first with full text, repost attribution, and per-post links. Solves browsing a single blogger's content by name instead of by numeric-UID `raw/` folders.

Robustness:

- Filesystem-safe author filenames (illegal + control chars replaced, CJK/emoji preserved, uid suffix for uniqueness); pipe in author names escaped in the index table; multiline repost text fully quoted; missing `posts.jsonl` fails with a clear error.

## 1.2.0 — 2026-07-23

Added:

- `--media {all,none,evidence}` flag (default `all`). `evidence` mode downloads media only from posts whose title or text matches built-in `EVIDENCE_MEDIA_KEYWORDS` (订单/成交/持仓/清仓/盈亏/对账单/order/filled/position/pnl etc.), useful for order-screenshot bloggers. `--skip-media` is retained as an alias for `--media none`; when both are supplied, `--media` takes precedence with a warning.
- Trailing tag noise reduction in `prepare`: consecutive ≥3 `$symbol$` tag blocks at the end of a post where the symbol was not discussed in the body are downgraded to `D` (mention only) and excluded from directional claim scoring. Addresses cases where up to 73% of candidates in some archives were pure exposure-tag artefacts.

Changed:

- Audit uniqueness now keyed on `(profile_uid, feed_id)` instead of `feed_id` alone, eliminating false-positive `error` reports when post A reposts post B and both appear in a multi-blogger archive (6 bloggers, 7 collisions all of this type in real testing).
- Media tripwire denominator changed from `posts` to `posts_with_image_content`; text-only bloggers no longer trigger spurious WARN. Posts skipped by `--media none` are marked `skipped_by_mode`; posts that have image content but produced 0 media tasks still emit WARN.

Fixed:

- `_repost_original_obj` empty-structure guard: a non-empty `dict` with both `richTextItems` and `pictureItems` absent is no longer classified as a repost.

## 1.1.2 — 2026-07-22

Fixed:

- `main()` now catches `OSError` and prints a human-readable ERROR message before exiting with code 2, instead of raising an unformatted traceback.
- `archive`: when 0 posts are retrieved, the summary output now includes a "verify the UID" note to help diagnose invalid or private profile targets.
- `doctor` without `--profile` now reports `status=PARTIAL` instead of failing silently or crashing.
- `CN_TZ` initialization: added `ZoneInfo` fallback to a fixed UTC+8 offset when the timezone database is unavailable (e.g., Windows without `tzdata`). Script no longer crashes on import.
- Bare 5-digit numeric symbols are now treated as Hong Kong market tickers (e.g., `09988` → `9988.HK`) rather than being passed through unresolved.
- `report`, `market`, and `audit` now emit an explicit error and direct the user to run `archive` / `prepare` first when the expected input directory is empty, instead of silently producing an empty output.

Changed:

- `REPORT_FOOTER` attribution updated to `作者：杰尼马（EdgeLab） · 专注美港股与期权研究`.
- Added Python 3.9 version guard at script top; `VERSION` constant updated to `1.1.2`.
- `install.sh`: `BASH_SOURCE` reference made zsh-compatible; backup directory name uses millisecond timestamp to prevent collisions on rapid consecutive installs.

## 1.1.1 — 2026-07-22

- Fix install.sh backup pollution: backup directory now goes to
  `~/.elab-futu-research-backups/<agent>-<timestamp>/` instead of
  `<skills-dir>/elab-futu-research.backup.<timestamp>/`.  Previously each
  reinstall left a sibling directory containing SKILL.md inside the skills
  folder, causing Claude Code / Codex to load multiple ghost copies of the
  skill.  Automatic pruning keeps at most 3 backups per agent type.  Uses
  bash-3.2-compatible constructs; no mapfile/readarray.
- README: add "环境要求" subsection (macOS/Linux/Windows bash, Python 3.9+,
  no third-party deps, no API key).
- README: add "账号安全 FAQ" section (no login, no Cookie, conservative rate
  limiting, --since window tip, behavior on CAPTCHA/drift).
- README: add "产出物使用边界" section (self-use OK; do not distribute full
  archives containing others' original posts; redact identifiable info;
  link to sample report).
- docs/sample-report.md: new fully synthetic sample demonstrating the
  profile.md output structure (ability matrix, market-state analysis, rule
  cards, evidence distribution, failure log, completeness note).  All data
  is fictional; real UIDs and real blogger content are absent.
- VERSION bump: SKILL.md, futu_research.py, CHANGELOG.md, CURRENT.md.

## 1.1.0 — 2026-07-22

- Fix repost misattribution: detect self-reposts via `feedModel.original` / `moduleData[i].data.origin`
  rather than author-UID comparison, which always matched for self-reposts.
- Split repost text: author's own comment goes to `text`; reposted content goes to new
  `original_text` field; original poster name (when present) goes to new `original_author` field.
- Fix title generation for reposts: uses own comment first, then `转发：<original preview>`,
  eliminating the duplicate-concatenation artifact.
- Update `references/data-schema.md` with `original_text` and `original_author` fields.
- Monthly Markdown now shows repost source line "原创：否；转自：<author>" and renders
  original content as a blockquote below the author's own comment.
- Startup alignment contract: `SKILL.md` now requires aligning on research target,
  time range, deliverables, and other constraints before any capture, with a one-line
  parameter summary echo ending in "elab-futu-research by 杰尼马（EdgeLab）".
- Report footer credit added to all three report files (`profile.md`, `capability_matrix.md`,
  `rule_cards.md`): attribution, social handles, and "本报告仅供研究参考，不构成任何投资建议。"
- README: brand line "by 杰尼马 · EdgeLab：给散户的可审计投研工具箱" added below title;
  alignment step description added to the 最省事的用法 section.
- `install.sh`: completion message now includes "更多工具：github.com/edgelab101".
- Test suite extended with `test_repost_attribution` (is_repost, text/original_text split,
  title correctness) and report-footer assertions in the end-to-end test.
- Fix media download silent zero-job failure: `extract_media_urls` now handles the real Futu
  nested image structure where `orgPic`/`bigPic`/`thumbPic` values are `{url, width, height}`
  dicts rather than bare URL strings.  Priority within each pictureItem: orgPic > bigPic;
  thumbPic is never downloaded.  Dict-valued `display`/`preview` keys at module level now
  also extract `.url` correctly.
- Adversarial audit: new `media_extraction_not_zero_jobs` tripwire emits WARN when
  `skip_media=false`, `posts>0`, and `media_objects=0` — catches future regressions silently.
- Test suite extended with `test_media_url_extraction`: nested orgPic collected, bigPic
  excluded when orgPic present, thumbPic never collected, bigPic fallback when orgPic absent,
  dict-valued display key extracted.

## 1.0.0 — 2026-07-22

- Initial public Skill for Codex and Claude Code.
- Resumable capture of both Futu dynamics and columns.
- Raw detail and public-media preservation with completeness auditing.
- Conservative claim prelabels and A/B/C/D evidence workflow.
- Time-frozen Yahoo Finance daily market enrichment.
- Episode candidates, uncertainty boundaries, BH FDR support, reports, and adversarial audit.
- Fully synthetic offline end-to-end test fixture.
