from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from config.profile import (
    ANCHOR_LIFTS,
    CUT_RATE_MAX,
    CUT_RATE_MIN,
    DAILY_CALORIES_TARGET,
    DAILY_CARBS_TARGET,
    DAILY_FAT_TARGET,
    DAILY_PROTEIN_TARGET,
    DAILY_SLEEP_MINIMUM,
    DAILY_SLEEP_TARGET,
    DAILY_STEPS_TARGET,
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
from src.fatigue import fatigue_risk_detector
from src.sheets_client import append_checkin_row

MUSCLE_GROUPS = ["chest", "back", "shoulders", "arms", "legs", "core"]
SPLIT_MUSCLES = [
    [muscle.lower() for muscle in split]
    for split in TRAINING_SPLIT
]
SPLIT_DAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
_ANCHOR_GROUP_TO_MUSCLE: dict[str, str] = {
    "Chest": "chest",
    "Back": "back",
    "Biceps": "arms",
    "Triceps": "arms",
    "Legs": "legs",
    "Shoulders": "shoulders",
}


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
    return _normalise_exercise(exercise) in {_normalise_exercise(x) for x in _anchor_lift_names()}


def _anchor_lift_names() -> list[str]:
    if isinstance(ANCHOR_LIFTS, dict):
        return [str(lift) for lifts in ANCHOR_LIFTS.values() for lift in lifts]
    return [str(lift) for lift in ANCHOR_LIFTS]


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
    return _checkin_for_date(checkins, _today())


def _checkin_for_date(checkins: pd.DataFrame | None, target_date: date) -> pd.Series | None:
    data = _prep_checkins(checkins)
    if data.empty:
        return None
    today_rows = data[data["Date"].dt.date == target_date]
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
            if steps > DAILY_STEPS_TARGET:
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

        energy = pd.to_numeric(last.get("Energy"), errors="coerce")
        if pd.notna(energy):
            energy = float(energy)
            delta = -15 if energy <= 3 else (10 if energy >= 7 else 0)
            score += delta
            breakdown.append({"label": "Energy", "delta": delta, "note": f"{energy:.0f}/10"})

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


def build_weekly_muscle_frequency(df: pd.DataFrame | None) -> dict[str, int]:
    work = _prep_workouts(df)
    today = _today()
    cutoff = today - timedelta(days=6)
    raw: dict[str, int] = {}
    if not work.empty:
        window = work[
            (work["Date"].dt.date >= cutoff) &
            (work["Date"].dt.date <= today)
        ]
        if not window.empty:
            raw = (
                window.groupby("MuscleGroup")["Date"]
                .apply(lambda s: s.dt.date.nunique())
                .to_dict()
            )
    arms = raw.get("arms", 0)
    legs = raw.get("legs", 0)
    return {
        "chest": raw.get("chest", 0),
        "back": raw.get("back", 0),
        "shoulders": raw.get("shoulders", 0),
        "biceps": arms,
        "triceps": arms,
        "quads": legs,
        "hamstrings": legs,
        "glutes": legs,
        "calves": legs,
        "abs": raw.get("core", 0),
    }


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


def _match_split(muscles: set[str]) -> tuple[int | None, list[str] | None, float]:
    if not muscles:
        return None, None, 0.0
    best_idx: int | None = None
    best_split: list[str] | None = None
    best_score = 0.0
    for idx, split in enumerate(SPLIT_MUSCLES):
        split_set = set(split)
        overlap = len(muscles & split_set)
        if overlap == 0:
            score = 0.0
        else:
            union = len(muscles | split_set)
            score = overlap / union
            if split_set == muscles:
                score += 0.25
        if score > best_score:
            best_idx = idx
            best_split = split
            best_score = score
    return best_idx, best_split, best_score


def _session_muscles_by_date(work: pd.DataFrame, start: date, end: date) -> dict[date, set[str]]:
    if work.empty:
        return {}
    rows = work[
        (work["Date"].dt.date >= start)
        & (work["Date"].dt.date <= end)
        & (work["MuscleGroup"].isin(MUSCLE_GROUPS))
    ].copy()
    if rows.empty:
        return {}
    grouped = rows.groupby(rows["Date"].dt.date)["MuscleGroup"].apply(lambda s: set(s.dropna().astype(str)))
    return {day: muscles for day, muscles in grouped.items()}


def build_split_rotation_status(df: pd.DataFrame | None, today: date | None = None) -> dict[str, object]:
    ref = today or _today()
    week_start, _ = _week_bounds(ref)
    work = _prep_workouts(df)
    sessions = _session_muscles_by_date(work, week_start, ref)
    expected_idx = 0
    last_completed: list[str] | None = None
    last_completed_day: date | None = None
    completed_indices: set[int] = set()
    out_of_rotation: dict[str, object] | None = None

    for session_day in sorted(sessions):
        if expected_idx >= len(SPLIT_MUSCLES):
            break
        muscles = sessions[session_day]
        matched_idx, matched_split, score = _match_split(muscles)
        expected_split = SPLIT_MUSCLES[expected_idx]
        if matched_idx == expected_idx and score > 0:
            completed_indices.add(expected_idx)
            last_completed = matched_split
            last_completed_day = session_day
            expected_idx += 1
        elif matched_split is not None and out_of_rotation is None:
            out_of_rotation = {
                "day": session_day,
                "actual": matched_split,
                "expected": expected_split,
            }
            last_completed = matched_split
            last_completed_day = session_day

    rotation_complete = bool(SPLIT_MUSCLES) and expected_idx >= len(SPLIT_MUSCLES)
    rotation_index = 0 if rotation_complete else min(expected_idx, max(len(SPLIT_MUSCLES) - 1, 0))
    expected_split = [] if rotation_complete else (SPLIT_MUSCLES[rotation_index] if SPLIT_MUSCLES else [])
    next_idx = 0 if rotation_complete else min(rotation_index + 1, max(len(SPLIT_MUSCLES) - 1, 0))
    next_split = SPLIT_MUSCLES[next_idx] if SPLIT_MUSCLES else []
    expected_day_label = (
        "Next Rotation"
        if rotation_complete
        else (SPLIT_DAY_LABELS[rotation_index] if rotation_index < len(SPLIT_DAY_LABELS) else f"Day {rotation_index + 1}")
    )

    expected_calendar_slots = min(ref.weekday() + 1, len(SPLIT_MUSCLES))
    missed_sessions = max(0, expected_calendar_slots - expected_idx)
    if ref.weekday() < len(SPLIT_MUSCLES) and ref not in sessions and missed_sessions > 0:
        missed_sessions = max(0, missed_sessions - 1)

    if out_of_rotation is not None:
        rotation_status = "Out of Rotation"
        actual = _split_label(list(out_of_rotation["actual"]))
        expected = _split_label(list(out_of_rotation["expected"]))
        reason = f"{actual} was logged when {expected} was expected."
    elif missed_sessions > 0:
        rotation_status = "Missed"
        reason = f"{_split_label(expected_split)} remains next because skipped days do not advance the split."
    elif rotation_complete:
        rotation_status = "On Track"
        reason = f"This week's rotation is complete; {_split_label(next_split)} starts the next rotation."
    else:
        rotation_status = "On Track"
        reason = f"{_split_label(expected_split)} is the next uncompleted split in the rotation."

    return {
        "expected_today": "Rotation Complete" if rotation_complete else _split_label(expected_split),
        "expected_muscles": expected_split,
        "next_split": _split_label(next_split),
        "next_muscles": next_split,
        "last_completed_split": "None" if last_completed is None else _split_label(last_completed),
        "last_completed_date": last_completed_day,
        "rotation_index": rotation_index,
        "expected_day_label": expected_day_label,
        "rotation_determined": bool(SPLIT_MUSCLES),
        "rotation_complete": rotation_complete,
        "rotation_status": rotation_status,
        "missed_sessions": missed_sessions,
        "reason": reason,
        "completed_indices": completed_indices,
    }


def _filled_checkin_fields(row: pd.Series | None, fields: list[str]) -> list[str]:
    if row is None:
        return []
    filled: list[str] = []
    for field in fields:
        value = pd.to_numeric(row.get(field), errors="coerce")
        if pd.notna(value):
            filled.append(field)
    return filled


def build_todays_priority(
    df: pd.DataFrame | None,
    checkins: pd.DataFrame | None,
    today: date | None = None,
) -> dict[str, object]:
    ref = today or _today()
    readiness = compute_readiness(checkins)
    rotation = build_split_rotation_status(df, ref)
    today_row = _checkin_for_date(checkins, ref)
    readiness_score = int(readiness["score"])
    rotation_muscles = list(rotation.get("expected_muscles", []))
    if rotation.get("rotation_complete") and not rotation_muscles:
        rotation_muscles = list(rotation.get("next_muscles", []))
    rotation_known = bool(rotation.get("rotation_determined") and rotation_muscles)
    expected_split = _split_label(rotation_muscles) if rotation_muscles else str(rotation.get("expected_today") or "Workout")
    required_fields = ["SleepHours", "Energy", "Soreness", "Stress"]
    filled_fields = _filled_checkin_fields(today_row, required_fields)
    workout_data_sufficient = not _prep_workouts(df).empty
    try:
        severe_recovery = _has_severe_recovery_warning(weekly_warnings(df, checkins))
    except Exception:
        severe_recovery = False

    if today_row is None:
        priority_title = "Log today's check-in first"
        action_tag = "Log Checkins"
        priority_reason = "Missing checkins lowers confidence because recovery data is incomplete."
        why = "Missing checkins lowers confidence because recovery data is incomplete."
    elif readiness_score < 30:
        priority_title = "Recovery Day"
        action_tag = "Recovery"
        priority_reason = "Low readiness means recovery is the highest-return move today."
        why = "Low readiness means recovery is the highest-return move today."
    elif severe_recovery:
        priority_title = "Recovery Day"
        action_tag = "Recovery"
        priority_reason = "Fatigue or regression warnings make recovery the highest-return move today."
        why = "Recovery now protects strength retention during the cut."
    elif readiness_score < 50:
        priority_title = f"{expected_split} at 2-3 RIR"
        action_tag = "Train Smart"
        priority_reason = f"Following rotation with low readiness, so keep {expected_split} conservative."
        why = "This keeps your split on track while preserving strength during the cut."
    else:
        priority_title = expected_split
        action_tag = "Train"
        day_label = str(rotation.get("expected_day_label", "Rotation"))
        priority_reason = f"Following rotation: {day_label} = {expected_split}."
        why = "This keeps your split on track while preserving strength during the cut."

    try:
        fatigue_result = fatigue_risk_detector(
            df if df is not None else pd.DataFrame(), checkins=checkins
        )
        fatigue_risk = str(fatigue_result.get("risk", "Low"))
    except Exception:
        fatigue_risk = "Low"

    if today_row is None:
        confidence_level = "Low"
        confidence_reason = "No checkin row exists for today."
    elif not rotation_known:
        confidence_level = "Low"
        confidence_reason = "Split rotation could not be determined."
    elif not workout_data_sufficient:
        confidence_level = "Low"
        confidence_reason = "Workout data is insufficient."
    elif len(filled_fields) == len(required_fields):
        signals_agree = (readiness_score >= 60 and fatigue_risk != "High") or (
            readiness_score < 40 and fatigue_risk == "High"
        )
        if signals_agree:
            confidence_level = "High"
            confidence_reason = "Checkins complete and readiness/fatigue signals agree."
        else:
            confidence_level = "Medium"
            confidence_reason = (
                f"Checkins complete but readiness ({readiness_score}) and fatigue "
                f"({fatigue_risk}) signals conflict."
            )
    else:
        confidence_level = "Medium"
        missing = ", ".join(field for field in required_fields if field not in filled_fields)
        confidence_reason = f"Rotation is known, but checkins are partial: missing {missing}."

    anchor_callouts: list[str] = []
    if rotation_muscles and df is not None:
        try:
            trends = _anchor_lift_trends(df)
            watch_exercises = {t["exercise"] for t in trends if t.get("flag") == "Watch this lift"}
            for group, lifts in ANCHOR_LIFTS.items():
                muscle = _ANCHOR_GROUP_TO_MUSCLE.get(group, group.lower())
                if muscle in rotation_muscles:
                    for lift in lifts:
                        if lift in watch_exercises and len(anchor_callouts) < 2:
                            anchor_callouts.append(
                                f"⚠ Anchor regression: {lift} — prioritize this lift today"
                            )
        except Exception:
            pass

    return {
        "priority_title": priority_title,
        "priority_reason": priority_reason,
        "confidence_level": confidence_level,
        "confidence_reason": confidence_reason,
        "action_tag": action_tag,
        "why_this_matters": why,
        "readiness_score": readiness_score,
        "expected_split": expected_split,
        "expected_muscles": rotation_muscles,
        "rotation": rotation,
        "has_today_checkin": today_row is not None,
        "anchor_callouts": anchor_callouts,
    }


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


def _load_increment(exercise: str, muscle_group: str | None = None) -> int:
    key = _normalise_exercise(exercise)
    muscle = str(muscle_group or "").strip().lower()
    major_leg_terms = ("leg press", "hack squat", "squat", "deadlift", "rdl", "lunge")
    if key in {"leg press", "hack squat"} or any(term in key for term in major_leg_terms):
        return 10
    if muscle == "legs" and any(term in key for term in ("press", "squat", "curl")):
        return 10
    return 5


def build_progressive_overload_targets(
    df: pd.DataFrame | None,
    selected_exercises: list[str] | None = None,
    readiness: int | None = None,
    fatigue_high: bool = False,
) -> list[dict[str, object]]:
    work = _prep_workouts(df)
    if work.empty:
        return []

    exercise_filter = {
        _normalise_exercise(exercise)
        for exercise in (selected_exercises or [])
        if str(exercise).strip()
    }
    targets: list[dict[str, object]] = []
    for exercise, rows in work.groupby("Exercise"):
        exercise_name = str(exercise)
        if exercise_filter and _normalise_exercise(exercise_name) not in exercise_filter:
            continue
        rows = rows.dropna(subset=["Date", "Weight", "Reps"]).sort_values("Date")
        if rows.empty:
            continue
        latest_date = rows["Date"].max().date()
        latest = rows[rows["Date"].dt.date == latest_date].copy()
        if latest.empty:
            continue
        latest["Reps"] = pd.to_numeric(latest["Reps"], errors="coerce")
        latest["Weight"] = pd.to_numeric(latest["Weight"], errors="coerce")
        latest = latest.dropna(subset=["Weight", "Reps"]).sort_values(["Reps", "Weight"], ascending=[False, False])
        if latest.empty:
            continue
        best = latest.iloc[0]
        last_weight = float(best["Weight"])
        last_reps = float(best["Reps"])
        muscle_group = str(best.get("MuscleGroup", "")).strip().lower()
        increment = _load_increment(exercise_name, muscle_group)

        # 2-session validation: look up prior session reps
        session_dates = sorted(rows["Date"].dt.date.unique())
        prev_reps: float | None = None
        if len(session_dates) >= 2:
            prev_date = session_dates[-2]
            prev_session = rows[rows["Date"].dt.date == prev_date].sort_values(
                ["Reps", "Weight"], ascending=[False, False]
            )
            if not prev_session.empty:
                prev_reps = float(prev_session.iloc[0]["Reps"])

        if fatigue_high:
            recommended_weight = last_weight
            recommended_reps = f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}"
            instruction = "Hold load today — fatigue risk high"
        elif readiness is not None and readiness < 50:
            recommended_weight = last_weight
            recommended_reps = f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}"
            instruction = "Hold load today — readiness low"
        elif last_reps >= TARGET_REPS_MAX:
            if prev_reps is not None and last_reps < prev_reps:
                recommended_weight = last_weight
                recommended_reps = f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}"
                instruction = "Rep drop detected — hold load this session"
            else:
                recommended_weight = last_weight + increment
                recommended_reps = f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}"
                instruction = "Hit top of rep range — increase load"
        elif last_reps >= TARGET_REPS_MIN:
            recommended_weight = last_weight
            recommended_reps = f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}"
            instruction = "Stay at weight — aim for 8 reps"
        else:
            recommended_weight = last_weight
            recommended_reps = f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}"
            instruction = "Below range — hold or reduce weight"

        targets.append({
            "exercise": exercise_name,
            "last_weight": last_weight,
            "last_reps": last_reps,
            "recommended_weight": recommended_weight,
            "recommended_reps": recommended_reps,
            "instruction": instruction,
            "anchor_lift": _is_anchor(exercise_name),
        })
    return targets


