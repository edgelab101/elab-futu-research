---
name: elab-futu-research
description: Archive a Futu/Moomoo public profile's visible dynamics and columns, preserve raw evidence and media, enrich time-frozen claims with market context, compare trading behavior across regimes, and generate auditable blogger research. Use when a user provides one or more q.futunn.com profile URLs or asks to crawl, save, review, compare, or analyze Futu bloggers, posts, columns, trading style, discipline, tone, or historical calls.
---

# Elab Futu Research

Turn one or more public Futu profile URLs into a resumable archive and an evidence-bounded research report. Make the default experience one-shot: accept the URL, choose safe defaults, run the workflow, and return the report plus audit status.

Version: `1.1.1` · Last updated: `2026-07-22`

## Startup alignment (required)

Before running any capture or producing any deliverable, align on the following four items. If the user's initial message already answers an item, **do not re-ask it** — simply acknowledge it in the summary line below.

Collect only what is still missing, in **one message** (not one question per item):

1. **Research target** — which Futu profile URL(s) or numeric UID(s)?
2. **Time range** — default is all publicly visible history; echo this back explicitly even when the user did not specify ("全量历史" or the explicit window they gave).
3. **Deliverables** — one or more of: ① 完整归档 ② 研究报告 ③ 多博主对比 ④ 规则卡 (multiple allowed).
4. **Other constraints** — skip media, custom output directory, redaction needs, or anything else that changes the run.

Once all four items are known, reply with **one summary line** before issuing any command:

> 博主 \<X\> · 范围 \<Y\> · 交付 \<Z\> · 输出目录 \<W\> · elab-futu-research by 杰尼马（EdgeLab）

Then proceed with the workflow.

## Default behavior

- Require only a profile URL or numeric UID.
- If no date is supplied, capture all content still visible at run time.
- Always capture both streams:
  - dynamics/all (`type=301`)
  - columns (`type=302`)
- Preserve original posts and reposts. Exclude reposts from ability scoring by default, but keep them searchable.
- Download public post media unless the user opts out.
- Write to `./futu-research-output/` unless the user names another directory.
- Resume safely from cached pages/details/media. Never delete raw evidence; rebuild derived files atomically.
- Use conservative request rates. Stop and report interface drift, login, CAPTCHA, or access denial; do not bypass access controls.
- Follow the **Startup alignment** section above before starting any capture.

## Fast path

From the repository or installed skill directory:

```bash
python3 scripts/futu_research.py run \
  --profile "https://q.futunn.com/profile/<uid>" \
  --output "./futu-research-output"
```

For multiple bloggers, repeat `--profile`. Optional `--since YYYY-MM-DD` and `--until YYYY-MM-DD` limit the archive. Use `--skip-media` only when requested.

Run the environment and endpoint check first when the interface may have changed:

```bash
python3 scripts/futu_research.py doctor \
  --profile "https://q.futunn.com/profile/<uid>"
```

## Workflow

### 1. Capture and normalize

Run `archive`, or use `run` for the full deterministic pipeline.

```bash
python3 scripts/futu_research.py archive --profile "<profile-url>" --output "<dir>"
```

Do not call an archive complete unless `qa/crawl_audit.json` confirms:

- both streams were attempted;
- each requested stream reached `has_more=0`, or crossed the requested start boundary;
- all retained feed IDs have cached detail responses or appear in an explicit failure list;
- normalized IDs are unique;
- media failures are listed rather than silently dropped.

“All history” means all public content returned by Futu at capture time. It cannot include deleted, private, region-restricted, or otherwise unavailable content.

### 2. Create claim candidates

`prepare` creates deterministic, reviewable candidates. Treat them as prelabels, never final truth.

```bash
python3 scripts/futu_research.py prepare --output "<dir>"
```

Use these evidence levels:

- `A`: order/fill/cost/position/P&L evidence verified from an image or primary record.
- `B`: explicit first-person trade action in text.
- `C`: market or security opinion without verified action.
- `D`: mention, repost, joke, question, or attention only.

Never infer a holding from `C` or `D`. The script never assigns `A` automatically.

### 3. Review before outcomes

Read `analysis/candidates.jsonl`, the cited post text, and relevant images. Write reviewed decisions to `analysis/claims.reviewed.jsonl` using `references/data-schema.md`.

Freeze each claim before fetching or inspecting forward returns. Record:

- quoted evidence span;
- symbol and direction;
- action, horizon, conditions, invalidation, and risk rule;
- evidence level and whether image evidence was actually inspected;
- confidence and unresolved ambiguity.

If using OCR or vision, preserve the source image path and extracted text. Do not upgrade to `A` from a filename, thumbnail, or unverified OCR alone.

### 4. Add time-frozen market context

```bash
python3 scripts/futu_research.py market --output "<dir>"
```

The context cutoff is the last completed daily bar known at post time. Evaluation begins at the next tradable daily open. Keep symbol mappings in `analysis/symbol_overrides.json`; unresolved mappings remain unresolved.

Use 1/5/20/60-session forward paths, MFE, MAE, and benchmark-relative returns when data are available. Do not fabricate option returns from an underlying chart.

### 5. Build reports

```bash
python3 scripts/futu_research.py report --output "<dir>"
python3 scripts/futu_research.py audit --output "<dir>"
```

Read `references/analysis-method-v1.md` before writing final judgments. Produce:

- evidence coverage and limitations;
- capability matrix, not one total leaderboard;
- market-regime episodes and before/after changes;
- trading style, strategy completeness, discipline, and risk handling;
- counterexamples and confidence;
- transferable rule cards for the user.

Do not diagnose personality or mental illness. Do not turn the report into a follow-trading recommendation. Separate author claims, observed public execution evidence, market outcomes, and inference.

## Output contract

The run directory contains:

```text
raw/list/<uid>/{all,columns}/page_*.json
raw/details/<uid>/<feed_id>.json
media/<uid>/<feed_id>/*
archive/posts.jsonl
archive/posts.csv
archive/monthly/*.md
analysis/candidates.jsonl
analysis/claims.reviewed.jsonl
analysis/episodes.jsonl
analysis/market/*.csv
reports/profile.md
reports/capability_matrix.md
reports/rule_cards.md
qa/crawl_audit.json
qa/adversarial_audit.json
manifest.json
```

Some later files appear only after their corresponding step. Preserve `raw/` as immutable evidence.

## Reporting rules

- Lead with one actionable conclusion, then evidence and caveats.
- Label machine-only output as `exploratory`.
- A favorable sample is not stable alpha.
- With fewer than 20 eligible claims per author/window, report descriptive results only.
- For larger samples, use uncertainty intervals and correct multiple comparisons as described in the method.
- Explicitly distinguish mention, opinion, claimed action, verified position evidence, and account-level return.
- Include failures and missingness in the report.

## References

Read only what the task requires:

- Capture, pagination, fallback, and completeness: `references/capture-and-runtime.md`
- Market-data adapters, CSV fallback, and symbol mapping: `references/market-data.md`
- Claim/episode/profile methodology and statistics: `references/analysis-method-v1.md`
- File and record schemas: `references/data-schema.md`
- Privacy, publishing, and compliance: `references/privacy-and-compliance.md`

## Safety boundary

Use only public content or content the user is authorized to access. Never export browser cookies, tokens, private messages, follower-only data, or unrelated personal data. Respect site terms, robots guidance, rate limits, and applicable law. If the API or page requires new authentication or anti-bot circumvention, stop and explain the legitimate next step.
