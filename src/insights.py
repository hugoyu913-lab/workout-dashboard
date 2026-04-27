from __future__ import annotations

import pandas as pd

from src.fatigue import fatigue_risk_detector
from src.recommendations import (
    build_next_workout,
    build_recommendations,
    build_suggested_exercises,
)
from src.retention import strength_retention_score

MIN_SESSIONS_FOR_STATUS = 3
TARGET_MIN_MUSCLE_FREQUENCY = 2
PROGRESSING_SCORE = 62
DECLINING_SCORE = 40


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
        "suggested_exercises": ["No exercise suggestions available yet."],
        "suggested_focus": "Log more complete workout data before changing next week's focus.",
    }


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


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

        latest = ordered.iloc[-1]
        previous = ordered.iloc[-2]
        recent = ordered.tail(3).reset_index(drop=True)

        weight_delta = 0.0
        reps_delta = 0.0
        e1rm_delta_pct = 0.0
        if pd.notna(latest["Weight"]) and pd.notna(previous["Weight"]):
            weight_delta = float(latest["Weight"]) - float(previous["Weight"])
        if pd.notna(latest["Reps"]) and pd.notna(previous["Reps"]):
            reps_delta = float(latest["Reps"]) - float(previous["Reps"])
        if (
            pd.notna(latest["Estimated1RM"])
            and pd.notna(previous["Estimated1RM"])
            and previous["Estimated1RM"] > 0
        ):
            e1rm_delta_pct = (
                (float(latest["Estimated1RM"]) - float(previous["Estimated1RM"]))
                / float(previous["Estimated1RM"])
                * 100
            )

        historical = ordered.iloc[:-1]
        best_weight = historical["Weight"].dropna().max()
        best_reps = historical["Reps"].dropna().max()
        best_e1rm = historical["Estimated1RM"].dropna().max()

        recent_weights = ordered["Weight"].dropna().tail(3).tolist()
        recent_reps = ordered["Reps"].dropna().tail(3).tolist()
        progressed_within_window = bool(
            len(recent_weights) >= 2 and max(recent_weights[1:]) > recent_weights[0]
        ) or bool(
            len(recent_reps) >= 2 and max(recent_reps[1:]) > recent_reps[0]
        )
        progressed_recently = bool(
            weight_delta > 0
            or reps_delta > 0
            or progressed_within_window
            or (pd.notna(best_weight) and pd.notna(latest["Weight"]) and latest["Weight"] > best_weight)
            or (pd.notna(best_reps) and pd.notna(latest["Reps"]) and latest["Reps"] > best_reps)
        )
        maintained_strength = bool(
            pd.notna(best_e1rm)
            and pd.notna(latest["Estimated1RM"])
            and latest["Estimated1RM"] >= best_e1rm * 0.98
        )
        immediate_regression = bool(
            pd.notna(latest["Estimated1RM"])
            and pd.notna(previous["Estimated1RM"])
            and latest["Estimated1RM"] < previous["Estimated1RM"] * 0.97
        )
        same_weight_reps_down = bool(
            pd.notna(latest["Weight"])
            and pd.notna(previous["Weight"])
            and abs(float(latest["Weight"]) - float(previous["Weight"])) < 0.01
            and reps_delta < 0
        )

        consecutive_drops = 0
        if len(recent) >= 3:
            e1rms = recent["Estimated1RM"].dropna().tolist()
            if len(e1rms) >= 3 and e1rms[-1] < e1rms[-2] < e1rms[-3]:
                consecutive_drops += 1
            if same_weight_reps_down:
                weights = recent["Weight"].dropna().tolist()
                reps = recent["Reps"].dropna().tolist()
                if (
                    len(weights) >= 3
                    and len(reps) >= 3
                    and max(weights) - min(weights) < 0.01
                    and reps[-1] < reps[-2] <= reps[-3]
                ):
                    consecutive_drops += 1

        score = 70.0
        if progressed_recently:
            score += 15.0
        elif maintained_strength:
            score += 6.0
        if immediate_regression:
            score -= 25.0
        if same_weight_reps_down:
            score -= 12.0
        if consecutive_drops:
            score -= 12.0 * consecutive_drops

        if immediate_regression or consecutive_drops or same_weight_reps_down:
            status = "declining"
        elif progressed_recently:
            status = "progressing"
        elif maintained_strength:
            status = "stable"
        elif sessions >= MIN_SESSIONS_FOR_STATUS:
            status = "stalled"
        else:
            status = "stable"

        scores.append({
            "exercise": str(exercise),
            "status": status,
            "score": round(_clamp(score)),
            "sessions": sessions,
            "weight_delta": round(weight_delta, 1),
            "reps_delta": round(reps_delta, 1),
            "e1rm_delta_pct": round(e1rm_delta_pct, 1),
            "maintained_strength": maintained_strength,
            "immediate_regression": immediate_regression,
            "same_weight_reps_down": same_weight_reps_down,
            "consecutive_drops": consecutive_drops,
            "muscle_group": str(latest.get("MuscleGroup", "other")).lower(),
            "category": str(latest.get("Category", "")).lower(),
            "latest_weight": float(latest["Weight"]) if pd.notna(latest["Weight"]) else None,
            "latest_reps": float(latest["Reps"]) if pd.notna(latest["Reps"]) else None,
            "latest_volume": float(latest["Volume"]) if pd.notna(latest["Volume"]) else 0.0,
        })

    return sorted(scores, key=lambda r: (r["score"], r["latest_volume"]), reverse=True)


