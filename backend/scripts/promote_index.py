"""Atomically point the serving alias at a validated physical index."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search.client import get_client
from search.index_lifecycle import promote_index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--alias", default=None)
    args = parser.parse_args()
    promote_index(get_client(), args.index, args.alias)
    print(f"promoted={args.index}")


if __name__ == "__main__":
    main()
