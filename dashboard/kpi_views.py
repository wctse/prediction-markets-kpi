from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

from .constants import (
    KALSHI_MARKET_TICKER_DEFAULT,
    KPI_3_MAX_TIER_USD,
    KPI_3_SUBTITLE,
    OPEN_INTEREST_ABSOLUTE_TITLE,
    OPEN_INTEREST_SHARE_TITLE,
    PLATFORM_COLORS,
    POLY_YES_TOKEN_ID_DEFAULT,
    ROLLING_RATIO_TITLE,
    TITLE,
)
from .market_data import (
    compute_open_interest_market_share,
    compute_rolling_volume_oi_ratio,
    fetch_merged_market_data,
    fetch_opinion_kpi2_data_from_dune,
)
from .orderbooks import (
    build_tiers,
    compute_slippage_ladder,
    fetch_kalshi_orderbook,
    fetch_opinion_orderbook,
    fetch_polymarket_orderbook,
    normalize_kalshi_book,
    normalize_opinion_book,
    normalize_polymarket_book,
)


def _render_market_share_chart(market_share_df: pd.DataFrame, chart_placeholder, absolute_placeholder) -> None:
    market_share_fig = px.area(
        market_share_df,
        x="date",
        y="open_interest_share_pct",
        color="source",
        color_discrete_map=PLATFORM_COLORS,
        hover_data={
            "open_interest_share_pct": ":.2f",
            "open_interest_usd": ":,.0f",
            "open_interest_original_usd": ":,.0f",
            "was_interpolated": True,
            "total_open_interest_usd": ":,.0f",
        },
        title=OPEN_INTEREST_SHARE_TITLE,
    )
    market_share_fig.update_xaxes(title_text="Date")
    market_share_fig.update_yaxes(title_text="Share (%)", range=[0, 100], ticksuffix="%")
    market_share_fig.update_layout(legend_title_text="Platform", template="plotly_white")
    chart_placeholder.plotly_chart(market_share_fig, use_container_width=True)

    market_absolute_fig = px.area(
        market_share_df,
        x="date",
        y="open_interest_usd",
        color="source",
        color_discrete_map=PLATFORM_COLORS,
        hover_data={
            "open_interest_usd": ":,.0f",
            "open_interest_original_usd": ":,.0f",
            "was_interpolated": True,
            "total_open_interest_usd": ":,.0f",
            "open_interest_share_pct": ":.2f",
        },
        title=OPEN_INTEREST_ABSOLUTE_TITLE,
    )
    market_absolute_fig.update_xaxes(title_text="Date")
    market_absolute_fig.update_yaxes(title_text="Open Interest (USD)", tickprefix="$", separatethousands=True)
    market_absolute_fig.update_layout(legend_title_text="Platform", template="plotly_white")
    absolute_placeholder.plotly_chart(market_absolute_fig, use_container_width=True)


def _build_interpolation_points(market_share_df: pd.DataFrame) -> pd.DataFrame:
    interpolated_df = market_share_df[market_share_df["was_interpolated"]].copy()
    if interpolated_df.empty:
        return pd.DataFrame()

    interpolation_points = interpolated_df[
        ["date", "source", "open_interest_original_usd", "open_interest_usd", "notional_volume_usd"]
    ].drop_duplicates(subset=["date", "source"])
    interpolation_points = interpolation_points.rename(
        columns={
            "date": "date",
            "source": "platform",
            "open_interest_original_usd": "original_open_interest_usd",
            "open_interest_usd": "interpolated_open_interest_usd",
            "notional_volume_usd": "notional_volume_usd",
        }
    )
    return interpolation_points.sort_values(["date", "platform"]).reset_index(drop=True)


