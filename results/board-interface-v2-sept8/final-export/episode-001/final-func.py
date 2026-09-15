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
        """Count beautiful integers in [1, n]."""
        if n <= 0:
            return 0
        digits = list(map(int, str(n)))
        L = len(digits)
        from functools import lru_cache

        @lru_cache(maxsize=None)
        def dp(pos: int, diff: int, rem: int, tight: bool, started: bool) -> int:
            if pos == L:
                # Beautiful iff we actually formed a number with equal even/odd
                # digit counts and divisible by k.
                if started and diff == 0 and rem == 0:
                    return 1
                return 0
            limit = digits[pos] if tight else 9
            total = 0
            for d in range(0, limit + 1):
                ntight = tight and (d == limit)
                if not started and d == 0:
                    # leading zero, number not started yet
                    total += dp(pos + 1, diff, rem, ntight, False)
                else:
                    ndiff = diff + (1 if d % 2 == 0 else -1)
                    nrem = (rem * 10 + d) % k
                    total += dp(pos + 1, ndiff, nrem, ntight, True)
            return total

        return dp(0, 0, 0, True, False)

    return count_upto(high) - count_upto(low - 1)
