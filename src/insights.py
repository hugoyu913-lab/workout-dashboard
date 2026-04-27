from __future__ import annotations

import pandas as pd


MIN_SESSIONS_FOR_STATUS = 3
PROGRESSING_SCORE = 60
DECLINING_SCORE = 40
UNDERTRAINED_RATIO = 0.75


def _empty_insights() -> dict[str, object]:
    return {
        "week_label": "No training week selected",
        "weekly_score": 0,
        "top_progressing": ["No progression signal yet."],
        "stalled": ["No stalled exercises detected yet."],
        "declining": ["No declining exercises detected yet."],
        "exercise_scores": [],
        "muscle_group_volume": [],
        "undertrained_muscle_groups": [],
        "balance": {
            "push": 0.0,
            "pull": 0.0,
            "legs": 0.0,
            "summary": "No push/pull/legs balance signal yet.",
        },
        "recommendations": ["Log more complete workout data before changing next week's focus."],
        "suggested_focus": "Log more complete workout data before changing next week's focus.",
    }


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _format_delta(value: float, unit: str = "lbs") -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.0f} {unit}"


def _add_week(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(subset=["Date"]).copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date"])
    work["Week"] = work["Date"].dt.to_period("W").dt.start_time
    return work


def _session_exercise_stats(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(subset=["Date", "Exercise"]).copy()
    if work.empty:
        return pd.DataFrame()

    work["Estimated1RM"] = work["Weight"] * (1 + work["Reps"] / 30)
    group_cols = ["Date", "Exercise"]
    optional_cols = [col for col in ("MuscleGroup", "Category") if col in work.columns]

    return (
        work.groupby(group_cols, as_index=False)
        .agg(
            Weight=("Weight", "max"),
            Reps=("Reps", "max"),
            Estimated1RM=("Estimated1RM", "max"),
            Volume=("Volume", "sum"),
            Sets=("Set", "count"),
            **{col: (col, "first") for col in optional_cols},
        )
        .sort_values(["Exercise", "Date"])
    )


def _weekly_exercise_stats(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(subset=["Date", "Exercise"]).copy()
    if work.empty:
        return pd.DataFrame()
    work["Week"] = work["Date"].dt.to_period("W").dt.start_time
    work["Estimated1RM"] = work["Weight"] * (1 + work["Reps"] / 30)
    return (
        work.groupby(["Week", "Exercise"], as_index=False)
        .agg(
            Volume=("Volume", "sum"),
            BestEstimated1RM=("Estimated1RM", "max"),
            Sets=("Set", "count"),
        )
        .sort_values(["Week", "Exercise"])
    )


def _score_exercise_sessions(session_stats: pd.DataFrame) -> list[dict[str, object]]:
    scores: list[dict[str, object]] = []
    if session_stats.empty:
        return scores

    for exercise, group in session_stats.groupby("Exercise"):
        ordered = group.sort_values("Date").tail(6).reset_index(drop=True)
        sessions = len(ordered)
        if sessions < 2:
            continue

        previous = ordered.iloc[:-1]
        latest = ordered.iloc[-1]
        baseline_weight = previous["Weight"].dropna().tail(3).mean()
        baseline_reps = previous["Reps"].dropna().tail(3).mean()
        baseline_e1rm = previous["Estimated1RM"].dropna().tail(3).mean()

        weight_delta_pct = 0.0
        reps_delta_pct = 0.0
        e1rm_delta_pct = 0.0
        if pd.notna(baseline_weight) and baseline_weight > 0 and pd.notna(latest["Weight"]):
            weight_delta_pct = (float(latest["Weight"]) - float(baseline_weight)) / float(baseline_weight) * 100
        if pd.notna(baseline_reps) and baseline_reps > 0 and pd.notna(latest["Reps"]):
            reps_delta_pct = (float(latest["Reps"]) - float(baseline_reps)) / float(baseline_reps) * 100
        if pd.notna(baseline_e1rm) and baseline_e1rm > 0 and pd.notna(latest["Estimated1RM"]):
            e1rm_delta_pct = (float(latest["Estimated1RM"]) - float(baseline_e1rm)) / float(baseline_e1rm) * 100

        best_signal = max(weight_delta_pct, reps_delta_pct, e1rm_delta_pct)
        worst_signal = min(weight_delta_pct, reps_delta_pct, e1rm_delta_pct)
        score = _clamp(50 + best_signal * 7 + min(e1rm_delta_pct, 0) * 3)

        recent_e1rm = ordered["Estimated1RM"].dropna()
        recent_volume = ordered["Volume"].dropna()
        latest_not_best = len(recent_e1rm) >= MIN_SESSIONS_FOR_STATUS and recent_e1rm.iloc[-1] <= recent_e1rm.iloc[:-1].max() * 1.005
        volume_down = len(recent_volume) >= MIN_SESSIONS_FOR_STATUS and recent_volume.iloc[-1] < recent_volume.iloc[:-1].tail(3).mean() * 0.95

        if sessions >= MIN_SESSIONS_FOR_STATUS and worst_signal <= -5 and volume_down:
            status = "declining"
        elif score >= PROGRESSING_SCORE and best_signal >= 2:
            status = "progressing"
        elif sessions >= MIN_SESSIONS_FOR_STATUS and latest_not_best:
            status = "stalled"
        else:
            status = "stable"

        scores.append(
            {
                "exercise": str(exercise),
                "status": status,
                "score": round(score),
                "sessions": sessions,
                "weight_delta_pct": round(weight_delta_pct, 1),
                "reps_delta_pct": round(reps_delta_pct, 1),
                "e1rm_delta_pct": round(e1rm_delta_pct, 1),
                "latest_weight": float(latest["Weight"]) if pd.notna(latest["Weight"]) else None,
                "latest_reps": float(latest["Reps"]) if pd.notna(latest["Reps"]) else None,
                "latest_volume": float(latest["Volume"]) if pd.notna(latest["Volume"]) else 0.0,
            }
        )

    return sorted(scores, key=lambda row: (row["score"], row["latest_volume"]), reverse=True)


def _score_line(row: dict[str, object]) -> str:
    return (
        f"{row['exercise']}: {row['score']}/100, {row['status']} "
        f"(load {row['weight_delta_pct']:+.1f}%, reps {row['reps_delta_pct']:+.1f}%)."
    )


def _status_lines(scores: list[dict[str, object]], status: str, empty: str, limit: int = 5) -> list[str]:
    rows = [row for row in scores if row["status"] == status]
    if not rows:
        return [empty]
    return [_score_line(row) for row in rows[:limit]]


def _muscle_group_volume(latest: pd.DataFrame) -> list[str]:
    if "MuscleGroup" not in latest.columns:
        return []
    grouped = (
        latest.dropna(subset=["MuscleGroup"])
        .groupby("MuscleGroup", as_index=False)
        .agg(Volume=("Volume", "sum"), Sets=("Set", "count"))
        .sort_values("Volume", ascending=False)
    )
    return [f"{row.MuscleGroup}: {row.Volume:,.0f} lbs, {row.Sets:.0f} sets" for row in grouped.itertuples(index=False)]


def _undertrained_muscle_groups(work: pd.DataFrame, latest_week: pd.Timestamp) -> list[dict[str, object]]:
    if "MuscleGroup" not in work.columns:
        return []

    weekly = (
        work.dropna(subset=["MuscleGroup"])
        .groupby(["Week", "MuscleGroup"], as_index=False)
        .agg(Volume=("Volume", "sum"), Sets=("Set", "count"))
    )
    if weekly.empty:
        return []

    latest = weekly[weekly["Week"] == latest_week].set_index("MuscleGroup")
    baseline = (
        weekly[weekly["Week"] < latest_week]
        .groupby("MuscleGroup", as_index=True)
        .agg(BaselineVolume=("Volume", "median"), BaselineSets=("Sets", "median"))
    )
    if baseline.empty:
        return []

    undertrained = []
    for muscle_group, row in baseline.iterrows():
        current_volume = float(latest["Volume"].get(muscle_group, 0.0))
        current_sets = float(latest["Sets"].get(muscle_group, 0.0))
        baseline_volume = float(row["BaselineVolume"])
        baseline_sets = float(row["BaselineSets"])
        if baseline_volume <= 0:
            continue
        ratio = current_volume / baseline_volume
        if ratio < UNDERTRAINED_RATIO:
            set_gap = max(2, round(baseline_sets - current_sets))
            if ratio < 0.5:
                set_gap = max(set_gap, 6)
            elif ratio < UNDERTRAINED_RATIO:
                set_gap = max(set_gap, 4)
            undertrained.append(
                {
                    "muscle_group": str(muscle_group),
                    "current_volume": current_volume,
                    "baseline_volume": baseline_volume,
                    "current_sets": current_sets,
                    "baseline_sets": baseline_sets,
                    "ratio": round(ratio, 2),
                    "set_gap": int(set_gap),
                }
            )

    return sorted(undertrained, key=lambda row: row["ratio"])


def _movement_bucket(row: pd.Series) -> str:
    category = str(row.get("Category", "")).lower()
    muscle_group = str(row.get("MuscleGroup", "")).lower()
    if "leg" in muscle_group or category in {"squat", "leg press", "quad isolation", "hamstring isolation", "calves", "hip isolation"}:
        return "legs"
    if "pull" in category or muscle_group == "back" or category == "biceps":
        return "pull"
    if "push" in category or muscle_group in {"chest", "shoulders"} or category == "triceps":
        return "push"
    return "other"


def _push_pull_legs_balance(latest: pd.DataFrame) -> dict[str, object]:
    if latest.empty:
        return {
            "push": 0.0,
            "pull": 0.0,
            "legs": 0.0,
            "summary": "No push/pull/legs balance signal yet.",
        }

    work = latest.copy()
    work["Bucket"] = work.apply(_movement_bucket, axis=1)
    totals = work.groupby("Bucket")["Volume"].sum()
    tracked_total = float(totals.reindex(["push", "pull", "legs"]).fillna(0).sum())
    if tracked_total <= 0:
        return {
            "push": 0.0,
            "pull": 0.0,
            "legs": 0.0,
            "summary": "No push/pull/legs volume detected this week.",
        }

    percentages = {
        bucket: float(totals.get(bucket, 0.0) / tracked_total * 100)
        for bucket in ("push", "pull", "legs")
    }
    low = min(percentages, key=percentages.get)
    high = max(percentages, key=percentages.get)
    spread = percentages[high] - percentages[low]
    if spread <= 15:
        summary = "Push, pull, and legs are reasonably balanced."
    else:
        summary = f"{low.title()} is underrepresented relative to {high}."
    return {**percentages, "summary": summary, "spread": spread, "low_bucket": low}


def _weekly_training_score(
    scores: list[dict[str, object]],
    undertrained: list[dict[str, object]],
    balance: dict[str, object],
) -> int:
    if not scores:
        return 0

    avg_exercise_score = sum(float(row["score"]) for row in scores) / len(scores)
    progressing_count = sum(1 for row in scores if row["status"] == "progressing")
    declining_count = sum(1 for row in scores if row["status"] == "declining")
    stalled_count = sum(1 for row in scores if row["status"] == "stalled")
    balance_penalty = min(20.0, float(balance.get("spread", 0.0)) * 0.4)
    undertrained_penalty = min(20.0, len(undertrained) * 6.0)
    status_bonus = min(10.0, progressing_count * 2.0)
    status_penalty = declining_count * 5.0 + stalled_count * 2.0

    return round(_clamp(avg_exercise_score + status_bonus - status_penalty - balance_penalty - undertrained_penalty))


def _recommendations(
    scores: list[dict[str, object]],
    undertrained: list[dict[str, object]],
    balance: dict[str, object],
) -> list[str]:
    recommendations: list[str] = []

    for item in undertrained[:3]:
        sets_needed = int(item["set_gap"])
        lower = max(2, sets_needed)
        upper = lower + 4
        recommendations.append(
            f"Increase {item['muscle_group']} volume by {lower}-{upper} sets next week."
        )

    for row in [item for item in scores if item["status"] == "stalled"][:3]:
        recommendations.append(
            f"{row['exercise']} has stalled for {row['sessions']} sessions - consider reducing load or increasing reps."
        )

    for row in [item for item in scores if item["status"] == "declining"][:2]:
        recommendations.append(
            f"{row['exercise']} is declining - reduce fatigue, lower load 5-10%, and rebuild reps."
        )

    if not recommendations:
        low_bucket = str(balance.get("low_bucket", "pull"))
        recommendations.append(
            f"Keep progressing top lifts and add 2-4 sets of {low_bucket} work to maintain balance."
        )

    return recommendations[:6]


def build_weekly_insights(df: pd.DataFrame) -> dict[str, object]:
    if df.empty or "Date" not in df.columns:
        return _empty_insights()

    work = _add_week(df)
    if work.empty:
        return _empty_insights()

    latest_week = work["Week"].max()
    latest = work[work["Week"] == latest_week].copy()
    session_stats = _session_exercise_stats(work)
    weekly_stats = _weekly_exercise_stats(work)

    scores = _score_exercise_sessions(session_stats)
    progressing = _status_lines(scores, "progressing", "No progressing exercises detected yet.")
    stalled = _status_lines(scores, "stalled", "No stalled exercises detected yet.")
    declining = _status_lines(scores, "declining", "No declining exercises detected yet.")
    muscle_groups = _muscle_group_volume(latest)
    undertrained = _undertrained_muscle_groups(work, latest_week)
    balance = _push_pull_legs_balance(latest)
    training_score = _weekly_training_score(scores, undertrained, balance)
    recommendations = _recommendations(scores, undertrained, balance)

    if weekly_stats.empty and not scores:
        fallback = _empty_insights()
        fallback["week_label"] = f"Week of {latest_week.strftime('%b %d, %Y')}"
        return fallback

    return {
        "week_label": f"Week of {latest_week.strftime('%b %d, %Y')}",
        "weekly_score": training_score,
        "top_progressing": progressing,
        "stalled": stalled,
        "declining": declining,
        "exercise_scores": scores[:10],
        "muscle_group_volume": muscle_groups,
        "undertrained_muscle_groups": [
            (
                f"{row['muscle_group']}: {row['current_volume']:,.0f} lbs vs "
                f"{row['baseline_volume']:,.0f} lbs baseline ({row['ratio']:.0%})."
            )
            for row in undertrained
        ],
        "balance": balance,
        "recommendations": recommendations,
        "suggested_focus": recommendations[0],
    }
