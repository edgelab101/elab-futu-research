#!/usr/bin/env python3
"""Archive and analyze public Futu profile content with an auditable evidence chain.

The core path intentionally uses only the Python standard library. Platform
endpoints are unofficial implementation details and are validated at runtime.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import csv
import hashlib
import html
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"
LIST_URL = "https://q.futunn.com/nnq/personal-list"
DETAIL_URL = "https://q.futunn.com/v2/api/feed/detail"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
EASTMONEY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
USER_AGENT = (
    "elab-futu-research/1.0 "
    "(public-research-tool; +https://github.com/edgelab101/elab-futu-research)"
)
CN_TZ = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
STREAMS = {301: "all", 302: "columns"}
TYPE_LABELS = {
    3: "帖子/话题",
    4: "专题文章",
    5: "股票评论",
    7: "其他动态",
}
URL_MEDIA_KEYS = {
    "orgpic",
    "bigpic",
    "display",
    "preview",
    "thumb",
    "imageurl",
    "image_url",
    "picurl",
    "pic_url",
}
SYMBOL_STOPLIST = {
    "ADR",
    "AI",
    "API",
    "ATM",
    "CALL",
    "CEO",
    "CFO",
    "CPI",
    "DCF",
    "ETF",
    "FED",
    "FOMC",
    "GDP",
    "GPU",
    "HKD",
    "IPO",
    "ITM",
    "KOL",
    "LTM",
    "MACD",
    "NAV",
    "OTM",
    "PCE",
    "PUT",
    "QE",
    "QOQ",
    "ROI",
    "RSI",
    "SEC",
    "TAM",
    "USD",
    "YOY",
    "YTD",
}
FIRST_PERSON = (
    "我",
    "本人",
    "我的",
    "我们",
    "my ",
    "i ",
    "i'm",
    "i’ve",
    "we ",
)
ACTION_KEYWORDS = {
    "buy": ("买入", "买了", "开仓", "建仓", "抄底", "bought", "buying", "long "),
    "add": ("加仓", "补仓", "增持", "加了", "added", "add position"),
    "hold": ("持有", "继续拿", "没卖", "守仓", "holding", "hold "),
    "reduce": ("减仓", "减持", "卖掉部分", "止盈部分", "trimmed", "reduce"),
    "sell": ("卖出", "清仓", "止盈", "离场", "卖了", "sold", "closed"),
    "short": ("做空", "开空", "买put", "买 put", "shorted", "short "),
    "cover": ("平空", "空单止盈", "cover short", "covered"),
    "watch": ("关注", "观察", "等待", "自选", "watchlist", "watching"),
}
BULLISH_KEYWORDS = (
    "看多",
    "看涨",
    "低估",
    "估值偏低",
    "上行",
    "突破",
    "新高",
    "利好",
    "增长",
    "反弹",
    "bullish",
    "undervalued",
    "upside",
)
BEARISH_KEYWORDS = (
    "看空",
    "看跌",
    "高估",
    "估值偏高",
    "下行",
    "跌破",
    "新低",
    "利空",
    "衰退",
    "bearish",
    "overvalued",
    "downside",
)
RISK_KEYWORDS = (
    "止损",
    "仓位",
    "风险",
    "回撤",
    "失效",
    "不及预期",
    "控制",
    "对冲",
    "stop loss",
    "position size",
    "risk",
    "hedge",
)
CONDITION_KEYWORDS = (
    "如果",
    "若",
    "除非",
    "一旦",
    "前提",
    "条件",
    "if ",
    "unless",
    "provided",
)
CERTAINTY_KEYWORDS = (
    "一定",
    "必然",
    "肯定",
    "毫无疑问",
    "必涨",
    "必跌",
    "definitely",
    "certainly",
    "must ",
)
URGENCY_KEYWORDS = (
    "立刻",
    "马上",
    "赶紧",
    "最后机会",
    "不能等",
    "now",
    "immediately",
    "urgent",
)


class ResearchError(RuntimeError):
    """A user-actionable workflow failure."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def log(message: str) -> None:
    print(message, flush=True)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ResearchError(f"Invalid JSONL at {path}:{number}: {error}") from error
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    atomic_write_text(path, text)


def parse_uid(value: str) -> str:
    candidate = str(value or "").strip()
    if re.fullmatch(r"\d{3,20}", candidate):
        return candidate
    match = re.search(r"/profile/(\d{3,20})(?:[/?#]|$)", candidate)
    if match:
        return match.group(1)
    raise ResearchError(
        f"Cannot find a numeric profile UID in {candidate!r}. "
        "Paste a URL like https://q.futunn.com/profile/<uid>."
    )


def parse_day(value: Optional[str], end: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ResearchError(f"Invalid date {value!r}; expected YYYY-MM-DD.") from error
    clock = datetime_time(23, 59, 59) if end else datetime_time(0, 0, 0)
    return datetime.combine(parsed, clock, tzinfo=CN_TZ)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def request_bytes(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    attempts: int = 4,
    timeout: int = 45,
) -> Tuple[bytes, Dict[str, str]]:
    full_url = url
    if params:
        full_url = f"{url}?{urllib.parse.urlencode(params)}"
    last_error: Optional[BaseException] = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            full_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                body = response.read()
                return body, {
                    "content_type": content_type,
                    "final_url": response.geturl(),
                    "status": str(getattr(response, "status", 200)),
                }
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code in (401, 403):
                raise ResearchError(
                    f"Access denied ({error.code}) at {url}. "
                    "A legitimate browser login or interface update may be required."
                ) from error
            if error.code == 429:
                retry_after = safe_int(error.headers.get("Retry-After"), 0)
                delay = max(retry_after, min(30, 1.0 * (2**attempt)))
            elif 400 <= error.code < 500:
                raise ResearchError(f"HTTP {error.code} at {url}") from error
            else:
                delay = min(30, 1.0 * (2**attempt))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
            delay = min(30, 1.0 * (2**attempt))
        if attempt + 1 < attempts:
            time.sleep(delay + random.random() * 0.25)
    raise ResearchError(f"Request failed after {attempts} attempts: {url}: {last_error}")


def request_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    attempts: int = 4,
) -> Dict[str, Any]:
    body, metadata = request_bytes(url, params=params, attempts=attempts)
    content_type = metadata.get("content_type", "").lower()
    prefix = body.lstrip()[:80].lower()
    if "html" in content_type or prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html"):
        raise ResearchError(
            f"Expected JSON but received HTML from {url}. "
            "The endpoint may now require login or its interface may have changed."
        )
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResearchError(f"Invalid JSON response from {url}: {error}") from error
    if not isinstance(payload, dict):
        raise ResearchError(f"Unexpected non-object JSON response from {url}.")
    return payload


def list_feed_id(feed: Dict[str, Any]) -> str:
    common = feed.get("feed_comm") or feed.get("feedCommon") or {}
    return str(common.get("feed_id") or common.get("feedId") or "")


def list_timestamp(feed: Dict[str, Any]) -> int:
    common = feed.get("feed_comm") or feed.get("feedCommon") or {}
    return safe_int(common.get("timestamp"), 0)


def validate_list_payload(payload: Dict[str, Any]) -> None:
    if safe_int(payload.get("result"), -999) not in (0, -13):
        raise ResearchError(
            f"Futu list interface returned result={payload.get('result')!r}; "
            "the interface may have changed."
        )
    if "feed" not in payload or not isinstance(payload.get("feed"), list):
        raise ResearchError(
            "Futu list response has no feed list. This is interface drift, not an empty profile."
        )


