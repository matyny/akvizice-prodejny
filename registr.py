#!/usr/bin/env python3
"""
Akviziční mapa – hotový registr firem pro aplikaci (běží na GitHubu, ne na hostingu aplikace).

Aplikace si dřív registr stavěla sama na hostingu: stáhla stovky MB (RES ČSÚ, Registr osob, adresy RÚIAN, kontroly ČOI),
rozebrala je a uložila do vlastního souboru SQLite. Teď ho jednou měsíčně postaví tento skript – se stejnými tabulkami
a stejnými pravidly jako aplikace (lib/res.php, lib/provozovny.php) – a aplikace si stáhne jen hotový soubor.

  python3 registr.py postav STAZENE VYSTUP
        stáhne zdroje, které ve složce STAZENE chybí, postaví registr, zkontroluje ho a zabalí do VYSTUP:
        registr-VERZE.bin – soubor registru po kusech 16 MiB, každý zkomprimovaný (zlib) a zašifrovaný (AES-256-GCM)
        registr.json – popis kusů a počty (nic tajného); potřebuje proměnnou BALIK_KLIC (tajemství repozitáře)
  python3 registr.py soubory RES ROS ADR COI VYSTUP
        postaví VYSTUP/registr.sqlite z místních souborů, bez stahování a šifrování (zkoušky; COI „-“ = bez ČOI)

Proč šifrovat: v registru jsou i jména živnostníků (osobní údaje). Repozitář je veřejný – soubor smí přečíst jen aplikace,
která má stejný klíč v config.php ('balik_klic').
Když se změní tabulky nebo pravidla stavby registru v aplikaci, musí se stejně změnit i tady a zvýšit REG_FORMAT
(v aplikaci AM_REG_FORMAT) – aplikace jiný formát nepřijme a postaví si registr sama jako dřív.
Data: RES (ČSÚ), Registr osob (Digitální a informační agentura), RÚIAN (ČÚZK, CC BY 4.0), kontroly ČOI – otevřená data.
"""
import base64, collections, csv, datetime, hashlib, json, math, os, re, sqlite3, sys, time, zipfile, zlib
from zoneinfo import ZoneInfo

csv.field_size_limit(10**9)
ZONA = ZoneInfo('Europe/Prague')


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------------------------------------------------
# Konstanty převzaté beze změny z aplikace (lib/res.php, lib/provozovny.php)
# --------------------------------------------------------------------------------------------------------------------

AM_RES_PO = [
    111, 112, 113, 121, 205, 301, 421, 422, 423, 424, 425, 932, 933]
AM_RES_FO = [
    101, 102, 105, 106, 107]
AM_RES_NACE_FO = [
    '01', '10', '11', '14', '15', '31', '32', '45', '46', '47', '55', '56', '58', '75', '77', '79', '86', '93', '95', '96']
AM_SLOVA_PRAZDNA = [
    'namesti', 'nadrazi', 'ulice', 'trida', 'moje', 'muj', 'nase', 'nas', 'vase', 'vas', 'cs', 'na', 've', 'po', 'za', 'do', 'od', 'ze', 'ke',
    'se', 'cr', 'sk', 'eu', 'dr', 'sro', 'spol', 'as', 'vos', 'ks', 'ops', 'druzstvo', 'cz', 'czech', 'ceska', 'cesky', 'ceske',
    'republika', 'group', 'holding', 'company', 'firma', 'republic', 'prague', 'bohemia', 'moravia', 'europe', 'international', 'ing',
    'mgr', 'mudr', 'mvdr', 'bc', 'phd', 'csc', 'judr', 'rndr', 'phdr', 'paeddr', 'dis', 'mba', 'pharmdr', 'the', 'and', 'von', 'pod', 'nad',
    'pro', 'pri', 'odstepny', 'zavod', 'likvidaci']
AM_SLOVA_OBECNA = [
    'optika', 'optik', 'ocni', 'optometrie', 'lekarna', 'sport', 'sporty', 'cyklo', 'kola', 'servis', 'prodejna', 'obchod', 'prodej',
    'potraviny', 'smisene', 'zbozi', 'vecerka', 'market', 'shop', 'store', 'centrum', 'center', 'studio', 'salon', 'kadernictvi',
    'kosmetika', 'bazar', 'outlet', 'kvetiny', 'kvetinarstvi', 'zahradnictvi', 'pekarna', 'pekarstvi', 'reznictvi', 'uzeniny', 'maso',
    'cukrarna', 'kavarna', 'restaurace', 'hospoda', 'hostinec', 'bistro', 'bar', 'pizzeria', 'hotel', 'penzion', 'autoservis', 'pneuservis',
    'auto', 'moto', 'elektro', 'drogerie', 'papirnictvi', 'knihkupectvi', 'knihy', 'hracky', 'obuv', 'textil', 'moda', 'butik',
    'zlatnictvi', 'klenoty', 'hodinarstvi', 'trafika', 'tabak', 'vinoteka', 'vino', 'napoje', 'zelezarstvi', 'nabytek', 'chovatelske',
    'potreby', 'zdrava', 'vyziva', 'bio', 'farma', 'farmarsky', 'outdoor', 'ski', 'rybarske', 'fitness', 'petrol', 'oil', 'pumpa', 'benzin',
    'tank', 'lpg', 'cng', 'gas', 'motor', 'motors', 'pneu', 'privesy', 'autodily', 'dily', 'autosalon', 'autobazar', 'car', 'cars',
    'professional', 'cerpaci', 'stanice', 'skoda', 'volkswagen', 'audi', 'seat', 'bmw', 'mercedes', 'benz', 'ford', 'opel', 'peugeot',
    'citroen', 'renault', 'dacia', 'toyota', 'lexus', 'honda', 'mazda', 'nissan', 'hyundai', 'kia', 'suzuki', 'subaru', 'mitsubishi',
    'volvo', 'fiat', 'iveco', 'jeep', 'tesla', 'mini', 'porsche', 'man', 'daf', 'scania', 'avia', 'tatra', 'yamaha', 'kawasaki',
    'cykloservis', 'cyklosport', 'autoopravna', 'lahudky', 'ovoce', 'zelenina', 'konzum', 'kolonial', 'jednota', 'mini', 'super', 'expres',
    'express', 'levne', 'asia', 'asian', 'food', 'foods', 'drinks', 'pecivo', 'uzenarstvi', 'cukrarstvi', 'racing', 'team', 'club', 'klub',
    'eshop', 'obchudek', 'kramek', 'palivo', 'paliva', 'nemocnice', 'poliklinika', 'klinika', 'zdravotni', 'zdravotnicke', 'stredisko',
    'ambulance', 'dum', 'zahrada', 'domaci', 'darky', 'darkove', 'galanterie', 'koberce', 'barvy', 'laky', 'stavebniny', 'ordinace',
    'veterina', 'veterinarni', 'zubni', 'praktik']
