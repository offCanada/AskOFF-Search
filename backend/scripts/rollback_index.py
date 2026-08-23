"""Atomically roll the serving alias back to a retained physical index."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search.client import get_client
from search.index_lifecycle import rollback_index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to-index", required=True)
    parser.add_argument("--alias", default=None)
    args = parser.parse_args()
    rollback_index(get_client(), args.to_index, args.alias)
    print(f"rolled_back_to={args.to_index}")


if __name__ == "__main__":
    main()
