from __future__ import annotations

import pandas as pd


def _empty_insights() -> dict[str, object]:
    return {
        "week_label": "No training week selected",
        "top_progressing": ["No progression signal yet."],
        "stalled": ["No stalled exercises detected yet."],
        "muscle_group_volume": [],
        "balance": {
            "push": 0.0,
            "pull": 0.0,
            "legs": 0.0,
            "summary": "No push/pull/legs balance signal yet.",
        },
        "suggested_focus": "Log more complete workout data before changing next week's focus.",
    }


def _format_delta(value: float, unit: str = "lbs") -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.0f} {unit}"


def _add_week(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(subset=["Date"]).copy()
    work["Week"] = work["Date"].dt.to_period("W").dt.start_time
    return work


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


def _progressing_exercises(stats: pd.DataFrame, latest_week: pd.Timestamp) -> list[str]:
    previous_week = stats[stats["Week"] < latest_week]["Week"].max()
    if pd.isna(previous_week):
        return ["Need at least two logged weeks to identify progression."]

    latest = stats[stats["Week"] == latest_week].set_index("Exercise")
    previous = stats[stats["Week"] == previous_week].set_index("Exercise")
    common = latest.index.intersection(previous.index)
    if common.empty:
        return ["No exercises overlap with the previous week."]

    rows = []
    for exercise in common:
        latest_row = latest.loc[exercise]
        previous_row = previous.loc[exercise]
        e1rm_delta = latest_row["BestEstimated1RM"] - previous_row["BestEstimated1RM"]
        volume_delta = latest_row["Volume"] - previous_row["Volume"]
        if pd.notna(e1rm_delta) and e1rm_delta > 0:
            rows.append((exercise, float(e1rm_delta), "e1RM", float(volume_delta)))
        elif pd.notna(volume_delta) and volume_delta > 0:
            rows.append((exercise, float(volume_delta), "volume", float(volume_delta)))

    if not rows:
        return ["No clear exercise-level progression versus the prior week."]

    rows.sort(key=lambda row: row[1], reverse=True)
    output = []
    for exercise, delta, metric, volume_delta in rows[:5]:
        if metric == "e1RM":
            output.append(f"{exercise}: estimated 1RM improved {_format_delta(delta)}.")
        else:
            output.append(f"{exercise}: weekly volume rose {_format_delta(volume_delta)}.")
    return output


def _stalled_exercises(stats: pd.DataFrame, latest_week: pd.Timestamp) -> list[str]:
    recent_weeks = sorted(stats[stats["Week"] <= latest_week]["Week"].dropna().unique())[-4:]
    if len(recent_weeks) < 3:
        return ["Need at least three logged weeks to flag stalls responsibly."]

    recent = stats[stats["Week"].isin(recent_weeks)]
    stalled = []
    for exercise, group in recent.groupby("Exercise"):
        if group["Week"].nunique() < 3:
            continue
        ordered = group.sort_values("Week")
        e1rm = ordered["BestEstimated1RM"].dropna()
        volume = ordered["Volume"].dropna()
        e1rm_flat = len(e1rm) >= 3 and e1rm.iloc[-1] <= e1rm.iloc[:-1].max()
        volume_flat = len(volume) >= 3 and volume.iloc[-1] <= volume.iloc[:-1].max() * 0.95
        if e1rm_flat and volume_flat:
            stalled.append((exercise, float(volume.iloc[-1]) if len(volume) else 0.0))

    if not stalled:
        return ["No major stalls detected across the last 3-4 weeks."]

    stalled.sort(key=lambda row: row[1], reverse=True)
    return [f"{exercise}: no recent e1RM high and volume is down or flat." for exercise, _ in stalled[:5]]


def _muscle_group_volume(latest: pd.DataFrame) -> list[str]:
    if "MuscleGroup" not in latest.columns:
        return []
    grouped = (
        latest.dropna(subset=["MuscleGroup"])
        .groupby("MuscleGroup", as_index=False)["Volume"]
        .sum()
        .sort_values("Volume", ascending=False)
    )
    return [f"{row.MuscleGroup}: {row.Volume:,.0f} lbs" for row in grouped.itertuples(index=False)]


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
    return {**percentages, "summary": summary}


def _suggest_focus(
    balance: dict[str, object],
    muscle_group_lines: list[str],
    stalled: list[str],
) -> str:
    low_bucket = min(("push", "pull", "legs"), key=lambda key: float(balance.get(key, 0.0)))
    has_real_stall = stalled and not stalled[0].startswith(("No ", "Need "))

    if has_real_stall:
        exercise = stalled[0].split(":", 1)[0]
        return f"Prioritize a small progression plan for {exercise}, then add enough {low_bucket} work to balance the week."
    if muscle_group_lines:
        lowest_group = muscle_group_lines[-1].split(":", 1)[0]
        return f"Bring up {lowest_group} volume while keeping the strongest lifts stable."
    return f"Add a measured {low_bucket} emphasis next week and keep effort consistent across repeated exercises."


def build_weekly_insights(df: pd.DataFrame) -> dict[str, object]:
    if df.empty or "Date" not in df.columns:
        return _empty_insights()

    work = _add_week(df)
    if work.empty:
        return _empty_insights()

    latest_week = work["Week"].max()
    latest = work[work["Week"] == latest_week].copy()
    stats = _weekly_exercise_stats(work)

    progressing = _progressing_exercises(stats, latest_week) if not stats.empty else _empty_insights()["top_progressing"]
    stalled = _stalled_exercises(stats, latest_week) if not stats.empty else _empty_insights()["stalled"]
    muscle_groups = _muscle_group_volume(latest)
    balance = _push_pull_legs_balance(latest)
    focus = _suggest_focus(balance, muscle_groups, stalled)

    return {
        "week_label": f"Week of {latest_week.strftime('%b %d, %Y')}",
        "top_progressing": progressing,
        "stalled": stalled,
        "muscle_group_volume": muscle_groups,
        "balance": balance,
        "suggested_focus": focus,
    }
