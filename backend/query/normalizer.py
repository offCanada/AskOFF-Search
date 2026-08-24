import re


class QueryNormalizer:
    # Common typo dictionary for nutrition terms and common product keywords
    TYPO_CORRECTIONS = {
        r"\bprotien\b": "protein",
        r"\bprotiens\b": "proteins",
        r"\bsugur\b": "sugar",
        r"\bsuagr\b": "sugar",
        r"\bsugurs\b": "sugars",
        r"\bsuagrs\b": "sugars",
        r"\bcalroies\b": "calories",
        r"\bcaloires\b": "calories",
        r"\bcaloire\b": "calories",
        r"\bsoidum\b": "sodium",
        r"\bdrniks\b": "drinks",
        r"\bdrnk\b": "drinks",
    }

    @staticmethod
    def normalize(query: str) -> str:
        if not query:
            return ""
        normalized = query.lower()

        # Fix common constraint keyword typos before stripping punctuation
        for pattern, replacement in QueryNormalizer.TYPO_CORRECTIONS.items():
            normalized = re.sub(pattern, replacement, normalized)

        # Space out comparison operators like '<= 300' vs '<=300'
        normalized = re.sub(r"([<>]=?|==|=)\s*", r" \1 ", normalized)

        # Keep comparison operators, decimal points, and percentages. They carry
        # product identity ("2% milk") and nutrition-constraint semantics
        # ("protein >= 20g") that the constraint extractor needs to inspect.
        normalized = re.sub(r"[^\w\s\-<>=%\.]", "", normalized)

        # Collapse multiple spaces and trim edges
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized
