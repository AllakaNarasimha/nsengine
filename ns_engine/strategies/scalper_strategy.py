import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.signal_generator import SignalGeneratorInterface
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

try:
    import talib  # Prefer TA-Lib for EMA
    _HAS_TALIB = True
except Exception:  # pragma: no cover - fallback path
    _HAS_TALIB = False

logging.basicConfig(filename='trading.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ScalperStrategy(SignalGeneratorInterface):
    def __init__(self, run_candle=1, ema_min=5, ema_period=21, stop_loss_pct=None, trailing_stop_pct=None):        
        self.run_candle = run_candle
        self.ema_min = ema_min
        self.ema_period = ema_period
        # Risk management params (percent values, e.g. 0.5 => 0.5%)
        self.stop_loss_pct = stop_loss_pct  # absolute % from entry
        self.trailing_stop_pct = trailing_stop_pct  # trail distance % from peak (long) or trough (short)
        
        # EMA calculation (switch to TA-Lib)
        self.ema = None
        self.previous_ema = None
        self.last_close = None
        # Maintain a rolling list of closes for TA-Lib computation
        self._closes = []  # append each completed ema_min candle close
        
        # Candle data storage
        self.candles = {}  # {datetime: {'open': price, 'high': price, 'low': price, 'close': price}}
        self.current_candle_start = None
        self.current_candle = {'open': None, 'high': None, 'low': None, 'close': None}
        
        # Trade state
        self.ema_crossed = False
        self.crossed_candle_time = None
        self.entry_pending = False
        self.entry_time = None
        self.exit_time = None
        self.in_trade = False
        # Risk management state
        self.entry_price = None
        self.stop_loss_price = None
        self.trailing_anchor = None  # highest price since entry (long) or lowest (short)
        self.cross_direction = None  # 'up' or 'down'
        
        self.logger = logging.getLogger(__name__)
        # Data for plotting (list of dicts with datetime, close, ema)
        self.plot_records = []
    
    def reset(self):
        """Reset strategy state"""
        self.ema = None
        self.previous_ema = None
        self._closes = []
        self.candles = {}
        self.current_candle_start = None
        self.current_candle = {'open': None, 'high': None, 'low': None, 'close': None}
        self.ema_crossed = False
        self.crossed_candle_time = None
        self.entry_pending = False
        self.entry_time = None
        self.exit_time = None
        self.in_trade = False
        self.cross_direction = None
        self.entry_price = None
        self.stop_loss_price = None
        self.trailing_anchor = None
    
    def get_indicators(self):
        """Return current strategy indicators"""
        return {
            'ema': self.ema or 0,
            'ema_crossed': self.ema_crossed,
            'in_trade': self.in_trade,
            'cross_direction': self.cross_direction,
            'stop_loss_price': self.stop_loss_price or 0,
            'trailing_anchor': self.trailing_anchor or 0
        }
    
    def _get_candle_start_time(self, current_datetime):
        """Get the start time of the current EMA candle"""
        minutes = current_datetime.minute
        candle_minute = (minutes // self.ema_min) * self.ema_min
        return current_datetime.replace(minute=candle_minute, second=0, microsecond=0)
    
    def _update_candle(self, price, current_datetime):
        """Update current candle data"""
        candle_start = self._get_candle_start_time(current_datetime)
        
        # New candle started
        if self.current_candle_start != candle_start:
            # Complete previous candle if it exists
            if self.current_candle_start is not None and self.current_candle['open'] is not None:
                self.candles[self.current_candle_start] = self.current_candle.copy()
                self._calculate_ema_for_candle(self.current_candle_start)
            
            # Start new candle
            self.current_candle_start = candle_start
            self.current_candle = {'open': price, 'high': price, 'low': price, 'close': price}
        else:
            # Update current candle
            self.current_candle['high'] = max(self.current_candle['high'], price)
            self.current_candle['low'] = min(self.current_candle['low'], price)
            self.current_candle['close'] = price
    
    def _calculate_ema_for_candle(self, candle_time):
        """Calculate EMA for completed candle using TA-Lib (fallback to pandas)."""
        if candle_time not in self.candles:
            return

        candle = self.candles[candle_time]
        close_price = float(candle['close'])
        self.previous_ema = self.ema

        # Append close and compute EMA series
        self._closes.append(close_price)
        closes_arr = np.asarray(self._closes, dtype='float64')

        if _HAS_TALIB:
            try:
                ema_series = talib.EMA(closes_arr, timeperiod=int(self.ema_period))
                current_ema = float(ema_series[-1]) if not np.isnan(ema_series[-1]) else None
            except Exception:
                self.logger.exception("TA-Lib EMA failed; falling back to pandas ewm")
                current_ema = float(pd.Series(closes_arr).ewm(span=self.ema_period, adjust=False).mean().iloc[-1])
        else:  # fallback
            current_ema = float(pd.Series(closes_arr).ewm(span=self.ema_period, adjust=False).mean().iloc[-1])

        # Initialization semantics: first EMA becomes first close (match old behavior)
        if self.previous_ema is None and current_ema is not None:
            self.ema = close_price  # force first EMA = first close
            self.logger.info(f"EMA initialized (TA-Lib) : {self.ema:.2f} at {candle_time}")
        else:
            self.ema = current_ema

        # Determine candle end time (next candle open)
        candle_end = candle_time + timedelta(minutes=self.ema_min)

        # Cross detection (maintain previous semantics) only after we have both prev EMA and last_close
        if self.previous_ema is not None and self.last_close is not None and not self.in_trade and self.ema is not None:
            if self.last_close <= self.previous_ema and close_price > self.ema:
                # Cross up
                self.ema_crossed = True
                self.crossed_candle_time = candle_end
                self.cross_direction = 'up'
                self.entry_pending = True
                self.logger.info(f"EMA crossed UP: price={close_price:.2f}, EMA={self.ema:.2f} at {candle_time} (entry at {candle_end})")
            elif self.last_close >= self.previous_ema and close_price < self.ema:
                # Cross down
                self.ema_crossed = True
                self.crossed_candle_time = candle_end
                self.cross_direction = 'down'
                self.entry_pending = True
                self.logger.info(f"EMA crossed DOWN: price={close_price:.2f}, EMA={self.ema:.2f} at {candle_time} (entry at {candle_end})")

        # Update last_close
        self.last_close = close_price

        # Record for plotting
        try:
            self.plot_records.append({
                'datetime': candle_time,
                'close': close_price,
                'ema': float(self.ema) if self.ema is not None else None
            })
        except Exception:
            self.logger.exception("Failed to append plot record")
    
    def update(self, price, current_datetime):        
        # Update candle data
        self._update_candle(price, current_datetime)
        
        # Check for exit signal first
        if self.in_trade and self.exit_time and current_datetime >= self.exit_time:
            signal = 'sell' if self.cross_direction == 'up' else 'buy'  # Close opposite to entry
            pl_percent = 0.1  # Placeholder for exit PL
            self.in_trade = False
            self.entry_pending = False
            self.ema_crossed = False
            self.logger.info(f"EXIT signal: {signal.upper()} at {current_datetime}")
            return {
                'signal': signal,
                'pl_percent': pl_percent,
                'action': 'exit'
            }
        
        # Trail / stop evaluation for OPEN trade (in_trade True)
        if self.in_trade and self.entry_price is not None:
            # Update trailing anchor based on direction
            if self.cross_direction == 'up':  # long trade
                if self.trailing_anchor is None or price > self.trailing_anchor:
                    self.trailing_anchor = price
                # Update trailing stop if enabled
                if self.trailing_stop_pct is not None and self.trailing_anchor is not None:
                    trail_distance = self.trailing_anchor * (self.trailing_stop_pct / 100.0)
                    candidate_stop = self.trailing_anchor - trail_distance
                    # Never move stop down for long
                    if self.stop_loss_price is None or candidate_stop > self.stop_loss_price:
                        self.stop_loss_price = candidate_stop
                # Hard stop based on initial stop_loss_pct
                if self.stop_loss_pct is not None and self.stop_loss_price is None:
                    self.stop_loss_price = self.entry_price * (1 - self.stop_loss_pct / 100.0)
                # Check stop breach
                if self.stop_loss_price is not None and price <= self.stop_loss_price:
                    self.in_trade = False
                    self.entry_pending = False
                    self.ema_crossed = False
                    self.logger.info(f"STOP (LONG) triggered at {price:.2f} stop={self.stop_loss_price:.2f}")
                    return {
                        'signal': 'sell',
                        'action': 'stop',
                        'pl_percent': None
                    }
            elif self.cross_direction == 'down':  # short trade
                if self.trailing_anchor is None or price < self.trailing_anchor:
                    self.trailing_anchor = price
                if self.trailing_stop_pct is not None and self.trailing_anchor is not None:
                    trail_distance = self.trailing_anchor * (self.trailing_stop_pct / 100.0)
                    candidate_stop = self.trailing_anchor + trail_distance
                    if self.stop_loss_price is None or candidate_stop < self.stop_loss_price:
                        self.stop_loss_price = candidate_stop
                if self.stop_loss_pct is not None and self.stop_loss_price is None:
                    self.stop_loss_price = self.entry_price * (1 + self.stop_loss_pct / 100.0)
                if self.stop_loss_price is not None and price >= self.stop_loss_price:
                    self.in_trade = False
                    self.entry_pending = False
                    self.ema_crossed = False
                    self.logger.info(f"STOP (SHORT) triggered at {price:.2f} stop={self.stop_loss_price:.2f}")
                    return {
                        'signal': 'buy',
                        'action': 'stop',
                        'pl_percent': None
                    }

        # Check for entry signal
        if self.entry_pending and not self.in_trade and self.crossed_candle_time:
            # Entry should happen at the next candle's open after EMA cross (crossed_candle_time is the next candle open)
            next_candle_time = self.crossed_candle_time

            if current_datetime >= next_candle_time:
                # Enter trade
                signal = 'buy' if self.cross_direction == 'up' else 'sell'
                self.in_trade = True
                self.entry_time = current_datetime
                self.entry_pending = False
                self.entry_price = price
                # Initialize hard stop if provided
                if self.cross_direction == 'up' and self.stop_loss_pct is not None:
                    self.stop_loss_price = self.entry_price * (1 - self.stop_loss_pct / 100.0)
                elif self.cross_direction == 'down' and self.stop_loss_pct is not None:
                    self.stop_loss_price = self.entry_price * (1 + self.stop_loss_pct / 100.0)
                # Initialize trailing anchor
                self.trailing_anchor = price
                
                # Calculate exit time: entry_time + run_candle + 1 minute (for next candle open)
                self.exit_time = self.entry_time + timedelta(minutes=self.run_candle + 1)
                
                pl_percent = 0.1  # Placeholder for entry PL
                self.logger.info(f"ENTRY signal: {signal.upper()} at {current_datetime}, exit scheduled at {self.exit_time}")
                return {
                    'signal': signal,
                    'pl_percent': pl_percent,
                    'action': 'entry',
                    'exit_time': self.exit_time
                }
        
        return None

    def save_plot(self, csv_path=None, png_path=None, html_path=None, ema_label='EMA'):
        if not self.plot_records:
            self.logger.warning("No plot records to save")
            return {'csv': None, 'png': None}

        df = pd.DataFrame(self.plot_records)
        # Ensure datetime is a pandas datetime
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime')

        # Ensure paths go to output directory
        import os
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output')
        os.makedirs(output_dir, exist_ok=True)
        
        if csv_path and not os.path.isabs(csv_path):
            csv_path = os.path.join(output_dir, csv_path)
        if png_path and not os.path.isabs(png_path):
            png_path = os.path.join(output_dir, png_path)
        if html_path and not os.path.isabs(html_path):
            html_path = os.path.join(output_dir, html_path)

        saved = {'csv': None, 'png': None, 'html': None}
        if csv_path:
            try:
                df.to_csv(csv_path, index=False)
                saved['csv'] = csv_path
                self.logger.info(f"Saved plot CSV to {csv_path}")
            except Exception:
                self.logger.exception(f"Failed to save plot CSV to {csv_path}")

        # Use TA-Lib for EMA computation if available (align with save_plot in external tools)
        try:
            import talib
            import numpy as np
            candle_df = pd.DataFrame([
                {
                    'datetime': pd.to_datetime(dt_key),
                    'open': float(c['open']),
                    'high': float(c['high']),
                    'low': float(c['low']),
                    'close': float(c['close'])
                }
                for dt_key, c in self.candles.items()
            ])
            candle_df = candle_df.sort_values('datetime')

            # Compute EMA on close prices using TA-Lib, fallback to pandas
            if not candle_df.empty:
                try:
                    close_arr = np.asarray(candle_df['close'], dtype='float64')
                    ema_vals = talib.EMA(close_arr, timeperiod=int(self.ema_period))
                    candle_df['ema'] = ema_vals
                except Exception:
                    candle_df['ema'] = candle_df['close'].ewm(span=self.ema_period, adjust=False).mean()
            else:
                # If no candle_df, fallback to recorded df
                candle_df = df[['datetime', 'close']].copy()
                candle_df['ema'] = df['ema'] if 'ema' in df.columns else df['close'].ewm(span=self.ema_period, adjust=False).mean()

        except Exception:
            # If TA-Lib not available, build candle_df and use pandas ewm
            self.logger.exception('TA-Lib not available; using pandas ewm for EMA')
            candle_rows = []
            for dt_key, c in self.candles.items():
                candle_rows.append({
                    'datetime': pd.to_datetime(dt_key),
                    'open': float(c['open']),
                    'high': float(c['high']),
                    'low': float(c['low']),
                    'close': float(c['close'])
                })
            candle_df = pd.DataFrame(candle_rows)
            if candle_df.empty:
                candle_df = df.reset_index()[['datetime', 'close']].rename(columns={'datetime': 'datetime'})
                candle_df['ema'] = candle_df['close'].ewm(span=self.ema_period, adjust=False).mean()
            else:
                candle_df = candle_df.sort_values('datetime')
                candle_df['ema'] = candle_df['close'].ewm(span=self.ema_period, adjust=False).mean()

        # Attempt to create interactive Plotly HTML and PNG via kaleido
        if html_path or png_path:
            try:
                import plotly.graph_objects as go
                fig = go.Figure()
                if 'open' in candle_df.columns and not candle_df.empty:
                    fig.add_trace(go.Candlestick(
                        x=candle_df['datetime'],
                        open=candle_df['open'],
                        high=candle_df['high'],
                        low=candle_df['low'],
                        close=candle_df['close'],
                        name='Price'
                    ))
                    if 'ema' in candle_df.columns and candle_df['ema'].notnull().any():
                        fig.add_trace(go.Scatter(x=candle_df['datetime'], y=candle_df['ema'], mode='lines', name=ema_label, line=dict(color='blue')))
                else:
                    # fallback to line chart
                    fig.add_trace(go.Scatter(x=df['datetime'], y=df['close'], mode='lines', name='Close'))
                    if 'ema' in df.columns:
                        fig.add_trace(go.Scatter(x=df['datetime'], y=df['ema'], mode='lines', name=ema_label))

                fig.update_layout(xaxis_rangeslider_visible=False, title='Candlestick chart with EMA')

                if png_path:
                    try:
                        fig.write_image(png_path)
                        saved['png'] = png_path
                        self.logger.info(f"Saved plot PNG to {png_path}")
                    except Exception:
                        self.logger.exception(f"Failed to save plot PNG to {png_path} via plotly/kaleido")

                if html_path:
                    try:
                        fig.write_html(html_path, include_plotlyjs='cdn', full_html=True)
                        saved['html'] = html_path
                        self.logger.info(f"Saved interactive Plotly HTML to {html_path}")
                    except Exception:
                        self.logger.exception(f"Failed to save interactive HTML to {html_path}")

            except Exception:
                self.logger.exception('Plotly not available; falling back to PNG-embedded HTML')
                # Fallback: embed CSV or create simple HTML with CSV link
                if html_path:
                    try:
                        html = """<!doctype html>
<html>
  <head><meta charset='utf-8'><title>Candlestick chart</title></head>
  <body>
    <h3>Candlestick chart with EMA (no interactive plotting available)</h3>
    <p>CSV: {csv}</p>
  </body>
</html>""".format(csv=saved.get('csv', ''))
                        with open(html_path, 'w', encoding='utf-8') as fh:
                            fh.write(html)
                        saved['html'] = html_path
                        self.logger.info(f"Saved fallback HTML to {html_path}")
                    except Exception:
                        self.logger.exception(f"Failed to save fallback HTML to {html_path}")

        # Write HTML that embeds the PNG as base64 if requested
        if html_path:
            # Prefer interactive Plotly HTML if plotly is available
            try:
                import plotly.graph_objects as go
                # Build candlestick DataFrame
                candle_rows = []
                for dt_key, c in self.candles.items():
                    candle_rows.append({
                        'datetime': pd.to_datetime(dt_key),
                        'open': float(c['open']),
                        'high': float(c['high']),
                        'low': float(c['low']),
                        'close': float(c['close'])
                    })
                candle_df = pd.DataFrame(candle_rows)
                if candle_df.empty:
                    # No candles -> fallback to PNG-embedded HTML below
                    raise ImportError('No candle data for Plotly')

                candle_df = candle_df.sort_values('datetime')
                # Merge EMA into candles if available
                df_ema = df[['datetime', 'ema']].dropna()
                if not df_ema.empty:
                    candle_df = pd.merge(candle_df, df_ema, on='datetime', how='left')

                fig = go.Figure()
                fig.add_trace(go.Candlestick(
                    x=candle_df['datetime'],
                    open=candle_df['open'],
                    high=candle_df['high'],
                    low=candle_df['low'],
                    close=candle_df['close'],
                    name='Price'))
                if 'ema' in candle_df.columns and candle_df['ema'].notnull().any():
                    fig.add_trace(go.Scatter(x=candle_df['datetime'], y=candle_df['ema'], mode='lines', name=ema_label, line=dict(color='blue')))

                fig.update_layout(xaxis_rangeslider_visible=False, title='Candlestick chart with EMA')
                # Write interactive HTML (embed Plotly JS)
                try:
                    fig.write_html(html_path, include_plotlyjs='cdn', full_html=True)
                except Exception:
                    # fallback to embedding JS directly
                    fig.write_html(html_path, include_plotlyjs=True, full_html=True)

                saved['html'] = html_path
                self.logger.info(f"Saved interactive Plotly HTML to {html_path}")
            except Exception:
                # Fallback: embed PNG as base64 in HTML
                try:
                    # Simple HTML fallback that links to the CSV containing price and EMA
                    import html as _html
                    csv_link = saved.get('csv', '')
                    html_content = f"""<!doctype html>
<html>
  <head><meta charset='utf-8'><title>Candlestick chart</title></head>
  <body>
    <h3>Candlestick chart with EMA (no interactive plotting available)</h3>
    <p>CSV with data: {_html.escape(csv_link)}</p>
  </body>
</html>"""
                    with open(html_path, 'w', encoding='utf-8') as fh:
                        fh.write(html_content)
                    saved['html'] = html_path
                    self.logger.info(f"Saved fallback HTML to {html_path}")
                except Exception:
                    self.logger.exception(f"Failed to save fallback HTML to {html_path}")

        return saved