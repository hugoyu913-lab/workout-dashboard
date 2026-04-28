from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config.profile import (
    DAILY_CARBS_TARGET,
    DAILY_FAT_TARGET,
    DAILY_PROTEIN_TARGET,
    DAILY_SLEEP_TARGET,
    DAILY_STEPS_GOAL,
)

_ACCENT = "#e8890c"
_ACCENT2 = "#f0c040"
_FONT = "IBM Plex Mono, monospace"

_GROUP_COLORS = {
    "chest": "#60a5fa",
    "back": "#4ade80",
    "shoulders": "#fb923c",
    "arms": "#f87171",
    "legs": "#2dd4bf",
    "core": "#fbbf24",
    "other": "#c084fc",
}

_CATEGORY_COLORS = {
    "horizontal push": "#60a5fa",
    "vertical push": "#38bdf8",
    "incline push": "#818cf8",
    "horizontal pull": "#4ade80",
    "vertical pull": "#22c55e",
    "pullover": "#84cc16",
    "biceps": "#f87171",
    "triceps": "#fb7185",
    "lateral delt": "#fb923c",
    "rear delt": "#fdba74",
    "leg press": "#2dd4bf",
    "squat": "#14b8a6",
    "quad isolation": "#5eead4",
    "hamstring isolation": "#0f766e",
    "calves": "#99f6e4",
    "hip isolation": "#67e8f9",
    "core": "#fbbf24",
    "strength": "#c084fc",
    "other": "#a3a3a3",
}

_BASE_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(20,20,22,0.6)",
    font=dict(family=_FONT, color="#888890", size=11),
    xaxis=dict(
        gridcolor="#1e1e22",
        linecolor="#252528",
        tickfont=dict(color="#555560", size=10, family=_FONT),
        title_font=dict(color="#666670", family=_FONT),
        showgrid=True,
        zeroline=False,
    ),
    yaxis=dict(
        gridcolor="#1e1e22",
        linecolor="#252528",
        tickfont=dict(color="#555560", size=10, family=_FONT),
        title_font=dict(color="#666670", family=_FONT),
        showgrid=True,
        zeroline=False,
    ),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(color="#888890", size=10, family=_FONT),
        bordercolor="#252528",
        borderwidth=1,
    ),
    margin=dict(l=12, r=12, t=28, b=12),
    hoverlabel=dict(
        bgcolor="#1c1c20",
        bordercolor="#e8890c",
        font=dict(family=_FONT, color="#c8c8cc", size=11),
        namelength=-1,
    ),
)


def _apply_theme(fig: go.Figure) -> go.Figure:
    fig.update_layout(**_BASE_LAYOUT)
    return fig


def empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        showarrow=False,
        x=0.5, y=0.5,
        xref="paper", yref="paper",
        font=dict(color="#333338", size=13, family=_FONT),
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _apply_theme(fig)


def line_weekly_volume(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_figure("No weekly volume data")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["Week"],
        y=df["Volume"],
        mode="lines+markers",
        line=dict(color=_ACCENT, width=2.5),
        marker=dict(color=_ACCENT, size=5, line=dict(color="#0d0d0f", width=1.5)),
        fill="tozeroy",
        fillcolor="rgba(232,137,12,0.07)",
        hovertemplate="<b>%{x|%b %d}</b><br>Volume: %{y:,.0f} lbs<extra></extra>",
    ))
    return _apply_theme(fig)


def line_bodyweight_trend(df: pd.DataFrame) -> go.Figure:
    if df.empty or "Bodyweight" not in df.columns:
        return empty_figure("No bodyweight data")
    work = df.dropna(subset=["Date", "Bodyweight"]).copy()
    if work.empty:
        return empty_figure("No bodyweight data")
    work = work.sort_values("Date")
    work["Bodyweight7DayAvg"] = work["Bodyweight"].rolling(7, min_periods=1).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=work["Date"],
        y=work["Bodyweight"],
        mode="markers",
        marker=dict(color="rgba(96,165,250,0.45)", size=5),
        name="Daily",
        hovertemplate="%{x|%Y-%m-%d}<br>Bodyweight: %{y:.1f} lbs<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=work["Date"],
        y=work["Bodyweight7DayAvg"],
        mode="lines",
        line=dict(color=_ACCENT, width=2.5),
        name="7-day avg",
        hovertemplate="%{x|%Y-%m-%d}<br>7-day avg: %{y:.1f} lbs<extra></extra>",
    ))
    fig.update_layout(yaxis_title="Bodyweight (lbs)", xaxis_title="")
    return _apply_theme(fig)


