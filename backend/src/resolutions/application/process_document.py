from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..domain.grouping import GroupingEngine, GroupingResult
from ..domain.page import PageClassification
from .inventory import Inventory, build_inventory
from .pipeline import ClassificationPipeline, PipelineStats
from .ports import DocumentAssembler, DocumentStore, InventoryStore
from .progress import NullProgressReporter, ProgressEvent, ProgressReporter, Stage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """A page the machine refuses to guess at."""

    page_number: int
    reason: str


@dataclass(frozen=True, slots=True)
class ProcessingReport:
    document: Path
    page_count: int
    grouping: GroupingResult
    classifications: list[PageClassification]
    #: What the operator called the file, which is not what it is stored as.
    #: Uploads land on disk under a generated name; an inventory recording that
    #: name cannot answer which document a resolution came from.
    document_name: str | None = None
    outputs: list[Path] = field(default_factory=list)
    review_queue: list[ReviewItem] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)
    inventory: Inventory | None = None
    inventory_path: Path | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "document": self.document_name or self.document.name,
            "page_count": self.page_count,
            "groups": [
                {
                    "code": group.code.value,
                    "title": group.title,
                    "pages": group.page_numbers,
                    "size": group.size,
                }
                for group in self.grouping.groups
            ],
            "quarantine": self.grouping.quarantine,
            "repairs": [
                {
                    "page": repair.page_number,
                    "observed": repair.observed.value,
                    "applied": repair.applied.value,
                    "distance": repair.distance,
                }
                for repair in self.grouping.repairs
            ],
            "review_queue": [
                {"page": item.page_number, "reason": item.reason} for item in self.review_queue
            ],
            "outputs": [path.name for path in self.outputs],
            "stats": self.stats,
            "inventory": self.inventory.as_dict() if self.inventory else None,
        }


class ProcessDocument:
    """Read a PDF, decide who owns every page, and write one file per resolution."""

    def __init__(
        self,
        store: DocumentStore,
        pipeline: ClassificationPipeline,
        assembler: DocumentAssembler,
        grouping: GroupingEngine | None = None,
        inventory: InventoryStore | None = None,
        progress: ProgressReporter | None = None,
        sheets: object | None = None,
    ) -> None:
        self._store = store
        self._pipeline = pipeline
        self._assembler = assembler
        self._grouping = grouping or GroupingEngine()
        self._inventory = inventory
        self._progress = progress or NullProgressReporter()
        #: Writes the per-document delivery note. Optional: a missing spreadsheet
        #: library must not stop a document from being split.
        self._sheets = sheets

    def execute(
        self,
        document: Path,
        destination: Path,
        source_name: str | None = None,
        operator: str | None = None,
    ) -> ProcessingReport:
        """Split ``document`` into ``destination``.

        ``source_name`` is what the operator called the file. Uploads land on
        disk under a generated name, and an inventory that records that name
        instead of theirs cannot answer the only question it exists for: which
        document did this resolution come from.
        """
        name = source_name or document.name
        source = self._store.open(document)
        try:
            classifications, stats = self._pipeline.classify(source)

            self._report(ProgressEvent(stage=Stage.GROUPING, page_count=source.page_count))
            result = self._grouping.group(classifications)

            # Nothing is written until the page accounting balances. A partial
            # split is the one failure mode nobody would catch by eye.
            result.verify_integrity(total_pages=source.page_count)

            self._report(
                ProgressEvent(stage=Stage.ASSEMBLING, page_count=len(result.groups))
            )
            assembly = self._assembler.write(document, result, destination)
            outputs = list(assembly.outputs)
            review_queue = self._build_review_queue(
                classifications, result, stats, assembly.unwritable_pages
            )

            inventory = build_inventory(
                source_document=name,
                source_pages=source.page_count,
                result=result,
                review_pages=[item.page_number for item in review_queue],
                stats=self._describe(stats),
                file_names=assembly.written,
            )
            inventory_path = (
                self._inventory.write(inventory, destination) if self._inventory else None
            )

            report = ProcessingReport(
                document=document,
                document_name=name,
                page_count=source.page_count,
                grouping=result,
                classifications=classifications,
                outputs=outputs,
                review_queue=review_queue,
                stats=self._describe(stats),
                inventory=inventory,
                inventory_path=inventory_path,
            )
            # The delivery note, written beside the PDFs it describes. It needs
            # the finished report -- the page reconciliation, the review queue,
            # the cascade histogram -- so it is written here and not by the
            # inventory store, which only sees the item list.
            if self._sheets is not None:
                try:
                    self._sheets.write(
                        report.as_dict(),
                        destination,
                        operator=operator,
                        processed_at=datetime.now(UTC).isoformat(),
                    )
                except Exception:  # noqa: BLE001 - the split succeeded either way
                    logger.warning("could not write the inventory sheet", exc_info=True)

            self._report(ProgressEvent(stage=Stage.DONE, page_count=source.page_count))
            return report
        except Exception as error:  # noqa: BLE001 - re-raised after reporting
            self._report(
                ProgressEvent(
                    stage=Stage.FAILED,
                    failed=True,
                    detail=f"{type(error).__name__}: {error}",
                )
            )
            raise
        finally:
            source.close()

    def _report(self, event: ProgressEvent) -> None:
        try:
            self._progress.emit(event)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _build_review_queue(
        classifications: list[PageClassification],
        result: GroupingResult,
        stats: PipelineStats,
        unwritable_pages: dict[int, str] | None = None,
    ) -> list[ReviewItem]:
        # Reasons are shown to the operator verbatim, so they are written in the
        # language of the people who read them.
        quarantined = set(result.quarantine)
        items = [
            ReviewItem(page_number=page, reason="sin código de resolución antes de esta página")
            for page in result.quarantine
        ]
        items += [
            ReviewItem(page_number=page, reason=f"la página no pudo procesarse: {error}")
            for page, error in stats.failures.items()
            if page not in quarantined
        ]
        failed = set(stats.failures)
        items += [
            ReviewItem(
                page_number=page.page_number,
                reason="códigos de resolución en conflicto en la página",
            )
            for page in classifications
            if page.ambiguous and page.page_number not in quarantined and page.page_number not in failed
        ]
        # A page the writer could not copy is the one review reason the operator
        # cannot infer from the output: the file exists and simply has less in it.
        items += [
            ReviewItem(
                page_number=page,
                reason=f"la página no pudo copiarse al PDF de salida: {error}",
            )
            for page, error in (unwritable_pages or {}).items()
        ]
        return sorted(items, key=lambda item: item.page_number)

    @staticmethod
    def _describe(stats: PipelineStats) -> dict[str, object]:
        return stats.as_dict()
