import logging
from pathlib import Path
from typing import Optional, Type

from adapters.base import BaseAdapter
from adapters.off_adapter import OFFAdapter
from builders.search_document_builder import SearchDocumentBuilder
from config.settings import settings
from models.search_document import SearchDocument
from pipeline.load import write_normalized_parquet_batch
from search.indexer import index_products

logger = logging.getLogger(__name__)


def run_pipeline(
    data_path: str | None = None,
    adapter_class: Type[BaseAdapter] = OFFAdapter,
    builder: Optional[SearchDocumentBuilder] = None,
    limit: Optional[int] = None,
    index_to_opensearch: bool = True,
) -> Path:
    logger.info("Initializing adapter and builder...")
    try:
        adapter = adapter_class(data_path) if data_path is not None else adapter_class()
    except TypeError:
        adapter = adapter_class()
    active_builder = builder or SearchDocumentBuilder()

    logger.info("Streaming and transforming raw products...")
    batch: list[SearchDocument] = []
    total_indexed = 0
    writer = None
    output_path = settings.processed_dir / "normalized.parquet"

    for raw_product in adapter.extract_raw_products(limit=limit):
        doc = active_builder.build(raw_product)

        batch.append(doc)
        if len(batch) >= settings.pipeline_batch_size:
            if index_to_opensearch:
                total_indexed += index_products(batch)
            output_path, writer = write_normalized_parquet_batch(batch, writer)
            batch = []

    if batch:
        if index_to_opensearch:
            total_indexed += index_products(batch)
        output_path, writer = write_normalized_parquet_batch(batch, writer)

    if writer is not None:
        writer.close()

    logger.info("Indexed %d search documents to OpenSearch", total_indexed)

    logger.info("Pipeline complete. Output: %s", output_path)
    return output_path

