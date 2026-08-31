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

## Layout

```
backend/
  src/resolutions/
    domain/       pure rules, zero dependencies  (anchor, extraction, scoring,
                  grouping, title, naming)
    application/  use cases and ports            (pipeline, process_document, inventory)
    adapters/     one vendor each                (PyMuPDF, Tesseract, Claude, files)
    api/          FastAPI, worker pool, SSE
  tests/          162 tests, domain runs in ~0.5s
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
pytest                                   # 162 tests
uvicorn resolutions.api.main:app --port 8000
```

### Front end

```bash
cd web
npm install
npm run dev                              # http://localhost:5173
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so everything is
same-origin and CORS never comes into it.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | enables the L4 rung; without it, escalations go to review |
| `RESOLUTIONS_DOCUMENT_WORKERS` | cores − 1 | PDFs processed in parallel (one process each) |
| `RESOLUTIONS_PAGE_WORKERS` | 8 | threads fanning pages across OCR inside a worker |
| `RESOLUTIONS_QUEUE_LIMIT` | 500 | documents in flight before the API returns 429 |
| `RESOLUTIONS_OCR_LANG` | `spa` | Tesseract language |
| `RESOLUTIONS_TESSERACT_CMD` | from `PATH` | full path to `tesseract.exe` when it is not on `PATH` |
| `RESOLUTIONS_MOSAIC_SIZE` | 12 | crops per vision request |
| `RESOLUTIONS_DATA_DIR` | `./data` | uploads and outputs |

## Not built yet

- **ROI learning.** The `RoiRegistry` port is defined but unwired: the header band
  is a fixed fraction of the page. Learning per-layout coordinates needs real
  documents to calibrate against, and a fixed band that works is better than a
  learned one that was never measured.
- **Durable job state.** `JobRegistry` is in memory; a restart forgets the queue.
- **Code format inference.** Captured codes are validated for shape, not against a
  learned corpus pattern. That needs a real corpus.
