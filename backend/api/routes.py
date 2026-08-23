import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse

from config.settings import settings
from models.search import SearchResponse
from models.search_document import SearchDocument
from retrieval.search_engine import SearchEngine

from .dependencies import get_search_engine

router = APIRouter()
logger = logging.getLogger(__name__)


def _search_backend_status(engine: SearchEngine) -> tuple[bool, int, str]:
    """Return readiness without exposing transport details to API clients."""
    client = getattr(engine.repository, "client", None)
    if client is None or not client.ping():
        return False, 0, "opensearch_unavailable"
    from config.settings import settings

    if not client.indices.exists(index=settings.opensearch_index):
        return False, 0, "index_missing"
    document_count = int(client.count(index=settings.opensearch_index).get("count", 0))
    if document_count == 0:
        return False, 0, "index_empty"
    health = client.cluster.health(index=settings.opensearch_index).get("status", "red")
    if health == "red":
        return False, document_count, "index_red"
    return True, document_count, "ready"


@router.get("/")
async def root(engine: SearchEngine = Depends(get_search_engine)):
    try:
        opensearch_connected, doc_count, _ = _search_backend_status(engine)
    except Exception:
        logger.warning("root_status_check_failed", exc_info=True)
        opensearch_connected, doc_count = False, 0

    return {
        "status": "ok",
        "service": "AskOFF Search API V2 (Search Platform)",
        "version": "0.2.0",
        "opensearch_connected": opensearch_connected,
        "document_count": doc_count
    }


@router.get("/health")
async def health():
    """Liveness probe: the API process is accepting requests."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness(engine: SearchEngine = Depends(get_search_engine)):
    """Readiness probe: serving index is reachable and has been opened."""
    try:
        connected, document_count, reason = _search_backend_status(engine)
    except Exception:
        logger.warning("readiness_check_failed", exc_info=True)
        connected, document_count, reason = False, 0, "dependency_check_failed"

    payload = {
        "status": "ready" if connected else "not_ready",
        "opensearch_connected": connected,
        "document_count": document_count,
        "reason": reason,
    }
    return JSONResponse(status_code=200 if connected else 503, content=payload)



@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, max_length=settings.request_max_query_length),
    size: int = Query(20, ge=1, le=settings.request_max_page_size),
    from_: int = Query(0, ge=0, le=settings.request_max_offset, alias="from"),
    brand: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    is_organic: Optional[bool] = Query(None),
    is_vegan: Optional[bool] = Query(None),
    is_vegetarian: Optional[bool] = Query(None),
    explain: bool = Query(False),
    engine: SearchEngine = Depends(get_search_engine),
):
    filters = {}
    if brand is not None:
        filters["brand"] = brand
    if category is not None:
        filters["category"] = category
    if is_organic is not None:
        filters["organic"] = is_organic
    if is_vegan is not None:
        filters["vegan"] = is_vegan
    if is_vegetarian is not None:
        filters["vegetarian"] = is_vegetarian

    return engine.search(
        query=q,
        filters=filters if filters else None,
        size=size,
        from_=from_,
        explain=explain,
    )


@router.get("/product/{id}", response_model=SearchDocument)
async def get_product(
    id: str = Path(..., min_length=1, max_length=settings.request_max_query_length),
    engine: SearchEngine = Depends(get_search_engine),
):
    product = engine.get_product(id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get("/brand/{brand}", response_model=SearchResponse)
async def search_brand(
    brand: str = Path(..., min_length=1, max_length=settings.request_max_query_length),
    size: int = Query(20, ge=1, le=settings.request_max_page_size),
    engine: SearchEngine = Depends(get_search_engine),
):
    return engine.search(query="", filters={"brand": brand}, size=size)


@router.get("/category/{category}", response_model=SearchResponse)
async def search_category(
    category: str = Path(..., min_length=1, max_length=settings.request_max_query_length),
    size: int = Query(20, ge=1, le=settings.request_max_page_size),
    engine: SearchEngine = Depends(get_search_engine),
):
    return engine.search(query="", filters={"category": category}, size=size)


@router.get("/ingredient/{ingredient}", response_model=SearchResponse)
async def search_ingredient(
    ingredient: str = Path(..., min_length=1, max_length=settings.request_max_query_length),
    size: int = Query(20, ge=1, le=settings.request_max_page_size),
    engine: SearchEngine = Depends(get_search_engine),
):
    return engine.search(query="", filters={"ingredients": ingredient}, size=size)


@router.get("/autocomplete")
async def autocomplete(
    q: str = Query(..., min_length=1, max_length=settings.request_max_query_length),
    size: int = Query(5, ge=1, le=20),
    engine: SearchEngine = Depends(get_search_engine),
):
    return engine.autocomplete(query=q, size=size)


@router.get("/suggestions")
async def suggestions(
    q: str = Query(..., min_length=1, max_length=settings.request_max_query_length),
    engine: SearchEngine = Depends(get_search_engine),
):
    completions = engine.autocomplete(query=q, size=5)
    return {"suggestions": completions}


@router.get("/compare")
async def compare(
    ids: List[str] = Query(..., min_length=1, max_length=settings.request_max_compare_ids),
    engine: SearchEngine = Depends(get_search_engine),
):
    results = []
    for doc_id in ids:
        doc = engine.get_product(doc_id)
        if doc:
            results.append(doc)
    return results


# ==========================================
# Legacy Aliases for Backwards Compatibility
# ==========================================


@router.get("/products/{barcode}", response_model=SearchDocument)
async def legacy_get_product(
    barcode: str = Path(..., min_length=1, max_length=settings.request_max_query_length),
    engine: SearchEngine = Depends(get_search_engine),
):
    return await get_product(id=barcode, engine=engine)


@router.get("/brands/{brand}", response_model=SearchResponse)
async def legacy_search_brand(
    brand: str = Path(..., min_length=1, max_length=settings.request_max_query_length),
    size: int = Query(20, ge=1, le=settings.request_max_page_size),
    engine: SearchEngine = Depends(get_search_engine),
):
    return await search_brand(brand=brand, size=size, engine=engine)


@router.get("/categories/{category}", response_model=SearchResponse)
async def legacy_search_category(
    category: str = Path(..., min_length=1, max_length=settings.request_max_query_length),
    size: int = Query(20, ge=1, le=settings.request_max_page_size),
    engine: SearchEngine = Depends(get_search_engine),
):
    return await search_category(category=category, size=size, engine=engine)

