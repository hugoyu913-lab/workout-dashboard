from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from config.profile import (
    ANCHOR_LIFTS,
    DAILY_CALORIES_TARGET,
    DAILY_CARBS_TARGET,
    DAILY_FAT_TARGET,
    DAILY_PROTEIN_TARGET,
    DAILY_SLEEP_MINIMUM,
    DAILY_SLEEP_TARGET,
    DAILY_STEPS_GOAL,
    MAX_MUSCLE_FREQ_PER_WEEK,
    TARGET_REPS_MAX,
    TARGET_REPS_MIN,
    TARGET_RIR,
    TARGET_SETS,
    TRAINING_DAYS_PER_WEEK,
    TRAINING_SPLIT,
)
from src.metrics import checkin_metrics, grade_sessions_history
from src.recommendations import EXERCISE_RECOMMENDATIONS_PATH

MUSCLE_GROUPS = ["chest", "back", "shoulders", "arms", "legs", "core"]
SPLIT_MUSCLES = [
    [muscle.lower() for muscle in split]
    for split in TRAINING_SPLIT
]


def _today() -> date:
    return date.today()


def _week_bounds(ref: date | None = None) -> tuple[date, date]:
    day = ref or _today()
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def _previous_week_bounds(ref: date | None = None) -> tuple[date, date]:
    start, _ = _week_bounds(ref)
    end = start - timedelta(days=1)
    return end - timedelta(days=6), end


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return int(max(low, min(high, round(value))))


def _normalise_exercise(name: str) -> str:
    return str(name).strip().lower()


def _is_anchor(exercise: str) -> bool:
    return _normalise_exercise(exercise) in {_normalise_exercise(x) for x in ANCHOR_LIFTS}