AM_NACE_BEZ_ZIVNOSTI = [
    '4773', '86', '75']
AM_CP1250 = {
    0x80: '€', 0x82: '‚', 0x84: '„', 0x85: '…', 0x86: '†', 0x87: '‡', 0x89: '‰', 0x8A: 'Š', 0x8B: '‹', 0x8C: 'Ś', 0x8D: 'Ť', 0x8E: 'Ž', 0x8F:
    'Ź', 0x91: '‘', 0x92: '’', 0x93: '“', 0x94: '”', 0x95: '•', 0x96: '–', 0x97: '—', 0x99: '™', 0x9A: 'š', 0x9B: '›', 0x9C: 'ś', 0x9D: 'ť',
    0x9E: 'ž', 0x9F: 'ź', 0xA0: '\xa0', 0xA1: 'ˇ', 0xA2: '˘', 0xA3: 'Ł', 0xA4: '¤', 0xA5: 'Ą', 0xA6: '¦', 0xA7: '§', 0xA8: '¨', 0xA9: '©',
    0xAA: 'Ş', 0xAB: '«', 0xAC: '¬', 0xAD: '\xad', 0xAE: '®', 0xAF: 'Ż', 0xB0: '°', 0xB1: '±', 0xB2: '˛', 0xB3: 'ł', 0xB4: '´', 0xB5: 'µ',
    0xB6: '¶', 0xB7: '·', 0xB8: '¸', 0xB9: 'ą', 0xBA: 'ş', 0xBB: '»', 0xBC: 'Ľ', 0xBD: '˝', 0xBE: 'ľ', 0xBF: 'ż', 0xC0: 'Ŕ', 0xC1: 'Á',
    0xC2: 'Â', 0xC3: 'Ă', 0xC4: 'Ä', 0xC5: 'Ĺ', 0xC6: 'Ć', 0xC7: 'Ç', 0xC8: 'Č', 0xC9: 'É', 0xCA: 'Ę', 0xCB: 'Ë', 0xCC: 'Ě', 0xCD: 'Í',
    0xCE: 'Î', 0xCF: 'Ď', 0xD0: 'Đ', 0xD1: 'Ń', 0xD2: 'Ň', 0xD3: 'Ó', 0xD4: 'Ô', 0xD5: 'Ő', 0xD6: 'Ö', 0xD7: '×', 0xD8: 'Ř', 0xD9: 'Ů',
    0xDA: 'Ú', 0xDB: 'Ű', 0xDC: 'Ü', 0xDD: 'Ý', 0xDE: 'Ţ', 0xDF: 'ß', 0xE0: 'ŕ', 0xE1: 'á', 0xE2: 'â', 0xE3: 'ă', 0xE4: 'ä', 0xE5: 'ĺ',
    0xE6: 'ć', 0xE7: 'ç', 0xE8: 'č', 0xE9: 'é', 0xEA: 'ę', 0xEB: 'ë', 0xEC: 'ě', 0xED: 'í', 0xEE: 'î', 0xEF: 'ď', 0xF0: 'đ', 0xF1: 'ń',
    0xF2: 'ň', 0xF3: 'ó', 0xF4: 'ô', 0xF5: 'ő', 0xF6: 'ö', 0xF7: '÷', 0xF8: 'ř', 0xF9: 'ů', 0xFA: 'ú', 0xFB: 'ű', 0xFC: 'ü', 0xFD: 'ý',
    0xFE: 'ţ', 0xFF: '˙'}


# --------------------------------------------------------------------------------------------------------------------
# Pomocné funkce chovající se přesně jako v PHP aplikace (lib/boot.php, lib/res.php, lib/provozovny.php)
# --------------------------------------------------------------------------------------------------------------------

PRAZDNA = set(AM_SLOVA_PRAZDNA)
OBECNA = set(AM_SLOVA_OBECNA)
RES_PO = set(AM_RES_PO)
RES_FO = set(AM_RES_FO)
RES_NACE_FO = set(AM_RES_NACE_FO)
NORM_MAP = str.maketrans({'á': 'a', 'č': 'c', 'ď': 'd', 'é': 'e', 'ě': 'e', 'í': 'i', 'ň': 'n', 'ó': 'o', 'ř': 'r', 'š': 's', 'ť': 't',
                          'ú': 'u', 'ů': 'u', 'ý': 'y', 'ž': 'z', 'ä': 'a', 'ö': 'o', 'ü': 'u', 'ľ': 'l', 'ĺ': 'l', 'ŕ': 'r', 'ô': 'o'})
