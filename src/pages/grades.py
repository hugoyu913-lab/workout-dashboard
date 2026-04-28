from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from src.charts import bar_grade_distribution
from src.metrics import (
    build_session_feedback,
    grade_session,
    grade_sessions_history,
    session_exercise_drilldown,
    weekly_grade,
)
from src.pages.dashboard import section_header

_GRADE_COLORS: dict[str, str] = {
    "A+": "#e8890c", "A": "#e8890c",
    "B+": "#4ade80", "B": "#4ade80",
    "C": "#f59e0b", "D": "#ef4444", "F": "#ef4444",
}


def _grade_card(title: str, body: str, color: str = "#e8890c") -> str:
    return f"""
    <div style="background:#111113;border:1px solid #1e1e22;border-left:4px solid {color};
                border-radius:4px;padding:1rem 1.1rem;min-height:132px;">
      <div style="font-family:'Bebas Neue',cursive;font-size:1.05rem;letter-spacing:0.12em;
                  color:#f0f0f2;margin-bottom:0.55rem;">{escape(title)}</div>
      <div style="font-size:0.72rem;color:#c8c8cc;line-height:1.55;">{body}</div>
    </div>
    """


def _feedback_list(items: list[str]) -> str:
    return "<ul style='margin:0;padding-left:1.1rem;'>" + "".join(
        f"<li>{escape(str(item))}</li>" for item in items
    ) + "</ul>"


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
        c2.metric("Strength (40%)", f"{g['strength_score']:.0f}")
        c3.metric("Rep Range (20%)", f"{g['rep_adherence_score']:.0f}")
        c4.metric("Volume (5%)", f"{g['volume_score']:.0f}")
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


def render_sessions_history(df: pd.DataFrame) -> pd.Timestamp | None:
    section_header("Past 30 Sessions")
    history = grade_sessions_history(df, limit=30)
    if history.empty:
        st.info("Not enough session history to build grade table.")
        return None

    left, right = st.columns([3, 2])
    selected_from_table: pd.Timestamp | None = None
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
        try:
            event = st.dataframe(
                styled,
                use_container_width=True,
                hide_index=True,
                key="grade_history_table",
                on_select="rerun",
                selection_mode="single-row",
            )
            if hasattr(event, "selection"):
                selected_rows = event.selection.rows
            elif isinstance(event, dict):
                selected_rows = event.get("selection", {}).get("rows", [])
            else:
                selected_rows = []
            if selected_rows:
                selected_from_table = pd.Timestamp(display.iloc[selected_rows[0]]["Date"])
        except TypeError:
            st.dataframe(styled, use_container_width=True, hide_index=True)
    with right:
        st.plotly_chart(bar_grade_distribution(history), use_container_width=True)
    return selected_from_table


