"""Explicit private search rebuild. Does not generate or publish public HTML."""
import argparse
from kenradar.core.config import load_config
from kenradar.storage import create_database
from kenradar.storage.sqlite_search import rebuild


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    print({"indexed_content": rebuild(create_database(load_config(args.config))), "scope": "private_local_only"})


if __name__ == "__main__":
    main()
