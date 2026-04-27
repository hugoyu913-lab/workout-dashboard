from __future__ import annotations

import pandas as pd


CHECKIN_COLUMNS = [
    "Date",
    "Bodyweight",
    "Waist",
    "Calories",
    "Protein",
    "SleepHours",
    "Energy",
    "Soreness",
    "Stress",
]


def weekly_total_volume(df: pd.DataFrame) -> pd.DataFrame:
    dated = df.dropna(subset=["Date"]).copy()
    dated["Week"] = dated["Date"].dt.to_period("W").dt.start_time
    return dated.groupby("Week", as_index=False)["Volume"].sum().sort_values("Week")


def clean_checkins(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=CHECKIN_COLUMNS)

    df = raw.copy()
    df.columns = [str(column).strip() for column in df.columns]
    for column in CHECKIN_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA

    df = df[CHECKIN_COLUMNS].copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for column in CHECKIN_COLUMNS:
        if column != "Date":
            df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    return df


def checkin_metrics(checkins: pd.DataFrame) -> dict[str, object]:
    empty = {
        "bodyweight_7day_avg": pd.NA,
        "weekly_weight_loss_rate": pd.NA,
        "average_protein": pd.NA,
        "average_sleep": pd.NA,
        "cut_pace": "unknown",
        "recovery_summary": "No check-in data available.",
        "warnings": [],
    }
    if checkins.empty:
        return empty

    df = checkins.sort_values("Date").copy()
    recent = df.tail(14)
    bodyweight_7day_avg = df["Bodyweight"].dropna().tail(7).mean()
    average_protein = recent["Protein"].dropna().mean()
    average_sleep = recent["SleepHours"].dropna().mean()

    weekly_rate = pd.NA
    weights = df.dropna(subset=["Bodyweight"])
    if len(weights) >= 2:
        current = weights.tail(7)["Bodyweight"].mean()
        previous = weights.iloc[:-7].tail(7)["Bodyweight"].mean() if len(weights) >= 8 else weights.iloc[0]["Bodyweight"]
        days = max((weights.iloc[-1]["Date"] - weights.iloc[0]["Date"]).days, 1)
        if pd.notna(current) and pd.notna(previous):
            if len(weights) >= 8:
                weekly_rate = previous - current
            else:
                weekly_rate = (weights.iloc[0]["Bodyweight"] - weights.iloc[-1]["Bodyweight"]) / days * 7

    if pd.isna(weekly_rate):
        cut_pace = "unknown"
    elif weekly_rate < 0.25:
        cut_pace = "slow"
    elif weekly_rate <= 1.25:
        cut_pace = "ideal"
    else:
        cut_pace = "aggressive"

    warnings = []
    if cut_pace == "aggressive":
        warnings.append("Bodyweight is dropping quickly; monitor strength retention and recovery.")
    if pd.notna(average_sleep) and average_sleep < 6.5:
        warnings.append("Average sleep is below 6.5 hours.")
    if pd.notna(average_protein) and average_protein < 120:
        warnings.append("Average protein appears low for muscle retention.")

    recovery_parts = []
    if pd.notna(average_sleep):
        recovery_parts.append(f"sleep {average_sleep:.1f}h")
    for column in ("Energy", "Soreness", "Stress"):
        value = recent[column].dropna().mean()
        if pd.notna(value):
            recovery_parts.append(f"{column.lower()} {value:.1f}/10")
    recovery_summary = " | ".join(recovery_parts) if recovery_parts else "No recent recovery ratings available."

    return {
        "bodyweight_7day_avg": bodyweight_7day_avg,
        "weekly_weight_loss_rate": weekly_rate,
        "average_protein": average_protein,
        "average_sleep": average_sleep,
        "cut_pace": cut_pace,
        "recovery_summary": recovery_summary,
        "warnings": warnings,
    }


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