def _render_interpolation_note(market_share_df: pd.DataFrame, note_placeholder) -> None:
    interpolation_points = _build_interpolation_points(market_share_df)
    if interpolation_points.empty:
        note_placeholder.empty()
        return

    interpolated_date_platforms = interpolation_points[["date", "platform"]].drop_duplicates().sort_values(["date", "platform"])
    date_platform_labels = [
        f"{row.date.strftime('%Y-%m-%d')} ({row.platform})"
        for row in interpolated_date_platforms.itertuples(index=False)
    ]

    with note_placeholder.container():
        st.error(
            "🚨 Interpolated open interest detected due to zero-value anomaly. "
            f"Date(s): {', '.join(date_platform_labels)}"
        )
        st.caption(
            "Rule: when daily OI is 0 while daily volume is positive, OI is linearly interpolated "
            "from previous and next day values for that platform."
        )
        st.markdown(
            "<a href='#kpi1-interpolation-audit-table'><button>Jump to interpolation audit table</button></a>",
            unsafe_allow_html=True,
        )


def _render_interpolation_audit_table(market_share_df: pd.DataFrame, table_placeholder) -> None:
    interpolation_points = _build_interpolation_points(market_share_df)
    if interpolation_points.empty:
        table_placeholder.empty()
        return

    with table_placeholder.container():
        st.markdown("<div id='kpi1-interpolation-audit-table'></div>", unsafe_allow_html=True)
        st.subheader("Interpolation audit table")
        st.dataframe(interpolation_points, use_container_width=True, hide_index=True)


def render_kpi_1() -> None:
    interpolation_note_placeholder = st.empty()
    market_share_chart_placeholder = st.empty()
    market_absolute_chart_placeholder = st.empty()
    interpolation_audit_table_placeholder = st.empty()

    try:
        merged_market_data = fetch_merged_market_data()
        market_share_df = compute_open_interest_market_share(merged_market_data, lookback_days=90)
    except Exception as exc:
        st.warning(f"Could not load open interest market share data: {exc}")
        st.stop()

    if market_share_df.empty:
        st.info("No valid merged data points available for the open interest market share chart.")
        _render_interpolation_note(market_share_df, interpolation_note_placeholder)
        _render_interpolation_audit_table(market_share_df, interpolation_audit_table_placeholder)
    else:
        _render_interpolation_note(market_share_df, interpolation_note_placeholder)
        _render_market_share_chart(market_share_df, market_share_chart_placeholder, market_absolute_chart_placeholder)
        _render_interpolation_audit_table(market_share_df, interpolation_audit_table_placeholder)

    opinion_status = st.empty()
    opinion_status.info("Loading Opinion from Dune…")
    try:
        opinion_market_data = fetch_opinion_kpi2_data_from_dune()
        if not opinion_market_data.empty:
            merged_with_opinion = pd.concat([merged_market_data, opinion_market_data], ignore_index=True)
            market_share_with_opinion = compute_open_interest_market_share(
                merged_with_opinion,
                lookback_days=90,
            )
            if not market_share_with_opinion.empty:
                _render_interpolation_note(market_share_with_opinion, interpolation_note_placeholder)
                _render_market_share_chart(
                    market_share_with_opinion,
                    market_share_chart_placeholder,
                    market_absolute_chart_placeholder,
                )
                _render_interpolation_audit_table(market_share_with_opinion, interpolation_audit_table_placeholder)
                opinion_status.success("Opinion loaded from Dune.")
            else:
                opinion_status.warning("Opinion Dune data loaded but produced no valid KPI 1 points.")
        else:
            opinion_status.warning("Opinion Dune query returned no rows.")
    except Exception as exc:
        opinion_status.warning(f"Could not load Opinion from Dune for KPI 1: {exc}")

    if market_share_df.empty:
        try:
            opinion_status.empty()
        except Exception:
            pass

    snapshot_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"Data refresh time: {snapshot_time}")


def _render_ratio_chart(ratio_df: pd.DataFrame, chart_placeholder) -> None:
    ratio_fig = px.line(
        ratio_df,
        x="date",
        y="volume_oi_ratio_7d",
        color="source",
        color_discrete_map=PLATFORM_COLORS,
        markers=True,
        title=ROLLING_RATIO_TITLE,
    )
    ratio_fig.update_xaxes(title_text="Date")
    ratio_fig.update_yaxes(title_text="Volume / Open Interest ratio")
    ratio_fig.update_layout(legend_title_text="Platform", template="plotly_white")
    chart_placeholder.plotly_chart(ratio_fig, use_container_width=True)


