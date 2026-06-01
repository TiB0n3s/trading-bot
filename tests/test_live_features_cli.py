import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live_features import collection_exit_code


def test_collection_exit_code_succeeds_when_all_symbols_succeed():
    assert collection_exit_code(success=59, failed=0) == 0


def test_collection_exit_code_succeeds_on_partial_symbol_failures():
    assert collection_exit_code(success=58, failed=1) == 0


def test_collection_exit_code_fails_when_no_symbols_succeed():
    assert collection_exit_code(success=0, failed=59) == 1
