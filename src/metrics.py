from __future__ import annotations

import pandas as pd


def weekly_total_volume(df: pd.DataFrame) -> pd.DataFrame:
    dated = df.dropna(subset=["Date"]).copy()
    dated["Week"] = dated["Date"].dt.to_period("W").dt.start_time
    return dated.groupby("Week", as_index=False)["Volume"].sum().sort_values("Week")


def volume_by_exercise(df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        df.groupby("Exercise", as_index=False)
        .agg(
            Volume=("Volume", "sum"),
            MuscleGroup=("MuscleGroup", "first") if "MuscleGroup" in df.columns else ("Exercise", "first"),
            Category=("Category", "first") if "Category" in df.columns else ("Exercise", "first"),
        )
        .sort_values("Volume", ascending=False)
        .reset_index(drop=True)
    )
    drop_columns = [
        column for column in ("MuscleGroup", "Category")
        if column in grouped.columns and grouped[column].equals(grouped["Exercise"])
    ]
    return grouped.drop(columns=drop_columns)


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
    if "MuscleGroup" not in df.columns:
        return pd.DataFrame(columns=["MuscleGroup", "Volume"])
    return (
        df.dropna(subset=["MuscleGroup"])
        .groupby("MuscleGroup", as_index=False)["Volume"]
        .sum()
        .sort_values("Volume", ascending=False)
        .reset_index(drop=True)
    )


def muscle_group_frequency(df: pd.DataFrame) -> pd.DataFrame:
    if "MuscleGroup" not in df.columns:
        return pd.DataFrame(columns=["MuscleGroup", "Sessions Trained"])

    work = df.dropna(subset=["Date", "MuscleGroup"]).copy()
    work["MuscleGroup"] = work["MuscleGroup"].astype(str).str.strip()
    work = work[
        work["MuscleGroup"].ne("")
        & work["MuscleGroup"].str.lower().ne("unknown")
        & work["MuscleGroup"].str.lower().ne("other")
    ]
    if work.empty:
        return pd.DataFrame(columns=["MuscleGroup", "Sessions Trained"])

    return (
        work.groupby("MuscleGroup", as_index=False)["Date"]
        .nunique()
        .rename(columns={"Date": "Sessions Trained"})
        .sort_values(["Sessions Trained", "MuscleGroup"], ascending=[False, True])
        .reset_index(drop=True)
    )


def weekly_muscle_group_volume(df: pd.DataFrame) -> pd.DataFrame:
    if "MuscleGroup" not in df.columns:
        return pd.DataFrame(columns=["Week", "MuscleGroup", "Volume"])
    work = df.dropna(subset=["Date", "MuscleGroup"]).copy()
    work["Week"] = work["Date"].dt.to_period("W").dt.start_time
    return work.groupby(["Week", "MuscleGroup"], as_index=False)["Volume"].sum()


def category_volume(df: pd.DataFrame) -> pd.DataFrame:
    if "Category" not in df.columns:
        return pd.DataFrame(columns=["Category", "Volume"])
    return (
        df.dropna(subset=["Category"])
        .groupby("Category", as_index=False)["Volume"]
        .sum()
        .sort_values("Volume", ascending=False)
        .reset_index(drop=True)
    )


def weekly_category_volume(df: pd.DataFrame) -> pd.DataFrame:
    if "Category" not in df.columns:
        return pd.DataFrame(columns=["Week", "Category", "Volume"])
    work = df.dropna(subset=["Date", "Category"]).copy()
    work["Week"] = work["Date"].dt.to_period("W").dt.start_time
    return work.groupby(["Week", "Category"], as_index=False)["Volume"].sum()


