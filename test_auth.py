# test_auth.py — run from your project root
import gspread
import json

# Step 1: Verify credentials file is valid JSON
with open("credentials.json") as f:
    creds = json.load(f)

print("[OK] credentials.json loaded")
print(f"   Type: {creds.get('type')}")
print(f"   Project ID: {creds.get('project_id')}")
print(f"   Client email: {creds.get('client_email')}")

# Step 2: Try to authenticate
try:
    gc = gspread.service_account(filename="credentials.json")
    print("[OK] gspread authenticated successfully")
except Exception as e:
    print(f"[FAIL] Auth failed: {e}")

# Step 3: Try to open the sheet
SHEET_ID = "1-45dvx4NOmyAOg8fDBL4_525NMXhCuEcSk_eaf9v9AI"
try:
    sh = gc.open_by_key(SHEET_ID)
    print(f"[OK] Sheet opened: {sh.title}")
    worksheets = sh.worksheets()
    print(f"   Tabs found: {[ws.title for ws in worksheets]}")
except gspread.exceptions.APIError as e:
    print(f"[FAIL] Sheet access failed")
    print(f"   Status: {e.response.status_code}")
    print(f"   Message: {e.response.json()}")
except Exception as e:
    print(f"[FAIL] Unexpected error: {type(e).__name__}: {e}")