def _exercise_targets(
    df: pd.DataFrame | None,
    muscles: list[str],
    readiness: int,
    fatigue_high: bool = False,
) -> list[dict[str, object]]:
    work = _prep_workouts(df)
    recs = _load_exercise_recs()
    selected: list[dict[str, object]] = []
    used: set[str] = set()
    overload_by_exercise = {
        _normalise_exercise(row["exercise"]): row
        for row in build_progressive_overload_targets(df, readiness=readiness, fatigue_high=fatigue_high)
    }

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
                overload = overload_by_exercise.get(key, {})
                target_w = overload.get("recommended_weight", last_w)
                target_reps = overload.get("recommended_reps", f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}" if target_w is not None else None)
                ex_streak = _progression_streak(df, exercise)
                selected.append({
                    "exercise": exercise,
                    "muscle_group": muscle,
                    "sets": TARGET_SETS,
                    "rep_range": f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}",
                    "rir": TARGET_RIR,
                    "last_weight": last_w,
                    "last_reps": last_r,
                    "target_weight": target_w,
                    "target_reps": target_reps,
                    "overload_note": str(overload.get("instruction", "No history found")),
                    "is_anchor": _is_anchor(exercise),
                    "streak": ex_streak,
                    "streak_broken": last_r is not None and ex_streak == 0,
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
            overload = overload_by_exercise.get(key, {})
            ex_streak = _progression_streak(df, exercise)
            selected.append({
                "exercise": exercise,
                "muscle_group": "",
                "sets": TARGET_SETS,
                "rep_range": f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}",
                "rir": TARGET_RIR,
                "last_weight": last_w,
                "last_reps": last_r,
                "target_weight": overload.get("recommended_weight", last_w),
                "target_reps": overload.get("recommended_reps", f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}" if last_w is not None else None),
                "overload_note": str(overload.get("instruction", "No history found")),
                "is_anchor": _is_anchor(exercise),
                "streak": ex_streak,
                "streak_broken": last_r is not None and ex_streak == 0,
            })
            used.add(key)
            if len(selected) >= 3:
                break
    return selected


