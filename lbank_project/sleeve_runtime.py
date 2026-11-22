"""Shared polling loop for the two four-hour trading sleeves."""

import time

FOUR_HOUR_SECONDS = 4 * 3600
CANDLE_CLOSE_DELAY_SECONDS = 3


def run_sleeve_loop(sleeve, config_path, load_config, logger, name, *, stop=None, once=False):
    """Reload settings and retry unprocessed candles without resetting sleeve state."""
    last_processed_boundary = None
    while stop is None or not stop.is_set():
        try:
            try:
                sleeve.c = load_config(config_path)
            except Exception:
                logger.exception('%s config unreadable; keeping previous settings', name)

            now = time.time()
            boundary = int(now) // FOUR_HOUR_SECONDS * FOUR_HOUR_SECONDS
            candle_ready = now >= boundary + CANDLE_CLOSE_DELAY_SECONDS
            if candle_ready and boundary != last_processed_boundary:
                if sleeve.scan(now):
                    last_processed_boundary = boundary
            else:
                sleeve.watchdog(now)
        except Exception:
            logger.exception('%s cycle failed; will retry', name)

        if once:
            break
        wait = stop.wait if stop is not None else time.sleep
        wait(sleeve.c['check_interval_seconds'])
