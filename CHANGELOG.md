# Changelog

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
