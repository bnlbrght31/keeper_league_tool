import base64
import json
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import gspread
from googleapiclient.discovery import build
from gspread.exceptions import WorksheetNotFound

from google_auth import get_credentials

# ---------------------------------------------------------------------------
# Apps Script templates
# ---------------------------------------------------------------------------

# _GAS_CODE is formatted with Python's .format(), so JS braces are doubled.
_GAS_CODE = """
const SPREADSHEET_ID = '{spreadsheet_id}';
const PROPOSED_DATES = {dates_json};
const LEAGUE_NAME = '{league_name}';
const EXPECTED_NAMES = {names_json};

function doGet(e) {{
  var template = HtmlService.createTemplateFromFile('calendar');
  template.proposedDates = JSON.stringify(PROPOSED_DATES);
  template.leagueName = LEAGUE_NAME;
  return template.evaluate()
    .setTitle('Draft Date Poll — ' + LEAGUE_NAME)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}}

function submitAvailability(name, availability) {{
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);

  var resp = ss.getSheetByName('Schedule Responses');
  if (!resp) {{
    resp = ss.insertSheet('Schedule Responses');
    var headers = ['Name', 'Submitted At'].concat(PROPOSED_DATES);
    resp.appendRow(headers);
    resp.setFrozenRows(1);
  }}

  var data = resp.getDataRange().getValues();
  for (var i = data.length - 1; i >= 1; i--) {{
    if (data[i][0] === name) resp.deleteRow(i + 1);
  }}

  var row = [name, new Date().toISOString()];
  for (var i = 0; i < PROPOSED_DATES.length; i++) {{
    row.push(availability[PROPOSED_DATES[i]] || 'none');
  }}
  resp.appendRow(row);
  SpreadsheetApp.flush(); // commit the new response before rebuilding the summary

  rebuildSummary(ss);
  return 'success';
}}

function rebuildSummary(ss) {{
  var resp = ss.getSheetByName('Schedule Responses');
  var sched = ss.getSheetByName('Draft Schedule');
  if (!resp || !sched) return;

  var data = resp.getDataRange().getValues();
  if (data.length < 2) return;

  // Column positions are fixed: 0=Name, 1=Submitted At, 2..N=dates in PROPOSED_DATES order.
  // Avoids parsing header dates, which Apps Script returns as Date objects not strings.
  var responses = {{}};
  for (var r = 1; r < data.length; r++) {{
    var n = data[r][0];
    responses[n] = {{}};
    for (var i = 0; i < PROPOSED_DATES.length; i++) {{
      responses[n][PROPOSED_DATES[i]] = data[r][i + 2] || 'none';
    }}
  }}

  var allNames = EXPECTED_NAMES.slice();
  for (var n in responses) {{
    if (allNames.indexOf(n) === -1) allNames.push(n);
  }}

  sched.clearContents();

  var headerRow = [''];
  for (var d of PROPOSED_DATES) {{
    var parts = d.split('-');
    var dt = new Date(parts[0], parts[1]-1, parts[2]);
    headerRow.push(Utilities.formatDate(dt, Session.getScriptTimeZone(), 'EEE M/d'));
  }}
  sched.appendRow(headerRow);

  // Build person rows and track background colors in parallel to avoid re-reading cells later
  var numCols = PROPOSED_DATES.length + 1;
  var statusEmoji   = {{ yes: '✅', maybe: '🟡', no: '❌', none: '—' }};
  var colorByStatus = {{ yes: '#c6efce', maybe: '#ffeb9c', no: '#ffc7ce', none: '#f1f3f4' }};
  var bgRows = [];
  for (var name of allNames) {{
    var row = [name];
    var bgRow = ['#ffffff'];
    for (var d of PROPOSED_DATES) {{
      var val = responses[name] ? responses[name][d] || 'none' : 'none';
      row.push(statusEmoji[val] || '—');
      bgRow.push(colorByStatus[val] || '#ffffff');
    }}
    sched.appendRow(row);
    bgRows.push(bgRow);
  }}

  var labels = ['✅ Yes', '🟡 Maybe', '❌ No', '— No Response'];
  var keys   = ['yes', 'maybe', 'no', 'none'];
  for (var ki = 0; ki < keys.length; ki++) {{
    var row = [labels[ki]];
    for (var d of PROPOSED_DATES) {{
      var count = 0;
      for (var name of allNames) {{
        var val = responses[name] ? responses[name][d] || 'none' : 'none';
        if (ki === 3) {{
          if (!responses[name]) count++;
        }} else {{
          if (val === keys[ki]) count++;
        }}
      }}
      row.push(count);
    }}
    sched.appendRow(row);
  }}

  // Flush pending writes before formatting
  SpreadsheetApp.flush();
  var numRows = sched.getLastRow();

  sched.getRange(1, 1, 1, numCols).setFontWeight('bold').setBackground('#1c3d5a').setFontColor('#ffffff');
  if (numRows >= 5) {{
    sched.getRange(numRows - 3, 1, 4, numCols).setFontWeight('bold').setBackground('#f1f3f4');
  }}
  if (bgRows.length > 0) {{
    sched.getRange(2, 1, bgRows.length, numCols).setBackgrounds(bgRows);
  }}
  sched.setFrozenRows(1);
  sched.setFrozenColumns(1);
  sched.autoResizeColumns(1, numCols);
}}
"""