PHP_TRIM = ' \t\n\r\0\x0b'
RE_MEZERY = re.compile(r'\s+')
RE_FORMA = re.compile(r'\b(s\s*\.?\s*r\s*\.?\s*o|a\s*\.\s*s|v\s*\.\s*o\s*\.\s*s|k\s*\.\s*s|spol\s*\.\s*s\s*r\s*\.?\s*o)\b\.?')
RE_SLOVA = re.compile(r'[^a-z0-9]+')
RE_RIDICI = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F]')
RE_NECISLICE = re.compile(r'\D', re.ASCII)
RE_INT = re.compile(r'^[ \t\n\r\v\f]*[+-]?\d+')
RE_FLOAT = re.compile(r'^[ \t\n\r\v\f]*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?')


def php_int(s):
    """(int)"…" v PHP: číslo na začátku textu, jinak 0."""
    m = RE_INT.match(s or '')
    return int(m.group(0)) if m else 0


def php_float(s):
    m = RE_FLOAT.match(s or '')
    return float(m.group(0)) if m else 0.0


def php_round(x, mista):
    """round() v PHP: polovina od nuly."""
    f = 10.0 ** mista
    t = x * f
    return (math.floor(t + 0.5) if t >= 0 else math.ceil(t - 0.5)) / f


def norm(s):
    """norm() z lib/boot.php: malá písmena bez diakritiky, jedna mezera."""
    return RE_MEZERY.sub(' ', s.lower().translate(NORM_MAP)).strip(PHP_TRIM)


def platne(s):
    """Neplatné bajty (UTF-8) → náhradní znak, ať jde text uložit."""
    return s.encode('utf-8', 'surrogateescape').decode('utf-8', 'replace') if any('\udc80' <= ch <= '\udcff' for ch in s) else s


def txt(s, maxi=190):
    """txt() z lib/boot.php."""
    s = (s or '').strip(PHP_TRIM)
    if any('\udc80' <= ch <= '\udcff' for ch in s):
        return ''                               # neplatné UTF-8: preg_replace v PHP vrátí null → prázdný text
    return RE_RIDICI.sub('', s)[:maxi]


def ico_norm(v):
    """icoNorm() z lib/boot.php: 8 číslic s kontrolní číslicí, jinak None."""
    s = RE_NECISLICE.sub('', v or '')
    if s == '' or len(s) > 8:
        return None
    s = s.zfill(8)
    soucet = sum(int(s[i]) * (8 - i) for i in range(7))
    a = soucet % 11
    c = 1 if a == 0 else (0 if a == 1 else 11 - a)
    return s if c == int(s[7]) else None


def firma_slova(nazev):
    """firmaSlova() z lib/res.php → (rozlišující slova, obecná slova), každé nejvýš 6."""
    n = RE_FORMA.sub(' ', norm(nazev))
    d, g = {}, {}
    slova, pismena = [], ''
    for w in RE_SLOVA.split(n):
        if len(w) == 1 and w.isascii() and w.isalpha():
            pismena += w
            continue
        if len(pismena) >= 2:
            slova.append((pismena, True))
        pismena = ''
        slova.append((w, False))
    if len(pismena) >= 2:
        slova.append((pismena, True))
    for w, zkratka in slova:
        if w == '' or w in PRAZDNA:
            continue
        if zkratka:
            d[w] = True
            continue
        if len(w) < 2:
            continue
        if w in OBECNA:
            g[w] = True
        else:
            d[w] = True
    return list(d)[:6], list(g)[:6]


def nace_bez_zivnosti(nace):
    return any(nace.startswith(z) for z in AM_NACE_BEZ_ZIVNOSTI)


def cp1250(b):
    """Bajty ve Windows-1250 → text, stejnou tabulkou jako aplikace (AM_CP1250)."""
    return ''.join(chr(x) if x < 0x80 else AM_CP1250.get(x, '�') for x in b)


def jtsk_na_wgs(y, x):
    """jtskNaWgs() z lib/provozovny.php – stejný výpočet, ať polohy sedí s aplikací."""
    e = 0.081696831215303; n = 0.97992470462083; roK = 12310230.12797036
    sinUQ = 0.863499969506341; cosUQ = 0.504348889819882; sinVQ = 0.420215144586493; cosVQ = 0.907424504992097
    alfa = 1.000597498371542; k = 1.003419163966575
    ro = math.sqrt(x * x + y * y)
    eps = 2 * math.atan(y / (ro + x))
    d = eps / n
    s = 2 * math.atan(math.exp(1 / n * math.log(roK / ro))) - math.pi / 2
    sinS = math.sin(s); cosS = math.cos(s)
    sinU = sinUQ * sinS - cosUQ * cosS * math.cos(d)
    cosU = math.sqrt(1 - sinU * sinU)
    sinDV = math.sin(d) * cosS / cosU; cosDV = math.sqrt(1 - sinDV * sinDV)
    sinV = sinVQ * cosDV - cosVQ * sinDV; cosV = cosVQ * cosDV + sinVQ * sinDV
    l = 2 * math.atan(sinV / (1 + cosV)) / alfa
    t = math.exp(2 / alfa * math.log((1 + sinU) / cosU / k))
    pom = (t - 1) / (t + 1)
    for _ in range(30):
        sinB = pom
        pom = t * math.exp(e * math.log((1 + e * sinB) / (1 - e * sinB)))
        pom = (pom - 1) / (pom + 1)
        if abs(pom - sinB) < 1e-15:
            break
    b = math.atan(pom / math.sqrt(1 - pom * pom))
    a = 6377397.15508; f1 = 299.152812853; e2 = 1 - (1 - 1 / f1) ** 2; h = 245
    rn = a / math.sqrt(1 - e2 * math.sin(b) ** 2)
    X = (rn + h) * math.cos(b) * math.cos(l); Y = (rn + h) * math.cos(b) * math.sin(l); Z = ((1 - e2) * rn + h) * math.sin(b)
    dx = 570.69; dy = 85.69; dz = 462.84
    wz = -5.2611 / 3600 * math.pi / 180; wy = -1.58676 / 3600 * math.pi / 180; wx = -4.99821 / 3600 * math.pi / 180; m = 3.543e-6
    xn = dx + (1 + m) * (X + wz * Y - wy * Z)
    yn = dy + (1 + m) * (-wz * X + Y + wx * Z)
    zn = dz + (1 + m) * (wy * X - wx * Y + Z)
    a = 6378137.0; f1 = 298.257223563; ab = f1 / (f1 - 1); e2 = 1 - (1 - 1 / f1) ** 2
    p = math.sqrt(xn * xn + yn * yn)
    th = math.atan(zn * ab / p); st = math.sin(th); ct = math.cos(th)
    tt = (zn + e2 * ab * a * st ** 3) / (p - e2 * a * ct ** 3)
    lat = math.atan(tt); lon = 2 * math.atan(yn / (p + xn))
    return (lat / math.pi) * 180.0, (lon / math.pi) * 180.0


