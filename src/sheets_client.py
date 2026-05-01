from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import gspread
import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from google.oauth2.service_account import Credentials


DEFAULT_SPREADSHEET_ID = "1-45dvx4NOmyAOg8fDBL4_525NMXhCuEcSk_eaf9v9AI"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
_WRITE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CHECKINS_SHEET_NAME = "checkins"
_CHECKIN_COLUMNS = [
    "Date", "Bodyweight", "Calories", "Protein", "Carbs", "Fat",
    "Steps", "SleepHours", "Energy", "Soreness", "Stress", "Deload", "Notes",
]

# Matches "m/d" or "m/d/yy" or "m/d/yyyy" anywhere in a string
_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)")
# Matches bare "m/d" with no year component
_BARE_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")


class GoogleSheetsError(RuntimeError):
    """Raised when the Google Sheets workbook cannot be loaded."""


def _credentials_from_streamlit_secrets() -> Credentials | None:
    info = _service_account_info_from_streamlit_secrets()
    if info is None:
        return None
    return Credentials.from_service_account_info(info, scopes=SCOPES)


def _service_account_info_from_streamlit_secrets() -> dict[str, Any] | None:
    try:
        if "gcp_service_account" not in st.secrets:
            return None
    except StreamlitSecretNotFoundError:
        return None
    return dict(st.secrets["gcp_service_account"])


def _credentials_from_local_file(path: str = "config/credentials.json") -> Credentials | None:
    info = _service_account_info_from_local_file(path)
    if info is None:
        return None
    return Credentials.from_service_account_info(info, scopes=SCOPES)


def _service_account_info_from_local_file(path: str = "config/credentials.json") -> dict[str, Any] | None:
    credentials_path = Path(path)
    if not credentials_path.exists():
        legacy_path = Path("credentials.json")
        if not legacy_path.exists():
            return None
        credentials_path = legacy_path
    with credentials_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_credentials_client_email() -> str | None:
    info = _service_account_info_from_streamlit_secrets() or _service_account_info_from_local_file()
    if info is None:
        return None
    return info.get("client_email")


def get_client() -> gspread.Client:
    credentials = _credentials_from_streamlit_secrets() or _credentials_from_local_file()
    if credentials is None:
        raise GoogleSheetsError(
            "Google credentials were not found. Add config/credentials.json locally or "
            "configure [gcp_service_account] in Streamlit secrets."
        )
    return gspread.authorize(credentials)


def _parse_block_header(cell: str) -> tuple[str, str | None]:
    """Return (workout_name, date_str) from a header cell like 'Upper C 4/21' or '3/2 push'."""
    cell = cell.strip()
    m = _DATE_RE.search(cell)
    if not m:
        return cell, None
    date_str = m.group(1)
    name = (cell[: m.start()] + cell[m.end() :]).strip().strip("-_ ")
    return name or cell, date_str


def worksheet_to_dataframe(worksheet: gspread.Worksheet) -> pd.DataFrame:
    """Parse a worksheet that uses the block-header format into a tidy DataFrame.

    Each workout session begins with a row ["Workout Date", "Weight", "Reps"].
    Exercise names appear only on the first set row; subsequent sets leave col[0] blank.
    """
    rows = worksheet.get_all_values()
    if not rows:
        return pd.DataFrame()

    records: list[dict] = []
    current_workout: str = worksheet.title
    current_date: str | None = None
    current_exercise: str | None = None
    set_counter: dict[tuple, int] = {}

    for row in rows:
        padded = (row + ["", "", ""])[:3]
        c0, c1, c2 = [c.strip() for c in padded]

        # Block header row: second col is "Weight" and third is "Reps"
        if c1.lower() == "weight" and c2.lower() == "reps":
            name, date_str = _parse_block_header(c0)
            current_workout = name or current_workout
            if date_str:
                current_date = date_str
            current_exercise = None
            set_counter = {}
            continue

        # Fully blank row
        if not c0 and not c1 and not c2:
            continue

        # Update current exercise when the name is provided
        if c0:
            current_exercise = c0

        if current_exercise is None:
            continue

        # Skip rows where both weight and reps are empty
        if not c1 and not c2:
            continue

        key = (current_workout, current_exercise)
        set_counter[key] = set_counter.get(key, 0) + 1

        records.append(
            {
                "Date": current_date,
                "Workout": current_workout,
                "Exercise": current_exercise,
                "Set": set_counter[key],
                "Weight": c1 or None,
                "Reps": c2 or None,
                "SourceSheet": worksheet.title,
            }
        )

    return pd.DataFrame(records) if records else pd.DataFrame()


