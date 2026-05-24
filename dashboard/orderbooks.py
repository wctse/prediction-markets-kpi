from typing import Iterable

import pandas as pd
import requests
import streamlit as st

from .constants import (
    KALSHI_MARKET_URL,
    OPINION_MARKET_URL,
    OPINION_ORDERBOOK_URL,
    POLYMARKET_MARKET_URL,
)
from .models import MarketBook


def _parse_kalshi_levels(levels: Iterable[list[str]]) -> list[tuple[float, float]]:
    parsed: list[tuple[float, float]] = []
    for level in levels or []:
        if not isinstance(level, list) or len(level) != 2:
            continue
        try:
            price = float(level[0])
            size = float(level[1])
        except (TypeError, ValueError):
            continue
        if 0 < price < 1 and size > 0:
            parsed.append((price, size))
    return parsed


def _parse_poly_levels(levels: Iterable[dict]) -> list[tuple[float, float]]:
    parsed: list[tuple[float, float]] = []
    for level in levels or []:
        if not isinstance(level, dict):
            continue
        try:
            price = float(level.get("price"))
            size = float(level.get("size"))
        except (TypeError, ValueError):
            continue
        if 0 < price < 1 and size > 0:
            parsed.append((price, size))
    return parsed


def _asks_to_frame(side: str, levels: list[tuple[float, float]]) -> pd.DataFrame:
    rows = []
    for i, (price_usd, quantity) in enumerate(levels, start=1):
        rows.append(
            {
                "side": side,
                "level_rank": i,
                "price_usd": price_usd,
                "quantity": quantity,
                "notional_usd": price_usd * quantity,
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(ttl=15, show_spinner=False)
def fetch_kalshi_orderbook(ticker: str) -> dict:
    url = f"https://external-api.kalshi.com/trade-api/v2/markets/{ticker}/orderbook"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=15, show_spinner=False)
def fetch_polymarket_orderbook(token_id: str) -> dict:
    url = f"https://clob.polymarket.com/book?token_id={token_id}"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=15, show_spinner=False)
def fetch_opinion_orderbook() -> dict:
    response = requests.get(OPINION_ORDERBOOK_URL, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errno") not in (0, None):
        raise ValueError(f"Opinion API returned errno={payload.get('errno')}: {payload.get('errmsg', '')}")
    return payload


def normalize_kalshi_book(payload: dict) -> MarketBook:
    book = payload.get("orderbook_fp", {})

    yes_bids = sorted(_parse_kalshi_levels(book.get("yes_dollars", [])), key=lambda x: x[0], reverse=True)
    no_bids = sorted(_parse_kalshi_levels(book.get("no_dollars", [])), key=lambda x: x[0], reverse=True)

    yes_asks = sorted([(1 - price, size) for price, size in no_bids if 0 < (1 - price) < 1], key=lambda x: x[0])
    no_asks = sorted([(1 - price, size) for price, size in yes_bids if 0 < (1 - price) < 1], key=lambda x: x[0])

    asks = pd.concat(
        [
            _asks_to_frame("YES", yes_asks),
            _asks_to_frame("NO", no_asks),
        ],
        ignore_index=True,
    )

    return MarketBook(platform="Kalshi", market_url=KALSHI_MARKET_URL, asks=asks)


def normalize_polymarket_book(payload: dict) -> MarketBook:
    yes_asks_raw = sorted(_parse_poly_levels(payload.get("asks", [])), key=lambda x: x[0])
    yes_bids_raw = sorted(_parse_poly_levels(payload.get("bids", [])), key=lambda x: x[0], reverse=True)

    no_asks = sorted([(1 - price, size) for price, size in yes_bids_raw if 0 < (1 - price) < 1], key=lambda x: x[0])

    asks = pd.concat(
        [
            _asks_to_frame("YES", yes_asks_raw),
            _asks_to_frame("NO", no_asks),
        ],
        ignore_index=True,
    )

    return MarketBook(platform="Polymarket", market_url=POLYMARKET_MARKET_URL, asks=asks)


def normalize_opinion_book(payload: dict) -> MarketBook:
    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    yes_asks_raw = sorted(_parse_kalshi_levels(result.get("asks", [])), key=lambda x: x[0])
    yes_bids_raw = sorted(_parse_kalshi_levels(result.get("bids", [])), key=lambda x: x[0], reverse=True)

    no_asks = sorted([(1 - price, size) for price, size in yes_bids_raw if 0 < (1 - price) < 1], key=lambda x: x[0])

    asks = pd.concat(
        [
            _asks_to_frame("YES", yes_asks_raw),
            _asks_to_frame("NO", no_asks),
        ],
        ignore_index=True,
    )

    return MarketBook(platform="Opinion", market_url=OPINION_MARKET_URL, asks=asks)


def build_tiers(max_usd: float = 25_000.0) -> list[float]:
    multipliers = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 7.0, 8.0, 9.0]
    tiers = [0.0]
    for power in range(1, 5):
        base = 10**power
        for mult in multipliers:
            value = mult * base
            if value <= max_usd:
                tiers.append(value)
    return sorted(set(tiers))