def generate_game_plan(
    df: pd.DataFrame | None,
    readiness_score: int,
    checklist: list[dict[str, object]],
    rotation: dict[str, object] | None = None,
    severe_recovery: bool = False,
    priority: dict[str, object] | None = None,
    fatigue_high: bool = False,
) -> dict[str, object]:
    rotation_muscles = list(rotation.get("expected_muscles", [])) if rotation else []
    if rotation and rotation.get("rotation_complete") and not rotation_muscles:
        rotation_muscles = list(rotation.get("next_muscles", []))
    rotation_available = bool(rotation and rotation.get("rotation_determined") and rotation_muscles)
    muscles: list[str] = []

    if priority and priority.get("action_tag") == "Log Checkins":
        focus = str(priority["priority_title"])
        reason = str(priority["priority_reason"])
        split_muscles = []
    elif priority and priority.get("action_tag") in {"Train", "Train Smart"}:
        focus = str(priority["expected_split"])
        reason = str(priority["priority_reason"])
        split_muscles = list(priority.get("expected_muscles", []))
    elif priority and priority.get("action_tag") == "Recovery":
        focus = "Recovery"
        reason = str(priority["priority_reason"])
        split_muscles = []
    elif readiness_score < 30:
        focus = "Recovery"
        reason = "Readiness is below 30, so recovery protects strength retention."
        split_muscles: list[str] = []
    elif severe_recovery:
        focus = "Recovery"
        reason = "Regression or fatigue warning is active, so recovery takes priority over advancing the split."
        split_muscles = []
    elif rotation_available:
        focus = _split_label(rotation_muscles)
        split_muscles = rotation_muscles
        expected_day = str(rotation.get("expected_day_label", "Rotation"))
        if readiness_score < 50:
            reason = f"Following rotation: {expected_day} = {focus}. Keep it easy because readiness is low."
        else:
            reason = f"Following rotation: {expected_day} = {focus}."
    else:
        muscles = _target_muscles(checklist, readiness_score)
        focus, reason, split_muscles = _focus_for_muscles(muscles, readiness_score, checklist)
    if focus == "Log today's check-in first":
        intensity = "Log checkins before confirming training intensity."
    elif focus == "Recovery":
        intensity = "Skip hard sets - walk, mobility, and recovery work only."
    elif readiness_score >= 70:
        intensity = "Work to 0-1 RIR - push the last set"
    elif readiness_score >= 50:
        intensity = "Work to 1-2 RIR - leave a rep in the tank"
    else:
        intensity = "Work to 2-3 RIR - protect the joints"
    return {
        "focus": focus,
        "reason": reason,
        "exercises": [] if focus in {"Recovery", "Log today's check-in first"} else _exercise_targets(
            df,
            split_muscles or muscles,
            readiness_score,
            fatigue_high=fatigue_high,
        ),
        "intensity": intensity,
        "action_tag": str(priority.get("action_tag", "")) if priority else "",
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
                        (complete["Steps"] >= DAILY_STEPS_TARGET)
                        & (complete["Calories"].between(DAILY_CALORIES_TARGET * 0.9, DAILY_CALORIES_TARGET * 1.1))
                        & (complete["Protein"] >= DAILY_PROTEIN_TARGET)
                        & (complete["SleepHours"] >= DAILY_SLEEP_MINIMUM)
                    )
                    all_targets_days = int(hit.sum())

            if all(col in c.columns for col in target_cols):
                complete_all = c.dropna(subset=target_cols).sort_values("Date", ascending=False)
                for row in complete_all.itertuples(index=False):
                    if (
                        float(getattr(row, "Steps")) >= DAILY_STEPS_TARGET
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
        ("STEPS", "Steps", DAILY_STEPS_TARGET, ""),
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


def _render_todays_priority(priority: dict[str, object]) -> None:
    confidence = str(priority["confidence_level"])
    action = str(priority["action_tag"])
    action_color = {
        "Train": "#22c55e",
        "Train Smart": "#f59e0b",
        "Recovery": "#ef4444",
        "Log Checkins": "#60a5fa",
    }.get(action, "#e8890c")
    confidence_color = {
        "High": "#22c55e",
        "Medium": "#f59e0b",
        "Low": "#ef4444",
    }.get(confidence, "#888890")
    st.markdown(
        f"""
        <div style="background:#111113;border:1px solid #1e1e22;border-left:5px solid {action_color};
                    border-radius:4px;padding:1.3rem 1.4rem;margin-bottom:1rem;">
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.62rem;
                      letter-spacing:0.22em;text-transform:uppercase;color:#555560;">
            TODAY'S PRIORITY
          </div>
          <div style="font-family:'Bebas Neue',cursive;font-size:2.65rem;line-height:1;
                      letter-spacing:0.08em;color:#f0f0f2;margin-top:0.45rem;">
            {escape(str(priority["priority_title"]))}
          </div>
          <div style="display:flex;gap:0.65rem;flex-wrap:wrap;margin-top:0.85rem;">
            <span style="border:1px solid {action_color};color:{action_color};border-radius:3px;
                         padding:0.28rem 0.55rem;font-size:0.66rem;letter-spacing:0.14em;
                         text-transform:uppercase;">Action: {escape(action)}</span>
            <span style="border:1px solid {confidence_color};color:{confidence_color};border-radius:3px;
                         padding:0.28rem 0.55rem;font-size:0.66rem;letter-spacing:0.14em;
                         text-transform:uppercase;">Confidence: {escape(confidence)}</span>
          </div>
          <div style="font-size:0.76rem;color:#c8c8cc;margin-top:0.85rem;line-height:1.5;">
            {escape(str(priority["priority_reason"]))}
          </div>
          <div style="font-size:0.68rem;color:#777782;margin-top:0.55rem;line-height:1.45;">
            Why this matters: {escape(str(priority["why_this_matters"]))}
          </div>
          <div style="font-size:0.62rem;color:#555560;margin-top:0.45rem;line-height:1.45;">
            Confidence: {escape(str(priority["confidence_reason"]))}
          </div>
          {"".join(
              f'<div style="font-size:0.72rem;color:#ef4444;margin-top:0.45rem;line-height:1.45;">{escape(c)}</div>'
              for c in priority.get("anchor_callouts", [])
          )}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_split_rotation(rotation: dict[str, object]) -> None:
    st.markdown("### SPLIT ROTATION TRACKER")
    status = str(rotation["rotation_status"])
    color = "#22c55e" if status == "On Track" else ("#ef4444" if status == "Out of Rotation" else "#f59e0b")
    last_date = rotation.get("last_completed_date")
    last_label = str(rotation["last_completed_split"])
    if last_date is not None:
        last_label = f"{last_label} ({pd.Timestamp(last_date).strftime('%Y-%m-%d')})"
    body = (
        _small_line("Expected Today", rotation["expected_today"], "#e8890c")
        + _small_line("Last Completed", last_label)
        + _small_line("Next Up", rotation["next_split"])
        + _small_line("Status", status, color)
        + _small_line("Reason", rotation["reason"])
    )
    st.markdown(_card("Split Rotation Tracker", body, color), unsafe_allow_html=True)

    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    completed = set(rotation.get("completed_indices", set()))
    current = int(rotation.get("rotation_index", 0))
    today_slot = min(_today().weekday(), len(SPLIT_MUSCLES) - 1)
    chips: list[str] = []
    for idx, split in enumerate(SPLIT_MUSCLES[:6]):
        label = day_labels[idx] if idx < len(day_labels) else f"Day {idx + 1}"
        split_label = _split_label(split)
        if idx in completed:
            border = "#22c55e"
            bg = "rgba(34,197,94,0.12)"
            text = "#d8f5df"
        elif idx == current:
            border = "#e8890c"
            bg = "rgba(232,137,12,0.16)"
            text = "#e8890c"
        elif idx < today_slot:
            border = "#ef4444"
            bg = "rgba(239,68,68,0.10)"
            text = "#fca5a5"
        else:
            border = "#333338"
            bg = "#0d0d0f"
            text = "#777782"
        chips.append(
            f"<div style='border:1px solid {border};background:{bg};border-radius:3px;"
            "padding:0.45rem 0.65rem;min-width:145px;'>"
            f"<div style='font-size:0.58rem;letter-spacing:0.16em;color:#555560;'>{label}</div>"
            f"<div style='font-size:0.66rem;color:{text};margin-top:0.2rem;'>{escape(split_label)}</div>"
            "</div>"
        )
    chips_html = (
        "<div style='display:flex;gap:0.45rem;flex-wrap:wrap;margin-top:0.75rem;'>"
        + "".join(chips)
        + "</div>"
    )
    with st.container():
        st.markdown(chips_html, unsafe_allow_html=True)


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


def _anchor_session_bests(work: pd.DataFrame, exercise: str) -> pd.DataFrame:
    if work.empty:
        return pd.DataFrame()
    rows = work[work["Exercise"].astype(str).str.lower().str.strip() == _normalise_exercise(exercise)]
    rows = rows.dropna(subset=["Date", "Weight", "Reps", "Estimated1RM"]).copy()
    if rows.empty:
        return pd.DataFrame()
    rows["SessionDate"] = rows["Date"].dt.date
    bests = (
        rows.sort_values(
            ["SessionDate", "Estimated1RM", "Weight", "Reps"],
            ascending=[True, False, False, False],
        )
        .groupby("SessionDate", as_index=False)
        .first()
        .sort_values("SessionDate")
    )
    return bests


def _consecutive_same_weight(weights: list[float]) -> int:
    if not weights:
        return 0
    streak = 1
    last = weights[-1]
    for weight in reversed(weights[:-1]):
        if abs(weight - last) >= 0.01:
            break
        streak += 1
    return streak


def _weight_regressed_twice(weights: list[float]) -> bool:
    if len(weights) < 3:
        return False
    drops = 0
    for previous, current in zip(weights[-3:-1], weights[-2:]):
        if current < previous - 0.01:
            drops += 1
        else:
            drops = 0
        if drops >= 2:
            return True
    return False


def _progression_streak(df: pd.DataFrame | None, exercise: str) -> int:
    work = _prep_workouts(df)
    if work.empty:
        return 0
    rows = work[work["Exercise"].astype(str).str.lower().str.strip() == _normalise_exercise(exercise)]
    rows = rows.dropna(subset=["Date", "Weight", "Reps"]).copy()
    if rows.empty:
        return 0
    rows["_w"] = pd.to_numeric(rows["Weight"], errors="coerce")
    rows["_r"] = pd.to_numeric(rows["Reps"], errors="coerce")
    rows = rows.dropna(subset=["_w", "_r"])
    rows["_date"] = rows["Date"].dt.date
    bests = (
        rows.sort_values(["_date", "_r", "_w"], ascending=[True, False, False])
        .groupby("_date", as_index=False)
        .first()
        .sort_values("_date")
    )
    if len(bests) < 2:
        return 0
    sessions = list(zip(bests["_w"].tolist(), bests["_r"].tolist()))
    streak = 0
    for i in range(len(sessions) - 1, 0, -1):
        curr_w, curr_r = sessions[i]
        prev_w, prev_r = sessions[i - 1]
        if curr_r >= prev_r and curr_w >= prev_w - 0.01:
            streak += 1
        else:
            break
    return streak


def _anchor_lift_trends(df: pd.DataFrame | None) -> list[dict[str, object]]:
    work = _prep_workouts(df)
    trends: list[dict[str, object]] = []
    for exercise in _anchor_lift_names():
        sessions = _anchor_session_bests(work, exercise).tail(4)
        streak = _progression_streak(df, exercise)
        streak_broken = not sessions.empty and len(sessions) >= 2 and streak == 0
        if sessions.empty:
            trends.append({
                "exercise": exercise,
                "last": "No sessions logged",
                "trend": "→",
                "flag": "",
                "color": "#555560",
                "streak": 0,
                "streak_broken": False,
            })
            continue

        latest = sessions.iloc[-1]
        last_weight = float(latest["Weight"])
        last_reps = float(latest["Reps"])
        recent_scores = [float(value) for value in sessions["Estimated1RM"].tolist()]
        recent_weights = [float(value) for value in sessions["Weight"].tolist()]

        trend = "→"
        if len(recent_scores) >= 2:
            prior_best = max(recent_scores[:-1])
            if recent_scores[-1] > prior_best + 0.01:
                trend = "↑"
            elif recent_scores[-1] < recent_scores[-2] - 0.01:
                trend = "↓"

        ready = _consecutive_same_weight(recent_weights) >= 3 and last_reps >= 8
        watch = _weight_regressed_twice(recent_weights)
        if watch:
            flag = "Watch this lift"
            color = "#ef4444"
        elif ready:
            flag = "Ready to progress"
            color = "#22c55e"
        elif trend == "↓":
            flag = "Monitor"
            color = "#f59e0b"
        else:
            flag = "Stable"
            color = "#e8890c" if trend == "↑" else "#c8c8cc"

        trends.append({
            "exercise": exercise,
            "last": f"{last_weight:g} x {last_reps:g}",
            "trend": trend,
            "flag": flag,
            "color": color,
            "streak": streak,
            "streak_broken": streak_broken,
        })
    return trends


def render_anchor_lift_trends(df: pd.DataFrame | None) -> None:
    st.markdown("### ANCHOR LIFT TRENDS")
    trends = _anchor_lift_trends(df)
    for start in range(0, len(trends), 3):
        cols = st.columns(3)
        for col, row in zip(cols, trends[start:start + 3]):
            flag = str(row["flag"])
            streak = int(row.get("streak", 0))
            streak_broken = bool(row.get("streak_broken", False))
            body = (
                _small_line("Last", row["last"])
                + _small_line("Trend", row["trend"], str(row["color"]))
                + (_small_line("Flag", flag, str(row["color"])) if flag else _small_line("Flag", "No logged sessions", "#555560"))
            )
            if streak >= 2:
                body += _small_line("Streak", f"↑ {streak}-session streak", "#22c55e")
            elif streak_broken:
                body += _small_line("Streak", "⚠ streak broken", "#ef4444")
            col.markdown(_card(str(row["exercise"]), body, str(row["color"])), unsafe_allow_html=True)


def _anchor_lift_debug_rows(df: pd.DataFrame | None) -> list[dict[str, str]]:
    work = _prep_workouts(df)
    rows: list[dict[str, str]] = []
    for exercise in _anchor_lift_names():
        sessions = _anchor_session_bests(work, exercise)
        if sessions.empty:
            rows.append({
                "Anchor lift name": exercise,
                "Found in data": "No",
                "Last logged date": "Never",
                "Last weight x reps": "—",
            })
            continue

        latest = sessions.iloc[-1]
        last_date = pd.Timestamp(latest["Date"]).strftime("%Y-%m-%d")
        rows.append({
            "Anchor lift name": exercise,
            "Found in data": "Yes",
            "Last logged date": last_date,
            "Last weight x reps": f"{float(latest['Weight']):g} x {float(latest['Reps']):g}",
        })
    return rows


def _render_anchor_lift_debug(df: pd.DataFrame | None) -> None:
    if "show_anchor_debug" not in st.session_state:
        st.session_state.show_anchor_debug = False

    if st.button(
        "▼ Anchor Lift Debug" if st.session_state.show_anchor_debug else "▶ Anchor Lift Debug",
        key="toggle_anchor_debug",
    ):
        st.session_state.show_anchor_debug = not st.session_state.show_anchor_debug

    if st.session_state.show_anchor_debug:
        st.table(pd.DataFrame(_anchor_lift_debug_rows(df)))


def _format_last(weight: float | None, reps: float | None) -> str:
    if weight is None or reps is None:
        return "No recent data"
    return f"{weight:g} x {reps:g}"


def _format_target(weight: float | None, reps: object | None) -> str:
    if weight is None or reps is None:
        return "Start at working weight"
    if isinstance(reps, str):
        return f"{weight:g} x {reps}"
    return f"{weight:g} x {float(reps):g}"


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
        if plan.get("action_tag") == "Log Checkins":
            st.caption("Log today's checkins first, then use the priority card to confirm training readiness.")
        else:
            st.caption("Recovery plan: walk, mobility, and no hard sets today.")
        return
    cols = st.columns(len(exercises))
    for col, ex in zip(cols, exercises):
        name = str(ex["exercise"])
        title = f"{'⚓ ' if ex['is_anchor'] else ''}{name}"
        streak = int(ex.get("streak", 0))
        streak_broken = bool(ex.get("streak_broken", False))
        body = (
            _small_line("Last", _format_last(ex["last_weight"], ex["last_reps"]))
            + _small_line("Target", _format_target(ex["target_weight"], ex["target_reps"]), "#e8890c")
            + _small_line("Reason", ex.get("overload_note", "No history found"))
        )
        if streak >= 2:
            body += _small_line("Streak", f"↑ {streak}-session streak", "#22c55e")
        elif streak_broken:
            body += _small_line("Streak", "⚠ streak broken", "#ef4444")
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
        ("Avg daily steps", empty_label if progress["avg_steps"] is None else f"{progress['avg_steps']:,.0f} / {DAILY_STEPS_TARGET:,}", None if progress["avg_steps"] is None else float(progress["avg_steps"]), DAILY_STEPS_TARGET * 0.9, DAILY_STEPS_TARGET * 0.7),
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


def _has_severe_recovery_warning(warnings: list[dict[str, str]]) -> bool:
    severe_terms = ("regressed twice", "three low-grade sessions")
    for warning in warnings:
        title = str(warning.get("title", "")).lower()
        if any(term in title for term in severe_terms):
            return True
    return False


def build_weekly_review(
    df: pd.DataFrame | None,
    checkins: pd.DataFrame | None,
) -> dict[str, object]:
    today = _today()
    week_ago = today - timedelta(days=7)
    two_weeks_ago = today - timedelta(days=14)
    c = _prep_checkins(checkins)
    work = _prep_workouts(df)

    # ── weight_trend ───────────────────────────────────────────────────────
    this_bw: list[float] = []
    last_bw: list[float] = []
    if not c.empty and "Bodyweight" in c.columns:
        c_bw = c.dropna(subset=["Bodyweight"]).copy()
        c_bw["_bw"] = pd.to_numeric(c_bw["Bodyweight"], errors="coerce")
        c_bw = c_bw.dropna(subset=["_bw"])
        this_bw = c_bw[c_bw["Date"].dt.date > week_ago]["_bw"].tolist()
        last_bw = c_bw[
            (c_bw["Date"].dt.date > two_weeks_ago) & (c_bw["Date"].dt.date <= week_ago)
        ]["_bw"].tolist()

    this_week_avg = float(sum(this_bw) / len(this_bw)) if this_bw else None
    last_week_avg = float(sum(last_bw) / len(last_bw)) if last_bw else None

    if this_week_avg is not None and last_week_avg is not None and last_week_avg > 0:
        weekly_change = this_week_avg - last_week_avg
        rate_pct = (last_week_avg - this_week_avg) / last_week_avg
        if rate_pct > CUT_RATE_MAX:
            wt_status = "Too Fast"
        elif rate_pct < CUT_RATE_MIN:
            wt_status = "Too Slow"
        else:
            wt_status = "On Track"
    else:
        weekly_change = None
        rate_pct = None
        wt_status = "No Data"

    weight_trend: dict[str, object] = {
        "this_week_avg": this_week_avg,
        "last_week_avg": last_week_avg,
        "weekly_change": weekly_change,
        "rate_pct": rate_pct,
        "status": wt_status,
    }

    # ── strength_summary ───────────────────────────────────────────────────
    anchors_maintained = 0
    anchors_total = 0
    regressions: list[str] = []
    this_1rm_sum = 0.0
    last_1rm_sum = 0.0
    anchor_scored = 0

    if not work.empty:
        for exercise in _anchor_lift_names():
            rows = work[
                work["Exercise"].astype(str).str.lower().str.strip() == _normalise_exercise(exercise)
            ].dropna(subset=["Date", "Estimated1RM"]).copy()
            if rows.empty:
                continue
            daily = rows.groupby(rows["Date"].dt.date)["Estimated1RM"].max().sort_index()
            this_slice = daily[daily.index > week_ago]
            last_slice = daily[(daily.index > two_weeks_ago) & (daily.index <= week_ago)]
            if this_slice.empty or last_slice.empty:
                continue
            this_1rm = float(this_slice.max())
            last_1rm = float(last_slice.max())
            anchors_total += 1
            if this_1rm >= last_1rm * 0.98:
                anchors_maintained += 1
            else:
                regressions.append(exercise)
            this_1rm_sum += this_1rm
            last_1rm_sum += last_1rm
            anchor_scored += 1

    if anchor_scored > 0 and last_1rm_sum > 0:
        retention_delta = (this_1rm_sum - last_1rm_sum) / last_1rm_sum * 100
    else:
        retention_delta = 0.0

    strength_summary: dict[str, object] = {
        "anchors_maintained": anchors_maintained,
        "anchors_total": anchors_total,
        "regressions": regressions,
        "retention_delta": retention_delta,
    }

    # ── recovery_summary ───────────────────────────────────────────────────
    avg_sleep: float | None = None
    avg_energy: float | None = None
    avg_soreness: float | None = None
    poor_sleep_days = 0
    poor_energy_days = 0
    high_soreness_days = 0

    if not c.empty:
        week_c = c[c["Date"].dt.date > week_ago]
        if not week_c.empty:
            if "SleepHours" in week_c.columns:
                sv = pd.to_numeric(week_c["SleepHours"], errors="coerce").dropna()
                if not sv.empty:
                    avg_sleep = float(sv.mean())
                    poor_sleep_days = int((sv < DAILY_SLEEP_TARGET).sum())
            if "Energy" in week_c.columns:
                ev = pd.to_numeric(week_c["Energy"], errors="coerce").dropna()
                if not ev.empty:
                    avg_energy = float(ev.mean())
                    poor_energy_days = int((ev <= 3).sum())
            if "Soreness" in week_c.columns:
                sorv = pd.to_numeric(week_c["Soreness"], errors="coerce").dropna()
                if not sorv.empty:
                    avg_soreness = float(sorv.mean())
                    high_soreness_days = int((sorv >= 4).sum())

    recovery_summary: dict[str, object] = {
        "avg_sleep": avg_sleep,
        "avg_energy": avg_energy,
        "avg_soreness": avg_soreness,
        "poor_sleep_days": poor_sleep_days,
        "poor_energy_days": poor_energy_days,
        "high_soreness_days": high_soreness_days,
    }

    checkins_this_week = 0
    if not c.empty:
        checkins_this_week = int((c["Date"].dt.date > week_ago).sum())

    # ── decisions ──────────────────────────────────────────────────────────
    decisions: list[str] = []
    rp = rate_pct if rate_pct is not None else 0.0
    rd = retention_delta
    recovery_good = (avg_sleep is not None and avg_sleep >= 6.5) and (
        avg_energy is not None and avg_energy >= 5
    )

    if rate_pct is not None and rp > CUT_RATE_MAX and rd < -5:
        decisions.append(
            "Weight dropping too fast and strength declining — add 150 calories"
        )
    elif rate_pct is not None and rp > CUT_RATE_MAX:
        decisions.append(
            "Cut pace aggressive — consider adding 100 calories or one higher-carb day"
        )
    if len(decisions) < 3 and rate_pct is not None and rp < CUT_RATE_MIN and recovery_good:
        decisions.append("Cut pace slow and recovery strong — reduce calories by 100")
    if len(decisions) < 3 and avg_sleep is not None and avg_sleep < 6.5 and poor_sleep_days >= 4:
        decisions.append(
            "Sleep is consistently low — address before any training or diet changes"
        )
    if len(decisions) < 3 and poor_energy_days >= 4:
        decisions.append(
            "Energy low most of the week — check calories and sleep before increasing intensity"
        )
    if (
        len(decisions) < 3
        and anchors_maintained == anchors_total
        and anchors_total > 0
        and wt_status == "On Track"
    ):
        decisions.append("All anchors maintained and cut on track — no changes needed")
    if not decisions:
        decisions.append("Insufficient data for weekly decision")

    muscle_frequency = build_weekly_muscle_frequency(df)

    return {
        "weight_trend": weight_trend,
        "strength_summary": strength_summary,
        "recovery_summary": recovery_summary,
        "muscle_frequency": muscle_frequency,
        "decisions": decisions,
        "checkins_this_week": checkins_this_week,
    }


def render_weekly_review(
    df: pd.DataFrame | None,
    checkins: pd.DataFrame | None,
) -> None:
    today = _today()
    is_monday = today.weekday() == 0
    review = build_weekly_review(df, checkins)
    wt = review["weight_trend"]
    ss = review["strength_summary"]
    rs = review["recovery_summary"]
    decisions = list(review["decisions"])

    if "show_weekly_review" not in st.session_state:
        st.session_state.show_weekly_review = is_monday

    if st.button(
        "▼ Weekly Review" if st.session_state.show_weekly_review else "▶ Weekly Review",
        key="toggle_weekly_review",
    ):
        st.session_state.show_weekly_review = not st.session_state.show_weekly_review

    if st.session_state.show_weekly_review:
        if int(review["checkins_this_week"]) < 5:
            st.caption("Log more checkins for weekly decisions (need 5+ days this week).")
        else:
            mf: dict[str, int] = dict(review.get("muscle_frequency", {}))

            st.markdown("#### Weight Trend")
            wt_status = str(wt["status"])
            wt_color = {
                "On Track": "#22c55e",
                "Too Fast": "#ef4444",
                "Too Slow": "#f59e0b",
            }.get(wt_status, "#555560")
            this_avg_s = f"{wt['this_week_avg']:.1f} lbs" if wt["this_week_avg"] else "—"
            last_avg_s = f"{wt['last_week_avg']:.1f} lbs" if wt["last_week_avg"] else "—"
            change_s = f"{wt['weekly_change']:+.2f} lbs" if wt["weekly_change"] is not None else "—"
            rate_s = f"{abs(float(wt['rate_pct'])) * 100:.2f}%" if wt["rate_pct"] is not None else "—"
            cols = st.columns(3)
            cols[0].markdown(
                _card("This Week Avg", _small_line("Bodyweight", this_avg_s), "#1e1e22"),
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                _card("Last Week Avg", _small_line("Bodyweight", last_avg_s), "#1e1e22"),
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                _card(
                    "Cut Rate",
                    _small_line("Change", change_s)
                    + _small_line("Rate", rate_s, wt_color)
                    + _small_line("Status", wt_status, wt_color),
                    wt_color,
                ),
                unsafe_allow_html=True,
            )

            st.markdown("#### Strength")
            maintained_s = (
                f"{ss['anchors_maintained']}/{ss['anchors_total']}" if ss["anchors_total"] else "No data"
            )
            delta_s = f"{float(ss['retention_delta']):+.1f}%" if ss["anchors_total"] else "—"
            reg_list = list(ss["regressions"])
            reg_s = ", ".join(reg_list) if reg_list else "None"
            reg_color = "#ef4444" if reg_list else "#22c55e"
            cols = st.columns(3)
            cols[0].markdown(
                _card("Anchors Maintained", _small_line("This vs last week", maintained_s), "#1e1e22"),
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                _card("1RM Delta", _small_line("vs last week", delta_s), "#1e1e22"),
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                _card("Regressions", _small_line("Lifts", reg_s, reg_color), reg_color),
                unsafe_allow_html=True,
            )

            st.markdown("#### Recovery (past 7 days)")
            sleep_s = f"{float(rs['avg_sleep']):.1f}h" if rs["avg_sleep"] is not None else "—"
            energy_s = f"{float(rs['avg_energy']):.1f}/10" if rs["avg_energy"] is not None else "—"
            soreness_s = f"{float(rs['avg_soreness']):.1f}/10" if rs["avg_soreness"] is not None else "—"
            poor_sleep = int(rs["poor_sleep_days"])
            poor_energy = int(rs["poor_energy_days"])
            high_soreness = int(rs["high_soreness_days"])
            cols = st.columns(3)
            cols[0].markdown(
                _card(
                    "Sleep",
                    _small_line("Avg", sleep_s)
                    + _small_line(
                        f"Nights < {DAILY_SLEEP_TARGET:g}h",
                        str(poor_sleep),
                        "#ef4444" if poor_sleep >= 4 else "#c8c8cc",
                    ),
                    "#ef4444" if poor_sleep >= 4 else "#1e1e22",
                ),
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                _card(
                    "Energy",
                    _small_line("Avg", energy_s)
                    + _small_line(
                        "Days ≤ 3",
                        str(poor_energy),
                        "#ef4444" if poor_energy >= 4 else "#c8c8cc",
                    ),
                    "#ef4444" if poor_energy >= 4 else "#1e1e22",
                ),
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                _card(
                    "Soreness",
                    _small_line("Avg", soreness_s)
                    + _small_line(
                        "Days ≥ 4",
                        str(high_soreness),
                        "#ef4444" if high_soreness >= 4 else "#c8c8cc",
                    ),
                    "#ef4444" if high_soreness >= 4 else "#1e1e22",
                ),
                unsafe_allow_html=True,
            )

            if mf:
                st.markdown("#### Training Frequency (past 7 days)")
                mf_order = [
                    ("Chest", "chest"), ("Back", "back"), ("Shoulders", "shoulders"),
                    ("Biceps", "biceps"), ("Triceps", "triceps"), ("Abs", "abs"),
                    ("Quads", "quads"), ("Hamstrings", "hamstrings"), ("Glutes", "glutes"),
                    ("Calves", "calves"),
                ]
                for row_start in range(0, len(mf_order), 5):
                    row_muscles = mf_order[row_start:row_start + 5]
                    cols = st.columns(5)
                    for col, (label, key) in zip(cols, row_muscles):
                        sessions = mf.get(key, 0)
                        if sessions == 0:
                            freq_color = "#555560"
                        elif sessions == 1:
                            freq_color = "#f59e0b"
                        else:
                            freq_color = "#22c55e"
                        col.markdown(
                            _card(label, _small_line("Sessions", str(sessions), freq_color), freq_color),
                            unsafe_allow_html=True,
                        )

            decisions_html = "".join(
                f"<div style='font-size:0.76rem;color:#c8c8cc;margin-bottom:0.55rem;"
                f"padding-bottom:0.55rem;border-bottom:1px solid #1e1e22;'>{escape(d)}</div>"
                for d in decisions
            )
            st.markdown(
                _card("This Week's Decisions", decisions_html, "#e8890c"),
                unsafe_allow_html=True,
            )


def render_checkin_form(spreadsheet_id: str | None) -> None:
    today = _today()
    today_str = str(today)
    has_today = False
    if spreadsheet_id is None:
        st.info("No spreadsheet ID — cannot log checkin.")
        return

    # Determine if today already logged (read from cached checkins via session state if available)
    # We pull a quick check from any already-loaded checkins in the page context
    try:
        from src.sheets_client import load_checkins_worksheet
        existing = load_checkins_worksheet(spreadsheet_id)
        if not existing.empty and "Date" in existing.columns:
            has_today = today_str in existing["Date"].astype(str).str.strip().values
    except Exception:
        has_today = False

    if "show_checkin_form" not in st.session_state:
        st.session_state.show_checkin_form = not has_today

    if st.button(
        "▼ Log Today's Checkin" if st.session_state.show_checkin_form else "▶ Log Today's Checkin",
        key="toggle_checkin_form",
    ):
        st.session_state.show_checkin_form = not st.session_state.show_checkin_form

    if st.session_state.show_checkin_form:
        with st.form("checkin_form"):
            st.text_input("Date", value=today_str, disabled=True)
            bodyweight = st.number_input("Bodyweight (lbs)", min_value=100.0, max_value=400.0, step=0.1, value=None)
            calories = st.number_input("Calories", min_value=1000, max_value=4000, step=50, value=None)
            protein = st.number_input("Protein (g)", min_value=0, max_value=400, step=5, value=None)
            carbs = st.number_input("Carbs (g)", min_value=0, max_value=400, step=5, value=None)
            fat = st.number_input("Fat (g)", min_value=0, max_value=100, step=5, value=None)
            steps = st.number_input("Steps", min_value=0, max_value=30000, step=500, value=None)
            sleep_hours = st.number_input("Sleep Hours", min_value=0.0, max_value=12.0, step=0.5, value=None)
            energy = st.slider("Energy (1–10)", min_value=1, max_value=10, value=5)
            soreness = st.slider("Soreness (1–10)", min_value=1, max_value=10, value=5)
            stress = st.slider("Stress (1–10)", min_value=1, max_value=10, value=5)
            deload = st.checkbox("Deload week", value=False)
            notes = st.text_input("Notes", value="")

            submitted = st.form_submit_button("Save Checkin")

        if submitted:
            row = {
                "Date": today_str,
                "Bodyweight": bodyweight if bodyweight is not None else "",
                "Calories": calories if calories is not None else "",
                "Protein": protein if protein is not None else "",
                "Carbs": carbs if carbs is not None else "",
                "Fat": fat if fat is not None else "",
                "Steps": steps if steps is not None else "",
                "SleepHours": sleep_hours if sleep_hours is not None else "",
                "Energy": energy,
                "Soreness": soreness,
                "Stress": stress,
                "Deload": "TRUE" if deload else "FALSE",
                "Notes": notes,
            }
            try:
                append_checkin_row(spreadsheet_id, row)
                st.cache_data.clear()
                st.success(f"Checkin logged for {today_str}")
            except Exception as exc:
                st.error(str(exc))


def render_coach_page(
    df: pd.DataFrame,
    checkins: pd.DataFrame | None = None,
    spreadsheet_id: str | None = None,
) -> None:
    render_checkin_form(spreadsheet_id)
    st.divider()

    readiness = compute_readiness(checkins)
    checklist = weekly_muscle_checklist(df)
    priority = build_todays_priority(df, checkins)
    rotation = dict(priority["rotation"])
    warnings = weekly_warnings(df, checkins)
    fatigue = fatigue_risk_detector(df, checkins=checkins)
    fatigue_high = str(fatigue.get("risk", "")).lower() == "high"
    plan = generate_game_plan(
        df,
        int(readiness["score"]),
        checklist,
        rotation=rotation,
        severe_recovery=_has_severe_recovery_warning(warnings),
        priority=priority,
        fatigue_high=fatigue_high,
    )
    progress = weekly_progress_tracker(df, checkins)

    render_weekly_review(df, checkins)
    st.divider()
    _render_todays_priority(priority)
    st.divider()
    _render_readiness(readiness)
    _render_checkins_status(checkins)
    st.divider()
    _render_split_rotation(rotation)
    st.divider()
    _render_today_targets(checkins, spreadsheet_id)
    st.divider()
    _render_checklist(checklist)
    st.divider()
    render_anchor_lift_trends(df)
    st.divider()
    _render_game_plan(plan)
    st.divider()
    _render_progress(progress)
    st.divider()
    _render_warnings(warnings)
    st.divider()
    _render_anchor_lift_debug(df)
