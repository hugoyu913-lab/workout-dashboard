from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


EXERCISE_MAP_PATH = Path("config/exercise_map.csv")
STANDARD_COLUMNS = [
    "Date",
    "Workout",
    "Exercise",
    "MuscleGroup",
    "Category",
    "Set",
    "Weight",
    "Reps",
    "Volume",
    "SourceSheet",
]

COLUMN_ALIASES = {
    "date": "Date",
    "day": "Date",
    "workout date": "Date",
    "session": "Workout",
    "workout": "Workout",
    "routine": "Workout",
    "exercise": "Exercise",
    "movement": "Exercise",
    "lift": "Exercise",
    "muscle group": "MuscleGroup",
    "musclegroup": "MuscleGroup",
    "category": "Category",
    "set": "Set",
    "sets": "Set",
    "set #": "Set",
    "weight": "Weight",
    "weight lbs": "Weight",
    "weight (lbs)": "Weight",
    "lbs": "Weight",
    "load": "Weight",
    "reps": "Reps",
    "rep": "Reps",
    "repetitions": "Reps",
    "volume": "Volume",
    "total volume": "Volume",
}

# Maps lowercase exercise name → muscle group
MUSCLE_GROUP_MAP: dict[str, str] = {
    # chest
    "bench": "chest",
    "bench press": "chest",
    "benchpress": "chest",
    "cable fly": "chest",
    "chest press machine": "chest",
    "dumbbell incline": "chest",
    "incline chest press machine": "chest",
    "incline dumbbell": "chest",
    "incline machine": "chest",
    "incline smith": "chest",
    "incline smith machine": "chest",
    "pec deck": "chest",
    "plate incline": "chest",
    "plate loaded chest press": "chest",
    "plate loaded incline": "chest",
    "plate loaded incline chest press": "chest",
    "seated incline": "chest",
    "seated incline machine": "chest",
    "smith incline": "chest",
    "smith machine incline": "chest",
    "standing chest press": "chest",
    # back
    "barbell row": "back",
    "cable row": "back",
    "cable seated row": "back",
    "chest suppirted row": "back",
    "chest supported row": "back",
    "chest supported seated row": "back",
    "close grip row": "back",
    "close grip seated row": "back",
    "diverging lat pulldown": "back",
    "dumbbell row": "back",
    "high row": "back",
    "hyperextension": "back",
    "lat pulldown": "back",
    "lat pullover": "back",
    "lat pullover machine": "back",
    "lat row": "back",
    "lat row machine": "back",
    "low row": "back",
    "megamass row": "back",
    "megamass t bar": "back",
    "plate loaded seated row": "back",
    "prime seated row": "back",
    "pull up": "back",
    "pull ups": "back",
    "pullups": "back",
    "reverse grip pulldown": "back",
    "seated cable row": "back",
    "seated row": "back",
    "seated row machine": "back",
    "single arm lat pulldown": "back",
    "single arm lat row": "back",
    "single arm pulldown": "back",
    "single arm row": "back",
    "single arm seated row": "back",
    "single lat pulldown": "back",
    "t bar row": "back",
    "tbar row": "back",
    "underhand row": "back",
    "upper back row": "back",
    "upper back row machine": "back",
    # shoulders
    "cable lat raise": "shoulders",
    "cable rear delt": "shoulders",
    "cable rear delt fly": "shoulders",
    "cuffed lat raise": "shoulders",
    "dumbbell shoulder press": "shoulders",
    "lat raise machine": "shoulders",
    "lateral raise machine": "shoulders",
    "machine lat raise": "shoulders",
    "plate loaded rear delt": "shoulders",
    "rear delt flt": "shoulders",
    "rear delt fly": "shoulders",
    "rear delt fly machine": "shoulders",
    "seated shoulder press": "shoulders",
    "seated shoulder press machine": "shoulders",
    "shoulder press": "shoulders",
    "shoulder press machine": "shoulders",
    "shoulder press plate loaded": "shoulders",
    "smith machine shoulder press": "shoulders",
    "smith shoulder": "shoulders",
    "smith shoulder press": "shoulders",
    # arms (biceps + triceps)
    "bicep curl machine": "arms",
    "cable curl": "arms",
    "cable reverse curl": "arms",
    "cable tricep pushdown": "arms",
    "cable wrist curl": "arms",
    "cuffed tricep pushdown": "arms",
    "curl machine": "arms",
    "dips": "arms",
    "dumbbell bicep": "arms",
    "dumbbell bicep curl": "arms",
    "dumbbell curl": "arms",
    "dumbbell hanmer": "arms",
    "dumbbell preacher": "arms",
    "dumbbell wrist curl": "arms",
    "ez bar reverse": "arms",
    "ez bar reverse curl": "arms",
    "hammer curl": "arms",
    "hammer curl machine": "arms",
    "over head tricep": "arms",
    "overhead tricep": "arms",
    "overhead tricep machine": "arms",
    "preacher curl": "arms",
    "preacher curl machine": "arms",
    "preachet curl machine": "arms",
    "reverse cable curl": "arms",
    "seated curl machine": "arms",
    "single arm tricep": "arms",
    "single arm tricep ext": "arms",
    "single arm tricep pushdown": "arms",
    "single cable curl": "arms",
    "single tricep": "arms",
    "single tricep ext": "arms",
    "single tricep pushdown": "arms",
    "single tricpe ext": "arms",
    "skullcrusher ez bar": "arms",
    "tricep overhead": "arms",
    "tricep push down": "arms",
    "tricep pushdown": "arms",
    # legs
    "calf raise": "legs",
    "goblin squat": "legs",
    "hip abductors": "legs",
    "hip adductor": "legs",
    "leg curl": "legs",
    "leg extension": "legs",
    "leg press": "legs",
    "pendulum squat": "legs",
    "seated calf raise": "legs",
    "single leg press": "legs",
    "standing calf raise": "legs",
    "sumo squat": "legs",
    # core
    "ab crunch machine": "core",
    "crunch machine": "core",
    "decline situp": "core",
    "hanging leg raise": "core",
    "leg raise": "core",
    "leg raises": "core",
}