def _prep_workouts(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    work = df.copy()
    for col in ("Date", "Exercise", "Weight", "Reps", "Set", "Volume", "MuscleGroup"):
        if col not in work.columns:
            work[col] = pd.NA
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date", "Exercise"])
    if work.empty:
        return work
    work["MuscleGroup"] = work["MuscleGroup"].astype(str).str.lower().str.strip()
    work["Weight"] = pd.to_numeric(work["Weight"], errors="coerce")
    work["Reps"] = pd.to_numeric(work["Reps"], errors="coerce")
    work["Set"] = pd.to_numeric(work["Set"], errors="coerce")
    work["Estimated1RM"] = work["Weight"] * (1 + work["Reps"] / 30)
    return work


def _prep_checkins(checkins: pd.DataFrame | None) -> pd.DataFrame:
    if checkins is None or checkins.empty:
        return pd.DataFrame()
    data = checkins.copy()
    if "Date" not in data.columns:
        return pd.DataFrame()
    raw_dates = data["Date"].astype(str).str.strip()
    current_year = pd.Timestamp.now().year
    bare_month_day = raw_dates.str.match(r"^\d{1,2}/\d{1,2}$", na=False)
    normalized_dates = raw_dates.mask(bare_month_day, raw_dates + f"/{current_year}")
    data["Date"] = pd.to_datetime(normalized_dates, format="mixed", errors="coerce")
    missing = data["Date"].isna()
    if missing.any():
        data.loc[missing, "Date"] = pd.to_datetime(
            raw_dates[missing] + f"/{current_year}",
            format="mixed",
            errors="coerce",
        )
    data["Date"] = data["Date"].dt.normalize()
    data = data.dropna(subset=["Date"]).sort_values("Date")
    return data


def _checkins_status(checkins: pd.DataFrame | None) -> dict[str, object]:
    raw_rows = 0 if checkins is None else len(checkins)
    columns = [] if checkins is None else [str(col) for col in checkins.columns]
    parsed = _prep_checkins(checkins)
    latest = None if parsed.empty else parsed["Date"].max().date()
    return {
        "rows": raw_rows,
        "parsed_rows": len(parsed),
        "latest_date": latest,
        "columns": columns,
    }


def _latest_checkin(checkins: pd.DataFrame | None) -> pd.Series | None:
    data = _prep_checkins(checkins)
    if data.empty:
        return None
    return data.iloc[-1]


def _today_checkin(checkins: pd.DataFrame | None) -> pd.Series | None:
    data = _prep_checkins(checkins)
    if data.empty:
        return None
    today_rows = data[data["Date"].dt.date == _today()]
    if today_rows.empty:
        return None
    return today_rows.iloc[-1]


def _days_ago(day: date | None) -> int | None:
    if day is None:
        return None
    return (_today() - day).days


def _days_ago_label(day: date | None) -> str:
    days = _days_ago(day)
    if days is None:
        return "Never"
    if days == 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    return f"{days} days ago"


def _score_label(score: int) -> tuple[str, str, str]:
    if score >= 90:
        return "GO HARD", "peak readiness", "#22c55e"
    if score >= 70:
        return "TRAIN NORMAL", "good to go", "#4ade80"
    if score >= 50:
        return "TRAIN SMART", "manage intensity", "#f59e0b"
    if score >= 30:
        return "EASY SESSION", "2 RIR today", "#f59e0b"
    return "RECOVERY DAY", "skip or walk only", "#ef4444"


def compute_readiness(checkins: pd.DataFrame | None) -> dict[str, object]:
    score = 60
    breakdown: list[dict[str, object]] = []

    last = _latest_checkin(checkins)
    if last is not None:
        steps = pd.to_numeric(last.get("Steps"), errors="coerce")
        if pd.notna(steps):
            steps = float(steps)
            if steps > 10000:
                delta = 10
            elif steps >= 7500:
                delta = 5
            elif steps >= 5000:
                delta = 0
            else:
                delta = -10
            score += delta
            breakdown.append({"label": "Steps", "delta": delta, "note": f"{steps:,.0f} today"})

        sleep = pd.to_numeric(last.get("SleepHours"), errors="coerce")
        if pd.notna(sleep):
            sleep = float(sleep)
            delta = -20 if sleep < 6 else (-5 if sleep < 7 else (10 if sleep < 8 else 15))
            score += delta
            breakdown.append({"label": "Sleep", "delta": delta, "note": f"{sleep:.1f}h last night"})

        soreness = pd.to_numeric(last.get("Soreness"), errors="coerce")
        if pd.notna(soreness):
            soreness = float(soreness)
            delta = 10 if soreness <= 3 else (-20 if soreness >= 7 else 0)
            score += delta
            breakdown.append({"label": "Soreness", "delta": delta, "note": f"{soreness:.0f}/10"})

        stress = pd.to_numeric(last.get("Stress"), errors="coerce")
        if pd.notna(stress):
            stress = float(stress)
            delta = 10 if stress <= 3 else (-15 if stress >= 7 else 0)
            score += delta
            breakdown.append({"label": "Stress", "delta": delta, "note": f"{stress:.0f}/10"})

    final_score = _clamp(score)
    label, subtitle, color = _score_label(final_score)
    return {
        "score": final_score,
        "label": f"{label} - {subtitle}",
        "color": color,
        "breakdown": breakdown,
        "has_checkins": last is not None,
    }


def _muscle_group_trend(history: pd.DataFrame) -> str:
    if history.empty:
        return "Maintaining"
    daily = (
        history.dropna(subset=["Estimated1RM"])
        .groupby(history["Date"].dt.date)["Estimated1RM"]
        .max()
        .sort_index()
        .tail(3)
    )
    if len(daily) < 2:
        return "Maintaining"
    first = float(daily.iloc[0])
    last = float(daily.iloc[-1])
    if last > first * 1.01:
        return "Improving"
    if last < first * 0.99:
        return "Declining"
    return "Maintaining"


def weekly_muscle_checklist(df: pd.DataFrame | None, ref: date | None = None) -> list[dict[str, object]]:
    today = ref or _today()
    week_start, week_end = _week_bounds(today)
    work = _prep_workouts(df)
    days_into_week = today.weekday()
    rows: list[dict[str, object]] = []

    for muscle in MUSCLE_GROUPS:
        all_rows = work[work["MuscleGroup"] == muscle] if not work.empty else pd.DataFrame()
        week_rows = all_rows[
            (all_rows["Date"].dt.date >= week_start)
            & (all_rows["Date"].dt.date <= today)
        ] if not all_rows.empty else pd.DataFrame()

        sessions = int(week_rows["Date"].dt.date.nunique()) if not week_rows.empty else 0
        sets = int(week_rows["Set"].notna().sum()) if not week_rows.empty else 0
        last_date = None if all_rows.empty else all_rows["Date"].dt.date.max()

        if sessions >= MAX_MUSCLE_FREQ_PER_WEEK:
            status, color = "Overreached", "#f97316"
        elif sessions == 0 and (days_into_week >= 3 or today >= week_end):
            status, color = "Undertrained", "#ef4444"
        elif days_into_week >= 2 and (sessions == 1 or sets < TARGET_SETS * 2):
            status, color = "Needs attention", "#f59e0b"
        elif sessions >= 2 and sets >= TARGET_SETS * 2:
            status, color = "On track", "#22c55e"
        else:
            status, color = "Pending", "#555560"

        rows.append({
            "muscle_group": muscle.title(),
            "muscle_key": muscle,
            "sessions": sessions,
            "sets": sets,
            "status": status,
            "color": color,
            "last_trained": _days_ago_label(last_date),
            "last_date": last_date,
            "trend": _muscle_group_trend(all_rows),
        })
    return rows


def _load_exercise_recs(path: Path = EXERCISE_RECOMMENDATIONS_PATH) -> pd.DataFrame:
    columns = ["muscle_group", "category", "exercise", "priority"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        recs = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame(columns=columns)
    recs.columns = [c.strip().lower() for c in recs.columns]
    for col in columns:
        if col not in recs.columns:
            recs[col] = ""
    recs["muscle_key"] = recs["muscle_group"].str.lower().str.strip()
    recs["priority_rank"] = recs["priority"].str.lower().map({"high": 0, "medium": 1, "low": 2}).fillna(9)
    stable_terms = ("machine", "supported", "cable", "pulldown", "row", "press")
    recs["stable_rank"] = recs.apply(
        lambda row: 0 if any(term in f"{row['category']} {row['exercise']}".lower() for term in stable_terms) else 1,
        axis=1,
    )
    return recs


def _target_muscles(checklist: list[dict[str, object]], readiness: int) -> list[str]:
    undertrained = [r for r in checklist if r["status"] == "Undertrained"]
    attention = [r for r in checklist if r["status"] == "Needs attention"]
    candidates = undertrained + attention
    if readiness < 50:
        easy = [r for r in candidates if r["muscle_key"] in {"arms", "core", "back", "shoulders"}]
        candidates = easy or candidates
    if candidates:
        return [str(r["muscle_key"]) for r in candidates[:3]]
    ordered = sorted(
        [r for r in checklist if r["last_date"] is not None],
        key=lambda r: r["last_date"],
    )
    return [str(ordered[0]["muscle_key"])] if ordered else ["chest", "back"]


def _split_label(muscles: list[str]) -> str:
    return " + ".join(muscle.title() for muscle in muscles)


def _split_score(split: list[str], checklist: list[dict[str, object]], target_muscles: list[str]) -> float:
    by_muscle = {str(row["muscle_key"]): row for row in checklist}
    target_set = set(target_muscles)
    score = 0.0
    for muscle in split:
        row = by_muscle.get(muscle)
        if row is None:
            continue
        sessions = int(row["sessions"])
        days_since = _days_ago(row["last_date"]) if row["last_date"] is not None else 99
        if muscle in target_set:
            score += 50
        score += max(0, 2 - sessions) * 18
        score += min(days_since or 0, 10) * 2
        if row["status"] == "Undertrained":
            score += 25
        elif row["status"] == "Needs attention":
            score += 15
        elif row["status"] == "Overreached":
            score -= 35
    return score


def _best_split(checklist: list[dict[str, object]], target_muscles: list[str], readiness: int) -> tuple[list[str], str]:
    candidates = SPLIT_MUSCLES or [["chest", "back"]]
    if readiness < 50:
        candidates = [split for split in candidates if "legs" not in split] or candidates
    scored = [
        (idx, split, _split_score(split, checklist, target_muscles))
        for idx, split in enumerate(candidates)
    ]
    _, split, _ = max(scored, key=lambda item: (item[2], -item[0]))
    return split, _split_label(split)


def _focus_for_muscles(
    muscles: list[str],
    readiness: int,
    checklist: list[dict[str, object]],
) -> tuple[str, str, list[str]]:
    if readiness < 30:
        return "Recovery", "Readiness is below 30, so recovery protects strength retention.", []
    if readiness < 50 and not muscles:
        return "Recovery", "Readiness is low and no frequency gap is urgent.", []

    split, focus = _best_split(checklist, muscles, readiness)
    primary = muscles[0] if muscles else split[0]
    if readiness < 50:
        return focus, f"{focus} best covers the easiest priority gap without high recovery cost.", split
    return focus, f"{primary.title()} has the clearest frequency, recency, or regression gap this week.", split


def _last_performance(work: pd.DataFrame, exercise: str) -> tuple[float | None, float | None]:
    if work.empty:
        return None, None
    rows = work[work["Exercise"].astype(str).str.lower().str.strip() == _normalise_exercise(exercise)]
    rows = rows.dropna(subset=["Weight", "Reps", "Date"])
    if rows.empty:
        return None, None
    last_date = rows["Date"].max().date()
    session = rows[rows["Date"].dt.date == last_date].sort_values(["Weight", "Reps"], ascending=[False, False])
    row = session.iloc[0]
    return float(row["Weight"]), float(row["Reps"])


def _exercise_targets(df: pd.DataFrame | None, muscles: list[str], readiness: int) -> list[dict[str, object]]:
    work = _prep_workouts(df)
    recs = _load_exercise_recs()
    selected: list[dict[str, object]] = []
    used: set[str] = set()

    if not recs.empty:
        for muscle in muscles:
            rows = recs[recs["muscle_key"] == muscle].copy()
            if rows.empty:
                continue
            sort_cols = ["stable_rank", "priority_rank", "exercise"] if readiness < 70 else ["priority_rank", "exercise"]
            for row in rows.sort_values(sort_cols).itertuples(index=False):
                exercise = str(row.exercise).strip()
                key = _normalise_exercise(exercise)
                if not exercise or key in used:
                    continue
                last_w, last_r = _last_performance(work, exercise)
                clean = last_r is not None and last_r >= TARGET_REPS_MAX
                target_w = (last_w + 2.5) if last_w is not None and clean else last_w
                selected.append({
                    "exercise": exercise,
                    "muscle_group": muscle,
                    "sets": TARGET_SETS,
                    "rep_range": f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}",
                    "rir": TARGET_RIR,
                    "last_weight": last_w,
                    "last_reps": last_r,
                    "target_weight": target_w,
                    "target_reps": TARGET_REPS_MIN if target_w is not None else None,
                    "is_anchor": _is_anchor(exercise),
                })
                used.add(key)
                if len(selected) >= 3:
                    return selected

    if not work.empty:
        fallback = work[work["MuscleGroup"].isin(muscles)].sort_values("Date", ascending=False)
        for exercise in fallback["Exercise"].dropna().astype(str).unique():
            key = _normalise_exercise(exercise)
            if key in used:
                continue
            last_w, last_r = _last_performance(work, exercise)
            selected.append({
                "exercise": exercise,
                "muscle_group": "",
                "sets": TARGET_SETS,
                "rep_range": f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}",
                "rir": TARGET_RIR,
                "last_weight": last_w,
                "last_reps": last_r,
                "target_weight": last_w,
                "target_reps": TARGET_REPS_MIN if last_w is not None else None,
                "is_anchor": _is_anchor(exercise),
            })
            used.add(key)
            if len(selected) >= 3:
                break
    return selected


