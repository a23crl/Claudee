import numpy as np

from analysis import montecarlo


def test_all_wins_never_breaches_and_eventually_passes():
    # every day nets +$1,000; profit target $3,000 reached in 3 days, no losses ever
    daily_pnls = np.array([1000.0] * 30)
    result = montecarlo.prop_monte_carlo(
        daily_pnls,
        account_size=50000,
        profit_target=3000,
        trailing_dd=2000,
        dd_type="EOD",
        daily_loss_limit=1000,
        consistency_pct=100,  # no consistency constraint for this sanity check
        n_paths=200,
        seed=1,
    )
    assert result["pass_rate"] == 1.0
    assert result["breach_rate"] == 0.0


def test_single_large_loss_breaches_trailing_drawdown_immediately():
    daily_pnls = np.array([-5000.0] * 30)
    result = montecarlo.prop_monte_carlo(
        daily_pnls,
        account_size=50000,
        profit_target=3000,
        trailing_dd=2000,
        dd_type="EOD",
        daily_loss_limit=10000,  # loosen so the trailing-DD check is what fires
        consistency_pct=100,
        n_paths=50,
        seed=2,
    )
    assert result["breach_rate"] == 1.0
    assert result["pass_rate"] == 0.0


def test_daily_loss_limit_breaches_before_drawdown_when_tighter():
    daily_pnls = np.array([-500.0] * 30)
    result = montecarlo.prop_monte_carlo(
        daily_pnls,
        account_size=50000,
        profit_target=3000,
        trailing_dd=100000,  # effectively disabled
        dd_type="EOD",
        daily_loss_limit=400,
        consistency_pct=100,
        n_paths=50,
        seed=3,
    )
    assert result["breach_rate"] == 1.0
    # breaches on day 1 every time
    assert (result["paths"]["days"] == 1).all()


def test_consistency_rule_blocks_a_pass_dominated_by_one_day():
    # One huge day (2900) plus fifty +10 days, cycled with a fixed block
    # length equal to the array length so every 51-day window contains
    # exactly one occurrence of the big day, wherever it starts. Over 60
    # days at most two occurrences of 2900 are possible, so the best
    # achievable total is 2*2900 + 58*10 = 6380 -- short of the 2900/0.30 =
    # 9,667 needed to bring the big day's share of profit under 30%, so a
    # strict consistency rule must always block the pass, regardless of the
    # random rotation start. A lenient rule (100%, i.e. no real constraint)
    # must always pass, since the full 51-day cycle alone sums to 3,400 >
    # the $3,000 target.
    daily_pnls = np.array([2900.0] + [10.0] * 50)
    common = dict(
        account_size=50000,
        profit_target=3000,
        trailing_dd=100000,
        dd_type="EOD",
        daily_loss_limit=100000,
        n_paths=20,
        block_len=(51, 51),
        max_days=60,
        seed=4,
    )
    strict = montecarlo.prop_monte_carlo(daily_pnls, consistency_pct=30, **common)
    lenient = montecarlo.prop_monte_carlo(daily_pnls, consistency_pct=100, **common)

    assert strict["pass_rate"] == 0.0
    assert lenient["pass_rate"] == 1.0
