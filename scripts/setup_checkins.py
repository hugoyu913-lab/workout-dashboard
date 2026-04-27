from __future__ import annotations

import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.metrics import CHECKIN_COLUMNS
from src.sheets_client import (
    DEFAULT_SPREADSHEET_ID,
    GoogleSheetsError,
    _service_account_info_from_local_file,
    _service_account_info_from_streamlit_secrets,
)

WRITE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CHECKINS_TITLE = "Checkins"


def _write_client() -> gspread.Client:
    info = _service_account_info_from_streamlit_secrets() or _service_account_info_from_local_file()
    if info is None:
        raise GoogleSheetsError(
            "Google credentials were not found. Add config/credentials.json locally or credentials.json in the repo root."
        )
    credentials = Credentials.from_service_account_info(info, scopes=WRITE_SCOPES)
    return gspread.authorize(credentials)


def ensure_checkins(spreadsheet_id: str = DEFAULT_SPREADSHEET_ID) -> list[str]:
    spreadsheet = _write_client().open_by_key(spreadsheet_id)
    worksheet = next(
        (sheet for sheet in spreadsheet.worksheets() if sheet.title.strip().lower() == CHECKINS_TITLE.lower()),
        None,
    )
    if worksheet is None:
        worksheet = spreadsheet.add_worksheet(title=CHECKINS_TITLE, rows=1000, cols=len(CHECKIN_COLUMNS))
        worksheet.update("A1", [CHECKIN_COLUMNS])
        return CHECKIN_COLUMNS

    existing = worksheet.row_values(1)
    merged = list(existing)
    for header in CHECKIN_COLUMNS:
        if header not in merged:
            merged.append(header)

    if merged != existing:
        if worksheet.col_count < len(merged):
            worksheet.add_cols(len(merged) - worksheet.col_count)
        end_col = chr(ord("A") + len(merged) - 1)
        worksheet.update(f"A1:{end_col}1", [merged])
    return merged


def main() -> None:
    headers = ensure_checkins()
    print("Checkins worksheet is ready.")
    print("Columns:")
    print(" | ".join(headers))


if __name__ == "__main__":
    main()