def render_kpi_2() -> None:
    ratio_chart_placeholder = st.empty()

    try:
        merged_market_data = fetch_merged_market_data()
        rolling_ratio_df = compute_rolling_volume_oi_ratio(merged_market_data, lookback_days=90, rolling_days=7)
    except Exception as exc:
        st.warning(f"Could not load 7d rolling Volume / Open Interest ratio data: {exc}")
        st.stop()

    if rolling_ratio_df.empty:
        st.info("No valid merged data points available for the 7d rolling Volume / Open Interest ratio chart.")
    else:
        _render_ratio_chart(rolling_ratio_df, ratio_chart_placeholder)

    opinion_status = st.empty()
    opinion_status.info("Loading Opinion from Dune…")
    try:
        opinion_market_data = fetch_opinion_kpi2_data_from_dune()
        if not opinion_market_data.empty:
            merged_with_opinion = pd.concat([merged_market_data, opinion_market_data], ignore_index=True)
            rolling_ratio_with_opinion = compute_rolling_volume_oi_ratio(
                merged_with_opinion,
                lookback_days=90,
                rolling_days=7,
            )
            if not rolling_ratio_with_opinion.empty:
                _render_ratio_chart(rolling_ratio_with_opinion, ratio_chart_placeholder)
                opinion_status.success("Opinion loaded from Dune.")
            else:
                opinion_status.warning("Opinion Dune data loaded but produced no valid KPI 2 points.")
        else:
            opinion_status.warning("Opinion Dune query returned no rows.")
    except Exception as exc:
        opinion_status.warning(f"Could not load Opinion from Dune for KPI 2: {exc}")

    if rolling_ratio_df.empty:
        try:
            opinion_status.empty()
        except Exception:
            pass

    snapshot_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"Data refresh time: {snapshot_time}")


def render_kpi_3() -> None:
    st.caption(KPI_3_SUBTITLE)

    try:
        kalshi_raw = fetch_kalshi_orderbook(KALSHI_MARKET_TICKER_DEFAULT)
        poly_raw = fetch_polymarket_orderbook(POLY_YES_TOKEN_ID_DEFAULT)
        opinion_raw = fetch_opinion_orderbook()
    except (requests.RequestException, ValueError) as exc:
        st.error(f"Live fetch failed: {exc}")
        st.stop()

    kalshi_book = normalize_kalshi_book(kalshi_raw)
    poly_book = normalize_polymarket_book(poly_raw)
    opinion_book = normalize_opinion_book(opinion_raw)

    tiers = build_tiers(max_usd=KPI_3_MAX_TIER_USD)
    slippage = pd.concat(
        [
            compute_slippage_ladder(kalshi_book, tiers),
            compute_slippage_ladder(poly_book, tiers),
            compute_slippage_ladder(opinion_book, tiers),
        ],
        ignore_index=True,
    )

    chart_df = slippage[slippage["executed_usd"] > 0].copy()
    fig = px.line(
        chart_df,
        x="executed_usd",
        y="avg_slippage_pct",
        color="platform",
        color_discrete_map=PLATFORM_COLORS,
        markers=True,
        hover_data={"mid": ":.4f"},
        title=f"{TITLE}<br><sup>Average over YES and NO</sup>",
    )
    fig.update_xaxes(type="log", title_text="USD executed (log scale)")
    fig.update_yaxes(title_text="Slippage (%)", range=[0, 30])
    fig.update_layout(legend_title_text="Platform", template="plotly_white")

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Current ladder data"):
        st.dataframe(
            slippage[["platform", "executed_usd", "avg_slippage_pct", "mid", "market_url"]],
            use_container_width=True,
            hide_index=True,
        )

    snapshot_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"Live snapshot time: {snapshot_time}")
