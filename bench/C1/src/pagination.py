def page_count(total_items, page_size):
    """Return the number of pages needed to hold `total_items` at `page_size` per page.

    total_items >= 0, page_size >= 1 (ValueError otherwise for page_size).
    Inputs are Python ints; the result must be exact for arbitrarily large values.
    """
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    if total_items == 0:
        return 0
    return (total_items + page_size - 1) // page_size
