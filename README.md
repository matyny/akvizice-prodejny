# akvizice-prodejny

Jednou měsíčně připraví balík prodejen v Česku pro Akviziční mapu.

- Spouští se samo 2. den v měsíci, ručně: **Actions → Prodejny z mapy → Run workflow** (volba „Jen zkouška“ balík nezveřejní).
- Výsledek: **Releases → Prodejny z mapy** (`prodejny.zip`, `meta.json`). Aplikace si ho stahuje sama.
- Zdroje:
  - **OpenStreetMap** (výřez mapy Česka od Geofabriku) – základ; které druhy prodejen se berou: `typy.txt`. Stojany sdílených kol se vynechávají.
  - **Overture Maps** (firemní stránky, Foursquare, Microsoft) – potvrdí prodejnu z mapy a doplní ty, které na mapě chybí;
    které kategorie odpovídají kterému druhu: `overture.txt`.
  - **Overture – jméno člověka bez provozovny**: místo jen z Overture, jehož název je jen jméno člověka („Robert Dominik“)
    a v domě není žádná provozovna z rejstříku, se nebere – bývá to sídlo živnostníka v bytě, ne prodejna.
  - **Overture – trvale zavřená místa**: prodejna z mapy, kterou Overture vede jako trvale zavřenou (a žádný jejich otevřený
    záznam ji nepotvrzuje), se označí jako zavřená.
  - **Foursquare OS Places** (zdarma, Apache 2.0) – kdy místo naposledy ověřili, nebo že je zavřené. Potřebuje přístupový klíč:
    na [huggingface.co/datasets/foursquare/fsq-os-places](https://huggingface.co/datasets/foursquare/fsq-os-places) potvrdit
    podmínky (účel Commercial), v Hugging Face → Settings → Access Tokens vytvořit klíč typu Read a vložit ho sem jako
    **Settings → Secrets and variables → Actions → New repository secret**, název `HF_TOKEN`. Bez klíče se Foursquare vynechá.
  - **Registr osob + RÚIAN + RES** – prodejna, jejíž firma tu ukončila provozovnu a jinou tu nemá, se označí jako nejspíš zavřená.
  - **Adresy RÚIAN**: každá prodejna dostane kód nejbližšího adresního místa (do 40 m) a prodejna bez adresy i adresu.
  - **Přestěhované prodejny**: prodejna, kterou nic nepotvrzuje, a do 500 m je potvrzená prodejna stejného druhu
    s podobným jménem → označí se odkazem na nástupce.
  - **Sortiment**: když Overture vede místo jako jiný druh než mapa, jde do balíku jeho kategorie (a kategorie Foursquare).
  - Z OpenStreetMap se neberou místa označená jako zavřená (datum ukončení v minulosti, otevírací doba „closed“, disused/abandoned);
    u záznamů, které nikdo 3 a více let neupravil ani nezkontroloval, jde do balíku datum poslední úpravy.
  - Když některý doplňkový zdroj selže, balík se postaví bez něj.
- Stahování doplňkových zdrojů: `zdroje.py`, stavba balíku: `build.py`.

## Registr firem pro aplikaci

Stejný běh postaví i hotový **registr firem** (RES ČSÚ, provozovny z Registru osob, adresy RÚIAN, kontroly ČOI) – stejné tabulky
a pravidla jako aplikace (`lib/res.php`, `lib/provozovny.php`). Aplikace si ho jen stáhne místo stavby na hostingu: `registr.py`.

- Výsledek: **Releases → Prodejny z mapy** – `registr.json` (popis, počty) a `registr-VERZE.bin` (data). Zůstávají dvě poslední verze dat.
- Data jsou **zašifrovaná** (AES-256-GCM): jsou v nich i jména živnostníků a repozitář je veřejný. Přečte je jen aplikace se stejným klíčem.
- Klíč (jednou): 32 náhodných bajtů v base64, např. v Git Bash `openssl rand -base64 32`, nebo v PowerShell 7
  `[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))`.
  Vložit sem jako **Settings → Secrets and variables → Actions → New repository secret**, název `BALIK_KLIC`,
  a stejný klíč do `config.php` každé aplikace (`'balik_klic' => '…'`). Klíč nikam jinam neposílat.
  Bez tajemství se krok přeskočí (aplikace si registr staví sama jako dřív).
- Volba „Jen zkouška“ registr nezveřejní – uloží ho na 3 dny k běhu (Actions → běh → Artifacts).
- Když se v aplikaci změní tabulky registru nebo pravidla jeho stavby, musí se stejně změnit `registr.py` a zvýšit `REG_FORMAT`
  (v aplikaci `AM_REG_FORMAT`) – aplikace jiný formát nepřijme a postaví si registr sama.
- Stažené soubory registrů nechává `zdroje.py registr` ve složce `stazene/`, `registr.py` z nich staví (co chybí, stáhne sám).

Data © přispěvatelé OpenStreetMap (ODbL 1.0); Overture Maps Foundation (CDLA Permissive 2.0 / Apache 2.0);
Foursquare OS Places (Apache 2.0, NOTICE se přikládá k vydání jako `NOTICE-foursquare.txt`);
Registr osob (Digitální a informační agentura), RÚIAN (ČÚZK, CC BY 4.0), RES (ČSÚ), kontroly ČOI (Česká obchodní inspekce) – otevřená data.
