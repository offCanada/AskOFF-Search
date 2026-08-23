"""Create an empty versioned physical index; it does not change the serving alias."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search.client import get_client
from search.index_lifecycle import create_index, new_versioned_index_name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", default=None)
    args = parser.parse_args()
    index_name = args.index or new_versioned_index_name()
    create_index(get_client(), index_name)
    print(index_name)


if __name__ == "__main__":
    main()
