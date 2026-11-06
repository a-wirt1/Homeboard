#!/usr/bin/env python3
"""Create a small public MVG departure snapshot for Homeboard.

The MVG website endpoint is unofficial for third parties and can change.
No personal addresses, API keys or credentials are used.
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = 'https://www.mvg.de/api/bgw-pt/v3'
HEADERS = {'User-Agent': 'Homeboard/4.7 (private non-commercial dashboard)', 'Accept': 'application/json'}
OUT = Path(__file__).resolve().parent.parent / 'mvg.json'


def get(path, params):
    url = BASE + path + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def station_id(name):
    result = get('/locations', {'query': name})
    if isinstance(result, dict):
        result = result.get('locations') or result.get('results') or result.get('stations') or []
    for entry in result:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get('name') or entry.get('label') or '')
        identifier = entry.get('globalId') or entry.get('id')
        if title.casefold().replace('ß','ss') == name.casefold().replace('ß','ss') and identifier:
            return identifier
    raise RuntimeError('Haltestelle nicht eindeutig gefunden: ' + name)


def departures(stop, mode):
    result = get('/departures', {'globalId': station_id(stop), 'limit': 80, 'transportTypes': mode})
    if isinstance(result, dict):
        result = result.get('departures') or result.get('results') or []
    if not isinstance(result, list):
        raise RuntimeError('Unerwartetes Antwortformat: ' + stop)
    return result


def normalize(row, direction):
    t = row.get('realtimeDepartureTime') or row.get('plannedDepartureTime')
    if not isinstance(t, (float, int)):
        return None
    return {
        'line': str(row.get('label') or ''),
        'direction': direction,
        'destination': str(row.get('destination') or ''),
        'time': int(t),
        'realtime': bool(row.get('realtime')),
        'delay': int(row.get('delayInMinutes') or 0),
        'cancelled': bool(row.get('cancelled')),
    }


def select(rows, line, destination, direction, limit=2):
    selected=[]
    for row in rows:
        if str(row.get('label') or '').strip() != line:
            continue
        # Exact destination matching avoids accidentally showing the opposite direction.
        # Short-turn services are omitted until their direction is explicitly verified.
        if str(row.get('destination') or '').casefold().strip() != destination.casefold():
            continue
        item=normalize(row,direction)
        if item:
            selected.append(item)
    selected.sort(key=lambda r:r['time'])
    return selected[:limit]


def main():
    now=dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')
    data={'updated_at':now,'bus':[],'u2':[]}
    errors=[]
    try:
        rows=departures('Infanteriestraße Süd','BUS')
        data['bus'] += select(rows,'153','Odeonsplatz','Richtung Odeonsplatz')
        data['bus'] += select(rows,'154','Westerlandanger','Richtung Westerlandanger')
    except Exception as exc:
        errors.append('Bus: '+str(exc))
    try:
        rows=departures('Theresienstraße','UBAHN')
        data['u2'] += select(rows,'U2','Feldmoching','Richtung Feldmoching')
        data['u2'] += select(rows,'U2','Messestadt Ost','Richtung Messestadt Ost')
    except Exception as exc:
        errors.append('U2: '+str(exc))
    if errors:
        # Do not overwrite last valid snapshot with an empty, misleading one.
        print('MVG fetch failed: '+'; '.join(errors),file=sys.stderr)
        return 1
    data['bus'].sort(key=lambda r:r['time'])
    data['u2'].sort(key=lambda r:r['time'])
    OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Wrote',OUT,'with',len(data['bus']),'bus and',len(data['u2']),'U2 departures')
    return 0

if __name__=='__main__':
    sys.exit(main())
