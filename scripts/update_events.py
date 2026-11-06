#!/usr/bin/env python3
"""Select Munich events from Eventsimple's documented public JSON API.
No API key or personal data. Intended for GitHub Actions every few hours.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Berlin')
OUTPUT = Path('events.json')
CATEGORIES = {'konzert', 'festival', 'party', 'kunst', 'film', 'markt', 'essen', 'vortrag', 'theater', 'stadtfest'}
PRIORITY = {'essen': 6, 'markt': 6, 'festival': 5, 'konzert': 5, 'party': 4, 'kunst': 4, 'film': 3, 'stadtfest': 4, 'vortrag': 2, 'theater': 2}

def dt(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)
    except ValueError:
        return None

def clean(value, maxlen):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:maxlen]

def normalize(e, now):
    if not isinstance(e, dict):
        return None
    category = str(e.get('category') or '').lower()
    if category not in CATEGORIES or str(e.get('city') or '').casefold() not in ('münchen', 'muenchen', 'munich'):
        return None
    start = dt(e.get('starts_at'))
    end = dt(e.get('ends_at')) or start
    if not start or end < now or start > now + timedelta(days=7):
        return None
    title = clean(e.get('title'), 110)
    venue = clean(e.get('venue') or 'München', 65)
    url = e.get('url')
    if not isinstance(url, str) or not url.startswith('https://'):
        relative = e.get('detail_url')
        if not isinstance(relative, str) or not relative.startswith('/veranstaltung/'):
            return None
        url = 'https://eventsimple.de' + relative
    if not title:
        return None
    # Multi-day exhibitions may have started weeks ago: display "Heute" rather than the past opening date.
    display_date = max(start, now) if end >= now else start
    when = ('Heute' if start < now else display_date.strftime('%a %d.%m.'))
    if not e.get('all_day') and start >= now:
        when += ' ' + start.strftime('%H:%M')
    return {'title': title, 'url': url, 'when': when, 'venue': venue,
            'category': clean(e.get('category_label') or category, 30).upper(),
            '_category': category, '_start': start, '_score': PRIORITY.get(category, 0)}

def main():
    now = datetime.now(TZ)
    params = {'from': now.date().isoformat(), 'to': (now + timedelta(days=7)).date().isoformat(),
              'city': 'München', 'country': 'DE', 'category': ','.join(sorted(CATEGORIES)), 'limit': '1000'}
    url = 'https://eventsimple.de/api/events?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'Homeboard/1.0 (private dashboard)', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=25) as response:
        raw = json.load(response)
    if not isinstance(raw, dict) or not isinstance(raw.get('events'), list):
        raise ValueError('Eventsimple returned an unexpected JSON structure')
    candidates = [x for event in raw['events'] if (x := normalize(event, now))]
    # Prioritise varied cultural/food tips; avoid filling all three slots with one category.
    candidates.sort(key=lambda e: (-e['_score'], e['_start']))
    selected, seen_titles, seen_categories = [], set(), set()
    for diversity in (True, False):
        for item in candidates:
            key = item['title'].casefold()
            if key in seen_titles or (diversity and item['_category'] in seen_categories):
                continue
            selected.append(item)
            seen_titles.add(key)
            seen_categories.add(item['_category'])
            if len(selected) == 3:
                break
        if len(selected) == 3:
            break
    public = [{k: v for k, v in e.items() if not k.startswith('_')} for e in selected]
    data = {'updated_at': datetime.now(timezone.utc).isoformat(), 'source': 'Eventsimple', 'events': public}
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Eventsimple returned {len(raw['events'])} events; {len(candidates)} eligible; {len(public)} selected")
    if not public:
        print('WARNING: No matching events. Check Munich coverage and filters.', file=sys.stderr)

if __name__ == '__main__':
    main()
