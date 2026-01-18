import logging
import datetime
from algo.utils.app_config import AppConfig


class TradeManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.position = None
        self.entry_price = None
        self.entry_datetime = None
        self.trade_id = 0
        self._start_time = self._parse_time(config.start_time)
        self._end_time = self._parse_time(config.end_time)
        self.pl_threshold = config.pl_percent  # Minimum percentage change to consider
        self.logger = logging.getLogger(__name__)

    def _parse_time(self, time_str):
        """Parse time string in HH:MM format to datetime.time object."""
        return datetime.datetime.strptime(time_str, '%H:%M').time()

    def process_signal(self, current_candle, trade_signal):
        try:
            ct = current_candle['timestamp']
        except Exception:
            ct = None
        
        trade_data = None
        
        # End-of-session handling: close existing position and block further trading
        if ct and self._end_time and ct.time() >= self._end_time:
            if self.position is not None:
                self.logger.info("End time reached. Auto-closing open position.")
                trade_data = self._close_position(current_candle)
            return trade_data
        
        # Flag controlling whether we are permitted to open NEW positions
        allow_new_entries = True    
        if ct.hour == 15 and ct.minute == 0:
            allow_new_entries = False
        if ct and self._start_time and ct.time() < self._start_time or ct.time() >= self._end_time:
            allow_new_entries = False
        
        if trade_signal is None:
            return trade_data
        
        if trade_signal['signal'] == 'buy':
            # Always allow closing an opposing position
            if self.position == 'short':
                trade_data = self._close_position(current_candle)
            # Only open a new long if entries are allowed
            if allow_new_entries and self.position != 'long':
                self._open_position('long', current_candle)
        elif trade_signal['signal'] == 'sell' :
            if self.position == 'long':
                trade_data = self._close_position(current_candle)
            if allow_new_entries and self.position != 'short':
                self._open_position('short', current_candle)        
        
        return trade_data
    
    def _open_position(self, position_type, current_candle):
        self.position = position_type
        self.entry_price = current_candle['open']
        self.entry_datetime = current_candle['timestamp']
        self.logger.info(f"Opened {position_type.upper()} position at {self.entry_price} on {self.entry_datetime}")
    
    def _close_position(self, current_candle):
        if not self.position:
            return None
        price = current_candle['close']
        current_datetime = current_candle['timestamp']
        profit_loss = (price - self.entry_price) if self.position == 'long' else (self.entry_price - price)
        
        trade_data = {
            'trade_id': self.trade_id,
            'entry_datetime': self.entry_datetime, 
            'exit_datetime': current_datetime,
            'entry_price': self.entry_price,
            'exit_price': price,
            'position_type': self.position,
            'action': 'closed',
            'position_state': 'closed',
            'profit_loss': profit_loss,
        }
        self.logger.info(f"Closed {self.position.upper()} position: P&L={profit_loss:.2f}")
        
        self.trade_id += 1
        self.position = None
        self.entry_price = None
        self.entry_option_price = None
        self.entry_datetime = None
        return trade_data    
        
                