def adr_text(c):
    """adrText() z lib/provozovny.php: „Husova třída 97/12a, Dolejší Předměstí, 34401 Domažlice“."""
    t = lambda i: (c[i] if i < len(c) else '').strip(PHP_TRIM)
    obec, cast, ulice, typ, cdom, cor, znak, psc = t(2), t(8), t(10), t(11), t(12), t(13), t(14), t(15)
    cislo = ('č. ev. ' if typ.startswith('č.ev') else '') + cdom + ('/' + cor + znak if cor != '' else '')
    casti = [((ulice if ulice != '' else (cast if cast != '' else obec)) + ' ' + cislo).strip(PHP_TRIM)]
    if ulice != '' and cast != '' and cast != obec:
        casti.append(cast)
    casti.append((psc + ' ' + obec).strip(PHP_TRIM))
    return ', '.join(casti)


RE_COI_ADR = re.compile(r'^(.*\S)\s+(č\. ev\. )?(\d+)(?:/(\d+[a-zA-Z]?))?$')
RE_PSC = re.compile(r'^(\d{5}) ')
RE_NEALNUM = re.compile(r'[^a-z0-9]+')
RE_NEALNUM2 = re.compile(r'[^0-9a-zA-Z]')


def coi_klice(psc, ulice, cp, co):
    """coiKlice() z lib/provozovny.php."""
    psc = RE_NECISLICE.sub('', psc)
    if len(psc) != 5:
        return []
    k = []
    u = RE_NEALNUM.sub('', norm(ulice))
    cp = RE_NECISLICE.sub('', cp).lstrip('0')
    co = RE_NEALNUM2.sub('', co).lstrip('0').lower()
    if u != '' and co != '':
        k.append('o|' + psc + '|' + u + '|' + co)
    if u != '' and cp != '':
        k.append('u|' + psc + '|' + u + '|' + cp)
    if cp != '':
        k.append('p|' + psc + '|' + cp)
    return k


def coi_klice_adresy(adresa):
    """coiKliceAdresy() z lib/provozovny.php."""
    casti = adresa.split(', ')
    if len(casti) < 2:
        return []
    p = RE_PSC.match(casti[-1])
    if not p:
        return []
    m = RE_COI_ADR.match(casti[0])
    if not m or (m.group(2) or '') != '':
        return []
    return coi_klice(p.group(1), m.group(1), m.group(3), m.group(4) or '')


def php_csv(radek):
    """str_getcsv($radek, ',', '"', '') – jeden záznam."""
    try:
        return next(csv.reader([radek], strict=False))
    except StopIteration:
        return ['']
    except csv.Error:
        return radek.split(',')


def php_upper(s):
    """strtoupper() v PHP 8: jen písmena a–z."""
    return ''.join(ch.upper() if 'a' <= ch <= 'z' else ch for ch in s)


def hlavicka(r, s_norm=False):
    """Názvy sloupců jako v aplikaci (array_flip – při dvou stejných názvech platí poslední)."""
    out = {}
    for i, x in enumerate(r):
        x = x.strip(' \t"\ufeff')
        out[php_upper(norm(x) if s_norm else x)] = i
    return out


def radky_souboru(cesta):
    """Řádky souboru jako bajty, bez koncového \\n (jako explode("\\n") v aplikaci)."""
    with open(cesta, 'rb') as f:
        for b in f:
            yield b[:-1] if b.endswith(b'\n') else b


def text_utf8(b):
    return b.decode('utf-8', 'surrogateescape')


# --------------------------------------------------------------------------------------------------------------------
# Stavba souboru registru – stejné tabulky, pravidla a pořadí jako aplikace (provozovny → adresy → kontroly ČOI → firmy)
# --------------------------------------------------------------------------------------------------------------------

