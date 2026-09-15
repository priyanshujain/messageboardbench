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
    inv2 = (MOD + 1) // 2  # 499122177
    # Expected value E_K = ((N+1) - (N-1)*((N-2)/N)^K)/2
    # Compute modulo MOD.
    # For N=1 the second term vanishes (N-1=0), result is 1.
    n_mod = N % MOD
    n_plus_1 = (N + 1) % MOD
    n_minus_1 = (N - 1) % MOD
    inv_n = pow(n_mod, MOD - 2, MOD)
    r = (N - 2) % MOD * inv_n % MOD
    term = pow(r, K, MOD)
    res = (n_plus_1 - n_minus_1 * term) % MOD
    res = res * inv2 % MOD
    return res