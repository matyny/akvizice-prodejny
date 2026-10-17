#!/usr/bin/env python3
"""
Akviziční mapa – měsíční balík prodejen z OpenStreetMap (výřez Česka z Geofabriku).

  python3 build.py filtr typy.txt > filtr.txt          výraz pro „osmium tags-filter“
  python3 build.py balik prodejny.osm.pbf typy.txt out  vytvoří out/prodejny.zip a out/meta.json

V ZIPu je pro každou dlaždici a druh prodejny jeden soubor „X_Y/klic=hodnota.json“ – seznam [id, lat, lon, {značky}].
Síť dlaždic musí sedět s aplikací (lib/geo.php: AM_LON0, AM_LAT0, AM_DLON, AM_DLAT, AM_TX_MAX, AM_TY_MAX).
Data © přispěvatelé OpenStreetMap, licence ODbL 1.0.
"""
import datetime
import hashlib
import json
import os
import re
import sys
import zipfile

import osmium

LON0, LAT0, DLON, DLAT, TX_MAX, TY_MAX = 12.0, 48.5, 0.8, 0.5, 8, 5

# značky, které aplikace z prodejny ukládá (název, adresa, kontakty, otevírací doba)
UDAJE = {
    'name', 'brand', 'operator',
    'addr:housenumber', 'addr:conscriptionnumber', 'addr:streetnumber', 'addr:street', 'addr:place', 'addr:city',
    'phone', 'contact:phone', 'mobile', 'contact:mobile', 'phone:mobile',
    'website', 'contact:website', 'email', 'contact:email', 'opening_hours',
}
HODNOTA = re.compile(r'^[a-z0-9_]+$')   # aplikace se jinou hodnotou nikdy neptá


def nacti_typy(soubor):
    """Vrací (klíče, které se berou celé, {klíč: {hodnoty}})."""
    cele, pary = set(), {}
    with open(soubor, encoding='utf-8') as f:
        for radek in f:
            r = radek.split('#', 1)[0].strip()
            if not r:
                continue
            if '=' in r:
                k, v = (x.strip() for x in r.split('=', 1))
                pary.setdefault(k, set()).add(v)
            else:
                cele.add(r)
    return cele, pary


def filtr(typy):
    cele, pary = nacti_typy(typy)
    for k in sorted(cele):
        print(f'nwr/{k}')
    for k in sorted(pary):
        if k not in cele:
            print(f'nwr/{k}=' + ','.join(sorted(pary[k])))


class Sber(osmium.SimpleHandler):
    def __init__(self, cele, pary):
        super().__init__()
        self.cele, self.pary = cele, pary
        self.klice = cele | set(pary)
        self.kose = {}        # (tx, ty, 'klic=hodnota') -> {id: [id, lat, lon, značky]}
        self.pocet = 0

    def druhy(self, tags):
        out = []
        for k in self.klice:
            v = tags.get(k)
            if v is None or not HODNOTA.match(v):
                continue
            if k == 'shop' and v == 'vacant':
                continue
            if k in self.cele or v in self.pary.get(k, ()):
                out.append(f'{k}={v}')
        return out

    def uloz(self, typ, oid, lat, lon, tags):
        druhy = self.druhy(tags)
        if not druhy:
            return
        tx, ty = int((lon - LON0) // DLON), int((lat - LAT0) // DLAT)
        if not (0 <= tx <= TX_MAX and 0 <= ty <= TY_MAX):
            return
        znacky = {k: v for k, v in tags if k in UDAJE or k in self.klice or k == 'disused:shop'}
        zaznam = [f'{typ}/{oid}', round(lat, 7), round(lon, 7), znacky]
        for d in druhy:
            self.kose.setdefault((tx, ty, d), {})[zaznam[0]] = zaznam
        self.pocet += 1

    def node(self, n):
        if n.tags and n.location.valid():
            self.uloz('node', n.id, n.location.lat, n.location.lon, n.tags)

    def way(self, w):
        if not w.tags or not self.druhy(w.tags):
            return
        body = [(nd.location.lat, nd.location.lon) for nd in w.nodes if nd.location.valid()]
        if body:   # střed obdélníku kolem prodejny – stejně jako „out center“ v Overpass
            la, lo = [p[0] for p in body], [p[1] for p in body]
            self.uloz('way', w.id, (min(la) + max(la)) / 2, (min(lo) + max(lo)) / 2, w.tags)

    def area(self, a):
        if a.from_way() or not a.tags or not self.druhy(a.tags):
            return   # plochy z cest už zpracovala way()
        la, lo = [], []
        for ring in a.outer_rings():
            for nd in ring:
                if nd.location.valid():
                    la.append(nd.lat); lo.append(nd.lon)
        if la:
            self.uloz('relation', a.orig_id(), (min(la) + max(la)) / 2, (min(lo) + max(lo)) / 2, a.tags)


def balik(pbf, typy, vystup):
    cele, pary = nacti_typy(typy)
    h = Sber(cele, pary)
    h.apply_file(pbf, locations=True)

    hl = osmium.io.Reader(pbf, osmium.osm.osm_entity_bits.NOTHING)
    stav = hl.header().get('osmosis_replication_timestamp') or hl.header().get('timestamp') or ''
    hl.close()

    os.makedirs(vystup, exist_ok=True)
    cesta = os.path.join(vystup, 'prodejny.zip')
    with zipfile.ZipFile(cesta, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for (tx, ty, d), prvky in sorted(h.kose.items()):
            z.writestr(f'{tx}_{ty}/{d}.json', json.dumps(list(prvky.values()), ensure_ascii=False, separators=(',', ':')))
    with open(cesta, 'rb') as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    meta = {
        'verze': stav or datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'vytvoreno': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'pocet': h.pocet,
        'typy': sorted(cele) + sorted(f'{k}={v}' for k in pary if k not in cele for v in pary[k]),
        'soubor': 'prodejny.zip',
        'velikost': os.path.getsize(cesta),
        'sha256': sha,
        'licence': '© přispěvatelé OpenStreetMap, ODbL 1.0',
    }
    with open(os.path.join(vystup, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"prodejen: {h.pocet}, souborů v ZIPu: {len(h.kose)}, velikost: {meta['velikost'] / 1048576:.1f} MB, data k {meta['verze']}")
    if h.pocet < 1000 and not os.environ.get('MALY_TEST'):
        sys.exit('Podezřele málo prodejen – balík se nezveřejní.')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'filtr':
        filtr(sys.argv[2])
    elif len(sys.argv) == 5 and sys.argv[1] == 'balik':
        balik(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        sys.exit(__doc__)
