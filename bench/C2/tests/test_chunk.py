
import pytest

from chunk import chunk

def test_even_split():
    assert chunk([1, 2, 3, 4, 5, 6], 2) == [[1, 2], [3, 4], [5, 6]]

def test_uneven_last_chunk():
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

def test_size_larger_than_input():
    assert chunk([1, 2], 5) == [[1, 2]]

def test_empty_input():
    assert chunk([], 3) == []

def test_size_of_one():
    assert chunk([1, 2, 3], 1) == [[1], [2], [3]]

def test_zero_size_raises():
    with pytest.raises(ValueError):
        chunk([1, 2, 3], 0)

def test_negative_size_raises():
    with pytest.raises(ValueError):
        chunk([1, 2, 3], -1)

def test_works_on_strings():
    assert chunk(["a", "b", "c", "d"], 2) == [["a", "b"], ["c", "d"]]

def test_does_not_mutate_input():
    items = [1, 2, 3, 4]
    chunk(items, 2)
    assert items == [1, 2, 3, 4]