def validate_detail_payload(payload: Dict[str, Any]) -> None:
    if safe_int(payload.get("code"), -999) != 0:
        raise ResearchError(
            f"Futu detail interface returned code={payload.get('code')!r}: "
            f"{payload.get('message') or payload.get('msg') or 'unknown error'}"
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ResearchError("Futu detail response has no data object.")


def page_signature(payload: Dict[str, Any]) -> str:
    ids = [list_feed_id(item) for item in (payload.get("feed") or [])]
    cursor = [payload.get("more_mark"), payload.get("sequence"), payload.get("has_more")]
    return hashlib.sha256(
        json.dumps([ids, cursor], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def crawl_stream(
    uid: str,
    feed_type: int,
    output: Path,
    since_dt: Optional[datetime],
    refresh: bool,
    max_pages: int,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    label = STREAMS[feed_type]
    stream_dir = output / "raw" / "list" / uid / label
    stream_dir.mkdir(parents=True, exist_ok=True)
    page = 0
    more_mark = ""
    sequence = ""
    seen_signatures = set()
    feeds: Dict[str, Dict[str, Any]] = {}
    metadata: List[Dict[str, Any]] = []
    older_streak = 0
    terminal_reason = "error"
    errors: List[str] = []

    while page < max_pages:
        page += 1
        path = stream_dir / f"page_{page:05d}.json"
        source = "network"
        payload = None
        if path.exists() and not refresh:
            payload = read_json(path)
            source = "cache"
        params: Dict[str, Any] = {
            "type": feed_type,
            "num": 10,
            "load_list_type": 2 if page == 1 else 1,
            "target_uid": uid,
        }
        if more_mark:
            params["more_mark"] = more_mark
        if sequence:
            params["sequence"] = sequence
        try:
            if not isinstance(payload, dict):
                payload = request_json(LIST_URL, params)
                atomic_write_json(path, payload)
            validate_list_payload(payload)
        except ResearchError as error:
            errors.append(str(error))
            terminal_reason = "error"
            break

        signature = page_signature(payload)
        if signature in seen_signatures:
            terminal_reason = "cursor_loop"
            errors.append(f"Repeated page/cursor signature at page {page}.")
            break
        seen_signatures.add(signature)

        page_feeds = payload.get("feed") or []
        timestamps = [list_timestamp(item) for item in page_feeds if list_timestamp(item)]
        new_ids = 0
        for feed in page_feeds:
            feed_id = list_feed_id(feed)
            if not feed_id:
                continue
            if feed_id not in feeds:
                new_ids += 1
            feeds[feed_id] = feed
        has_more = bool(safe_int(payload.get("has_more"), 0))
        metadata.append(
            {
                "page": page,
                "source": source,
                "rows": len(page_feeds),
                "new_ids": new_ids,
                "newest_epoch": max(timestamps) if timestamps else None,
                "oldest_epoch": min(timestamps) if timestamps else None,
                "has_more": has_more,
                "more_mark": str(payload.get("more_mark") or ""),
                "sequence": str(payload.get("sequence") or ""),
                "sha256": hashlib.sha256(
                    path.read_bytes() if path.exists() else b""
                ).hexdigest(),
            }
        )
        log(
            f"[{uid}/{label}] page={page} rows={len(page_feeds)} "
            f"unique={len(feeds)} source={source}"
        )

        if not has_more:
            terminal_reason = "has_more_zero"
            break
        if not page_feeds:
            terminal_reason = "empty_page_with_has_more"
            errors.append("The interface returned an empty page while has_more was true.")
            break

        if since_dt and timestamps and max(timestamps) < int(since_dt.timestamp()):
            older_streak += 1
        else:
            older_streak = 0
        if since_dt and older_streak >= 2:
            terminal_reason = "since_boundary"
            break

        next_more = str(payload.get("more_mark") or "")
        next_sequence = str(payload.get("sequence") or sequence)
        if not next_more and not next_sequence:
            terminal_reason = "missing_cursor"
            errors.append("has_more was true but no continuation cursor was returned.")
            break
        more_mark = next_more
        sequence = next_sequence
        if source == "network":
            time.sleep(0.18 + random.random() * 0.08)
    else:
        terminal_reason = "max_pages"
        errors.append(f"Stopped at safety limit max_pages={max_pages}.")

    complete = terminal_reason == "has_more_zero" or (
        since_dt is not None and terminal_reason == "since_boundary"
    )
    audit = {
        "profile_uid": uid,
        "stream": label,
        "feed_type": feed_type,
        "pages_saved": len(metadata),
        "unique_feed_ids": len(feeds),
        "terminal_reason": terminal_reason,
        "complete_for_request": complete,
        "pages": metadata,
        "errors": errors,
    }
    return feeds, audit


def detail_data(envelope: Dict[str, Any]) -> Dict[str, Any]:
    outer = envelope.get("data") or {}
    nested = outer.get("data") if isinstance(outer, dict) else None
    if isinstance(nested, dict):
        return nested
    return outer if isinstance(outer, dict) else {}


def fetch_details(
    uid: str,
    feed_ids: Sequence[str],
    output: Path,
    workers: int,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    detail_dir = output / "raw" / "details" / uid
    detail_dir.mkdir(parents=True, exist_ok=True)

    def fetch_one(feed_id: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        path = detail_dir / f"{feed_id}.json"
        cached = read_json(path)
        if isinstance(cached, dict):
            try:
                validate_detail_payload(cached)
                return feed_id, None
            except ResearchError:
                pass
        try:
            payload = request_json(
                DETAIL_URL,
                {
                    "feedId": feed_id,
                    "targetLang": 0,
                    "translateType": 1,
                    "lang": "zh-cn",
                },
            )
            validate_detail_payload(payload)
            atomic_write_json(path, payload)
            time.sleep(0.04 + random.random() * 0.04)
            return feed_id, None
        except Exception as error:  # failure is recorded and audited
            return None, {"uid": uid, "feed_id": feed_id, "error": str(error)}

    successes: List[str] = []
    failures: List[Dict[str, Any]] = []
    ordered = sorted(set(feed_ids))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as pool:
        for index, result in enumerate(pool.map(fetch_one, ordered), start=1):
            success, failure = result
            if success:
                successes.append(success)
            if failure:
                failures.append(failure)
            if index % 50 == 0 or index == len(ordered):
                log(
                    f"[{uid}/details] {index}/{len(ordered)} "
                    f"ok={len(successes)} failed={len(failures)}"
                )
    return successes, failures


def recursively_collect_text(value: Any) -> List[str]:
    parts: List[str] = []
    if isinstance(value, list):
        for item in value:
            parts.extend(recursively_collect_text(item))
    elif isinstance(value, dict):
        direct = value.get("text")
        rich = value.get("richText")
        if isinstance(direct, str):
            parts.append(direct)
        elif isinstance(rich, str):
            parts.append(rich)
        else:
            for key, child in value.items():
                if key.lower() not in {
                    "attrs",
                    "stockinfo",
                    "stock_info",
                    "stocknamemultilang",
                }:
                    parts.extend(recursively_collect_text(child))
    return parts


def clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\u200b", "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def module_text(modules: Any) -> str:
    paragraphs: List[str] = []
    for module in modules if isinstance(modules, list) else []:
        chunks = recursively_collect_text(
            module.get("data", module) if isinstance(module, dict) else module
        )
        paragraph = clean_text("".join(chunks))
        if paragraph:
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs).strip()


def canonical_symbol(code: str, market: Optional[str] = None) -> Optional[Dict[str, Any]]:
    raw_code = str(code or "").strip().upper().strip("$")
    raw_market = str(market or "").strip().upper()
    if not raw_code or len(raw_code) > 24:
        return None
    prefix_match = re.fullmatch(r"(US|HK|SH|SZ)\.([A-Z0-9.-]+)", raw_code)
    suffix_match = re.fullmatch(r"([A-Z0-9.-]+)\.(US|HK|SH|SZ)", raw_code)
    if prefix_match:
        raw_market, raw_code = prefix_match.groups()
    elif suffix_match:
        raw_code, raw_market = suffix_match.groups()
    if raw_market not in {"US", "HK", "SH", "SZ"}:
        raw_market = ""
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,20}", raw_code):
        return None
    canonical = f"{raw_market}.{raw_code}" if raw_market else raw_code
    return {"raw": canonical, "code": raw_code, "market": raw_market or None, "name": None}


def recursively_collect_symbols(value: Any) -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    if isinstance(value, list):
        for item in value:
            for symbol in recursively_collect_symbols(item):
                found[symbol["raw"]] = symbol
    elif isinstance(value, dict):
        market = (
            value.get("market")
            or value.get("marketCode")
            or value.get("market_code")
            or value.get("stockMarket")
        )
        name = (
            value.get("stockName")
            or value.get("name")
            or value.get("stock_name")
        )
        for key in ("stockCode", "stock_code", "stockSymbol", "displaySymbol", "symbol"):
            if isinstance(value.get(key), str):
                symbol = canonical_symbol(value[key], market)
                if symbol:
                    if isinstance(name, str) and name.strip():
                        symbol["name"] = name.strip()
                    found[symbol["raw"]] = symbol
        for child in value.values():
            for symbol in recursively_collect_symbols(child):
                found[symbol["raw"]] = symbol
    return sorted(found.values(), key=lambda item: item["raw"])


def inferred_symbols(text: str) -> List[Dict[str, Any]]:
    values = set()
    for pattern in (
        r"\$([A-Za-z]{1,8}(?:\.[A-Za-z]{1,4})?)\$",
        r"(?<![A-Za-z0-9])((?:US|HK|SH|SZ)\.[A-Za-z0-9.-]{1,16})(?![A-Za-z0-9])",
    ):
        for candidate in re.findall(pattern, text):
            values.add(candidate.upper())
    for candidate in re.findall(
        r"(?<![A-Za-z0-9])([A-Z][A-Z0-9.-]{1,7})(?![A-Za-z0-9])", text
    ):
        cleaned = candidate.strip(".-")
        if cleaned and cleaned not in SYMBOL_STOPLIST and not re.fullmatch(r"[A-Z]\d+", cleaned):
            values.add(cleaned)
    result = []
    for value in sorted(values):
        symbol = canonical_symbol(value)
        if symbol:
            result.append(symbol)
    return result


def topic_names(detail: Dict[str, Any]) -> List[str]:
    result = set()
    for item in detail.get("topicItems") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("topicName") or item.get("name")
        if isinstance(value, str) and value.strip():
            result.add(value.strip())
    return sorted(result)


def like_count(detail: Dict[str, Any]) -> int:
    total = 0
    for item in ((detail.get("like") or {}).get("likeEmotionInfo") or []):
        if isinstance(item, dict):
            total += safe_int(item.get("emoticonNum"), 0)
    return total


def extract_media_urls(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    found: Dict[str, Dict[str, str]] = {}

    def visit(value: Any, parent_key: str = "") -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, parent_key)
        elif isinstance(value, dict):
            for key, child in value.items():
                normalized = key.lower().replace("-", "").replace(" ", "")
                if isinstance(child, str) and child.startswith(("https://", "http://")):
                    if normalized in URL_MEDIA_KEYS or (
                        parent_key.lower() in {"image", "images", "pic", "pics"}
                        and re.search(r"\.(?:jpe?g|png|webp|gif)(?:[?#]|$)", child, re.I)
                    ):
                        if "spacer.gif" not in child:
                            found[child] = {"url": child, "source_field": key}
                else:
                    visit(child, key)

    visit(detail.get("moduleData") or [])
    return list(found.values())


def extension_for(url: str, content_type: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in mapping:
        return mapping[mime]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ".bin"


def download_media(
    uid: str,
    detail_paths: Sequence[Path],
    output: Path,
    workers: int,
) -> List[Dict[str, Any]]:
    jobs: List[Tuple[str, int, Dict[str, str]]] = []
    for path in detail_paths:
        envelope = read_json(path, {})
        detail = detail_data(envelope)
        feed_id = str((detail.get("feedCommon") or {}).get("feedId") or path.stem)
        for index, item in enumerate(extract_media_urls(detail), start=1):
            jobs.append((feed_id, index, item))

    def fetch_one(job: Tuple[str, int, Dict[str, str]]) -> Dict[str, Any]:
        feed_id, index, item = job
        base = output / "media" / uid / feed_id
        existing = sorted(base.glob(f"{index:03d}.*")) if base.exists() else []
        for path in existing:
            if path.suffix != ".part" and path.stat().st_size > 0:
                return {
                    "uid": uid,
                    "feed_id": feed_id,
                    "index": index,
                    "status": "ok",
                    "source": "cache",
                    "url": item["url"],
                    "source_field": item["source_field"],
                    "path": str(path.relative_to(output)),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
        try:
            body, metadata = request_bytes(item["url"], attempts=4)
            content_type = metadata.get("content_type", "")
            if not content_type.lower().startswith("image/"):
                raise ResearchError(f"non-image content type {content_type!r}")
            extension = extension_for(item["url"], content_type)
            path = base / f"{index:03d}{extension}"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".part")
            temporary.write_bytes(body)
            os.replace(temporary, path)
            return {
                "uid": uid,
                "feed_id": feed_id,
                "index": index,
                "status": "ok",
                "source": "network",
                "url": item["url"],
                "source_field": item["source_field"],
                "path": str(path.relative_to(output)),
                "content_type": content_type,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        except Exception as error:
            return {
                "uid": uid,
                "feed_id": feed_id,
                "index": index,
                "status": "failed",
                "url": item["url"],
                "source_field": item["source_field"],
                "error": str(error),
            }

    items: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 6))) as pool:
        for index, result in enumerate(pool.map(fetch_one, jobs), start=1):
            items.append(result)
            if index % 50 == 0 or index == len(jobs):
                failures = sum(item["status"] != "ok" for item in items)
                log(f"[{uid}/media] {index}/{len(jobs)} failed={failures}")
    return items


def normalize_detail(
    path: Path,
    uid: str,
    stream_membership: Sequence[str],
    media_by_feed: Dict[str, List[Dict[str, Any]]],
    profile_url: str,
) -> Dict[str, Any]:
    envelope = read_json(path)
    if not isinstance(envelope, dict):
        raise ResearchError(f"Cannot parse detail file {path}")
    validate_detail_payload(envelope)
    detail = detail_data(envelope)
    common = detail.get("feedCommon") or {}
    timestamp = safe_int(common.get("timestamp"), 0)
    published = (
        datetime.fromtimestamp(timestamp, CN_TZ).isoformat(timespec="seconds")
        if timestamp
        else None
    )
    author = detail.get("authorInfo") or {}
    author_uid = str(author.get("userId") or "")
    feed_id = str(common.get("feedId") or path.stem)
    title = clean_text(str(detail.get("feedTitle") or ""))
    text = module_text(detail.get("moduleData") or [])
    tagged = recursively_collect_symbols(detail.get("moduleData") or [])
    tagged_values = {item["raw"] for item in tagged}
    inferred = [
        item for item in inferred_symbols(f"{title}\n{text}") if item["raw"] not in tagged_values
    ]
    counts = detail.get("count") or {}
    feed_type = safe_int(common.get("feedType"), 0)
    action = (common.get("dynamicDescription") or {})
    if isinstance(action, dict):
        profile_action = (
            action.get("stringSc")
            or action.get("stringTc")
            or action.get("stringEn")
            or ""
        )
    else:
        profile_action = str(action or "")
    media_items = sorted(
        media_by_feed.get(feed_id, []), key=lambda item: safe_int(item.get("index"), 0)
    )
    original = author_uid == uid if author_uid else not bool(profile_action)
    warnings = []
    if not timestamp:
        warnings.append("timestamp_parse_error")
    if not text and not title:
        warnings.append("empty_extractable_text")
    return {
        "schema_version": SCHEMA_VERSION,
        "feed_id": feed_id,
        "author_uid": author_uid or uid,
        "profile_uid": uid,
        "author_name": str(author.get("nickName") or "") or None,
        "published_at": published,
        "published_at_raw": common.get("timestamp"),
        "date": published[:10] if published else None,
        "month": published[:7] if published else "unknown",
        "stream_membership": sorted(set(stream_membership)),
        "is_column": "columns" in stream_membership or feed_type == 4,
        "is_repost": not original,
        "is_original_author": original,
        "feed_type": feed_type,
        "content_type": TYPE_LABELS.get(feed_type, "其他动态"),
        "profile_action": profile_action,
        "title": title,
        "text": text,
        "symbols": tagged,
        "inferred_symbols": inferred,
        "topics": topic_names(detail),
        "metrics": {
            "comments": safe_int(counts.get("comment"), 0),
            "likes": like_count(detail),
            "reposts": safe_int(counts.get("share"), 0),
            "views": safe_int(counts.get("browse"), 0),
        },
        "images": [
            {
                "url": item.get("url"),
                "source_field": item.get("source_field"),
                "local_path": item.get("path") if item.get("status") == "ok" else None,
                "status": item.get("status"),
            }
            for item in media_items
        ],
        "url": f"https://q.futunn.com/feed/{feed_id}?lang=zh-cn",
        "source": {
            "detail_path": str(path),
            "profile_url": profile_url,
        },
        "parse_warnings": warnings,
    }


def within_requested_range(
    timestamp: int,
    since_dt: Optional[datetime],
    until_dt: Optional[datetime],
) -> bool:
    if not timestamp:
        return True
    if since_dt and timestamp < int(since_dt.timestamp()):
        return False
    if until_dt and timestamp > int(until_dt.timestamp()):
        return False
    return True


def write_archive_files(output: Path, records: Sequence[Dict[str, Any]]) -> None:
    archive = output / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        records,
        key=lambda row: (row.get("published_at") or "", row.get("feed_id") or ""),
        reverse=True,
    )
    write_jsonl(archive / "posts.jsonl", ordered)
    fields = [
        "feed_id",
        "profile_uid",
        "author_uid",
        "author_name",
        "published_at",
        "stream_membership",
        "is_column",
        "is_repost",
        "content_type",
        "profile_action",
        "title",
        "tagged_symbols",
        "inferred_symbols",
        "topics",
        "views",
        "comments",
        "reposts",
        "likes",
        "image_count",
        "url",
        "text",
        "detail_path",
    ]
    csv_path = archive / "posts.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = csv_path.with_name(csv_path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in ordered:
            metrics = row.get("metrics") or {}
            writer.writerow(
                {
                    "feed_id": row.get("feed_id"),
                    "profile_uid": row.get("profile_uid"),
                    "author_uid": row.get("author_uid"),
                    "author_name": row.get("author_name"),
                    "published_at": row.get("published_at"),
                    "stream_membership": " | ".join(row.get("stream_membership") or []),
                    "is_column": row.get("is_column"),
                    "is_repost": row.get("is_repost"),
                    "content_type": row.get("content_type"),
                    "profile_action": row.get("profile_action"),
                    "title": row.get("title"),
                    "tagged_symbols": " | ".join(
                        item.get("raw", "") for item in (row.get("symbols") or [])
                    ),
                    "inferred_symbols": " | ".join(
                        item.get("raw", "") for item in (row.get("inferred_symbols") or [])
                    ),
                    "topics": " | ".join(row.get("topics") or []),
                    "views": metrics.get("views", 0),
                    "comments": metrics.get("comments", 0),
                    "reposts": metrics.get("reposts", 0),
                    "likes": metrics.get("likes", 0),
                    "image_count": len(row.get("images") or []),
                    "url": row.get("url"),
                    "text": row.get("text"),
                    "detail_path": (row.get("source") or {}).get("detail_path"),
                }
            )
    os.replace(temporary, csv_path)

    monthly_dir = archive / "monthly"
    monthly_dir.mkdir(parents=True, exist_ok=True)
    for old in monthly_dir.glob("*.md"):
        old.unlink()
    by_month: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        by_month[str(row.get("month") or "unknown")].append(row)
    for month, rows in sorted(by_month.items()):
        lines = [
            f"# 富途公开内容归档 · {month}",
            "",
            f"> {len(rows)} 条。原创与转发均保存；是否原创见每条标记。",
            "",
        ]
        for row in rows:
            headline = row.get("title") or (row.get("text") or "（无正文）")[:50]
            symbols = [item.get("raw") for item in (row.get("symbols") or [])]
            lines.extend(
                [
                    f"## {row.get('published_at') or '时间未知'} · {headline}",
                    "",
                    (
                        f"- 主页 UID：{row.get('profile_uid')}；作者："
                        f"{row.get('author_name') or row.get('author_uid') or '未知'}；"
                        f"原创：{'否' if row.get('is_repost') else '是'}；"
                        f"专栏：{'是' if row.get('is_column') else '否'}"
                    ),
                    f"- 标的标签：{', '.join(symbols) if symbols else '—'}；[原帖]({row.get('url')})",
                    "",
                    row.get("text") or "（无可提取正文；原始详情 JSON 已保留）",
                    "",
                    "---",
                    "",
                ]
            )
        atomic_write_text(monthly_dir / f"{month}.md", "\n".join(lines))


def archive(args: argparse.Namespace) -> Dict[str, Any]:
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    since_dt = parse_day(args.since)
    until_dt = parse_day(args.until, end=True)
    if since_dt and until_dt and since_dt > until_dt:
        raise ResearchError("--since must be on or before --until.")
    uids = []
    for profile in args.profile:
        uid = parse_uid(profile)
        if uid not in uids:
            uids.append(uid)
    if not uids:
        raise ResearchError("At least one --profile is required.")

    previous_index = read_json(output / "raw" / "feed_index.json", {})
    if not isinstance(previous_index, dict):
        previous_index = {}
    index: Dict[str, Dict[str, Any]] = previous_index
    stream_audits: List[Dict[str, Any]] = []
    detail_failures: List[Dict[str, Any]] = []
    media_items: List[Dict[str, Any]] = []
    profiles: Dict[str, Dict[str, Any]] = {}

    for uid in uids:
        profile_url = f"https://q.futunn.com/profile/{uid}"
        profiles[uid] = {"uid": uid, "profile_url": profile_url}
        combined: Dict[str, Dict[str, Any]] = {}
        memberships: Dict[str, set] = defaultdict(set)
        for feed_type, label in STREAMS.items():
            feeds, audit_row = crawl_stream(
                uid,
                feed_type,
                output,
                since_dt,
                args.refresh,
                args.max_pages,
            )
            stream_audits.append(audit_row)
            for feed_id, feed in feeds.items():
                combined.setdefault(feed_id, feed)
                memberships[feed_id].add(label)

        retained = []
        for feed_id, feed in combined.items():
            if within_requested_range(list_timestamp(feed), since_dt, until_dt):
                retained.append(feed_id)
                key = f"{uid}:{feed_id}"
                existing = index.get(key) if isinstance(index.get(key), dict) else {}
                existing_memberships = set(existing.get("stream_membership") or [])
                index[key] = {
                    "uid": uid,
                    "feed_id": feed_id,
                    "timestamp": list_timestamp(feed),
                    "stream_membership": sorted(existing_memberships | memberships[feed_id]),
                    "profile_url": profile_url,
                }
        successes, failures = fetch_details(
            uid, retained, output, workers=args.detail_workers
        )
        detail_failures.extend(failures)
        detail_paths = [
            output / "raw" / "details" / uid / f"{feed_id}.json"
            for feed_id in successes
        ]
        if not args.skip_media:
            media_items.extend(
                download_media(uid, detail_paths, output, workers=args.media_workers)
            )

    atomic_write_json(output / "raw" / "feed_index.json", index)
    media_manifest_path = output / "raw" / "media_manifest.json"
    previous_media = read_json(media_manifest_path, {})
    previous_items = previous_media.get("items") if isinstance(previous_media, dict) else []
    media_by_key: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for item in list(previous_items or []) + media_items:
        key = (
            str(item.get("uid") or ""),
            str(item.get("feed_id") or ""),
            safe_int(item.get("index"), 0),
        )
        if key[0] and key[1] and key[2]:
            current = media_by_key.get(key)
            if not current or item.get("status") == "ok":
                media_by_key[key] = item
    atomic_write_json(
        media_manifest_path,
        {"schema_version": SCHEMA_VERSION, "items": list(media_by_key.values())},
    )

    media_lookup: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for item in media_by_key.values():
        media_lookup[(str(item["uid"]), str(item["feed_id"]))].append(item)

    records: List[Dict[str, Any]] = []
    normalization_failures = []
    for key, item in sorted(index.items()):
        uid = str(item.get("uid") or "")
        feed_id = str(item.get("feed_id") or "")
        if not uid or not feed_id:
            continue
        if uids and uid not in uids and not (output / "raw" / "details" / uid).exists():
            continue
        path = output / "raw" / "details" / uid / f"{feed_id}.json"
        if not path.exists():
            continue
        if not within_requested_range(safe_int(item.get("timestamp"), 0), since_dt, until_dt):
            continue
        try:
            records.append(
                normalize_detail(
                    path,
                    uid,
                    item.get("stream_membership") or [],
                    {
                        feed_id: media_lookup.get((uid, feed_id), [])
                    },
                    str(item.get("profile_url") or f"https://q.futunn.com/profile/{uid}"),
                )
            )
        except Exception as error:
            normalization_failures.append(
                {"uid": uid, "feed_id": feed_id, "error": str(error)}
            )
    write_archive_files(output, records)

    all_history = since_dt is None
    complete_streams = all(row["complete_for_request"] for row in stream_audits)
    detail_expected = sum(
        1
        for item in index.values()
        if str(item.get("uid") or "") in uids
        and within_requested_range(
            safe_int(item.get("timestamp"), 0), since_dt, until_dt
        )
    )
    detail_success_count = detail_expected - len(detail_failures)
    media_failures = [item for item in media_by_key.values() if item.get("status") != "ok"]
    if complete_streams and not detail_failures and not normalization_failures:
        status = "PASS" if not media_failures or args.skip_media else "WARN"
    else:
        status = "FAIL"
    visible_status = (
        "complete_visible_history"
        if all_history and all(row["terminal_reason"] == "has_more_zero" for row in stream_audits)
        else "complete_requested_window"
        if complete_streams
        else "incomplete"
    )
    crawl_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "visible_history_status": visible_status,
        "captured_at": now_iso(),
        "requested_since": args.since,
        "requested_until": args.until,
        "profiles": list(profiles.values()),
        "streams": stream_audits,
        "detail_expected": detail_expected,
        "detail_successes": detail_success_count,
        "detail_failures": detail_failures,
        "normalization_failures": normalization_failures,
        "normalized_records": len(records),
        "media_objects": len(media_by_key),
        "media_failures": media_failures,
        "notes": [
            "Both dynamics/all and columns streams are captured and unioned by feed_id.",
            "All history means all content still returned publicly at capture time.",
            "Deleted, private, restricted, or otherwise unavailable content is outside the archive boundary.",
        ],
    }
    atomic_write_json(output / "qa" / "crawl_audit.json", crawl_audit)
    manifest = {
        "tool": "elab-futu-research",
        "tool_version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_iso(),
        "output_root": str(output),
        "profiles": list(profiles.values()),
        "options": {
            "since": args.since,
            "until": args.until,
            "skip_media": args.skip_media,
        },
        "counts": {
            "posts": len(records),
            "columns": sum(bool(row.get("is_column")) for row in records),
            "reposts": sum(bool(row.get("is_repost")) for row in records),
            "media": len(media_by_key),
        },
        "crawl_audit": "qa/crawl_audit.json",
    }
    atomic_write_json(output / "manifest.json", manifest)
    log(
        f"Archive {status}: posts={len(records)} columns="
        f"{manifest['counts']['columns']} output={output}"
    )
    return crawl_audit


def contains_any(text: str, values: Sequence[str]) -> List[str]:
    lowered = text.lower()
    return [value for value in values if value.lower() in lowered]


def detect_action(text: str) -> Tuple[str, List[str]]:
    for action, keywords in ACTION_KEYWORDS.items():
        hits = contains_any(text, keywords)
        if hits:
            return action, hits
    return "none", []


def detect_direction(text: str, action: str) -> Tuple[str, List[str]]:
    bullish = contains_any(text, BULLISH_KEYWORDS)
    bearish = contains_any(text, BEARISH_KEYWORDS)
    if action in {"buy", "add", "hold"}:
        bullish.append(f"action:{action}")
    if action == "short":
        bearish.append(f"action:{action}")
    if bullish and bearish:
        return "mixed", bullish + bearish
    if bullish:
        return "bullish", bullish
    if bearish:
        return "bearish", bearish
    return "unclear", []


def evidence_span(text: str, hits: Sequence[str], limit: int = 280) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    positions = [
        compact.lower().find(hit.lower())
        for hit in hits
        if compact.lower().find(hit.lower()) >= 0
    ]
    center = min(positions) if positions else 0
    start = max(0, center - 80)
    return compact[start : start + limit]


def tone_prelabels(text: str) -> Dict[str, Any]:
    risk = contains_any(text, RISK_KEYWORDS)
    conditional = contains_any(text, CONDITION_KEYWORDS)
    certainty = contains_any(text, CERTAINTY_KEYWORDS)
    urgency = contains_any(text, URGENCY_KEYWORDS)
    positive = len(contains_any(text, BULLISH_KEYWORDS))
    negative = len(contains_any(text, BEARISH_KEYWORDS))
    valence = 0
    if positive > negative:
        valence = 1
    elif negative > positive:
        valence = -1
    exclamations = min(4, text.count("!") + text.count("！"))
    return {
        "valence_prelabel": valence,
        "arousal_prelabel": min(4, exclamations),
        "certainty_hits": certainty,
        "urgency_hits": urgency,
        "conditionality_hits": conditional,
        "risk_awareness_hits": risk,
    }


def prepare(args: argparse.Namespace) -> Dict[str, Any]:
    output = Path(args.output).expanduser().resolve()
    posts_path = output / "archive" / "posts.jsonl"
    posts = read_jsonl(posts_path)
    if not posts:
        raise ResearchError(f"No normalized posts found at {posts_path}. Run archive first.")
    candidates = []
    for row in posts:
        text = "\n".join(
            part for part in [str(row.get("title") or ""), str(row.get("text") or "")] if part
        )
        action, action_hits = detect_action(text)
        direction, direction_hits = detect_direction(text, action)
        first_person_hits = contains_any(text, FIRST_PERSON)
        if action in {"buy", "add", "hold", "reduce", "sell", "short", "cover"} and first_person_hits:
            evidence = "B"
        elif direction in {"bullish", "bearish", "mixed"}:
            evidence = "C"
        else:
            evidence = "D"
        symbols = list(row.get("symbols") or [])
        symbol_source = "tagged"
        if not symbols:
            symbols = list(row.get("inferred_symbols") or [])
            symbol_source = "inferred"
        if not symbols:
            symbols = [{"raw": None, "code": None, "market": None, "name": None}]
            symbol_source = "none"
        all_hits = action_hits + direction_hits + first_person_hits
        for symbol in symbols:
            raw_symbol = symbol.get("raw") if isinstance(symbol, dict) else str(symbol)
            candidate_id = f"{row.get('feed_id')}:{raw_symbol or 'GENERAL'}"
            candidates.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "candidate_id": candidate_id,
                    "feed_id": str(row.get("feed_id") or ""),
                    "author_uid": str(row.get("profile_uid") or row.get("author_uid") or ""),
                    "author_name": row.get("author_name"),
                    "published_at": row.get("published_at"),
                    "symbol_raw": raw_symbol,
                    "symbol_source": symbol_source,
                    "direction_prelabel": direction,
                    "action_prelabel": action,
                    "evidence_prelabel": evidence,
                    "evidence_span": evidence_span(text, all_hits),
                    "keyword_hits": sorted(set(all_hits)),
                    "tone_prelabels": tone_prelabels(text),
                    "is_repost": bool(row.get("is_repost")),
                    "ability_eligible_prelabel": (
                        not row.get("is_repost")
                        and evidence in {"B", "C"}
                        and raw_symbol is not None
                    ),
                    "needs_symbol_verification": symbol_source == "inferred",
                    "needs_human_review": True,
                    "source_post_path": "archive/posts.jsonl",
                    "source_url": row.get("url"),
                }
            )
    analysis = output / "analysis"
    write_jsonl(analysis / "candidates.jsonl", candidates)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": "machine_prelabelled_exploratory",
        "posts": len(posts),
        "candidates": len(candidates),
        "by_evidence_prelabel": dict(Counter(row["evidence_prelabel"] for row in candidates)),
        "ability_eligible_prelabels": sum(
            bool(row["ability_eligible_prelabel"]) for row in candidates
        ),
        "warnings": [
            "These are deterministic candidates, not reviewed claims.",
            "The script never assigns evidence level A.",
            "Inferred symbols and all holding/action claims require source review.",
        ],
    }
    atomic_write_json(analysis / "prepare_summary.json", summary)
    if not (analysis / "claims.reviewed.jsonl").exists():
        atomic_write_text(analysis / "claims.reviewed.jsonl", "")
    review_guide = "\n".join(
        [
            "# 观点复核工作台",
            "",
            "先复核并冻结观点，完成前不要查看未来收益文件。",
            "",
            "1. 逐条读取 `candidates.jsonl` 指向的原帖和图片。",
            "2. 修正标的、方向、动作、期限、条件、失效、仓位、风险和退出。",
            "3. 按 A/B/C/D 分级；A 必须实际检查图片或一手记录，C/D 不能推断持仓。",
            "4. 把结果按 `references/data-schema.md` 的 Reviewed claim 结构写入 `claims.reviewed.jsonl`。",
            "5. 不确定就保留 `ambiguities` 并降低 confidence，不要猜。",
            "6. 冻结完成后再运行 `market`、`report` 和 `audit`。",
            "",
            "发布比较结论前，还要复核 `episodes.jsonl` 的事件边界和更新标签，并寻找反例。",
            "",
        ]
    )
    atomic_write_text(analysis / "review_guide.md", review_guide)
    log(
        f"Prepared {len(candidates)} candidates from {len(posts)} posts "
        "(exploratory; review required)."
    )
    return summary