def generate_game_plan(df: pd.DataFrame | None, readiness_score: int, checklist: list[dict[str, object]]) -> dict[str, object]:
    muscles = [] if readiness_score < 30 else _target_muscles(checklist, readiness_score)
    focus, reason, split_muscles = _focus_for_muscles(muscles, readiness_score, checklist)
    if readiness_score >= 70:
        intensity = "Work to 0-1 RIR - push the last set"
    elif readiness_score >= 50:
        intensity = "Work to 1-2 RIR - leave a rep in the tank"
    else:
        intensity = "Work to 2-3 RIR - protect the joints"
    return {
        "focus": focus,
        "reason": reason,
        "exercises": [] if focus == "Recovery" else _exercise_targets(df, split_muscles or muscles, readiness_score),
        "intensity": intensity,
    }


def weekly_progress_tracker(df: pd.DataFrame | None, checkins: pd.DataFrame | None) -> dict[str, object]:
    work = _prep_workouts(df)
    today = _today()
    week_start, _ = _week_bounds(today)
    prev_start, prev_end = _previous_week_bounds(today)

    def session_count(start: date, end: date) -> int:
        if work.empty:
            return 0
        rows = work[(work["Date"].dt.date >= start) & (work["Date"].dt.date <= end)]
        return int(rows["Date"].dt.date.nunique()) if not rows.empty else 0

    this_week = work[(work["Date"].dt.date >= week_start) & (work["Date"].dt.date <= today)] if not work.empty else pd.DataFrame()
    hit_2x = 0
    if not this_week.empty:
        hit_2x = int((this_week.groupby("MuscleGroup")["Date"].apply(lambda s: s.dt.date.nunique()) >= 2).sum())

    anchor_total = 0
    anchor_kept = 0
    if not work.empty:
        for exercise in sorted(work["Exercise"].dropna().astype(str).unique()):
            if not _is_anchor(exercise):
                continue
            daily = (
                work[work["Exercise"] == exercise]
                .dropna(subset=["Estimated1RM"])
                .groupby(work[work["Exercise"] == exercise]["Date"].dt.date)["Estimated1RM"]
                .max()
                .sort_index()
            )
            if len(daily) >= 2:
                anchor_total += 1
                if float(daily.iloc[-1]) >= float(daily.iloc[-2]) * 0.98:
                    anchor_kept += 1
    strength_pct = round(anchor_kept / anchor_total * 100) if anchor_total else None

    metrics = checkin_metrics(_prep_checkins(checkins))
    cut_pace = metrics.get("weekly_weight_loss_rate")
    cut_pace_value = None if pd.isna(cut_pace) else float(cut_pace)

    recovery_avg = None
    avg_steps = None
    avg_protein = None
    avg_sleep = None
    avg_calories = None
    all_targets_days = 0
    perfect_streak = 0
    c = _prep_checkins(checkins)
    if not c.empty:
        week_c = c[(c["Date"].dt.date >= week_start) & (c["Date"].dt.date <= today)]
        values: list[float] = []
        for col in ("Energy", "Soreness", "Stress"):
            if col in week_c.columns:
                avg = pd.to_numeric(week_c[col], errors="coerce").dropna().mean()
                if pd.notna(avg):
                    values.append(float(avg) if col == "Energy" else 10 - float(avg))
        if values:
            recovery_avg = round(sum(values) / len(values), 1)

        if not week_c.empty:
            if "Steps" in week_c.columns:
                val = pd.to_numeric(week_c["Steps"], errors="coerce").dropna().mean()
                avg_steps = None if pd.isna(val) else round(float(val))
            if "Protein" in week_c.columns:
                val = pd.to_numeric(week_c["Protein"], errors="coerce").dropna().mean()
                avg_protein = None if pd.isna(val) else round(float(val), 1)
            if "SleepHours" in week_c.columns:
                val = pd.to_numeric(week_c["SleepHours"], errors="coerce").dropna().mean()
                avg_sleep = None if pd.isna(val) else round(float(val), 1)
            if "Calories" in week_c.columns:
                val = pd.to_numeric(week_c["Calories"], errors="coerce").dropna().mean()
                avg_calories = None if pd.isna(val) else round(float(val))

            target_cols = ["Steps", "Calories", "Protein", "SleepHours"]
            if all(col in week_c.columns for col in target_cols):
                complete = week_c.dropna(subset=target_cols).copy()
                if not complete.empty:
                    hit = (
                        (complete["Steps"] >= DAILY_STEPS_GOAL)
                        & (complete["Calories"].between(DAILY_CALORIES_TARGET * 0.9, DAILY_CALORIES_TARGET * 1.1))
                        & (complete["Protein"] >= DAILY_PROTEIN_TARGET)
                        & (complete["SleepHours"] >= DAILY_SLEEP_MINIMUM)
                    )
                    all_targets_days = int(hit.sum())

            if all(col in c.columns for col in target_cols):
                complete_all = c.dropna(subset=target_cols).sort_values("Date", ascending=False)
                for row in complete_all.itertuples(index=False):
                    if (
                        float(getattr(row, "Steps")) >= DAILY_STEPS_GOAL
                        and DAILY_CALORIES_TARGET * 0.9 <= float(getattr(row, "Calories")) <= DAILY_CALORIES_TARGET * 1.1
                        and float(getattr(row, "Protein")) >= DAILY_PROTEIN_TARGET
                        and float(getattr(row, "SleepHours")) >= DAILY_SLEEP_MINIMUM
                    ):
                        perfect_streak += 1
                    else:
                        break

    return {
        "this_sessions": session_count(week_start, today),
        "last_sessions": session_count(prev_start, prev_end),
        "hit_2x": hit_2x,
        "strength_pct": strength_pct,
        "cut_pace": cut_pace_value,
        "recovery_avg": recovery_avg,
        "avg_steps": avg_steps,
        "avg_protein": avg_protein,
        "avg_sleep": avg_sleep,
        "avg_calories": avg_calories,
        "all_targets_days": all_targets_days,
        "perfect_streak": perfect_streak,
        "checkins_rows": len(c),
    }


