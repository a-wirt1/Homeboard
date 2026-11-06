#!/usr/bin/env python3
"""Homeboard Munich events: Eventsimple + EventIndex + Evensos.
Rausgegangen is deliberately not scraped: no verified public feed.
Python 3.9+, standard library only. Failures in optional sources do not block others.
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
NOW = datetime.now(TZ)
UNTIL = NOW + timedelta(days=10)
OUT = Path('events.json')
HEADERS = {'User-Agent': 'Homeboard/5.3 (personal event recommendations)', 'Accept': 'application/json, application/ld+json'}
BOOST = {'coffee rave': 30, 'day rave': 30, 'dayrave': 30, 'rave': 20, 'techno': 16,
         'house music': 15, 'house party': 15, 'disco': 12, 'dj set': 12, 'clubnacht': 13,
         'street food': 20, 'streetfood': 20, 'food festival': 20, 'supper club': 18,
         'pop-up': 14, 'popup': 14, 'tasting': 10, 'kulinar': 10, 'food': 8,
         'fotografie': 20, 'photography': 20, 'fotoausstellung': 20,
         'vintage': 16, 'designmarkt': 16, 'flohmarkt': 12, 'kreativmarkt': 14,
         'nightlife': 10, 'party': 9, 'markt': 5, 'festival': 5}
PENALTY = {'arena tour': -35, 'olympiahalle': -28, 'stadion': -25,
           'sinfonie': -15, 'oper': -15, 'klassische musik': -15,
           'nico santos': -30, 'meisterwerke': -8}
CATEGORY_SCORE = {'party': 13, 'nightlife': 13, 'essen': 10, 'food-drink': 10,
                  'markt': 9, 'maerkte': 9, 'festival': 7, 'festivals': 7,
                  'kunst': 3, 'arts': 3, 'konzert': 0, 'music': 2, 'concerts': 0,
                  'film': 1, 'theater': -5, 'sport': -8, 'business': -8}


def get(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=22) as response:
        return json.load(response)


def dt(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)
    except ValueError:
        return None


def string(value, limit=140):
    if isinstance(value, dict):
        value = value.get('name') or value.get('value') or ''
    if isinstance(value, list):
        value = ' '.join(str(v) for v in value if isinstance(v, str))
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def place_name(value):
    if isinstance(value, dict):
        return string(value.get('name') or (value.get('address') or {}).get('addressLocality') if isinstance(value.get('address'), dict) else value.get('name'), 65)
    return string(value, 65)


def city_of(value):
    if isinstance(value, dict):
        address = value.get('address') or {}
        if isinstance(address, dict):
            return string(address.get('addressLocality')).casefold()
    return ''


def candidate(title, url, start, end=None, venue='', category='', description='', source='', city=''):
    title, url = string(title, 110), string(url, 600)
    if not title or not url.startswith('https://') or not start:
        return None
    if city and city.casefold() not in ('münchen', 'muenchen', 'munich'):
        return None
    end = end or start
    if end < NOW or start > UNTIL:
        return None
    category = string(category, 35).lower()
    text = ' '.join((title, string(venue), category, string(description, 350))).casefold()
    score = CATEGORY_SCORE.get(category, 0)
    for term, points in BOOST.items():
        if term in text:
            score += points
    for term, points in PENALTY.items():
        if term in text:
            score += points
    # Exclude obvious irrelevant results, but allow a sparse week to show weaker choices.
    when = 'Heute' if start < NOW else start.strftime('%a %d.%m.') + (' ' + start.strftime('%H:%M') if start.hour or start.minute else '')
    return {'title': title, 'url': url, 'when': when, 'venue': string(venue, 65) or 'München',
            'category': category.upper() or 'EVENT', '_source': source, '_start': start,
            '_score': score, '_category': category}


def eventsimple():
    params = {'from': NOW.date().isoformat(), 'to': UNTIL.date().isoformat(),
              'city': 'München', 'country': 'DE', 'limit': '1000'}
    raw = get('https://eventsimple.de/api/events?' + urllib.parse.urlencode(params))
    rows = raw.get('events') if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise ValueError('unexpected Eventsimple response')
    result = []
    for e in rows:
        if not isinstance(e, dict):
            continue
        url = e.get('url')
        if not isinstance(url, str) or not url.startswith('https://'):
            rel = e.get('detail_url', '')
            url = 'https://eventsimple.de' + rel if isinstance(rel, str) and rel.startswith('/veranstaltung/') else ''
        item = candidate(e.get('title'), url, dt(e.get('starts_at')),
                         dt(e.get('ends_at')), e.get('venue'), e.get('category'),
                         e.get('description'), 'Eventsimple', e.get('city', ''))
        if item:
            result.append(item)
    return len(rows), result


def eventindex():
    params = {'lat': 48.1374, 'lng': 11.5755, 'radius': 20,
              'from': NOW.date().isoformat(), 'to': UNTIL.date().isoformat(), 'limit': 100}
    raw = get('https://eventindex.io/api/v1/events?' + urllib.parse.urlencode(params))
    # The documented format uses `hits`. Alternate JSON-LD collection wrappers
    # are accepted, but an unknown response is reported rather than guessed.
    rows = None
    if isinstance(raw, dict):
        for key in ('hits', 'itemListElement', 'items', 'events', '@graph'):
            if isinstance(raw.get(key), list):
                rows = raw[key]
                break
    elif isinstance(raw, list):
        rows = raw
    if rows is None:
        shape = ('keys=' + ','.join(sorted(str(k) for k in raw.keys())[:15])) if isinstance(raw, dict) else ('type=' + type(raw).__name__)
        raise ValueError('unexpected EventIndex response (' + shape + ')')
    result = []
    detail_requests = 0
    for entry in rows:
        e = entry.get('item', entry) if isinstance(entry, dict) else None
        if not isinstance(e, dict):
            continue
        url = e.get('url') or e.get('event_url') or e.get('website') or ''
        # Detail endpoint is documented; its public canonical URL is not.
        # Limit additional requests to avoid hitting the anonymous rate limit.
        if not url and e.get('slug') and detail_requests < 12:
            detail_requests += 1
            try:
                detail = get('https://eventindex.io/api/v1/events/' + urllib.parse.quote(str(e['slug']), safe=''))
                if isinstance(detail, dict):
                    url = detail.get('url') or detail.get('event_url') or detail.get('website') or ''
            except Exception:
                pass
        tags = e.get('tags', [])
        category = ' '.join(str(t) for t in tags) if isinstance(tags, list) else string(tags)
        item = candidate(e.get('title') or e.get('name'), url,
                         dt(e.get('start_date') or e.get('startDate')),
                         dt(e.get('end_date') or e.get('endDate')),
                         place_name(e.get('venue') or e.get('location')),
                         category, e.get('description'), 'EventIndex', e.get('city', ''))
        if item:
            result.append(item)
    print('EventIndex detail requests: %d' % detail_requests)
    return len(rows), result


def evensos():
    # Public documented city-specific JSON-LD list. Try German and English city slugs.
    raw = None
    for slug in ('muenchen', 'munich'):
        try:
            raw = get('https://www.evensos.de/events/' + slug + '.json')
            break
        except Exception:
            pass
    if raw is None:
        raise ValueError('neither city feed responded')
    rows = raw.get('dataFeedElement') if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise ValueError('unexpected Evensos DataFeed response')
    result = []
    for entry in rows:
        e = entry.get('item', entry) if isinstance(entry, dict) else None
        if not isinstance(e, dict):
            continue
        location = e.get('location') or {}
        category = e.get('eventType') or e.get('keywords') or e.get('genre') or ''
        item = candidate(e.get('name'), e.get('url') or e.get('@id'),
                         dt(e.get('startDate')), dt(e.get('endDate')),
                         place_name(location), category, e.get('description'),
                         'Evensos', city_of(location))
        if item:
            result.append(item)
    return len(rows), result


def dedup_key(e):
    title = re.sub(r'[^a-z0-9äöüß]+', '', e['title'].casefold())
    # same title + day, regardless of source
    return (title, e['_start'].date().isoformat())


def main():
    all_items, stats = [], {}
    for name, fetcher in [('Eventsimple', eventsimple), ('EventIndex', eventindex), ('Evensos', evensos)]:
        try:
            raw_count, items = fetcher()
            all_items.extend(items)
            stats[name] = {'raw': raw_count, 'eligible': len(items), 'status': 'ok'}
            print('%s: %d raw, %d eligible' % (name, raw_count, len(items)))
        except Exception as exc:
            stats[name] = {'raw': 0, 'eligible': 0, 'status': 'error: ' + str(exc)[:150]}
            print('WARNING %s: %s' % (name, exc), file=sys.stderr)
    stats['Rausgegangen'] = {'raw': 0, 'eligible': 0, 'status': 'not connected: no verified public API/feed'}
    unique = {}
    for e in all_items:
        key = dedup_key(e)
        if key not in unique or e['_score'] > unique[key]['_score']:
            unique[key] = e
    ranked = sorted(unique.values(), key=lambda e: (-e['_score'], e['_start']))
    selected = ranked[:9]
    public = []
    for e in selected:
        public.append({k: v for k, v in e.items() if not k.startswith('_')})
    result = {'updated_at': datetime.now(timezone.utc).isoformat(),
              'source': 'Eventsimple, EventIndex, Evensos (when available)',
              'events': public, 'source_stats': stats}
    if not public and OUT.exists():
        print('WARNING: no new events; preserving previous events.json', file=sys.stderr)
        return
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('TOTAL: %d eligible, %d unique, %d selected' % (len(all_items), len(unique), len(selected)))

if __name__ == '__main__':
    main()
