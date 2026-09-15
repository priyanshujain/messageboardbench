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
    if N == 1:
        return 1
    # Probability a single operation touches the black ball's position:
    # 2(N-1) / (N*(N-1)) = 2/N (ordered pairs (a, b) with a or b equal to p).
    inv_n = pow(N, MOD - 2, MOD)
    # Probability the black ball is never swapped during K operations.
    never = pow((1 - 2 * inv_n) % MOD, K, MOD)
    # If never moved: stays at position 1.
    # Otherwise its position is uniform on 1..N, expectation (N+1)/2.
    half = pow(2, MOD - 2, MOD)
    return (never + (1 - never) * ((N + 1) % MOD) % MOD * half) % MOD