def weekly_warnings(df: pd.DataFrame | None, checkins: pd.DataFrame | None) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    work = _prep_workouts(df)
    today = _today()

    if not work.empty:
        for exercise in sorted(work["Exercise"].dropna().astype(str).unique()):
            if not _is_anchor(exercise):
                continue
            rows = work[work["Exercise"] == exercise].dropna(subset=["Estimated1RM"])
            daily = rows.groupby(rows["Date"].dt.date)["Estimated1RM"].max().sort_index()
            if len(daily) >= 3 and daily.iloc[-1] < daily.iloc[-2] * 0.98 and daily.iloc[-2] < daily.iloc[-3] * 0.98:
                warnings.append({
                    "icon": "⚓",
                    "title": f"{exercise} regressed twice",
                    "explanation": "Estimated 1RM dropped across the last two exposures.",
                    "action": "Consider deload or form check.",
                })

        for muscle in MUSCLE_GROUPS:
            rows = work[work["MuscleGroup"] == muscle]
            last_date = None if rows.empty else rows["Date"].dt.date.max()
            days = _days_ago(last_date)
            if days is not None and days >= 5:
                warnings.append({
                    "icon": "🎯",
                    "title": f"{muscle.title()} frequency gap",
                    "explanation": f"{muscle.title()} has not been trained in {days} days.",
                    "action": f"Priority: train {muscle} today.",
                })

        grades = grade_sessions_history(work, limit=3)
        if not grades.empty and len(grades) >= 3 and all(g in {"D", "F"} for g in grades["Grade"].head(3)):
            warnings.append({
                "icon": "🔴",
                "title": "Three low-grade sessions",
                "explanation": "The last three graded sessions were D/F.",
                "action": "Recovery week recommended.",
            })

    c = _prep_checkins(checkins)
    if not c.empty:
        if "Steps" in c.columns:
            steps = pd.to_numeric(c["Steps"], errors="coerce").dropna()
            if len(steps) >= 3 and steps.tail(3).lt(5000).all():
                warnings.append({
                    "icon": "👟",
                    "title": "Low activity outside gym",
                    "explanation": "Steps have been below 5k for 3 straight days.",
                    "action": "Add 20 min walks.",
                })

        if "SleepHours" in c.columns:
            sleep_recent = pd.to_numeric(c["SleepHours"], errors="coerce").dropna()
            if len(sleep_recent) >= 2 and sleep_recent.tail(2).lt(DAILY_SLEEP_MINIMUM).all():
                warnings.append({
                    "icon": "🌙",
                    "title": "Sleep debt accumulating",
                    "explanation": f"Sleep has been below {DAILY_SLEEP_MINIMUM:.1f}h for 2 nights.",
                    "action": "Prioritize sleep tonight.",
                })

        if "Protein" in c.columns:
            protein = pd.to_numeric(c["Protein"], errors="coerce").dropna()
            if len(protein) >= 3 and protein.tail(3).lt(DAILY_PROTEIN_TARGET).all():
                warnings.append({
                    "icon": "🥤",
                    "title": "Protein consistently low",
                    "explanation": "Protein has been below target for 3 straight days.",
                    "action": "Add a shake post-workout.",
                })

        if "Calories" in c.columns:
            calories = pd.to_numeric(c["Calories"], errors="coerce").dropna()
            if len(calories) >= 3 and calories.tail(3).lt(DAILY_CALORIES_TARGET * 0.7).all():
                warnings.append({
                    "icon": "🍽️",
                    "title": "Deficit too deep",
                    "explanation": "Calories have been under 70% of target for 3 straight days.",
                    "action": "You're risking muscle loss - increase food intake.",
                })

        metrics = checkin_metrics(c)
        pace = metrics.get("weekly_weight_loss_rate")
        current_weight = metrics.get("bodyweight_7day_avg")
        if not pd.isna(pace) and not pd.isna(current_weight) and float(current_weight) > 0:
            pct = float(pace) / float(current_weight) * 100
            if pct > 1:
                warnings.append({
                    "icon": "⚡",
                    "title": "Cut pace too aggressive",
                    "explanation": f"Bodyweight is dropping about {pct:.1f}% per week.",
                    "action": "Increase calories by 200 - too aggressive.",
                })
            elif pct < 0.3:
                warnings.append({
                    "icon": "📉",
                    "title": "Cut pace stalled",
                    "explanation": f"Bodyweight is dropping about {pct:.1f}% per week.",
                    "action": "Reduce calories by 150 - cut stalled.",
                })

        week_start, _ = _week_bounds(today)
        week_c = c[(c["Date"].dt.date >= week_start) & (c["Date"].dt.date <= today)]
        if "SleepHours" in week_c.columns:
            sleep = pd.to_numeric(week_c["SleepHours"], errors="coerce").dropna()
            if not sleep.empty and float(sleep.mean()) < 6.5:
                warnings.append({
                    "icon": "🌙",
                    "title": "Sleep is limiting recovery",
                    "explanation": f"Sleep is averaging {float(sleep.mean()):.1f}h this week.",
                    "action": "Sleep is limiting your recovery.",
                })

    return warnings


