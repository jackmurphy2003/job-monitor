import os
import json
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TIMEOUT = 20


def fetch_greenhouse(token):
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        out.append({
            "id": str(j.get("id")),
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""),
        })
    return out


def fetch_lever(token):
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json():
        cats = j.get("categories") or {}
        out.append({
            "id": str(j.get("id")),
            "title": j.get("text", ""),
            "location": cats.get("location", ""),
            "url": j.get("hostedUrl", ""),
        })
    return out


def fetch_ashby(token):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        out.append({
            "id": str(j.get("id")),
            "title": j.get("title", ""),
            "location": j.get("location", ""),
            "url": j.get("jobUrl", ""),
        })
    return out


def fetch_amazon(query):
    url = "https://www.amazon.jobs/en/search.json"
    params = {"base_query": query, "result_limit": 100, "sort": "recent"}
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        out.append({
            "id": str(j.get("id_icims") or j.get("id")),
            "title": j.get("title", ""),
            "location": j.get("normalized_location", "") or j.get("location", ""),
            "url": "https://www.amazon.jobs" + j.get("job_path", ""),
        })
    return out


ADAPTERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "amazon": fetch_amazon,
}


def matches(job, keywords, locations):
    title = job["title"].lower()
    loc = job["location"].lower()
    if keywords:
        if not any(k.strip().lower() in title for k in keywords if k.strip()):
            return False
    if locations:
        if not any(l.strip().lower() in loc for l in locations if l.strip()):
            return False
    return True


def open_sheet():
    info = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(os.environ["SHEET_ID"])


def read_targets(sheet):
    ws = sheet.worksheet("Targets")
    rows = ws.get_all_records()
    targets = []
    for row in rows:
        if str(row.get("status", "")).strip().upper() != "ON":
            continue
        targets.append({
            "company": str(row.get("company", "")).strip(),
            "ats": str(row.get("ats", "")).strip().lower(),
            "token": str(row.get("token", "")).strip(),
            "keywords": [k for k in str(row.get("keywords", "")).split(",")],
            "locations": [l for l in str(row.get("locations", "")).split(",")],
        })
    return targets


def read_seen_keys(sheet):
    ws = sheet.worksheet("Hits")
    records = ws.get_all_records()
    return {str(r.get("job_key", "")) for r in records}, ws


def send_email(new_hits):
    addr = os.environ.get("GMAIL_ADDRESS")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("ALERT_EMAIL", addr)
    if not (addr and pw):
        print("Email not configured, skipping send.")
        return
    lines = [f"{len(new_hits)} new role(s) matched your targets:\n"]
    by_company = {}
    for h in new_hits:
        by_company.setdefault(h["company"], []).append(h)
    for company, jobs in by_company.items():
        lines.append(f"\n{company}")
        for j in jobs:
            loc = f" ({j['location']})" if j["location"] else ""
            lines.append(f"  - {j['title']}{loc}\n    {j['url']}")
    msg = MIMEText("\n".join(lines))
    msg["Subject"] = f"[Job Monitor] {len(new_hits)} new role(s)"
    msg["From"] = addr
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(addr, pw)
        server.send_message(msg)
    print(f"Email sent to {to}.")


def main():
    sheet = open_sheet()
    targets = read_targets(sheet)
    seen, hits_ws = read_seen_keys(sheet)
    print(f"{len(targets)} active targets, {len(seen)} jobs already seen.")

    new_hits = []
    new_rows = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for t in targets:
        adapter = ADAPTERS.get(t["ats"])
        if not adapter:
            print(f"  skip {t['company']}: unknown ats '{t['ats']}'")
            continue
        try:
            jobs = adapter(t["token"])
        except Exception as e:
            print(f"  ERROR {t['company']} ({t['ats']}/{t['token']}): {e}")
            continue

        kept = [j for j in jobs if matches(j, t["keywords"], t["locations"])]
        print(f"  {t['company']}: {len(jobs)} roles, {len(kept)} match filters")

        for j in kept:
            key = f"{t['company'].lower()}:{j['id']}"
            if key in seen:
                continue
            seen.add(key)
            new_hits.append({**j, "company": t["company"], "key": key})
            new_rows.append([today, t["company"], j["title"], j["location"], j["url"], key])

    if new_rows:
        hits_ws.append_rows(new_rows, value_input_option="RAW")
        print(f"Logged {len(new_rows)} new hit(s) to the sheet.")
        send_email(new_hits)
    else:
        print("No new roles today.")


if __name__ == "__main__":
    main()
