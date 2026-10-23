# akvizice-prodejny

Jednou měsíčně připraví balík prodejen v Česku pro Akviziční mapu.

- Spouští se samo 2. den v měsíci, ručně: **Actions → Prodejny z mapy → Run workflow** (volba „Jen zkouška“ balík nezveřejní).
- Výsledek: **Releases → Prodejny z mapy** (`prodejny.zip`, `meta.json`). Aplikace si ho stahuje sama.
- Zdroje:
  - **OpenStreetMap** (výřez mapy Česka od Geofabriku) – základ; které druhy prodejen se berou: `typy.txt`. Stojany sdílených kol se vynechávají.
  - **Overture Maps** (firemní stránky, Foursquare, Microsoft) – potvrdí prodejnu z mapy a doplní ty, které na mapě chybí;
    které kategorie odpovídají kterému druhu: `overture.txt`.
  - **Registr osob + RÚIAN + RES** – prodejna, jejíž firma tu ukončila provozovnu a jinou tu nemá, se označí jako nejspíš zavřená.
  - Když některý doplňkový zdroj selže, balík se postaví bez něj.
- Stahování doplňkových zdrojů: `zdroje.py`, stavba balíku: `build.py`.

Data © přispěvatelé OpenStreetMap (ODbL 1.0); Overture Maps Foundation (CDLA Permissive 2.0 / Apache 2.0);
Registr osob (Digitální a informační agentura), RÚIAN (ČÚZK, CC BY 4.0), RES (ČSÚ) – otevřená data.
