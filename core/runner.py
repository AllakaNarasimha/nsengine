"""
Strategy runner module for NS Engine backtesting framework.
Contains the main StrategyRunner class that orchestrates backtesting execution.
"""

import pandas as pd
import logging
import numpy as np
import os
import sys
from collections import deque
from datetime import time as dtime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.utils import calculate_ohlc_fast
from core.config import AppConfig
from core.journal import TradeJournal

from strategies.ema_strategy import EMAStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.scalper_strategy import ScalperStrategy
from strategies.orb_strategy import ORBStrategy
from data.data_manager import DataManager
from data.trade_manager import TradeManager
from nslogger.history_data_manager import HistoryDataManager
from charts.ns_mplchart import MplChart
from charts.ns_tvchart import TvChart


class StrategyRunner:
    """
    Main strategy runner that orchestrates backtesting execution.
    Aggregates ticks into higher timeframe candles and executes signals on candle close.
    """
    
    def __init__(self, config: AppConfig):
        """
        Initialize the strategy runner with configuration.
        
        Args:
            config (AppConfig): Application configuration
        """
        self.cfg = config
        self.logger = logging.getLogger(__name__)
        self.journal = TradeJournal(config.trades_csv)
        self.strategy = self._get_strategy()
        
        # Initialize data managers
        self.hdm = HistoryDataManager(
            db_dir=config.db_dir,
            db_date=config.start_date,
            db_suffix='history.db'
        )
        self.data_manager = DataManager(
            config.db_dir,
            config.symbol,
            config.underlying,
            config.segment,
            config.instrument_type,
            multi_db_base_path=config.db_dir,
            interval=1,
            unit='seconds'
        )
        
        # Initialize trading components
        self.lot_size = self._get_lot_size()
        self.trade_manager = TradeManager(
            self.lot_size,
            pl_percent=getattr(self.cfg, 'pl_percent', 0.5),
            start_time=getattr(self.cfg, 'start_time', None),
            end_time=getattr(self.cfg, 'end_time', None)
        )

        # Candle aggregation state
        self.tick_buffer = deque()
        self.current_candle_start = None
        self.candle_freq = getattr(config, 'candle_freq', '5min')
        self.candle_interval = pd.Timedelta(self.candle_freq)

        # Candle dataframe with all required columns
        self.candles_df = pd.DataFrame(
            columns=['open', 'high', 'low', 'close', 'volume', 'signal']
        ).astype({
            'open': 'float64',
            'high': 'float64',
            'low': 'float64',
            'close': 'float64',
            'volume': 'float64',
            'signal': 'object'
        })
        
        # Add indicator columns
        for col in ['pivot_time', 'pivot_high', 'pivot_low', 'pivot_direction', 'range_high', 'range_low']:
            dtype = 'float64' if any(x in col for x in ['high', 'low', 'range']) else 'object'
            self.candles_df[col] = pd.Series(dtype=dtype)
        
        self.max_candles = 1000

        # Chart initialization
        self.mpl_chart = MplChart() if getattr(config, 'chart_library', 'mpl') == 'mpl' else None
        self.tv_chart = None
        if getattr(config, 'chart_library', 'mpl') == 'tv':
            try:
                self.tv_chart = TvChart(config)
            except Exception:
                self.logger.exception("Failed to initialize TvChart")

        # Performance tracking
        self.performance_stats = {
            'candles_built': 0,
            'jit_ohlc_calls': 0,
            'plots_throttled': 0
        }
        self.ema_cache = {'last_update': 0}

        # Execution state
        self.signal_count = 0
        self.trade_count = 0
        self.last_signal_candle = None
        self.last_signal_val = None
        self.completed_trades = []

        # Plot throttling
        self.last_plot_time = 0.0
        self.ticks_since_last_plot = 0
        self.plot_interval = 2.0
        self.min_ticks_between_plots = 200

        # Helper state
        self._entry_stop_map = {}
        self._first_trail_logged = set()
        self.pending_signal = None
        self.option_chain_cache = None

        # Parse end time
        try:
            self.end_time = self._parse_time(getattr(self.cfg, 'end_time', None))
        except Exception:
            self.end_time = getattr(self.cfg, 'end_time', None)

    def _get_strategy(self):
        """
        Initialize strategy based on configuration.
        
        Returns:
            Strategy: Configured strategy instance
        """
        params = self.cfg.strategy_params or {}
        stype = self.cfg.strategy_type

        # Set default parameters if not provided
        if not params:
            if stype == 'ema':
                params = {'short_period': 5, 'long_period': 20}
            elif stype == 'rsi':
                params = {'period': 14, 'oversold': 30, 'overbought': 70}
            elif stype == 'scalper':
                params = {'run_candle': 1, 'ema_min': 5, 'ema_period': 21}
            elif stype == 'orb':
                params = {}

        # Create strategy with filtered parameters
        if stype == 'ema':
            allowed = {'short_period', 'long_period'}
            clean = {k: v for k, v in params.items() if k in allowed}
            return EMAStrategy(**clean)
        elif stype == 'rsi':
            allowed = {'period', 'oversold', 'overbought'}
            clean = {k: v for k, v in params.items() if k in allowed}
            return RSIStrategy(**clean)
        elif stype == 'scalper':
            allowed = {'run_candle', 'ema_min', 'ema_period', 'stop_loss_pct', 'trailing_stop_pct'}
            clean = {k: v for k, v in params.items() if k in allowed}
            return ScalperStrategy(**clean)
        elif stype == 'orb':
            allowed = {
                'range_minutes', 'max_trades_per_day', 'candle_granularity',
                'opening_range_bars', 'stop_loss_pct', 'trailing_stop_pct',
                'target_pct', 'require_boundary_touch'
            }
            clean = {k: v for k, v in params.items() if k in allowed}
            clean['external_candles'] = True
            
            if 'candle_granularity' not in clean:
                freq = getattr(self.cfg, 'candle_freq', '1min')
                clean['candle_granularity'] = 'hour' if 'H' in freq or 'hour' in freq else 'minute'
            
            if 'target_pct' not in clean:
                legacy_tp = params.get('pl_percent') or getattr(self.cfg, 'pl_percent', None)
                if legacy_tp is not None:
                    clean['target_pct'] = legacy_tp
            
            return ORBStrategy(**clean)
        else:
            raise ValueError(f'Unknown strategy_type: {stype}')

    def _get_lot_size(self):
        """
        Get lot size for the symbol from instrument info.
        
        Returns:
            int: Lot size
        """
        instrument_df = self.hdm.get_instrument_info(self.cfg.symbol)
        df_fut = instrument_df[
            (instrument_df['name'] == self.cfg.symbol) &
            (instrument_df['instrument_type'] == "FUT")
        ]
        
        if not df_fut.empty:
            df_fut = df_fut.copy()
            df_fut['expiry_date'] = pd.to_datetime(df_fut['expiry'])
            df_fut = df_fut.sort_values('expiry_date')
            if len(df_fut) > self.cfg.expiry_index:
                return int(df_fut.iloc[self.cfg.expiry_index]['lot_size'])
        return 0

    def _write_tv_placeholder(self):
        """Write TradingView placeholder if configured."""
        if not self.tv_chart:
            return
        try:
            self.tv_chart.write_placeholder()
        except Exception:
            self.logger.exception("Failed to write TV placeholder")

    def build_candle_from_ticks(self, ticks):
        """
        Build OHLCV candle from tick data.
        
        Args:
            ticks (list): List of tick dictionaries
            
        Returns:
            tuple: (candle_datetime, candle_dict) or (None, None)
        """
        if not ticks:
            return None, None

        candle_dt = pd.to_datetime(ticks[0]['datetime']).floor(self.candle_freq)
        
        # Extract prices and volumes
        prices = np.array([t['price'] for t in ticks], dtype=np.float64)
        volumes = np.array([t.get('volume', 1.0) for t in ticks], dtype=np.float64)
        
        # Calculate OHLC using JIT-compiled function
        open_price, high_price, low_price, close_price = calculate_ohlc_fast(prices)
        
        self.performance_stats['candles_built'] += 1
        self.performance_stats['jit_ohlc_calls'] += 1

        candle = {
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': np.sum(volumes),
            'signal': None
        }

        return candle_dt, candle

    def append_candle(self, candle_data):
        """
        Append candle to dataframe with chart updates.
        
        Args:
            candle_data (tuple): (candle_datetime, candle_dict)
        """
        if candle_data[0] is None:
            return

        candle_dt, candle = candle_data
        candle_df_row = pd.DataFrame([candle], index=[candle_dt])

        if candle_dt not in self.candles_df.index:
            if self.candles_df.empty:
                self.candles_df = candle_df_row.copy()
                # Render first candle immediately
                if self.mpl_chart:
                    try:
                        self.mpl_chart.update(self.candles_df, self.completed_trades, self.performance_stats)
                    except Exception:
                        pass
                if self.tv_chart:
                    try:
                        self.tv_chart.maybe_export(self.candles_df, self.completed_trades, force=True)
                    except Exception:
                        pass
            else:
                self.candles_df = pd.concat([self.candles_df, candle_df_row], ignore_index=False)

            # Keep only recent candles
            self.candles_df = self.candles_df.tail(self.max_candles)
            self.ema_cache['last_update'] = 0
            
            self.logger.debug(
                f"Added candle for {candle_dt}: "
                f"O={candle['open']}, H={candle['high']}, L={candle['low']}, C={candle['close']}"
            )

    def run_backtest(self):
        """Execute the backtesting loop."""
        self.logger.info(f"Starting backtest for {self.cfg.symbol}")
        self._write_tv_placeholder()
        
        self.data_manager.load_data(
            start_date=self.cfg.start_date,
            end_date=self.cfg.end_date,
            use_multi_db=self.cfg.use_multi_db,
            preprocessing_days=self.cfg.preprocessing_days
        )
        
        current_date = None
        while True:
            # Get next data point
            price_dt = self.data_manager.get_next_data_point_with_volume()
            if isinstance(price_dt, tuple):
                price, dt, volume = price_dt
            else:
                price, dt = price_dt
                volume = 1.0
            
            if price is None:
                # Finalize last candle
                if self.tick_buffer:
                    candle = self.build_candle_from_ticks(list(self.tick_buffer))
                    self.append_candle(candle)
                    self.tick_buffer.clear()
                break
            
            dt = pd.to_datetime(dt)
            if self.current_candle_start is None:
                self.current_candle_start = dt.floor(self.candle_freq)
            
            tick_candle_start = dt.floor(self.candle_freq)

            # Per-tick strategy update
            per_tick_signal = None
            try:
                per_tick = self.strategy.update(price=price, current_datetime=dt)
                if per_tick:
                    per_tick_signal = per_tick.get('signal') if isinstance(per_tick, dict) else per_tick
                    
                    if per_tick_signal in ('buy', 'sell') and self.pending_signal is None:
                        self.pending_signal = {
                            'signal': per_tick_signal,
                            'raw': per_tick,
                            'bar_start': self.current_candle_start,
                            'price': price,
                            'dt': dt
                        }
            except Exception:
                pass

            # Handle candle boundary
            if tick_candle_start > self.current_candle_start:
                self._handle_candle_close(tick_candle_start)
                self.current_candle_start = tick_candle_start

            # Accumulate tick
            self.tick_buffer.append({'price': price, 'datetime': dt, 'volume': volume})
            
            # Refresh option chain once per second
            date_dt = dt.replace(microsecond=0)
            if current_date is None or date_dt != current_date:
                current_date = date_dt
                try:
                    self.data_manager.load_option_chain(date_dt.strftime('%Y-%m-%d %H:%M:%S'), price)
                except Exception:
                    pass

        self.logger.info(f"Backtest finished: signals={self.signal_count}, trades={self.trade_count}")
        self._finalize_backtest()

    def _handle_candle_close(self, next_candle_start):
        """Handle close of previous candle and process signals."""
        if not self.tick_buffer:
            return

        candle = self.build_candle_from_ticks(list(self.tick_buffer))
        self.append_candle(candle)
        
        if candle[0] is not None:
            candle_dt, candle_data = candle
            self._process_candle_signals(candle_dt, candle_data)
            self._update_charts()

        self.tick_buffer.clear()

    def _process_candle_signals(self, candle_dt, candle_data):
        """Process trading signals for closed candle."""
        # Inject indicators
        try:
            inds = getattr(self.strategy, 'get_indicators', lambda: {})() or {}
            if candle_dt in self.candles_df.index:
                for k in ['pivot_time', 'pivot_high', 'pivot_low', 'pivot_direction', 'range_high', 'range_low']:
                    if k in inds:
                        self.candles_df.at[candle_dt, k] = inds[k]
                for k in ['pivot_high', 'pivot_low', 'range_high', 'range_low']:
                    try:
                        self.candles_df[k] = self.candles_df[k].ffill()
                    except Exception:
                        pass
        except Exception:
            pass

        # Determine which signal to execute
        exec_sig_val = None
        if self.pending_signal and self.pending_signal.get('bar_start') == self.current_candle_start:
            exec_sig_val = self.pending_signal['signal']
        else:
            try:
                close_out = self.strategy.update(price=candle_data['close'], current_datetime=candle_dt)
            except (TypeError, Exception):
                close_out = None
            
            if close_out:
                exec_sig_val = close_out.get('signal') if isinstance(close_out, dict) else close_out

        # Execute signal if valid
        if exec_sig_val in ('buy', 'sell'):
            if not (self.last_signal_candle == candle_dt and self.last_signal_val == exec_sig_val):
                self.signal_count += 1
                self.last_signal_candle = candle_dt
                self.last_signal_val = exec_sig_val
                
                self.logger.info(
                    f"Signal #{self.signal_count}: {exec_sig_val} at {candle_dt} "
                    f"close={candle_data['close']}"
                )
                
                trade_data = self._process_trade_for_signal(candle_dt, candle_data['close'], exec_sig_val)
                self._update_candle_signal(candle_dt, exec_sig_val, trade_data)

        if self.pending_signal and self.pending_signal.get('bar_start') == self.current_candle_start:
            self.pending_signal = None

        # End-of-day close enforcement
        ses_close = self.close_trade_on_endtime(candle_dt, candle_data['close'])
        if ses_close in ('buy', 'sell') and candle_dt in self.candles_df.index:
            self.candles_df.at[candle_dt, 'signal'] = ses_close

        # Trailing log
        try:
            self._maybe_log_first_trail(candle_dt)
        except Exception:
            pass

    def _update_candle_signal(self, candle_dt, sig_val, trade_data):
        """Update candle signal column."""
        try:
            if candle_dt in self.candles_df.index:
                existing = self.candles_df.at[candle_dt, 'signal']
                sigs = []
                
                if existing is not None and existing != '':
                    sigs = [s.strip() for s in (existing.split(',') if isinstance(existing, str) else existing)]
                
                if sig_val not in sigs:
                    sigs.append(sig_val)
                
                if trade_data and isinstance(trade_data, dict) and trade_data.get('position_state') in ['closed', 'exit']:
                    pos_type = trade_data.get('position_type')
                    close_sig = 'sell' if pos_type == 'long' else 'buy'
                    if close_sig not in sigs:
                        sigs.append(close_sig)
                
                self.candles_df.at[candle_dt, 'signal'] = ','.join(sigs)
        except Exception:
            pass

    def _update_charts(self):
        """Update all configured charts."""
        if self.mpl_chart:
            try:
                self.mpl_chart.update(self.candles_df, self.completed_trades, self.performance_stats)
            except Exception:
                pass
        
        if self.tv_chart:
            try:
                self.tv_chart.maybe_export(self.candles_df, self.completed_trades)
            except Exception:
                pass

    def _finalize_backtest(self):
        """Finalize backtest and export results."""
        try:
            if self.cfg.export_csv and hasattr(self.strategy, 'save_plot'):
                base = self.cfg.export_csv.rsplit('.', 1)[0]
                self.strategy.save_plot(
                    csv_path=self.cfg.export_csv,
                    png_path=f'{base}.png',
                    html_path=f'{base}.html'
                )
        except Exception:
            self.logger.exception("Plot export failed")
        
        self.journal.summarize()
        
        if self.tv_chart:
            try:
                self.tv_chart.export_final(self.candles_df, self.completed_trades)
            except Exception:
                self.logger.exception("Failed to export final TV chart")

    def _process_trade_for_signal(self, candle_dt, price, signal_val):
        """Process trade for given signal."""
        try:
            option_data = self.get_option_data(candle_dt, price, signal_val) or {}
            if option_data is None or len(option_data) == 0:
                self.data_manager.clear_all_caches()
                option_data = self.get_option_data(candle_dt, price, signal_val)
                if option_data is None:
                    return None
            
            indicators = getattr(self.strategy, 'get_indicators', lambda: {})() or {}
            self.logger.info(
                f"Processing signal '{signal_val}' at {candle_dt} price={price} "
                f"option_data_present={bool(option_data)}"
            )
            
            trade_data = self.trade_manager.process_signal(
                signal_val, price, candle_dt, indicators, option_data,
                pl_percent=self.cfg.pl_percent
            )
            
            self.update_trade_data(candle_dt, price, trade_data)
            return trade_data
        except Exception:
            self.logger.exception("Trade processing failed")
        return None

    def update_trade_data(self, candle_dt, price, trade_data):
        """Update trade data and track completed trades."""
        if not trade_data:
            return
        
        self.trade_count += 1
        self.journal.save_trade(
            trade_data,
            {'symbol': self.cfg.symbol, 'instrument_type': self.cfg.instrument_type}
        )

        # Track completed trades
        if trade_data.get('position_state') in ['closed', 'exit'] and 'profit_loss' in trade_data:
            entry_dt = trade_data.get('entry_datetime') or candle_dt
            exit_dt = trade_data.get('exit_datetime') or candle_dt
            
            self.completed_trades.append({
                'entry_datetime': pd.to_datetime(entry_dt),
                'exit_datetime': pd.to_datetime(exit_dt),
                'stop_loss': trade_data.get('stop_loss', None),
                'position_type': trade_data.get('position_type'),
                'entry_price': trade_data.get('entry_price', price),
                'exit_price': price,
                'option_symbol': trade_data.get('option_symbol', ''),
                'entry_option_price': trade_data.get('entry_option_price', 0),
                'exit_option_price': trade_data.get('exit_option_price', 0),
                'pl': trade_data['profit_loss'],
                'trade_id': trade_data.get('trade_id', f'T{self.trade_count}')
            })
            
            if isinstance(trade_data, dict) and trade_data.get('position_state') in ['closed', 'exit']:
                self.trade_manager.position = None

    def get_option_data(self, candle_dt, price, signal):
        """Get option data with retries."""
        option_data = self.get_option_data_with_cache(candle_dt, price, signal)
        
        if option_data is None or len(option_data) == 0:
            option_data = self.get_option_data_with_cache(candle_dt, price, signal, clear_cache=True)
            counter = 0
            
            while counter < 20 and (option_data is None or len(option_data) == 0):
                price, dt, volume = self.data_manager.get_next_data_point_with_volume()
                option_data = self.get_option_data_with_cache(dt, price, signal, clear_cache=True)
                counter += 1
        
        if option_data is None or len(option_data) == 0:
            self.logger.warning("No option data available even after retries")
        
        return option_data

    def get_option_data_with_cache(self, candle_dt, price, signal, clear_cache=False):
        """Get option data with optional cache clearing."""
        if clear_cache:
            self.data_manager.clear_all_caches()
        
        ts_str = candle_dt.strftime('%Y-%m-%d %H:%M:%S')
        self.option_chain_cache = self.data_manager.load_option_chain(ts_str, price)
        option_chain = self.option_chain_cache
        option_data = None

        if self.trade_manager.position is not None:
            entry_option_info = self.option_chain_cache[
                self.option_chain_cache['instrument_token'] == self.trade_manager.entry_instrument_token
            ]
            if not entry_option_info.empty:
                option_data = {
                    'option_symbol': entry_option_info.iloc[0].get('tradingsymbol',
                                                                   entry_option_info.iloc[0].get('symbol', '')),
                    'option_type': entry_option_info.iloc[0].get('option_type', ''),
                    'strike_price': entry_option_info.iloc[0].get('strike', 0),
                    'option_price': entry_option_info.iloc[0].get('option_price',
                                                                   entry_option_info.iloc[0].get('last_price', 0)),
                    'instrument_token': entry_option_info.iloc[0].get('instrument_token', None)
                }
        elif option_chain is not None and not option_chain.empty:
            option_type = 'CE' if signal == 'buy' else 'PE'
            atm_option = self.data_manager.find_atm_option(price, option_chain, option_type)
            
            if atm_option is not None:
                option_data = {
                    'option_symbol': atm_option.get('tradingsymbol', atm_option.get('symbol', '')),
                    'option_type': option_type,
                    'strike_price': atm_option.get('strike', 0),
                    'option_price': atm_option.get('option_price', atm_option.get('last_price', 0)),
                    'instrument_token': atm_option.get('instrument_token', None)
                }

        return option_data

    def _parse_time(self, t):
        """Parse time string to datetime.time object."""
        if t is None:
            return None
        
        if isinstance(t, dtime):
            return t
        
        if isinstance(t, int):
            if 0 <= t <= 23:
                return dtime(t, 0)
            self.logger.warning(f"Invalid hour: {t}")
            return None
        
        if isinstance(t, str):
            s = t.strip()
            if not s:
                return None
            
            try:
                parts = s.split(':')
                if len(parts) == 2:
                    h, m = int(parts[0]), int(parts[1])
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        return dtime(h, m)
                self.logger.warning(f"Invalid time string: {t}")
            except Exception:
                self.logger.exception(f"Failed to parse time: {t}")
            return None
        
        self.logger.warning(f"Unsupported time type: {type(t)}")
        return None

    def close_trade_on_endtime(self, candle_dt, price):
        """Enforce end-of-day position closing."""
        try:
            candle_start = pd.to_datetime(candle_dt)
            try:
                candle_end_dt = candle_start + getattr(self, 'candle_interval', pd.Timedelta('0s'))
            except Exception:
                candle_end_dt = candle_start
            
            ct = candle_end_dt.time()
        except Exception:
            return None

        configured_end = getattr(self, 'end_time', None) or getattr(self.trade_manager, '_end_time', None)
        
        if self.trade_manager.position is not None and configured_end and ct >= configured_end:
            try:
                indicators = getattr(self.strategy, 'get_indicators', lambda: {})()
                option_data = self.get_option_data(candle_dt, price, signal=None)
                
                if option_data is None:
                    option_data = self.get_option_data(candle_dt, price, signal=None)
                    if option_data is None:
                        return None
                
                trade_data = self.trade_manager.enforce_session_constraints(
                    price, candle_dt, option_data=option_data, indicators=indicators
                )
                self.update_trade_data(candle_dt, price, trade_data)
                
                if trade_data is not None:
                    return "sell" if trade_data['position_type'] == 'long' else "buy"
            except Exception:
                self.logger.exception("Failed to enforce session constraints")
        
        return None

    def _maybe_log_first_trail(self, candle_dt):
        """Log trailing stop movement if favorable."""
        tm = self.trade_manager
        if tm.position is None:
            return
        
        trade_id = tm.trade_id
        if trade_id in self._first_trail_logged:
            return
        
        entry_sl = self._entry_stop_map.get(trade_id)
        if entry_sl is None:
            return
        
        try:
            inds = getattr(self.strategy, 'get_indicators', lambda: {})() or {}
        except Exception:
            inds = {}
        
        cur_sl = inds.get('stop_loss') or inds.get('stop_loss_price')
        if cur_sl is None:
            return
        
        try:
            cur_sl = float(cur_sl)
            entry_sl = float(entry_sl)
        except Exception:
            return
        
        moved = False
        if tm.position == 'long' and cur_sl > entry_sl:
            moved = True
        elif tm.position == 'short' and cur_sl < entry_sl:
            moved = True
        
        if not moved:
            return
        
        # Calculate first P&L
        first_pl_val = ''
        try:
            if self.option_chain_cache is not None and tm.entry_instrument_token is not None:
                oc_row = self.option_chain_cache[
                    self.option_chain_cache['instrument_token'] == tm.entry_instrument_token
                ]
                if not oc_row.empty:
                    cur_opt_price = oc_row.iloc[0].get('option_price',
                                                       oc_row.iloc[0].get('last_price', None))
                    if cur_opt_price is not None and tm.entry_option_price not in (None, 0):
                        if tm.position == 'long':
                            first_pl_val = (cur_opt_price - tm.entry_option_price) * tm.lot_size
                        else:
                            first_pl_val = (tm.entry_option_price - cur_opt_price) * tm.lot_size
        except Exception:
            pass
        
        if first_pl_val == '':
            try:
                locked_points = max(0.0, cur_sl - tm.entry_price if tm.position == 'long'
                                    else tm.entry_price - cur_sl)
                first_pl_val = locked_points * tm.lot_size
            except Exception:
                first_pl_val = ''
        
        trail_record = {
            'trade_id': trade_id,
            'entry_datetime': tm.entry_datetime,
            'exit_datetime': None,
            'entry_price': tm.entry_price,
            'exit_price': None,
            'entry_option_price': tm.entry_option_price,
            'exit_option_price': None,
            'position_type': tm.position,
            'action': 'first_trail',
            'position_state': 'open',
            'profit_loss': 0.0,
            'lot_size': tm.lot_size,
            'first_pl': first_pl_val,
            'stop_loss': cur_sl
        }
        
        try:
            trail_record.update(inds)
        except Exception:
            pass
        
        self.journal.save_trade(
            trail_record,
            {'symbol': self.cfg.symbol, 'instrument_type': self.cfg.instrument_type}
        )
        self._first_trail_logged.add(trade_id)

    def run(self):
        """Run the backtest."""
        self.run_backtest()
