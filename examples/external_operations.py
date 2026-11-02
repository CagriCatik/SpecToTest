"""Application operation added without changing the generator core."""
from tcg.runtime import CheckFailed


def expect_supply_at_least(bench, *, minimum):
    actual = bench.supply
    if actual < minimum:
        raise CheckFailed(f'supply: expected at least {minimum} V, actual {actual} V')
