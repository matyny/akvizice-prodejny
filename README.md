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
  - Z OpenStreetMap se neberou místa označená jako zavřená (datum ukončení v minulosti, otevírací doba „closed“, disused/abandoned);
    u záznamů, které nikdo 3 a více let neupravil ani nezkontroloval, jde do balíku datum poslední úpravy.
  - Když některý doplňkový zdroj selže, balík se postaví bez něj.
- Stahování doplňkových zdrojů: `zdroje.py`, stavba balíku: `build.py`.

Data © přispěvatelé OpenStreetMap (ODbL 1.0); Overture Maps Foundation (CDLA Permissive 2.0 / Apache 2.0);
Foursquare OS Places (Apache 2.0, NOTICE se přikládá k vydání jako `NOTICE-foursquare.txt`);
Registr osob (Digitální a informační agentura), RÚIAN (ČÚZK, CC BY 4.0), RES (ČSÚ) – otevřená data.
