def expected_black_ball_position(N: int, K: int) -> int:
    """ There are N-1 white balls and one black ball arranged in a row, with the black ball
    initially at the leftmost position. Takahashi performs K operations, where each operation
    consists of:
    - Choose two integers a and b uniformly at random between 1 and N, inclusive
    - If a ≠ b, swap the a-th and b-th balls from the left

    Find the expected position of the black ball after K operations, modulo 998244353.

    The result is returned as an integer R where R × Q ≡ P (mod 998244353), where P/Q is
    the expected value expressed as an irreducible fraction.

    Args:
        N: Total number of balls (1 ≤ N ≤ 998244352)
        K: Number of operations (1 ≤ K ≤ 10^5)

    Returns:
        The expected position modulo 998244353

    >>> expected_black_ball_position(2, 1)
    499122178
    >>> expected_black_ball_position(3, 2)
    554580198
    >>> expected_black_ball_position(4, 4)
    592707587
    """
    MOD = 998244353

    # Recurrence: with probability p = 2(N-1)/N^2 the black ball moves to a
    # uniformly random other position, otherwise it stays.
    #   E_{k+1} = (1 - p) E_k + p * (S - E_k)/(N-1),  S = N(N+1)/2
    #         = (1 - 2/N) E_k + (N+1)/N
    # Fixed point E* = (N+1)/2, so
    #   E_K = (N+1)/2 - (N-1)/2 * (1 - 2/N)^K
    inv2 = pow(2, MOD - 2, MOD)
    invN = pow(N % MOD, MOD - 2, MOD)

    base = (1 - 2 * invN) % MOD
    ans = (N + 1) % MOD * inv2 % MOD
    ans = (ans - (N - 1) % MOD * inv2 % MOD * pow(base, K, MOD)) % MOD
    return ans % MOD
