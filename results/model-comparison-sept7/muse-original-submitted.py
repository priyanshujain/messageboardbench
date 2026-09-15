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

    def count_upto(x: int) -> int:
        if x <= 0:
            return 0
        s = str(x)
        digits = list(map(int, s))
        n = len(digits)

        @lru_cache(maxsize=None)
        def dfs(pos: int, tight: bool, started: bool, diff: int, mod: int) -> int:
            # diff = (#even digits so far) - (#odd digits so far), valid only if started
            # mod = value so far % k, valid only if started
            if pos == n:
                if started and diff == 0 and mod == 0:
                    return 1
                return 0
            limit = digits[pos] if tight else 9
            total = 0
            for d in range(limit + 1):
                ntight = tight and (d == limit and d == digits[pos])
                # Actually ntight should be tight and (d == digits[pos])
                # The above condition with limit is equivalent when tight,
                # but be precise:
                # (recompute for clarity)
                # ntight = tight and (d == digits[pos])
                nstarted = started or (d != 0)
                if not nstarted:
                    total += dfs(pos + 1, ntight, False, 0, 0)
                else:
                    ndiff = diff + (1 if (d % 2 == 0) else -1)
                    nmod = (mod * 10 + d) % k
                    total += dfs(pos + 1, ntight, True, ndiff, nmod)
            return total

        return dfs(0, True, False, 0, 0)

    return count_upto(high) - count_upto(low - 1)
