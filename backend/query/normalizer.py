import re


class QueryNormalizer:
    @staticmethod
    def normalize(query: str) -> str:
        if not query:
            return ""
        normalized = query.lower()
        # Keep comparison operators, decimal points, and percentages.  They carry
        # product identity ("2% milk") and nutrition-constraint semantics
        # ("protein >= 20g") that the constraint extractor needs to inspect.
        normalized = re.sub(r"[^\w\s\-<>=%\.]", "", normalized)
        # Collapse multiple spaces and trim edges
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized
