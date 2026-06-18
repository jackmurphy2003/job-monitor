import re
import time
import requests

RAW = """
Amazon, LVMH, Spotify, Google, Meta, Uber, Reddit, SpaceX, Apple, Microsoft,
Stripe, Salesforce, Robinhood, Morgan Stanley, JP Morgan, Goldman Sachs,
BlackRock, NVIDIA, DoorDash, Roblox, Twitch, AirBnb, EY-Parthenon, PWC,
Deloitte, Houlihan Lokey, Kroll, KPMG, Fanatics, Snap, Lyft, Intuit, Coinbase,
NBCUniversal, NFL, NBA, Snowflake, Block (Square), Hulu, Riot Games,
Epic Games, Take Two, Nike, PepsiCo, Stout, Alvarez & Marsal, Primary Wave,
Concord, WME, WMG, Adidas, FTI Consulting, BDO Deal Advisory, Asana, Figma,
Lincoln, Boeing, Adobe, ServiceNow, Cisco, Oracle, Databricks, OpenAI,
Anthropic, Visa, Mastercard, PayPal, American Express, Capital One,
The Walt Disney Company, Warner Bros. Discovery, Sony Pictures, Paramount,
Electronic Arts (EA), Live Nation, Ticketmaster, Grant Thornton, RSM US,
VRC Valuation Research, Lincoln International, Universal Music Group,
Sony Music, Endeavor, CAA, Wasserman, AEG, Genius Sports, Sportradar,
Dodgers, Lakers, Rams, Clippers, LAFC
"""

DEFAULT_KEYWORDS = "finance,strategy,corporate development,valuation,financial analyst,internship,rotation"
DEFAULT_LOCATIONS = "San Francisco,New York,Los Angeles,Seattle,Remote"

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (job-discovery)"


def companies():
    items = [c.strip() for c in RAW.replace("\n", " ").split(",")]
    seen, out = set(), []
    for c in items:
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def slug_candidates(name):
    paren = re.findall(r"\(([^)]+)\)", name)
    base = re.sub(r"\([^)]*\)", "", name)
    cands = []
    for part in re.split(r"[/]", base) + paren:
        words = re.findall(r"[a-z0-9]+", part.lower())
        if not words:
            continue
        cands += ["".join(words), "-".join(words), words[0]]
    out, seen = [], set()
    for c in cands:
        if len(c) >= 2 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def probe_greenhouse(slug):
    r = session.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=10)
    if r.status_code == 200:
        jobs = r.json().get("jobs", [])
        if jobs:
            return len(jobs), jobs[0].get("title", "")
    return None


def probe_lever(slug):
    r = session.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=10)
    if r.status_code == 200:
        jobs = r.json()
        if isinstance(jobs, list) and jobs:
            return len(jobs), jobs[0].get("text", "")
    return None


def probe_ashby(slug):
    r = session.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=10)
    if r.status_code == 200:
        jobs = r.json().get("jobs", [])
        if jobs:
            return len(jobs), jobs[0].get("title", "")
    return None


PROBES = [("greenhouse", probe_greenhouse), ("lever", probe_lever), ("ashby", probe_ashby)]


def main():
    found = []
    names = companies()
    print(f"Checking {len(names)} unique companies...\n")

    for name in names:
        hit = None
        for slug in slug_candidates(name):
            for ats, fn in PROBES:
                try:
                    res = fn(slug)
                except Exception:
                    res = None
                time.sleep(0.2)
                if res:
                    count, sample = res
                    hit = (ats, slug, count, sample)
                    break
            if hit:
                break
        if hit:
            ats, slug, count, sample = hit
            print(f'FOUND  {name:28} {ats:11} token={slug:22} ({count} roles, e.g. "{sample[:50]}")')
            found.append((name, ats, slug))
        else:
            print(f"  --   {name:28} not on greenhouse/lever/ashby (custom portal, use native alerts)")

    print("\n" + "=" * 60)
    print(f"{len(found)} of {len(names)} confirmed on an easy ATS.\n")
    print("Paste-ready rows for your Targets tab (status OFF so you review first):\n")
    for name, ats, slug in found:
        print(f'{name},{ats},{slug},"{DEFAULT_KEYWORDS}","{DEFAULT_LOCATIONS}",OFF')


if __name__ == "__main__":
    main()