def _card(title: str, body: str, border: str = "#1e1e22") -> str:
    return f"""
    <div style="background:#111113;border:1px solid #1e1e22;border-left:4px solid {border};
                border-radius:4px;padding:1rem 1.1rem;min-height:132px;">
      <div style="font-family:'Bebas Neue',cursive;font-size:1.05rem;letter-spacing:0.12em;
                  color:#f0f0f2;margin-bottom:0.55rem;">{escape(title)}</div>
      {body}
    </div>
    """


def _small_line(label: str, value: object, color: str = "#c8c8cc") -> str:
    return (
        "<div style=\"display:flex;justify-content:space-between;gap:1rem;"
        "font-size:0.68rem;color:#777782;margin-top:0.35rem;\">"
        f"<span>{escape(label)}</span><span style=\"color:{color};\">{escape(str(value))}</span></div>"
    )


def _target_status(current: float | None, target: float) -> tuple[float, str, str]:
    if current is None or pd.isna(current):
        return 0.0, "#555560", "No data"
    pct = float(current) / target if target > 0 else 0.0
    if pct >= 0.9:
        return min(pct, 1.0), "#22c55e", "OK"
    if pct >= 0.7:
        return pct, "#f59e0b", "WARN"
    return max(pct, 0.02), "#ef4444", "LOW"