def yahoo_symbol(raw: Optional[str], overrides: Dict[str, str]) -> Optional[str]:
    if not raw:
        return None
    value = str(raw).strip().upper()
    if value in overrides:
        return overrides[value] or None
    match = re.fullmatch(r"(US|HK|SH|SZ)\.([A-Z0-9.-]+)", value)
    if match:
        market, code = match.groups()
        if market == "US":
            return code.replace(".", "-")
        if market == "HK":
            normalized = (code.lstrip("0") or "0").zfill(4)
            return f"{normalized}.HK"
        if market == "SH":
            return f"{code}.SS"
        if market == "SZ":
            return f"{code}.SZ"
    suffix = re.fullmatch(r"([A-Z0-9.-]+)\.(US|HK|SH|SZ)", value)
    if suffix:
        return yahoo_symbol(f"{suffix.group(2)}.{suffix.group(1)}", overrides)
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,7}", value):
        return value.replace(".", "-")
    return None


def benchmark_for(raw: Optional[str]) -> Optional[str]:
    value = str(raw or "").upper()
    if value.startswith("HK."):
        return "^HSI"
    if value.startswith(("SH.", "SZ.")):
        return "000001.SS"
    if value:
        return "^GSPC"
    return None


def parse_claim_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value)
    with contextlib.suppress(ValueError):
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=CN_TZ)
        return parsed
    return None


