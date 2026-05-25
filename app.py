import streamlit as st
from dashboard.constants import KPI_1_LABEL, KPI_2_LABEL, KPI_3_LABEL
from dashboard.kpi_views import render_kpi_1, render_kpi_2, render_kpi_3


def main() -> None:
    st.set_page_config(page_title="Prediction Market Comparison Dashboard", layout="wide")
    kpi2_ratio_mode = "7d rolling"

    with st.sidebar:
        selected_kpi = st.radio("KPI", [KPI_1_LABEL, KPI_2_LABEL, KPI_3_LABEL], index=0)
        st.header("Inputs")
        refresh = st.button("Refresh data")

        if selected_kpi == KPI_2_LABEL:
            kpi2_ratio_mode = st.radio(
                "Average mode",
                ["7d rolling", "Daily (no rolling)"],
                index=0,
                horizontal=True,
                key="kpi2_ratio_mode",
            )
        elif selected_kpi == KPI_1_LABEL:
            st.caption("No additional inputs for this KPI.")

    if refresh:
        st.cache_data.clear()

    st.title(selected_kpi)
    if selected_kpi == KPI_1_LABEL:
        render_kpi_1()
    elif selected_kpi == KPI_2_LABEL:
        render_kpi_2(kpi2_ratio_mode)
    else:
        render_kpi_3()


if __name__ == "__main__":
    main()
