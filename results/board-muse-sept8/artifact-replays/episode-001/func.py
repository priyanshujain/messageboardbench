def count_beautiful_integers(low: int, high: int, k: int) -> int:
    """ Count the number of beautiful integers in the range [low, high].
    
    A number is beautiful if it meets both conditions:
    1. The count of even digits equals the count of odd digits
    2. The number is divisible by k
    
    Args:
        low: Lower bound of the range (inclusive), 0 < low <= high <= 10^9
        high: Upper bound of the range (inclusive)
        k: Divisor to check, 0 < k <= 20
    
    Returns:
        The count of beautiful integers in the given range
    
    >>> count_beautiful_integers(10, 20, 3)
    2
    >>> count_beautiful_integers(1, 10, 1)
    1
    >>> count_beautiful_integers(5, 5, 2)
    0
    """
    from functools import lru_cache

    def count_upto(n: int) -> int:
        if n <= 0:
            return 0
        s = str(n)
        digits = list(map(int, s))
        L = len(digits)

        @lru_cache(maxsize=None)
        def dfs(pos: int, diff: int, rem: int, tight: bool, started: bool) -> int:
            # diff = (#even digits so far) - (#odd digits so far), offset handling via value
            # only meaningful when started; when not started diff should be 0 and rem 0
            if pos == L:
                return 1 if (started and diff == 0 and rem == 0) else 0
            if tight:
                limit = digits[pos]
            else:
                limit = 9
            total = 0
            for d in range(limit + 1):
                ntight = tight and (d == limit)
                nstarted = started or (d != 0)
                if not nstarted:
                    total += dfs(pos + 1, 0, 0, ntight, False)
                else:
                    ndiff = diff + (1 if (d % 2 == 0) else -1)
                    nrem = (rem * 10 + d) % k
                    total += dfs(pos + 1, ndiff, nrem, ntight, True)
            return total

        return dfs(0, 0, 0, True, False)

    return count_upto(high) - count_upto(low - 1)