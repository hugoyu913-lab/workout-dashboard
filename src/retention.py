from __future__ import annotations

from typing import Collection

import pandas as pd

from config.profile import ANCHOR_LIFTS


def _normalise_exercise(name: str) -> str:
    return str(name).strip().lower()


def _anchor_lift_names() -> set[str]:
    if isinstance(ANCHOR_LIFTS, dict):
        anchors = [lift for lifts in ANCHOR_LIFTS.values() for lift in lifts]
    else:
        anchors = list(ANCHOR_LIFTS)
    return {_normalise_exercise(lift) for lift in anchors}


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
    statuses: list[tuple[str, bool]] = []
    anchor_names = _anchor_lift_names()
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
        is_anchor = _normalise_exercise(exercise) in anchor_names
        if ratio > 1.005:
            statuses.append(("Improved", is_anchor))
        elif ratio < 0.98:
            statuses.append(("Regressed", is_anchor))
        else:
            statuses.append(("Maintained", is_anchor))

    exercises_with_history = len(statuses)
    if exercises_with_history == 0:
        return empty

    improved = sum(1 for status, _ in statuses if status == "Improved")
    maintained = sum(1 for status, _ in statuses if status == "Maintained")
    regressed = sum(1 for status, _ in statuses if status == "Regressed")
    improved_pct = improved / exercises_with_history * 100
    maintained_pct = maintained / exercises_with_history * 100
    regressed_pct = regressed / exercises_with_history * 100
    weighted_total = sum(2.0 if is_anchor else 1.0 for _, is_anchor in statuses)
    weighted_score = 0.0
    for status, is_anchor in statuses:
        weight = 2.0 if is_anchor else 1.0
        if status == "Improved":
            weighted_score += weight
        elif status == "Maintained":
            weighted_score += weight * 0.7
    score = round(weighted_score / weighted_total * 100) if weighted_total else 0

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
