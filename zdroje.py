#!/usr/bin/env python3
"""
Akviziční mapa – další zdroje k měsíčnímu balíku prodejen (běží na GitHubu, ne na hostingu aplikace).

  python3 zdroje.py overture CIL     místa z Overture Maps v Česku → CIL/overture.csv.gz
  python3 zdroje.py foursquare CIL   místa z Foursquare OS Places v Česku → CIL/foursquare.csv.gz (+ NOTICE)
                                     potřebuje proměnnou HF_TOKEN (Hugging Face, přístup k datasetu foursquare/fsq-os-places)
  python3 zdroje.py registr CIL      provozovny z Registru osob s polohou z RÚIAN a názvem firmy z RES ČSÚ
                                     → CIL/provozovny.csv.gz (aktivní) a CIL/ukoncene.csv.gz (ukončené za poslední 3 roky)
                                     a všechna adresní místa RÚIAN → CIL/adresy.csv.gz (kód, poloha, adresa) pro přichycení
                                     prodejen k adresám

Když se zdroj nepodaří stáhnout, skript skončí chybou a balík se postaví jen z OpenStreetMap (jako dřív).
Data: Overture Maps Foundation (CDLA Permissive 2.0 / Apache 2.0), Foursquare OS Places (Apache 2.0), Digitální a informační agentura (Registr osob),
ČÚZK (RÚIAN, CC BY 4.0), ČSÚ (RES) – otevřená data.
"""
import csv, datetime, gzip, io, json, os, re, subprocess, sys, time, urllib.request, zipfile

csv.field_size_limit(10**9)
UA = 'akvizice-prodejny (github.com/matyny/akvizice-prodejny)'
CR = (12.05, 48.50, 18.90, 51.10)          # západ, jih, východ, sever


def log(*a):
    print(*a, flush=True)


