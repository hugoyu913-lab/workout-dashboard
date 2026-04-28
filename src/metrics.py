from __future__ import annotations

import pandas as pd

from config.profile import (
    DAILY_CALORIES_TARGET,
    DAILY_PROTEIN_TARGET,
    DAILY_SLEEP_MINIMUM,
    TARGET_REPS_MIN,
    TARGET_REPS_MAX,
    TARGET_SETS,
)

# Re-export from dedicated modules so existing callers keep working
from src.fatigue import fatigue_risk_detector  # noqa: F401
from src.retention import strength_retention_score  # noqa: F401


CHECKIN_COLUMNS = [
    "Date",
    "Bodyweight",
    "Calories",
    "Protein",
    "Carbs",
    "Fat",
    "Steps",
    "SleepHours",
    "Energy",
    "Soreness",
    "Stress",
    "Deload",
    "Notes",
]


def weekly_total_volume(df: pd.DataFrame) -> pd.DataFrame:
    dated = df.dropna(subset=["Date"]).copy()
    dated["Week"] = dated["Date"].dt.to_period("W").dt.start_time
    return dated.groupby("Week", as_index=False)["Volume"].sum().sort_values("Week")


def clean_checkins(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=CHECKIN_COLUMNS)

    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for col in CHECKIN_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    df = df[CHECKIN_COLUMNS].copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    numeric_cols = [
        "Bodyweight",
        "Calories",
        "Protein",
        "Carbs",
        "Fat",
        "Steps",
        "SleepHours",
        "Energy",
        "Soreness",
        "Stress",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Parse Deload as boolean: TRUE / 1 / yes → True, everything else → False
    df["Deload"] = (
        df["Deload"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes"})
    )

    df["Notes"] = df["Notes"].fillna("").astype(str)

    df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    return df


def get_deload_dates(checkins: pd.DataFrame) -> list[pd.Timestamp]:
    """Return list of dates where Deload=True in the checkins sheet."""
    if checkins.empty or "Deload" not in checkins.columns or "Date" not in checkins.columns:
        return []
    return checkins.loc[checkins["Deload"] == True, "Date"].dropna().tolist()


def checkin_metrics(checkins: pd.DataFrame) -> dict[str, object]:
    empty: dict[str, object] = {
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

    # 7-day rolling average for bodyweight — used everywhere for cut pace + display
    bw_rolling = df["Bodyweight"].rolling(7, min_periods=1).mean()
    bodyweight_7day_avg = bw_rolling.dropna().iloc[-1] if not bw_rolling.dropna().empty else pd.NA

    average_protein = recent["Protein"].dropna().mean()
    average_sleep = recent["SleepHours"].dropna().mean()

    # Cut pace from rolling-average trend, not raw daily spikes
    weekly_rate: object = pd.NA
    valid_rolling = bw_rolling.dropna()
    if len(valid_rolling) >= 8:
        current_avg = float(valid_rolling.iloc[-1])
        previous_avg = float(valid_rolling.iloc[-8])
        weekly_rate = previous_avg - current_avg
    elif len(df.dropna(subset=["Bodyweight"])) >= 2:
        weights = df.dropna(subset=["Bodyweight"])
        days = max((weights.iloc[-1]["Date"] - weights.iloc[0]["Date"]).days, 1)
        weekly_rate = (float(weights.iloc[0]["Bodyweight"]) - float(weights.iloc[-1]["Bodyweight"])) / days * 7

    if pd.isna(weekly_rate):
        cut_pace = "unknown"
    elif float(weekly_rate) < 0.25:
        cut_pace = "slow"
    elif float(weekly_rate) <= 1.25:
        cut_pace = "ideal"
    else:
        cut_pace = "aggressive"

    warnings: list[str] = []
    if cut_pace == "aggressive":
        warnings.append("Bodyweight is dropping quickly; monitor strength retention and recovery.")
    if pd.notna(average_sleep) and float(average_sleep) < DAILY_SLEEP_MINIMUM:
        warnings.append(f"Average sleep is below {DAILY_SLEEP_MINIMUM:.1f} hours.")
    if pd.notna(average_protein) and float(average_protein) < DAILY_PROTEIN_TARGET * 0.8:
        warnings.append("Average protein appears low for muscle retention.")

    if "Protein" in df.columns:
        low_protein = df["Protein"].tail(3).lt(DAILY_PROTEIN_TARGET * 0.8).all()
        if len(df["Protein"].dropna()) >= 3 and low_protein:
            warnings.append("Low protein - muscle loss risk on this cut.")
    if "Calories" in df.columns:
        latest_calories = df["Calories"].dropna().iloc[-1] if not df["Calories"].dropna().empty else pd.NA
        if pd.notna(latest_calories) and float(latest_calories) < DAILY_CALORIES_TARGET * 0.7:
            warnings.append("Too aggressive deficit - increase food intake.")
        if pd.notna(latest_calories) and float(latest_calories) > DAILY_CALORIES_TARGET * 1.1:
            warnings.append("Surplus detected - check against cut goal.")

    recovery_parts: list[str] = []
    if pd.notna(average_sleep):
        recovery_parts.append(f"sleep {float(average_sleep):.1f}h")
    for col in ("Energy", "Soreness", "Stress"):
        val = recent[col].dropna().mean()
        if pd.notna(val):
            recovery_parts.append(f"{col.lower()} {float(val):.1f}/10")
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
    drop_cols = [
        col for col in ("MuscleGroup", "Category")
        if col in grouped.columns and grouped[col].equals(grouped["Exercise"])
    ]
    return grouped.drop(columns=drop_cols)


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
        records.append({
            "Exercise": exercise,
            "MaxWeight": max_weight.loc[exercise, "Weight"] if exercise in max_weight.index else pd.NA,
            "MaxReps": max_reps.loc[exercise, "Reps"] if exercise in max_reps.index else pd.NA,
            "BestEstimated1RM": max_e1rm.loc[exercise, "Estimated1RM"] if exercise in max_e1rm.index else pd.NA,
            "BestDate": max_e1rm.loc[exercise, "Date"] if exercise in max_e1rm.index else pd.NaT,
        })
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
    order_cols = [c for c in order_candidates if c in work.columns]
    sort_cols = order_cols or [c for c in ["SourceSheet", "Exercise", "Set"] if c in work.columns]
    if sort_cols:
        work = work.sort_values(sort_cols, na_position="last")
    for col in columns:
        if col not in work.columns:
            work[col] = pd.NA
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
        detail["MuscleGroup"].dropna().astype(str).str.strip()
    )
    muscle_groups = sorted(
        g for g in muscle_groups.unique()
        if g and g.lower() not in {"unknown", "other"}
    )
    return {
        "total_exercises": int(detail["Exercise"].dropna().nunique()),
        "total_working_sets": int(detail["Set"].notna().sum()),
        "total_volume": float(detail["Volume"].sum(skipna=True)),
        "muscle_groups_trained": ", ".join(muscle_groups) if muscle_groups else "None",
    }


def workout_comparison(df: pd.DataFrame, selected_date: object) -> pd.DataFrame:
    columns = [
        "Exercise", "Current Weight", "Current Reps",
        "Previous Weight", "Previous Reps",
        "Weight Change", "Rep Change", "Status",
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
            (work["Exercise"] == exercise) & (work["Date"].dt.date < target_date.date())
        ].copy()
        if previous_rows.empty:
            records.append({
                "Exercise": exercise,
                "Current Weight": current_best["Weight"],
                "Current Reps": current_best["Reps"],
                "Previous Weight": pd.NA,
                "Previous Reps": pd.NA,
                "Weight Change": pd.NA,
                "Rep Change": pd.NA,
                "Status": "No Previous",
            })
            continue
        prev_date = previous_rows["Date"].max().date()
        prev_group = previous_rows[previous_rows["Date"].dt.date == prev_date]
        prev_best = (
            prev_group.sort_values(["Weight", "Reps"], ascending=[False, False], na_position="last")
            .iloc[0]
        )
        weight_change = current_best["Weight"] - prev_best["Weight"]
        rep_change = current_best["Reps"] - prev_best["Reps"]
        improved = (pd.notna(weight_change) and weight_change > 0) or (pd.notna(rep_change) and rep_change > 0)
        regressed = (pd.notna(weight_change) and weight_change < 0) or (pd.notna(rep_change) and rep_change < 0)
        status = "Improved" if improved else ("Regressed" if regressed else "Same")
        records.append({
            "Exercise": exercise,
            "Current Weight": current_best["Weight"],
            "Current Reps": current_best["Reps"],
            "Previous Weight": prev_best["Weight"],
            "Previous Reps": prev_best["Reps"],
            "Weight Change": weight_change,
            "Rep Change": rep_change,
            "Status": status,
        })
    return pd.DataFrame(records, columns=columns)


def session_quality_score(df: pd.DataFrame) -> pd.DataFrame:
    """0-100 quality score per session over the last 30 sessions.

    Components:
      40% — % exercises improved-or-maintained vs their previous occurrence
      30% — % reps in TARGET_REPS_MIN..TARGET_REPS_MAX range
      30% — session volume relative to personal average (capped at 100)
    """
    empty = pd.DataFrame(columns=["Date", "QualityScore"])
    if df.empty or "Date" not in df.columns or "Exercise" not in df.columns:
        return empty

    work = df.dropna(subset=["Date", "Exercise"]).copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date"])
    if work.empty:
        return empty

    work["Estimated1RM"] = work["Weight"] * (1 + work["Reps"] / 30)

    session_dates = sorted(work["Date"].dt.date.unique())
    if len(session_dates) < 2:
        return empty

    avg_volume = float(work.groupby(work["Date"].dt.date)["Volume"].sum().mean())
    recent_dates = session_dates[-30:]

    records: list[dict[str, object]] = []
    for session_date in recent_dates:
        session = work[work["Date"].dt.date == session_date]

        # --- improvement component ---
        improved_or_maintained = 0
        total_comparable = 0
        for exercise in session["Exercise"].unique():
            prev_data = work[
                (work["Exercise"] == exercise)
                & (work["Date"].dt.date < session_date)
            ]
            if prev_data.empty:
                continue
            prev_best = prev_data["Estimated1RM"].max()
            curr_best = session[session["Exercise"] == exercise]["Estimated1RM"].max()
            if pd.isna(prev_best) or pd.isna(curr_best) or prev_best <= 0:
                continue
            total_comparable += 1
            if curr_best / prev_best >= 0.98:
                improved_or_maintained += 1
        improvement_score = (improved_or_maintained / total_comparable * 100) if total_comparable > 0 else 50.0

        # --- rep adherence component ---
        reps = session["Reps"].dropna()
        if not reps.empty:
            in_range = ((reps >= TARGET_REPS_MIN) & (reps <= TARGET_REPS_MAX)).sum()
            rep_score = float(in_range) / len(reps) * 100
        else:
            rep_score = 50.0

        # --- volume component ---
        session_vol = float(session["Volume"].sum())
        volume_score = min(100.0, session_vol / avg_volume * 100) if avg_volume > 0 else 50.0

        quality = improvement_score * 0.4 + rep_score * 0.3 + volume_score * 0.3
        records.append({"Date": pd.Timestamp(session_date), "QualityScore": round(quality, 1)})

    return pd.DataFrame(records)


def minimum_effective_volume(df: pd.DataFrame) -> list[str]:
    """Flag muscle groups below TARGET_SETS sets in the most recent week."""
    if df.empty or "MuscleGroup" not in df.columns or "Date" not in df.columns:
        return []

    work = df.dropna(subset=["Date", "MuscleGroup"]).copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date"])
    work["Week"] = work["Date"].dt.to_period("W").dt.start_time

    if work.empty:
        return []

    latest_week = work["Week"].max()
    latest = work[work["Week"] == latest_week].copy()
    latest = latest[~latest["MuscleGroup"].str.lower().isin({"unknown", "other", ""})]

    if latest.empty:
        return []

    mg_sets = (
        latest.groupby("MuscleGroup", as_index=False)
        .size()
        .rename(columns={"size": "SetCount"})
    )

    week_str = latest_week.strftime("%b %d") if hasattr(latest_week, "strftime") else str(latest_week)
    warnings: list[str] = []
    for _, row in mg_sets.iterrows():
        if int(row["SetCount"]) < TARGET_SETS:
            warnings.append(
                f"{row['MuscleGroup'].title()}: only {row['SetCount']} set(s) this week "
                f"(MEV = {TARGET_SETS} sets) — week of {week_str}."
            )
    return warnings


def daily_workout_metrics(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(subset=["Date"]).copy()
    work["Estimated1RM"] = work["Weight"] * (1 + work["Reps"] / 30)
    agg = work.groupby("Date", as_index=False).agg(
        daily_volume=("Volume", "sum"),
        daily_best_e1rm=("Estimated1RM", "max"),
        daily_sets=("Set", "count"),
    )
    agg.rename(columns={"Date": "date"}, inplace=True)
    return agg.sort_values("date").reset_index(drop=True)


# ── Session grading ────────────────────────────────────────────────────────


def _score_to_grade(score: float) -> str:
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B+"
    if score >= 55:
        return "B"
    if score >= 45:
        return "C"
    if score >= 35:
        return "D"
    return "F"


def _grade_color(grade: str) -> str:
    if grade in ("A+", "A"):
        return "#e8890c"
    if grade in ("B+", "B"):
        return "#4ade80"
    if grade == "C":
        return "#f59e0b"
    return "#ef4444"


def _grade_coaching_comment(grade: str) -> str:
    if grade in ("A+", "A"):
        return "Strength holding on this cut — excellent."
    if grade == "B+":
        return "Solid cut session — consistency is key."
    if grade == "B":
        return "Expected cut performance — stay the course."
    if grade == "C":
        return "Minor regression — normal on a deficit, monitor next session."
    if grade == "D":
        return "Multiple regressions — consider 1-2 RIR this week."
    return "Recovery session needed — take a lighter day."


def grade_session(df: pd.DataFrame, session_date=None) -> dict[str, object]:
    """Grade a single training session (0-100) across four components.

    Components (weights — cut-phase calibration):
      Consistency             35% — set count relative to personal average
      Strength performance    30% — exercises improved or maintained vs previous
      Rep range adherence     20% — sets within TARGET_REPS range
      Volume vs average       15% — session volume relative to personal average
    """
    empty: dict[str, object] = {
        "date": None,
        "grade": "N/A",
        "score": 0.0,
        "strength_score": 0.0,
        "rep_adherence_score": 0.0,
        "volume_score": 0.0,
        "consistency_score": 0.0,
        "coaching_comment": "No session data.",
        "best_lift": None,
        "worst_lift": None,
        "muscle_groups": [],
        "total_volume": 0.0,
        "total_exercises": 0,
        "total_sets": 0,
        "session_found": False,
        "exercise_results": {},
    }
    if df.empty or "Date" not in df.columns or "Exercise" not in df.columns:
        return empty

    work = df.dropna(subset=["Date", "Exercise"]).copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date"])
    if work.empty:
        return empty

    work["Estimated1RM"] = work["Weight"] * (1 + work["Reps"] / 30)

    if session_date is None:
        session_date = work["Date"].max().date()
    else:
        session_date = pd.Timestamp(session_date).date()

    session = work[work["Date"].dt.date == session_date]
    if session.empty:
        return empty

    # Pre-build per-exercise history index (one pass, fast lookups)
    history = work[work["Date"].dt.date < session_date]
    hist_by_ex: dict[str, pd.DataFrame] = {}
    for ex, grp in history.groupby("Exercise"):
        hist_by_ex[str(ex)] = grp

    # ── Component 1: Strength (40%) ──────────────────────────────────────
    improved_or_maintained = 0
    total_comparable = 0
    exercise_results: dict[str, dict] = {}

    for exercise in session["Exercise"].unique():
        ex_str = str(exercise)
        curr = session[session["Exercise"] == exercise]
        curr_e1rm = curr["Estimated1RM"].max()
        curr_vol = float(curr["Volume"].sum())

        prev_grp = hist_by_ex.get(ex_str)
        if prev_grp is None or prev_grp.empty:
            exercise_results[ex_str] = {
                "status": "new", "ratio": None,
                "curr_e1rm": curr_e1rm, "prev_e1rm": None, "volume": curr_vol,
            }
            continue

        prev_e1rm = prev_grp["Estimated1RM"].max()
        if pd.isna(curr_e1rm) or pd.isna(prev_e1rm) or prev_e1rm <= 0:
            exercise_results[ex_str] = {
                "status": "no_data", "ratio": None,
                "curr_e1rm": curr_e1rm, "prev_e1rm": prev_e1rm, "volume": curr_vol,
            }
            continue

        ratio = float(curr_e1rm) / float(prev_e1rm)
        total_comparable += 1
        if ratio >= 0.98:
            improved_or_maintained += 1
            status = "improved" if ratio > 1.005 else "maintained"
        else:
            status = "regressed"

        exercise_results[ex_str] = {
            "status": status, "ratio": ratio,
            "curr_e1rm": curr_e1rm, "prev_e1rm": prev_e1rm, "volume": curr_vol,
        }

    strength_score = (improved_or_maintained / total_comparable * 100) if total_comparable > 0 else 50.0

    # ── Component 2: Rep range adherence (25%) ───────────────────────────
    reps = session["Reps"].dropna()
    if not reps.empty:
        in_range = ((reps >= TARGET_REPS_MIN) & (reps <= TARGET_REPS_MAX)).sum()
        rep_score = float(in_range) / len(reps) * 100
    else:
        rep_score = 50.0

    # ── Component 3: Volume vs average for this muscle-group combo (20%) ─
    today_volume = float(session["Volume"].sum())
    today_mgs = (
        set(session["MuscleGroup"].dropna().astype(str).str.lower().unique())
        if "MuscleGroup" in session.columns else set()
    )
    if today_mgs and not history.empty and "MuscleGroup" in history.columns:
        def _has_overlap(g: pd.DataFrame) -> bool:
            return bool(
                today_mgs & set(g["MuscleGroup"].dropna().astype(str).str.lower().unique())
            )
        hist_vols = (
            history.groupby(history["Date"].dt.date)
            .apply(lambda g: float(g["Volume"].sum()) if _has_overlap(g) else None)
            .dropna()
        )
        avg_vol = float(hist_vols.mean()) if not hist_vols.empty else today_volume
    elif not history.empty:
        avg_vol = float(history.groupby(history["Date"].dt.date)["Volume"].sum().mean())
    else:
        avg_vol = today_volume
    volume_score = min(today_volume / avg_vol * 100, 100.0) if avg_vol > 0 else 50.0

    # ── Component 4: Consistency — set count vs personal average (15%) ───
    today_sets = int(session["Set"].notna().sum())
    if not history.empty:
        avg_sets = float(history.groupby(history["Date"].dt.date)["Set"].count().mean())
    else:
        avg_sets = float(today_sets)
    consistency_score = min(today_sets / avg_sets * 100, 100.0) if avg_sets > 0 else 50.0

    # ── Composite ────────────────────────────────────────────────────────
    # Cut-phase weights: completing sets (consistency) is #1 priority
    composite = (
        strength_score * 0.30
        + rep_score * 0.20
        + volume_score * 0.15
        + consistency_score * 0.35
    )
    grade = _score_to_grade(composite)

    # ── Best / worst lift ────────────────────────────────────────────────
    valid_e1rms = {
        ex: d["curr_e1rm"]
        for ex, d in exercise_results.items()
        if d["curr_e1rm"] is not None and not pd.isna(d["curr_e1rm"])
    }
    best_lift: dict | None = None
    worst_lift: dict | None = None
    if valid_e1rms:
        best_ex = max(valid_e1rms, key=valid_e1rms.get)
        best_lift = {"exercise": best_ex, "e1rm": round(float(valid_e1rms[best_ex]), 1)}

    regressed = {
        ex: d["ratio"]
        for ex, d in exercise_results.items()
        if d["status"] == "regressed" and d["ratio"] is not None
    }
    if regressed:
        worst_ex = min(regressed, key=regressed.get)
        worst_lift = {
            "exercise": worst_ex,
            "delta_pct": round((float(regressed[worst_ex]) - 1) * 100, 1),
        }

    muscle_groups = sorted(today_mgs - {"unknown", "other", ""})

    return {
        "date": session_date,
        "grade": grade,
        "score": round(composite, 1),
        "strength_score": round(strength_score, 1),
        "rep_adherence_score": round(rep_score, 1),
        "volume_score": round(volume_score, 1),
        "consistency_score": round(consistency_score, 1),
        "coaching_comment": _grade_coaching_comment(grade),
        "best_lift": best_lift,
        "worst_lift": worst_lift,
        "muscle_groups": muscle_groups,
        "total_volume": today_volume,
        "total_exercises": len(exercise_results),
        "total_sets": today_sets,
        "session_found": True,
        "exercise_results": exercise_results,
    }


def grade_sessions_history(df: pd.DataFrame, limit: int = 30) -> pd.DataFrame:
    """Return a DataFrame with a grade row for each of the last `limit` sessions."""
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()

    work = df.dropna(subset=["Date"]).copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date"])
    session_dates = sorted(work["Date"].dt.date.unique(), reverse=True)[:limit]

    records: list[dict] = []
    for d in session_dates:
        g = grade_session(df, d)
        if not g["session_found"]:
            continue
        records.append({
            "Date": pd.Timestamp(d),
            "Grade": g["grade"],
            "Score": g["score"],
            "Muscle Groups": ", ".join(g["muscle_groups"]) if g["muscle_groups"] else "—",
            "Volume (lbs)": round(g["total_volume"]),
            "Sets": g["total_sets"],
            "_grade_group": (
                "A+/A" if g["grade"] in ("A+", "A")
                else "B+/B" if g["grade"] in ("B+", "B")
                else g["grade"]  # C, D, F
            ),
        })

    return pd.DataFrame(records)


def _weekly_coaching_summary(
    grade: str,
    vol_change_pct: float | None,
    retention_score: int,
    covered_2x: list[str],
) -> str:
    parts: list[str] = []
    if grade in ("A+", "A"):
        parts.append("Excellent training week — performance held up well across sessions.")
    elif grade in ("B+", "B"):
        parts.append("Solid week. Sessions were productive with room for minor refinement.")
    elif grade == "C":
        parts.append("Mixed week — loads were sustainable but no clear progression signal.")
    else:
        parts.append("Difficult week. Prioritise recovery and sleep before the next block.")

    if vol_change_pct is not None:
        if vol_change_pct > 12:
            parts.append(f"Volume jumped {vol_change_pct:.0f}% vs last week — monitor fatigue closely.")
        elif vol_change_pct < -15:
            parts.append(f"Volume dropped {abs(vol_change_pct):.0f}% vs last week.")
        else:
            direction = "up" if vol_change_pct >= 0 else "down"
            parts.append(f"Volume {direction} {abs(vol_change_pct):.0f}% vs last week — within normal range.")

    if retention_score >= 80:
        parts.append("Strength retention looks solid.")
    elif retention_score < 60 and retention_score > 0:
        parts.append("Strength retention needs attention — check fatigue levels.")

    return " ".join(parts)


def weekly_grade(
    df: pd.DataFrame,
    checkins: pd.DataFrame | None = None,
    num_weeks: int = 4,
) -> list[dict[str, object]]:
    """Grade the last `num_weeks` training weeks."""
    if df.empty or "Date" not in df.columns:
        return []

    work = df.dropna(subset=["Date", "Exercise"]).copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date"])
    work["Week"] = work["Date"].dt.to_period("W")
    if work.empty:
        return []

    recent_weeks = sorted(work["Week"].unique(), reverse=True)[:num_weeks]
    results: list[dict[str, object]] = []

    for i, week in enumerate(recent_weeks):
        week_start = week.start_time.date()
        week_end = week.end_time.date()
        week_session_dates = work[work["Week"] == week]["Date"].dt.date.unique()
        if len(week_session_dates) == 0:
            continue

        # Grade each session this week
        valid_grades = [
            g for d in week_session_dates
            if (g := grade_session(df, d))["session_found"]
        ]
        if not valid_grades:
            continue

        avg_score = sum(g["score"] for g in valid_grades) / len(valid_grades)
        wk_grade = _score_to_grade(avg_score)
        week_vol = float(work[work["Week"] == week]["Volume"].sum())

        # Volume change vs previous week
        vol_change_pct: float | None = None
        if i + 1 < len(recent_weeks):
            prev_week = recent_weeks[i + 1]
            prev_vol = float(work[work["Week"] == prev_week]["Volume"].sum())
            if prev_vol > 0:
                vol_change_pct = (week_vol - prev_vol) / prev_vol * 100

        # Retention for recent window (uses full df, not week-scoped)
        retention = strength_retention_score(df, weeks=2)

        # Muscle groups with 2+ sessions this week
        week_data = work[work["Week"] == week]
        covered_2x: list[str] = []
        if "MuscleGroup" in week_data.columns:
            mg_days = week_data.groupby("MuscleGroup")["Date"].nunique()
            covered_2x = [
                str(mg) for mg, d in mg_days.items()
                if d >= 2 and str(mg).lower() not in {"unknown", "other"}
            ]

        # Recovery from checkins this week
        recovery_score: int | None = None
        if checkins is not None and not checkins.empty and "Date" in checkins.columns:
            c = checkins.copy()
            c["Date"] = pd.to_datetime(c["Date"], errors="coerce")
            wk_c = c[
                (c["Date"].dt.date >= week_start)
                & (c["Date"].dt.date <= week_end)
            ]
            if not wk_c.empty:
                scores: list[float] = []
                for col in ("Energy", "Soreness", "Stress"):
                    if col in wk_c.columns:
                        val = wk_c[col].dropna().mean()
                        if pd.notna(val):
                            # Energy: higher=better; Soreness/Stress: lower=better
                            scores.append(10 - float(val) if col != "Energy" else float(val))
                if scores:
                    recovery_score = round(sum(scores) / len(scores) * 10)

        coaching = _weekly_coaching_summary(
            wk_grade, vol_change_pct, retention["score"], covered_2x
        )

        results.append({
            "week": str(week),
            "week_start": week_start,
            "week_end": week_end,
            "grade": wk_grade,
            "score": round(avg_score, 1),
            "sessions": len(valid_grades),
            "volume": round(week_vol),
            "volume_change_pct": round(vol_change_pct, 1) if vol_change_pct is not None else None,
            "retention_score": retention["score"],
            "recovery_score": recovery_score,
            "covered_2x": covered_2x,
            "coaching_summary": coaching,
        })

    return results
