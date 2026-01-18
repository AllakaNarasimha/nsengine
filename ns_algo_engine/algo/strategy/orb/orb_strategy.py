import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from .orb_config import OrbConfig
from .orb_signal import ORBSignal
from .orb_utils import CandleAggregator
from .orb_trade_manager import ORBTradeManager
from algo.utils.app_config import AppConfig
from algo.engine.data_state_manager import DataStateManager
import logging

logging.basicConfig(filename='trading.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ORBStrategy:
    def __init__(self, df, app_config: AppConfig, data_state_manager: DataStateManager):
        self.app_config: AppConfig = app_config
        self.config = OrbConfig.from_app_config(app_config)
        self.df = df
        self.data_state_manager = data_state_manager
        # Logging / storage
        self.logger = logging.getLogger(__name__)
        self._end_time = self._parse_time(app_config.end_time)

        # Initialize components
        self.orb_signal = ORBSignal(df, self.config)
        self.orb_trade_manager = ORBTradeManager(self.config, self._end_time, self.orb_signal)
        # Candle aggregator for tick-based updates
        self.candle_aggregator = CandleAggregator(self.config.candle_granularity)
        # Daily control
        self.current_trade_day = None

    def _parse_time(self, time_str):
        """Parse time string in HH:MM format to datetime.time object."""
        return datetime.datetime.strptime(time_str, '%H:%M').time()
    
    def reset(self):
        self.orb_trade_manager.reset()
        if self.candle_aggregator:
            self.candle_aggregator.reset()
        self.current_trade_day = None

    def update(self, price, current_datetime):
        # Detect day change
        trade_day = current_datetime.date()
        if self.current_trade_day is None:
            self.current_trade_day = trade_day
        elif trade_day != self.current_trade_day:
            self.logger.info(f"New trading day detected: {trade_day}. Resetting ORB state.")
            self.reset()
            self.current_trade_day = trade_day
        # Aggregate ticks into candles
        finalized_candle = self.candle_aggregator.update(price, current_datetime)
        if finalized_candle:
            return self._process_candle(finalized_candle)
        return None    

    def _process_candle(self, candle):
        """Process a finalized candle through pivots and trade manager."""
        signal = self.orb_trade_manager.update_candle(candle)  
        
        self._process_candle_signals(candle)

        return signal

    def _process_candle_signals(self, candle):
        """Process trading signals for closed candle."""
        # Inject indicators
        try:
            candle_dt = candle['timestamp']
            inds = self.get_indicators()
            if candle_dt in self.df.iloc[:self.data_state_manager.current_index].index:
                for k in [ 'orb_time', 'pivot_time', 'pivot_high', 'pivot_low', 'pivot_direction', 'range_high', 'range_low']:
                    if k in inds:
                        self.df.at[candle_dt, k] = inds[k]
                for k in ['orb_time', 'pivot_high', 'pivot_low', 'range_high', 'range_low']:
                    try:
                        self.df[k] = self.df[k].ffill()
                    except Exception:
                        pass
        except Exception:
            pass 
    
    def get_indicators(self):
        # Gather from components
        orb_signal = self.orb_signal
        orb_trade_manager = self.orb_trade_manager
       
        return {
            'orb_time' : orb_signal.orb_end_dt,
            'pivot_time': orb_signal.pivot_candle_time,
            'pivot_high': orb_signal.pivot_high,
            'pivot_low': orb_signal.pivot_low,
            'pivot_direction': orb_signal.pivot_direction if orb_signal.pivot_candle_time else None,
            'range_high': orb_signal.range_high,
            'range_low': orb_signal.range_low,            
            'entry_taken': orb_trade_manager.in_position,  
            'daily_trade_taken': orb_trade_manager.trades_taken_today > 0, 
            'trades_taken_today': orb_trade_manager.trades_taken_today,
            'max_trades_per_day': orb_trade_manager.max_trades_per_day,
            'in_position': orb_trade_manager.in_position,
            'stop_loss': orb_trade_manager.stop_loss,
            'stop_loss_pct': orb_trade_manager.stop_loss_pct,
            'trailing_stop_pct': orb_trade_manager.trailing_stop_pct,
            'entry_price': orb_trade_manager.entry_price,
            'trailing_anchor': orb_trade_manager.trailing_anchor,
            'target_pct': orb_trade_manager.target_pct,
            'target_price': orb_trade_manager.target_price,
            'target_locked': orb_trade_manager.target_locked,
        }
