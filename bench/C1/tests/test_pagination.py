
import pytest

from pagination import page_count

def test_exact_multiple():
    assert page_count(10, 5) == 2

def test_zero_items():
    assert page_count(0, 10) == 0

def test_last_page_boundary():
    # 11 items at 5 per page -> 3 pages (5 + 5 + 1)
    assert page_count(11, 5) == 3

def test_single_item():
    assert page_count(1, 10) == 1

def test_large_numbers():
    assert page_count(1_000_001, 100) == 10_001

def test_invalid_page_size():
    with pytest.raises(ValueError):
        page_count(10, 0)
