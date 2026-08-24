from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from models.search_document import SearchDocument


class SearchRepository(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        filters: Optional[dict] = None,
        numeric_filters: Optional[List[dict]] = None,
        modifiers: Optional[List[str]] = None,
        ranking_preferences: Optional[dict] = None,
        size: int = 20,
        from_: int = 0,
        explain: bool = False
    ) -> Tuple[int, List[Tuple[float, SearchDocument]], dict]:
        """
        Runs search and returns total count, list of (score, SearchDocument), and metadata dict.
        """
        pass

    @abstractmethod
    def get_by_id(self, doc_id: str) -> Optional[SearchDocument]:
        """
        Retrieves a document by its ID.
        """
        pass

    @abstractmethod
    def get_autocomplete(self, query: str, size: int = 5) -> List[str]:
        """
        Runs autocomplete prefix search and returns suggestion strings.
        """
        pass
