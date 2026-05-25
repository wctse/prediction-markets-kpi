import json
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

KPI_EVENT_MARKERS = [
    (pd.Timestamp("2026-03-05", tz="UTC"), "$OPN airdrop"),
]


def _with_week_label(df: pd.DataFrame) -> pd.DataFrame:
    chart_df = df.copy()
    chart_df["date_week_label"] = chart_df["date"].dt.strftime("%Y-%m-%d (%A)")
    return chart_df


def _add_event_markers(fig) -> None:
    for event_date, event_label in KPI_EVENT_MARKERS:
        event_x = event_date.strftime("%Y-%m-%d")
        fig.add_shape(
            type="line",
            x0=event_x,
            x1=event_x,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line=dict(color="#6B7280", dash="dash", width=1.5),
        )
        fig.add_annotation(
            x=event_x,
            y=1,
            xref="x",
            yref="paper",
            text=event_label,
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font=dict(color="#6B7280", size=11),
        )


def _render_market_share_chart(market_share_df: pd.DataFrame, chart_placeholder, absolute_placeholder) -> None:
    chart_df = _with_week_label(market_share_df)

    market_share_fig = px.area(
        chart_df,
        x="date",
        y="open_interest_share_pct",
        color="source",
        color_discrete_map=PLATFORM_COLORS,
        custom_data=[
            "date_week_label",
            "open_interest_usd",
            "open_interest_original_usd",
            "was_interpolated",
            "total_open_interest_usd",
        ],
        title=OPEN_INTEREST_SHARE_TITLE,
    )
    market_share_fig.update_traces(
        hovertemplate=(
            "Date: %{customdata[0]}"
            "<br>Platform: %{fullData.name}"
            "<br>Share: %{y:.2f}%"
            "<br>Open Interest: $%{customdata[1]:,.0f}"
            "<br>Original Open Interest: $%{customdata[2]:,.0f}"
            "<br>Interpolated: %{customdata[3]}"
            "<br>Total Open Interest: $%{customdata[4]:,.0f}"
            "<extra></extra>"
        ),
    )
    _add_event_markers(market_share_fig)
    market_share_fig.update_xaxes(title_text="Date")
    market_share_fig.update_yaxes(title_text="Share (%)", range=[0, 100], ticksuffix="%")
    market_share_fig.update_layout(legend_title_text="Platform", template="plotly_white")
    chart_placeholder.plotly_chart(market_share_fig, use_container_width=True)

    market_absolute_fig = px.area(
        chart_df,
        x="date",
        y="open_interest_usd",
        color="source",
        color_discrete_map=PLATFORM_COLORS,
        custom_data=[
            "date_week_label",
            "open_interest_original_usd",
            "was_interpolated",
            "total_open_interest_usd",
            "open_interest_share_pct",
        ],
        title=OPEN_INTEREST_ABSOLUTE_TITLE,
    )
    market_absolute_fig.update_traces(
        hovertemplate=(
            "Date: %{customdata[0]}"
            "<br>Platform: %{fullData.name}"
            "<br>Open Interest: $%{y:,.0f}"
            "<br>Original Open Interest: $%{customdata[1]:,.0f}"
            "<br>Interpolated: %{customdata[2]}"
            "<br>Total Open Interest: $%{customdata[3]:,.0f}"
            "<br>Share: %{customdata[4]:.2f}%"
            "<extra></extra>"
        ),
    )
    _add_event_markers(market_absolute_fig)
    market_absolute_fig.update_xaxes(title_text="Date")
    market_absolute_fig.update_yaxes(title_text="Open Interest (USD)", tickprefix="$", separatethousands=True)
    market_absolute_fig.update_layout(legend_title_text="Platform", template="plotly_white")
    absolute_placeholder.plotly_chart(market_absolute_fig, use_container_width=True)


