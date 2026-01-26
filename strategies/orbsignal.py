class ORBSignal:
    """
    Checks the actual ORB breakout signal based on a candle and range boundaries.
    """
    def __init__(self, require_boundary_touch=True):
        self.require_boundary_touch = require_boundary_touch

    def check_breakout(self, candle, range_high, range_low):
        """
        Check if the given candle represents a breakout from the ORB range.
        Returns 'bull' for upward breakout, 'bear' for downward, None otherwise.
        """
        if candle['close'] > range_high:
            if not self.require_boundary_touch or candle['low'] <= range_high:
                return 'bull'
        elif candle['close'] < range_low:
            if not self.require_boundary_touch or candle['high'] >= range_low:
                return 'bear'
        return None