from __future__ import annotations

from pathlib import Path


def process_document_job(payload: dict) -> dict:
    """Process one PDF. Runs inside a worker process, so it must stay picklable.

    Adapters are imported here rather than at module scope: the API process has
    no business loading MuPDF or Tesseract just to accept an upload.
    """
    from ..adapters.claude_vision import (
        ClaudeVisionConfig,
        ClaudeVisionOracle,
        NullVisionOracle,
    )
    from ..adapters.file_inventory import FileInventoryStore
    from ..adapters.pymupdf_assembler import PyMuPDFAssembler
    from ..adapters.pymupdf_source import PyMuPDFDocumentStore
    from ..adapters.queue_progress import QueueProgressReporter
    from ..adapters.tesseract_ocr import HeaderAndPageOcr
    from ..application.pipeline import ClassificationPipeline, PipelineConfig
    from ..application.process_document import ProcessDocument
    from ..application.progress import NullProgressReporter

    settings = payload["settings"]
    source = Path(payload["source"])
    destination = Path(settings["output_dir"]) / payload["job_id"]

    queue = payload.get("progress_queue")
    progress = (
        QueueProgressReporter(queue, payload["job_id"]) if queue is not None
        else NullProgressReporter()
    )

    api_key = settings.get("anthropic_api_key")
    if api_key:
        from anthropic import Anthropic

        vision = ClaudeVisionOracle(
            client=Anthropic(api_key=api_key),
            config=ClaudeVisionConfig(model=settings["vision_model"]),
        )
    else:
        vision = NullVisionOracle()

    pipeline = ClassificationPipeline(
        ocr=HeaderAndPageOcr(language=settings["ocr_language"]),
        vision=vision,
        config=PipelineConfig(
            max_workers=settings["page_workers"],
            mosaic_size=settings["mosaic_size"],
        ),
        progress=progress,
    )

    try:
        from ..adapters.excel_inventory import ExcelInventory

        sheets = ExcelInventory()
    except ImportError:
        # openpyxl is not installed: the document still gets split, it just
        # ships without its spreadsheet.
        sheets = None

    use_case = ProcessDocument(
        store=PyMuPDFDocumentStore(),
        pipeline=pipeline,
        assembler=PyMuPDFAssembler(),
        inventory=FileInventoryStore(),
        progress=progress,
        sheets=sheets,
    )
    return use_case.execute(
        source,
        destination,
        source_name=payload.get("filename"),
        operator=payload.get("operator"),
    ).as_dict()
