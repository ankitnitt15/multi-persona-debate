from limits import rate_limiter


def test_user_cap_allows_up_to_the_limit_then_blocks():
    allowed, count = rate_limiter.check_user_cap("user-1", daily_cap=2)
    assert allowed and count == 0

    rate_limiter.record_user_usage("user-1")
    allowed, count = rate_limiter.check_user_cap("user-1", daily_cap=2)
    assert allowed and count == 1

    rate_limiter.record_user_usage("user-1")
    allowed, count = rate_limiter.check_user_cap("user-1", daily_cap=2)
    assert not allowed and count == 2


def test_user_caps_are_independent_per_user():
    rate_limiter.record_user_usage("user-a")
    rate_limiter.record_user_usage("user-a")

    allowed, count = rate_limiter.check_user_cap("user-b", daily_cap=2)

    assert allowed and count == 0


def test_global_cap_allows_up_to_the_limit_then_blocks():
    allowed, count = rate_limiter.check_global_cap(daily_cap=5)
    assert allowed and count == 0

    rate_limiter.record_global_usage(3)
    allowed, count = rate_limiter.check_global_cap(daily_cap=5)
    assert allowed and count == 3

    rate_limiter.record_global_usage(3)  # pushes total to 6, over the cap of 5
    allowed, count = rate_limiter.check_global_cap(daily_cap=5)
    assert not allowed and count == 6