def _build_interpolation_points(market_share_df: pd.DataFrame) -> pd.DataFrame:
    interpolated_df = market_share_df[market_share_df["was_interpolated"]].copy()
    if interpolated_df.empty:
        return pd.DataFrame()

    market_share_sorted = market_share_df.sort_values(["source", "date"]).copy()

    def _neighbor_points(row: pd.Series) -> list[dict[str, object]]:
        source_rows = market_share_sorted[market_share_sorted["source"] == row["source"]]
        anchor_rows = source_rows[(~source_rows["was_interpolated"]) & source_rows["open_interest_usd"].notna()]

        previous_row = anchor_rows[anchor_rows["date"] < row["date"]].tail(1)
        next_row = anchor_rows[anchor_rows["date"] > row["date"]].head(1)

        neighbors = []
        for neighbor_df in (previous_row, next_row):
            if neighbor_df.empty:
                continue
            neighbor = neighbor_df.iloc[0]
            neighbors.append(
                {
                    "date": neighbor["date"].strftime("%Y-%m-%d"),
                    "open_interest": float(neighbor["open_interest_usd"]),
                }
            )
        return neighbors

    interpolation_points = interpolated_df[
        ["date", "source", "open_interest_original_usd", "open_interest_usd", "notional_volume_usd"]
    ].drop_duplicates(subset=["date", "source"])
    interpolation_points["interpolation_neighbors"] = interpolation_points.apply(_neighbor_points, axis=1)
    interpolation_points["interpolation_neighbors"] = interpolation_points["interpolation_neighbors"].map(
        lambda neighbors: json.dumps(neighbors)
    )
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
    market_share_chart_placeholder.info("Loading...")
    market_absolute_chart_placeholder.info("Loading...")
    charts_rendered = False

    try:
        merged_market_data = fetch_merged_market_data()
        market_share_df = compute_open_interest_market_share(merged_market_data, lookback_days=180)
    except Exception as exc:
        market_share_chart_placeholder.empty()
        market_absolute_chart_placeholder.empty()
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
        charts_rendered = True

    opinion_status = st.empty()
    opinion_status.info("Loading Opinion from Dune…")
    try:
        opinion_market_data = fetch_opinion_kpi2_data_from_dune()
        if not opinion_market_data.empty:
            merged_with_opinion = pd.concat([merged_market_data, opinion_market_data], ignore_index=True)
            market_share_with_opinion = compute_open_interest_market_share(
                merged_with_opinion,
                lookback_days=180,
            )
            if not market_share_with_opinion.empty:
                _render_interpolation_note(market_share_with_opinion, interpolation_note_placeholder)
                _render_market_share_chart(
                    market_share_with_opinion,
                    market_share_chart_placeholder,
                    market_absolute_chart_placeholder,
                )
                _render_interpolation_audit_table(market_share_with_opinion, interpolation_audit_table_placeholder)
                charts_rendered = True
                opinion_status.empty()
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

    if not charts_rendered:
        market_share_chart_placeholder.empty()
        market_absolute_chart_placeholder.empty()

    snapshot_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"Data refresh time: {snapshot_time}")


def _render_ratio_chart(
    ratio_df: pd.DataFrame,
    chart_placeholder,
    chart_title: str,
    y_axis_max: float,
) -> None:
    chart_df = _with_week_label(ratio_df)

    ratio_fig = px.line(
        chart_df,
        x="date",
        y="volume_oi_ratio_7d",
        color="source",
        color_discrete_map=PLATFORM_COLORS,
        custom_data=["date_week_label"],
        markers=True,
        title=chart_title,
    )
    ratio_fig.update_traces(
        hovertemplate=(
            "Date: %{customdata[0]}"
            "<br>Platform: %{fullData.name}"
            "<br>Volume / Open Interest ratio: %{y:.2f}"
            "<extra></extra>"
        ),
    )
    _add_event_markers(ratio_fig)
    ratio_fig.update_xaxes(title_text="Date")
    ratio_fig.update_yaxes(title_text="Volume / Open Interest ratio", range=[0, y_axis_max])
    ratio_fig.update_layout(legend_title_text="Platform", template="plotly_white")
    chart_placeholder.plotly_chart(ratio_fig, use_container_width=True)


