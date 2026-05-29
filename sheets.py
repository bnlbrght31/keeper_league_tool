import gspread
from gspread.exceptions import SpreadsheetNotFound
from gspread.utils import rowcol_to_a1

from google_auth import get_credentials

COLUMNS = ["Team", "Player", "Keeper Count", "Draft Price", "FAAB Cost", "Keeper Cost"]
NUM_COLS = len(COLUMNS)

# Colors
COLOR_RED = {"red": 0.918, "green": 0.447, "blue": 0.447}        # keeper count = 2
COLOR_YELLOW = {"red": 1.0, "green": 0.949, "blue": 0.667}        # keeper count = 1
COLOR_TEAM_HEADER = {"red": 0.263, "green": 0.263, "blue": 0.263} # dark gray team header bg
COLOR_WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
COLOR_HEADER_BG = {"red": 0.192, "green": 0.306, "blue": 0.475}   # dark blue header row


def _gc():
    return gspread.Client(auth=get_credentials())


def _cell_range(row, col, end_col=None):
    if end_col is None:
        return rowcol_to_a1(row, col)
    return f"{rowcol_to_a1(row, col)}:{rowcol_to_a1(row, end_col)}"


def _row_bg_request(sheet_id, row_idx, color, num_cols=NUM_COLS):
    """Return a batchUpdate request to set background color for a full row."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_idx,
                "endRowIndex": row_idx + 1,
                "startColumnIndex": 0,
                "endColumnIndex": num_cols,
            },
            "cell": {"userEnteredFormat": {"backgroundColor": color}},
            "fields": "userEnteredFormat.backgroundColor",
        }
    }


def _merge_request(sheet_id, row_idx, num_cols=NUM_COLS):
    return {
        "mergeCells": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_idx,
                "endRowIndex": row_idx + 1,
                "startColumnIndex": 0,
                "endColumnIndex": num_cols,
            },
            "mergeType": "MERGE_ALL",
        }
    }


def _text_format_request(sheet_id, row_idx, bold=False, font_size=10, color=None, num_cols=NUM_COLS):
    fmt = {"bold": bold, "fontSize": font_size}
    if color:
        fmt["foregroundColor"] = color
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_idx,
                "endRowIndex": row_idx + 1,
                "startColumnIndex": 0,
                "endColumnIndex": num_cols,
            },
            "cell": {"userEnteredFormat": {"textFormat": fmt}},
            "fields": "userEnteredFormat.textFormat",
        }
    }


def _col_width_request(sheet_id, col_idx, width_px):
    return {
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": col_idx,
                "endIndex": col_idx + 1,
            },
            "properties": {"pixelSize": width_px},
            "fields": "pixelSize",
        }
    }


def _freeze_request(sheet_id, rows=1):
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": rows},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    }


def export_to_sheets(rows, title):
    """
    Write rows to a Google Sheet. Updates the sheet if one with the same title
    already exists in Drive; otherwise creates a new one.
    Returns the URL of the sheet.
    """

    gc = _gc()

    try:
        spreadsheet = gc.open(title)
        print(f"Updating existing sheet: '{title}'...")
        ws = spreadsheet.sheet1
        ws.clear()
    except SpreadsheetNotFound:
        print(f"Creating new sheet: '{title}'...")
        spreadsheet = gc.create(title)
        ws = spreadsheet.sheet1
        ws.update_title("Keepers")

    sheet_id = ws.id

    # -----------------------------------------------------------------------
    # Build the grid: header row + team header + player rows + blank separators
    # -----------------------------------------------------------------------
    grid = []          # list of row value lists
    fmt_requests = []  # batchUpdate formatting requests
    current_row = 0    # 0-indexed

    # Header row
    grid.append(COLUMNS)
    fmt_requests.append(_row_bg_request(sheet_id, current_row, COLOR_HEADER_BG))
    fmt_requests.append(_text_format_request(
        sheet_id, current_row, bold=True, font_size=10,
        color={"red": 1.0, "green": 1.0, "blue": 1.0}
    ))
    current_row += 1

    # Group rows by team
    teams = {}
    for row in rows:
        teams.setdefault(row["Team"], []).append(row)

    for team_name, team_rows in teams.items():
        # Blank spacer between teams (skip before first team)
        if current_row > 1:
            grid.append([""] * NUM_COLS)
            current_row += 1

        # Team header row
        grid.append([team_name] + [""] * (NUM_COLS - 1))
        fmt_requests.append(_merge_request(sheet_id, current_row))
        fmt_requests.append(_row_bg_request(sheet_id, current_row, COLOR_TEAM_HEADER))
        fmt_requests.append(_text_format_request(
            sheet_id, current_row, bold=True, font_size=10,
            color={"red": 1.0, "green": 1.0, "blue": 1.0}
        ))
        current_row += 1

        # Player rows
        for r in team_rows:
            grid.append([r[c] for c in COLUMNS])
            keeper_count = r.get("Keeper Count", 0)
            if keeper_count == 2:
                fmt_requests.append(_row_bg_request(sheet_id, current_row, COLOR_RED))
            elif keeper_count == 1:
                fmt_requests.append(_row_bg_request(sheet_id, current_row, COLOR_YELLOW))
            else:
                fmt_requests.append(_row_bg_request(sheet_id, current_row, COLOR_WHITE))
            current_row += 1

    # -----------------------------------------------------------------------
    # Write all values at once
    # -----------------------------------------------------------------------
    print(f"Writing {len(grid)} rows...")
    ws.update(grid, "A1")

    # -----------------------------------------------------------------------
    # Column widths
    # -----------------------------------------------------------------------
    col_widths = [180, 200, 110, 100, 90, 100]
    for i, w in enumerate(col_widths):
        fmt_requests.append(_col_width_request(sheet_id, i, w))

    # Freeze header row
    fmt_requests.append(_freeze_request(sheet_id))

    # -----------------------------------------------------------------------
    # Apply all formatting in one batch
    # -----------------------------------------------------------------------
    print("Applying formatting...")
    spreadsheet.batch_update({"requests": fmt_requests})

    url = spreadsheet.url
    print(f"Sheet created: {url}")
    return url
