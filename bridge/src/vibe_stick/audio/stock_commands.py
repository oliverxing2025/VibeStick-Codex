from __future__ import annotations

import re
import json
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Any


_STOCKS = (
    ("sh000001", "上证指数", ("上证", "上证指数")),
    ("sh000300", "沪深300", ("沪深300", "沪深三百")),
    ("sz399001", "深证成指", ("深证成指", "深成指")),
    ("sh601398", "工商银行", ("工商银行", "工行")),
    ("sh601216", "君正集团", ("君正集团", "内蒙古君正", "君正", "均正集团", "军政集团", "君政集团")),
    ("hk00700", "腾讯控股", ("腾讯控股", "腾讯")),
    ("hk09988", "阿里巴巴", ("阿里巴巴", "阿里")),
    ("hk01810", "小米集团", ("小米集团", "小米")),
    ("hk00981", "中芯国际", ("中芯国际", "中芯")),
    ("hk09992", "泡泡玛特", ("泡泡玛特", "泡泡玛特")),
)

_ADD_TERMS = ("添加", "增加", "新增", "加入", "加进", "加上")
_DELETE_TERMS = ("删除", "移除", "删掉", "去掉")


def parse_stock_command(transcript: str) -> dict[str, Any]:
    """Convert spoken text into a small, device-safe stock command."""
    normalized = _normalize(transcript)
    if not normalized:
        return {}

    if any(term in normalized for term in ("刷新行情", "刷新股票", "刷新")):
        return {"action": "refresh", "label": "刷新行情"}
    if any(term in normalized for term in ("下一页", "翻到下一页", "向后翻页")):
        return {"action": "next_page", "label": "下一页"}
    if any(term in normalized for term in ("上一页", "翻到上一页", "向前翻页")):
        return {"action": "previous_page", "label": "上一页"}

    if "排序" in normalized or "排列" in normalized:
        if any(term in normalized for term in ("跌幅", "跌得多", "跌序")):
            return {"action": "sort", "sort": "losers", "label": "跌幅排序"}
        if any(term in normalized for term in ("原始", "自定义", "恢复")):
            return {"action": "sort", "sort": "custom", "label": "原始排序"}
        if any(term in normalized for term in ("涨幅", "涨得多", "涨序")):
            return {"action": "sort", "sort": "gainers", "label": "涨幅排序"}

    action = ""
    if any(term in normalized for term in _ADD_TERMS):
        action = "add"
    elif any(term in normalized for term in _DELETE_TERMS):
        action = "delete"
    if not action:
        return {}

    for symbol, name, aliases in _STOCKS:
        if any(_normalize(alias) in normalized for alias in aliases):
            verb = "添加" if action == "add" else "删除"
            return {
                "action": action,
                "symbol": symbol,
                "name": name,
                "label": f"{verb}{name}",
            }

    symbol = _spoken_symbol(normalized)
    if symbol:
        verb = "添加" if action == "add" else "删除"
        return {"action": action, "symbol": symbol, "name": symbol, "label": f"{verb}{symbol}"}
    return {"action": "unknown", "label": "未识别股票名称"}


def resolve_stock_command(transcript: str) -> dict[str, Any]:
    """Resolve a spoken command, using an online A-share lookup as fallback."""
    command = parse_stock_command(transcript)
    if not command or command.get("action") != "unknown":
        return command

    normalized = _normalize(transcript)
    action = _requested_action(normalized)
    query = _stock_name_query(normalized)
    if not action or not query:
        return command
    match = lookup_a_share(query)
    if not match:
        return command
    symbol, name = match
    verb = "添加" if action == "add" else "删除"
    return {
        "action": action,
        "symbol": symbol,
        "name": name,
        "label": f"{verb}{name}",
    }


@lru_cache(maxsize=128)
def lookup_a_share(query: str) -> tuple[str, str] | None:
    """Look up Shanghai, Shenzhen, or Beijing A shares by spoken name."""
    query = str(query or "").strip()
    if len(query) < 2 or len(query) > 24:
        return None
    params = urllib.parse.urlencode({"input": query, "type": "14", "count": "8"})
    request = urllib.request.Request(
        f"https://searchapi.eastmoney.com/api/suggest/get?{params}",
        headers={"User-Agent": "VibeStick-Stock-Monitor/0.2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=4.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    rows = payload.get("QuotationCodeTable", {}).get("Data", [])
    candidates: list[tuple[str, str]] = []
    market_prefix = {"沪a": "sh", "深a": "sz", "京a": "bj"}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("Code") or "")
        name = str(row.get("Name") or "").strip()
        prefix = market_prefix.get(str(row.get("SecurityTypeName") or "").lower())
        if prefix and len(code) == 6 and code.isdigit() and name:
            candidates.append((prefix + code, name))
    if not candidates:
        return None

    normalized_query = _normalize(query)
    for candidate in candidates:
        if _normalize(candidate[1]) == normalized_query:
            return candidate
    return candidates[0] if len(candidates) == 1 else None


def _normalize(text: str) -> str:
    return re.sub(r"[\s,，。.!！?？:：;；、_-]+", "", str(text or "")).lower()


def _requested_action(normalized: str) -> str:
    if any(term in normalized for term in _ADD_TERMS):
        return "add"
    if any(term in normalized for term in _DELETE_TERMS):
        return "delete"
    return ""


def _stock_name_query(normalized: str) -> str:
    positions = [
        (normalized.find(term), term)
        for term in (*_ADD_TERMS, *_DELETE_TERMS)
        if normalized.find(term) >= 0
    ]
    if not positions:
        return ""
    position, term = min(positions, key=lambda item: item[0])
    query = normalized[position + len(term):]
    prefixes = ("一下", "一个", "一只", "一支", "这只", "这支", "把", "股票")
    suffixes = ("到自选股", "到自选", "进自选股", "进自选", "进来", "进去",
                "这只股票", "这只股", "股票", "吧")
    changed = True
    while changed and query:
        changed = False
        for prefix in prefixes:
            if query.startswith(prefix):
                query = query[len(prefix):]
                changed = True
                break
    changed = True
    while changed and query:
        changed = False
        for suffix in suffixes:
            if query.endswith(suffix):
                query = query[:-len(suffix)]
                changed = True
                break
    return query.strip()


def _spoken_symbol(text: str) -> str:
    match = re.search(r"(?:sh|sz|bj|hk)([0-9]{4,8})", text, re.IGNORECASE)
    if not match:
        return ""
    prefix = match.group(0)[:2].lower()
    body = match.group(1)
    if not body.isdigit():
        return ""
    return prefix + body
