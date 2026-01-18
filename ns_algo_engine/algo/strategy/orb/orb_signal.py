import datetime
import pandas as pd
from .orb_config import OrbConfig

class ORBSignal:
    def __init__(self, df, config: OrbConfig):
        self.df = df.sort_index()
        self.config = config
        self.range_high = None
        self.range_low = None
        self.pivot_high = None
        self.pivot_low = None
        self.pivot_candle = None
        self.pivot_direction = None
        self.pivot_candle_time = None
        self.entry_signal_data = None
        self.trade_date = self.df.index[0].date()
        self.orb_start_dt = pd.to_datetime(f"{self.trade_date.strftime('%Y-%m-%d')} {self.config.orb_start_time.strftime('%H:%M:%S')}").tz_localize(self.df.index.tz)
        self.orb_end_dt = pd.to_datetime(f"{self.trade_date.strftime('%Y-%m-%d')} {self.config.orb_end_time.strftime('%H:%M:%S')}").tz_localize(self.df.index.tz)
        self.set_orb_range()

    def set_orb_range(self):
        # Get the date from the df index
        opening_range_df = self.df.loc[self.orb_start_dt:self.orb_end_dt]
        if not opening_range_df.empty:
            self.range_high = opening_range_df['high'].max()
            self.range_low = opening_range_df['low'].min()
            return True
        return False

    def get_pivot_candle(self, current_candle):
        if (current_candle['timestamp'].time() <= self.orb_end_dt.time()):              
            return None, None, None
        
        # Scan df after orb_end_time and before current_candle time for breakout, from latest to oldest
        post_range_df = self.df[(self.df.index > self.orb_end_dt) & (self.df.index < current_candle['timestamp'])].iloc[::-1]
        for idx, row in post_range_df.iterrows():
            if row['close'] > self.range_high:
                self.pivot_candle = row.to_dict()
                self.pivot_high = self.pivot_candle['high']
                self.pivot_low = self.pivot_candle['low']
                self.pivot_direction = 'bull'
                self.pivot_candle_time = idx
                return self.pivot_candle, self.pivot_direction, self.pivot_candle_time
            elif row['close'] < self.range_low:
                self.pivot_candle = row.to_dict()
                self.pivot_high = self.pivot_candle['high']
                self.pivot_low = self.pivot_candle['low']
                self.pivot_direction = 'bear'
                self.pivot_candle_time = idx
                return self.pivot_candle, self.pivot_direction, self.pivot_candle_time
        return None, None, None

    def check_trade_signal(self, current_candle):
        if self.trade_date != current_candle['timestamp'].date():
            self.trade_date = current_candle['timestamp'].date()
            self.orb_start_dt = pd.to_datetime(f"{self.trade_date.strftime('%Y-%m-%d')} {self.config.orb_start_time.strftime('%H:%M:%S')}").tz_localize(self.df.index.tz)
            self.orb_end_dt = pd.to_datetime(f"{self.trade_date.strftime('%Y-%m-%d')} {self.config.orb_end_time.strftime('%H:%M:%S')}").tz_localize(self.df.index.tz)

            self.range_high = None
            self.range_low = None
            self.pivot_candle = None
            self.pivot_direction = None
            self.pivot_candle_time = None
            self.entry_signal_data = None
            
            self.set_orb_range()

        if self.entry_signal_data:
            self.entry_signal_data['pivot_time'] = current_candle['timestamp']
            signal = self.entry_signal_data.copy()
            self.entry_signal_data = None
            return signal
        
        if self.pivot_candle is None:
            self.get_pivot_candle(current_candle)            
        # pivot_candle, pivot_direction, pivot_candle_time = self.get_pivot_candle(current_candle)
        if self.pivot_candle:
            if (self.pivot_direction == 'bull' and current_candle['close'] > self.pivot_candle['high']) or (self.pivot_direction == 'bear' and current_candle['close'] < self.pivot_candle['low']):
                entry_signal = 'buy' if self.pivot_direction == 'bull' else 'sell'                
                self.entry_signal_data = {
                    'entry_signal': entry_signal,
                    'orb_high': self.range_high,
                    'orb_low': self.range_low,
                    'pivot_high': self.pivot_candle['high'],
                    'pivot_low': self.pivot_candle['low'],
                    'pivot_direction': self.pivot_direction,
                    'pivot_time': current_candle['timestamp']
                }
            #else:
                # it will shift the pivot candle on next check
                # self.get_pivot_candle(current_candle)            
        
        # Update df with current_candle
        if current_candle['timestamp'] not in self.df.index:
            self.df.loc[current_candle['timestamp']] = {k: v for k, v in current_candle.items() if k in self.df.columns}
        return None