def bar_checkin_steps(df: pd.DataFrame, days: int = 30) -> go.Figure:
    if df.empty or "Date" not in df.columns or "Steps" not in df.columns:
        return empty_figure("No steps check-in data")
    work = df.dropna(subset=["Date", "Steps"]).copy()
    if work.empty:
        return empty_figure("No steps check-in data")
    work = work.sort_values("Date").tail(days)
    fig = go.Figure(go.Bar(
        x=work["Date"],
        y=work["Steps"],
        marker=dict(color="#4ade80", line=dict(width=0)),
        hovertemplate="%{x|%Y-%m-%d}<br>Steps: %{y:,.0f}<extra></extra>",
        name="Steps",
    ))
    fig.add_hline(
        y=DAILY_STEPS_GOAL,
        line=dict(color=_ACCENT, width=1.5, dash="dot"),
        annotation_text=f"{DAILY_STEPS_GOAL:,}",
        annotation_font=dict(color=_ACCENT, size=10, family=_FONT),
    )
    fig.update_layout(yaxis_title="Steps", xaxis_title="")
    return _apply_theme(fig)


def bar_checkin_sleep(df: pd.DataFrame, days: int = 30) -> go.Figure:
    if df.empty or "Date" not in df.columns or "SleepHours" not in df.columns:
        return empty_figure("No sleep check-in data")
    work = df.dropna(subset=["Date", "SleepHours"]).copy()
    if work.empty:
        return empty_figure("No sleep check-in data")
    work = work.sort_values("Date").tail(days)
    fig = go.Figure(go.Bar(
        x=work["Date"],
        y=work["SleepHours"],
        marker=dict(color="#60a5fa", line=dict(width=0)),
        hovertemplate="%{x|%Y-%m-%d}<br>Sleep: %{y:.1f}h<extra></extra>",
        name="Sleep",
    ))
    fig.add_hline(
        y=DAILY_SLEEP_TARGET,
        line=dict(color=_ACCENT, width=1.5, dash="dot"),
        annotation_text=f"{DAILY_SLEEP_TARGET:g}h",
        annotation_font=dict(color=_ACCENT, size=10, family=_FONT),
    )
    fig.update_layout(yaxis_title="Sleep (hours)", xaxis_title="")
    return _apply_theme(fig)


def bar_checkin_macros(df: pd.DataFrame, days: int = 30) -> go.Figure:
    required = {"Date", "Protein", "Carbs", "Fat"}
    if df.empty or not required.issubset(df.columns):
        return empty_figure("No macro check-in data")
    work = df.dropna(subset=["Date"]).copy()
    if work.empty:
        return empty_figure("No macro check-in data")
    work = work.sort_values("Date").tail(days)
    long = work.melt(
        id_vars=["Date"],
        value_vars=["Protein", "Carbs", "Fat"],
        var_name="Macro",
        value_name="Grams",
    ).dropna(subset=["Grams"])
    if long.empty:
        return empty_figure("No macro check-in data")
    targets = {
        "Protein": DAILY_PROTEIN_TARGET,
        "Carbs": DAILY_CARBS_TARGET,
        "Fat": DAILY_FAT_TARGET,
    }
    long["Target"] = long["Macro"].map(targets)
    long["Adherence"] = long["Grams"] / long["Target"] * 100
    fig = px.bar(
        long,
        x="Date",
        y="Adherence",
        color="Macro",
        barmode="group",
        color_discrete_map={
            "Protein": "#4ade80",
            "Carbs": "#60a5fa",
            "Fat": "#f59e0b",
        },
        hover_data={"Grams": ":.0f", "Target": ":.0f", "Adherence": ":.0f"},
    )
    fig.add_hline(
        y=100,
        line=dict(color=_ACCENT, width=1.5, dash="dot"),
        annotation_text="target",
        annotation_font=dict(color=_ACCENT, size=10, family=_FONT),
    )
    fig.update_layout(yaxis_title="Macro target adherence (%)", xaxis_title="")
    return _apply_theme(fig)


