from __future__ import annotations

import os
from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from src.apple_health import render_uploader as health_uploader
from src.charts import (
    bar_grade_distribution,
    bar_muscle_group_frequency,
    bar_muscle_group_volume,
    bar_top_exercises,
    bar_checkin_macros,
    bar_checkin_sleep,
    bar_checkin_steps,
    correlation_heatmap,
    dual_axis_line,
    heatmap_weekly_muscle_volume,
    line_bodyweight_trend,
    line_session_quality,
    line_weekly_volume,
    line_workout_frequency,
    scatter_1rm_timeline,
    scatter_estimated_1rm,
    scatter_with_r2,
)
from src.cleaner import clean_workout_log
from src.coach import render_coach_page
from src.fatigue import fatigue_risk_detector
from src.guardrails import compute_guardrails
from src.insights import build_next_workout_recommendation, build_weekly_insights
from src.metrics import (
    checkin_metrics,
    clean_checkins,
    daily_workout_detail,
    daily_workout_metrics,
    daily_workout_summary,
    estimated_1rm_by_exercise,
    estimated_1rm_over_time,
    get_deload_dates,
    grade_session,
    grade_sessions_history,
    minimum_effective_volume,
    muscle_group_frequency,
    muscle_group_volume,
    pr_tracker,
    session_quality_score,
    top_exercises_by_volume,
    volume_by_exercise,
    weekly_grade,
    weekly_muscle_group_volume,
    weekly_total_volume,
    workout_comparison,
    workout_frequency,
)
from src.retention import strength_retention_score
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

_SECTION_TMPL = """
<div style="display:flex;align-items:center;gap:0.75rem;
            margin:2rem 0 0.25rem 0;padding-bottom:0.75rem;
            border-bottom:1px solid #1e1e22;">
  <div style="width:3px;height:1.4rem;background:#e8890c;
              border-radius:2px;flex-shrink:0;"></div>
  <div style="font-family:'Bebas Neue',cursive;font-size:1.45rem;
              letter-spacing:0.1em;color:#c8c8cc;line-height:1;">{label}</div>
</div>
"""


def section_header(label: str) -> None:
    st.markdown(_SECTION_TMPL.format(label=label), unsafe_allow_html=True)


_PLACEHOLDER_TMPL = """
<div style="
    background:#111113;border:1px solid #252528;border-left:3px solid #e8890c;
    border-radius:3px;padding:2.5rem 1.5rem;text-align:center;
    min-height:260px;display:flex;flex-direction:column;
    align-items:center;justify-content:center;gap:0.8rem;
">
  <div style="font-size:1.8rem;opacity:0.18;color:#e8890c;">◈</div>
  <div style="font-family:'Bebas Neue',cursive;font-size:1.05rem;
              letter-spacing:0.14em;color:#e8890c;">
    Connect Apple Health to Unlock
  </div>
  <div style="font-family:'IBM Plex Mono',monospace;font-size:0.65rem;
              letter-spacing:0.08em;color:#333338;max-width:280px;">
    {metric}
  </div>
  <div style="font-family:'IBM Plex Mono',monospace;font-size:0.58rem;
              color:#222228;max-width:280px;margin-top:0.25rem;">
    {hint}
  </div>
</div>
"""


def placeholder_card(metric: str, hint: str = "") -> None:
    st.markdown(_PLACEHOLDER_TMPL.format(metric=metric, hint=hint), unsafe_allow_html=True)


_CHECKINS_PLACEHOLDER_TMPL = """
<div style="
    background:#111113;border:1px solid #252528;border-left:3px solid #333338;
    border-radius:3px;padding:1.8rem 1.5rem;text-align:center;
    display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.6rem;
">
  <div style="font-size:1.4rem;opacity:0.15;color:#888890;">◇</div>
  <div style="font-family:'Bebas Neue',cursive;font-size:0.95rem;
              letter-spacing:0.14em;color:#555560;">{title}</div>
  <div style="font-family:'IBM Plex Mono',monospace;font-size:0.62rem;
              color:#333338;max-width:300px;">{hint}</div>
</div>
"""


def checkins_placeholder(title: str, hint: str = "") -> None:
    st.markdown(_CHECKINS_PLACEHOLDER_TMPL.format(title=title, hint=hint), unsafe_allow_html=True)


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


