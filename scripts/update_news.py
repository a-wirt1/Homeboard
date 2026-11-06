#!/usr/bin/env python3
"""Build a compact, source-attributed news.json for the static Homeboard.
No API key, third-party packages or generative summaries needed.
"""
import datetime as dt
import email.utils
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'news.json'
FEEDS = [
    ('tagesschau', 'https://www.tagesschau.de/xml/rss2/'),
    ('Deutschlandfunk', 'https://www.deutschlandfunk.de/nachrichten-100.rss'),
    ('ZDFheute', 'https://www.zdfheute.de/rss/zdf/nachrichten'),
]
STOP = set('der die das und oder mit bei für von aus auf zur zum über nach eine einer eines einem einen ist sind wird wurde werden haben hatte auch nicht noch mehr heute gestern aktuell jetzt sich den dem des im in am an als um zu es ein er sie wir ihr vor durch gegen seit laut wegen unter trotz neue neuen neuer news live ticker meldung'.split())
IMPORTANT = {'bundestag': 3, 'bundesregierung': 3, 'kanzler': 2, 'eu': 2, 'europa': 2, 'ukraine': 3, 'russland': 3, 'usa': 2, 'china': 2, 'krieg': 4, 'wahl': 3, 'wahlen': 3, 'wirtschaft': 2, 'inflation': 3, 'energie': 2, 'klima': 2, 'urteil': 2, 'gericht': 2, 'katastrophe': 3, 'streik': 2, 'münchen': 1}

def clean(s):
    s = re.sub(r'<[^>]*>', ' ', s or '')
    return re.sub(r'\s+', ' ', html.unescape(s)).strip()

def stamp(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
        if d:
            return d.astimezone(dt.timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(dt.timezone.utc)
    except (ValueError, TypeError):
        return None

def tokens(s):
    return set(x for x in re.findall(r'[a-zäöüß]{4,}', s.lower()) if x not in STOP)

def fetch(source, url, now):
    req = urllib.request.Request(url, headers={'User-Agent': 'HomeboardNews/1.0 (+GitHub Actions)', 'Accept': 'application/rss+xml,application/xml,text/xml,*/*'})
    with urllib.request.urlopen(req, timeout=18) as response:
        xml = response.read(2_000_000)
    root = ET.fromstring(xml)
    items = root.findall('.//item')
    if not items:  # Atom fallback
        items = root.findall('{http://www.w3.org/2005/Atom}entry')
    results = []
    for item in items[:45]:
        def value(name):
            x = item.find(name)
            return ''.join(x.itertext()).strip() if x is not None else ''
        title = clean(value('title') or value('{http://www.w3.org/2005/Atom}title'))
        summary = clean(value('description') or value('{http://www.w3.org/2005/Atom}summary'))
        link = value('link')
        if not link:
            node = item.find('{http://www.w3.org/2005/Atom}link')
            link = node.get('href', '') if node is not None else ''
        published = stamp(value('pubDate') or value('{http://www.w3.org/2005/Atom}updated') or value('{http://www.w3.org/2005/Atom}published'))
        if not (title and link.startswith('https://') and published):
            continue
        age = (now - published).total_seconds() / 3600
        if age < -1 or age > 36:
            continue
        if len(title) < 20:
            continue
        results.append({'title': title[:160], 'summary': summary[:240], 'url': link, 'source': source, 'published': published.isoformat().replace('+00:00','Z'), '_age': max(age,0), '_tokens': tokens(title)})
    return results

def rank(items):
    for item in items:
        cross = set()
        for other in items:
            if other is item or other['source'] == item['source']:
                continue
            a, b = item['_tokens'], other['_tokens']
            if len(a & b) >= 2 and len(a & b) / max(1, min(len(a), len(b))) >= .38:
                cross.add(other['source'])
        item['_score'] = 4 * len(cross) + sum(IMPORTANT.get(t, 0) for t in item['_tokens']) + max(0, 5 - item['_age'] / 5)
    selected = []
    for item in sorted(items, key=lambda x: (-x['_score'], x['_age'])):
        if any(len(item['_tokens'] & prev['_tokens']) >= 2 and len(item['_tokens'] & prev['_tokens']) / max(1, min(len(item['_tokens']), len(prev['_tokens']))) >= .38 for prev in selected):
            continue
        selected.append(item)
        if len(selected) == 3:
            break
    return [{k:v for k,v in i.items() if not k.startswith('_')} for i in selected]

def main():
    now = dt.datetime.now(dt.timezone.utc)
    all_items = []
    errors = []
    for source, url in FEEDS:
        try:
            found = fetch(source, url, now)
            all_items.extend(found)
            print(source, len(found), 'recent articles')
        except Exception as exc:
            errors.append(f'{source}: {exc}')
            print('Feed failed:', source, exc)
    if not all_items:
        # Do not overwrite the last good data with empty or invented stories.
        raise SystemExit('No current news available; preserving previous news.json. ' + '; '.join(errors))
    data = {'updated_at': now.isoformat(timespec='seconds').replace('+00:00','Z'), 'method': 'Automatische Auswahl aus RSS-Feeds nach Aktualität, Themengewichtung und Quellenübereinstimmung; keine redaktionelle Rangliste.', 'stories': rank(all_items)}
    if len(data['stories']) < 3:
        raise SystemExit('Fewer than three distinct stories; preserving previous news.json')
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Wrote', OUTPUT, 'with', len(data['stories']), 'stories')

if __name__ == '__main__':
    main()
