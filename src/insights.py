from __future__ import annotations

import pandas as pd


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
        historical = ordered.iloc[:-1]
        recent = ordered.tail(3).reset_index(drop=True)

        weight_delta = 0.0
        reps_delta = 0.0
        e1rm_delta_pct = 0.0
        if pd.notna(latest["Weight"]) and pd.notna(previous["Weight"]):
            weight_delta = float(latest["Weight"]) - float(previous["Weight"])
        if pd.notna(latest["Reps"]) and pd.notna(previous["Reps"]):
            reps_delta = float(latest["Reps"]) - float(previous["Reps"])
        if pd.notna(latest["Estimated1RM"]) and pd.notna(previous["Estimated1RM"]) and previous["Estimated1RM"] > 0:
            e1rm_delta_pct = (float(latest["Estimated1RM"]) - float(previous["Estimated1RM"])) / float(previous["Estimated1RM"]) * 100

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
        immediate_regression = bool(pd.notna(latest["Estimated1RM"]) and pd.notna(previous["Estimated1RM"]) and latest["Estimated1RM"] < previous["Estimated1RM"] * 0.97)
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
                if len(weights) >= 3 and len(reps) >= 3 and max(weights) - min(weights) < 0.01 and reps[-1] < reps[-2] <= reps[-3]:
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

        scores.append(
            {
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
            }
        )

    return sorted(scores, key=lambda row: (row["score"], row["latest_volume"]), reverse=True)


def _score_line(row: dict[str, object]) -> str:
    if row["status"] == "progressing":
        return f"{row['exercise']}: {row['score']}/100, progressing (load {row['weight_delta']:+.1f} lbs, reps {row['reps_delta']:+.1f})."
    if row["status"] == "declining":
        return f"{row['exercise']}: {row['score']}/100, declining (e1RM {row['e1rm_delta_pct']:+.1f}%)."
    if row.get("maintained_strength"):
        return f"{row['exercise']}: strength maintained during cut - good."
    return f"{row['exercise']}: {row['score']}/100, {row['status']}."


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

    seen_groups = set(str(value).lower() for value in work["MuscleGroup"].dropna().unique())
    target_groups = sorted(seen_groups)
    frequency = (
        latest.groupby("MuscleGroup", as_index=True)
        .agg(Days=("Date", "nunique"), Sets=("Set", "count"))
    )

    flags = []
    for muscle_group in target_groups:
        days = int(frequency["Days"].get(muscle_group, 0)) if not frequency.empty else 0
        sets = int(frequency["Sets"].get(muscle_group, 0)) if not frequency.empty else 0
        if days == 0:
            status = "neglected"
        elif days < TARGET_MIN_MUSCLE_FREQUENCY:
            status = "low_frequency"
        else:
            status = "covered"
        if status != "covered":
            flags.append(
                {
                    "muscle_group": muscle_group,
                    "days": days,
                    "sets": sets,
                    "status": status,
                }
            )
    return flags


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
            "summary": "No push/pull/legs frequency signal yet.",
        }

    work = latest.copy()
    work["Bucket"] = work.apply(_movement_bucket, axis=1)
    days = work.groupby("Bucket")["Date"].nunique()
    tracked_total = float(days.reindex(["push", "pull", "legs"]).fillna(0).sum())
    if tracked_total <= 0:
        return {
            "push": 0.0,
            "pull": 0.0,
            "legs": 0.0,
            "summary": "No push/pull/legs frequency detected this week.",
        }

    percentages = {
        bucket: float(days.get(bucket, 0.0) / tracked_total * 100)
        for bucket in ("push", "pull", "legs")
    }
    low = min(percentages, key=percentages.get)
    high = max(percentages, key=percentages.get)
    spread = percentages[high] - percentages[low]
    if spread <= 20:
        summary = "Push, pull, and legs frequency is balanced for a cut."
    else:
        summary = f"{low.title()} frequency is low relative to {high}."
    return {**percentages, "summary": summary, "spread": spread, "low_bucket": low}


def _weekly_training_score(
    scores: list[dict[str, object]],
    frequency_flags: list[dict[str, object]],
    balance: dict[str, object],
) -> int:
    if not scores:
        return 0

    avg_exercise_score = sum(float(row["score"]) for row in scores) / len(scores)
    progressing_count = sum(1 for row in scores if row["status"] == "progressing")
    declining_count = sum(1 for row in scores if row["status"] == "declining")
    stable_count = sum(1 for row in scores if row["status"] == "stable")
    frequency_penalty = sum(12 if row["status"] == "neglected" else 6 for row in frequency_flags)
    balance_penalty = min(12.0, float(balance.get("spread", 0.0)) * 0.2)
    progression_bonus = min(8.0, progressing_count * 1.5 + stable_count * 0.5)
    regression_penalty = declining_count * 12.0

    return round(_clamp(avg_exercise_score + progression_bonus - regression_penalty - frequency_penalty - balance_penalty))


def _recommendations(
    scores: list[dict[str, object]],
    frequency_flags: list[dict[str, object]],
    balance: dict[str, object],
) -> list[str]:
    recommendations: list[str] = []
    declining_rows = [item for item in scores if item["status"] == "declining"]
    declining_groups = sorted(
        {str(item.get("muscle_group", "")).lower() for item in declining_rows if item.get("muscle_group")}
    )

    for muscle_group in declining_groups[:2]:
        recommendations.append(
            f"{muscle_group.title()} exercises regressing - consider more recovery or a slight frequency increase."
        )

    for row in declining_rows[:3]:
        if row.get("same_weight_reps_down"):
            recommendations.append(
                f"{row['exercise']} reps dropped at the same weight - increase RIR by 1-2 or add recovery before pushing load."
            )
        else:
            recommendations.append(
                f"{row['exercise']} strength is regressing - keep load conservative and prioritize recovery this week."
            )

    for item in frequency_flags[:4]:
        muscle_group = str(item["muscle_group"])
        if item["status"] == "neglected":
            recommendations.append(
                f"{muscle_group.title()} not trained this week - add 2 hard sets to preserve muscle."
            )
        else:
            recommendations.append(
                f"{muscle_group.title()} trained only once - increase frequency to preserve muscle."
            )

    for row in [item for item in scores if item["status"] == "stable" and item.get("maintained_strength")] [:2]:
        recommendations.append(f"{row['exercise']} strength maintained during cut - good.")

    progressing = [item for item in scores if item["status"] == "progressing"]
    if progressing and not recommendations:
        recommendations.append(
            f"{progressing[0]['exercise']} is progressing - keep 0-1 RIR but avoid adding unnecessary volume."
        )

    if not recommendations:
        low_bucket = str(balance.get("low_bucket", "pull"))
        recommendations.append(
            f"Maintain current loads and add one {low_bucket} exposure if recovery stays stable."
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
    frequency_flags = _muscle_group_frequency(work, latest_week)
    balance = _push_pull_legs_balance(latest)
    training_score = _weekly_training_score(scores, frequency_flags, balance)
    recommendations = _recommendations(scores, frequency_flags, balance)

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
                f"{'0 days' if row['status'] == 'neglected' else f'{row['days']} day'} this week."
            )
            for row in frequency_flags
        ],
        "balance": balance,
        "recommendations": recommendations,
        "suggested_focus": recommendations[0],
    }
