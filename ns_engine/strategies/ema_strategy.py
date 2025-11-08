import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.signal_generator import SignalGeneratorInterface
import logging

logging.basicConfig(filename='trading.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class EMAStrategy(SignalGeneratorInterface):
    def __init__(self, short_period=5, long_period=20):
        self.short_period = short_period
        self.long_period = long_period
        self.short_ema = None
        self.long_ema = None
        self.previous_short_ema = None
        self.previous_long_ema = None
        self.alpha_short = 2 / (short_period + 1)
        self.alpha_long = 2 / (long_period + 1)
        self.price_history = []
        self.initialized = False
        self.logger = logging.getLogger(__name__)
    
    def update(self, price, current_datetime):
        self.price_history.append(price)
        
        if len(self.price_history) < max(self.short_period, self.long_period):
            return None
        
        if not self.initialized:
            self.short_ema = sum(self.price_history[-self.short_period:]) / self.short_period
            self.long_ema = sum(self.price_history[-self.long_period:]) / self.long_period
            self.initialized = True
            self.logger.info(f"EMA initialized: short={self.short_ema:.2f}, long={self.long_ema:.2f}")
            return None

        self.previous_short_ema = self.short_ema
        self.previous_long_ema = self.long_ema
        self.short_ema = price * self.alpha_short + self.short_ema * (1 - self.alpha_short)
        self.long_ema = price * self.alpha_long + self.long_ema * (1 - self.alpha_long)

        if self.previous_short_ema <= self.previous_long_ema and self.short_ema > self.long_ema:
            pl_percent = ((self.short_ema - self.long_ema) / self.long_ema) * 100 if self.long_ema != 0 else 0
            self.logger.info(f"BUY signal: price={price}, short_ema={self.short_ema:.2f}, long_ema={self.long_ema:.2f}, PL%={pl_percent:.2f}")
            return 'buy'
        elif self.previous_short_ema >= self.previous_long_ema and self.short_ema < self.long_ema:
            pl_percent = ((self.long_ema - self.short_ema) / self.long_ema) * 100 if self.long_ema != 0 else 0
            self.logger.info(f"SELL signal: price={price}, short_ema={self.short_ema:.2f}, long_ema={self.long_ema:.2f}, PL%={pl_percent:.2f}")
            return 'sell'
        return None
    
    def reset(self):
        self.short_ema = None
        self.long_ema = None
        self.previous_short_ema = None
        self.previous_long_ema = None
        self.price_history = []
        self.initialized = False
    
    def get_indicators(self):
        return {'short_ema': self.short_ema, 'long_ema': self.long_ema}