def _fmt_target_value(value: float | None, unit: str = "") -> str:
    if value is None or pd.isna(value):
        return "No data"
    if unit == "h":
        return f"{float(value):g}h"
    if unit == "g":
        return f"{float(value):g}g"
    return f"{float(value):,.0f}"


def _render_today_targets(checkins: pd.DataFrame | None, spreadsheet_id: str | None = None) -> None:
    st.markdown("### TODAY'S TARGETS")
    row = _today_checkin(checkins)
    if row is None:
        latest = _latest_checkin(checkins)
        sheet_link = ""
        if spreadsheet_id:
            url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
            sheet_link = f"<div style='margin-top:0.5rem;'><a href='{url}' target='_blank' style='color:#e8890c;'>Open Checkins sheet</a></div>"
        if latest is not None:
            latest_date = pd.Timestamp(latest["Date"]).strftime("%Y-%m-%d")
            message = f"Latest checkin found: {latest_date}. Add today's row for full daily targets."
            row = latest
        else:
            message = "Log today's checkins to see targets."
            st.markdown(
                _card(
                    "Daily Lifestyle Targets",
                    f"<div style='font-size:0.75rem;color:#c8c8cc;'>{escape(message)}</div>" + sheet_link,
                    "#555560",
                ),
                unsafe_allow_html=True,
            )
            return
        st.caption(message)

    targets = [
        ("STEPS", "Steps", DAILY_STEPS_GOAL, ""),
        ("CALORIES", "Calories", DAILY_CALORIES_TARGET, ""),
        ("PROTEIN", "Protein", DAILY_PROTEIN_TARGET, "g"),
        ("CARBS", "Carbs", DAILY_CARBS_TARGET, "g"),
        ("FAT", "Fat", DAILY_FAT_TARGET, "g"),
        ("SLEEP", "SleepHours", DAILY_SLEEP_TARGET, "h"),
    ]

    available = [
        column for _, column, _, _ in targets
        if pd.notna(pd.to_numeric(row.get(column), errors="coerce"))
    ]
    if not available:
        st.markdown(
            _card(
                "Daily Lifestyle Targets",
                "<div style='font-size:0.75rem;color:#c8c8cc;'>Checkin row found, but no lifestyle targets are filled yet.</div>" + sheet_link,
                "#555560",
            ),
            unsafe_allow_html=True,
        )
        return
    for label, column, target, unit in targets:
        current_raw = pd.to_numeric(row.get(column), errors="coerce")
        current = None if pd.isna(current_raw) else float(current_raw)
        fill, color, status = _target_status(current, float(target))
        pct = 0 if current is None else round(current / float(target) * 100)
        icon = "✅" if status == "OK" else ("⚠️" if status == "WARN" else "❌")
        value = f"{_fmt_target_value(current, unit)} / {_fmt_target_value(float(target), unit)}"
        st.markdown(
            f"""
            <div style="display:grid;grid-template-columns:110px 1fr 70px 48px;gap:0.75rem;
                        align-items:center;font-size:0.72rem;color:#c8c8cc;margin:0.35rem 0;">
              <div style="letter-spacing:0.12em;color:#777782;">{label}</div>
              <div>{escape(value)}</div>
              <div style="color:{color};text-align:right;">{pct}%</div>
              <div style="color:{color};text-align:right;">{icon}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.progress(fill)


def _render_readiness(readiness: dict[str, object]) -> None:
    st.markdown("### DAILY READINESS CHECK")
    score = int(readiness["score"])
    color = str(readiness["color"])
    st.markdown(
        f"""
        <div style="background:#111113;border:1px solid #1e1e22;border-left:4px solid {color};
                    border-radius:4px;padding:1.15rem 1.25rem;margin-bottom:0.75rem;">
          <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;flex-wrap:wrap;">
            <div>
              <div style="font-family:'Bebas Neue',cursive;font-size:3rem;line-height:1;color:{color};
                          letter-spacing:0.08em;">{score}/100</div>
              <div style="font-family:'Bebas Neue',cursive;font-size:1.35rem;color:#f0f0f2;
                          letter-spacing:0.12em;">{escape(str(readiness["label"]))}</div>
            </div>
            <div style="font-size:0.62rem;color:#555560;letter-spacing:0.12em;text-transform:uppercase;">
              Last updated {datetime.now().strftime("%Y-%m-%d %I:%M %p")}
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.progress(score / 100)
    if not readiness["has_checkins"]:
        st.caption("Add Checkins tab for full readiness score")
    if not readiness["breakdown"]:
        st.caption("No Checkins readiness inputs found. Baseline score shown.")
    else:
        cols = st.columns(min(5, len(readiness["breakdown"])))
        for col, item in zip(cols, readiness["breakdown"]):
            delta = int(item["delta"])
            delta_label = f"{delta:+d}"
            col.metric(str(item["label"]), delta_label, str(item["note"]))


def _render_checkins_status(checkins: pd.DataFrame | None) -> None:
    status = _checkins_status(checkins)
    latest = status["latest_date"]
    latest_label = latest.strftime("%Y-%m-%d") if latest is not None else "None"
    columns = ", ".join(status["columns"]) if status["columns"] else "None"
    st.caption(
        f"Checkins rows loaded: {status['rows']} | "
        f"Parsed rows: {status['parsed_rows']} | "
        f"Latest checkin date: {latest_label} | "
        f"Columns detected: {columns}"
    )


def _render_checklist(checklist: list[dict[str, object]]) -> None:
    st.markdown("### MUSCLE GROUP CHECKLIST")
    for row_group in (checklist[:3], checklist[3:]):
        cols = st.columns(3)
        for col, row in zip(cols, row_group):
            body = (
                _small_line("Sessions this week", row["sessions"])
                + _small_line("Sets this week", row["sets"])
                + _small_line("Status", row["status"], str(row["color"]))
                + _small_line("Last trained", row["last_trained"])
                + _small_line("Trend", row["trend"])
            )
            col.markdown(_card(str(row["muscle_group"]), body, str(row["color"])), unsafe_allow_html=True)


def _format_last(weight: float | None, reps: float | None) -> str:
    if weight is None or reps is None:
        return "No prior logged performance"
    return f"{weight:g} x {reps:g}"


def _format_target(weight: float | None, reps: float | None) -> str:
    if weight is None or reps is None:
        return f"{TARGET_SETS} x {TARGET_REPS_MIN}-{TARGET_REPS_MAX} @ target RIR"
    return f"{weight:g} x {reps:g}"


def _render_game_plan(plan: dict[str, object]) -> None:
    st.markdown("### TODAY'S GAME PLAN")
    st.markdown(
        _card(
            f"Recommended Focus: {plan['focus']}",
            f"<div style='font-size:0.75rem;color:#c8c8cc;'>{escape(str(plan['reason']))}</div>"
            f"<div style='font-size:0.7rem;color:#e8890c;margin-top:0.65rem;'>{escape(str(plan['intensity']))}</div>",
            "#e8890c",
        ),
        unsafe_allow_html=True,
    )
    exercises = plan.get("exercises", [])
    if not exercises:
        st.caption("Recovery plan: walk, mobility, and no hard sets today.")
        return
    cols = st.columns(len(exercises))
    for col, ex in zip(cols, exercises):
        name = str(ex["exercise"])
        title = f"{'⚓ ' if ex['is_anchor'] else ''}{name}"
        body = (
            _small_line("Target", f"{ex['sets']} x {ex['rep_range']} @ {ex['rir']} RIR")
            + _small_line("Last performance", _format_last(ex["last_weight"], ex["last_reps"]))
            + _small_line("Target today", _format_target(ex["target_weight"], ex["target_reps"]), "#e8890c")
        )
        col.markdown(_card(title, body, "#e8890c" if ex["is_anchor"] else "#1e1e22"), unsafe_allow_html=True)


def _progress_status(value: float | None, green_at: float, amber_at: float) -> tuple[float, str, str]:
    if value is None:
        return 0, "#555560", "No data"
    if value >= green_at:
        return min(value / green_at, 1.0), "#22c55e", "On track"
    if value >= amber_at:
        return max(value / green_at, 0.05), "#f59e0b", "Borderline"
    return max(value / green_at, 0.02), "#ef4444", "Off track"


def _render_progress(progress: dict[str, object]) -> None:
    st.markdown("### WEEKLY PROGRESS TRACKER")
    rows = [
        ("Total sessions", f"{progress['this_sessions']} vs {progress['last_sessions']}", float(progress["this_sessions"]), TRAINING_DAYS_PER_WEEK * 0.8, 3),
        ("Muscle groups hit 2x+", f"{progress['hit_2x']}/6", float(progress["hit_2x"]), 5, 3),
        ("Strength trend", "No anchor data" if progress["strength_pct"] is None else f"{progress['strength_pct']}% maintained/improved", None if progress["strength_pct"] is None else float(progress["strength_pct"]), 80, 60),
        ("Cut pace", "No checkin data" if progress["cut_pace"] is None else f"{progress['cut_pace']:.2f} lbs/week", None if progress["cut_pace"] is None else 100 - abs(float(progress["cut_pace"]) - 0.75) * 100, 75, 50),
        ("Recovery average", "No checkin data" if progress["recovery_avg"] is None else f"{progress['recovery_avg']}/10", None if progress["recovery_avg"] is None else float(progress["recovery_avg"]), 7, 5),
    ]
    cols = st.columns(5)
    for col, (label, value_label, value, green_at, amber_at) in zip(cols, rows):
        fill, color, status = _progress_status(value, green_at, amber_at)
        col.markdown(_card(label, _small_line(value_label, status, color), color), unsafe_allow_html=True)
        col.progress(fill)

    st.markdown("#### Lifestyle")
    empty_label = "No checkin rows" if progress.get("checkins_rows", 0) == 0 else "Not filled"
    lifestyle_rows = [
        ("Avg daily steps", empty_label if progress["avg_steps"] is None else f"{progress['avg_steps']:,.0f} / {DAILY_STEPS_GOAL:,}", None if progress["avg_steps"] is None else float(progress["avg_steps"]), DAILY_STEPS_GOAL * 0.9, DAILY_STEPS_GOAL * 0.7),
        ("Avg protein", empty_label if progress["avg_protein"] is None else f"{progress['avg_protein']:.0f}g / {DAILY_PROTEIN_TARGET}g", None if progress["avg_protein"] is None else float(progress["avg_protein"]), DAILY_PROTEIN_TARGET * 0.9, DAILY_PROTEIN_TARGET * 0.7),
        ("Avg sleep", empty_label if progress["avg_sleep"] is None else f"{progress['avg_sleep']:.1f}h / {DAILY_SLEEP_TARGET:g}h", None if progress["avg_sleep"] is None else float(progress["avg_sleep"]), DAILY_SLEEP_TARGET * 0.9, DAILY_SLEEP_MINIMUM),
        ("Avg calories", empty_label if progress["avg_calories"] is None else f"{progress['avg_calories']:,.0f} / {DAILY_CALORIES_TARGET:,}", None if progress["avg_calories"] is None else 100 - abs(float(progress["avg_calories"]) - DAILY_CALORIES_TARGET) / DAILY_CALORIES_TARGET * 100, 90, 70),
        ("All-target days", f"{progress['all_targets_days']} this week", float(progress["all_targets_days"]), 4, 2),
        ("Perfect streak", f"{progress['perfect_streak']} days", float(progress["perfect_streak"]), 3, 1),
    ]
    for start in range(0, len(lifestyle_rows), 3):
        cols = st.columns(3)
        for col, (label, value_label, value, green_at, amber_at) in zip(cols, lifestyle_rows[start:start + 3]):
            fill, color, status = _progress_status(value, green_at, amber_at)
            col.markdown(_card(label, _small_line(value_label, status, color), color), unsafe_allow_html=True)
            col.progress(fill)


def _render_warnings(warnings: list[dict[str, str]]) -> None:
    st.markdown("### WEEKLY WARNINGS & ACTIONS")
    if not warnings:
        st.success("No high-priority warnings this week.")
        return
    for row_group_start in range(0, len(warnings), 3):
        cols = st.columns(3)
        for col, warning in zip(cols, warnings[row_group_start:row_group_start + 3]):
            body = (
                f"<div style='font-size:0.72rem;color:#888890;margin-bottom:0.55rem;'>{escape(warning['explanation'])}</div>"
                f"<div style='font-size:0.72rem;color:#e8890c;'>Action: {escape(warning['action'])}</div>"
            )
            col.markdown(_card(f"{warning['icon']} - {warning['title']}", body, "#ef4444"), unsafe_allow_html=True)


def render_coach_page(
    df: pd.DataFrame,
    checkins: pd.DataFrame | None = None,
    spreadsheet_id: str | None = None,
) -> None:
    readiness = compute_readiness(checkins)
    checklist = weekly_muscle_checklist(df)
    plan = generate_game_plan(df, int(readiness["score"]), checklist)
    progress = weekly_progress_tracker(df, checkins)
    warnings = weekly_warnings(df, checkins)

    _render_readiness(readiness)
    _render_checkins_status(checkins)
    st.divider()
    _render_today_targets(checkins, spreadsheet_id)
    st.divider()
    _render_checklist(checklist)
    st.divider()
    _render_game_plan(plan)
    st.divider()
    _render_progress(progress)
    st.divider()
    _render_warnings(warnings)
