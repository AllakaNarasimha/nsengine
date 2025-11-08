import pandas as pd
import logging
from datetime import time

logging.basicConfig(filename='trading.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TradeManager:
    def __init__(self, lot_size, pl_percent=0.5, start_time=None, end_time=None):
        self.lot_size = lot_size
        self.position = None
        self.entry_price = None
        self.entry_datetime = None
        self.entry_option_symbol = None
        self.trade_id = 0
        self._start_time = self._parse_time(start_time)
        self._end_time = self._parse_time(end_time)
        self.pl_threshold = pl_percent  # Minimum percentage change to consider
        self.logger = logging.getLogger(__name__)
        
    
    def process_signal(self, signal, price, current_datetime, indicators=None, option_data=None, pl_percent=None,
                       start_time=None, end_time=None):        
        self.pl_threshold = pl_percent if pl_percent is not None else self.pl_threshold  # Minimum percentage change to consider
        # Determine current time component (robust to non-datetime objects)
        try:
            ct = current_datetime.time()
        except Exception:
            ct = None

        # End-of-session handling: close existing position and block further trading
        if ct and self._end_time and ct >= self._end_time:
            if self.position is not None:
                self.logger.info("End time reached. Auto-closing open position.")
                trade_data = self._close_position(price, current_datetime, indicators, option_data or {})
                if trade_data and option_data:
                    trade_data.update(option_data)
                return trade_data
            # No position open; ignore any signals after session end
            return None

        # Flag controlling whether we are permitted to open NEW positions
        allow_new_entries = True    
        if ct.hour == 15 and ct.minute == 0:
            allow_new_entries = False
        if ct and self._start_time and ct < self._start_time or ct >= self._end_time:
            allow_new_entries = False

        if not signal:
            if self.position is not None and option_data:
                current_pl_percent = self._calculate_current_pl_percentage(option_data.get('option_price', 0))
                if abs(current_pl_percent) >= self.pl_threshold:
                    self.logger.info(f"PL% threshold reached ({current_pl_percent:.2f}%), auto-closing {self.position} position")
                    trade_data = self._close_position(price, current_datetime, indicators, option_data)
                    if trade_data and option_data:
                        trade_data.update(option_data)
                    return trade_data
            return None
        
        trade_data = None

        if self.position is not None and option_data:
            current_pl_percent = self._calculate_current_pl_percentage(option_data.get('option_price', 0))
            if abs(current_pl_percent) >= self.pl_threshold:
                self.logger.info(f"PL% threshold reached ({current_pl_percent:.2f}%), auto-closing {self.position} position")
                trade_data = self._close_position(price, current_datetime, indicators, option_data)
                if trade_data and option_data:
                    trade_data.update(option_data)
                return trade_data            
        
        if signal == 'buy':
            # Always allow closing an opposing position
            if self.position == 'short':
                trade_data = self._close_position(price, current_datetime, indicators, option_data)
            # Only open a new long if entries are allowed
            if allow_new_entries and self.position != 'long':
                self._open_position('long', price, current_datetime, option_data or {})
        elif signal == 'sell':
            if self.position == 'long':
                trade_data = self._close_position(price, current_datetime, indicators, option_data)
            if allow_new_entries and self.position != 'short':
                self._open_position('short', price, current_datetime, option_data or {})
        
        if trade_data and option_data:
            trade_data.update(option_data)
        return trade_data

    # -------------------- Helper Methods --------------------
    def _parse_time(self, t):        
        if t is None:
            return None
        if isinstance(t, time):
            return t
        if isinstance(t, int):
            if 0 <= t <= 23:
                return time(t, 0)
            self.logger.warning(f"Invalid hour int for time parsing: {t}")
            return None
        if isinstance(t, str):
            try:
                parts = t.strip().split(':')
                if len(parts) == 2:
                    h = int(parts[0]); m = int(parts[1])
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        return time(h, m)
                self.logger.warning(f"Invalid time string format: {t}")
            except Exception:
                self.logger.exception(f"Failed parsing time string: {t}")
            return None
        self.logger.warning(f"Unsupported time spec type: {type(t)} -> {t}")
        return None
    
    def _calculate_current_pl_percentage(self, current_option_price):
        """Calculate current PL percentage based on entry and current option prices"""
        if not self.position or self.entry_option_price == 0:
            return 0
        
        if self.position == 'long':
            pl_percentage = ((current_option_price - self.entry_option_price) / self.entry_option_price) * 100
        else:  # short position
            pl_percentage = ((self.entry_option_price - current_option_price) / self.entry_option_price) * 100
        
        return pl_percentage
    
    def _open_position(self, position_type, price, current_datetime, option_data):
        self.position = position_type
        self.entry_price = price
        self.entry_option_price = option_data.get('option_price', 0)
        self.entry_datetime = current_datetime
        self.entry_option_symbol = option_data.get('option_symbol', '')
        self.entry_instrument_token = option_data.get('instrument_token', None)
        self.logger.info(f"Opened {position_type.upper()} position at {price} on {current_datetime}")
    
    def _close_position(self, price, current_datetime, indicators, option_data):
        if not self.position:
            return None
        # Defensive: allow option_data to be None
        option_data = option_data or {}
        option_price = option_data.get('option_price', 0)
        profit_loss = (option_price - self.entry_option_price) * self.lot_size
        #if option_data and option_data.get('option_price', 0) > 0:
        #    profit_loss = option_data['option_price'] * 0.1 * self.lot_size
        
        trade_data = {
            'trade_id': self.trade_id,
            'entry_datetime': self.entry_datetime,
            'exit_datetime': current_datetime,
            'entry_price': self.entry_price,
            'exit_price': price,
            'entry_option_price': self.entry_option_price,
            'exit_option_price': option_data.get('option_price', 0),
            'position_type': self.position,
            'action': 'closed',
            'position_state': 'closed',
            'profit_loss': profit_loss,
            'lot_size': self.lot_size
        }
        trade_data.update(indicators or {})
        self.logger.info(f"Closed {self.position.upper()} position: P&L={profit_loss:.2f}")
        
        self.trade_id += 1
        self.position = None
        self.entry_price = None
        self.entry_option_price = None
        self.entry_datetime = None
        return trade_data

    def enforce_session_constraints(self, price, current_datetime, option_data, indicators=None):        
        try:
            ct = current_datetime.time()
        except Exception:
            return None
        if self.position and self._end_time and ct >= self._end_time:
            trade_data = self._close_position(price, current_datetime, indicators, option_data or {})
            if trade_data and option_data:
                trade_data.update(option_data)
            return trade_data
        return None