def _score_line(row: dict[str, object]) -> str:
    if row["status"] == "progressing":
        return f"{row['exercise']}: {row['score']}/100, progressing (load {row['weight_delta']:+.1f} lbs, reps {row['reps_delta']:+.1f})."
    if row["status"] == "declining":
        return f"{row['exercise']}: {row['score']}/100, declining (e1RM {row['e1rm_delta_pct']:+.1f}%)."
    if row.get("maintained_strength"):
        return f"{row['exercise']}: strength maintained during cut - good."
    return f"{row['exercise']}: {row['score']}/100, {row['status']}."


def _status_lines(scores: list[dict[str, object]], status: str, empty: str, limit: int = 5) -> list[str]:
    rows = [r for r in scores if r["status"] == status]
    if not rows:
        return [empty]
    return [_score_line(r) for r in rows[:limit]]


def _muscle_group_volume(latest: pd.DataFrame) -> list[str]:
    if "MuscleGroup" not in latest.columns:
        return []
    grouped = (
        latest.dropna(subset=["MuscleGroup"])
        .groupby("MuscleGroup", as_index=False)
        .agg(Volume=("Volume", "sum"), Sets=("Set", "count"), Days=("Date", "nunique"))
        .sort_values("Days", ascending=False)
    )
    return [
        f"{row.MuscleGroup}: {row.Days:.0f} days, {row.Sets:.0f} working sets"
        for row in grouped.itertuples(index=False)
    ]


def _muscle_group_frequency(work: pd.DataFrame, latest_week: pd.Timestamp) -> list[dict[str, object]]:
    if "MuscleGroup" not in work.columns:
        return []
    latest = work[work["Week"] == latest_week].dropna(subset=["MuscleGroup"])
    if latest.empty:
        return []
    seen_groups = sorted({str(v).lower() for v in work["MuscleGroup"].dropna().unique()})
    frequency = (
        latest.groupby("MuscleGroup", as_index=True)
        .agg(Days=("Date", "nunique"), Sets=("Set", "count"))
    )
    flags: list[dict[str, object]] = []
    for mg in seen_groups:
        days = int(frequency["Days"].get(mg, 0)) if not frequency.empty else 0
        sets = int(frequency["Sets"].get(mg, 0)) if not frequency.empty else 0
        if days == 0:
            status = "neglected"
        elif days < TARGET_MIN_MUSCLE_FREQUENCY:
            status = "low_frequency"
        else:
            status = "covered"
        if status != "covered":
            flags.append({"muscle_group": mg, "days": days, "sets": sets, "status": status})
    return flags


