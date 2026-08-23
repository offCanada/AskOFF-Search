"""Validate a physical index before it is eligible for promotion."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search.client import get_client
from search.index_lifecycle import validate_index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--expected-count", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(validate_index(get_client(), args.index, args.expected_count), sort_keys=True))


if __name__ == "__main__":
    main()
