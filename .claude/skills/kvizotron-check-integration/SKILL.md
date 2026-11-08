---
name: kvizotron-check-integration
description: Use when a Kvízotron change touches more than one layer or an existing flow such as playing, revisions, schedule, grading, settings or import, and when asked whether a feature really works end to end.
---

# Kontrola toků napříč vrstvami

`tests/test_wiring.py` ověří, že kusy existují. Tady se ověřuje, že na sebe navazují: co jeden článek uloží, další opravdu čte, a člověk se k tomu dostane přes skutečnou adresu.

Čtení diffu a hodnocení návrhu sem nepatří, to dělá `review-roles`.

## Postup

1. **Najdi dotčené toky.** Podle změněných souborů je vyber v `flows.md` vedle tohoto souboru. Nic nesedí? Změna je buď lokální, a řekni to, nebo vzniká nový tok, a přidej ho.
2. **Spusť testy toku.** Každý tok má v `flows.md` příkaz. Vždy celý tok, ne jen soubor, který ses dotkl.
3. **Projdi články, které se změnily.** Ke každému napiš důkaz, že ho volá předchozí článek a jeho výsledek čte další:
   - test, který jde přes HTTP adresu toku a spadl by, kdyby článek chyběl,
   - test jen volající funkci domény důkaz není.
4. **Zkus cestu, kdy článek odmítne.** Každý tok uvádí, co může selhat. Člověk musí dostat srozumitelnou odpověď a data musí zůstat v pořádku.
5. **Projdi sousední cesty.** Náhled a testovací odkaz se mají chovat stejně a nic nezapočítat. Soukromý odkaz, veřejný průchod a archiv musí unést nová data.
6. **Chybí test?** Napiš ho, nech ho selhat a pak oprav. Co ověřit nejde, napiš jako **neověřeno**.

## Výstup

| Tok | Testy toku | Změněný článek | Důkaz napojení | Odmítnutí | Sousední cesty |
|---|---|---|---|---|---|

Na konci seznam **neověřeno**, i když je prázdný.

## Údržba

Milník, který přidá tok nebo článek, mění `flows.md` ve stejné větvi. Cesty v něm hlídá `tests/test_docs.py`.