def compute_mid(asks: pd.DataFrame) -> tuple[float, float, float]:
    best_yes_ask = asks[(asks["side"] == "YES") & (asks["level_rank"] == 1)]["price_usd"].max()
    best_no_ask = asks[(asks["side"] == "NO") & (asks["level_rank"] == 1)]["price_usd"].max()

    if pd.isna(best_yes_ask) or pd.isna(best_no_ask):
        raise ValueError("Missing top-of-book levels for YES/NO")

    best_no_ask_yes_equiv = 1 - float(best_no_ask)
    mid = (float(best_yes_ask) + best_no_ask_yes_equiv) / 2.0
    return float(best_yes_ask), best_no_ask_yes_equiv, float(mid)


def _simulate_side_vwap(asks: pd.DataFrame, side: str, trade_usd: float) -> float | None:
    side_levels = asks[asks["side"] == side].sort_values("level_rank", ascending=True)
    if side_levels.empty or trade_usd <= 0:
        return None

    weighted_yes_equiv = 0.0
    executed_shares = 0.0
    remaining = trade_usd

    for row in side_levels.itertuples(index=False):
        if remaining <= 0:
            break

        level_price = float(row.price_usd)
        level_shares = float(row.quantity)
        if level_price <= 0 or level_shares <= 0:
            continue

        fill_shares = min(level_shares, remaining / level_price)
        if fill_shares <= 0:
            continue

        spent_usd = fill_shares * level_price
        remaining -= spent_usd
        executed_shares += fill_shares

        if side == "YES":
            weighted_yes_equiv += level_price * fill_shares
        else:
            weighted_yes_equiv += (1 - level_price) * fill_shares

    if remaining > 0:
        synthetic_shares = remaining
        executed_shares += synthetic_shares
        if side == "YES":
            weighted_yes_equiv += synthetic_shares

    if executed_shares <= 0:
        return None

    return weighted_yes_equiv / executed_shares


def compute_slippage_ladder(book: MarketBook, tiers: list[float]) -> pd.DataFrame:
    asks = book.asks.copy()
    asks = asks[(asks["price_usd"] > 0) & (asks["price_usd"] < 1) & (asks["notional_usd"] > 0)]

    best_yes_ask, best_no_ask_yes_equiv, mid = compute_mid(asks)

    rows = []
    for trade_usd in tiers:
        if trade_usd == 0:
            vwap_yes = best_yes_ask
            vwap_no_yes_equiv = best_no_ask_yes_equiv
        else:
            vwap_yes = _simulate_side_vwap(asks, "YES", trade_usd)
            vwap_no_yes_equiv = _simulate_side_vwap(asks, "NO", trade_usd)

        slippage_terms = []
        if vwap_yes is not None and mid > 0:
            slippage_terms.append(abs(vwap_yes - mid) / mid)
        if vwap_no_yes_equiv is not None and mid > 0:
            slippage_terms.append(abs(vwap_no_yes_equiv - mid) / mid)

        avg_slippage_pct = (sum(slippage_terms) / len(slippage_terms) * 100) if slippage_terms else None

        rows.append(
            {
                "platform": book.platform,
                "market_url": book.market_url,
                "executed_usd": trade_usd,
                "avg_slippage_pct": avg_slippage_pct,
                "mid": mid,
            }
        )

    return pd.DataFrame(rows)