TABULKY = [
    """CREATE TABLE IF NOT EXISTS main.am_subjekty (
            ico TEXT NOT NULL PRIMARY KEY,
            nazev TEXT NOT NULL,
            forma INTEGER NOT NULL DEFAULT 0,
            katpo INTEGER NOT NULL DEFAULT 0,
            nace TEXT NOT NULL DEFAULT '',
            okres TEXT NOT NULL DEFAULT '',
            obec TEXT NOT NULL DEFAULT '',
            ulice TEXT NOT NULL DEFAULT '',
            cdom TEXT NOT NULL DEFAULT '',
            cor TEXT NOT NULL DEFAULT '',
            vznik TEXT NOT NULL DEFAULT '',
            slov INTEGER NOT NULL DEFAULT 0,
            obecna TEXT NOT NULL DEFAULT '',
            davka INTEGER NOT NULL DEFAULT 0
        ) WITHOUT ROWID""",
    """CREATE TABLE IF NOT EXISTS main.am_subjekty_slova (
            slovo TEXT NOT NULL,
            okres TEXT NOT NULL,
            ico TEXT NOT NULL,
            PRIMARY KEY (slovo, okres, ico)
        ) WITHOUT ROWID""",
    """CREATE TABLE IF NOT EXISTS main.am_provozovny (
            icp INTEGER NOT NULL PRIMARY KEY,
            ico TEXT NOT NULL,
            kod INTEGER NOT NULL,
            od TEXT NOT NULL DEFAULT ''
        ) WITHOUT ROWID""",
    "CREATE INDEX IF NOT EXISTS main.i_prov_ico ON am_provozovny (ico)",
    "CREATE INDEX IF NOT EXISTS main.i_prov_kod ON am_provozovny (kod)",
    """CREATE TABLE IF NOT EXISTS main.am_body (
            kod INTEGER NOT NULL PRIMARY KEY,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            adresa TEXT NOT NULL DEFAULT ''
        )""",
    "CREATE INDEX IF NOT EXISTS main.i_body_poloha ON am_body (lat, lon)",
    """CREATE TABLE IF NOT EXISTS main.am_coi (
            kod INTEGER NOT NULL,
            ico TEXT NOT NULL DEFAULT '',
            datum TEXT NOT NULL,
            pocet INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (kod, ico)
        ) WITHOUT ROWID""",
    "CREATE INDEX IF NOT EXISTS main.i_coi_ico ON am_coi (ico)",
]
# Otisk podoby souboru: aplikace přijme jen balík se stejným číslem (lib/res.php AM_REG_FORMAT).
# Zvýšit, když se změní tabulky nebo pravidla výše (a stejně tak v aplikaci).
REG_FORMAT = 1
REG_VZNIK_DNI = 400
COI_LET = 3


def provozovny(db, cesta, dnes):
    """provCsvKrok(): aktivní provozovny s číslem a IČO (i bez adresního místa – kód 0)."""
    sloupce = None
    ins = 'INSERT OR IGNORE INTO am_provozovny (icp, ico, kod, od) VALUES (?, ?, ?, ?)'
    davka = []
    for b in radky_souboru(cesta):
        line = text_utf8(b).rstrip('\r')
        if line == '':
            continue
        r = php_csv(line)
        if sloupce is None:
            sloupce = hlavicka(r)
            for nutny in ('ICP', 'ICO', 'DATUKON', 'PKODADM'):
                if nutny not in sloupce:
                    raise SystemExit('soubor provozoven má jiný tvar, chybí sloupec ' + nutny)
            continue
        g = lambda k: r[sloupce[k]] if sloupce[k] < len(r) else ''
        konec = g('DATUKON').strip(PHP_TRIM)
        if konec != '' and konec <= dnes:
            continue
        kod = php_int(g('PKODADM'))
        icp = int(RE_NECISLICE.sub('', g('ICP')) or 0)
        ico = ico_norm(g('ICO'))
        if icp <= 0 or ico is None:
            continue
        od = platne(g('DATZAH').strip(PHP_TRIM)[:10]) if 'DATZAH' in sloupce else ''
        davka.append((icp, ico, max(0, kod), od))
        if len(davka) >= 50000:
            db.executemany(ins, davka); davka = []
    db.executemany(ins, davka)
    n = db.execute('SELECT COUNT(*) FROM am_provozovny').fetchone()[0]
    if n == 0:
        raise SystemExit('v souboru provozoven nebyla žádná aktivní provozovna')
    return n


def adresy(db, cesta):
    """adrKrok(): adresní místa RÚIAN, na kterých je nějaká provozovna – poloha a adresa textem."""
    kody = {r[0] for r in db.execute('SELECT DISTINCT kod FROM am_provozovny WHERE kod > 0')}
    ins = 'INSERT OR IGNORE INTO am_body (kod, lat, lon, adresa) VALUES (?, ?, ?, ?)'
    davka = []
    with zipfile.ZipFile(cesta) as z:
        for info in z.infolist():
            obsah = z.read(info)
            if not obsah:
                continue
            pos = obsah.find(b'\n')
            if pos < 0 or 'Souřadnice Y' not in cp1250(obsah[:pos]):
                raise SystemExit('soubor adres RÚIAN má jiný tvar, než aplikace čeká')
            for b in obsah[pos + 1:].split(b'\n'):
                strednik = b.find(b';')
                kod = php_int(b[:max(strednik, 0)].decode('ascii', 'replace'))
                if kod not in kody:
                    continue
                c = [cp1250(x) for x in b.rstrip(b'\r').split(b';')]
                if len(c) < 18:
                    continue
                y, x = php_float(c[16]), php_float(c[17])
                if y < 1000 or x < 1000:
                    continue
                lat, lon = jtsk_na_wgs(y, x)
                davka.append((kod, php_round(lat, 6), php_round(lon, 6), adr_text(c)))
                if len(davka) >= 50000:
                    db.executemany(ins, davka); davka = []
    db.executemany(ins, davka)
    n = db.execute('SELECT COUNT(*) FROM am_body').fetchone()[0]
    if n == 0:
        raise SystemExit('z adres RÚIAN se nenašla žádná adresa provozovny')
    return n


def tri_roky_zpet(d):
    try:
        return d.replace(year=d.year - COI_LET)
    except ValueError:                           # 29. 2. → 1. 3. (jako strtotime v PHP)
        return d.replace(year=d.year - COI_LET, month=3, day=1)