def stahni(url, cil):
    for pokus in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=900) as r, open(cil, 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            log('staženo', url, os.path.getsize(cil) // 1048576, 'MB')
            return
        except Exception as e:                      # síť nebo server – zkusí se znovu
            log('chyba stahování', url, e)
            time.sleep(30)
    raise SystemExit('nepodařilo se stáhnout ' + url)


def overture(cil):
    import duckdb
    vypis = subprocess.run(['aws', 's3', 'ls', '--no-sign-request', 's3://overturemaps-us-west-2/release/'],
                           capture_output=True, text=True, check=True).stdout
    rel = sorted(l.split()[-1].strip('/') for l in vypis.splitlines() if l.strip().startswith('PRE'))[-1]
    log('Overture release', rel)
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    src = f"read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*', hive_partitioning=1)"
    w, s, e, n = CR
    q = f"""SELECT id, names.primary AS nazev, round(confidence, 3) AS conf, round(bbox.xmin, 6) AS lon, round(bbox.ymin, 6) AS lat,
              taxonomy.primary AS kat, operating_status AS stav, addresses[1].freeform AS adresa, addresses[1].locality AS obec,
              websites[1] AS web, phones[1] AS tel
            FROM {src} WHERE bbox.xmin BETWEEN {w} AND {e} AND bbox.ymin BETWEEN {s} AND {n}
              AND (addresses IS NULL OR len(addresses) = 0 OR addresses[1].country = 'CZ')"""
    con.execute(f"COPY ({q}) TO '{cil}/overture.csv.gz' (HEADER, COMPRESSION gzip)")
    pocet = con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{cil}/overture.csv.gz')").fetchone()[0]
    with open(f'{cil}/overture.txt', 'w') as f:
        f.write(rel)
    log('Overture míst', pocet)
    if pocet < 100000:
        raise SystemExit('podezřele málo míst z Overture')


FSQ = 'foursquare/fsq-os-places'


def foursquare(cil):
    """Foursquare OS Places (zdarma, Apache 2.0) – jen Česko a jen to, co je potřeba k poznání zavřených míst."""
    import duckdb
    token = os.environ.get('HF_TOKEN', '').strip()
    if not token:
        raise SystemExit('chybí HF_TOKEN (tajemství repozitáře) – Foursquare se vynechá')
    if not re.match(r'^[A-Za-z0-9_\-]+$', token):
        raise SystemExit('HF_TOKEN má nečekaný tvar')
    hl = {'Authorization': f'Bearer {token}', 'User-Agent': UA}
    with urllib.request.urlopen(urllib.request.Request(f'https://huggingface.co/api/datasets/{FSQ}/tree/main/release', headers=hl), timeout=60) as r:
        polozky = json.load(r)
    rel = sorted(x['path'].rsplit('/', 1)[-1] for x in polozky if x.get('type') == 'directory' and re.search(r'dt=\d{4}-\d{2}-\d{2}$', x['path']))[-1]
    log('Foursquare release', rel)
    # licence Apache 2.0: k šířeným datům patří jejich NOTICE
    try:
        with urllib.request.urlopen(urllib.request.Request(f'https://huggingface.co/datasets/{FSQ}/resolve/main/NOTICE.txt', headers=hl), timeout=60) as r, \
                open(f'{cil}/foursquare-NOTICE.txt', 'wb') as f:
            f.write(r.read())
    except Exception as e:
        log('NOTICE se nepodařilo stáhnout', e)
    con = duckdb.connect()
    con.execute('INSTALL httpfs; LOAD httpfs;')
    con.execute(f"CREATE SECRET fsq (TYPE HUGGINGFACE, TOKEN '{token}')")
    src = f"read_parquet('hf://datasets/{FSQ}/release/{rel}/places/parquet/*.parquet')"
    w, s, e, n = CR
    sloupce = {r[0] for r in con.execute(f'DESCRIBE SELECT * FROM {src}').fetchall()}
    for nutny in ('fsq_place_id', 'name', 'latitude', 'longitude', 'country', 'date_refreshed', 'date_closed'):
        if nutny not in sloupce:
            raise SystemExit('data Foursquare mají jiný tvar, chybí ' + nutny)
    vlajky = "array_to_string(unresolved_flags, ' ')" if 'unresolved_flags' in sloupce else "''"
    adresa = 'address' if 'address' in sloupce else "''"
    kat = "fsq_category_labels[1]" if 'fsq_category_labels' in sloupce else "''"
    q = f"""SELECT fsq_place_id AS id, name AS nazev, round(latitude, 6) AS lat, round(longitude, 6) AS lon,
              CAST(date_refreshed AS VARCHAR) AS obnoveno, CAST(date_closed AS VARCHAR) AS zavreno, {vlajky} AS vlajky, {adresa} AS adresa, {kat} AS kat
            FROM {src} WHERE country = 'CZ' AND latitude BETWEEN {s} AND {n} AND longitude BETWEEN {w} AND {e} AND name IS NOT NULL"""
    # nejdřív do dočasného souboru – nedokončené stažení nesmí zůstat jako platný zdroj
    tmp = f'{cil}/foursquare.tmp.csv.gz'
    con.execute(f"COPY ({q}) TO '{tmp}' (HEADER, COMPRESSION gzip)")
    pocet = con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{tmp}')").fetchone()[0]
    log('Foursquare míst', pocet)
    if pocet < 50000:
        os.remove(tmp)
        raise SystemExit('podezřele málo míst z Foursquare')
    os.replace(tmp, f'{cil}/foursquare.csv.gz')
    with open(f'{cil}/foursquare.txt', 'w') as f:
        f.write(rel)


def adresa_text(c):
    """Adresa z řádku RÚIAN ve stejném tvaru jako v aplikaci (lib/provozovny.php adrText):
    „Husova třída 97/12a, Dolejší Předměstí, 34401 Domažlice“."""
    t = lambda i: (c[i] if i < len(c) else '').strip()
    obec, cast, ulice, typ, cdom, cor, znak, psc = t(2), t(8), t(10), t(11), t(12), t(13), t(14), t(15)
    cislo = ('č. ev. ' if typ.startswith('č.ev') else '') + cdom + ('/' + cor + znak if cor else '')
    casti = [((ulice or cast or obec) + ' ' + cislo).strip()]
    if ulice and cast and cast != obec:
        casti.append(cast)
    casti.append((psc + ' ' + obec).strip())
    return ', '.join(casti)


def registr(cil):
    from pyproj import Transformer
    tr = Transformer.from_crs('EPSG:5514', 'EPSG:4326', always_xy=True)
    dnes = datetime.date.today().isoformat()
    od_ukoncenych = (datetime.date.today() - datetime.timedelta(days=3 * 365)).isoformat()

    stahni('https://opendata.csu.gov.cz/soubory/od/od_org03/res_data.csv', 'res.csv')
    firmy = {}
    with open('res.csv', encoding='utf-8-sig', errors='replace', newline='') as f:
        rd = csv.reader(f)
        c = {k.strip().upper(): i for i, k in enumerate(next(rd))}
        for r in rd:
            try:
                firmy[r[c['ICO']].strip().zfill(8)] = (r[c['FIRMA']].strip(), r[c['DDATZAN']].strip())
            except (IndexError, KeyError):
                pass
    os.remove('res.csv')
    log('firem', len(firmy))

    stahni('https://www.szrcr.cz/images/dokumenty/ROS/Otevrena%20data/ros02_data.csv', 'ros.csv')
    akt, ukon = [], []
    with open('ros.csv', encoding='utf-8-sig', errors='replace', newline='') as f:
        rd = csv.reader(f)
        c = {k.strip().upper(): i for i, k in enumerate(next(rd))}
        for nutny in ('ICP', 'ICO', 'PKODADM', 'DATUKON'):
            if nutny not in c:
                raise SystemExit('soubor provozoven má jiný tvar, chybí ' + nutny)
        for r in rd:
            try:
                ico = r[c['ICO']].strip().zfill(8)
                kod = int(r[c['PKODADM']] or 0)
            except (IndexError, ValueError):
                continue
            if kod <= 0:
                continue
            konec = r[c['DATUKON']].strip()[:10]
            if konec and konec <= dnes:
                if konec >= od_ukoncenych:
                    ukon.append((ico, kod, konec))
            else:
                akt.append((ico, kod))
    os.remove('ros.csv')
    log('provozoven aktivních', len(akt), 'ukončených', len(ukon))

    kody = {x[1] for x in akt} | {x[1] for x in ukon}
    d = datetime.date.today().replace(day=1) - datetime.timedelta(days=1)
    for _ in range(3):
        try:
            stahni(f'https://vdp.cuzk.gov.cz/vymenny_format/csv/{d:%Y%m%d}_OB_ADR_csv.zip', 'adr.zip')
            break
        except SystemExit:
            d = d.replace(day=1) - datetime.timedelta(days=1)
    else:
        raise SystemExit('adresy RÚIAN se nepodařilo stáhnout')
    body = {}
    vsech = 0
    # všechna adresní místa jdou i do adresy.csv.gz (přichycení prodejen k adrese); do dočasného souboru, ať nedokončený nezůstane
    with zipfile.ZipFile('adr.zip') as z, gzip.open(f'{cil}/adresy.tmp.csv.gz', 'wt', encoding='utf-8', newline='') as fa:
        wa = csv.writer(fa)
        wa.writerow(['kod', 'lat', 'lon', 'adresa'])
        for jm in z.namelist():
            for line in io.TextIOWrapper(z.open(jm), encoding='cp1250', errors='replace'):
                k = line.split(';', 1)[0]
                if not k.isdigit():
                    continue
                col = line.rstrip('\r\n').split(';')
                if len(col) < 18:
                    continue
                try:
                    y, x = float(col[16]), float(col[17])
                except ValueError:
                    continue
                if y < 1000 or x < 1000:
                    continue
                lon, lat = tr.transform(-y, -x)
                la, lo = round(lat, 6), round(lon, 6)
                wa.writerow([k, la, lo, adresa_text(col)])
                vsech += 1
                if int(k) in kody:
                    body[int(k)] = (la, lo, ' '.join(filter(None, [col[10] or col[8] or col[2], col[2]])))
    os.remove('adr.zip')
    if vsech > 1000000:
        os.replace(f'{cil}/adresy.tmp.csv.gz', f'{cil}/adresy.csv.gz')
    else:
        os.remove(f'{cil}/adresy.tmp.csv.gz')
    log('adresních bodů s provozovnou', len(body), 'všech adres', vsech)

    for jm, rows in (('provozovny', akt), ('ukoncene', ukon)):
        n = 0
        with gzip.open(f'{cil}/{jm}.csv.gz', 'wt', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(['ico', 'lat', 'lon', 'misto', 'firma', 'zanik'] + (['do'] if jm == 'ukoncene' else []))
            for x in rows:
                b = body.get(x[1])
                if not b:
                    continue
                fi = firmy.get(x[0], ('', ''))
                w.writerow([x[0], b[0], b[1], b[2], fi[0], fi[1]] + ([x[2]] if jm == 'ukoncene' else []))
                n += 1
        log(jm, n)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] not in ('overture', 'foursquare', 'registr'):
        sys.exit(__doc__)
    os.makedirs(sys.argv[2], exist_ok=True)
    {'overture': overture, 'foursquare': foursquare, 'registr': registr}[sys.argv[1]](sys.argv[2])