def strength_retention_score(df: pd.DataFrame, weeks: int = 3) -> dict[str, object]:
    empty = {
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

    latest_date = work["Date"].max()
    cutoff = latest_date - pd.Timedelta(weeks=weeks)
    recent = work[work["Date"] >= cutoff].copy()
    if recent.empty:
        return empty

    recent["Estimated1RM"] = recent["Weight"] * (1 + recent["Reps"] / 30)
    statuses = []
    for exercise, group in recent.groupby("Exercise"):
        ordered = group.sort_values("Date")
        dates = ordered["Date"].dt.date.unique()
        if len(dates) < 2:
            continue

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

    total = len(statuses)
    if total == 0:
        return empty

    improved = statuses.count("Improved")
    maintained = statuses.count("Maintained")
    regressed = statuses.count("Regressed")
    improved_pct = improved / total * 100
    maintained_pct = maintained / total * 100
    regressed_pct = regressed / total * 100
    score = round((improved * 1.0 + maintained * 0.7) / total * 100)

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
        "exercise_count": total,
    }


def fatigue_risk_detector(df: pd.DataFrame, weeks: int = 3) -> dict[str, object]:
    empty = {
        "risk": "Low",
        "reasons": ["No repeat-performance fatigue signals detected."],
        "suggested_action": "Maintain current loads and recovery habits.",
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

    latest_date = work["Date"].max()
    cutoff = latest_date - pd.Timedelta(weeks=weeks)
    recent = work[work["Date"] >= cutoff].copy()
    if recent.empty:
        return empty

    session_best = (
        recent.groupby(["Date", "Exercise"], as_index=False)
        .agg(
            Weight=("Weight", "max"),
            Reps=("Reps", "max"),
            MuscleGroup=("MuscleGroup", "first") if "MuscleGroup" in recent.columns else ("Exercise", "first"),
        )
        .sort_values(["Exercise", "Date"])
    )

    same_weight_rep_drops: list[str] = []
    regression_groups: dict[str, int] = {}
    for exercise, group in session_best.groupby("Exercise"):
        ordered = group.sort_values("Date").reset_index(drop=True)
        if len(ordered) < 2:
            continue
        for idx in range(1, len(ordered)):
            previous = ordered.iloc[idx - 1]
            current = ordered.iloc[idx]
            if (
                pd.notna(previous["Weight"])
                and pd.notna(current["Weight"])
                and pd.notna(previous["Reps"])
                and pd.notna(current["Reps"])
                and abs(float(current["Weight"]) - float(previous["Weight"])) < 0.01
                and float(current["Reps"]) < float(previous["Reps"])
            ):
                same_weight_rep_drops.append(
                    f"{exercise}: reps dropped from {previous['Reps']:.0f} to {current['Reps']:.0f} at {current['Weight']:.0f} lbs."
                )
                muscle_group = str(current.get("MuscleGroup", "unknown")).strip().lower() or "unknown"
                regression_groups[muscle_group] = regression_groups.get(muscle_group, 0) + 1

    reasons: list[str] = []
    if same_weight_rep_drops:
        reasons.extend(same_weight_rep_drops[:3])

    clustered_groups = [
        group for group, count in sorted(regression_groups.items())
        if count >= 2 and group not in {"unknown", "other"}
    ]
    for group in clustered_groups:
        reasons.append(f"{group.title()} has {regression_groups[group]} same-load rep regressions in the recent window.")

    weekly_sessions = workout_frequency(recent)
    high_frequency_weeks = weekly_sessions[weekly_sessions["Workouts"] > 6] if not weekly_sessions.empty else pd.DataFrame()
    if not high_frequency_weeks.empty:
        max_sessions = int(high_frequency_weeks["Workouts"].max())
        reasons.append(f"Weekly training frequency reached {max_sessions} sessions, above the normal 5-6 target.")

    risk_points = len(same_weight_rep_drops) + len(clustered_groups) * 2 + len(high_frequency_weeks)
    if risk_points >= 4:
        risk = "High"
        suggested_action = "Reduce fatigue: add recovery, increase RIR by 1-2, or trim intensity for regressing muscle groups."
    elif risk_points >= 2:
        risk = "Moderate"
        suggested_action = "Monitor recovery and avoid pushing load on exercises with same-weight rep drops."
    else:
        risk = "Low"
        suggested_action = "Maintain current recovery habits and keep loads stable."

    return {
        "risk": risk,
        "reasons": reasons or empty["reasons"],
        "suggested_action": suggested_action,
    }


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
