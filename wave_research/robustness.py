import numpy as np


def block_bootstrap(returns, draws, block_days, seed):
    rng = np.random.default_rng(seed)
    output = []
    blocks = (len(returns) + block_days - 1) // block_days
    for i in range(0, draws, 256):
        starts = rng.integers(0, len(returns), (min(256, draws-i), blocks, 1))
        idx = (starts + np.arange(block_days)) % len(returns)
        paths = np.cumprod(1 + returns[idx.reshape(len(starts), -1)[:, :len(returns)]], axis=1)
        peak = np.maximum.accumulate(np.c_[np.ones(len(paths)), paths], axis=1)[:, 1:]
        output.append(np.column_stack((100*(paths[:, -1]-1), 100*(1-paths/peak).max(axis=1))))
    return np.concatenate(output)