def _exercise_key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _normalize_column_name(name: object) -> str:
    cleaned = re.sub(r"\s+", " ", str(name).strip().lower())
    return COLUMN_ALIASES.get(cleaned, str(name).strip())


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def _coerce_numeric(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.extract(r"(-?\d+(?:\.\d+)?)", expand=False)
    return pd.to_numeric(cleaned, errors="coerce")


def _drop_blank_rows(df: pd.DataFrame) -> pd.DataFrame:
    core = df.drop(columns=["SourceSheet"], errors="ignore")
    blank_mask = core.apply(
        lambda row: all(
            not str(v).strip() or str(v).strip().lower() in ("nan", "none", "<na>")
            for v in row
        ),
        axis=1,
    )
    return df.loc[~blank_mask].copy()


def _infer_missing_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "Exercise" not in df.columns:
        text_columns = [column for column in df.columns if column != "SourceSheet"]
        if text_columns:
            df["Exercise"] = df[text_columns[0]]

    if "Workout" not in df.columns:
        df["Workout"] = df.get("SourceSheet", "Workout")

    if "Set" not in df.columns:
        df["Set"] = df.groupby(["SourceSheet", "Exercise"], dropna=False).cumcount() + 1

    return df


def _load_exercise_map(path: Path = EXERCISE_MAP_PATH) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    try:
        mapping_df = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return {}

    mapping_df.columns = [_exercise_key(column) for column in mapping_df.columns]
    if "raw_name" not in mapping_df.columns or "standard_name" not in mapping_df.columns:
        return {}

    if "muscle_group" not in mapping_df.columns:
        mapping_df["muscle_group"] = ""
    if "category" not in mapping_df.columns:
        mapping_df["category"] = ""

    mapping: dict[str, dict[str, str]] = {}
    for row in mapping_df.to_dict("records"):
        raw_name = str(row.get("raw_name", "")).strip()
        standard_name = str(row.get("standard_name", "")).strip()
        if not raw_name or not standard_name:
            continue

        key = _exercise_key(raw_name)
        standard_key = _exercise_key(standard_name)
        muscle_group = str(row.get("muscle_group", "")).strip().lower()
        category = str(row.get("category", "")).strip().lower()

        mapping[key] = {
            "standard_name": standard_name,
            "muscle_group": muscle_group or MUSCLE_GROUP_MAP.get(standard_key, ""),
            "category": category,
        }

    return mapping


def _standardize_exercises(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    mapping = _load_exercise_map()

    normalized = df["Exercise"].map(_exercise_key)
    mapped = normalized.map(mapping)

    standard_names = mapped.map(
        lambda value: value.get("standard_name") if isinstance(value, dict) else None
    )
    df["Exercise"] = standard_names.fillna(df["Exercise"].astype(str).str.strip())

    standardized_key = df["Exercise"].map(_exercise_key)
    mapped_muscle_groups = mapped.map(
        lambda value: value.get("muscle_group") if isinstance(value, dict) else None
    )
    fallback_muscle_groups = standardized_key.map(MUSCLE_GROUP_MAP).fillna(
        normalized.map(MUSCLE_GROUP_MAP)
    )
    df["MuscleGroup"] = (
        mapped_muscle_groups.replace("", pd.NA)
        .fillna(fallback_muscle_groups)
        .fillna("other")
    )

    mapped_categories = mapped.map(
        lambda value: value.get("category") if isinstance(value, dict) else None
    )
    df["Category"] = mapped_categories.replace("", pd.NA).fillna("strength")
    return df


def clean_workout_log(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    df = raw.copy()
    df.columns = [_normalize_column_name(column) for column in df.columns]
    df = _drop_blank_rows(df)

    if df.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    df = _infer_missing_columns(df)

    for column in STANDARD_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA

    df["SourceSheet"] = df["SourceSheet"].fillna("Unknown")
    df["Date"] = pd.to_datetime(df["Date"].replace("", pd.NA), errors="coerce").ffill()
    df["Workout"] = df["Workout"].replace("", pd.NA).ffill()
    df["Exercise"] = df["Exercise"].replace("", pd.NA).ffill()

    df["Weight"] = _coerce_numeric(df["Weight"])
    df["Reps"] = _coerce_numeric(df["Reps"])
    df["Set"] = _coerce_numeric(df["Set"])

    missing_set = df["Set"].isna()
    df.loc[missing_set, "Set"] = (
        df[missing_set].groupby(["SourceSheet", "Date", "Workout", "Exercise"], dropna=False).cumcount() + 1
    )

    computed_volume = df["Weight"] * df["Reps"]
    df["Volume"] = _coerce_numeric(df["Volume"]).fillna(computed_volume)

    df = df.dropna(subset=["Exercise"])
    df = df[df["Weight"].notna() | df["Reps"].notna() | df["Volume"].notna()]
    df = _standardize_exercises(df)
    df = df[STANDARD_COLUMNS].copy()
    df = df.sort_values(["Date", "SourceSheet", "Workout", "Exercise", "Set"], na_position="last")
    return df.reset_index(drop=True)
