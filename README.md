# Resolutions splitter

Splits a multi-resolution PDF into one file per resolution number, using OCR and a
vision model **only where cheaper evidence runs out**.

## The cost model

400,000 pages a day cannot each be read by a model. The pipeline is a cascade, and
every rung only sees what the previous one could not answer:

| Rung | What it does | Cost |
|------|--------------|------|
| L0 | embedded text layer + fuzzy anchor match | ~0 |
| L1 | OCR of the header band only (~28% of the pixels) | CPU |
| L2 | OCR of the full page | CPU |
| L3 | sequence context — a page whose neighbours agree needs nobody | ~0 |
| L4 | vision model, on header crops, batched a dozen at a time | tokens |

A page with no anchor but a text layer that was read successfully is a continuation
page: the grouping engine inherits it for free and it never reaches a model. Only
pages that are genuinely ambiguous — competing codes, or an OCR read that came back
near-empty — escalate.

Every run reports what fraction of pages reached L4, so the bill is measured rather
than assumed. On a 180-page digital batch that figure is **0%**.

## Batches and live progress

Fifty or more PDFs can be dropped at once. They are uploaded three at a time —
fifty parallel transfers only starve one another — and processed by a pool of one
OS process per document.

Each worker emits an event per page through a shared queue. The API folds those
into per-document state and pushes coalesced frames four times a second: a
400-page document produces 400 events but never 400 frames at the browser. The UI
draws a live ribbon, one cell per page, painted by the rung that answered it.

Failures are isolated at three levels, so nothing cascades:

- **a page** that cannot be read is marked unreadable and sent to review; the other
  399 pages of that document still process
- **a document** that fails does not stop its batch
- **telemetry** that breaks never interrupts the work it was describing

Three screens, one verb each: **do** the work, **find** the work, **fix** the work.

**Procesar** takes documents in and shows only what is happening now. Uploads come
in three modes -- individual up to five, batch unbounded, or a local folder --
because "I am splitting these five", "I am running a job" and "watch this folder"
want different screens and different pacing. Finished work leaves this screen
entirely; the count on the Archivo tab is what says so.

**Archivo** is everything that came out, at either grain. One card per processed
document, whether it is still in the registry or only in the ledger -- live jobs
and history used to render as two different objects, so the same document looked
like two kinds of thing depending on how recently it ran. The cards carry the
figures that matter (resolutions, pages, size, who, when) and not the resolution
numbers: a fistful of codes with no room to say what they mean is noise, and the
"por resolución" grain lists them properly. Filter by text, period, state and
operator; order by date, volume or name; every day heading carries that day's own
totals, because a heading that only gives the date makes the reader add up the
cards underneath it. Documents and
resolutions used to be two screens showing the same work at two levels, and an
operator looking for "la 00086" had to guess which one held it. They are the same
question, so they are one screen and the grain is a control rather than a
destination. It reads its history from the ledger rather than the registry, which
is what makes it survive a screen clear and a restart, and why everything in it
carries the date it was processed, grouped by day.

**Revisión** is the queue of what the machine refused to guess at, gathered
across every document and grouped by why. Every other screen answers "what did it
do"; this one answers "what needs me", which is the only question with a deadline
attached. Buried one document at a time it was invisible.

The console is docked to the bottom, collapsed to a strip showing its last line.
A log reassures, is read after the fact, and is almost never the most important
thing on screen -- parked down the right-hand side it was taking a third of a
laptop's width from the work itself.

A report is raised only for work this tab watched go from in flight to settled.
The service keeps finished runs in memory and replays them on connect, so
without that rule a page refresh popped a report for a run that had finished an
hour earlier. Anything already done when a tab connects is filed into the
history silently.

A folder run reports from its own totals -- pages, bytes, wall clock -- because
its documents leave the registry long before anyone reopens the report. Summing
the jobs then yields zeros, and a report that states something untrue is worse
than no report at all.

When a unit of work settles it raises a report rather than simply vanishing:
documents, pages, resolutions, net weight, wall clock, how each page was
answered, and every resolution produced. The live view disappearing is not an
answer; the operator watched it run and is owed what it did.

## Sessions

