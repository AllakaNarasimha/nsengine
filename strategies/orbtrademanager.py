from .orbpivots import ORBPivots

class ORBTradeManager:
    """
    Manages trades using ORBPivots. Handles entries, exits, stops, trailing, and targets.
    """
    def __init__(self, orbpivots, stop_loss_pct=None, trailing_stop_pct=None, target_pct=None):
        self.orbpivots = orbpivots
        self.stop_loss_pct = stop_loss_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.target_pct = target_pct
        # Trade state
        self.in_position = False
        self.pivot_direction = None
        self.stop_loss = None
        self.entry_price = None
        self.trailing_anchor = None
        self.target_price = None
        self.target_locked = False
        self.prev_candle = None

    def update_candle(self, candle):
        """
        Update with a new candle. Processes pivots and manages position.
        Returns signal dict if entry or exit occurs.
        """
        # Update pivots first
        pivot_result = self.orbpivots.update_candle(candle)

        # Handle entry
        if pivot_result and 'entry_signal' in pivot_result:
            self.in_position = True
            self.pivot_direction = self.orbpivots.pivot_direction
            if self.pivot_direction == 'bull':
                self.entry_price = self.orbpivots.pivot_high
                self.stop_loss = self.orbpivots.pivot_low
                if self.stop_loss_pct and self.entry_price:
                    pct_stop = self.entry_price * (1 - self.stop_loss_pct / 100.0)
                    if pct_stop > self.stop_loss:
                        self.stop_loss = pct_stop
                if self.target_pct and self.entry_price:
                    self.target_price = self.entry_price * (1 + self.target_pct / 100.0)
                self.trailing_anchor = candle['high']
                # Check if target hit on entry candle
                if self.target_price and candle['high'] >= self.target_price and not self.target_locked:
                    if self.stop_loss < self.target_price:
                        self.stop_loss = self.target_price
                    self.target_locked = True
            else:  # bear
                self.entry_price = self.orbpivots.pivot_low
                self.stop_loss = self.orbpivots.pivot_high
                if self.stop_loss_pct and self.entry_price:
                    pct_stop = self.entry_price * (1 + self.stop_loss_pct / 100.0)
                    if pct_stop < self.stop_loss:
                        self.stop_loss = pct_stop
                if self.target_pct and self.entry_price:
                    self.target_price = self.entry_price * (1 - self.target_pct / 100.0)
                self.trailing_anchor = candle['low']
                # Check if target hit on entry candle
                if self.target_price and candle['low'] <= self.target_price and not self.target_locked:
                    if self.stop_loss > self.target_price:
                        self.stop_loss = self.target_price
                    self.target_locked = True
            self.prev_candle = candle.copy()
            return {
                'signal': pivot_result['entry_signal'],
                'action': 'entry',
                'sl': self.stop_loss,
                'target_price': self.target_price,
                'target_pct': self.target_pct,
                'target_locked': self.target_locked,
                **pivot_result
            }

        # Manage existing position
        if self.in_position and self.prev_candle:
            # Early stop check
            if self.pivot_direction == 'bull':
                if self.stop_loss and candle['low'] <= self.stop_loss:
                    self.in_position = False
                    self.orbpivots.in_entry_window = False
                    return {
                        'signal': 'sell',
                        'action': 'stop_exit',
                        'sl': self.stop_loss,
                        'pivot_time': self.orbpivots.pivot_candle_time,
                        'trade_number': self.orbpivots.trades_taken_today
                    }
            else:
                if self.stop_loss and candle['high'] >= self.stop_loss:
                    self.in_position = False
                    self.orbpivots.in_entry_window = False
                    return {
                        'signal': 'buy',
                        'action': 'stop_exit',
                        'sl': self.stop_loss,
                        'pivot_time': self.orbpivots.pivot_candle_time,
                        'trade_number': self.orbpivots.trades_taken_today
                    }

            # Target and trailing adjustments
            if self.pivot_direction == 'bull':
                # Target lock
                if self.target_price and not self.target_locked and candle['high'] >= self.target_price:
                    if self.stop_loss < self.target_price:
                        self.stop_loss = self.target_price
                    self.target_locked = True
                # Trailing
                if self.trailing_stop_pct:
                    if self.trailing_anchor is None or candle['high'] > self.trailing_anchor:
                        self.trailing_anchor = candle['high']
                    if self.trailing_anchor:
                        trail_distance = self.trailing_anchor * (self.trailing_stop_pct / 100.0)
                        candidate_sl = self.trailing_anchor - trail_distance
                        if candidate_sl > self.stop_loss:
                            self.stop_loss = candidate_sl
                else:
                    candidate = self.prev_candle['low']
                    if candidate and candidate > (self.stop_loss or -float('inf')) and candidate < candle['low']:
                        self.stop_loss = candidate
                # Post-adjust stop check
                if self.stop_loss and candle['low'] <= self.stop_loss:
                    self.in_position = False
                    self.orbpivots.in_entry_window = False
                    return {
                        'signal': 'sell',
                        'action': 'stop_exit',
                        'sl': self.stop_loss,
                        'pivot_time': self.orbpivots.pivot_candle_time,
                        'trade_number': self.orbpivots.trades_taken_today
                    }
            else:
                # Target lock
                if self.target_price and not self.target_locked and candle['low'] <= self.target_price:
                    if self.stop_loss > self.target_price:
                        self.stop_loss = self.target_price
                    self.target_locked = True
                # Trailing
                if self.trailing_stop_pct:
                    if self.trailing_anchor is None or candle['low'] < self.trailing_anchor:
                        self.trailing_anchor = candle['low']
                    if self.trailing_anchor:
                        trail_distance = self.trailing_anchor * (self.trailing_stop_pct / 100.0)
                        candidate_sl = self.trailing_anchor + trail_distance
                        if candidate_sl < self.stop_loss:
                            self.stop_loss = candidate_sl
                else:
                    candidate = self.prev_candle['high']
                    if candidate and candidate < (self.stop_loss or float('inf')) and candidate > candle['high']:
                        self.stop_loss = candidate
                # Post-adjust stop check
                if self.stop_loss and candle['high'] >= self.stop_loss:
                    self.in_position = False
                    self.orbpivots.in_entry_window = False
                    return {
                        'signal': 'buy',
                        'action': 'stop_exit',
                        'sl': self.stop_loss,
                        'pivot_time': self.orbpivots.pivot_candle_time,
                        'trade_number': self.orbpivots.trades_taken_today
                    }

        self.prev_candle = candle.copy()
        return None

    def reset(self):
        """Reset trade state."""
        self.orbpivots.reset()
        self.in_position = False
        self.pivot_direction = None
        self.stop_loss = None
        self.entry_price = None
        self.trailing_anchor = None
        self.target_price = None
        self.target_locked = False
        self.prev_candle = None