def render_session_feedback_panel(df: pd.DataFrame, selected_date: object) -> None:
    section_header("Selected Session Feedback")
    feedback = build_session_feedback(df, selected_date)
    if not feedback["session_found"]:
        st.info("No session found for the selected date.")
        return

    grade = str(feedback["overall_grade"])
    color = _GRADE_COLORS.get(grade, "#888890")
    score = float(feedback["numeric_score"])
    selected_label = pd.Timestamp(selected_date).strftime("%b %d, %Y")

    top_left, top_right = st.columns([1, 3])
    with top_left:
        st.markdown(
            f"""
            <div style="text-align:center;padding:1.35rem 1rem;background:#111113;
                        border:1px solid #1e1e22;border-left:4px solid {color};border-radius:4px;">
              <div style="font-family:'Bebas Neue',cursive;font-size:4.6rem;line-height:1;color:{color};">
                {escape(grade)}
              </div>
              <div style="font-size:0.75rem;color:#888890;letter-spacing:0.15em;margin-top:0.35rem;">
                {score:.1f}/100
              </div>
              <div style="font-size:0.6rem;color:#444450;margin-top:0.35rem;letter-spacing:0.1em;">
                {escape(selected_label)}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with top_right:
        scores = feedback["category_scores"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Consistency", f"{scores['consistency']:.0f}")
        c2.metric("Strength", f"{scores['strength']:.0f}")
        c3.metric("Rep Range", f"{scores['rep_range']:.0f}")
        c4.metric("Volume", f"{scores['volume']:.0f}")

        detail_cols = st.columns(4)
        detail_cols[0].metric("Sets", f"{int(feedback['total_sets'])}")
        detail_cols[1].metric("Volume", f"{float(feedback['total_volume']):,.0f} lbs")
        detail_cols[2].caption("Best lift")
        detail_cols[2].markdown(f"**{escape(str(feedback['best_lift']))}**")
        detail_cols[3].caption("Needs work")
        detail_cols[3].markdown(f"**{escape(str(feedback['weakest_lift']))}**")
        muscle_groups = feedback["muscle_groups_trained"]
        if muscle_groups:
            st.caption("Muscle groups trained: " + ", ".join(str(m).title() for m in muscle_groups))

    cards = st.columns(4)
    cards[0].markdown(
        _grade_card(
            "Why This Grade?",
            "This score weights consistency, strength retention, rep-range adherence, and volume for a cutting phase.",
            color,
        ),
        unsafe_allow_html=True,
    )
    cards[1].markdown(
        _grade_card("What Went Well", _feedback_list(list(feedback["what_went_well"])), "#22c55e"),
        unsafe_allow_html=True,
    )
    cards[2].markdown(
        _grade_card("What To Improve", _feedback_list(list(feedback["what_needs_improvement"])), "#f59e0b"),
        unsafe_allow_html=True,
    )
    cards[3].markdown(
        _grade_card("Next Time Adjustment", escape(str(feedback["recommended_adjustment"])), "#e8890c"),
        unsafe_allow_html=True,
    )

    comparison = feedback["previous_comparison"]
    if comparison.get("previous_date") is not None:
        st.markdown("#### Previous Session Comparison")
        comp_cols = st.columns(4)
        comp_cols[0].metric("Volume", f"{float(comparison['volume_delta']):+,.0f} lbs")
        comp_cols[1].metric("Sets", f"{int(comparison['sets_delta']):+d}")
        comp_cols[2].metric("Score", f"{float(comparison['score_delta']):+.1f}")
        comp_cols[3].metric("Grade", str(comparison["grade_delta"]))

        improved = comparison.get("improved_categories") or []
        declined = comparison.get("declined_categories") or []
        if improved:
            st.success("Improved categories: " + ", ".join(str(x).replace("_", " ").title() for x in improved))
        if declined:
            st.warning("Declined categories: " + ", ".join(str(x).replace("_", " ").title() for x in declined))
    else:
        st.caption("No previous workout available for session-to-session comparison.")

    st.markdown("#### Exercise Drilldown")
    drilldown = session_exercise_drilldown(df, selected_date)
    if drilldown.empty:
        st.info("No exercise rows found for this session.")
    else:
        st.dataframe(drilldown, use_container_width=True, hide_index=True)


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
    valid_dates = df["Date"].dropna() if "Date" in df.columns else pd.Series(dtype="datetime64[ns]")
    if valid_dates.empty:
        st.info("No session dates available for grading.")
        return

    session_dates = sorted(pd.to_datetime(valid_dates).dt.date.unique(), reverse=True)
    labels = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in session_dates]
    selected_label = st.selectbox("Select session", labels, index=0, key="selected_grade_session")
    selected_date = pd.Timestamp(selected_label).date()

    selected_from_table = render_sessions_history(df)
    if selected_from_table is not None:
        selected_date = selected_from_table.date()
        st.caption(f"Selected from table: {selected_from_table.strftime('%Y-%m-%d')}")

    render_session_feedback_panel(df, selected_date)
    render_weekly_grade_cards(df, checkins)