def daily_workout_detail(df: pd.DataFrame, selected_date: object) -> pd.DataFrame:
    columns = ["Exercise", "Set", "Weight", "Reps", "Volume", "MuscleGroup", "Category", "SourceSheet"]
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame(columns=columns)

    target_date = pd.to_datetime(selected_date, errors="coerce")
    if pd.isna(target_date):
        return pd.DataFrame(columns=columns)

    dated = df.copy()
    dated["Date"] = pd.to_datetime(dated["Date"], errors="coerce")
    work = dated[dated["Date"].dt.date == target_date.date()].copy()
    if work.empty:
        return pd.DataFrame(columns=columns)

    order_candidates = ["WorkoutOrder", "ExerciseOrder", "Order", "RowOrder"]
    order_columns = [column for column in order_candidates if column in work.columns]
    sort_columns = order_columns or [column for column in ["SourceSheet", "Exercise", "Set"] if column in work.columns]
    if sort_columns:
        work = work.sort_values(sort_columns, na_position="last")

    for column in columns:
        if column not in work.columns:
            work[column] = pd.NA
    return work[columns].reset_index(drop=True)


def daily_workout_summary(detail: pd.DataFrame) -> dict[str, object]:
    if detail.empty:
        return {
            "total_exercises": 0,
            "total_working_sets": 0,
            "total_volume": 0.0,
            "muscle_groups_trained": "None",
        }

    muscle_groups = (
        detail["MuscleGroup"]
        .dropna()
        .astype(str)
        .str.strip()
    )
    muscle_groups = sorted(
        group for group in muscle_groups.unique()
        if group and group.lower() not in {"unknown", "other"}
    )

    return {
        "total_exercises": int(detail["Exercise"].dropna().nunique()),
        "total_working_sets": int(detail["Set"].notna().sum()),
        "total_volume": float(detail["Volume"].sum(skipna=True)),
        "muscle_groups_trained": ", ".join(muscle_groups) if muscle_groups else "None",
    }


def workout_comparison(df: pd.DataFrame, selected_date: object) -> pd.DataFrame:
    columns = [
        "Exercise",
        "Current Weight",
        "Current Reps",
        "Previous Weight",
        "Previous Reps",
        "Weight Change",
        "Rep Change",
        "Status",
    ]
    if df.empty or "Date" not in df.columns or "Exercise" not in df.columns:
        return pd.DataFrame(columns=columns)

    target_date = pd.to_datetime(selected_date, errors="coerce")
    if pd.isna(target_date):
        return pd.DataFrame(columns=columns)

    work = df.copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date", "Exercise"])
    current = work[work["Date"].dt.date == target_date.date()].copy()
    if current.empty:
        return pd.DataFrame(columns=columns)

    records = []
    for exercise, current_group in current.groupby("Exercise", sort=False):
        current_best = (
            current_group.sort_values(["Weight", "Reps"], ascending=[False, False], na_position="last")
            .iloc[0]
        )
        previous_rows = work[
            (work["Exercise"] == exercise)
            & (work["Date"].dt.date < target_date.date())
        ].copy()
        if previous_rows.empty:
            previous_weight = pd.NA
            previous_reps = pd.NA
            weight_change = pd.NA
            rep_change = pd.NA
            status = "No Previous"
        else:
            previous_date = previous_rows["Date"].max().date()
            previous_group = previous_rows[previous_rows["Date"].dt.date == previous_date]
            previous_best = (
                previous_group.sort_values(["Weight", "Reps"], ascending=[False, False], na_position="last")
                .iloc[0]
            )
            previous_weight = previous_best["Weight"]
            previous_reps = previous_best["Reps"]
            weight_change = current_best["Weight"] - previous_weight
            rep_change = current_best["Reps"] - previous_reps

            improved = (
                pd.notna(weight_change)
                and weight_change > 0
            ) or (
                pd.notna(rep_change)
                and rep_change > 0
            )
            regressed = (
                pd.notna(weight_change)
                and weight_change < 0
            ) or (
                pd.notna(rep_change)
                and rep_change < 0
            )
            if improved:
                status = "Improved"
            elif regressed:
                status = "Regressed"
            else:
                status = "Same"

        records.append(
            {
                "Exercise": exercise,
                "Current Weight": current_best["Weight"],
                "Current Reps": current_best["Reps"],
                "Previous Weight": previous_weight,
                "Previous Reps": previous_reps,
                "Weight Change": weight_change,
                "Rep Change": rep_change,
                "Status": status,
            }
        )

    return pd.DataFrame(records, columns=columns)


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
