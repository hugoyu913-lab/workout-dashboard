from __future__ import annotations

import os
from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from src.apple_health import render_uploader as health_uploader
from src.charts import (
    bar_muscle_group_volume,
    bar_top_exercises,
    correlation_heatmap,
    dual_axis_line,
    heatmap_weekly_muscle_volume,
    line_weekly_volume,
    line_workout_frequency,
    scatter_1rm_timeline,
    scatter_estimated_1rm,
    scatter_with_r2,
)
from src.cleaner import clean_workout_log
from src.insights import build_weekly_insights
from src.metrics import (
    daily_workout_metrics,
    estimated_1rm_by_exercise,
    estimated_1rm_over_time,
    muscle_group_volume,
    pr_tracker,
    top_exercises_by_volume,
    volume_by_exercise,
    weekly_muscle_group_volume,
    weekly_total_volume,
    workout_frequency,
)
from src.sheets_client import (
    DEFAULT_SPREADSHEET_ID,
    GoogleSheetsError,
    get_credentials_client_email,
    load_all_worksheets,
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


@st.cache_data(ttl=600, show_spinner=False)
def load_data(spreadsheet_id: str) -> pd.DataFrame:
    raw = load_all_worksheets(spreadsheet_id)
    return clean_workout_log(raw)


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


def render_weekly_insights(df: pd.DataFrame) -> None:
    insights = build_weekly_insights(df)
    balance = insights["balance"]
    muscle_group_volume = insights["muscle_group_volume"] or ["No muscle group volume this week."]
    undertrained = insights.get("undertrained_muscle_groups") or ["No undertrained muscle groups detected."]
    recommendations = insights.get("recommendations") or [insights["suggested_focus"]]
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
        st.markdown(f"<ul>{_insight_list(muscle_group_volume)}</ul>", unsafe_allow_html=True)
    with c4:
        st.markdown("##### Push/Pull/Legs")
        st.metric("Push", f"{balance['push']:.0f}%")
        st.metric("Pull", f"{balance['pull']:.0f}%")
        st.metric("Legs", f"{balance['legs']:.0f}%")
        st.caption(balance_summary)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Undertrained")
        st.markdown(f"<ul>{_insight_list(undertrained)}</ul>", unsafe_allow_html=True)
    with c2:
        st.markdown("##### Recommendations")
        st.markdown(f"<ul>{_insight_list(recommendations)}</ul>", unsafe_allow_html=True)


def render_dashboard(df: pd.DataFrame) -> None:
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

    render_weekly_insights(filtered)

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

    # ── 1. Body weight vs e1RM over time ──────────────────────────────
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

    # ── 2. Steps vs volume  /  Caloric intake vs next-day volume ──────
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
            placeholder_card(
                "Daily Steps vs Workout Volume",
                "Requires step count data from Apple Health",
            )

    with right:
        if _has_col(merged, "calories_in") and _has_col(merged, "daily_volume"):
            # Lag: for each calorie date look up volume on the next calendar day
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
                placeholder_card("Caloric Intake vs Next-Day Volume",
                                  "No overlapping calorie + workout days found")
        else:
            placeholder_card(
                "Caloric Intake vs Next-Day Volume (lagged)",
                "Requires dietary calorie data synced to Apple Health (e.g. MyFitnessPal)",
            )

    # ── 3. Sleep vs volume / e1RM ─────────────────────────────────────
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
            placeholder_card("Sleep Duration vs Training Volume",
                              "Requires sleep data from Apple Health")

    with right:
        if _has_col(merged, "sleep_hours") and _has_col(merged, "daily_best_e1rm"):
            sub = merged[["sleep_hours", "daily_best_e1rm"]].dropna()
            st.plotly_chart(
                scatter_with_r2(sub, "sleep_hours", "daily_best_e1rm",
                                "Sleep Duration (hrs)", "Best e1RM (lbs)"),
                use_container_width=True,
            )
        else:
            placeholder_card("Sleep Duration vs Estimated 1RM",
                              "Requires sleep data from Apple Health")

    # ── 4. Full correlation matrix ─────────────────────────────────────
    section_header("Full Correlation Matrix")
    available = [c for c in _CORR_LABELS if c in merged.columns and merged[c].notna().sum() >= 4]

    if len(available) >= 3:
        corr_data = (
            merged[available]
            .rename(columns={c: _CORR_LABELS[c] for c in available})
        )
        st.plotly_chart(
            correlation_heatmap(corr_data.corr()),
            use_container_width=True,
        )
    else:
        placeholder_card(
            "Correlation Matrix — all metrics",
            "Connect Apple Health to populate health columns and unlock the full heatmap",
        )


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

    # ── Page navigation ───────────────────────────────────────────────
    st.sidebar.markdown("## Navigation")
    page = st.sidebar.radio(
        "",
        ["Dashboard", "Correlations"],
        label_visibility="collapsed",
    )
    st.sidebar.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

    # ── Apple Health uploader ─────────────────────────────────────────
    health_df = health_uploader()

    # ── Workout data ──────────────────────────────────────────────────
    spreadsheet_id = st.sidebar.text_input(
        "Google Spreadsheet ID",
        value=os.getenv("WORKOUT_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID),
    )
    client_email = get_credentials_client_email()
    st.sidebar.caption(f"Service account: {client_email or 'credentials not found'}")
    st.sidebar.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    if st.sidebar.button("↺  Refresh Data"):
        load_data.clear()

    try:
        with st.spinner("Loading workout data..."):
            df = load_data(spreadsheet_id)
    except GoogleSheetsError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.exception(exc)
        st.stop()

    if df.empty:
        st.warning("No usable workout rows were found after cleaning.")
        st.stop()

    if page == "Dashboard":
        render_dashboard(df)
    else:
        filtered = filter_frame(df)
        render_correlations(filtered, health_df)


if __name__ == "__main__":
    main()
