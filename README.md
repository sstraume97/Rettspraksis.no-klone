# Rettspraksis.no-klone

En automatisert, ikke-kommersiell speiling av [Rettspraksis.no](https://rettspraksis.no)
— norske rettsavgjørelser lagret som Markdown-filer og publisert som
nedlastbare [Quarto](https://quarto.org)-bøker (HTML, PDF og EPUB).

Dette prosjektet er **ikke** tilknyttet eller godkjent av Rettspraksis.no. Se
[LICENSE-CONTENT.md](LICENSE-CONTENT.md) for lisensvilkår (CC BY-NC-SA 4.0)
for selve innholdet.

## Struktur

Hver `content/<court>/[<år>/]`-mappe er *både* der kildefilene ligger *og* et
komplett Quarto-bokprosjekt (ingen egen kopi i en separat `books/`-mappe):

```
content/
  hoyesterett/<år>/
    <Publisert>.md      # én fil per avgjørelse (YAML-frontmatter + brødtekst)
    index.qmd            # generert oppsummeringstabell (kapittel 1)
    _quarto.yml           # generert Quarto-bokkonfigurasjon
  lagmannsrett/<år>/      # samme oppsett som hoyesterett
  tingrett/                # samlebok, ikke årsdelt (lavt volum: ~120 saker)
    <Publisert>.md
    index.qmd
    _quarto.yml
```

Hver avgjørelse har frontmatter-feltene Instans, Dato, Publisert, Stikkord,
Sammendrag, Saksgang, Parter, Forfatter, Lovhenvisninger og kilde.
Oppsummeringstabellen i `index.qmd` er sortert på registreringsnummer
(tallet rett etter årstallet i `Publisert`, f.eks. `1374` i `Rt-1953-1374`).

## Automatisering

- **`.github/workflows/backfill.yml`** — kjører hver 6. time og henter
  historiske avgjørelser i bolker (respekterer `Crawl-delay: 15` fra
  Rettspraksis.no sin `robots.txt`), med gjenopptagbar fremdrift lagret i
  `state/sync_state.json`. Blir automatisk en no-op når alt er hentet.
- **`.github/workflows/weekly-update.yml`** — kjører hver mandag, henter kun
  nye/endrede sider siden forrige kjøring (`list=recentchanges`),
  regenererer berørte bøker (`build_books.py`), renderer HTML/PDF/EPUB med
  Quarto (`render_books.py`), laster opp PDF/EPUB som vedlegg til en GitHub
  Release per bok (`publish_releases.py`) og publiserer HTML-versjonen til
  GitHub Pages (`build_index.py` + `peaceiris/actions-gh-pages`, med
  `keep_files: true` slik at tidligere publiserte, ikke-berørte bøker blir
  liggende).

**Obs, ett engangsoppsett:** GitHub Pages må slås på manuelt én gang i
repoets Settings → Pages → Source: "Deploy from a branch" → `gh-pages` (denne
branchen opprettes automatisk av `weekly-update.yml` ved første kjøring med
innhold å publisere).

## Kjøre lokalt

```bash
pip install -r requirements.txt

# Hent et lite testutvalg (respekterer 15s crawl-delay mot rettspraksis.no)
python scripts/fetch_pages.py --mode backfill --limit 20

# Bygg bøker for alt hentet innhold
python scripts/build_books.py --all

# Render én bok (krever quarto + tinytex, og tlmgr install hyphen-norwegian
# for PDF — se merknad i .github/workflows/weekly-update.yml)
quarto render content/hoyesterett/1953
```

## Lisens

- Kildekode (`scripts/`, workflows): [MIT](LICENSE)
- Innhold (`content/`, genererte bøker/PDF/EPUB): [CC BY-NC-SA 4.0](LICENSE-CONTENT.md)