def kontroly_coi(db, cesta, dnes_d):
    """coiAdrKrok() + coiKrok(): kontroly ČOI za poslední 3 roky na adresních místech s provozovnou. Vrací (uloženo, řádků, chyba)."""
    db.execute('CREATE TABLE IF NOT EXISTS main.am_coi_adr (klic TEXT NOT NULL PRIMARY KEY, kod INTEGER NOT NULL) WITHOUT ROWID')
    db.execute('DELETE FROM main.am_coi_adr')
    ins_adr = 'INSERT INTO main.am_coi_adr (klic, kod) VALUES (?, ?) ON CONFLICT(klic) DO UPDATE SET kod = CASE WHEN kod = excluded.kod THEN kod ELSE 0 END'
    for kod, adresa in db.execute('SELECT kod, adresa FROM main.am_body ORDER BY kod').fetchall():
        for k in coi_klice_adresy(adresa):
            db.execute(ins_adr, (k, kod))
    od = tri_roky_zpet(dnes_d).isoformat()
    dnes = dnes_d.isoformat()
    ins = '''INSERT INTO main.am_coi (kod, ico, datum, pocet) VALUES (?, ?, ?, 1)
             ON CONFLICT(kod, ico) DO UPDATE SET datum = max(datum, excluded.datum), pocet = pocet + 1'''
    sloupce = None
    radku = 0
    for b in radky_souboru(cesta):
        b = b.rstrip(b'\r')
        if b == b'':
            continue
        try:
            line = b.decode('utf-8')
        except UnicodeDecodeError:
            line = cp1250(b)                     # soubor může být i ve Windows-1250
        r = [x.strip(PHP_TRIM) for x in php_csv(line)]
        if sloupce is None:
            sloupce = hlavicka(r, s_norm=True)
            sloupce['_n'] = len(r)
            for nutny in ('DATUM KONTROLY', 'IC SUBJEKTU', 'ULICE', 'C. POPISNE', 'C. ORIENTACNI', 'PSC'):
                if nutny not in sloupce:
                    db.execute('DROP TABLE IF EXISTS main.am_coi_adr')
                    return db.execute('SELECT COUNT(*) FROM am_coi').fetchone()[0], 0, 'soubor ČOI má jiný tvar, než čekám'
            continue
        c = sloupce
        navic = len(r) - c['_n']
        if navic < 0:
            continue
        if navic > 0:                            # čárka v názvu ulice (soubor nepoužívá uvozovky)
            iu = c['ULICE']
            if c['C. POPISNE'] < iu or c['C. ORIENTACNI'] < iu or c['PSC'] < iu:
                continue
            r[iu:iu + navic + 1] = [','.join(r[iu:iu + navic + 1])]
        g = lambda k: r[c[k]] if c[k] < len(r) else ''
        m = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', g('DATUM KONTROLY'))
        if not m:
            continue
        datum = '%04d-%02d-%02d' % (int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if datum < od or datum > dnes:
            continue
        radku += 1
        ulice, cp, co = g('ULICE'), g('C. POPISNE'), g('C. ORIENTACNI')
        if cp == '' and co == '':
            mm = re.match(r'^(.*\S)\s+(\d+)(?:\s*/\s*(\d+[a-zA-Z]?))?$', ulice)
            if mm:
                ulice, cp, co = mm.group(1), mm.group(2), mm.group(3) or ''
        kod = None
        for k in coi_klice(g('PSC'), ulice, cp, co):
            x = db.execute('SELECT kod FROM main.am_coi_adr WHERE klic = ? AND kod > 0', (k,)).fetchone()
            if x:
                kod = x[0]
                break
        if kod is None:
            continue
        ico = ico_norm(g('IC SUBJEKTU')) or ''      # živnostníci jsou bez IČO (ČOI je anonymizuje)
        db.execute(ins, (kod, ico, datum))
    db.execute('DROP TABLE IF EXISTS main.am_coi_adr')
    return db.execute('SELECT COUNT(*) FROM am_coi').fetchone()[0], radku, ''


def firmy(db, cesta, davka_cislo):
    """resKrok(): firmy z RES ČSÚ – obchodní společnosti a družstva; živnostníci jen s aktivní provozovnou
    (lékárník, lékař, veterinář provozovnu v rejstříku mít nemusí)."""
    s_prov = {r[0] for r in db.execute('SELECT DISTINCT ico FROM main.am_provozovny')}
    ins = '''INSERT INTO am_subjekty (ico, nazev, forma, katpo, nace, okres, obec, ulice, cdom, cor, vznik, slov, obecna, davka)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(ico) DO UPDATE SET nazev = excluded.nazev, forma = excluded.forma, katpo = excluded.katpo, nace = excluded.nace, okres = excluded.okres,
                 obec = excluded.obec, ulice = excluded.ulice, cdom = excluded.cdom, cor = excluded.cor, vznik = excluded.vznik, slov = excluded.slov,
                 obecna = excluded.obecna, davka = excluded.davka'''
    ins_slovo = 'INSERT OR IGNORE INTO am_subjekty_slova (slovo, okres, ico) VALUES (?, ?, ?)'
    c = None
    poc = collections.Counter()
    nedokonceny = ''
    d_firmy, d_slova = [], []

    def uloz():
        db.executemany(ins, d_firmy); db.executemany(ins_slovo, d_slova)
        d_firmy.clear(); d_slova.clear()

    for b in radky_souboru(cesta):
        line = text_utf8(b)
        if nedokonceny != '':
            line = nedokonceny + '\n' + line
            nedokonceny = ''
        if line.count('"') & 1:                  # název přes víc řádků
            nedokonceny = line
            continue
        line = line.rstrip('\r')
        if line == '':
            continue
        r = php_csv(line)
        if c is None:
            c = hlavicka(r)
            for nutny in ('ICO', 'OKRESLAU', 'DDATZAN', 'FORMA', 'KATPO', 'NACE', 'FIRMA'):
                if nutny not in c:
                    raise SystemExit('soubor registru má jiný tvar, chybí sloupec ' + nutny)
            continue
        g = lambda k: (r[c[k]] if c[k] < len(r) else '') if k in c else ''
        poc['radku'] += 1
        okres = g('OKRESLAU').strip(PHP_TRIM)
        forma = php_int(g('FORMA'))
        nace = g('NACE').strip(PHP_TRIM)
        if g('DDATZAN').strip(PHP_TRIM) != '':
            poc['zanikle'] += 1
            continue
        if forma not in RES_PO and forma not in RES_FO:
            poc['jine'] += 1
            continue
        if forma in RES_FO and not s_prov and nace[:2] not in RES_NACE_FO:
            poc['jine'] += 1
            continue
        ico = ico_norm(g('ICO'))
        nazev = txt(g('FIRMA'), 190)
        if ico is None or nazev == '':
            continue
        if forma in RES_FO and s_prov and not nace_bez_zivnosti(nace) and ico not in s_prov:
            poc['bez_prov'] += 1
            continue
        h = lambda k: platne(g(k).strip(PHP_TRIM))
        dd, gg = firma_slova(nazev)
        d_firmy.append((ico, nazev, forma, php_int(g('KATPO')), platne(nace), platne(okres), h('OBEC_TEXT'), h('ULICE_TEXT'), h('CDOM'), h('COR'), h('DDATVZN'),
                        len(dd), ' '.join(gg), davka_cislo))
        d_slova.extend((w, platne(okres), ico) for w in dd)
        poc['ulozeno'] += 1
        if len(d_firmy) >= 50000:
            uloz()
    uloz()
    if c is None:
        raise SystemExit('soubor registru je prázdný')
    return dict(poc)


def postav(cil, res, ros, adr, coi, cas=None):
    """Postaví CIL/registr.sqlite ze stažených souborů a vrátí údaje pro registr.json."""
    cas = cas or int(time.time())
    dnes_d = datetime.datetime.fromtimestamp(cas, ZONA).date()
    dnes = dnes_d.isoformat()
    os.makedirs(cil, exist_ok=True)
    soubor = os.path.join(cil, 'registr.sqlite')
    for k in ('', '-journal', '-wal', '-shm'):
        if os.path.exists(soubor + k):
            os.remove(soubor + k)
    db = sqlite3.connect(soubor, isolation_level=None)
    db.execute('PRAGMA journal_mode = DELETE')
    db.execute('PRAGMA synchronous = OFF')
    for sql in TABULKY:
        db.execute(sql)
    info = {'format': REG_FORMAT, 'davka': cas}
    db.execute('BEGIN')
    info['prov_ulozeno'] = provozovny(db, ros, dnes)
    db.execute('COMMIT')
    log('provozoven', info['prov_ulozeno'])
    db.execute('BEGIN')
    info['adr_ulozeno'] = adresy(db, adr)
    db.execute('COMMIT')
    info['adr_soubor'] = os.path.basename(adr)
    log('adres s provozovnou', info['adr_ulozeno'])
    if coi and os.path.isfile(coi):
        db.execute('BEGIN')
        info['coi_ulozeno'], info['coi_radku'], info['coi_chyba'] = kontroly_coi(db, coi, dnes_d)
        db.execute('COMMIT')
    else:
        info['coi_ulozeno'], info['coi_radku'], info['coi_chyba'] = 0, 0, 'soubor ČOI se nepodařilo stáhnout'
    log('kontrol ČOI', info['coi_ulozeno'], info['coi_chyba'])
    db.execute('BEGIN')
    info.update(firmy(db, res, cas))
    db.execute('COMMIT')
    log('firem', info.get('ulozeno'), 'řádků', info.get('radku'))
    info['vznik_od'] = datetime.datetime.fromtimestamp(cas - REG_VZNIK_DNI * 86400, ZONA).date().isoformat()     # regVznikOd()
    db.execute(f"CREATE INDEX IF NOT EXISTS main.i_subjekty_vznik ON am_subjekty (vznik) WHERE vznik >= '{info['vznik_od']}'")
    db.execute('VACUUM')
    db.close()
    info['velikost'] = os.path.getsize(soubor)
    with open(soubor, 'rb') as f:
        info['sha256'] = hashlib.sha256(f.read()).hexdigest()
    return soubor, info


# --------------------------------------------------------------------------------------------------------------------
# Zabalení: kusy po 16 MiB, každý zvlášť zkomprimovaný (zlib) a zašifrovaný (AES-256-GCM)
# --------------------------------------------------------------------------------------------------------------------

KUS = 16 * 1048576


def klic_z_prostredi():
    k = os.environ.get('BALIK_KLIC', '').strip()
    if not k:
        raise SystemExit('chybí BALIK_KLIC (tajemství repozitáře) – registr se nezveřejní')
    try:
        b = base64.b64decode(k, validate=True)
    except ValueError:
        raise SystemExit('BALIK_KLIC není v base64')
    if len(b) != 32:
        raise SystemExit('BALIK_KLIC musí mít 32 bajtů (base64 ze 32 náhodných bajtů)')
    return b


def zabal(soubor, info, vystup, klic):
    """registr.sqlite → vystup/registr-VERZE.bin (zašifrované kusy za sebou) + vystup/registr.json (popis kusů, nic tajného)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    os.makedirs(vystup, exist_ok=True)
    aes = AESGCM(klic)
    verze = datetime.datetime.fromtimestamp(info['davka'], datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    kusy = []
    pozice = 0
    # název podle verze: aplikace, která zrovna stahuje starší verzi, ji dostáhne (na GitHubu zůstávají dvě poslední)
    nazev = 'registr-' + verze.replace('-', '').replace(':', '') + '.bin'
    with open(soubor, 'rb') as f, open(os.path.join(vystup, nazev), 'wb') as o:
        i = 0
        while True:
            data = f.read(KUS)
            if not data:
                break
            nonce = os.urandom(12)
            sifra = aes.encrypt(nonce, zlib.compress(data, 6), f'{verze}|{i}'.encode())
            o.write(nonce + sifra)
            kusy.append([pozice, 12 + len(sifra)])
            pozice += 12 + len(sifra)
            i += 1
    meta = {
        'verze': verze,
        'vytvoreno': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'soubor': nazev,
        'velikost_bin': pozice,
        'kus': KUS,
        'kusy': kusy,
        'sifra': 'aes-256-gcm',
        **info,
        'licence': 'RES (ČSÚ), Registr osob (Digitální a informační agentura), RÚIAN (ČÚZK, CC BY 4.0), kontroly ČOI (Česká obchodní inspekce) – otevřená data',
    }
    with open(os.path.join(vystup, 'registr.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    log(f'zabaleno: {len(kusy)} kusů, {pozice / 1048576:.1f} MB (soubor registru {info["velikost"] / 1048576:.1f} MB)')
    return meta


def rozbal(vystup, klic, cil):
    """Opačný postup (stejně jako aplikace): kus po kusu rozšifrovat, rozbalit, připojit; nakonec ověřit sha256."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    meta = json.load(open(os.path.join(vystup, 'registr.json'), encoding='utf-8'))
    aes = AESGCM(klic)
    with open(os.path.join(vystup, meta['soubor']), 'rb') as f, open(cil, 'wb') as o:
        for i, (pozice, delka) in enumerate(meta['kusy']):
            f.seek(pozice)
            b = f.read(delka)
            o.write(zlib.decompress(aes.decrypt(b[:12], b[12:], f'{meta["verze"]}|{i}'.encode())))
    with open(cil, 'rb') as f:
        if hashlib.sha256(f.read()).hexdigest() != meta['sha256']:
            raise SystemExit('rozbalený registr nesedí (sha256)')
    log('rozbaleno a ověřeno', cil)


# --------------------------------------------------------------------------------------------------------------------
# Stažení zdrojů (nejsou-li už stažené z kroku „Registr provozoven“ – zdroje.py je nechává ve složce stazene/)
# --------------------------------------------------------------------------------------------------------------------

URL_RES = 'https://opendata.csu.gov.cz/soubory/od/od_org03/res_data.csv'
URL_ROS = 'https://www.szrcr.cz/images/dokumenty/ROS/Otevrena%20data/ros02_data.csv'
URL_ADR = 'https://vdp.cuzk.gov.cz/vymenny_format/csv/{:%Y%m%d}_OB_ADR_csv.zip'
URL_COI = 'https://coi.gov.cz/userdata/files/dokumenty-ke-stazeni/open-data/kontroly.csv'


def stahni_zdroje(slozka):
    from zdroje import stahni
    os.makedirs(slozka, exist_ok=True)
    res, ros, coi = (os.path.join(slozka, x) for x in ('res.csv', 'ros.csv', 'kontroly.csv'))
    if not os.path.isfile(res):
        stahni(URL_RES, res)
    if not os.path.isfile(ros):
        stahni(URL_ROS, ros)
    adr = next((os.path.join(slozka, x) for x in sorted(os.listdir(slozka), reverse=True) if x.endswith('_OB_ADR_csv.zip')), None)
    if adr is None:
        d = datetime.date.today().replace(day=1) - datetime.timedelta(days=1)
        for _ in range(3):
            try:
                adr = os.path.join(slozka, f'{d:%Y%m%d}_OB_ADR_csv.zip')
                stahni(URL_ADR.format(d), adr)
                break
            except SystemExit:
                if adr and os.path.exists(adr):
                    os.remove(adr)
                d = d.replace(day=1) - datetime.timedelta(days=1)
                adr = None
        if adr is None:
            raise SystemExit('adresy RÚIAN se nepodařilo stáhnout')
    if not os.path.isfile(coi):
        try:
            stahni(URL_COI, coi)
        except SystemExit:
            log('kontroly ČOI se nepodařilo stáhnout – registr se postaví bez nich')
            coi = None
    return res, ros, adr, coi


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == 'postav':
        # python3 registr.py postav STAZENE VYSTUP: stáhne, co chybí, postaví, zkontroluje a zabalí (potřebuje BALIK_KLIC)
        klic = klic_z_prostredi()
        soubor, info = postav(os.path.join(a[2], 'prace'), *stahni_zdroje(a[1]))
        if not os.environ.get('MALY_TEST') and (info['ulozeno'] < 300000 or info['prov_ulozeno'] < 200000 or info['adr_ulozeno'] < 100000):
            raise SystemExit(f'podezřele málo dat (firem {info["ulozeno"]}, provozoven {info["prov_ulozeno"]}, adres {info["adr_ulozeno"]}) – registr se nezveřejní')
        zabal(soubor, info, a[2], klic)
        rozbal(a[2], klic, os.path.join(a[2], 'prace', 'kontrola.sqlite'))
    elif len(a) == 6 and a[0] == 'soubory':
        # python3 registr.py soubory RES ROS ADR COI VYSTUP: postaví z místních souborů (zkoušky), bez zabalení
        soubor, info = postav(a[5], a[1], a[2], a[3], a[4] if a[4] != '-' else None, int(os.environ['CAS']) if os.environ.get('CAS') else None)
        with open(os.path.join(a[5], 'registr-info.json'), 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=1)
    else:
        sys.exit(__doc__)
