import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.signal_generator import SignalGeneratorInterface
import logging

logging.basicConfig(filename='trading.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RSIStrategy(SignalGeneratorInterface):
    def __init__(self, period=14, oversold=30, overbought=70):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.prices = []
        self.gains = []
        self.losses = []
        self.rsi = None
        self.logger = logging.getLogger(__name__)
    
    def update(self, price, current_datetime):
        self.prices.append(price)
        
        if len(self.prices) < 2:
            return None
        
        change = self.prices[-1] - self.prices[-2]
        self.gains.append(max(change, 0))
        self.losses.append(max(-change, 0))
        
        if len(self.gains) > self.period:
            self.gains.pop(0)
            self.losses.pop(0)
        
        if len(self.gains) < self.period:
            return None
        
        avg_gain = sum(self.gains) / self.period
        avg_loss = sum(self.losses) / self.period
        self.rsi = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
        
        if self.rsi < self.oversold:
            self.logger.info(f"BUY signal: price={price}, rsi={self.rsi:.2f}")
            return 'buy'
        elif self.rsi > self.overbought:
            self.logger.info(f"SELL signal: price={price}, rsi={self.rsi:.2f}")
            return 'sell'
        return None
    
    def reset(self):
        self.prices = []
        self.gains = []
        self.losses = []
        self.rsi = None
    
    def get_indicators(self):
        return {'rsi': self.rsi}