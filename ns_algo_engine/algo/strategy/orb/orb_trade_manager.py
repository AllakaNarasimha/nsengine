from .orb_signal import ORBSignal
from .orb_config import OrbConfig

class ORBTradeManager:
    """
    Manages trades using ORBPivots. Handles entries, exits, stops, trailing, and targets.
    """
    def __init__(self, orb_config: OrbConfig, end_time, orb_signal: ORBSignal):
        self.orb_signal = orb_signal
        self.end_time = end_time
        self.stop_loss_pct = orb_config.stop_loss_pct
        self.trailing_stop_pct = orb_config.trailing_stop_pct
        self.target_pct = orb_config.target_pct
        
        # Trade state
        self.in_position = False
        self.pivot_direction = None
        self.stop_loss = None
        self.entry_price = None
        self.trailing_anchor = None
        self.trailing_step = None
        self.last_trail_level = None
        self.target_price = None
        self.target_locked = False
        self.prev_candle = None
        self.pivot_candle_time = None

        # Daily trade tracking
        self.trades_taken_today = 0
        self.max_trades_per_day = orb_config.max_trades_per_day
        self.require_range_retouch = orb_config.require_boundary_touch

    def update_candle(self, candle):
        """
        Update with a new candle. Processes pivots and manages position.
        Returns signal dict if entry or exit occurs.
        """
        if self.trades_taken_today < self.max_trades_per_day and not self.require_range_retouch:
            return None
        
        # Update pivots first
        if not self.in_position and self.end_time > candle['timestamp'].time():
            pivot_result = self.orb_signal.check_trade_signal(candle)
        else:
            pivot_result = None    

        # Handle entry
        if pivot_result and 'entry_signal' in pivot_result:
            self.in_position = True
            self.pivot_direction =  pivot_result['pivot_direction']
            self.pivot_candle_time = pivot_result['pivot_time']
            self.trades_taken_today += 1
            if self.pivot_direction == 'bull':
                self.entry_price = pivot_result['orb_high']
                self.stop_loss = pivot_result['orb_low']
                if self.stop_loss_pct and self.entry_price:
                    pct_stop = self.entry_price * (1 - self.stop_loss_pct)
                    if pct_stop > self.stop_loss:
                        self.stop_loss = pct_stop
                if self.target_pct and self.entry_price:
                    self.target_price = self.entry_price * (1 + self.target_pct)
                if self.trailing_stop_pct:
                    self.trailing_step = self.entry_price * self.trailing_stop_pct
                    self.last_trail_level = self.entry_price + self.trailing_step
                    candidate_sl = self.entry_price - self.trailing_step
                    if candidate_sl > self.stop_loss:
                        self.stop_loss = candidate_sl
                # Check if target hit on entry candle
                if self.target_price and candle['high'] >= self.target_price and not self.target_locked:
                    if self.stop_loss < self.target_price:
                        self.stop_loss = self.target_price
                    self.target_locked = True
            else:  # bear
                self.entry_price = pivot_result['orb_low']
                self.stop_loss = pivot_result['orb_high']
                if self.stop_loss_pct and self.entry_price:
                    pct_stop = self.entry_price * (1 + self.stop_loss_pct)
                    if pct_stop < self.stop_loss:
                        self.stop_loss = pct_stop
                if self.target_pct and self.entry_price:
                    self.target_price = self.entry_price * (1 - self.target_pct)
                if self.trailing_stop_pct:
                    self.trailing_step = self.entry_price * self.trailing_stop_pct
                    self.last_trail_level = self.entry_price - self.trailing_step
                    candidate_sl = self.entry_price + self.trailing_step
                    if candidate_sl < self.stop_loss:
                        self.stop_loss = candidate_sl
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
                    self.orb_signal.pivot_candle = None  # Reset pivot on exit
                    return {
                        'signal': 'sell',
                        'action': 'stop_exit',
                        'sl': self.stop_loss,
                        'pivot_time': self.pivot_candle_time,
                        'trade_number': self.trades_taken_today
                    }
            else:
                if self.stop_loss and candle['high'] >= self.stop_loss:
                    self.in_position = False
                    self.orb_signal.pivot_candle = None  # Reset pivot on exit
                    return {
                        'signal': 'buy',
                        'action': 'stop_exit',
                        'sl': self.stop_loss,
                        'pivot_time': self.pivot_candle_time,
                        'trade_number': self.trades_taken_today
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
                    if candle['high'] >= self.last_trail_level:
                        self.last_trail_level += self.trailing_step
                        self.stop_loss = self.last_trail_level - self.trailing_step
                else:
                    candidate = self.prev_candle['low']
                    if candidate and candidate > (self.stop_loss or -float('inf')) and candidate < candle['low']:
                        self.stop_loss = candidate
                # Post-adjust stop check
                if self.stop_loss and candle['low'] <= self.stop_loss:
                    self.in_position = False
                    self.orb_signal.pivot_candle = None  # Reset pivot on exit
                    return {
                        'signal': 'sell',
                        'action': 'stop_exit',
                        'sl': self.stop_loss,
                        'pivot_time': self.pivot_candle_time,
                        'trade_number': self.trades_taken_today
                    }
            else:
                # Target lock
                if self.target_price and not self.target_locked and candle['low'] <= self.target_price:
                    if self.stop_loss > self.target_price:
                        self.stop_loss = self.target_price
                    self.target_locked = True
                # Trailing
                if self.trailing_stop_pct:
                    if candle['low'] <= self.last_trail_level:
                        self.last_trail_level -= self.trailing_step
                        self.stop_loss = self.last_trail_level + self.trailing_step
                else:
                    candidate = self.prev_candle['high']
                    if candidate and candidate < (self.stop_loss or float('inf')) and candidate > candle['high']:
                        self.stop_loss = candidate
                # Post-adjust stop check
                if self.stop_loss and candle['high'] >= self.stop_loss:
                    self.in_position = False
                    self.orb_signal.pivot_candle = None  # Reset pivot on exit
                    return {
                        'signal': 'buy',
                        'action': 'stop_exit',
                        'sl': self.stop_loss,
                        'pivot_time': self.pivot_candle_time,
                        'trade_number': self.trades_taken_today
                    }

        self.prev_candle = candle.copy()

        if self.end_time < candle['timestamp'].time():
            self.orb_signal.pivot_candle_time = None 
            self.in_position = None
            
        return None

    def reset(self):
        """Reset trade state."""
        self.orb_signal.reset()
        self.trades_taken_today = 0
        self.in_position = False
        self.orb_signal.pivot_candle = None  # Reset pivot on exit
        self.pivot_direction = None
        self.pivot_candle_time = None
        self.stop_loss = None
        self.entry_price = None
        self.trailing_anchor = None
        self.trailing_step = None
        self.last_trail_level = None
        self.target_price = None
        self.target_locked = False
        self.prev_candle = None