Entry asks for a name and nothing else. There is no password, the login screen
says so in as many words, and the tests pin it: `TestItGrantsNothing` asserts
that reading, deleting and uploading all work with no name at all. If anyone
ever wires the header to a permission, those tests fail and the decision has to
be made on purpose.

What the name buys is real anyway. Every job carries the operator who ran it,
into the ledger, so the archive answers "who processed this" long after the
screen was cleared, and a shift has a beginning and an end. The name is
percent-encoded on the wire, because HTTP header values are ASCII and half the
names in a Spanish-speaking building carry an accent -- sending one raw throws
in the browser before the request is even made.

The session is an explicit machine with three states:

```
anonymous --open()--> active --idle(1h)--> idle --resume()--> active
                         `--close()--> anonymous <--close()--'
```

Idle is not a lock; one click resumes it, because there is nothing to unlock. It
exists so a console left open overnight stops attributing the next morning's
work to whoever walked away from it. Closing a session may clear the screen --
handing over someone else's work is its own confusion -- but never the files,
and never without being asked.

## The header format

Real headers are written one of three ways, and the corpus varies only in casing,
accents and the trailing year:

```
RESOLUCION NO. 00086
Resolución No. 00072 de 2023
RESOLUCIÓN No. 00083 de 2023
```

The anchor, a numbering token and a zero-padded number are the invariant, so that
structure is scored as a signal in its own right (`OFFICIAL_FORM_WEIGHT`). Without
it a title-cased header rests on its capitals alone and lands a hundredth above
the confidence floor — one competing reading away from an avoidable trip to the
vision model. The signal is withheld from citations, which are written in the same
form: the shape says "this is a resolution number", never "this page is it".

## The grouping rules

1. A page with a code opens or continues that resolution's group.
2. A page with no code inherits the **previous page's** code.
3. Grouping is **by code, not by contiguity**: a code that reappears later rejoins
   its original group. Pages keep their original document order.
4. Pages before the first code are **quarantined**, never guessed at.
5. A single-page misread flanked by two identical readings (edit distance ≤ 2) is
   absorbed as OCR noise, and the correction is recorded.
6. Nothing is written unless every source page is accounted for exactly once.

Output files are named `<code>__<title>.pdf`, and an `inventory.json` /
`inventory.csv` records what came out of each source document.

## The inventory

A per-document `inventory.json` answers "what came out of this file". After a few
hundred documents the question becomes "which document did 00086 come from", so
every generated PDF is also appended to one durable ledger (`data/inventory.jsonl`,
one line per file). Recording a finished job is a single append, never a rewrite,
and the parse is cached against the file's own size and mtime.

The ledger outlives the job registry deliberately: clearing the screen forgets
jobs, and the ledger is the record that the work happened. `GET /api/inventory`
searches it, `GET /api/inventory.csv` exports it with a BOM so Excel opens the
accents correctly, and downloads are served by job id alone so a cleared
document's files stay reachable.

## Damage and scale

Scanners, mail gateways and decade-old archives produce PDFs whose object tables
do not survive a strict read — `code=4: source object number out of range` is
MuPDF saying so. A document that reaches assembly has already been read, grouped
and balanced, so the writer degrades in three steps rather than losing all of it:

1. **Repair.** When MuPDF had to rebuild the cross-reference table it did so in
   memory, and the object numbers the page tree cites are not the ones the
   rebuild holds. Writing that rebuild out and reopening it renumbers everything
   consistently — one extra pass, and only for damaged files.
2. **Per-page retry.** A block copy that raises is retried page by page. More
   object rewrites, but every page that is not itself broken still ships.
3. **Named loss.** A page that cannot be copied at any granularity goes to review
   by number. The file exists with less in it, and nobody has to discover that by
   diffing page counts.

Uploads stream to disk in chunks and are never held in memory, so the 4 GB
default cap bounds disk rather than RAM, and the queue limit bounds what may be
accepted and not yet started rather than what can be processed.

## Idle cache sweep

Three things accumulate during a run and are worthless once it ends: an upload
whose job is gone, an output directory nothing references, and the page ribbon of
a document whose report already says everything the ribbon said. A janitor
reclaims them — and nothing else. The generated PDFs and the ledger are never
touched.

Two guards keep the idle case free. It skips unless the queue is empty, because
reclaiming disk under a running worker is how a half-written output directory
disappears; and it skips again unless the registry has changed since the last
pass. A system at rest costs one integer comparison per tick and not a single
filesystem call. `GET /api/cache` reports what it would do; `POST /api/cache/sweep`
runs it now.

## Layout

```
backend/
  src/resolutions/
    domain/       pure rules, zero dependencies  (anchor, extraction, scoring,
                  grouping, title, naming)
    application/  use cases and ports            (pipeline, process_document, inventory)
    adapters/     one vendor each                (PyMuPDF, Tesseract, Claude, files)
    api/          FastAPI, worker pool, SSE
  tests/          384 tests, domain runs in ~0.5s
