"""
Canadian-English synonym configuration for AskOFF search (P3).

Single source of truth: backend/search/synonyms_ca.txt

Every entry is evidenced against the live 114,453-document Canadian OFF dataset
(see backend/evaluation/pre_fix_audit.md Phase 2 evidence): each pair token and
its synonym co-occur in the dataset, so the conflation is safe and data-driven,
not an arbitrary blender.

Mechanics:
  - Index-side: mappings.py injects these pairs as an inline OpenSearch synonym
    filter on the canonical product search fields (product_name, brand, category,
    ingredients, search_text). A doc indexed with "soya" is token-expanded so a
    "soy" query (and vice versa) retrieves it.
  - Query-side: canonicalize() rewrites query text so both the DuckDB offline
    benchmark repo and entity extraction agree on the canonical form.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

SYNONYMS_FILE = Path(__file__).with_name("synonyms_ca.txt")


def load_synonym_pairs(path: Path = SYNONYMS_FILE) -> List[Tuple[str, str]]:
    """Parse the versioned file: 'soya, soy' per line; blank and '#' ignored."""
    pairs: List[Tuple[str, str]] = []
    if not path.exists():
        return pairs
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip().lower() for p in line.split(",") if p.strip()]
        if len(parts) == 2:
            pairs.append((parts[0], parts[1]))
    return pairs


def canonical_map(pairs: List[Tuple[str, str]] = None) -> Dict[str, str]:
    """Each variant -> canonical. The canonical head is the first token on the line,
    which follows dataset-observed dominance (soy over soya, yogurt over yoghurt)."""
    pairs = pairs if pairs is not None else load_synonym_pairs()
    mapping: Dict[str, str] = {}
    for a, b in pairs:
        head = a  # dataset-dominant / evidence-backed canonical form
        mapping[a] = head
        mapping[b] = head
    return mapping


def synonym_tokens(pairs: List[Tuple[str, str]] = None) -> List[str]:
    """OpenSearch synonym filter lines ('a, b') with expand-by-default behaviour."""
    pairs = pairs if pairs is not None else load_synonym_pairs()
    return [f"{a}, {b}" for a, b in pairs]


def synonym_variants(token: str, pairs: List[Tuple[str, str]] = None) -> List[str]:
    """All tokens a given token can expand to (synonyms + itself)."""
    pairs = pairs if pairs is not None else load_synonym_pairs()
    variants = [token]
    for a, b in pairs:
        if token == a:
            variants.append(b)
        elif token == b:
            variants.append(a)
    return sorted(set(variants))


def canonicalize(text: str, mapping: Dict[str, str] = None) -> str:
    """
    Rewrite query text using canonical synonyms (word-boundary aware).
    'soya sauce' -> 'soy sauce'; 'yoghurt' -> 'yogurt'. Returns the closest
    canonical form without touching non-synonym words.
    """
    if not text:
        return text
    mapping = mapping if mapping is not None else canonical_map()
    if not mapping:
        return text
    # Sort variants by length desc so 'yoghurt' is replaced before any prefix clash
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(v) for v in sorted(set(mapping), key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )
    return pattern.sub(lambda m: mapping[m.group(1).lower()], text)


if __name__ == "__main__":
    pairs = load_synonym_pairs()
    print(f"synonym pairs: {pairs}")
    print("canonical map:", canonical_map(pairs))
    print("filter tokens:", synonym_tokens(pairs))
    print("sample: 'compliments soya sauce' ->", canonicalize("compliments soya sauce"))
