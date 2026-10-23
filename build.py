#!/usr/bin/env python3
"""
Akviziční mapa – měsíční balík prodejen z OpenStreetMap (výřez Česka z Geofabriku), doplněný o Overture Maps
a o ukončené provozovny z Registru osob.

  python3 build.py filtr typy.txt > filtr.txt                    výraz pro „osmium tags-filter“
  python3 build.py balik prodejny.osm.pbf typy.txt out [ZDROJE]   vytvoří out/prodejny.zip a out/meta.json
      ZDROJE = složka z zdroje.py (overture.csv.gz, provozovny.csv.gz, ukoncene.csv.gz); co v ní chybí, se vynechá.

V ZIPu je pro každou dlaždici a druh prodejny jeden soubor „X_Y/klic=hodnota.json“ – seznam [id, lat, lon, {značky}, {zdroje}]:
  id    „node/123“, „way/…“, „relation/…“ (OpenStreetMap), nebo „ovt/<id>“ (prodejna jen z Overture Maps),
  zdroje (jen když je co říct): „o“ = jistota Overture 0–1 (prodejnu zná i Overture), „k“ = datum, kdy firma prodejny
        v tomto místě ukončila provozovnu a jinou tu nemá (prodejna nejspíš zavřela).
Prodejna z OpenStreetMap bez „o“ Overture nezná (když balík Overture obsahuje – meta.json „overture“).
Síť dlaždic musí sedět s aplikací (lib/geo.php: AM_LON0, AM_LAT0, AM_DLON, AM_DLAT, AM_TX_MAX, AM_TY_MAX).
Data © přispěvatelé OpenStreetMap (ODbL 1.0), Overture Maps Foundation (CDLA Permissive 2.0 / Apache 2.0),
Registr osob (Digitální a informační agentura), RÚIAN (ČÚZK, CC BY 4.0), RES (ČSÚ).
"""
import collections
import csv
import datetime
import gzip
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
import zipfile

import osmium

csv.field_size_limit(10**9)
LON0, LAT0, DLON, DLAT, TX_MAX, TY_MAX = 12.0, 48.5, 0.8, 0.5, 8, 5

# značky, které aplikace z prodejny ukládá (název, adresa, kontakty, otevírací doba)
UDAJE = {
    'name', 'brand', 'operator',
    'addr:housenumber', 'addr:conscriptionnumber', 'addr:streetnumber', 'addr:street', 'addr:place', 'addr:city',
    'phone', 'contact:phone', 'mobile', 'contact:mobile', 'phone:mobile',
    'website', 'contact:website', 'email', 'contact:email', 'opening_hours',
}
HODNOTA = re.compile(r'^[a-z0-9_]+$')   # aplikace se jinou hodnotou nikdy neptá
# stojany sdílených kol nejsou půjčovny, kam by šel obchodník
SDILENA_KOLA = re.compile(r'nextbike|rekola|pilsen ?bike|scoo ?bike|bolt|lime|freebike|kolonka|velonet|bike ?sharing|sdilen', re.I)

OVT_JISTOTA_NOVA = 0.5          # prodejna jen z Overture se do balíku bere od této jistoty
M_SHODA_JMENO = 120             # Overture × OSM: stejné jméno do 120 m
M_SHODA_MISTO = 25              # … nebo stejný druh do 25 m
M_KONEC = 40                    # ukončená provozovna firmy se jménem prodejny do 40 m
M_FIRMA_JINDE = 100             # … a stejná firma tu nemá jinou aktivní provozovnu do 100 m

OBECNA = set('''prodejna obchod shop store centrum studio servis spol sro s r o a as cz the and der die das pro pod nad
optika optik optic optics ocni opticke sport sports cyklo kola bike bikes outdoor velo potraviny market supermarket
restaurace restaurant hospoda pub bar kavarna cafe coffee hotel penzion pension lekarna pharmacy drogerie kadernictvi
salon beauty nails kosmetika fitness gym autoservis pneuservis elektro mobil mobily kvetiny kvetinarstvi pekarna
reznictvi vinoteka trafika praha brno ostrava plzen nove mesto namesti nam ulice'''.split())


def norm(s):
    s = unicodedata.normalize('NFKD', (s or '').lower())
    return ''.join(c for c in s if not unicodedata.combining(c))


def slova(s):
    return {w for w in re.split(r'[^a-z0-9]+', norm(s)) if len(w) >= 3 and w not in OBECNA}