web/              SvelteKit 5 + Tailwind 4 front end
```

The user interface, its messages and the review reasons are in Spanish. Code
identifiers and comments stay in English, matching the libraries they sit on.

The domain layer imports nothing but the standard library. That is what keeps the
rules testable in microseconds and portable if throughput ever demands another
runtime.

## Running it

### Requirements

- Python 3.12+
- Node 20+
- **Tesseract OCR** with the Spanish language pack — the only external binary.
  Windows: `winget install UB-Mannheim.TesseractOCR`, then make sure `tesseract`
  is on `PATH`. Without it, digital PDFs still work; scans go to review.

### Backend

```bash
cd backend
pip install -e ".[dev]"
pytest                                   # 384 tests
uvicorn resolutions.api.main:app --port 8000
```

### Front end

```bash
cd web
npm install
npm run dev                              # http://localhost:5173
npm test                                 # 54 tests over the stores
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so everything is
same-origin and CORS never comes into it.

### Desde otro equipo de la red

El servidor de desarrollo escucha en todas las interfaces (`server.host` en
`web/vite.config.ts`), así que basta con abrir `http://IP-DEL-SERVIDOR:5173`
desde el otro puesto. Vite imprime la dirección al arrancar, bajo `Network:`.

El backend **no** hace falta exponerlo: quien habla con él es el proxy del
servidor de desarrollo, que corre en la misma máquina, y por eso puede seguir
escuchando sólo en `127.0.0.1`. Si aun así se quisiera alcanzar la API
directamente desde otro equipo, hay que arrancarla con
`uvicorn resolutions.api.main:app --host 0.0.0.0 --port 8000` **y** añadir ese
origen a la lista de CORS en `api/main.py`, que hoy sólo admite localhost.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | enables the L4 rung; without it, escalations go to review |
| `RESOLUTIONS_DOCUMENT_WORKERS` | cores − 1 | PDFs processed in parallel (one process each) |
| `RESOLUTIONS_PAGE_WORKERS` | 8 | threads fanning pages across OCR inside a worker |
| `RESOLUTIONS_QUEUE_LIMIT` | 10000 | documents accepted and not yet started before the API returns 429 |
| `RESOLUTIONS_OCR_LANG` | `spa` | Tesseract language |
| `RESOLUTIONS_TESSERACT_CMD` | from `PATH` | full path to `tesseract.exe` when it is not on `PATH` |
| `RESOLUTIONS_MOSAIC_SIZE` | 12 | crops per vision request |
| `RESOLUTIONS_DATA_DIR` | `./data` | uploads and outputs |
| `RESOLUTIONS_MAX_UPLOAD_BYTES` | 4 GB | largest accepted PDF; bounds disk, not memory |
| `RESOLUTIONS_LEDGER` | `./data/inventory.jsonl` | the durable inventory |
| `RESOLUTIONS_SWEEP_SECONDS` | 30 | how often the idle janitor looks for scratch |

## Not built yet

- **ROI learning.** The `RoiRegistry` port is defined but unwired: the header band
  is a fixed fraction of the page. Learning per-layout coordinates needs real
  documents to calibrate against, and a fixed band that works is better than a
  learned one that was never measured.
- **Durable job state.** `JobRegistry` is in memory; a restart forgets the queue.
- **Code format inference.** Captured codes are validated for shape, not against a
  learned corpus pattern. That needs a real corpus.
