from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.cleaner import clean_workout_log
from src.coach import render_coach_page
from src.metrics import clean_checkins
from src.pages.dashboard import render_dashboard
from src.pages.grades import render_grades_page
from src.sheets_client import (
    DEFAULT_SPREADSHEET_ID,
    GoogleSheetsError,
    get_credentials_client_email,
    load_all_worksheets,
    load_checkins_worksheet,
)

st.set_page_config(
    page_title="Workout Analytics",
    page_icon=":material/fitness_center:",
    layout="wide",
)

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=IBM+Plex+Mono:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap');

*, *::before, *::after { box-sizing: border-box; }

html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
.main {
    background-color: #0d0d0f !important;
    color: #c8c8cc !important;
}

[data-testid="stMain"] .block-container {
    padding-top: 2rem !important;
    max-width: 1400px !important;
}

[data-testid="stHeader"] { display: none !important; }
#MainMenu, footer { visibility: hidden !important; }

[data-testid="collapsedControl"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    z-index: 999999 !important;
    position: fixed !important;
    top: 0.75rem !important;
    left: 0.75rem !important;
}

[data-testid="collapsedControl"] button,
[data-testid="collapsedControl"] [role="button"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    pointer-events: auto !important;
    color: #e8890c !important;
    background: #111113 !important;
    border: 1px solid #252528 !important;
    border-radius: 3px !important;
}

* { font-family: 'IBM Plex Mono', monospace !important; }

/* Restore Material Symbols font so Streamlit icons render correctly */
.material-symbols-rounded,
[class*="material-symbols-"] {
    font-family: 'Material Symbols Rounded' !important;
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Bebas Neue', cursive !important;
    letter-spacing: 0.06em !important;
}

/* ── Sidebar ─────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #090909 !important;
    border-right: 1px solid #1a1a1e !important;
}

[data-testid="stSidebarContent"] { padding: 1.5rem 1rem !important; }

[data-testid="stSidebar"] h2 {
    color: #e8890c !important;
    font-size: 1.3rem !important;
    letter-spacing: 0.12em !important;
    border-bottom: 1px solid #1a1a1e !important;
    padding-bottom: 0.6rem !important;
    margin-bottom: 1.2rem !important;
}

[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    font-size: 0.68rem !important;
    color: #444450 !important;
    letter-spacing: 0.04em !important;
}

/* Top page navigation */
[data-testid="stSegmentedControl"],
[data-testid="stRadio"] {
    background: #090909 !important;
    border: 1px solid #1e1e22 !important;
    border-radius: 3px !important;
    padding: 0.35rem !important;
    margin-bottom: 1.1rem !important;
}

[data-testid="stSegmentedControl"] button,
[data-testid="stRadio"] label {
    color: #888890 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.16em !important;
    font-size: 0.66rem !important;
    border-radius: 2px !important;
}

[data-testid="stSegmentedControl"] button[aria-pressed="true"],
[data-testid="stRadio"] label:has(input:checked) {
    background: rgba(232,137,12,0.16) !important;
    border-color: rgba(232,137,12,0.45) !important;
    color: #e8890c !important;
}

/* ── Buttons ─────────────────────────────── */
.stButton > button {
    background: transparent !important;
    border: 1px solid #e8890c !important;
    color: #e8890c !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.65rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    border-radius: 2px !important;
    padding: 0.45rem 1.2rem !important;
    transition: background 0.15s ease, color 0.15s ease !important;
    width: 100% !important;
}

.stButton > button:hover {
    background: #e8890c !important;
    color: #0d0d0f !important;
    border-color: #e8890c !important;
}

/* ── Metric cards ────────────────────────── */
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}

[data-testid="metric-container"] {
    background: #111113 !important;
    border: 1px solid #1e1e22 !important;
    border-left: 3px solid #e8890c !important;
    border-radius: 3px !important;
    padding: 1.1rem 1.3rem !important;
    animation: fadeUp 0.4s ease-out both !important;
}

[data-testid="stMetricLabel"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.6rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.22em !important;
    text-transform: uppercase !important;
    color: #444450 !important;
}

[data-testid="stMetricValue"] {
    font-family: 'Bebas Neue', cursive !important;
    font-size: 2.6rem !important;
    color: #f0f0f2 !important;
    letter-spacing: 0.04em !important;
    line-height: 1.1 !important;
}

/* ── Inputs ──────────────────────────────── */
[data-testid="stTextInput"] input,
[data-baseweb="input"] input {
    background: #0a0a0c !important;
    border-color: #252528 !important;
    color: #c8c8cc !important;
    font-size: 0.75rem !important;
    border-radius: 2px !important;
}

[data-baseweb="select"] > div {
    background: #0a0a0c !important;
    border-color: #252528 !important;
    border-radius: 2px !important;
}

[data-baseweb="tag"] {
    background: rgba(232,137,12,0.15) !important;
    border: 1px solid rgba(232,137,12,0.3) !important;
    color: #e8890c !important;
}

