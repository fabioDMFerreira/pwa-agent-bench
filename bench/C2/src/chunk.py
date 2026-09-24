def chunk(items, size):
    """Split `items` into consecutive sub-lists of length `size`.

    See TASK.md for the exact spec.
    """
    if isinstance(size, bool) or not isinstance(size, int):
        raise TypeError(f"size must be an int, not {type(size).__name__}")
    if size <= 0:
        raise ValueError("size must be a positive integer")

    sentinel = object()
    it = iter(items)
    result = []
    while True:
        first = next(it, sentinel)
        if first is sentinel:
            break
        group = [first]
        for _ in range(size - 1):
            element = next(it, sentinel)
            if element is sentinel:
                break
            group.append(element)
        result.append(group)
    return result