def line_workout_frequency(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_figure("No workout frequency data")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["Week"],
        y=df["Workouts"],
        mode="lines+markers",
        line=dict(color="#60a5fa", width=2.5),
        marker=dict(color="#60a5fa", size=5, line=dict(color="#0d0d0f", width=1.5)),
        fill="tozeroy",
        fillcolor="rgba(96,165,250,0.07)",
        hovertemplate="<b>%{x|%b %d}</b><br>Workouts: %{y}<extra></extra>",
    ))
    return _apply_theme(fig)


def bar_top_exercises(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_figure("No exercise volume data")
    fig = go.Figure(go.Bar(
        x=df["Volume"],
        y=df["Exercise"],
        orientation="h",
        marker=dict(
            color=df["Volume"],
            colorscale=[[0, "#1c1c20"], [1, _ACCENT]],
            showscale=False,
            line=dict(width=0),
        ),
        hovertemplate="<b>%{y}</b><br>%{x:,.0f} lbs<extra></extra>",
    ))
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    return _apply_theme(fig)


def scatter_estimated_1rm(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_figure("No estimated 1RM data")
    fig = px.scatter(
        df, x="Exercise", y="Estimated1RM",
        size="Weight",
        hover_data=["Weight", "Reps", "Date"],
        color_discrete_sequence=[_ACCENT],
    )
    fig.update_traces(
        marker=dict(
            color=_ACCENT,
            line=dict(color="#0d0d0f", width=1),
            opacity=0.8,
        )
    )
    fig.update_layout(xaxis_tickangle=-40)
    return _apply_theme(fig)


def bar_muscle_group_volume(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_figure("No muscle group data")
    work = df.copy()
    work["MuscleGroup"] = work["MuscleGroup"].astype(str).str.lower()
    fig = px.bar(
        work,
        x="MuscleGroup",
        y="Volume",
        color="MuscleGroup",
        color_discrete_map=_GROUP_COLORS,
        labels={"MuscleGroup": "Muscle Group", "Volume": "Total Volume (lbs)"},
    )
    fig.update_traces(
        hovertemplate="<b>%{x}</b><br>%{y:,.0f} lbs<extra></extra>",
        marker_line_width=0,
    )
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Volume (lbs)")
    return _apply_theme(fig)


def bar_muscle_group_frequency(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_figure("No muscle group frequency data")
    work = df.copy()
    work["MuscleGroup"] = work["MuscleGroup"].astype(str).str.lower()
    fig = px.bar(
        work,
        x="MuscleGroup",
        y="Sessions Trained",
        color="MuscleGroup",
        color_discrete_map=_GROUP_COLORS,
        labels={"MuscleGroup": "Muscle Group", "Sessions Trained": "Sessions Trained"},
    )
    fig.update_traces(
        hovertemplate="<b>%{x}</b><br>Sessions: %{y}<extra></extra>",
        marker_line_width=0,
    )
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Sessions Trained")
    return _apply_theme(fig)


def bar_category_volume(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_figure("No category data")
    work = df.copy()
    work["Category"] = work["Category"].astype(str).str.lower()
    fig = px.bar(
        work,
        x="Category",
        y="Volume",
        color="Category",
        color_discrete_map=_CATEGORY_COLORS,
        labels={"Category": "Category", "Volume": "Total Volume (lbs)"},
    )
    fig.update_traces(
        hovertemplate="<b>%{x}</b><br>%{y:,.0f} lbs<extra></extra>",
        marker_line_width=0,
    )
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Volume (lbs)")
    return _apply_theme(fig)


def heatmap_weekly_muscle_volume(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_figure("No muscle group data")
    pivot = df.pivot_table(index="MuscleGroup", columns="Week", values="Volume", fill_value=0)

    def _fmt_week(c: object) -> str:
        if not hasattr(c, "strftime"):
            return str(c)
        return c.strftime("%b") + " " + str(c.day)

    pivot.columns = [_fmt_week(c) for c in pivot.columns]
    fig = px.imshow(
        pivot,
        labels={"x": "Week of", "y": "Muscle Group", "color": "Volume (lbs)"},
        aspect="auto",
        color_continuous_scale=[[0, "#111113"], [0.35, "#7a4800"], [1.0, _ACCENT]],
    )
    fig.update_layout(
        xaxis_tickangle=-45,
        coloraxis_colorbar=dict(
            title="lbs",
            tickfont=dict(color="#666670", size=9, family=_FONT),
            title_font=dict(color="#888890", size=10, family=_FONT),
            thickness=10,
        ),
    )
    return _apply_theme(fig)


def scatter_1rm_timeline(time_df: pd.DataFrame, exercise: str) -> go.Figure:
    if time_df.empty:
        return empty_figure(f"No data for {exercise}")

    prs = time_df[time_df["IsPR"]]
    non_prs = time_df[~time_df["IsPR"]]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=time_df["Date"],
        y=time_df["Estimated1RM"],
        mode="lines",
        line=dict(color="rgba(232,137,12,0.2)", width=1.5),
        showlegend=False,
        hoverinfo="skip",
    ))

    if not non_prs.empty:
        fig.add_trace(go.Scatter(
            x=non_prs["Date"],
            y=non_prs["Estimated1RM"],
            mode="markers",
            name="Session",
            marker=dict(
                color="rgba(96,165,250,0.75)",
                size=7,
                line=dict(color="#0d0d0f", width=1),
            ),
            hovertemplate="%{x|%Y-%m-%d}<br>e1RM: %{y:.1f} lbs<extra></extra>",
        ))

    if not prs.empty:
        fig.add_trace(go.Scatter(
            x=prs["Date"],
            y=prs["Estimated1RM"],
            mode="markers",
            name="PR",
            marker=dict(
                color=_ACCENT2,
                size=18,
                symbol="star",
                line=dict(color=_ACCENT, width=1.5),
            ),
            hovertemplate="%{x|%Y-%m-%d}<br><b>★ PR: %{y:.1f} lbs</b><extra></extra>",
        ))

    fig.update_layout(
        xaxis_title="",
        yaxis_title="Estimated 1RM (lbs)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    return _apply_theme(fig)


def line_session_quality(df: pd.DataFrame) -> go.Figure:
    if df.empty or "QualityScore" not in df.columns:
        return empty_figure("No session quality data yet")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["Date"],
        y=df["QualityScore"],
        mode="lines+markers",
        line=dict(color="#4ade80", width=2.5),
        marker=dict(color="#4ade80", size=5, line=dict(color="#0d0d0f", width=1.5)),
        fill="tozeroy",
        fillcolor="rgba(74,222,128,0.07)",
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Quality: %{y:.1f}/100<extra></extra>",
        name="Session Quality",
    ))
    fig.add_hline(
        y=70,
        line=dict(color="rgba(232,137,12,0.35)", width=1, dash="dot"),
        annotation_text="70",
        annotation_font=dict(color="#444450", size=10, family=_FONT),
    )
    fig.update_layout(yaxis_range=[0, 100], yaxis_title="Quality Score (0-100)", xaxis_title="")
    return _apply_theme(fig)


def bar_grade_distribution(history_df: pd.DataFrame) -> go.Figure:
    """Horizontal bar showing session count per grade bucket."""
    if history_df.empty or "Grade" not in history_df.columns:
        return empty_figure("No grade history yet")
    grade_order = ["A+", "A", "B+", "B", "C", "D", "F"]
    grade_color_map = {
        "A+": "#e8890c", "A": "#e8890c",
        "B+": "#4ade80", "B": "#4ade80",
        "C": "#f59e0b", "D": "#ef4444", "F": "#ef4444",
    }
    counts = history_df["Grade"].value_counts()
    # F at bottom → A+ at top for a horizontal bar
    grades = [g for g in reversed(grade_order) if g in counts.index]
    if not grades:
        return empty_figure("No grade history yet")
    values = [int(counts[g]) for g in grades]
    colors = [grade_color_map.get(g, "#888890") for g in grades]
    fig = go.Figure(go.Bar(
        x=values,
        y=grades,
        orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        text=[str(v) for v in values],
        textposition="outside",
        textfont=dict(color="#888890", size=11, family=_FONT),
        cliponaxis=False,
        hovertemplate="<b>%{y}</b>: %{x} session(s)<extra></extra>",
    ))
    fig = _apply_theme(fig)
    x_max = max(values) * 1.35 if values else 5
    fig.update_layout(
        xaxis=dict(title="Sessions", dtick=1, range=[0, x_max]),
        yaxis=dict(tickfont=dict(color="#c8c8cc", size=13, family=_FONT)),
        margin=dict(l=12, r=44, t=28, b=12),
    )
    return fig


