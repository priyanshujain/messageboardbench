from typing import List

MOD = 998244353


def _poly_mul(a, b, limit):
    """Multiply two coefficient lists mod MOD, truncated to degree <= limit,
    using Kronecker substitution (packing into big integers)."""
    B = 128  # bits per slot; products < 2^60, sums of <= ~2001 terms < 2^71
    def pack(p):
        x = 0
        for i in range(len(p) - 1, -1, -1):
            x = (x << B) | p[i]
        return x
    prod = pack(a) * pack(b)
    mask = (1 << B) - 1
    res = []
    total = len(a) + len(b) - 1
    for i in range(min(total, limit + 1)):
        res.append((prod & mask) % MOD)
        prod >>= B
    return res


def count_valid_strings(K: int, C: List[int]) -> int:
    """ Count the number of strings consisting of uppercase English letters with length between 
    1 and K (inclusive) that satisfy the following condition: for each letter (A=0, B=1, ..., Z=25),
    the number of occurrences in the string is at most C[i].
    
    Return the count modulo 998244353.
    
    Args:
        K: Maximum length of strings to consider (1 <= K <= 1000)
        C: List of 26 integers where C[i] is the maximum allowed occurrences of the i-th letter
            (0 <= C[i] <= 1000)
    
    Returns:
        The number of valid strings modulo 998244353
    
    >>> count_valid_strings(2, [2, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    10
    >>> count_valid_strings(358, [1, 0, 1, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    64
    """
    # Precompute factorials and inverse factorials up to K
    fact = [1] * (K + 1)
    for i in range(1, K + 1):
        fact[i] = fact[i - 1] * i % MOD
    inv_fact = [1] * (K + 1)
    inv_fact[K] = pow(fact[K], MOD - 2, MOD)
    for i in range(K, 0, -1):
        inv_fact[i - 1] = inv_fact[i] * i % MOD

    # Exponential generating function: product over letters of
    # sum_{t=0}^{C[i]} x^t / t!, truncated at degree K.
    poly = [1]
    for c in C:
        c = min(c, K)
        if c == 0:
            continue
        letter_poly = [inv_fact[t] for t in range(c + 1)]
        poly = _poly_mul(poly, letter_poly, K)
        if len(poly) > K + 1:
            poly = poly[: K + 1]

    ans = 0
    for j in range(1, min(len(poly), K + 1)):
        ans = (ans + fact[j] * poly[j]) % MOD
    return ans