def filter_frame(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.markdown("## Filters")

    valid_dates = df["Date"].dropna()
    if valid_dates.empty:
        st.sidebar.warning("No valid dates found in the workout log.")
        return df.iloc[0:0]

    min_date = valid_dates.min().date()
    max_date = valid_dates.max().date()
    selected_dates = st.sidebar.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
    else:
        start_date = end_date = selected_dates if isinstance(selected_dates, date) else max_date

    groups = sorted(df["MuscleGroup"].dropna().unique().tolist())
    selected_groups = st.sidebar.multiselect("Muscle group", groups, default=groups)

    exercises = sorted(df["Exercise"].dropna().unique().tolist())
    selected_exercises = st.sidebar.multiselect("Exercise", exercises, default=exercises)

    sheets = sorted(df["SourceSheet"].dropna().unique().tolist())
    selected_sheets = st.sidebar.multiselect("Source sheet", sheets, default=sheets)

    filtered = df.copy()
    filtered = filtered[
        (filtered["Date"].dt.date >= start_date)
        & (filtered["Date"].dt.date <= end_date)
        & (filtered["MuscleGroup"].isin(selected_groups))
        & (filtered["Exercise"].isin(selected_exercises))
        & (filtered["SourceSheet"].isin(selected_sheets))
    ]
    return filtered


def metric_value(value: float) -> str:
    if pd.isna(value):
        return "0"
    return f"{value:,.0f}"


def _insight_list(items: list[str]) -> str:
    return "".join(f"<li>{escape(str(item))}</li>" for item in items)


def render_guardrails_banner(df: pd.DataFrame, checkins: pd.DataFrame, deload_dates: list) -> None:
    try:
        g = compute_guardrails(df, checkins, deload_dates=deload_dates or None)
    except Exception:
        return

    score = g["composite_risk"]
    level = g["level"]
    color = g["color"]
    bg = g["bg"]
    border = g["border"]
    action = escape(str(g["action"]))
    pace_label = escape(str(g["cut_pace"]).title())
    ret_score = int(g["retention_score"])
    flags = g["recovery_flags"]
    flags_str = escape(", ".join(flags)) if flags else "none"

    st.markdown(
        f"""
        <div style="background:{bg};border:1px solid {border};border-left:4px solid {color};
                    border-radius:4px;padding:1rem 1.2rem;margin-bottom:1rem;">
          <div style="display:flex;align-items:center;gap:0.9rem;flex-wrap:wrap;">
            <div style="font-family:'Bebas Neue',cursive;font-size:1.1rem;
                        letter-spacing:0.14em;color:{color};">
              CUT GUARDRAILS
            </div>
            <div style="font-family:'Bebas Neue',cursive;font-size:1.5rem;
                        color:{color};letter-spacing:0.06em;">
              {level.upper()} — {score}/100
            </div>
          </div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.76rem;
                      color:#c8c8cc;margin-top:0.5rem;">{action}</div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.62rem;
                      color:#555560;margin-top:0.4rem;letter-spacing:0.04em;">
            retention {ret_score}/100 &nbsp;·&nbsp; cut pace {pace_label}
            &nbsp;·&nbsp; recovery flags: {flags_str}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_weekly_insights(df: pd.DataFrame) -> None:
    insights = build_weekly_insights(df)
    balance = insights["balance"]
    muscle_group_vol = insights["muscle_group_volume"] or ["No muscle group volume this week."]
    undertrained = insights.get("undertrained_muscle_groups") or ["No muscle group frequency gaps detected."]
    recommendations = insights.get("recommendations") or [insights["suggested_focus"]]
    suggested_exercises = insights.get("suggested_exercises") or ["No targeted exercise substitutions needed this week."]
    week_label = escape(str(insights["week_label"]))
    suggested_focus = escape(str(insights["suggested_focus"]))
    balance_summary = escape(str(balance["summary"]))
    weekly_score = float(insights.get("weekly_score", 0))

    section_header("Weekly Training Insights")
    st.markdown(
        f"""
        <div style="background:#111113;border:1px solid #1e1e22;border-left:3px solid #e8890c;
                    border-radius:3px;padding:1rem 1.1rem;margin-bottom:0.75rem;">
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.62rem;
                      letter-spacing:0.16em;text-transform:uppercase;color:#444450;">
            Rule-Based Summary | {week_label}
          </div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;
                      color:#c8c8cc;margin-top:0.6rem;line-height:1.55;">
            Training score: <span style="color:#e8890c;">{weekly_score:.0f}/100</span>
            &nbsp;|&nbsp; Suggested focus:
            <span style="color:#e8890c;">{suggested_focus}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("##### Top Progressing")
        st.markdown(f"<ul>{_insight_list(insights['top_progressing'])}</ul>", unsafe_allow_html=True)
    with c2:
        st.markdown("##### Stalled / Declining")
        combined_risks = list(insights["stalled"]) + list(insights.get("declining", []))
        st.markdown(f"<ul>{_insight_list(combined_risks)}</ul>", unsafe_allow_html=True)
    with c3:
        st.markdown("##### Muscle Volume")
        st.markdown(f"<ul>{_insight_list(muscle_group_vol)}</ul>", unsafe_allow_html=True)
    with c4:
        st.markdown("##### Push/Pull/Legs")
        st.metric("Push", f"{balance['push']:.0f}%")
        st.metric("Pull", f"{balance['pull']:.0f}%")
        st.metric("Legs", f"{balance['legs']:.0f}%")
        st.caption(balance_summary)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Frequency Gaps")
        st.markdown(f"<ul>{_insight_list(undertrained)}</ul>", unsafe_allow_html=True)
    with c2:
        st.markdown("##### Recommendations")
        st.markdown(f"<ul>{_insight_list(recommendations)}</ul>", unsafe_allow_html=True)

    st.markdown("##### Suggested Exercises")
    st.markdown(f"<ul>{_insight_list(suggested_exercises)}</ul>", unsafe_allow_html=True)

    next_workout = build_next_workout_recommendation(df)
    st.markdown("##### Next Workout Recommendation")
    st.markdown(
        f"""
        <div style="background:#111113;border:1px solid #1e1e22;border-left:3px solid #60a5fa;
                    border-radius:3px;padding:0.9rem 1rem;margin-top:0.4rem;">
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;color:#c8c8cc;">
            Recommended Focus: <span style="color:#60a5fa;">{escape(str(next_workout['recommended_focus']))}</span>
          </div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.68rem;color:#888890;margin-top:0.45rem;">
            {escape(str(next_workout['reason']))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"<ul>{_insight_list(next_workout['suggested_exercises'])}</ul>", unsafe_allow_html=True)
    st.caption(
        f"Sets/Reps: {next_workout['recommended_sets_reps']} | "
        f"Intensity: {next_workout['intensity_guidance']}"
    )


def render_daily_workout_detail(df: pd.DataFrame, filtered: pd.DataFrame) -> None:
    available_dates = sorted(df["Date"].dropna().dt.date.unique().tolist())
    if not available_dates:
        return

    filtered_dates = filtered["Date"].dropna().dt.date
    default_date = filtered_dates.max() if not filtered_dates.empty else available_dates[-1]
    default_index = available_dates.index(default_date) if default_date in available_dates else len(available_dates) - 1

    section_header("Daily Workout Detail")
    selected_date = st.selectbox(
        "Workout date",
        available_dates,
        index=default_index,
        format_func=lambda value: value.strftime("%Y-%m-%d"),
        key="daily_workout_date",
    )

    detail = daily_workout_detail(filtered, selected_date)
    if detail.empty:
        detail = daily_workout_detail(df, selected_date)

    summary = daily_workout_summary(detail)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Exercises", f"{summary['total_exercises']:,}")
    c2.metric("Working Sets", f"{summary['total_working_sets']:,}")
    c3.metric("Volume", metric_value(float(summary["total_volume"])))
    c4.metric("Muscle Groups", str(summary["muscle_groups_trained"]))

    st.dataframe(detail, use_container_width=True, hide_index=True)

    section_header("Workout Comparison")
    comparison = workout_comparison(df, selected_date)
    if comparison.empty:
        st.info("No prior matching exercises found for this workout date.")
    else:
        st.dataframe(comparison, use_container_width=True, hide_index=True)


def render_strength_retention(df: pd.DataFrame, deload_dates: list) -> None:
    try:
        retention = strength_retention_score(df, deload_dates=deload_dates or None)
    except Exception:
        retention = {"score": 0, "improved_pct": 0.0, "maintained_pct": 0.0,
                     "regressed_pct": 0.0, "interpretation": "Error computing retention.", "exercise_count": 0}

    section_header("Strength Retention Score")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Score", f"{retention['score']:.0f}/100")
    c2.metric("Improved", f"{retention['improved_pct']:.0f}%")
    c3.metric("Maintained", f"{retention['maintained_pct']:.0f}%")
    c4.metric("Regressed", f"{retention['regressed_pct']:.0f}%")
    st.caption(
        f"{retention['interpretation']} "
        f"Based on {retention['exercise_count']} exercises with repeat data in the last 2-3 weeks."
    )


def render_fatigue_risk(df: pd.DataFrame, deload_dates: list) -> None:
    try:
        fatigue = fatigue_risk_detector(df, deload_dates=deload_dates or None)
    except Exception:
        fatigue = {"risk": "Low", "reasons": ["Error computing fatigue risk."], "suggested_action": ""}

    section_header("Fatigue Risk Detector")
    c1, c2 = st.columns([1, 3])
    with c1:
        st.metric("Fatigue Risk", fatigue["risk"])
    with c2:
        st.markdown("##### Reasons")
        st.markdown(f"<ul>{_insight_list(fatigue['reasons'])}</ul>", unsafe_allow_html=True)
        st.caption(f"Suggested action: {fatigue['suggested_action']}")


def render_session_quality(df: pd.DataFrame) -> None:
    section_header("Session Quality Score")
    try:
        sq = session_quality_score(df)
    except Exception:
        sq = pd.DataFrame()

    if sq.empty:
        st.info("Need at least 2 sessions to compute quality scores.")
        return

    latest_score = float(sq["QualityScore"].iloc[-1])
    avg_score = float(sq["QualityScore"].mean())
    trend = float(sq["QualityScore"].iloc[-1]) - float(sq["QualityScore"].iloc[-min(5, len(sq))]) if len(sq) >= 2 else 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("Latest Session", f"{latest_score:.0f}/100")
    c2.metric("30-Session Avg", f"{avg_score:.0f}/100")
    c3.metric("5-Session Trend", f"{trend:+.0f} pts")
    st.plotly_chart(line_session_quality(sq), use_container_width=True)


def render_mev_warnings(df: pd.DataFrame) -> None:
    try:
        warnings = minimum_effective_volume(df)
    except Exception:
        return
    if not warnings:
        return

    section_header("Minimum Effective Volume")
    items_html = "".join(
        f"<li style='margin-bottom:0.3rem;'>{escape(w)}</li>" for w in warnings
    )
    st.markdown(
        f"""
        <div style="background:#1a0f00;border:1px solid #7a4800;border-left:3px solid #e8890c;
                    border-radius:3px;padding:0.9rem 1rem;margin-bottom:0.5rem;">
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;
                      letter-spacing:0.12em;text-transform:uppercase;color:#e8890c;margin-bottom:0.5rem;">
            MEV Warning — Muscle Groups Below Minimum Sets
          </div>
          <ul style="margin:0;padding-left:1.2rem;font-family:'IBM Plex Mono',monospace;
                     font-size:0.72rem;color:#c8c8cc;line-height:1.6;">
            {items_html}
          </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_bodyweight_recovery(checkins: pd.DataFrame, workout_df: pd.DataFrame) -> None:
    section_header("Bodyweight & Recovery")

    if checkins.empty:
        c1, c2 = st.columns(2)
        with c1:
            checkins_placeholder(
                "Bodyweight Trend",
                "Add a Google Sheet tab named 'Checkins' with columns: "
                "Date, Bodyweight, Waist, Calories, Protein, Carbs, Fat, Steps, "
                "SleepHours, Energy, Soreness, Stress, Deload, Notes",
            )
        with c2:
            checkins_placeholder(
                "Recovery Summary",
                "Track sleep, soreness, stress, and energy daily to see trends here.",
            )
        return

    try:
        metrics = checkin_metrics(checkins)
        retention = strength_retention_score(workout_df)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "7-Day Bodyweight",
            "0" if pd.isna(metrics["bodyweight_7day_avg"]) else f"{float(metrics['bodyweight_7day_avg']):.1f} lbs",
        )
        c2.metric(
            "Weekly Loss",
            "0" if pd.isna(metrics["weekly_weight_loss_rate"]) else f"{float(metrics['weekly_weight_loss_rate']):.1f} lbs/wk",
        )
        c3.metric(
            "Protein",
            "0" if pd.isna(metrics["average_protein"]) else f"{float(metrics['average_protein']):.0f} g",
        )
        c4.metric(
            "Sleep",
            "0" if pd.isna(metrics["average_sleep"]) else f"{float(metrics['average_sleep']):.1f} h",
        )

        left, right = st.columns([2, 1])
        with left:
            st.plotly_chart(line_bodyweight_trend(checkins), use_container_width=True)
        with right:
            st.markdown("##### Recovery Summary")
            st.caption(f"Cut pace: {str(metrics['cut_pace']).title()}")
            st.caption(str(metrics["recovery_summary"]))
            warnings = list(metrics["warnings"])
            if metrics["cut_pace"] == "aggressive" and retention["regressed_pct"] > 0:
                warnings.append("Weight is dropping fast while strength retention is declining.")
            if warnings:
                st.warning(" ".join(warnings))
            else:
                st.success("No recovery warnings from check-ins.")

        chart_a, chart_b = st.columns(2)
        with chart_a:
            st.plotly_chart(bar_checkin_steps(checkins), use_container_width=True)
        with chart_b:
            st.plotly_chart(bar_checkin_sleep(checkins), use_container_width=True)
        st.plotly_chart(bar_checkin_macros(checkins), use_container_width=True)
    except Exception as exc:
        st.warning(f"Could not render bodyweight/recovery section: {exc}")


def render_dashboard(df: pd.DataFrame, checkins: pd.DataFrame) -> None:
    filtered = filter_frame(df)

    total_volume = filtered["Volume"].sum()
    total_workouts = filtered[["Date", "Workout", "SourceSheet"]].drop_duplicates().shape[0]
    total_sets = filtered["Set"].notna().sum()
    exercise_count = filtered["Exercise"].nunique()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Volume", metric_value(total_volume))
    col2.metric("Workouts", f"{total_workouts:,}")
    col3.metric("Logged Sets", f"{total_sets:,}")
    col4.metric("Exercises", f"{exercise_count:,}")

    if filtered.empty:
        st.info("No rows match the selected filters.")
        return

    # Deload dates suppress fatigue/retention warnings
    deload_dates = get_deload_dates(checkins)

    # Prominent guardrails banner
    render_guardrails_banner(filtered, checkins, deload_dates)

    render_weekly_insights(filtered)
    render_strength_retention(filtered, deload_dates)
    render_fatigue_risk(filtered, deload_dates)
    render_mev_warnings(filtered)
    render_session_quality(filtered)
    render_bodyweight_recovery(checkins, filtered)

    section_header("Muscle Group Frequency")
    mg_frequency = muscle_group_frequency(filtered)
    left, right = st.columns(2)
    with left:
        st.dataframe(mg_frequency, use_container_width=True, hide_index=True)
    with right:
        st.plotly_chart(bar_muscle_group_frequency(mg_frequency), use_container_width=True)

    weekly = weekly_total_volume(filtered)
    frequency = workout_frequency(filtered)
    top_volume = top_exercises_by_volume(filtered, limit=10)
    e1rm = estimated_1rm_by_exercise(filtered)
    exercise_volume = volume_by_exercise(filtered)
    prs = pr_tracker(filtered)

    section_header("Volume & Frequency")
    left, right = st.columns(2)
    with left:
        st.plotly_chart(line_weekly_volume(weekly), use_container_width=True)
    with right:
        st.plotly_chart(line_workout_frequency(frequency), use_container_width=True)

    section_header("Exercise Breakdown")
    left, right = st.columns(2)
    with left:
        st.plotly_chart(bar_top_exercises(top_volume), use_container_width=True)
    with right:
        st.plotly_chart(scatter_estimated_1rm(e1rm), use_container_width=True)

    section_header("Muscle Group Breakdown")
    mg_vol = muscle_group_volume(filtered)
    weekly_mg = weekly_muscle_group_volume(filtered)

    left, right = st.columns(2)
    with left:
        st.plotly_chart(bar_muscle_group_volume(mg_vol), use_container_width=True)
    with right:
        st.plotly_chart(heatmap_weekly_muscle_volume(weekly_mg), use_container_width=True)

    section_header("PR Timeline")
    exercises_with_data = sorted(
        filtered.dropna(subset=["Weight", "Reps"])["Exercise"].dropna().unique().tolist()
    )
    if not exercises_with_data:
        st.info("No exercises with weight/rep data in the current filter.")
    else:
        selected_ex = st.selectbox("Select exercise", exercises_with_data, key="pr_exercise")
        time_df = estimated_1rm_over_time(filtered, selected_ex)

        if not time_df.empty:
            best_1rm = time_df["Estimated1RM"].max()
            best_date = time_df.loc[time_df["Estimated1RM"].idxmax(), "Date"]
            pr_count = int(time_df["IsPR"].sum())
            c1, c2, c3 = st.columns(3)
            c1.metric(
                "All-time best e1RM",
                f"{best_1rm:,.1f} lbs",
                help=f"Set on {best_date.date() if hasattr(best_date, 'date') else best_date}",
            )
            c2.metric("Sessions tracked", len(time_df))
            c3.metric("PRs set", pr_count)

        st.plotly_chart(scatter_1rm_timeline(time_df, selected_ex), use_container_width=True)

    render_daily_workout_detail(df, filtered)

    section_header("Data Tables")
    tab1, tab2, tab3 = st.tabs(["Volume by Exercise", "PR Tracker", "Raw Data"])
    with tab1:
        st.dataframe(exercise_volume, use_container_width=True, hide_index=True)
    with tab2:
        st.dataframe(prs, use_container_width=True, hide_index=True)
    with tab3:
        st.dataframe(filtered, use_container_width=True, hide_index=True)


_CORR_LABELS: dict[str, str] = {
    "daily_volume": "Volume (lbs)",
    "daily_best_e1rm": "Best e1RM (lbs)",
    "daily_sets": "Sets",
    "body_weight_lbs": "Body Weight",
    "steps": "Daily Steps",
    "resting_hr": "Resting HR",
    "active_calories": "Active Cal",
    "hrv": "HRV (ms)",
    "sleep_hours": "Sleep Hrs",
    "sleep_quality_pct": "Sleep Quality %",
    "calories_in": "Cal Intake",
}


def _has_col(df: pd.DataFrame, col: str) -> bool:
    return df is not None and col in df.columns and df[col].notna().any()


def render_correlations(workout_df: pd.DataFrame, health_df: pd.DataFrame | None) -> None:
    daily_w = daily_workout_metrics(workout_df)
    daily_w["date"] = pd.to_datetime(daily_w["date"])

    has_health = health_df is not None and not health_df.empty
    if has_health:
        merged = daily_w.merge(health_df, on="date", how="outer").sort_values("date").reset_index(drop=True)
    else:
        merged = daily_w.copy()

    section_header("Body Composition vs Strength")
    if _has_col(merged, "body_weight_lbs") and _has_col(merged, "daily_best_e1rm"):
        st.plotly_chart(
            dual_axis_line(merged, "date", "body_weight_lbs", "daily_best_e1rm",
                           "Body Weight (lbs)", "Best e1RM (lbs)"),
            use_container_width=True,
        )
    else:
        placeholder_card(
            "Body Weight vs Estimated 1RM over time",
            "Upload Apple Health export to compare body weight trends with strength progress",
        )

    section_header("Activity & Nutrition Correlations")
    left, right = st.columns(2)

    with left:
        if _has_col(merged, "steps") and _has_col(merged, "daily_volume"):
            st.plotly_chart(
                scatter_with_r2(merged, "steps", "daily_volume",
                                "Daily Steps", "Training Volume (lbs)"),
                use_container_width=True,
            )
        else:
            placeholder_card("Daily Steps vs Workout Volume", "Requires step count data from Apple Health")

    with right:
        if _has_col(merged, "calories_in") and _has_col(merged, "daily_volume"):
            cal = merged.set_index("date")["calories_in"].dropna()
            vol = merged.set_index("date")["daily_volume"]
            lag_rows = [
                {"calories_in": c, "next_day_volume": vol.get(d + pd.Timedelta(days=1))}
                for d, c in cal.items()
            ]
            lag_df = pd.DataFrame(lag_rows).dropna()
            if not lag_df.empty:
                st.plotly_chart(
                    scatter_with_r2(lag_df, "calories_in", "next_day_volume",
                                    "Caloric Intake (kcal)", "Next-Day Volume (lbs)"),
                    use_container_width=True,
                )
            else:
                placeholder_card("Caloric Intake vs Next-Day Volume", "No overlapping calorie + workout days found")
        else:
            placeholder_card(
                "Caloric Intake vs Next-Day Volume (lagged)",
                "Requires dietary calorie data synced to Apple Health (e.g. MyFitnessPal)",
            )

    section_header("Sleep vs Performance")
    left, right = st.columns(2)

    with left:
        if _has_col(merged, "sleep_hours") and _has_col(merged, "daily_volume"):
            sub = merged[["sleep_hours", "daily_volume"]].dropna()
            st.plotly_chart(
                scatter_with_r2(sub, "sleep_hours", "daily_volume",
                                "Sleep Duration (hrs)", "Training Volume (lbs)"),
                use_container_width=True,
            )
        else:
            placeholder_card("Sleep Duration vs Training Volume", "Requires sleep data from Apple Health")

    with right:
        if _has_col(merged, "sleep_hours") and _has_col(merged, "daily_best_e1rm"):
            sub = merged[["sleep_hours", "daily_best_e1rm"]].dropna()
            st.plotly_chart(
                scatter_with_r2(sub, "sleep_hours", "daily_best_e1rm",
                                "Sleep Duration (hrs)", "Best e1RM (lbs)"),
                use_container_width=True,
            )
        else:
            placeholder_card("Sleep Duration vs Estimated 1RM", "Requires sleep data from Apple Health")

    section_header("Full Correlation Matrix")
    available = [c for c in _CORR_LABELS if c in merged.columns and merged[c].notna().sum() >= 4]

    if len(available) >= 3:
        corr_data = merged[available].rename(columns={c: _CORR_LABELS[c] for c in available})
        st.plotly_chart(correlation_heatmap(corr_data.corr()), use_container_width=True)
    else:
        placeholder_card(
            "Correlation Matrix — all metrics",
            "Connect Apple Health to populate health columns and unlock the full heatmap",
        )


_GRADE_COLORS: dict[str, str] = {
    "A+": "#e8890c", "A": "#e8890c",
    "B+": "#4ade80", "B": "#4ade80",
    "C": "#f59e0b", "D": "#ef4444", "F": "#ef4444",
}


def render_today_grade(df: pd.DataFrame) -> None:
    section_header("Today's Session Grade")
    g = grade_session(df)
    if not g["session_found"]:
        st.info("No session data available for grading.")
        return

    color = _GRADE_COLORS.get(g["grade"], "#888890")
    date_str = pd.Timestamp(g["date"]).strftime("%b %d, %Y") if g["date"] else ""

    col_letter, col_details = st.columns([1, 3])
    with col_letter:
        st.markdown(
            f"""
            <div style="text-align:center;padding:1.5rem 1rem;background:#111113;
                        border:1px solid #1e1e22;border-left:4px solid {color};border-radius:4px;">
              <div style="font-family:'Bebas Neue',cursive;font-size:5rem;line-height:1;color:{color};">
                {g['grade']}
              </div>
              <div style="font-size:0.75rem;color:#888890;letter-spacing:0.15em;margin-top:0.4rem;">
                {g['score']}/100
              </div>
              <div style="font-size:0.6rem;color:#444450;margin-top:0.35rem;letter-spacing:0.1em;">
                {date_str}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_details:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Consistency (35%)", f"{g['consistency_score']:.0f}")
        c2.metric("Strength (30%)", f"{g['strength_score']:.0f}")
        c3.metric("Rep Range (20%)", f"{g['rep_adherence_score']:.0f}")
        c4.metric("Volume (15%)", f"{g['volume_score']:.0f}")
        st.markdown(
            f"<p style='color:#888890;font-size:0.78rem;margin-top:0.6rem;"
            f"font-style:italic;'>{escape(g['coaching_comment'])}</p>",
            unsafe_allow_html=True,
        )
        if g["best_lift"]:
            bl = g["best_lift"]
            st.success(f"Best lift: **{bl['exercise']}** — e1RM {bl['e1rm']} lbs")
        if g["worst_lift"]:
            wl = g["worst_lift"]
            st.warning(f"Needs work: **{wl['exercise']}** — {wl['delta_pct']:+.1f}% vs previous")
        if g["muscle_groups"]:
            st.caption("Muscle groups: " + ", ".join(str(m).title() for m in g["muscle_groups"]))


def render_sessions_history(df: pd.DataFrame) -> None:
    section_header("Past 30 Sessions")
    history = grade_sessions_history(df, limit=30)
    if history.empty:
        st.info("Not enough session history to build grade table.")
        return

    left, right = st.columns([3, 2])
    with left:
        def _row_style(row: pd.Series) -> list[str]:
            g = str(row.get("Grade", ""))
            if g in ("D", "F"):
                return ["background-color: rgba(239,68,68,0.12);"] * len(row)
            if g == "C":
                return ["background-color: rgba(245,158,11,0.10);"] * len(row)
            return [""] * len(row)

        display = history.drop(columns=["_grade_group"], errors="ignore").copy()
        display["Date"] = display["Date"].dt.strftime("%Y-%m-%d")
        display["Score"] = display["Score"].map(lambda x: f"{float(x):.1f}")
        styled = display.style.apply(_row_style, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)
    with right:
        st.plotly_chart(bar_grade_distribution(history), use_container_width=True)


def render_weekly_grade_cards(df: pd.DataFrame, checkins: pd.DataFrame) -> None:
    section_header("Weekly Grades")
    weeks = weekly_grade(df, checkins, num_weeks=4)
    if not weeks:
        st.info("Not enough data for weekly grades yet.")
        return

    for w in weeks:
        color = _GRADE_COLORS.get(str(w["grade"]), "#888890")
        vol_arrow = ""
        if w["volume_change_pct"] is not None:
            pct = float(w["volume_change_pct"])
            vol_arrow = f" ({pct:+.0f}%)"

        body_parts: list[str] = []
        if w["retention_score"] is not None:
            body_parts.append(f"Strength retention: <b>{w['retention_score']}%</b>")
        if w["recovery_score"] is not None:
            body_parts.append(f"Recovery score: <b>{w['recovery_score']}/100</b>")
        if w["covered_2x"]:
            covered = ", ".join(str(m).title() for m in w["covered_2x"])
            body_parts.append(f"2× frequency: {covered}")

        container_html = (
            f"<div style='background:#111113;border:1px solid #1e1e22;"
            f"border-left:4px solid {color};border-radius:4px;"
            f"padding:1rem 1.2rem;margin-bottom:0.75rem;'>"
            f"<div style='display:flex;align-items:center;gap:1rem;margin-bottom:0.4rem;'>"
            f"<span style='font-family:\"Bebas Neue\",cursive;font-size:2.2rem;"
            f"color:{color};line-height:1;'>{w['grade']}</span>"
            f"<span style='font-size:0.72rem;color:#888890;'>"
            f"Week of {w['week_start']} &nbsp;·&nbsp; "
            f"{w['sessions']} session(s) &nbsp;·&nbsp; "
            f"{w['volume']:,} lbs{vol_arrow}"
            f"</span></div>"
            + (
                f"<div style='font-size:0.72rem;color:#666672;margin-bottom:0.4rem;'>"
                + " &nbsp;·&nbsp; ".join(body_parts)
                + "</div>"
                if body_parts else ""
            )
            + f"<p style='font-size:0.75rem;color:#888890;font-style:italic;margin:0;'>"
            f"{escape(str(w['coaching_summary']))}</p>"
            f"</div>"
        )
        st.markdown(container_html, unsafe_allow_html=True)


def render_grades_page(df: pd.DataFrame, checkins: pd.DataFrame) -> None:
    render_today_grade(df)
    render_sessions_history(df)
    render_weekly_grade_cards(df, checkins)


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

    st.sidebar.markdown("## Navigation")
    page = st.sidebar.radio("", ["Coach", "Dashboard", "Grades", "Correlations"], label_visibility="collapsed")
    st.sidebar.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

    health_df = health_uploader()

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
        render_coach_page(df, checkins, health_df, spreadsheet_id)
    elif page == "Dashboard":
        render_dashboard(df, checkins)
    elif page == "Grades":
        render_grades_page(df, checkins)
    else:
        filtered = filter_frame(df)
        render_correlations(filtered, health_df)


if __name__ == "__main__":
    main()