def render_kpi_2(ratio_mode: str = "7d rolling") -> None:
    rolling_days = 7 if ratio_mode == "7d rolling" else 1
    ratio_title = ROLLING_RATIO_TITLE if rolling_days == 7 else "Daily Volume / Open Interest ratio"
    ratio_y_axis_max = 2.0

    ratio_overflow_warning = st.empty()
    ratio_chart_placeholder = st.empty()
    ratio_chart_placeholder.info("Loading...")
    chart_rendered = False
    displayed_ratio_df = pd.DataFrame()

    try:
        merged_market_data = fetch_merged_market_data()
        rolling_ratio_df = compute_rolling_volume_oi_ratio(
            merged_market_data,
            lookback_days=180,
            rolling_days=rolling_days,
        )
    except Exception as exc:
        ratio_chart_placeholder.empty()
        st.warning(f"Could not load {ratio_mode} Volume / Open Interest ratio data: {exc}")
        st.stop()

    if rolling_ratio_df.empty:
        st.info(f"No valid merged data points available for the {ratio_mode} Volume / Open Interest ratio chart.")
    else:
        _render_ratio_chart(rolling_ratio_df, ratio_chart_placeholder, ratio_title, ratio_y_axis_max)
        chart_rendered = True
        displayed_ratio_df = rolling_ratio_df

    opinion_status = st.empty()
    opinion_status.info("Loading Opinion from Dune…")
    try:
        opinion_market_data = fetch_opinion_kpi2_data_from_dune()
        if not opinion_market_data.empty:
            merged_with_opinion = pd.concat([merged_market_data, opinion_market_data], ignore_index=True)
            rolling_ratio_with_opinion = compute_rolling_volume_oi_ratio(
                merged_with_opinion,
                lookback_days=180,
                rolling_days=rolling_days,
            )
            if not rolling_ratio_with_opinion.empty:
                _render_ratio_chart(
                    rolling_ratio_with_opinion,
                    ratio_chart_placeholder,
                    ratio_title,
                    ratio_y_axis_max,
                )
                chart_rendered = True
                displayed_ratio_df = rolling_ratio_with_opinion
                opinion_status.empty()
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

    if not displayed_ratio_df.empty:
        opinion_overflow = displayed_ratio_df[
            (displayed_ratio_df["source"] == "Opinion")
            & displayed_ratio_df["volume_oi_ratio_7d"].notna()
            & (displayed_ratio_df["volume_oi_ratio_7d"] > ratio_y_axis_max)
        ]
        if not opinion_overflow.empty:
            max_ratio = float(opinion_overflow["volume_oi_ratio_7d"].max())
            ratio_overflow_warning.warning(
                f"⚠️ Opinion ratio exceeds chart max ({ratio_y_axis_max:.1f}). "
                f"Highest point is {max_ratio:.2f}; values above the cap are clipped. "
                "Use pan to inspect overflowed values."
            )
        else:
            ratio_overflow_warning.empty()
    else:
        ratio_overflow_warning.empty()

    if not chart_rendered:
        ratio_overflow_warning.empty()
        ratio_chart_placeholder.empty()

    snapshot_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"Data refresh time: {snapshot_time}")


def render_kpi_3() -> None:
    st.caption(KPI_3_SUBTITLE)
    warning_placeholder = st.empty()
    chart_placeholder = st.empty()
    chart_placeholder.info("Loading...")

    try:
        kalshi_raw = fetch_kalshi_orderbook(KALSHI_MARKET_TICKER_DEFAULT)
        poly_raw = fetch_polymarket_orderbook(POLY_YES_TOKEN_ID_DEFAULT)
        opinion_raw = fetch_opinion_orderbook()
    except (requests.RequestException, ValueError) as exc:
        chart_placeholder.empty()
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

    kpi3_y_axis_max = 30.0
    chart_df = slippage[slippage["executed_usd"] > 0].copy()
    opinion_overflow = chart_df[
        (chart_df["platform"] == "Opinion")
        & chart_df["avg_slippage_pct"].notna()
        & (chart_df["avg_slippage_pct"] > kpi3_y_axis_max)
    ]
    if not opinion_overflow.empty:
        max_slippage = float(opinion_overflow["avg_slippage_pct"].max())
        warning_placeholder.error(
            f"⚠️ Opinion slippage exceeds chart max ({kpi3_y_axis_max:.0f}%). "
            f"Highest point is {max_slippage:.2f}% and values above the cap are clipped. "
            "Use pan to inspect overflowed values."
        )
    else:
        warning_placeholder.empty()

    if chart_df.empty:
        chart_placeholder.empty()
        st.info("No valid slippage points available for the live depth comparison chart.")
    else:
        fig = px.line(
            chart_df,
            x="executed_usd",
            y="avg_slippage_pct",
            color="platform",
            color_discrete_map=PLATFORM_COLORS,
            custom_data=["mid"],
            markers=True,
            title=f"{TITLE}<br><sup>Average over YES and NO</sup>",
        )
        fig.update_traces(
            hovertemplate=(
                "Platform: %{fullData.name}"
                "<br>USD executed: $%{x:,.0f}"
                "<br>Average slippage: %{y:.2f}%"
                "<br>Mid: %{customdata[0]:.4f}"
                "<extra></extra>"
            ),
        )
        fig.update_xaxes(type="log", title_text="USD executed (log scale)")
        fig.update_yaxes(title_text="Slippage (%)", range=[0, kpi3_y_axis_max])
        fig.update_layout(legend_title_text="Platform", template="plotly_white")

        chart_placeholder.plotly_chart(fig, use_container_width=True)

    with st.expander("Current ladder data"):
        st.dataframe(
            slippage[["platform", "executed_usd", "avg_slippage_pct", "mid", "market_url"]],
            use_container_width=True,
            hide_index=True,
        )

    snapshot_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"Live snapshot time: {snapshot_time}")