def kompakt(s):
    return re.sub(r'[^a-z0-9]', '', norm(s))


def jmeno_sedi(a, b, adresa=''):
    """Sedí název prodejny se jménem (firmy, jiné prodejny)? Společné rozlišující slovo, které není kus adresy."""
    pryc = slova(adresa)
    if (slova(a) - pryc) & (slova(b) - pryc):
        return True
    ka, kb = kompakt(a), kompakt(b)
    return len(ka) >= 5 and len(kb) >= 5 and (ka in kb or kb in ka)


def vzdal(la1, lo1, la2, lo2):
    return math.hypot((lo1 - lo2) * 111320 * math.cos(math.radians(la1)), (la1 - la2) * 111320)


class Mrizka:
    """Rychlé hledání sousedů: buňky zhruba 110 × 110 m."""
    def __init__(self):
        self.g = collections.defaultdict(list)

    @staticmethod
    def klic(la, lo):
        return int(la * 1000), int(lo * 650)

    def pridej(self, la, lo, o):
        self.g[self.klic(la, lo)].append((la, lo, o))

    def okolo(self, la, lo, m):
        r = int(m / 110) + 1
        a, b = self.klic(la, lo)
        for i in range(a - r, a + r + 1):
            for j in range(b - r, b + r + 1):
                for x in self.g.get((i, j), ()):
                    d = vzdal(la, lo, x[0], x[1])
                    if d <= m:
                        yield d, x[2]


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
        self.kose = {}        # (tx, ty, 'klic=hodnota') -> {id: [id, lat, lon, značky, zdroje]}
        self.pocet = 0
        self.sdilena = 0

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
        if 'amenity=bicycle_rental' in out and (tags.get('bicycle_rental') in ('docking_station', 'dropoff_point')
                or 'network' in tags or SDILENA_KOLA.search(' '.join(tags.get(x, '') for x in ('name', 'brand', 'operator')))):
            out.remove('amenity=bicycle_rental')
            self.sdilena += 1
        return out

    def uloz(self, typ, oid, lat, lon, tags):
        druhy = self.druhy(tags)
        if not druhy:
            return
        tx, ty = int((lon - LON0) // DLON), int((lat - LAT0) // DLAT)
        if not (0 <= tx <= TX_MAX and 0 <= ty <= TY_MAX):
            return
        znacky = {k: v for k, v in tags if k in UDAJE or k in self.klice or k == 'disused:shop'}
        zaznam = [f'{typ}/{oid}', round(lat, 7), round(lon, 7), znacky, {}]
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


def nacti_mapovani(soubor, druhy_balik):
    """overture.txt → {kategorie: [(druh, +regex|None, -regex|None)]} jen pro druhy, které balík má."""
    mapa = collections.defaultdict(list)
    with open(soubor, encoding='utf-8') as f:
        for radek in f:
            r = radek.split('#', 1)[0].strip() if not radek.lstrip().startswith('#') else ''
            if not r:
                continue
            casti = r.split()
            kat, druh = casti[0].split(','), casti[1]
            ano = next((re.compile(x[1:]) for x in casti[2:] if x.startswith('+')), None)
            ne = next((re.compile(x[1:]) for x in casti[2:] if x.startswith('-')), None)
            k = druh.split('=', 1)[0]
            if druh in druhy_balik or k in druhy_balik:
                for kk in kat:
                    mapa[kk].append((druh, ano, ne))
    return mapa


def adresa_ovt(adresa, obec):
    """Overture „Fügnerova 916/1“ + „Blansko“ → značky adresy jako v OpenStreetMap."""
    z = {}
    a = (adresa or '').strip()
    m = re.match(r'^(.*?)[\s,]+((?:č\.\s*ev\.\s*)?\d+[a-zA-Z]?(?:/\d+[a-zA-Z]?)?)$', a)
    if m and m.group(1):
        z['addr:street'], z['addr:housenumber'] = m.group(1).strip(' ,'), m.group(2)
    elif a:
        z['addr:street'] = a
    if obec:
        z['addr:city'] = obec.strip()
    return z


def pridej_overture(h, slozka, mapovani):
    """Overture místa: potvrdí prodejnu z OSM (zdroje „o“), nebo přibude jako nová „ovt/…“. Vrací (potvrzeno, nových)."""
    osm = Mrizka()
    vse = {}
    for (tx, ty, d), prvky in h.kose.items():
        for z in prvky.values():
            if z[0] not in vse:
                vse[z[0]] = z
                osm.pridej(z[1], z[2], z)
    druhy_zaznamu = collections.defaultdict(set)
    for (tx, ty, d), prvky in h.kose.items():
        for z in prvky.values():
            druhy_zaznamu[z[0]].add(d)
    nove = Mrizka()
    potvrzeno, novych = 0, 0
    with gzip.open(os.path.join(slozka, 'overture.csv.gz'), 'rt', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            pravidla = mapovani.get(r['kat'] or '')
            if not pravidla or (r.get('stav') or '') in ('permanently_closed', 'closed'):
                continue
            nazev = (r['nazev'] or '').strip()
            n = norm(nazev)
            druhy = [d for d, ano, ne in pravidla if (ano is None or ano.search(n)) and (ne is None or not ne.search(n))]
            if not druhy:
                continue
            try:
                la, lo, conf = float(r['lat']), float(r['lon']), float(r['conf'] or 0)
            except ValueError:
                continue
            # prodejna z OpenStreetMap: stejné jméno do 120 m (jakýkoli druh), nebo stejný druh do 25 m
            nejlepsi = None
            for d, z in osm.okolo(la, lo, M_SHODA_JMENO):
                jm = nazev and jmeno_sedi(nazev, z[3].get('name') or z[3].get('brand') or '', r['adresa'] or '')
                if jm or (d <= M_SHODA_MISTO and druhy_zaznamu[z[0]] & set(druhy)):
                    if nejlepsi is None or d < nejlepsi[0]:
                        nejlepsi = (d, z)
            if nejlepsi:
                z = nejlepsi[1]
                if conf > z[4].get('o', -1):
                    z[4]['o'] = round(conf, 2)
                potvrzeno += 1
                continue
            if conf < OVT_JISTOTA_NOVA or not nazev:
                continue
            # stejné místo v Overture dvakrát: ponechá se to s vyšší jistotou
            dvojce = next((z for d, z in nove.okolo(la, lo, 30) if jmeno_sedi(nazev, z[3]['name'])), None)
            if dvojce:
                dvojce[4]['o'] = max(dvojce[4]['o'], round(conf, 2))
                continue
            tx, ty = int((lo - LON0) // DLON), int((la - LAT0) // DLAT)
            if not (0 <= tx <= TX_MAX and 0 <= ty <= TY_MAX):
                continue
            znacky = {'name': nazev[:190], **adresa_ovt(r['adresa'], r['obec'])}
            if r.get('web'):
                znacky['website'] = r['web'][:255]
            if r.get('tel'):
                znacky['phone'] = r['tel'][:80]
            for d in druhy:
                k, v = d.split('=', 1)
                znacky[k] = v
            zaznam = [f"ovt/{r['id']}", round(la, 7), round(lo, 7), znacky, {'o': round(conf, 2)}]
            for d in druhy:
                h.kose.setdefault((tx, ty, d), {})[zaznam[0]] = zaznam
            nove.pridej(la, lo, zaznam)
            novych += 1
    return potvrzeno, novych


def oznac_ukoncene(h, slozka):
    """Prodejna, jejíž firma (podle jména) tu v posledních letech ukončila provozovnu a jinou tu nemá → zdroje „k“ = datum."""
    akt = collections.defaultdict(list)           # ico → [(lat, lon)]
    zive = Mrizka()                               # aktivní provozovny s názvem firmy (nástupce: živnostník → s.r.o.)
    with gzip.open(os.path.join(slozka, 'provozovny.csv.gz'), 'rt', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            la, lo = float(r['lat']), float(r['lon'])
            akt[r['ico']].append((la, lo))
            if r['firma']:
                zive.pridej(la, lo, (r['firma'], r['misto']))
    konce = Mrizka()
    with gzip.open(os.path.join(slozka, 'ukoncene.csv.gz'), 'rt', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['firma']:
                konce.pridej(float(r['lat']), float(r['lon']), r)
    oznaceno, videno = 0, set()
    for prvky in h.kose.values():
        for z in prvky.values():
            if z[0] in videno:
                continue
            videno.add(z[0])
            nazev = z[3].get('name') or z[3].get('brand') or ''
            if not nazev:
                continue
            nejnovejsi = ''
            for d, p in konce.okolo(z[1], z[2], M_KONEC):
                if not jmeno_sedi(nazev, p['firma'], p['misto']):
                    continue
                if any(vzdal(z[1], z[2], la, lo) <= M_FIRMA_JINDE for la, lo in akt.get(p['ico'], ())):
                    continue                                 # firma tu dál provozovnu má (třeba se jen přestěhovala v domě)
                nejnovejsi = max(nejnovejsi, p['do'])
            # prodejnu tu dál provozuje firma se stejným jménem (převod na s.r.o., nový majitel se starým názvem)
            if nejnovejsi and any(jmeno_sedi(nazev, fi, mi) for d, (fi, mi) in zive.okolo(z[1], z[2], M_FIRMA_JINDE)):
                nejnovejsi = ''
            if nejnovejsi:
                z[4]['k'] = nejnovejsi
                oznaceno += 1
    return oznaceno


def balik(pbf, typy, vystup, zdroje=None):
    cele, pary = nacti_typy(typy)
    h = Sber(cele, pary)
    h.apply_file(pbf, locations=True)
    print(f'z OpenStreetMap: {h.pocet}, stojanů sdílených kol vynecháno: {h.sdilena}')

    hl = osmium.io.Reader(pbf, osmium.osm.osm_entity_bits.NOTHING)
    stav = hl.header().get('osmosis_replication_timestamp') or hl.header().get('timestamp') or ''
    hl.close()

    meta_navic = {}
    druhy_balik = cele | {f'{k}={v}' for k in pary for v in pary[k]}
    if zdroje and os.path.isfile(os.path.join(zdroje, 'overture.csv.gz')):
        mapovani = nacti_mapovani(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'overture.txt'), druhy_balik)
        potvrzeno, novych = pridej_overture(h, zdroje, mapovani)
        rel = open(os.path.join(zdroje, 'overture.txt')).read().strip() if os.path.isfile(os.path.join(zdroje, 'overture.txt')) else ''
        meta_navic['overture'] = rel or 'ano'
        meta_navic['overture_potvrzeno'] = potvrzeno
        meta_navic['overture_novych'] = novych
        print(f'Overture: potvrzeno {potvrzeno} prodejen z mapy, nových {novych}')
    if zdroje and all(os.path.isfile(os.path.join(zdroje, f)) for f in ('provozovny.csv.gz', 'ukoncene.csv.gz')):
        meta_navic['ukoncene'] = oznac_ukoncene(h, zdroje)
        print(f"prodejen s ukončenou provozovnou: {meta_navic['ukoncene']}")

    os.makedirs(vystup, exist_ok=True)
    cesta = os.path.join(vystup, 'prodejny.zip')
    with zipfile.ZipFile(cesta, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for (tx, ty, d), prvky in sorted(h.kose.items()):
            data = [p if p[4] else p[:4] for p in prvky.values()]
            z.writestr(f'{tx}_{ty}/{d}.json', json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    with open(cesta, 'rb') as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    pocet = len({p[0] for prvky in h.kose.values() for p in prvky.values()})
    meta = {
        'verze': stav or datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'vytvoreno': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'pocet': pocet,
        'typy': sorted(cele) + sorted(f'{k}={v}' for k in pary if k not in cele for v in pary[k]),
        'soubor': 'prodejny.zip',
        'velikost': os.path.getsize(cesta),
        'sha256': sha,
        'licence': '© přispěvatelé OpenStreetMap, ODbL 1.0' + (' · Overture Maps Foundation, CDLA Permissive 2.0 / Apache 2.0' if 'overture' in meta_navic else '')
                   + (' · Registr osob (DIA), RÚIAN (ČÚZK), RES (ČSÚ)' if 'ukoncene' in meta_navic else ''),
        **meta_navic,
    }
    with open(os.path.join(vystup, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"prodejen: {pocet}, souborů v ZIPu: {len(h.kose)}, velikost: {meta['velikost'] / 1048576:.1f} MB, data k {meta['verze']}")
    if h.pocet < 1000 and not os.environ.get('MALY_TEST'):
        sys.exit('Podezřele málo prodejen – balík se nezveřejní.')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'filtr':
        filtr(sys.argv[2])
    elif len(sys.argv) in (5, 6) and sys.argv[1] == 'balik':
        balik(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) == 6 else None)
    else:
        sys.exit(__doc__)
