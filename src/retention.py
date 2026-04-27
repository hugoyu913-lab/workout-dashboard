from __future__ import annotations

from typing import Collection

import pandas as pd


def strength_retention_score(
    df: pd.DataFrame,
    weeks: int = 3,
    deload_dates: Collection[pd.Timestamp] | None = None,
) -> dict[str, object]:
    empty: dict[str, object] = {
        "score": 0,
        "improved_pct": 0.0,
        "maintained_pct": 0.0,
        "regressed_pct": 0.0,
        "interpretation": "Not enough recent strength data to score retention.",
        "exercise_count": 0,
    }
    if df.empty or "Date" not in df.columns or "Exercise" not in df.columns:
        return empty

    work = df.dropna(subset=["Date", "Exercise", "Weight", "Reps"]).copy()
    if work.empty:
        return empty

    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date"])
    if work.empty:
        return empty

    if deload_dates:
        deload_weeks = {pd.Timestamp(d).to_period("W") for d in deload_dates}
        work = work[~work["Date"].dt.to_period("W").isin(deload_weeks)].copy()

    latest_date = work["Date"].max()
    cutoff = latest_date - pd.Timedelta(weeks=weeks)
    recent = work[work["Date"] >= cutoff].copy()
    if recent.empty:
        return empty

    recent["Estimated1RM"] = recent["Weight"] * (1 + recent["Reps"] / 30)
    statuses: list[str] = []
    for exercise, group in recent.groupby("Exercise"):
        ordered = group.sort_values("Date")
        dates = ordered["Date"].dt.date.unique()
        if len(dates) < 2:
            continue  # require 2+ distinct session dates

        latest_ex_date = ordered["Date"].max().date()
        current = ordered[ordered["Date"].dt.date == latest_ex_date]
        previous = ordered[ordered["Date"].dt.date < latest_ex_date]
        if previous.empty:
            continue

        current_best = current["Estimated1RM"].max()
        previous_best = previous["Estimated1RM"].max()
        if pd.isna(current_best) or pd.isna(previous_best) or previous_best <= 0:
            continue

        ratio = current_best / previous_best
        if ratio > 1.005:
            statuses.append("Improved")
        elif ratio < 0.98:
            statuses.append("Regressed")
        else:
            statuses.append("Maintained")

    exercises_with_history = len(statuses)
    if exercises_with_history == 0:
        return empty

    improved = statuses.count("Improved")
    maintained = statuses.count("Maintained")
    improved_pct = improved / exercises_with_history * 100
    maintained_pct = maintained / exercises_with_history * 100
    regressed_pct = statuses.count("Regressed") / exercises_with_history * 100
    score = round((improved + maintained * 0.7) / exercises_with_history * 100)

    if score >= 85:
        interpretation = "Strength retention is excellent for a cut."
    elif score >= 70:
        interpretation = "Strength is mostly maintained; monitor any regressions."
    elif score >= 50:
        interpretation = "Strength retention is mixed; recovery or effort may need adjustment."
    else:
        interpretation = "Strength retention is poor; reduce fatigue and prioritize key lifts."

    return {
        "score": score,
        "improved_pct": improved_pct,
        "maintained_pct": maintained_pct,
        "regressed_pct": regressed_pct,
        "interpretation": interpretation,
        "exercise_count": exercises_with_history,
    }
