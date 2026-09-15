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
    def count_upto(n: int) -> int:
        if n <= 0:
            return 0
        s = str(n)
        L = len(s)
        from functools import lru_cache

        @lru_cache(maxsize=None)
        def dp(pos: int, bal: int, mod: int, tight: bool, started: bool) -> int:
            if pos == L:
                return 1 if (started and bal == 0 and mod == 0) else 0
            total = 0
            limit = int(s[pos]) if tight else 9
            for d in range(limit + 1):
                ntight = tight and (d == limit)
                if not started:
                    if d == 0:
                        total += dp(pos + 1, 0, 0, ntight, False)
                    else:
                        nbal = 1 if d % 2 == 0 else -1
                        total += dp(pos + 1, nbal, d % k, ntight, True)
                else:
                    nbal = bal + (1 if d % 2 == 0 else -1)
                    total += dp(pos + 1, nbal, (mod * 10 + d) % k, ntight, True)
            return total

        return dp(0, 0, 0, True, False)

    return count_upto(high) - count_upto(low - 1)
