from __future__ import annotations

TARGET_REPS_MIN: int = 6
TARGET_REPS_MAX: int = 8
TARGET_SETS: int = 2
TARGET_RIR: int = 1
TRAINING_DAYS_PER_WEEK: float = 5.5
PHASE: str = "cut"  # cut | bulk | maintain
TARGET_BODY_FAT: int = 10
MIN_MUSCLE_FREQ_PER_WEEK: int = 2
MAX_MUSCLE_FREQ_PER_WEEK: int = 4
TRAINING_SPLIT: list[list[str]] = [
    ["Chest", "Back"],
    ["Shoulders", "Arms"],
    ["Legs"],
    ["Chest", "Arms"],
    ["Back", "Shoulders"],
    ["Legs"],
]

DAILY_STEPS_TARGET: int = 10000
DAILY_CALORIES_TARGET: int = 2200
DAILY_PROTEIN_TARGET: int = 180
DAILY_CARBS_TARGET: int = 180
DAILY_FAT_TARGET: int = 60
DAILY_SLEEP_TARGET: float = 8
DAILY_SLEEP_MINIMUM: float = 6.5

CUT_RATE_MIN: float = 0.003
CUT_RATE_MAX: float = 0.01
IDEAL_CUT_RATE_MIN: float = 0.005
IDEAL_CUT_RATE_MAX: float = 0.008

# Key lifts used for strength-retention tracking, warnings, and game plan flagging
ANCHOR_LIFTS: dict[str, list[str]] = {
    "Chest": ["Smith Machine Incline Press", "Pec Deck"],
    "Back": ["Lat Pulldown", "Seated Cable Row"],
    "Biceps": ["Dumbbell Curl", "Cable Curl"],
    "Triceps": ["Tricep Pushdown", "Single Arm Tricep Extension"],
    "Legs": ["Leg Press", "Leg Curl"],
}

# Compatibility list for existing logic that expects list[str]
ANCHOR_LIFT_LIST: list[str] = [
    lift
    for lifts in ANCHOR_LIFTS.values()
    for lift in lifts
]