# _CALENDAR_HTML is NOT formatted with Python's .format(), so single braces are correct.
_CALENDAR_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f5;padding:20px;color:#1a1a1a}
    .card{max-width:720px;margin:0 auto;background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 16px rgba(0,0,0,.1)}
    h1{font-size:22px;margin-bottom:4px}
    .sub{color:#666;font-size:14px;margin-bottom:24px}
    label{display:block;font-weight:600;margin-bottom:6px;font-size:14px}
    input[type=text]{width:100%;padding:10px 12px;border:1.5px solid #ddd;border-radius:8px;font-size:15px;margin-bottom:20px}
    input[type=text]:focus{outline:none;border-color:#1a73e8}
    .legend{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:20px}
    .li{display:flex;align-items:center;gap:6px;font-size:13px;color:#555}
    .dot{width:14px;height:14px;border-radius:50%;flex-shrink:0}
    .month{margin-bottom:28px}
    .mhdr{font-weight:700;font-size:16px;text-align:center;margin-bottom:10px}
    .wdays{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin-bottom:3px}
    .wd{text-align:center;font-size:11px;font-weight:700;color:#999;padding:3px}
    .grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}
    .day{height:46px;display:flex;align-items:center;justify-content:center;border-radius:10px;font-size:14px;font-weight:500;position:relative}
    .empty{background:transparent}
    .other{color:#ccc}
    .proposed{cursor:pointer;background:#f1f3f4;transition:transform .1s}
    .proposed:hover{transform:scale(1.08)}
    .yes{background:#34a853!important;color:#fff}
    .maybe{background:#fbbc04!important;color:#fff}
    .no{background:#ea4335!important;color:#fff}
    .missing{outline:3px solid #7c4dff!important;background:#ede7f6!important;animation:pulse .35s ease-in-out 4}
    @keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.18)}}
    #err-banner{background:#ede7f6;border:1.5px solid #7c4dff;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:14px;color:#4a148c;font-weight:600;display:none}
    .btn{width:100%;padding:14px;background:#1a73e8;color:#fff;border:none;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;margin-top:8px;transition:background .2s}
    .btn:hover{background:#1558c0}
    .btn:disabled{background:#ccc;cursor:not-allowed}
    .success{text-align:center;padding:60px 20px}
    .success h2{color:#34a853;font-size:26px;margin-bottom:10px}
    .success p{color:#666}
    .tip{font-size:12px;color:#999;margin-bottom:16px}
  </style>
</head>
<body>
<div class="card" id="frm">
  <h1>🏈 Draft Date Poll</h1>
  <p class="sub"><?= leagueName ?> — click each date to set your availability</p>

  <label for="nm">Your team name</label>
  <input type="text" id="nm" placeholder="e.g. Ben's Lobos" autocomplete="name" />

  <div class="legend">
    <div class="li"><div class="dot" style="background:#34a853"></div>Available</div>
    <div class="li"><div class="dot" style="background:#fbbc04"></div>Maybe</div>
    <div class="li"><div class="dot" style="background:#ea4335"></div>Not available</div>
    <div class="li"><div class="dot" style="background:#f1f3f4;border:1px solid #ccc"></div>Click to respond</div>
  </div>
  <p class="tip">Click once = available, twice = maybe, three times = not available, four times = clear</p>

  <div id="cals"></div>

  <div id="err-banner"></div>
  <button class="btn" id="sub" onclick="submit()">Submit Availability</button>
</div>

<div class="success" id="ok" style="display:none">
  <h2>✅ Submitted!</h2>
  <p>Your availability has been recorded.<br>You can close this tab.</p>
</div>

<script>
const DATES = <?!= proposedDates ?>;
const proposed = new Set(DATES);
const avail = {};
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const WDAYS  = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

function cycle(d) {
  const order = ['none','yes','maybe','no'];
  const cur = avail[d] || 'none';
  avail[d] = order[(order.indexOf(cur)+1) % order.length];
  const el = document.getElementById('d-'+d);
  el.className = 'day proposed ' + (avail[d]==='none' ? '' : avail[d]);
}

function renderAll() {
  const months = {};
  DATES.forEach(d => {
    const [y,m] = d.split('-');
    const k = y+'-'+m;
    if (!months[k]) months[k] = {y:+y, m:+m-1};
  });
  const cont = document.getElementById('cals');
  Object.values(months)
    .sort((a,b) => a.y*12+a.m - b.y*12+b.m)
    .forEach(({y,m}) => cont.appendChild(renderMonth(y,m)));
}

function renderMonth(y, m) {
  const wrap = document.createElement('div');
  wrap.className = 'month';

  const hdr = document.createElement('div');
  hdr.className = 'mhdr';
  hdr.textContent = MONTHS[m] + ' ' + y;
  wrap.appendChild(hdr);

  const wdays = document.createElement('div');
  wdays.className = 'wdays';
  WDAYS.forEach(d => {
    const wd = document.createElement('div');
    wd.className = 'wd';
    wd.textContent = d;
    wdays.appendChild(wd);
  });
  wrap.appendChild(wdays);

  const grid = document.createElement('div');
  grid.className = 'grid';
  const first = new Date(y, m, 1).getDay();
  const total = new Date(y, m+1, 0).getDate();

  for (let i=0; i<first; i++) {
    const e = document.createElement('div'); e.className='day empty'; grid.appendChild(e);
  }
  for (let d=1; d<=total; d++) {
    const ds = y+'-'+String(m+1).padStart(2,'0')+'-'+String(d).padStart(2,'0');
    const cell = document.createElement('div');
    cell.id = 'd-'+ds;
    cell.className = 'day ' + (proposed.has(ds) ? 'proposed' : 'other');
    cell.textContent = d;
    if (proposed.has(ds)) cell.onclick = () => cycle(ds);
    grid.appendChild(cell);
  }
  wrap.appendChild(grid);
  return wrap;
}

function submit() {
  const name = document.getElementById('nm').value.trim();
  if (!name) { alert('Please enter your team name.'); return; }

  const missing = DATES.filter(d => !avail[d] || avail[d] === 'none');
  if (missing.length > 0) {
    missing.forEach(d => {
      const el = document.getElementById('d-'+d);
      if (el) el.classList.add('missing');
    });
    const first = document.getElementById('d-'+missing[0]);
    if (first) first.scrollIntoView({behavior:'smooth', block:'center'});
    const banner = document.getElementById('err-banner');
    banner.textContent = `${missing.length} date${missing.length===1?'':'s'} still need a response — they're highlighted in purple. Click each one to set your availability.`;
    banner.style.display = 'block';
    return;
  }
  document.getElementById('err-banner').style.display = 'none';

  const btn = document.getElementById('sub');
  btn.disabled = true;
  btn.textContent = 'Submitting…';
  google.script.run
    .withSuccessHandler(() => {
      document.getElementById('frm').style.display='none';
      document.getElementById('ok').style.display='block';
    })
    .withFailureHandler(err => {
      alert('Error: ' + err.message);
      btn.disabled=false;
      btn.textContent='Submit Availability';
    })
    .submitAvailability(name, avail);
}

renderAll();
</script>
</body>
</html>"""

_MANIFEST = {
    "timeZone": "America/New_York",
    "exceptionLogging": "STACKDRIVER",
    "runtimeVersion": "V8",
    "webapp": {
        "executeAs": "USER_DEPLOYING",
        "access": "ANYONE_ANONYMOUS",
    },
}


# ---------------------------------------------------------------------------
# Apps Script deployment
# ---------------------------------------------------------------------------

def _script_service(creds):
    return build("script", "v1", credentials=creds)


def _gmail_service(creds):
    return build("gmail", "v1", credentials=creds)


def _get_stored_script_info(spreadsheet):
    """Read script_id and deployment_id stored in the Schedule Info tab, if any."""
    try:
        ws = spreadsheet.worksheet("Schedule Info")
        vals = ws.col_values(1)
        script_id = deployment_id = None
        for val in vals:
            if str(val).startswith("script_id:"):
                script_id = val.split(":", 1)[1].strip()
            elif str(val).startswith("deployment_id:"):
                deployment_id = val.split(":", 1)[1].strip()
        return script_id, deployment_id
    except Exception:
        return None, None


def create_or_update_script(spreadsheet_id, league_name, dates, names, creds, spreadsheet=None):
    """
    Create or update an Apps Script project and deploy as a web app.
    Reuses an existing project/deployment when IDs are stored in the sheet,
    so the web app URL stays the same across reruns (no repeated auth prompts).
    """
    svc = _script_service(creds)

    gas_code = _GAS_CODE.format(
        spreadsheet_id=spreadsheet_id,
        dates_json=json.dumps(dates),
        league_name=league_name,
        names_json=json.dumps(names),
    )

    files = [
        {"name": "Code",       "type": "SERVER_JS", "source": gas_code},
        {"name": "calendar",   "type": "HTML",      "source": _CALENDAR_HTML},
        {"name": "appsscript", "type": "JSON",      "source": json.dumps(_MANIFEST)},
    ]

    script_id, deployment_id = _get_stored_script_info(spreadsheet) if spreadsheet else (None, None)

    if script_id and deployment_id:
        print("Updating existing Apps Script project...")
        svc.projects().updateContent(scriptId=script_id, body={"files": files}).execute()

        version = svc.projects().versions().create(
            scriptId=script_id,
            body={"description": "updated"},
        ).execute()

        svc.projects().deployments().update(
            scriptId=script_id,
            deploymentId=deployment_id,
            body={
                "deploymentConfig": {
                    "versionNumber": version["versionNumber"],
                    "manifestFileName": "appsscript",
                    "description": "Draft Scheduler Web App",
                }
            },
        ).execute()

        url = f"https://script.google.com/macros/s/{deployment_id}/exec"
        print(f"  Web app URL (unchanged): {url}")
        return url, script_id, deployment_id

    print("Creating Apps Script project...")
    project = svc.projects().create(body={
        "title": f"Draft Scheduler — {league_name}",
        "parentId": spreadsheet_id,
    }).execute()
    script_id = project["scriptId"]

    print("Uploading script files...")
    svc.projects().updateContent(scriptId=script_id, body={"files": files}).execute()

    print("Creating deployment...")
    version = svc.projects().versions().create(
        scriptId=script_id,
        body={"description": "v1"},
    ).execute()

    deployment = svc.projects().deployments().create(
        scriptId=script_id,
        body={
            "versionNumber": version["versionNumber"],
            "manifestFileName": "appsscript",
            "description": "Draft Scheduler Web App",
        },
    ).execute()
    deployment_id = deployment["deploymentId"]

    url = f"https://script.google.com/macros/s/{deployment_id}/exec"
    print(f"  Web app URL: {url}")
    return url, script_id, deployment_id


# ---------------------------------------------------------------------------
# Sheet setup
# ---------------------------------------------------------------------------

def setup_schedule_tab(spreadsheet, dates, names):
    """Create or clear the Draft Schedule tab with placeholder content."""
    try:
        ws = spreadsheet.worksheet("Draft Schedule")
        ws.clear()
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet("Draft Schedule", rows=100, cols=30)

    ws.update([["Waiting for responses — submit the form to see results here."]], "A1")
    return ws


def store_web_app_url(spreadsheet, url, script_id, deployment_id):
    """Store the web app URL and script IDs in a dedicated tab."""
    try:
        ws = spreadsheet.worksheet("Schedule Info")
        ws.clear()
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet("Schedule Info", rows=12, cols=4)

    ws.update([
        ["Draft Schedule Poll"],
        [""],
        ["Share this link with your league:"],
        [url],
        [""],
        [f"script_id:{script_id}"],
        [f"deployment_id:{deployment_id}"],
    ], "A1")

    spreadsheet.batch_update({"requests": [{
        "repeatCell": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": 3,
                "endRowIndex": 4,
                "startColumnIndex": 0,
                "endColumnIndex": 1,
            },
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True, "fontSize": 12,
                               "foregroundColor": {"red": 0.1, "green": 0.45, "blue": 0.85}},
            }},
            "fields": "userEnteredFormat.textFormat",
        }
    }]})


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_invites(web_app_url, emails, league_name, dates, creds):
    svc = _gmail_service(creds)

    date_list = "\n".join(f"  • {d}" for d in dates)
    subject = f"📅 {league_name} — Draft Date Poll"
    body = f"""Hey,

It's time to schedule the {league_name} fantasy draft!

Click the link below to indicate your availability for each proposed date:

{web_app_url}

Proposed dates:
{date_list}

Click each date on the calendar to mark yourself as Available, Maybe, or Not Available.

Thanks!
"""

    html_body = f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:520px;margin:0 auto;padding:24px">
  <h2 style="color:#1a1a1a">📅 {league_name} Draft Date Poll</h2>
  <p style="color:#444;line-height:1.6">
    It's time to schedule the fantasy draft! Click below to mark your availability.
  </p>
  <div style="margin:24px 0">
    <a href="{web_app_url}"
       style="background:#1a73e8;color:#fff;padding:14px 28px;border-radius:8px;
              text-decoration:none;font-weight:700;font-size:15px;display:inline-block">
      Open Availability Poll →
    </a>
  </div>
  <p style="color:#666;font-size:13px"><strong>Proposed dates:</strong></p>
  <ul style="color:#444;font-size:14px;line-height:2">
    {"".join(f"<li>{d}</li>" for d in dates)}
  </ul>
  <p style="color:#999;font-size:12px;margin-top:24px">
    Click each date to cycle through: Available → Maybe → Not Available
  </p>
</div>
"""

    sent = 0
    for email in emails:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["To"] = email
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        print(f"  Sent to {email}")
        sent += 1
        time.sleep(0.3)

    print(f"Sent {sent} invite emails.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_scheduler(spreadsheet_id, league_name, dates, emails, names=None):
    creds = get_credentials()
    gc = gspread.Client(auth=creds)
    spreadsheet = gc.open_by_key(spreadsheet_id)

    print(f"\nSetting up draft schedule for '{league_name}'")
    print(f"  Dates: {', '.join(dates)}")
    print(f"  Emails: {len(emails)}")

    setup_schedule_tab(spreadsheet, dates, names or [])

    web_app_url, script_id, deployment_id = create_or_update_script(
        spreadsheet_id, league_name, dates, names or [], creds, spreadsheet
    )

    store_web_app_url(spreadsheet, web_app_url, script_id, deployment_id)

    print("Sending invite emails...")
    send_invites(web_app_url, emails, league_name, dates, creds)

    print(f"\nDone! Poll URL: {web_app_url}")
    print(f"Sheet: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
    return web_app_url