def load_price_bars(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    chart = payload.get("chart") or {}
    result = chart.get("result") or []
    if not result or not isinstance(result[0], dict):
        return []
    item = result[0]
    timestamps = item.get("timestamp") or []
    quotes = ((item.get("indicators") or {}).get("quote") or [{}])[0]
    adjusted_values = (
        ((item.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
        or []
    )
    bars = []
    for index, stamp in enumerate(timestamps):
        try:
            raw_close = safe_float((quotes.get("close") or [])[index])
            adjusted_close = (
                safe_float(adjusted_values[index])
                if index < len(adjusted_values)
                else None
            )
            adjustment = (
                adjusted_close / raw_close
                if adjusted_close is not None and raw_close not in (None, 0)
                else 1.0
            )
            raw_open = safe_float((quotes.get("open") or [])[index])
            raw_high = safe_float((quotes.get("high") or [])[index])
            raw_low = safe_float((quotes.get("low") or [])[index])
            row = {
                "date": datetime.fromtimestamp(int(stamp), UTC).date().isoformat(),
                "timestamp": int(stamp),
                "open": raw_open * adjustment if raw_open is not None else None,
                "high": raw_high * adjustment if raw_high is not None else None,
                "low": raw_low * adjustment if raw_low is not None else None,
                "close": adjusted_close if adjusted_close is not None else raw_close,
                "volume": safe_float((quotes.get("volume") or [])[index]),
            }
        except (IndexError, TypeError, ValueError):
            continue
        if row["open"] is not None and row["close"] is not None:
            bars.append(row)
    unique = {bar["date"]: bar for bar in bars}
    return [unique[key] for key in sorted(unique)]


def fetch_yahoo_history(
    symbol: str,
    start: datetime,
    end: datetime,
    cache_path: Path,
    refresh: bool,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    payload = None if refresh else read_json(cache_path)
    if not isinstance(payload, dict):
        try:
            payload = request_json(
                YAHOO_URL.format(symbol=urllib.parse.quote(symbol, safe="^.-")),
                {
                    "period1": int(start.timestamp()),
                    "period2": int(end.timestamp()),
                    "interval": "1d",
                    "events": "history",
                },
            )
            atomic_write_json(cache_path, payload)
            time.sleep(0.12 + random.random() * 0.08)
        except Exception as error:
            return [], str(error)
    error_value = (payload.get("chart") or {}).get("error")
    if error_value:
        return [], json.dumps(error_value, ensure_ascii=False)
    bars = load_price_bars(payload)
    if not bars:
        return [], "no usable daily bars returned"
    return bars, None


def safe_market_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "unknown"


def load_market_csv(path: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not path.exists():
        return [], "file_not_found"
    rows = []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for source in reader:
                normalized = {str(key).strip().lower(): value for key, value in source.items()}
                raw_day = normalized.get("date") or normalized.get("day")
                if not raw_day:
                    continue
                with contextlib.suppress(ValueError):
                    raw_day = date.fromisoformat(str(raw_day)[:10]).isoformat()
                row = {
                    "date": str(raw_day)[:10],
                    "timestamp": int(
                        datetime.combine(
                            date.fromisoformat(str(raw_day)[:10]),
                            datetime_time(0, 0),
                            tzinfo=UTC,
                        ).timestamp()
                    ),
                    "open": safe_float(normalized.get("open")),
                    "high": safe_float(normalized.get("high")),
                    "low": safe_float(normalized.get("low")),
                    "close": safe_float(
                        normalized.get("close") or normalized.get("adj close")
                    ),
                    "volume": safe_float(normalized.get("volume")),
                }
                if row["open"] is not None and row["close"] is not None:
                    rows.append(row)
    except (OSError, ValueError, csv.Error) as error:
        return [], str(error)
    unique = {row["date"]: row for row in rows}
    result = [unique[key] for key in sorted(unique)]
    return (result, None) if result else ([], "no_usable_rows")


def eastmoney_secids(raw_symbol: str, provider_symbol: str) -> List[str]:
    raw = str(raw_symbol or "").upper()
    provider = str(provider_symbol or "").upper()
    if provider == "^GSPC":
        return ["100.SPX"]
    if provider == "^HSI":
        return ["100.HSI"]
    if provider == "000001.SS":
        return ["1.000001"]
    match = re.fullmatch(r"(US|HK|SH|SZ)\.([A-Z0-9._-]+)", raw)
    if not match:
        return []
    market, code = match.groups()
    if market == "HK":
        normalized = (code.lstrip("0") or "0").zfill(5)
        return [f"116.{normalized}"]
    if market == "SH":
        return [f"1.{code}"]
    if market == "SZ":
        return [f"0.{code}"]
    variants = []
    for candidate in (code, code.replace("-", "."), code.replace(".", "_")):
        if candidate not in variants:
            variants.append(candidate)
    return [
        f"{market_code}.{candidate}"
        for candidate in variants
        for market_code in (105, 106, 107)
    ]


def parse_eastmoney_bars(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    rows = []
    for line in data.get("klines") or []:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        with contextlib.suppress(ValueError):
            day = date.fromisoformat(parts[0]).isoformat()
            row = {
                "date": day,
                "timestamp": int(
                    datetime.combine(
                        date.fromisoformat(day), datetime_time(0, 0), tzinfo=UTC
                    ).timestamp()
                ),
                "open": safe_float(parts[1]),
                "close": safe_float(parts[2]),
                "high": safe_float(parts[3]),
                "low": safe_float(parts[4]),
                "volume": safe_float(parts[5]),
            }
            if row["open"] is not None and row["close"] is not None:
                rows.append(row)
    unique = {row["date"]: row for row in rows}
    return [unique[key] for key in sorted(unique)]


def fetch_eastmoney_history(
    raw_symbol: str,
    provider_symbol: str,
    start: datetime,
    end: datetime,
    cache_dir: Path,
    refresh: bool,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    errors = []
    for secid in eastmoney_secids(raw_symbol, provider_symbol):
        cache_path = cache_dir / f"{safe_market_filename(provider_symbol)}.{safe_market_filename(secid)}.eastmoney.json"
        payload = None if refresh else read_json(cache_path)
        if not isinstance(payload, dict):
            try:
                payload = request_json(
                    EASTMONEY_URL,
                    {
                        "secid": secid,
                        "klt": 101,
                        "fqt": 1,
                        "lmt": 100000,
                        "beg": start.date().strftime("%Y%m%d"),
                        "end": end.date().strftime("%Y%m%d"),
                        "fields1": "f1,f2,f3,f4,f5,f6",
                        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    },
                    attempts=2,
                )
                atomic_write_json(cache_path, payload)
                time.sleep(0.22 + random.random() * 0.08)
            except Exception as error:
                errors.append(f"{secid}: {error}")
                continue
        bars = parse_eastmoney_bars(payload)
        if bars:
            return bars, None, f"eastmoney:{secid}"
        errors.append(f"{secid}: no usable daily bars")
    return [], "; ".join(errors) or "no Eastmoney mapping", None


def fetch_price_history(
    raw_symbol: str,
    provider_symbol: str,
    start: datetime,
    end: datetime,
    market_dir: Path,
    refresh: bool,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    input_dir = market_dir / "input"
    input_candidates = [
        input_dir / f"{safe_market_filename(raw_symbol)}.csv",
        input_dir / f"{safe_market_filename(provider_symbol)}.csv",
    ]
    for path in input_candidates:
        bars, error = load_market_csv(path)
        if bars:
            return bars, None, f"csv:{path.name}"
        if error != "file_not_found":
            return [], f"CSV {path}: {error}", None

    cache_dir = market_dir / "raw"
    bars, eastmoney_error, source = fetch_eastmoney_history(
        raw_symbol, provider_symbol, start, end, cache_dir, refresh
    )
    if bars:
        return bars, None, source

    yahoo_path = cache_dir / f"{safe_market_filename(provider_symbol)}.yahoo.json"
    bars, yahoo_error = fetch_yahoo_history(
        provider_symbol, start, end, yahoo_path, refresh
    )
    if bars:
        return bars, None, "yahoo"
    return (
        [],
        f"Eastmoney: {eastmoney_error or 'unavailable'}; "
        f"Yahoo: {yahoo_error or 'unavailable'}",
        None,
    )


def mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def percent_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old is None or old == 0:
        return None
    return new / old - 1.0


def moving_volatility(bars: Sequence[Dict[str, Any]], end_index: int, window: int = 20) -> Optional[float]:
    start = max(1, end_index - window + 1)
    returns = []
    for index in range(start, end_index + 1):
        value = percent_change(bars[index]["close"], bars[index - 1]["close"])
        if value is not None:
            returns.append(value)
    if len(returns) < max(5, window // 2):
        return None
    return statistics.pstdev(returns) * math.sqrt(252)


def percentile_rank(value: Optional[float], values: Sequence[float]) -> Optional[float]:
    if value is None or not values:
        return None
    return sum(item <= value for item in values) / len(values)


def metric_round(value: Optional[float]) -> Optional[float]:
    return round(value, 8) if value is not None and math.isfinite(value) else None


def compute_market_row(
    claim: Dict[str, Any],
    provider_symbol: str,
    bars: Sequence[Dict[str, Any]],
    benchmark_symbol: Optional[str] = None,
    benchmark_bars: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    claim_time = parse_claim_time(claim.get("published_at"))
    direction = claim.get("direction") or claim.get("direction_prelabel")
    direction_sign = 1.0 if direction == "bullish" else -1.0 if direction == "bearish" else None
    base = {
        "claim_id": claim.get("claim_id") or claim.get("candidate_id"),
        "feed_id": claim.get("feed_id"),
        "author_uid": claim.get("author_uid"),
        "published_at": claim.get("published_at"),
        "symbol_raw": claim.get("symbol_raw"),
        "direction": direction,
        "provider_symbol": provider_symbol,
        "benchmark_symbol": benchmark_symbol,
        "market_data_source": None,
        "context_cutoff": None,
        "evaluation_open_date": None,
        "trend": "unknown",
        "volatility": "unknown",
        "close_vs_ma20": None,
        "close_vs_ma60": None,
        "drawdown_60d": None,
        "ret_1": None,
        "ret_5": None,
        "ret_20": None,
        "ret_60": None,
        "directional_ret_1": None,
        "directional_ret_5": None,
        "directional_ret_20": None,
        "directional_ret_60": None,
        "mfe_20": None,
        "mae_20": None,
        "excess_ret_20": None,
        "directional_excess_ret_20": None,
        "missing_reason": None,
    }
    if claim_time is None:
        base["missing_reason"] = "unparseable_claim_time"
        return base
    claim_day = claim_time.astimezone(CN_TZ).date().isoformat()
    context_indices = [index for index, bar in enumerate(bars) if bar["date"] < claim_day]
    future_indices = [index for index, bar in enumerate(bars) if bar["date"] > claim_day]
    if not context_indices:
        base["missing_reason"] = "no_completed_context_bar"
        return base
    context_index = context_indices[-1]
    base["context_cutoff"] = bars[context_index]["date"]
    closes20 = [
        bar["close"] for bar in bars[max(0, context_index - 19) : context_index + 1]
        if bar["close"] is not None
    ]
    closes60 = [
        bar["close"] for bar in bars[max(0, context_index - 59) : context_index + 1]
        if bar["close"] is not None
    ]
    close = bars[context_index]["close"]
    ma20 = mean(closes20)
    ma60 = mean(closes60)
    base["close_vs_ma20"] = metric_round(percent_change(close, ma20))
    base["close_vs_ma60"] = metric_round(percent_change(close, ma60))
    recent_highs = [
        bar["high"] for bar in bars[max(0, context_index - 59) : context_index + 1]
        if bar["high"] is not None
    ]
    base["drawdown_60d"] = metric_round(
        percent_change(close, max(recent_highs) if recent_highs else None)
    )
    old_ma20_values = [
        bar["close"]
        for bar in bars[max(0, context_index - 24) : max(0, context_index - 4)]
        if bar["close"] is not None
    ]
    old_ma20 = mean(old_ma20_values[-20:])
    slope = percent_change(ma20, old_ma20)
    if ma60 is not None and slope is not None:
        if close > ma60 and slope > 0:
            base["trend"] = "up"
        elif close < ma60 and slope < 0:
            base["trend"] = "down"
        else:
            base["trend"] = "mixed"
    current_vol = moving_volatility(bars, context_index)
    historical_vols = []
    for index in range(max(20, context_index - 252), context_index + 1):
        value = moving_volatility(bars, index)
        if value is not None:
            historical_vols.append(value)
    vol_percentile = percentile_rank(current_vol, historical_vols)
    if vol_percentile is not None:
        base["volatility"] = (
            "high" if vol_percentile >= 0.8 else "low" if vol_percentile <= 0.2 else "normal"
        )

    if not future_indices:
        base["missing_reason"] = "no_forward_bar"
        return base
    start_index = future_indices[0]
    entry = bars[start_index]["open"]
    base["evaluation_open_date"] = bars[start_index]["date"]
    if entry is None or entry == 0:
        base["missing_reason"] = "missing_evaluation_open"
        return base
    for horizon in (1, 5, 20, 60):
        target_index = start_index + horizon - 1
        if target_index < len(bars):
            raw_return = percent_change(bars[target_index]["close"], entry)
            base[f"ret_{horizon}"] = metric_round(raw_return)
            base[f"directional_ret_{horizon}"] = metric_round(
                raw_return * direction_sign
                if raw_return is not None and direction_sign is not None
                else None
            )
    path20 = bars[start_index : min(len(bars), start_index + 20)]
    highs = [bar["high"] for bar in path20 if bar["high"] is not None]
    lows = [bar["low"] for bar in path20 if bar["low"] is not None]
    raw_high_excursion = percent_change(max(highs), entry) if highs else None
    raw_low_excursion = percent_change(min(lows), entry) if lows else None
    if direction == "bearish":
        base["mfe_20"] = metric_round(-raw_low_excursion if raw_low_excursion is not None else None)
        base["mae_20"] = metric_round(-raw_high_excursion if raw_high_excursion is not None else None)
    else:
        base["mfe_20"] = metric_round(raw_high_excursion)
        base["mae_20"] = metric_round(raw_low_excursion)

    if benchmark_bars and base["ret_20"] is not None:
        benchmark_context = [bar for bar in benchmark_bars if bar["date"] <= base["evaluation_open_date"]]
        benchmark_future = [bar for bar in benchmark_bars if bar["date"] >= base["evaluation_open_date"]]
        if benchmark_context and len(benchmark_future) >= 20:
            benchmark_entry = benchmark_future[0]["open"]
            benchmark_ret = percent_change(benchmark_future[19]["close"], benchmark_entry)
            if benchmark_ret is not None:
                base["excess_ret_20"] = metric_round(base["ret_20"] - benchmark_ret)
                base["directional_excess_ret_20"] = metric_round(
                    (base["ret_20"] - benchmark_ret) * direction_sign
                    if direction_sign is not None
                    else None
                )
    return base


def market(args: argparse.Namespace) -> Dict[str, Any]:
    output = Path(args.output).expanduser().resolve()
    reviewed_path = output / "analysis" / "claims.reviewed.jsonl"
    reviewed = read_jsonl(reviewed_path)
    if reviewed:
        claims = reviewed
        mode = "reviewed"
    else:
        claims = read_jsonl(output / "analysis" / "candidates.jsonl")
        mode = "machine_prelabelled_exploratory"
    claims = [
        row
        for row in claims
        if row.get("symbol_raw")
        and (
            row.get("direction") in {"bullish", "bearish"}
            or row.get("direction_prelabel") in {"bullish", "bearish"}
        )
        and not row.get("is_repost")
        and (mode == "reviewed" or not row.get("needs_symbol_verification"))
    ]
    if not claims:
        raise ResearchError("No eligible symbol-specific directional claims found.")
    override_path = output / "analysis" / "symbol_overrides.json"
    overrides = read_json(override_path, {})
    if not isinstance(overrides, dict):
        raise ResearchError(f"{override_path} must contain a JSON object.")
    if not override_path.exists():
        atomic_write_json(
            override_path,
            {
                "_comment": (
                    "Map an unresolved raw symbol to its Yahoo symbol. "
                    "Use an empty string to skip it."
                )
            },
        )
        overrides = {}
    mapped: Dict[str, Optional[str]] = {}
    unresolved = []
    for claim in claims:
        raw = str(claim.get("symbol_raw") or "")
        mapped[raw] = yahoo_symbol(raw, {str(k).upper(): str(v) for k, v in overrides.items() if not str(k).startswith("_")})
        if not mapped[raw]:
            unresolved.append(raw)

    times = [parse_claim_time(row.get("published_at")) for row in claims]
    valid_times = [item for item in times if item is not None]
    if not valid_times:
        raise ResearchError("No parseable claim timestamps.")
    start = min(valid_times) - timedelta(days=450)
    end = max(max(valid_times) + timedelta(days=150), datetime.now(UTC) + timedelta(days=2))
    market_dir = output / "analysis" / "market"
    bars_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    fetch_errors: Dict[str, str] = {}
    data_sources: Dict[str, str] = {}
    raw_by_provider: Dict[str, str] = {}
    for raw, provider in mapped.items():
        if provider:
            raw_by_provider.setdefault(provider, raw)
    for raw in mapped:
        provider = mapped[raw]
        benchmark = benchmark_for(raw) if provider else None
        if benchmark:
            raw_by_provider.setdefault(benchmark, benchmark)
    needed_symbols = {value for value in mapped.values() if value}
    needed_benchmarks = {benchmark_for(raw) for raw in mapped if mapped[raw]}
    for symbol in sorted(needed_symbols | {item for item in needed_benchmarks if item}):
        bars, error, source = fetch_price_history(
            raw_by_provider.get(symbol, symbol),
            symbol,
            start,
            end,
            market_dir,
            args.refresh_market,
        )
        bars_by_symbol[symbol] = bars
        if source:
            data_sources[symbol] = source
        if error:
            fetch_errors[symbol] = error
        log(
            f"[market] {symbol}: bars={len(bars)} "
            f"source={source or 'none'} error={error or 'none'}"
        )

    rows = []
    for claim in claims:
        raw = str(claim.get("symbol_raw") or "")
        provider = mapped.get(raw)
        if not provider:
            row = compute_market_row(claim, "", [])
            row["missing_reason"] = "unresolved_symbol"
            rows.append(row)
            continue
        benchmark = benchmark_for(raw)
        row = compute_market_row(
            claim,
            provider,
            bars_by_symbol.get(provider, []),
            benchmark,
            bars_by_symbol.get(benchmark, []),
        )
        row["market_data_source"] = data_sources.get(provider)
        if provider in fetch_errors:
            row["missing_reason"] = f"provider_error: {fetch_errors[provider]}"
        rows.append(row)

    market_dir = output / "analysis" / "market"
    write_jsonl(market_dir / "claims_market.jsonl", rows)
    fields = [
        "claim_id",
        "feed_id",
        "author_uid",
        "published_at",
        "symbol_raw",
        "direction",
        "provider_symbol",
        "benchmark_symbol",
        "market_data_source",
        "context_cutoff",
        "evaluation_open_date",
        "trend",
        "volatility",
        "close_vs_ma20",
        "close_vs_ma60",
        "drawdown_60d",
        "ret_1",
        "ret_5",
        "ret_20",
        "ret_60",
        "directional_ret_1",
        "directional_ret_5",
        "directional_ret_20",
        "directional_ret_60",
        "mfe_20",
        "mae_20",
        "excess_ret_20",
        "directional_excess_ret_20",
        "missing_reason",
    ]
    csv_path = market_dir / "claims_market.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = csv_path.with_name(csv_path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fields} for row in rows)
    os.replace(temporary, csv_path)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": mode,
        "claims_considered": len(claims),
        "rows": len(rows),
        "rows_with_forward_20": sum(row.get("ret_20") is not None for row in rows),
        "unresolved_symbols": sorted(set(unresolved)),
        "provider_errors": fetch_errors,
        "data_sources": data_sources,
        "time_protocol": {
            "context": "last daily bar strictly before the publication date",
            "evaluation": "first daily open strictly after the publication date",
        },
        "warning": (
            "Exploratory machine prelabels were used; review and freeze claims before "
            "publishing conclusions."
            if mode != "reviewed"
            else None
        ),
    }
    atomic_write_json(market_dir / "market_manifest.json", summary)
    log(f"Market enrichment complete: {summary['rows_with_forward_20']}/{len(rows)} have 20-session outcomes.")
    return summary


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(str(item) for item in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(str(item).replace("|", "\\|").replace("\n", " ") for item in row)
            + " |"
        )
    return "\n".join(lines)


def display_percent(value: Optional[float]) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def bootstrap_interval(
    values: Sequence[float],
    level: float,
    seed: str,
    samples: int = 2000,
) -> Tuple[Optional[float], Optional[float]]:
    if not values:
        return None, None
    generator = random.Random(
        int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16)
    )
    size = len(values)
    estimates = []
    for _ in range(samples):
        sample = [values[generator.randrange(size)] for _ in range(size)]
        estimates.append(sum(sample) / size)
    estimates.sort()
    tail = (1.0 - level) / 2.0
    low_index = max(0, min(samples - 1, int(math.floor(tail * samples))))
    high_index = max(0, min(samples - 1, int(math.ceil((1.0 - tail) * samples)) - 1))
    return estimates[low_index], estimates[high_index]


def binomial_two_sided_pvalue(successes: int, total: int) -> Optional[float]:
    if total <= 0:
        return None
    lower = sum(
        math.comb(total, index) * (0.5**total)
        for index in range(0, successes + 1)
    )
    upper = sum(
        math.comb(total, index) * (0.5**total)
        for index in range(successes, total + 1)
    )
    return min(1.0, 2.0 * min(lower, upper))


def benjamini_hochberg(pvalues: Dict[str, float]) -> Dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda item: item[1])
    count = len(ordered)
    adjusted: Dict[str, float] = {}
    running = 1.0
    for rank_from_end in range(count, 0, -1):
        key, value = ordered[rank_from_end - 1]
        candidate = min(1.0, value * count / rank_from_end)
        running = min(running, candidate)
        adjusted[key] = running
    return adjusted


def build_episode_candidates(
    output: Path,
    claims: Sequence[Dict[str, Any]],
    market_by_id: Dict[str, Dict[str, Any]],
    mode: str,
) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        uid = str(claim.get("author_uid") or "")
        symbol = str(claim.get("symbol_raw") or "")
        published = parse_claim_time(claim.get("published_at"))
        if uid and symbol and published:
            groups[(uid, symbol)].append(claim)
    episodes = []
    for (uid, symbol), rows in sorted(groups.items()):
        rows.sort(key=lambda row: parse_claim_time(row.get("published_at")) or datetime.min.replace(tzinfo=UTC))
        chunks: List[List[Dict[str, Any]]] = []
        for row in rows:
            published = parse_claim_time(row.get("published_at"))
            if (
                not chunks
                or published is None
                or parse_claim_time(chunks[-1][-1].get("published_at")) is None
                or published - parse_claim_time(chunks[-1][-1].get("published_at")) <= timedelta(days=90)
            ):
                if not chunks:
                    chunks.append([])
                chunks[-1].append(row)
            else:
                chunks.append([row])
        for index, chunk in enumerate(chunks, start=1):
            claim_ids = [
                str(row.get("claim_id") or row.get("candidate_id") or "")
                for row in chunk
            ]
            updates = []
            previous_direction = None
            for row, claim_id in zip(chunk, claim_ids):
                direction = row.get("direction") or row.get("direction_prelabel")
                action = row.get("action") or row.get("action_prelabel")
                if previous_direction and direction in {"bullish", "bearish"} and direction != previous_direction:
                    label = "reversal"
                elif action in {"reduce", "sell", "cover"}:
                    label = "disciplined_execution"
                else:
                    label = "insufficient_evidence"
                updates.append(
                    {
                        "claim_id": claim_id,
                        "label_prelabel": label,
                        "needs_review": True,
                    }
                )
                if direction in {"bullish", "bearish"}:
                    previous_direction = direction
            market = [market_by_id[item] for item in claim_ids if item in market_by_id]
            regimes = sorted(
                {
                    f"{row.get('trend', 'unknown')}_{row.get('volatility', 'unknown')}"
                    for row in market
                }
            )
            returns = [
                float(
                    row.get("directional_ret_20")
                    if row.get("directional_ret_20") is not None
                    else row["ret_20"]
                )
                for row in market
                if row.get("ret_20") is not None
            ]
            started = parse_claim_time(chunk[0].get("published_at"))
            ended = parse_claim_time(chunk[-1].get("published_at"))
            digest = hashlib.sha256(
                f"{uid}|{symbol}|{started.isoformat() if started else index}".encode("utf-8")
            ).hexdigest()[:12]
            if len(chunk) == 1:
                confidence = "case_only"
            elif len(chunk) <= 3:
                confidence = "exploratory"
            elif len(chunk) <= 7:
                confidence = "medium_candidate"
            else:
                confidence = "needs_consistency_and_counterexample_review"
            episodes.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "episode_id": f"EP-{digest}",
                    "status": "machine_grouped_needs_review",
                    "mode": mode,
                    "author_uid": uid,
                    "symbol_raw": symbol,
                    "claim_ids": claim_ids,
                    "started_at": started.isoformat() if started else None,
                    "ended_at": ended.isoformat() if ended else None,
                    "updates": updates,
                    "regimes": regimes,
                    "outcome_summary": {
                        "evaluated_20d": len(returns),
                        "mean_raw_ret_20": metric_round(mean(returns)),
                    },
                    "confidence_prelabel": confidence,
                    "notes": [
                        "Claims are grouped by author and symbol with a 90-day gap rule.",
                        "Update labels and episode boundaries require chronological review.",
                    ],
                }
            )
    write_jsonl(output / "analysis" / "episodes.jsonl", episodes)
    return episodes


def report(args: argparse.Namespace) -> Dict[str, Any]:
    output = Path(args.output).expanduser().resolve()
    posts = read_jsonl(output / "archive" / "posts.jsonl")
    candidates = read_jsonl(output / "analysis" / "candidates.jsonl")
    reviewed = read_jsonl(output / "analysis" / "claims.reviewed.jsonl")
    claims = reviewed or candidates
    market_rows = read_jsonl(output / "analysis" / "market" / "claims_market.jsonl")
    market_by_id = {
        str(row.get("claim_id")): row for row in market_rows if row.get("claim_id")
    }
    mode = "reviewed" if reviewed else "machine_prelabelled_exploratory"
    episodes = build_episode_candidates(output, claims, market_by_id, mode)
    episodes_by_uid = Counter(str(row.get("author_uid") or "") for row in episodes)
    reports = output / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    profile_names: Dict[str, str] = {}
    for post in posts:
        uid = str(post.get("profile_uid") or post.get("author_uid") or "")
        if uid and post.get("author_name") and not post.get("is_repost"):
            profile_names.setdefault(uid, str(post["author_name"]))

    profile_lines = [
        "# 富途博主历史内容研究",
        "",
        f"> 生成时间：{now_iso()}；模式：`{mode}`。",
        "",
    ]
    if mode != "reviewed":
        profile_lines.extend(
            [
                "> **重要：本报告是机器预标注的探索版。动作、方向、标的与证据尚未逐条复核，不能作为公开能力结论或跟单依据。**",
                "",
            ]
        )
    author_uids = sorted(
        {str(row.get("profile_uid") or "") for row in posts if row.get("profile_uid")}
    )
    author_outcomes: Dict[str, List[Tuple[str, float]]] = {}
    pvalues: Dict[str, float] = {}
    for uid in author_uids:
        author_claims = [row for row in claims if str(row.get("author_uid")) == uid]
        outcomes = []
        for claim in author_claims:
            claim_id = str(claim.get("claim_id") or claim.get("candidate_id") or "")
            outcome = market_by_id.get(claim_id)
            direction = claim.get("direction") or claim.get("direction_prelabel")
            if outcome and outcome.get("ret_20") is not None and direction in {"bullish", "bearish"}:
                signed = (
                    float(outcome["directional_ret_20"])
                    if outcome.get("directional_ret_20") is not None
                    else float(outcome["ret_20"]) * (1 if direction == "bullish" else -1)
                )
                outcomes.append((str(claim.get("published_at") or ""), signed))
        outcomes.sort(key=lambda item: item[0])
        author_outcomes[uid] = outcomes
        if mode == "reviewed" and len(outcomes) >= 20:
            pvalue = binomial_two_sided_pvalue(
                sum(value > 0 for _, value in outcomes), len(outcomes)
            )
            if pvalue is not None:
                pvalues[uid] = pvalue
    qvalues = benjamini_hochberg(pvalues)

    matrix_rows = []
    for uid in author_uids:
        author_posts = [row for row in posts if str(row.get("profile_uid")) == uid]
        author_claims = [row for row in claims if str(row.get("author_uid")) == uid]
        evidence_counter = Counter(
            str(row.get("evidence_level") or row.get("evidence_prelabel") or "?")
            for row in author_claims
        )
        symbols = Counter(
            str(row.get("symbol_raw"))
            for row in author_claims
            if row.get("symbol_raw")
        )
        actions = Counter(
            str(row.get("action") or row.get("action_prelabel") or "none")
            for row in author_claims
        )
        dated_outcomes = author_outcomes.get(uid, [])
        eligible_rows = [value for _, value in dated_outcomes]
        hit_rate = (
            sum(value > 0 for value in eligible_rows) / len(eligible_rows)
            if eligible_rows
            else None
        )
        evidence_actions = evidence_counter.get("A", 0) + evidence_counter.get("B", 0)
        confidence = (
            "descriptive"
            if len(eligible_rows) < 20
            else "sample-sized; uncertainty testing still required"
        )
        statistical_lines = []
        fdr_label = "不检验"
        if mode == "reviewed" and len(eligible_rows) >= 20:
            hit_values = [1.0 if value > 0 else 0.0 for value in eligible_rows]
            hit_80 = bootstrap_interval(hit_values, 0.80, f"{uid}:hit:80")
            hit_95 = bootstrap_interval(hit_values, 0.95, f"{uid}:hit:95")
            mean_80 = bootstrap_interval(eligible_rows, 0.80, f"{uid}:mean:80")
            mean_95 = bootstrap_interval(eligible_rows, 0.95, f"{uid}:mean:95")
            qvalue = qvalues.get(uid)
            fdr_label = (
                f"q={qvalue:.3f}; {'通过' if qvalue is not None and qvalue <= 0.10 else '未通过'}"
                if qvalue is not None
                else "—"
            )
            statistical_lines.extend(
                [
                    (
                        f"- 命中率 bootstrap 80% CI："
                        f"{display_percent(hit_80[0])}–{display_percent(hit_80[1])}；"
                        f"95% CI：{display_percent(hit_95[0])}–{display_percent(hit_95[1])}"
                    ),
                    (
                        f"- 20 日方向收益均值 bootstrap 80% CI："
                        f"{display_percent(mean_80[0])}–{display_percent(mean_80[1])}；"
                        f"95% CI：{display_percent(mean_95[0])}–{display_percent(mean_95[1])}"
                    ),
                    f"- 多重比较：{fdr_label}（BH FDR 10%）",
                ]
            )
        if len(dated_outcomes) >= 10:
            split = max(1, min(len(dated_outcomes) - 1, int(len(dated_outcomes) * 0.7)))
            train = [value for _, value in dated_outcomes[:split]]
            test = [value for _, value in dated_outcomes[split:]]
            statistical_lines.append(
                f"- 70/30 时间切分命中率：前段 {display_percent(mean([1.0 if value > 0 else 0.0 for value in train]))}；"
                f"后段 {display_percent(mean([1.0 if value > 0 else 0.0 for value in test]))}"
            )
        name = profile_names.get(uid, f"UID {uid}")
        profile_lines.extend(
            [
                f"## {name}",
                "",
                (
                    f"- 归档：{len(author_posts)} 条（专栏 "
                    f"{sum(bool(row.get('is_column')) for row in author_posts)}；转发 "
                    f"{sum(bool(row.get('is_repost')) for row in author_posts)}）"
                ),
                (
                    f"- 观点/动作候选：{len(author_claims)}；A/B 执行证据："
                    f"{evidence_actions}；事件候选：{episodes_by_uid.get(uid, 0)}；"
                    f"20 日可评估样本：{len(eligible_rows)}"
                ),
                f"- 20 日方向命中率：{display_percent(hit_rate)}（{confidence}）",
                (
                    "- 高频标的："
                    + (", ".join(f"{symbol}({count})" for symbol, count in symbols.most_common(8)) or "—")
                ),
                (
                    "- 动作分布："
                    + (", ".join(f"{action}({count})" for action, count in actions.most_common()) or "—")
                ),
                *statistical_lines,
                "",
                (
                    "**当前结论：** "
                    + (
                        "已存在逐条复核记录；仍需结合事件链、反例和跨市场状态稳定性写最终判断。"
                        if reviewed
                        else "只能确认公开内容结构和机器候选，尚不能确认真实持仓、执行质量或稳定 Alpha。"
                    )
                ),
                "",
            ]
        )
        matrix_rows.append(
            [
                name,
                len(author_posts),
                sum(bool(row.get("is_column")) for row in author_posts),
                evidence_actions,
                len(eligible_rows),
                display_percent(hit_rate),
                fdr_label,
                confidence,
            ]
        )
    profile_lines.extend(
        [
            "## 统一限制",
            "",
            "- 公开发言不等于完整持仓；提及、观点、声称动作和账户收益相互不同。",
            "- 删帖、私密帖和平台未返回内容不可见，存在幸存者偏差。",
            "- 日线不能还原盘中成交；没有完整期权合约信息时不计算期权收益。",
            "- 少于 20 个合格样本只做描述，不声称统计稳定性。",
            "",
        ]
    )
    atomic_write_text(reports / "profile.md", "\n".join(profile_lines))
    matrix_text = "\n".join(
        [
            "# 能力证据矩阵",
            "",
            "> 不设总分。每一列回答不同问题，不能相互替代。",
            "",
            markdown_table(
                ["作者", "归档数", "专栏", "A/B证据", "20日样本", "方向命中", "FDR 10%", "统计边界"],
                matrix_rows,
            ),
            "",
            "待人工/模型复核的独立维度：论点清晰度、证据密度、可证伪性、入场、仓位、风险、退出、观点更新与反例。",
            "",
        ]
    )
    atomic_write_text(reports / "capability_matrix.md", matrix_text)
    rule_lines = [
        "# 可迁移规则卡",
        "",
        "这些是研究流程的安全底线，不是对任何博主的个性化结论。",
        "",
        "1. 把“提到、观点、声称交易、已验证交易证据”分开记录。",
        "2. 先冻结当时的判断，再看未来价格，避免事后聪明。",
        "3. 每个观点写清失效条件、仓位上限和退出规则；缺一项就降低可执行性。",
        "4. 大涨时检查是否按规则止盈或只会强化叙事；大跌时检查是否执行失效条件或继续迁移风险。",
        "5. 比较不同趋势与波动状态下的表现，不用单一顺风阶段定义能力。",
        "6. 强制寻找反例；没有反例审查的“风格总结”容易变成人设复述。",
        "7. 公开内容只能评价公开决策链，不能替代真实账户收益与完整仓位。",
        "",
    ]
    if reviewed:
        rule_lines.extend(
            [
                "## 基于复核记录的个性化规则",
                "",
                "请由分析模型基于 `analysis/claims.reviewed.jsonl` 和事件链补写，并逐条引用 claim_id。",
                "",
            ]
        )
    atomic_write_text(reports / "rule_cards.md", "\n".join(rule_lines))
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": mode,
        "profiles": len(matrix_rows),
        "posts": len(posts),
        "claims_or_candidates": len(claims),
        "market_rows": len(market_rows),
        "episode_candidates": len(episodes),
        "files": [
            "reports/profile.md",
            "reports/capability_matrix.md",
            "reports/rule_cards.md",
        ],
    }
    atomic_write_json(reports / "report_manifest.json", summary)
    log(f"Reports generated in {reports} ({mode}).")
    return summary


def audit(args: argparse.Namespace) -> Dict[str, Any]:
    output = Path(args.output).expanduser().resolve()
    crawl = read_json(output / "qa" / "crawl_audit.json", {})
    posts = read_jsonl(output / "archive" / "posts.jsonl")
    candidates = read_jsonl(output / "analysis" / "candidates.jsonl")
    reviewed = read_jsonl(output / "analysis" / "claims.reviewed.jsonl")
    market_rows = read_jsonl(output / "analysis" / "market" / "claims_market.jsonl")
    checks = []

    def add(name: str, passed: bool, severity: str, detail: Any) -> None:
        checks.append(
            {"name": name, "passed": bool(passed), "severity": severity, "detail": detail}
        )

    add(
        "crawl_audit_present",
        bool(crawl),
        "error",
        crawl.get("status") if isinstance(crawl, dict) else "missing",
    )
    add(
        "crawl_status_not_fail",
        bool(crawl) and crawl.get("status") != "FAIL",
        "error",
        crawl.get("status") if isinstance(crawl, dict) else "missing",
    )
    streams = crawl.get("streams") or [] if isinstance(crawl, dict) else []
    stream_pairs = {(row.get("profile_uid"), row.get("stream")) for row in streams}
    uids = {str(row.get("profile_uid")) for row in posts if row.get("profile_uid")}
    missing_streams = [
        f"{uid}:{label}"
        for uid in sorted(uids)
        for label in ("all", "columns")
        if (uid, label) not in stream_pairs
    ]
    add("both_streams_present", not missing_streams, "error", missing_streams)
    incomplete_streams = [
        f"{row.get('profile_uid')}:{row.get('stream')}:{row.get('terminal_reason')}"
        for row in streams
        if not row.get("complete_for_request")
    ]
    add("streams_complete_for_request", not incomplete_streams, "error", incomplete_streams)
    feed_ids = [str(row.get("feed_id")) for row in posts]
    duplicates = [key for key, count in Counter(feed_ids).items() if count > 1]
    add("normalized_feed_ids_unique", not duplicates, "error", duplicates)
    missing_sources = []
    for row in posts:
        detail_path = str((row.get("source") or {}).get("detail_path") or "")
        if not detail_path or not Path(detail_path).exists():
            missing_sources.append(row.get("feed_id"))
    add("normalized_posts_trace_to_detail", not missing_sources, "error", missing_sources[:50])
    candidate_feeds = {str(row.get("feed_id")) for row in candidates}
    unknown_candidate_feeds = sorted(candidate_feeds - set(feed_ids))
    add("candidates_trace_to_posts", not unknown_candidate_feeds, "error", unknown_candidate_feeds[:50])
    post_by_feed = {str(row.get("feed_id")): row for row in posts}
    unknown_reviewed_feeds = sorted(
        {
            str(row.get("feed_id"))
            for row in reviewed
            if str(row.get("feed_id")) not in post_by_feed
        }
    )
    add(
        "reviewed_claims_trace_to_posts",
        not unknown_reviewed_feeds,
        "error",
        unknown_reviewed_feeds[:50],
    )
    invalid_reviewed = []
    allowed_evidence = {"A", "B", "C", "D"}
    allowed_directions = {"bullish", "bearish", "mixed", "neutral"}
    for row in reviewed:
        claim_id = row.get("claim_id") or row.get("candidate_id") or "unknown"
        required = ("feed_id", "author_uid", "published_at", "evidence_span")
        missing = [key for key in required if not row.get(key)]
        if missing:
            invalid_reviewed.append(f"{claim_id}:missing={','.join(missing)}")
        if row.get("evidence_level") not in allowed_evidence:
            invalid_reviewed.append(f"{claim_id}:invalid_evidence")
        if row.get("direction") not in allowed_directions:
            invalid_reviewed.append(f"{claim_id}:invalid_direction")
    add(
        "reviewed_claim_schema_minimum",
        not invalid_reviewed,
        "error",
        invalid_reviewed[:50],
    )
    untraceable_spans = []
    for row in reviewed:
        post = post_by_feed.get(str(row.get("feed_id")))
        span = re.sub(r"\s+", " ", str(row.get("evidence_span") or "")).strip()
        source_text = re.sub(
            r"\s+",
            " ",
            f"{(post or {}).get('title') or ''} {(post or {}).get('text') or ''}",
        ).strip()
        if post and span and span not in source_text:
            untraceable_spans.append(row.get("claim_id") or row.get("candidate_id"))
    add(
        "reviewed_evidence_spans_trace_to_text",
        not untraceable_spans,
        "error",
        untraceable_spans[:50],
    )
    invalid_a = [
        row.get("claim_id")
        for row in reviewed
        if row.get("evidence_level") == "A"
        and (
            not row.get("image_evidence_verified")
            or not row.get("image_evidence_paths")
        )
    ]
    add("evidence_A_has_verified_source", not invalid_a, "error", invalid_a)
    missing_a_paths = []
    for row in reviewed:
        if row.get("evidence_level") != "A":
            continue
        for value in row.get("image_evidence_paths") or []:
            path = Path(str(value))
            if not path.is_absolute():
                path = output / path
            if not path.exists():
                missing_a_paths.append(f"{row.get('claim_id')}:{value}")
    add("evidence_A_paths_exist", not missing_a_paths, "error", missing_a_paths[:50])
    valid_claim_ids = {
        str(row.get("claim_id") or row.get("candidate_id") or "")
        for row in (reviewed or candidates)
    }
    unknown_market_claims = sorted(
        {
            str(row.get("claim_id"))
            for row in market_rows
            if str(row.get("claim_id")) not in valid_claim_ids
        }
    )
    add(
        "market_rows_trace_to_frozen_claims",
        not unknown_market_claims,
        "error",
        unknown_market_claims[:50],
    )
    time_violations = []
    for row in market_rows:
        published = parse_claim_time(row.get("published_at"))
        cutoff = row.get("context_cutoff")
        evaluation = row.get("evaluation_open_date")
        if published and cutoff and str(cutoff) >= published.astimezone(CN_TZ).date().isoformat():
            time_violations.append(f"{row.get('claim_id')}:context")
        if published and evaluation and str(evaluation) <= published.astimezone(CN_TZ).date().isoformat():
            time_violations.append(f"{row.get('claim_id')}:evaluation")
    add("market_no_time_travel", not time_violations, "error", time_violations[:50])
    directional_reviewed_ids = {
        str(row.get("claim_id") or row.get("candidate_id") or "")
        for row in reviewed
        if row.get("symbol_raw") and row.get("direction") in {"bullish", "bearish"}
    }
    market_claim_ids = {
        str(row.get("claim_id") or "") for row in market_rows if row.get("claim_id")
    }
    missing_market_claims = sorted(directional_reviewed_ids - market_claim_ids)
    if directional_reviewed_ids:
        add(
            "reviewed_directional_claims_have_market_rows",
            bool(market_rows),
            "error",
            {
                "directional_reviewed": len(directional_reviewed_ids),
                "market_rows": len(market_rows),
            },
        )
        add(
            "reviewed_market_row_coverage",
            not missing_market_claims,
            "warning",
            missing_market_claims[:50],
        )
    provider_missing = [
        str(row.get("claim_id"))
        for row in market_rows
        if row.get("missing_reason")
    ]
    add(
        "market_provider_and_forward_data_coverage",
        not provider_missing,
        "warning",
        provider_missing[:50],
    )
    media_failures = crawl.get("media_failures") or [] if isinstance(crawl, dict) else []
    add(
        "media_failures_disclosed",
        not media_failures,
        "warning",
        len(media_failures),
    )
    add(
        "reviewed_claims_available",
        bool(reviewed),
        "warning",
        f"{len(reviewed)} reviewed; {len(candidates)} machine candidates",
    )
    add(
        "sample_size_boundary",
        True,
        "info",
        "Per-author/window N<20 must remain descriptive; larger samples still require uncertainty and FDR checks.",
    )
    add(
        "structural_missingness_disclosed",
        True,
        "info",
        "Deleted/private/restricted posts, survivor bias, OCR limits, and daily-data limits remain.",
    )

    failed_errors = [row for row in checks if not row["passed"] and row["severity"] == "error"]
    warnings = [row for row in checks if not row["passed"] and row["severity"] == "warning"]
    status = "FAIL" if failed_errors else "WARN" if warnings else "PASS"
    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "status": status,
        "checks": checks,
        "publication_gate": {
            "data_chain_passed": not failed_errors,
            "reviewed_claims_present": bool(reviewed),
            "public_comparative_conclusion_allowed": not failed_errors and bool(reviewed),
            "market_performance_conclusion_allowed": (
                not failed_errors
                and bool(reviewed)
                and bool(market_rows)
                and not provider_missing
            ),
            "note": "PASS validates traceability and chronology, not stable alpha.",
        },
    }
    atomic_write_json(output / "qa" / "adversarial_audit.json", result)
    log(
        f"Adversarial audit {status}: errors={len(failed_errors)} warnings={len(warnings)}"
    )
    return result


def doctor(args: argparse.Namespace) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "tool": "elab-futu-research",
        "tool_version": VERSION,
        "checked_at": now_iso(),
        "python": {
            "version": ".".join(str(item) for item in sys.version_info[:3]),
            "supported": sys.version_info >= (3, 9),
        },
        "output_writable": None,
        "profile_uid": None,
        "futu_list_endpoints": {
            label: {"checked": False, "ok": None, "error": None}
            for label in STREAMS.values()
        },
        "notes": [
            "Core workflow has no third-party Python dependency.",
            "No browser cookie, token, or API key is read.",
        ],
    }
    if getattr(args, "output", None):
        output = Path(args.output).expanduser().resolve()
        try:
            output.mkdir(parents=True, exist_ok=True)
            probe = output / ".elab-futu-write-probe"
            atomic_write_text(probe, "ok")
            probe.unlink()
            result["output_writable"] = True
        except OSError as error:
            result["output_writable"] = False
            result["output_error"] = str(error)
    profiles = getattr(args, "profile", None) or []
    if profiles:
        uid = parse_uid(profiles[0])
        result["profile_uid"] = uid
        for feed_type, label in STREAMS.items():
            probe = result["futu_list_endpoints"][label]
            probe["checked"] = True
            try:
                payload = request_json(
                    LIST_URL,
                    {
                        "type": feed_type,
                        "num": 1,
                        "load_list_type": 2,
                        "target_uid": uid,
                    },
                )
                validate_list_payload(payload)
                probe["ok"] = True
                probe["sample_rows"] = len(payload.get("feed") or [])
                probe["has_more_present"] = "has_more" in payload
            except Exception as error:
                probe["ok"] = False
                probe["error"] = str(error)
    endpoint_failed = any(
        item["ok"] is False for item in result["futu_list_endpoints"].values()
    )
    result["status"] = (
        "PASS"
        if result["python"]["supported"]
        and result["output_writable"] is not False
        and not endpoint_failed
        else "FAIL"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def add_archive_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        action="append",
        required=True,
        help="Futu profile URL or numeric UID. Repeat for multiple profiles.",
    )
    parser.add_argument("--since", help="Start date YYYY-MM-DD; default is all visible history.")
    parser.add_argument("--until", help="End date YYYY-MM-DD; default is today/latest visible.")
    parser.add_argument("--output", default="./futu-research-output")
    parser.add_argument("--skip-media", action="store_true")
    parser.add_argument("--detail-workers", type=int, default=4)
    parser.add_argument("--media-workers", type=int, default=6)
    parser.add_argument("--max-pages", type=int, default=10000)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh list pages. Successful detail/media caches are still reused.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive public Futu dynamics and columns, then build auditable research."
    )
    parser.add_argument("--version", action="version", version=VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="Check runtime and current endpoint shape.")
    doctor_parser.add_argument("--profile", action="append")
    doctor_parser.add_argument("--output", default="./futu-research-output")

    archive_parser = subparsers.add_parser("archive", help="Capture, normalize, and audit content.")
    add_archive_arguments(archive_parser)

    prepare_parser = subparsers.add_parser("prepare", help="Create reviewable claim candidates.")
    prepare_parser.add_argument("--output", default="./futu-research-output")

    market_parser = subparsers.add_parser("market", help="Add time-frozen daily market context.")
    market_parser.add_argument("--output", default="./futu-research-output")
    market_parser.add_argument("--refresh-market", action="store_true")

    report_parser = subparsers.add_parser("report", help="Generate bounded profile reports.")
    report_parser.add_argument("--output", default="./futu-research-output")

    audit_parser = subparsers.add_parser("audit", help="Run adversarial evidence-chain checks.")
    audit_parser.add_argument("--output", default="./futu-research-output")

    run_parser = subparsers.add_parser(
        "run", help="One-shot archive, candidate preparation, market, report, and audit."
    )
    add_archive_arguments(run_parser)
    run_parser.add_argument("--refresh-market", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor(args)
        elif args.command == "archive":
            result = archive(args)
        elif args.command == "prepare":
            result = prepare(args)
        elif args.command == "market":
            result = market(args)
        elif args.command == "report":
            result = report(args)
        elif args.command == "audit":
            result = audit(args)
        elif args.command == "run":
            archive(args)
            prepare(args)
            try:
                market(args)
            except ResearchError as error:
                log(f"Market enrichment skipped with recorded warning: {error}")
            report(args)
            result = audit(args)
        else:
            parser.error(f"Unknown command {args.command}")
            return 2
        return 1 if isinstance(result, dict) and result.get("status") == "FAIL" else 0
    except KeyboardInterrupt:
        log("Interrupted; cached files remain resumable.")
        return 130
    except ResearchError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
