import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.signal_generator import SignalGeneratorInterface
import logging

logging.basicConfig(filename='trading.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ORBStrategy(SignalGeneratorInterface):    
    def __init__(self, range_minutes=15, max_trades_per_day=3, candle_granularity: str = 'minute', opening_range_bars: int | None = None, external_candles: bool = False, stop_loss_pct=None, trailing_stop_pct=None, target_pct=None, require_boundary_touch: bool = True):
        self.external_candles = False  # force unified tick-based update usage for consistency
        self.candle_granularity = candle_granularity.lower()
        if self.candle_granularity not in ('minute', 'hour'):
            raise ValueError("candle_granularity must be 'minute' or 'hour'")
        # Opening range definition (bars-based now). Keep original range_minutes for backward compatibility (minute mode)
        if opening_range_bars is None:
            if self.candle_granularity == 'minute':
                opening_range_bars = range_minutes  # same behaviour as before
            else:
                opening_range_bars = 1  # one hour by default for hourly mode
        self.opening_range_bars = opening_range_bars
        # Preserve original attribute for external code relying on it (minute-specific semantics)
        self.range_minutes = range_minutes
        self.max_trades_per_day = max_trades_per_day
        # Opening range tracking
        self.range_high = None
        self.range_low = None
        self.orb_start = None
        self.orb_end = None
        self.open_range_completed = False
        # Pivot detection
        self.pivot_candle_time = None
        self.pivot_high = None
        self.pivot_low = None
        self.pivot_direction = None  # 'bull' or 'bear'
        self.entry_window_start = None  # time of candle immediately after pivot candle
        self.entry_taken = False  # retained for backward compatibility (first entry flag)
        self.in_entry_window = False  # controls eligibility for entries/re-entries
        # Logging / storage
        self.logger = logging.getLogger(__name__)
        self.last_candle_minute = None
        # Per-minute OHLC build (assumes caller supplies price per tick or per minute; we aggregate by minute here)
        self.current_minute = None
        self.minute_ohlc = None  # {'open','high','low','close','time'}
        # Daily control
        self.current_trade_day = None
        self.daily_trade_taken = False  # legacy flag (first trade) – still used for pivot freeze logic
        self.trades_taken_today = 0
        # Trailing stop state
        self.in_position = False
        self.stop_loss = None  # current trailing stop (price)
        self.prev_candle = None  # store last finalized candle for trail logic
        # Percentage-based risk management (optional). Accept either 0.x (fraction) or X (percent)
        def _norm(p):
            if p is None:
                return None
            try:
                v = float(p)
                if v == 0:
                    return 0.0
                # Revised normalization:
                #  - If 0 < v < 1 now treat as already a percent (0.5 => 0.5%) to avoid exploding small inputs.
                #  - If v >= 1 treat as percent directly (5 => 5%).
                # Backward compatibility: if user previously relied on 0.1 meaning 10%, they must now pass 10.
                if 0 < v < 1:
                    return v  # keep as sub-1 percent
                return v  # unchanged for >=1
            except Exception:
                return None
        self.stop_loss_pct = _norm(stop_loss_pct)  # stored in true percent units
        self.trailing_stop_pct = _norm(trailing_stop_pct)
        self.target_pct = _norm(target_pct)
        self.entry_price = None
        self.trailing_anchor = None  # highest high since entry (bull) or lowest low since entry (bear)
        self.target_price = None
        self.target_locked = False
        # Retouch logic: after a completed trade we must see price return fully inside original OR range
        # before allowing another breakout trade. This enforces: "IF take a trade again if the 15 candle range reached only".
        self.require_range_retouch = False  # when True we ignore outside-range closes until retouched
        # Pivot formation rule (if False, accept any close outside range even if candle didn't touch boundary)
        self.require_boundary_touch = require_boundary_touch
        self.logger.debug(f"ORBStrategy initialized with stop_loss_pct={self.stop_loss_pct}% trailing_stop_pct={self.trailing_stop_pct}%")

    def _finalize_minute(self):
        return self.minute_ohlc if self.minute_ohlc else None

    def _start_new_minute(self, dt, price):
        self.current_minute = dt.replace(second=0, microsecond=0)
        self.minute_ohlc = {
            'time': self.current_minute,
            'open': price,
            'high': price,
            'low': price,
            'close': price
        }

    def _update_minute(self, price):
        if not self.minute_ohlc:
            return
        self.minute_ohlc['high'] = max(self.minute_ohlc['high'], price)
        self.minute_ohlc['low'] = min(self.minute_ohlc['low'], price)
        self.minute_ohlc['close'] = price

    def reset(self):
        self.range_high = None
        self.range_low = None
        self.orb_start = None
        self.orb_end = None
        self.open_range_completed = False
        self.pivot_candle_time = None
        self.pivot_high = None
        self.pivot_low = None
        self.pivot_direction = None
        self.entry_window_start = None
        self.entry_taken = False
        self.in_entry_window = False
        self.current_minute = None
        self.minute_ohlc = None
        self.current_trade_day = None
        self.daily_trade_taken = False
        self.trades_taken_today = 0
        self.in_position = False
        self.stop_loss = None
        self.prev_candle = None
        self.require_range_retouch = False
        # Reset percentage risk fields (preserve configured pct values)
        self.entry_price = None
        self.trailing_anchor = None
        self.target_price = None
        self.target_locked = False

    def update(self, price, current_datetime):
        """Tick/stream update.
        If external_candles=True the caller SHOULD NOT call this per tick; instead call update_with_candle.
        Retained for backward compatibility.
        """
        # external_candles deprecated; always process via internal aggregation
        # Detect day change
        trade_day = current_datetime.date()
        if self.current_trade_day is None:
            self.current_trade_day = trade_day
        elif trade_day != self.current_trade_day:
            # New day: full reset except persistent config
            self.logger.info(f"New trading day detected: {trade_day}. Resetting ORB state.")
            self.reset()
            self.current_trade_day = trade_day
        # NOTE: We do NOT early-return after daily_trade_taken anymore because we must still
        # process candles for trailing stop and stop-loss exits. daily_trade_taken only blocks
        # creation of NEW entries (handled inside _on_minute_close logic now).

        # Build/roll minute candle
        # Generic bucketing by selected granularity
        if self.candle_granularity == 'minute':
            bucket_ts = current_datetime.replace(second=0, microsecond=0)
        else:  # hour
            bucket_ts = current_datetime.replace(minute=0, second=0, microsecond=0)

        if self.current_minute is None:
            self._start_new_minute(bucket_ts, price)
        elif bucket_ts != self.current_minute:
            finished = self._finalize_minute()
            self._start_new_minute(bucket_ts, price)
            if finished:
                return self._on_minute_close(finished)
        else:
            self._update_minute(price)
        return None

    # NEW: direct candle ingestion path (caller aggregated candles: e.g., from tick->1min/5min)
    def update_with_candle(self, candle_dt, candle):        
        # Day change detection
        trade_day = candle_dt.date()
        if self.current_trade_day is None:
            self.current_trade_day = trade_day
        elif trade_day != self.current_trade_day:
            self.logger.info(f"New trading day detected (external candles): {trade_day}. Resetting ORB state.")
            self.reset()
            self.current_trade_day = trade_day

        # For external candles treat each input candle as one bar for opening range counting.
        # We emulate previous time-based logic by deriving orb_end on first bar if not yet set.
        if self.orb_start is None:
            self.orb_start = candle_dt
            if self.candle_granularity == 'minute':
                self.orb_end = self.orb_start + pd.Timedelta(minutes=self.opening_range_bars)
            else:
                self.orb_end = self.orb_start + pd.Timedelta(hours=self.opening_range_bars)

        # While still collecting opening range
        if candle_dt < self.orb_end:
            self.range_high = max(self.range_high, candle['high']) if self.range_high is not None else candle['high']
            self.range_low = min(self.range_low, candle['low']) if self.range_low is not None else candle['low']
            return None

        if not self.open_range_completed:
            self.open_range_completed = True
            self.logger.info(f"(External) ORB range finalized at {candle_dt}: HIGH={self.range_high} LOW={self.range_low}")

        # Pivot detection (touch criteria) when allowed
        if (
            self.pivot_candle_time is None and
            self.trades_taken_today < self.max_trades_per_day and
            not self.require_range_retouch
        ):
            if candle['close'] > self.range_high and candle['low'] <= self.range_high:
                self.pivot_candle_time = candle_dt
                self.pivot_high = self.range_high
                self.pivot_low = self.range_low
                self.pivot_direction = 'bull'
                self.entry_window_start = candle_dt + pd.Timedelta(minutes=1)  # still wait one minute bar
                self.in_entry_window = True
                self.logger.info(f"(External) Bull pivot at {candle_dt}")
            elif candle['close'] < self.range_low and candle['high'] >= self.range_low:
                self.pivot_candle_time = candle_dt
                self.pivot_high = self.range_high
                self.pivot_low = self.range_low
                self.pivot_direction = 'bear'
                self.entry_window_start = candle_dt + pd.Timedelta(minutes=1)
                self.in_entry_window = True
                self.logger.info(f"(External) Bear pivot at {candle_dt}")
            return None

        # Entry logic triggers on first bar AFTER pivot bar
        if (
            self.in_entry_window and
            self.entry_window_start and
            candle_dt >= self.entry_window_start and
            (not self.in_position) and
            self.trades_taken_today < self.max_trades_per_day
        ):
            if self.pivot_direction == 'bull' and candle['high'] > self.pivot_high:
                self.entry_taken = True
                self.daily_trade_taken = True
                self.in_position = True
                self.trades_taken_today += 1
                self.stop_loss = self.pivot_low
                self.prev_candle = candle.copy()
                self.require_range_retouch = True
                self.in_entry_window = False
                return {'signal': 'buy', 'action': 'entry', 'pivot_high': self.pivot_high, 'pivot_low': self.pivot_low, 'pivot_time': self.pivot_candle_time, 'trade_number': self.trades_taken_today}
            if self.pivot_direction == 'bear' and candle['low'] < self.pivot_low:
                self.entry_taken = True
                self.daily_trade_taken = True
                self.in_position = True
                self.trades_taken_today += 1
                self.stop_loss = self.pivot_high
                self.prev_candle = candle.copy()
                self.require_range_retouch = True
                self.in_entry_window = False
                return {'signal': 'sell', 'action': 'entry', 'pivot_high': self.pivot_high, 'pivot_low': self.pivot_low, 'pivot_time': self.pivot_candle_time, 'trade_number': self.trades_taken_today}

        # Trailing / stop exit
        if self.in_position and self.prev_candle is not None:
            if self.pivot_direction == 'bull':
                if self.stop_loss is not None and candle['low'] <= self.stop_loss:
                    exit_sl = self.stop_loss
                    self.in_position = False
                    self.in_entry_window = False
                    return {'signal': 'sell', 'action': 'stop_exit', 'sl': exit_sl, 'pivot_time': self.pivot_candle_time, 'trade_number': self.trades_taken_today}
                candidate = self.prev_candle['low']
                if candidate is not None and candidate > (self.stop_loss or -float('inf')) and candidate < candle['low']:
                    self.stop_loss = candidate
            elif self.pivot_direction == 'bear':
                if self.stop_loss is not None and candle['high'] >= self.stop_loss:
                    exit_sl = self.stop_loss
                    self.in_position = False
                    self.in_entry_window = False
                    return {'signal': 'buy', 'action': 'stop_exit', 'sl': exit_sl, 'pivot_time': self.pivot_candle_time, 'trade_number': self.trades_taken_today}
                candidate = self.prev_candle['high']
                if candidate is not None and candidate < (self.stop_loss or float('inf')) and candidate > candle['high']:
                    self.stop_loss = candidate

        self.prev_candle = candle.copy()

        # Range retouch (external)
        if (not self.in_position) and self.require_range_retouch and self.open_range_completed:
            if candle['close'] <= self.range_high and candle['close'] >= self.range_low:
                self.pivot_candle_time = None
                self.pivot_high = None
                self.pivot_low = None
                self.pivot_direction = None
                self.entry_window_start = None
                self.in_entry_window = False
                self.require_range_retouch = False
        return None

    def _on_minute_close(self, candle):
        ct = candle['time']
        # Initialize ORB window start at first candle time if not set
        if self.orb_start is None:
            self.orb_start = ct
            # Determine ORB end based on number of opening range bars & granularity
            if self.candle_granularity == 'minute':
                self.orb_end = self.orb_start + pd.Timedelta(minutes=self.opening_range_bars)
            else:  # hour granularity
                self.orb_end = self.orb_start + pd.Timedelta(hours=self.opening_range_bars)

        # Still inside opening range collection
        if ct < self.orb_end:
            self.range_high = max(self.range_high, candle['high']) if self.range_high is not None else candle['high']
            self.range_low = min(self.range_low, candle['low']) if self.range_low is not None else candle['low']
            return None

        # Mark completion once
        if not self.open_range_completed:
            self.open_range_completed = True
            self.logger.info(f"ORB range finalized at {ct}: HIGH={self.range_high} LOW={self.range_low}")

    # If pivot not yet set, look for a pivot candle (close outside range) with boundary touch criteria
        # BUT if we are waiting for a retouch (price to come back inside range) skip new pivot detection
        if (
            self.pivot_candle_time is None and
            self.trades_taken_today < self.max_trades_per_day and
            not self.require_range_retouch
        ):
            # Refined breakout criteria:
            # Bull pivot requires: candle closes above range_high AND its low traded at/through the boundary (low <= range_high)
            # Bear pivot requires: candle closes below range_low  AND its high traded at/through the boundary (high >= range_low)
            # This filters out pure gap candles that never touch the opening range extremity.
            self.logger.debug(
                f"Pivot check {ct}: close={candle['close']} high={candle['high']} low={candle['low']} "
                f"range_high={self.range_high} range_low={self.range_low}"
            )
            if candle['close'] > self.range_high:
                if (not self.require_boundary_touch) or candle['low'] <= self.range_high:    
                    self.pivot_candle_time = ct
                    self.pivot_high = self.range_high
                    self.pivot_low = self.range_low
                    self.pivot_direction = 'bull'
                    self.entry_window_start = ct + pd.Timedelta(minutes=1)
                    self.in_entry_window = True
                    self.logger.info(
                        f"Bull pivot (touch) at {ct}: close {candle['close']} > range_high {self.range_high} and low {candle['low']} <= range_high"
                    )
            elif candle['close'] < self.range_low:
                if (not self.require_boundary_touch) or candle['high'] >= self.range_low:
                    self.pivot_candle_time = ct
                    self.pivot_high = self.range_high
                    self.pivot_low = self.range_low
                    self.pivot_direction = 'bear'
                    self.entry_window_start = ct + pd.Timedelta(minutes=1)
                    self.in_entry_window = True
                    self.logger.info(
                        f"Bear pivot (touch) at {ct}: close {candle['close']} < range_low {self.range_low} and high {candle['high']} >= range_low"
                    )
            # After detecting (or not) we return; entries still wait for next minute
            return None

        # Pivot already identified: wait for first minute AFTER pivot to trigger entry if breakout confirmed
        if (
            self.in_entry_window and
            self.entry_window_start and
            ct >= self.entry_window_start and
            (not self.in_position) and
            self.trades_taken_today < self.max_trades_per_day
        ):
            # We use THIS candle's price action relative to pivot extremes
            if self.pivot_direction == 'bull':
                # Entry if candle high reaches or exceeds pivot high (>= to avoid missing exact-touch cases)
                if candle['high'] >= self.pivot_high:
                    self.logger.debug(
                        f"LONG entry trigger {ct}: candle_high={candle['high']} pivot_high={self.pivot_high}"
                    )
                    self.entry_taken = True
                    self.daily_trade_taken = True  # legacy
                    self.in_position = True
                    self.trades_taken_today += 1
                    # Record entry price (approximate execution). Use pivot_high to simulate breakout fill.
                    self.entry_price = self.pivot_high if self.pivot_high is not None else candle['close']
                    # Base stop: pivot low
                    sl = self.pivot_low
                    # Override with percentage stop if configured
                    if self.stop_loss_pct is not None and self.entry_price is not None:
                        pct_stop = self.entry_price * (1 - self.stop_loss_pct / 100.0)
                        if pct_stop > sl:
                            sl = pct_stop
                    self.stop_loss = sl                    
                    
                    # Initialize trailing anchor for percentage trailing
                    self.trailing_anchor = candle['high']
                    # Initialize target for LONG
                    self.target_price = None
                    self.target_locked = False
                    if self.target_pct is not None and self.entry_price is not None:
                        try:
                            self.target_price = self.entry_price * (1 + self.target_pct/100.0)
                        except Exception:
                            self.target_price = None
                    # If the entry candle itself already reached target, lock immediately
                    if (
                        self.target_price is not None and
                        candle['high'] >= self.target_price and
                        not self.target_locked
                    ):
                        if self.stop_loss is None or self.stop_loss < self.target_price:
                            old_sl = self.stop_loss
                            self.stop_loss = self.target_price
                            self.logger.info(
                                f"LONG target hit on entry candle: stop {old_sl} -> {self.stop_loss} at {ct}"
                            )
                        self.target_locked = True
                    self.logger.info(
                        f"LONG entry signal at {ct} crossing pivot_high={self.pivot_high} SL={sl} (entry_price={self.entry_price}, pct_stop={self.stop_loss_pct})"
                    )
                    self.prev_candle = candle.copy()  # set prev candle for next trailing evaluation
                    # After taking a trade we now enforce range retouch before another pivot
                    self.in_entry_window = False
                    self.require_range_retouch = True
                    return {
                        'signal': 'buy',
                        'action': 'entry',
                        'pivot_high': self.pivot_high,
                        'pivot_low': self.pivot_low,
                        'sl': sl,
                        'target_price': self.target_price,
                        'target_pct': self.target_pct,
                        'target_locked': self.target_locked,
                        'pivot_time': self.pivot_candle_time,
                        'trade_number': self.trades_taken_today
                    }
            elif self.pivot_direction == 'bear':
                if candle['low'] <= self.pivot_low:
                    self.logger.debug(
                        f"SHORT entry trigger {ct}: candle_low={candle['low']} pivot_low={self.pivot_low}"
                    )
                    self.entry_taken = True
                    self.daily_trade_taken = True  # legacy
                    self.in_position = True
                    self.trades_taken_today += 1
                    self.entry_price = self.pivot_low if self.pivot_low is not None else candle['close']
                    sl = self.pivot_high
                    if self.stop_loss_pct is not None and self.entry_price is not None:
                        pct_stop = self.entry_price * (1 + self.stop_loss_pct / 100.0)
                        if pct_stop < sl:
                            sl = pct_stop
                    self.stop_loss = sl
                    self.target_price = None
                    self.target_locked = False
                    if self.target_pct is not None and self.entry_price is not None:
                        try:
                            self.target_price = self.entry_price * (1 - self.target_pct/100.0)
                        except Exception:
                            self.target_price = None
                    # If the entry candle itself already reached target on a SHORT, lock immediately
                    if (
                        self.target_price is not None and
                        candle['low'] <= self.target_price and
                        not self.target_locked
                    ):
                        if self.stop_loss is None or self.stop_loss > self.target_price:
                            old_sl = self.stop_loss
                            self.stop_loss = self.target_price
                            self.logger.info(
                                f"SHORT target hit on entry candle: stop {old_sl} -> {self.stop_loss} at {ct}"
                            )
                        self.target_locked = True
                    self.trailing_anchor = candle['low']
                    self.logger.info(
                        f"SHORT entry signal at {ct} crossing pivot_low={self.pivot_low} SL={sl} (entry_price={self.entry_price}, pct_stop={self.stop_loss_pct})"
                    )
                    self.prev_candle = candle.copy()
                    self.in_entry_window = False
                    self.require_range_retouch = True
                    return {
                        'signal': 'sell',
                        'action': 'entry',
                        'pivot_high': self.pivot_high,
                        'pivot_low': self.pivot_low,
                        'sl': sl,
                        'target_price': self.target_price,
                        'target_pct': self.target_pct,
                        'target_locked': self.target_locked,
                        'pivot_time': self.pivot_candle_time,
                        'trade_number': self.trades_taken_today
                    }

        # Manage trailing stop after entry (use previous candle low/high for stability; check breach BEFORE updating)
        if self.in_position and self.prev_candle is not None:
            # Early breach check BEFORE modifying stop (captures gaps and immediate hits)
            if self.pivot_direction == 'bull':
                if self.stop_loss is not None and candle['low'] <= self.stop_loss:
                    exit_sl = self.stop_loss
                    self.logger.info(f"LONG stop EXIT (early check) at {ct} stop={exit_sl}")
                    self.in_position = False
                    self.in_entry_window = False
                    return {
                        'signal': 'sell',
                        'action': 'stop_exit',
                        'sl': exit_sl,
                        'pivot_time': self.pivot_candle_time,
                        'trade_number': self.trades_taken_today
                    }
            elif self.pivot_direction == 'bear':
                if self.stop_loss is not None and candle['high'] >= self.stop_loss:
                    exit_sl = self.stop_loss
                    self.logger.info(f"SHORT stop EXIT (early check) at {ct} stop={exit_sl}")
                    self.in_position = False
                    self.in_entry_window = False
                    return {
                        'signal': 'buy',
                        'action': 'stop_exit',
                        'sl': exit_sl,
                        'pivot_time': self.pivot_candle_time,
                        'trade_number': self.trades_taken_today
                    }

            # Proceed with target lock and trailing adjustments only if still in position
            if self.in_position:
                if self.pivot_direction == 'bull':
                    # Target lock
                    if self.target_price is not None and not self.target_locked and candle['high'] >= self.target_price:
                        if self.stop_loss is None or self.stop_loss < self.target_price:
                            old_sl = self.stop_loss
                            self.stop_loss = self.target_price
                            self.logger.info(f"LONG target reached: stop {old_sl} -> {self.stop_loss} at {ct}")
                        self.target_locked = True
                    # Trailing adjustments
                    if self.trailing_stop_pct is not None:
                        if self.trailing_anchor is None or candle['high'] > self.trailing_anchor:
                            self.trailing_anchor = candle['high']
                        if self.trailing_anchor is not None:
                            trail_distance = self.trailing_anchor * (self.trailing_stop_pct / 100.0)
                            candidate_sl = self.trailing_anchor - trail_distance
                            if candidate_sl is not None and (self.stop_loss is None or candidate_sl > self.stop_loss):
                                old_sl = self.stop_loss
                                self.stop_loss = candidate_sl
                                self.logger.info(f"LONG pct trail move: stop {old_sl} -> {self.stop_loss} at {ct}")
                    else:
                        candidate = self.prev_candle['low']
                        if candidate is not None and candidate > (self.stop_loss or -float('inf')) and candidate < candle['low']:
                            old_sl = self.stop_loss
                            self.stop_loss = candidate
                            self.logger.info(f"LONG trail move: stop {old_sl} -> {self.stop_loss} at {ct}")
                    # Post-adjust breach check
                    if self.stop_loss is not None and candle['low'] <= self.stop_loss:
                        exit_sl = self.stop_loss
                        self.logger.info(f"LONG stop EXIT (post adjust) at {ct} stop={exit_sl}")
                        self.in_position = False
                        self.in_entry_window = False
                        return {
                            'signal': 'sell',
                            'action': 'stop_exit',
                            'sl': exit_sl,
                            'pivot_time': self.pivot_candle_time,
                            'trade_number': self.trades_taken_today
                        }
                elif self.pivot_direction == 'bear':
                    if self.target_price is not None and not self.target_locked and candle['low'] <= self.target_price:
                        if self.stop_loss is None or self.stop_loss > self.target_price:
                            old_sl = self.stop_loss
                            self.stop_loss = self.target_price
                            self.logger.info(f"SHORT target reached: stop {old_sl} -> {self.stop_loss} at {ct}")
                        self.target_locked = True
                    if self.trailing_stop_pct is not None:
                        if self.trailing_anchor is None or candle['low'] < self.trailing_anchor:
                            self.trailing_anchor = candle['low']
                        if self.trailing_anchor is not None:
                            trail_distance = self.trailing_anchor * (self.trailing_stop_pct / 100.0)
                            candidate_sl = self.trailing_anchor + trail_distance
                            if candidate_sl is not None and (self.stop_loss is None or candidate_sl < self.stop_loss):
                                old_sl = self.stop_loss
                                self.stop_loss = candidate_sl
                                self.logger.info(f"SHORT pct trail move: stop {old_sl} -> {self.stop_loss} at {ct}")
                    else:
                        candidate = self.prev_candle['high']
                        if candidate is not None and candidate < (self.stop_loss or float('inf')) and candidate > candle['high']:
                            old_sl = self.stop_loss
                            self.stop_loss = candidate
                            self.logger.info(f"SHORT trail move: stop {old_sl} -> {self.stop_loss} at {ct}")
                    if self.stop_loss is not None and candle['high'] >= self.stop_loss:
                        exit_sl = self.stop_loss
                        self.logger.info(f"SHORT stop EXIT (post adjust) at {ct} stop={exit_sl}")
                        self.in_position = False
                        self.in_entry_window = False
                        return {
                            'signal': 'buy',
                            'action': 'stop_exit',
                            'sl': exit_sl,
                            'pivot_time': self.pivot_candle_time,
                            'trade_number': self.trades_taken_today
                        }

        # Store candle as previous after processing trailing logic
        self.prev_candle = candle.copy()

        # RANGE RETOUCH CHECK: If we are awaiting retouch (require_range_retouch) and NOT in position
        # detect a candle that fully returns inside (or touches) the original range (close within bounds).
        if (not self.in_position) and self.require_range_retouch and self.open_range_completed:
            # Condition: candle's close returns BETWEEN range_low and range_high
            if candle['close'] <= self.range_high and candle['close'] >= self.range_low:
                # Reset pivot & allow new breakout sequence
                self.logger.info(f"Range retouched at {ct}; re-arming breakout logic.")
                self.pivot_candle_time = None
                self.pivot_high = None
                self.pivot_low = None
                self.pivot_direction = None
                self.entry_window_start = None
                self.in_entry_window = False
                self.require_range_retouch = False
                # Expose cleared state for chart (explicit Nones)

        return None

    def get_indicators(self):
        # If no pivot detected yet but opening range is completed, allow charts to show OR high/low as provisional lines
        # by mapping them into pivot_high/low with pivot_time at orb_end - 1 minute (last minute inside range).
        provisional_pivot_time = None
        provisional_high = None
        provisional_low = None
        provisional_dir = None
        if self.open_range_completed and self.pivot_candle_time is None:
            provisional_high = self.range_high
            provisional_low = self.range_low
            # Use the exact orb_end boundary as provisional time (aligned to minute at end of collection window)
            if self.orb_end is not None:
                provisional_pivot_time = self.orb_end
        return {
            'range_high': self.range_high,
            'range_low': self.range_low,
            'open_range_completed': self.open_range_completed,
            'pivot_time': self.pivot_candle_time or provisional_pivot_time,
            'pivot_high': self.pivot_high if self.pivot_candle_time else provisional_high,
            'pivot_low': self.pivot_low if self.pivot_candle_time else provisional_low,
            'pivot_direction': self.pivot_direction if self.pivot_candle_time else provisional_dir,
            'entry_taken': self.entry_taken,
            'daily_trade_taken': self.daily_trade_taken,
            'trades_taken_today': self.trades_taken_today,
            'max_trades_per_day': self.max_trades_per_day,
            'in_position': self.in_position,
            'stop_loss': self.stop_loss,
            'stop_loss_pct': self.stop_loss_pct,
            'trailing_stop_pct': self.trailing_stop_pct,
            'entry_price': self.entry_price,
            'trailing_anchor': self.trailing_anchor,
            'target_pct': self.target_pct,
            'target_price': self.target_price,
            'target_locked': self.target_locked,
            'in_entry_window': self.in_entry_window,
            'require_range_retouch': self.require_range_retouch,
            'require_boundary_touch': self.require_boundary_touch
        }