def _movement_bucket(row: pd.Series) -> str:
    category = str(row.get("Category", "")).lower()
    muscle_group = str(row.get("MuscleGroup", "")).lower()
    if "leg" in muscle_group or category in {
        "squat", "leg press", "quad isolation", "hamstring isolation", "calves", "hip isolation"
    }:
        return "legs"
    if "pull" in category or muscle_group == "back" or category == "biceps":
        return "pull"
    if "push" in category or muscle_group in {"chest", "shoulders"} or category == "triceps":
        return "push"
    return "other"


def _push_pull_legs_balance(latest: pd.DataFrame) -> dict[str, object]:
    if latest.empty:
        return {"push": 0.0, "pull": 0.0, "legs": 0.0, "summary": "No push/pull/legs frequency signal yet."}
    work = latest.copy()
    work["Bucket"] = work.apply(_movement_bucket, axis=1)
    days = work.groupby("Bucket")["Date"].nunique()
    tracked_total = float(days.reindex(["push", "pull", "legs"]).fillna(0).sum())
    if tracked_total <= 0:
        return {"push": 0.0, "pull": 0.0, "legs": 0.0, "summary": "No push/pull/legs frequency detected this week."}
    percentages = {b: float(days.get(b, 0.0) / tracked_total * 100) for b in ("push", "pull", "legs")}
    low = min(percentages, key=percentages.get)
    high = max(percentages, key=percentages.get)
    spread = percentages[high] - percentages[low]
    summary = (
        "Push, pull, and legs frequency is balanced for a cut."
        if spread <= 20
        else f"{low.title()} frequency is low relative to {high}."
    )
    return {**percentages, "summary": summary, "spread": spread, "low_bucket": low}


def _weekly_training_score(
    scores: list[dict[str, object]],
    frequency_flags: list[dict[str, object]],
    balance: dict[str, object],
) -> int:
    if not scores:
        return 0
    avg_score = sum(float(r["score"]) for r in scores) / len(scores)
    progressing_count = sum(1 for r in scores if r["status"] == "progressing")
    declining_count = sum(1 for r in scores if r["status"] == "declining")
    stable_count = sum(1 for r in scores if r["status"] == "stable")
    frequency_penalty = sum(12 if r["status"] == "neglected" else 6 for r in frequency_flags)
    balance_penalty = min(12.0, float(balance.get("spread", 0.0)) * 0.2)
    progression_bonus = min(8.0, progressing_count * 1.5 + stable_count * 0.5)
    regression_penalty = declining_count * 12.0
    return round(_clamp(avg_score + progression_bonus - regression_penalty - frequency_penalty - balance_penalty))


def build_next_workout_recommendation(df: pd.DataFrame) -> dict[str, object]:
    if df.empty or "Date" not in df.columns:
        return {
            "recommended_focus": "Recovery",
            "reason": "No workout history is available yet.",
            "suggested_exercises": ["Easy walk or mobility work"],
            "recommended_sets_reps": "Keep it easy",
            "intensity_guidance": "Stay well short of failure.",
        }

    work = _add_week(df)
    if work.empty:
        return {
            "recommended_focus": "Recovery",
            "reason": "No dated workout history is available yet.",
            "suggested_exercises": ["Easy walk or mobility work"],
            "recommended_sets_reps": "Keep it easy",
            "intensity_guidance": "Stay well short of failure.",
        }

    latest_week = work["Week"].max()
    session_stats = _session_exercise_stats(work)
    scores = _score_exercise_sessions(session_stats)
    frequency_flags = _muscle_group_frequency(work, latest_week)
    fatigue = fatigue_risk_detector(df)
    retention = strength_retention_score(df)

    return build_next_workout(work, latest_week, scores, frequency_flags, fatigue, retention)


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
    frequency_flags = _muscle_group_frequency(work, latest_week)
    balance = _push_pull_legs_balance(latest)
    training_score = _weekly_training_score(scores, frequency_flags, balance)
    recommendations = build_recommendations(scores, frequency_flags, balance)
    suggested_exercises = build_suggested_exercises(frequency_flags, scores, recommendations)

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
                f"{row['muscle_group']}: "
                + ("0 days" if row["status"] == "neglected" else f"{row['days']} day")
                + " this week."
            )
            for row in frequency_flags
        ],
        "balance": balance,
        "recommendations": recommendations,
        "suggested_exercises": suggested_exercises,
        "suggested_focus": recommendations[0],
    }
