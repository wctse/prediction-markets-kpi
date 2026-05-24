from io import StringIO
import os

import pandas as pd
import requests
import streamlit as st

from .constants import MERGED_MARKET_DATA_URL, OPINION_KPI2_DUNE_QUERY_ID


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_merged_market_data(csv_url: str = MERGED_MARKET_DATA_URL) -> pd.DataFrame:
    try:
        response = requests.get(csv_url, timeout=30)
        response.raise_for_status()
    except requests.exceptions.SSLError:
        response = requests.get(csv_url, timeout=30, verify=False)
        response.raise_for_status()

    df = pd.read_csv(StringIO(response.text))
    required_columns = {"timestamp", "source", "notional_volume_usd", "open_interest_usd"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Merged data is missing required columns: {missing}")

    cleaned = df[list(required_columns)].copy()
    cleaned["timestamp"] = pd.to_datetime(cleaned["timestamp"], utc=True, errors="coerce")
    cleaned["notional_volume_usd"] = pd.to_numeric(cleaned["notional_volume_usd"], errors="coerce")
    cleaned["open_interest_usd"] = pd.to_numeric(cleaned["open_interest_usd"], errors="coerce")
    cleaned = cleaned.dropna(subset=["timestamp", "source", "notional_volume_usd", "open_interest_usd"])
    return cleaned


def _extract_dune_rows(query_result: object) -> list[dict]:
    get_rows = getattr(query_result, "get_rows", None)
    if callable(get_rows):
        rows = get_rows()
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    candidates = [query_result, getattr(query_result, "result", None)]
    for candidate in candidates:
        if candidate is None:
            continue
        rows = candidate.get("rows") if isinstance(candidate, dict) else getattr(candidate, "rows", None)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    raise ValueError("Unexpected Dune response format: could not parse rows")


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_opinion_kpi2_data_from_dune(query_id: int = OPINION_KPI2_DUNE_QUERY_ID) -> pd.DataFrame:
    try:
        from dune_client.client import DuneClient
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Missing dune-client package. Install dependencies with './.venv/bin/pip install -r requirements.txt'."
        ) from exc

    api_key = os.getenv("DUNE_API_KEY")
    if not api_key:
        raise ValueError("Missing DUNE_API_KEY in environment")

    dune = DuneClient(api_key)
    query_result = dune.get_latest_result(query_id)
    rows = _extract_dune_rows(query_result)

    columns = ["timestamp", "source", "notional_volume_usd", "open_interest_usd"]
    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)
    required_columns = {"day", "daily_volume_usd", "open_interest_usd"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Opinion Dune data is missing required columns: {missing}")

    cleaned = df[list(required_columns)].copy()
    cleaned["timestamp"] = pd.to_datetime(cleaned["day"], utc=True, errors="coerce")
    cleaned["source"] = "Opinion"
    cleaned["notional_volume_usd"] = pd.to_numeric(cleaned["daily_volume_usd"], errors="coerce")
    cleaned["open_interest_usd"] = pd.to_numeric(cleaned["open_interest_usd"], errors="coerce")
    cleaned = cleaned.dropna(subset=["timestamp", "source", "notional_volume_usd", "open_interest_usd"])
    return cleaned[columns]


def compute_rolling_volume_oi_ratio(
    merged_data: pd.DataFrame,
    lookback_days: int = 90,
    rolling_days: int = 7,
) -> pd.DataFrame:
    daily = (
        merged_data.assign(date=merged_data["timestamp"].dt.floor("D"))
        .groupby(["source", "date"], as_index=False)[["notional_volume_usd", "open_interest_usd"]]
        .sum()
        .sort_values(["source", "date"])
    )

    daily["volume_rolling_usd"] = daily.groupby("source")["notional_volume_usd"].transform(
        lambda s: s.rolling(window=rolling_days, min_periods=1).sum()
    )
    daily["open_interest_rolling_usd"] = daily.groupby("source")["open_interest_usd"].transform(
        lambda s: s.rolling(window=rolling_days, min_periods=1).sum()
    )
    daily["volume_oi_ratio_7d"] = daily["volume_rolling_usd"] / daily["open_interest_rolling_usd"].replace(0, pd.NA)

    ratio_df = daily.dropna(subset=["volume_oi_ratio_7d"]).copy()
    if ratio_df.empty:
        return ratio_df

    max_date = ratio_df["date"].max()
    min_date = max_date - pd.Timedelta(days=lookback_days - 1)
    return ratio_df[ratio_df["date"] >= min_date]


def compute_open_interest_market_share(
    merged_data: pd.DataFrame,
    lookback_days: int = 90,
) -> pd.DataFrame:
    daily = (
        merged_data.assign(date=merged_data["timestamp"].dt.floor("D"))
        .groupby(["source", "date"], as_index=False)[["open_interest_usd", "notional_volume_usd"]]
        .sum()
        .sort_values(["source", "date"])
    )

    daily["open_interest_original_usd"] = daily["open_interest_usd"]
    anomaly_mask = (daily["open_interest_usd"] == 0) & (daily["notional_volume_usd"] > 0)

    daily["open_interest_usd"] = daily["open_interest_usd"].astype("Float64")
    daily.loc[anomaly_mask, "open_interest_usd"] = pd.NA
    daily["open_interest_usd"] = daily.groupby("source")["open_interest_usd"].transform(
        lambda s: s.interpolate(method="linear", limit_area="inside")
    )

    daily["was_interpolated"] = anomaly_mask & daily["open_interest_usd"].notna()
    daily["open_interest_original_usd"] = daily["open_interest_original_usd"].where(
        daily["was_interpolated"],
        daily["open_interest_usd"],
    )

    daily["total_open_interest_usd"] = daily.groupby("date")["open_interest_usd"].transform("sum")
    share_df = daily[daily["total_open_interest_usd"] > 0].copy()
    if share_df.empty:
        return share_df

    share_df["open_interest_share_pct"] = (share_df["open_interest_usd"] / share_df["total_open_interest_usd"]) * 100

    max_date = share_df["date"].max()
    min_date = max_date - pd.Timedelta(days=lookback_days - 1)
    return share_df[share_df["date"] >= min_date]