def _assign_date_years(df: pd.DataFrame) -> pd.DataFrame:
    """Walk rows in source order and append the correct year to bare 'm/d' date strings.

    Starts from (current_year - 1) and increments the year whenever the month/day
    makes a significant backward jump, which indicates a calendar year rollover.
    """
    current_year = pd.Timestamp.now().year - 1
    prev_approx_doy = 0  # approximate day-of-year used only for detecting rollover

    def resolve(date_str: Any) -> Any:
        nonlocal current_year, prev_approx_doy
        if date_str is None or (not isinstance(date_str, str)):
            return date_str
        s = date_str.strip()
        m = _BARE_DATE_RE.match(s)
        if not m:
            return s  # Already has a year or is in a different format
        month, day = int(m.group(1)), int(m.group(2))
        approx_doy = month * 32 + day
        if approx_doy < prev_approx_doy - 45:  # Backward jump signals year rollover
            current_year += 1
        prev_approx_doy = approx_doy
        return f"{month}/{day}/{current_year}"

    df = df.copy()
    df["Date"] = [resolve(d) for d in df["Date"]]
    return df


def load_all_worksheets(spreadsheet_id: str = DEFAULT_SPREADSHEET_ID) -> pd.DataFrame:
    try:
        spreadsheet = get_client().open_by_key(spreadsheet_id)
        frames = [
            worksheet_to_dataframe(sheet)
            for sheet in spreadsheet.worksheets()
            if sheet.title.strip().lower() != CHECKINS_SHEET_NAME
        ]
    except gspread.exceptions.APIError as exc:
        raise GoogleSheetsError(f"Google Sheets API error: {exc}") from exc
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise GoogleSheetsError(
            "Spreadsheet was not found. Confirm the ID and share the sheet with "
            "the service account email."
        ) from exc

    usable_frames = [frame for frame in frames if not frame.empty]
    if not usable_frames:
        return pd.DataFrame()

    combined = pd.concat(usable_frames, ignore_index=True, sort=False)
    return _assign_date_years(combined)


def load_checkins_worksheet(spreadsheet_id: str = DEFAULT_SPREADSHEET_ID) -> pd.DataFrame:
    try:
        spreadsheet = get_client().open_by_key(spreadsheet_id)
        worksheet = next(
            (
                sheet for sheet in spreadsheet.worksheets()
                if sheet.title.strip().lower() == CHECKINS_SHEET_NAME
            ),
            None,
        )
        if worksheet is None:
            return pd.DataFrame()
        records = worksheet.get_all_records()
    except gspread.exceptions.APIError as exc:
        raise GoogleSheetsError(f"Google Sheets API error: {exc}") from exc
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise GoogleSheetsError(
            "Spreadsheet was not found. Confirm the ID and share the sheet with "
            "the service account email."
        ) from exc

    return pd.DataFrame(records)


def append_checkin_row(spreadsheet_id: str, row: dict) -> None:
    info = _service_account_info_from_streamlit_secrets() or _service_account_info_from_local_file()
    if info is None:
        raise GoogleSheetsError(
            "Google credentials were not found. Add config/credentials.json locally or "
            "configure [gcp_service_account] in Streamlit secrets."
        )
    creds = Credentials.from_service_account_info(info, scopes=_WRITE_SCOPES)
    client = gspread.authorize(creds)
    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise GoogleSheetsError(
            "Spreadsheet was not found. Confirm the ID and share the sheet with "
            "the service account email."
        ) from exc
    worksheet = next(
        (sheet for sheet in spreadsheet.worksheets()
         if sheet.title.strip().lower() == CHECKINS_SHEET_NAME),
        None,
    )
    if worksheet is None:
        raise GoogleSheetsError("Checkins worksheet not found.")

    row_values = [row.get(col, "") for col in _CHECKIN_COLUMNS]
    today_str = str(row.get("Date", ""))
    col_a = worksheet.col_values(1)
    for i, cell in enumerate(col_a):
        if cell.strip() == today_str:
            worksheet.update([[*row_values]], f"A{i + 1}")
            return
    worksheet.append_row(row_values, value_input_option="USER_ENTERED")
