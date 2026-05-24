import streamlit as st
from dashboard.constants import KPI_1_LABEL, KPI_2_LABEL, KPI_3_LABEL
from dashboard.kpi_views import render_kpi_1, render_kpi_2, render_kpi_3


def main() -> None:
    st.set_page_config(page_title="Prediction Market Comparison Dashboard", layout="wide")

    with st.sidebar:
        selected_kpi = st.radio("KPI", [KPI_1_LABEL, KPI_2_LABEL, KPI_3_LABEL], index=0)
        st.header("Inputs")
        refresh = st.button("Refresh data")

        if selected_kpi in (KPI_1_LABEL, KPI_2_LABEL):
            st.caption("No additional inputs for this KPI.")

    if refresh:
        st.cache_data.clear()

    st.title(selected_kpi)
    if selected_kpi == KPI_1_LABEL:
        render_kpi_1()
    elif selected_kpi == KPI_2_LABEL:
        render_kpi_2()
    else:
        render_kpi_3()


if __name__ == "__main__":
    main()
