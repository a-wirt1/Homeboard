#!/usr/bin/env python3
"""Public Munich events feed -> events.json; no keys or personal data."""
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

URL = "https://comealone.app/feed/v1/city/munich.json"
OUTPUT = Path("events.json")
TZ = ZoneInfo("Europe/Berlin")

def first(obj, *names):
    for name in names:
        value = obj.get(name)
        if value is not None and value != "":
            return value
    return None

def parse_date(value):
    if not value:
        return None
    if isinstance(value, dict):
        value = first(value, "start", "date", "datetime")
    if not isinstance(value, str):
        return None
    value = value.strip().replace("Z", "+00:00")
    try:
        date = datetime.fromisoformat(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=TZ)
        return date.astimezone(TZ)
    except ValueError:
        return None

def normalize(event, now):
    if not isinstance(event, dict):
        return None
    title = first(event, "title", "name")
    date = parse_date(first(event, "starts_at", "start_at", "start_time", "start_date", "start", "date", "datetime", "date_start"))
    url = first(event, "source_url", "url", "event_url", "link")
    if isinstance(url, dict):
        url = first(url, "url", "href")
    if not title or not date or not isinstance(url, str) or not url.startswith("https://"):
        return None
    if date < now or date > now + timedelta(days=7):
        return None
    venue = first(event, "venue_name", "venue", "location_name", "location", "place")
    if isinstance(venue, dict):
        venue = first(venue, "name", "title")
    if not isinstance(venue, str):
        venue = "München"
    cat = first(event, "category", "type", "tag")
    if isinstance(cat, list):
        cat = cat[0] if cat else "EVENT"
    if not isinstance(cat, str):
        cat = "EVENT"
    title = re.sub(r"\s+", " ", str(title)).strip()[:110]
    return {"title": title, "url": url, "when": date.strftime("%a %d.%m. %H:%M"),
            "venue": venue[:65], "category": cat[:30].upper(), "sort_date": date.isoformat()}

def main():
    req = urllib.request.Request(URL, headers={"User-Agent": "Homeboard/1.0 (personal dashboard)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        raw = json.load(response)
    items = raw.get("events", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Unknown events feed structure")
    now = datetime.now(TZ)
    result = [e for x in items if (e := normalize(x, now))]
    result.sort(key=lambda e: e["sort_date"])
    seen = set()
    unique = []
    for item in result:
        key = item["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append({k:v for k,v in item.items() if k != "sort_date"})
    if items and not result:
        print("WARNING: No future events matched. Check source schema and date fields.", file=sys.stderr)
    data = {"updated_at": datetime.now(timezone.utc).isoformat(), "source": "Come Alone / Meet & Mint", "events": unique[:3]}
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Read {len(items)} source items; selected {len(unique[:3])} Munich events")

if __name__ == "__main__":
    main()
