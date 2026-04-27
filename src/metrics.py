from __future__ import annotations

import pandas as pd


def weekly_total_volume(df: pd.DataFrame) -> pd.DataFrame:
    dated = df.dropna(subset=["Date"]).copy()
    dated["Week"] = dated["Date"].dt.to_period("W").dt.start_time
    return dated.groupby("Week", as_index=False)["Volume"].sum().sort_values("Week")


def volume_by_exercise(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("Exercise", as_index=False)["Volume"]
        .sum()
        .sort_values("Volume", ascending=False)
        .reset_index(drop=True)
    )


def estimated_1rm_by_exercise(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(subset=["Exercise", "Weight", "Reps"]).copy()
    work["Estimated1RM"] = work["Weight"] * (1 + work["Reps"] / 30)
    return (
        work.sort_values(["Exercise", "Estimated1RM"], ascending=[True, False])
        .groupby("Exercise", as_index=False)
        .first()[["Exercise", "Estimated1RM", "Weight", "Reps", "Date"]]
        .sort_values("Estimated1RM", ascending=False)
        .reset_index(drop=True)
    )


def estimated_1rm_over_time(df: pd.DataFrame, exercise: str) -> pd.DataFrame:
    """Daily best estimated 1RM for one exercise, with PR flag."""
    work = df[(df["Exercise"] == exercise)].dropna(subset=["Weight", "Reps", "Date"]).copy()
    if work.empty:
        return pd.DataFrame(columns=["Date", "Estimated1RM", "IsPR"])
    work["Estimated1RM"] = work["Weight"] * (1 + work["Reps"] / 30)
    daily = (
        work.groupby("Date", as_index=False)["Estimated1RM"]
        .max()
        .sort_values("Date")
        .reset_index(drop=True)
    )
    # A day is a PR if its 1RM exceeds all previous days' 1RMs
    prev_best = daily["Estimated1RM"].shift(1).expanding(min_periods=1).max()
    daily["IsPR"] = daily["Estimated1RM"] > prev_best.fillna(-1)
    return daily


def pr_tracker(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(subset=["Exercise"]).copy()
    work["Estimated1RM"] = work["Weight"] * (1 + work["Reps"] / 30)

    max_weight = work.sort_values(["Exercise", "Weight"], ascending=[True, False]).groupby("Exercise").first()
    max_reps = work.sort_values(["Exercise", "Reps"], ascending=[True, False]).groupby("Exercise").first()
    max_e1rm = work.sort_values(["Exercise", "Estimated1RM"], ascending=[True, False]).groupby("Exercise").first()

    records = []
    for exercise in sorted(work["Exercise"].dropna().unique()):
        records.append(
            {
                "Exercise": exercise,
                "MaxWeight": max_weight.loc[exercise, "Weight"] if exercise in max_weight.index else pd.NA,
                "MaxReps": max_reps.loc[exercise, "Reps"] if exercise in max_reps.index else pd.NA,
                "BestEstimated1RM": max_e1rm.loc[exercise, "Estimated1RM"] if exercise in max_e1rm.index else pd.NA,
                "BestDate": max_e1rm.loc[exercise, "Date"] if exercise in max_e1rm.index else pd.NaT,
            }
        )
    return pd.DataFrame(records).sort_values("BestEstimated1RM", ascending=False, na_position="last")


def workout_frequency(df: pd.DataFrame) -> pd.DataFrame:
    dated = df.dropna(subset=["Date"]).copy()
    dated["Week"] = dated["Date"].dt.to_period("W").dt.start_time
    sessions = dated[["Week", "Date", "Workout", "SourceSheet"]].drop_duplicates()
    return sessions.groupby("Week", as_index=False).size().rename(columns={"size": "Workouts"})


def top_exercises_by_volume(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    return volume_by_exercise(df).head(limit)


def muscle_group_volume(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.dropna(subset=["MuscleGroup"])
        .groupby("MuscleGroup", as_index=False)["Volume"]
        .sum()
        .sort_values("Volume", ascending=False)
        .reset_index(drop=True)
    )


def weekly_muscle_group_volume(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(subset=["Date", "MuscleGroup"]).copy()
    work["Week"] = work["Date"].dt.to_period("W").dt.start_time
    return work.groupby(["Week", "MuscleGroup"], as_index=False)["Volume"].sum()


def daily_workout_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """One row per calendar day: total volume, best e1RM, set count."""
    work = df.dropna(subset=["Date"]).copy()
    work["Estimated1RM"] = work["Weight"] * (1 + work["Reps"] / 30)
    agg = work.groupby("Date", as_index=False).agg(
        daily_volume=("Volume", "sum"),
        daily_best_e1rm=("Estimated1RM", "max"),
        daily_sets=("Set", "count"),
    )
    agg.rename(columns={"Date": "date"}, inplace=True)
    return agg.sort_values("date").reset_index(drop=True)