/* ── Widget labels ───────────────────────── */
[data-testid="stWidgetLabel"] {
    font-size: 0.62rem !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    color: #444450 !important;
    font-weight: 500 !important;
}

/* ── Tabs ────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid #1e1e22 !important;
    gap: 0 !important;
}

.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #444450 !important;
    font-size: 0.65rem !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    border-bottom: 2px solid transparent !important;
    padding: 0.55rem 1.3rem !important;
    font-family: 'IBM Plex Mono', monospace !important;
}

.stTabs [aria-selected="true"] {
    color: #e8890c !important;
    border-bottom: 2px solid #e8890c !important;
}

.stTabs [data-baseweb="tab-panel"] {
    padding-top: 1.25rem !important;
    background: transparent !important;
}

/* ── DataFrames ──────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid #1e1e22 !important;
    border-radius: 3px !important;
    overflow: hidden !important;
}

/* ── Expander ────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid #1e1e22 !important;
    border-radius: 3px !important;
    background: #0f0f11 !important;
}

[data-testid="stExpander"] summary {
    font-size: 0.68rem !important;
    letter-spacing: 0.15em !important;
    text-transform: uppercase !important;
    color: #444450 !important;
}

/* ── Alerts ──────────────────────────────── */
[data-testid="stAlert"] {
    background: #111113 !important;
    border: 1px solid #252528 !important;
    border-radius: 3px !important;
    font-size: 0.78rem !important;
}

/* ── Dividers ────────────────────────────── */
hr { border-color: #1e1e22 !important; border-width: 1px 0 0 0 !important; }

/* ── Spinner ─────────────────────────────── */
[data-testid="stSpinner"] p { color: #e8890c !important; }

/* ── Chart containers ────────────────────── */
[data-testid="stPlotlyChart"] {
    background: #111113 !important;
    border: 1px solid #1e1e22 !important;
    border-radius: 3px !important;
    padding: 0.5rem !important;
}

/* ── Selectbox dropdown ──────────────────── */
[data-testid="stSelectbox"] [data-baseweb="select"] {
    background: #0a0a0c !important;
}
</style>
"""


def render_top_navigation() -> str:
    pages = ["Coach", "Dashboard", "Grades"]
    if hasattr(st, "segmented_control"):
        return st.segmented_control(
            "Page",
            pages,
            default="Coach",
            label_visibility="collapsed",
            key="top_page_nav",
        ) or "Coach"

    try:
        return st.radio(
            "Page",
            pages,
            index=0,
            horizontal=True,
            label_visibility="collapsed",
            key="top_page_nav",
        ) or "Coach"
    except TypeError:
        return st.radio(
            "Page",
            pages,
            index=0,
            label_visibility="collapsed",
            key="top_page_nav",
        ) or "Coach"


@st.cache_data(ttl=600, show_spinner=False)
def load_data(spreadsheet_id: str) -> pd.DataFrame:
    raw = load_all_worksheets(spreadsheet_id)
    return clean_workout_log(raw)


@st.cache_data(ttl=600, show_spinner=False)
def load_checkins(spreadsheet_id: str) -> pd.DataFrame:
    try:
        raw = load_checkins_worksheet(spreadsheet_id)
        return clean_checkins(raw)
    except Exception:
        return pd.DataFrame()


def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

    st.markdown(
        """
        <div style="margin-bottom:1.75rem;">
          <div style="font-family:'Bebas Neue',cursive;font-size:3rem;
                      letter-spacing:0.12em;color:#f0f0f2;line-height:1;
                      margin-bottom:0.3rem;">
            WORKOUT ANALYTICS
          </div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.62rem;
                      letter-spacing:0.25em;color:#333338;text-transform:uppercase;">
            Performance &nbsp;·&nbsp; Volume &nbsp;·&nbsp; Progress
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    page = render_top_navigation()

    spreadsheet_id = st.sidebar.text_input(
        "Google Spreadsheet ID",
        value=os.getenv("WORKOUT_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID),
    )
    client_email = get_credentials_client_email()
    st.sidebar.caption(f"Service account: {client_email or 'credentials not found'}")
    st.sidebar.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    if st.sidebar.button("↺  Refresh Data"):
        load_data.clear()
        load_checkins.clear()

    try:
        with st.spinner("Loading workout data..."):
            df = load_data(spreadsheet_id)
            checkins = load_checkins(spreadsheet_id)
    except GoogleSheetsError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.exception(exc)
        st.stop()

    if df.empty:
        st.warning("No usable workout rows were found after cleaning.")
        st.stop()

    if page == "Coach":
        render_coach_page(df, checkins, spreadsheet_id)
    elif page == "Dashboard":
        render_dashboard(df, checkins)
    else:
        render_grades_page(df, checkins)


if __name__ == "__main__":
    main()
