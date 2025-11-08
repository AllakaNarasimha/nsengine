import pandas as pd
import time
from datetime import time as dtime
import os
import logging
import numpy as np
import sys

from collections import deque
from numba import jit

# Add parent directory to path for relative imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import from organized modules
from strategies.ema_strategy import EMAStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.scalper_strategy import ScalperStrategy
from strategies.orb_strategy import ORBStrategy
from data.data_manager import DataManager
from data.trade_manager import TradeManager
from nslogger.history_data_manager import HistoryDataManager
from charts.ns_mplchart import MplChart
from charts.ns_tvchart import TvChart

# JIT-compiled functions for performance optimization
@jit(nopython=True, cache=True)
def calculate_ohlc_fast(prices):
    """Fast OHLC calculation using Numba JIT compilation"""
    if len(prices) == 0:
        return 0.0, 0.0, 0.0, 0.0
    elif len(prices) == 1:
        price = prices[0]
        return price, price, price, price
    else:
        return prices[0], np.max(prices), np.min(prices), prices[-1]

@jit(nopython=True, cache=True)
def should_throttle_plot(current_time, last_plot_time, ticks_count, min_interval, min_ticks):
    """Fast throttling check using JIT compilation"""
    return (current_time - last_plot_time >= min_interval and ticks_count >= min_ticks)

@jit(nopython=True, cache=True)
def validate_cache_size(cache_len, data_len):
    """Fast cache validation using JIT compilation"""
    return cache_len == data_len and cache_len > 0

class AppConfig:
    def __init__(self, **kwargs):
        default_cfg = dict(
            db_dir=None, symbol=None, underlying=None, segment=None,
            instrument_type=None, strategy_type='ema', strategy_params=None,
            data_mode='historical', initialization_periods=50, live=False,
            trades_csv='trading_journal.csv', expiry_index=0, start_date=None,
            end_date=None, start_time="09:15", end_time="15:00", use_multi_db=False, preprocessing_days=3,
            export_csv=None, pl_percent=0.5, candle_freq='1min',
            chart_library='mpl',  # 'mpl' or 'tv'
            tv_autoupdate=False,   # if True, regenerate TV HTML every tv_update_every candles
            tv_update_every=5,     # frequency (in completed candles) for auto export
            tv_refresh_seconds=0,  # if >0, inject meta refresh tag into HTML for auto reload
            tv_auto_open=False,    # if True, open HTML in browser on first export
            tv_pl_padding=2,       # number of "\n" lines to pad P&L marker text to shift vertically
            tv_pl_multiline=False, # if True show each P&L on its own line when multiple trades exit same candle
            tv_pl_color_scale=True, # scale marker color intensity by absolute P&L
            show_pl_line=True,      # plot cumulative P&L line in TV (and MPL) charts
            pl_line_hover_only=False, # if True show PL line only on hover
            tv_volume_ratio=0.25     # fraction (0.10-0.50) of vertical space for volume pane
            ,tv_pl_separate_panel=False # if True render cumulative P&L in its own chart below
            ,volume_mode='tick_count' # how to derive volume: tick_count | price_range | abs_return | real
            # session_close_time removed: strategy now responsible for EOD logic
        )
        for k, v in default_cfg.items():
            setattr(self, k, kwargs.get(k, v))


class TradeJournal:
    def __init__(self, trades_csv):
        self.trades_csv =  trades_csv
        self.cumulative_pnl = 0
        logging.basicConfig(filename='trading.log', level=logging.INFO,
                            format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

    def save_trade(self, trade_data, meta):
        # Normalize datetimes for storage
        entry_dt = trade_data.get('entry_datetime')
        exit_dt = trade_data.get('exit_datetime')
        if entry_dt is not None:
            try:
                entry_dt = pd.to_datetime(entry_dt)
            except Exception:
                entry_dt = None
        if exit_dt is not None:
            try:
                exit_dt = pd.to_datetime(exit_dt)
            except Exception:
                exit_dt = None

        # Prepare the new/updated journal row
        journal_entry = {
            'trade_id': trade_data.get('trade_id'),
            'symbol': meta['symbol'],
            'instrument_type': meta['instrument_type'],
            'position_type': trade_data.get('position_type'),
            'action': trade_data.get('action'),
            'position_state': trade_data.get('position_state'),
            'entry_datetime': entry_dt.strftime('%Y-%m-%d %H:%M:%S') if entry_dt is not None else '',
            'exit_datetime': exit_dt.strftime('%Y-%m-%d %H:%M:%S') if exit_dt is not None else '',
            'entry_price': round(trade_data.get('entry_price', 0) or 0, 2),
            'exit_price': round(trade_data.get('exit_price', 0) or 0, 2),
            'entry_option_price': round(trade_data.get('entry_option_price', 0) or 0, 2),
            'exit_option_price': round(trade_data.get('exit_option_price', 0) or 0, 2),
            'lot_size': trade_data.get('lot_size', 0),
            'profit_loss': round(trade_data.get('profit_loss', 0) or 0, 2),
            'option_symbol': trade_data.get('option_symbol', ''),
            'option_type': trade_data.get('option_type', ''),
            'strike_price': trade_data.get('strike_price', 0),
            'cumulative_pnl': 0.0
        }

        # If CSV exists, try to update an existing row for the same trade_id and symbol when closing
        if os.path.exists(self.trades_csv):
            try:
                df = pd.read_csv(self.trades_csv)
            except Exception:
                df = pd.DataFrame()
        else:
            df = pd.DataFrame()

        updated = False
        tid = journal_entry.get('trade_id')
        sym = journal_entry.get('symbol')
        action = journal_entry.get('action')

        if not df.empty and tid is not None:
            # Prefer to update an existing OPEN/entry row for this trade_id and symbol
            # Consider rows where exit_datetime is empty or NaN as open
            try:
                exit_empty = df['exit_datetime'].isna() | (df['exit_datetime'].astype(str).str.strip() == '')
            except Exception:
                # If column missing or unexpected types, treat all as not empty
                exit_empty = pd.Series([False] * len(df))

            mask_open = (df.get('trade_id') == tid) & (df.get('symbol') == sym) & exit_empty
            if mask_open.any():
                # Update the most recent open row (last index)
                idx = df[mask_open].index[-1]
                if journal_entry['exit_datetime']:
                    df.at[idx, 'exit_datetime'] = journal_entry['exit_datetime']
                if journal_entry['exit_price']:
                    df.at[idx, 'exit_price'] = journal_entry['exit_price']
                if journal_entry['exit_option_price']:
                    df.at[idx, 'exit_option_price'] = journal_entry['exit_option_price']
                # Always update profit/position_state/action on close
                df.at[idx, 'profit_loss'] = journal_entry['profit_loss']
                df.at[idx, 'position_state'] = journal_entry['position_state']
                df.at[idx, 'action'] = journal_entry['action']
                updated = True
            else:
                # No open row found. If this is an entry action, avoid creating duplicates:
                if action == 'entry':
                    try:
                        # Look for an identical open entry (same symbol, position_type and entry_datetime)
                        same_entry_mask = (
                            (df.get('symbol') == sym) &
                            (df.get('action') == 'entry') &
                            (df.get('position_type') == journal_entry.get('position_type')) &
                            ((df.get('entry_datetime').astype(str) == journal_entry.get('entry_datetime')))
                        )
                        if same_entry_mask.any():
                            updated = True  # skip append, entry already exists
                        else:
                            updated = False
                    except Exception:
                        updated = False
                else:
                    # For close without open, fall back to matching any row by trade_id & symbol and update the last one
                    mask_any = (df.get('trade_id') == tid) & (df.get('symbol') == sym)
                    if mask_any.any():
                        idx = df[mask_any].index[-1]
                        if journal_entry['exit_datetime']:
                            df.at[idx, 'exit_datetime'] = journal_entry['exit_datetime']
                        if journal_entry['exit_price']:
                            df.at[idx, 'exit_price'] = journal_entry['exit_price']
                        df.at[idx, 'profit_loss'] = journal_entry['profit_loss']
                        df.at[idx, 'position_state'] = journal_entry['position_state']
                        df.at[idx, 'action'] = journal_entry['action']
                        updated = True

        if not updated:
            # Append new row
            df = pd.concat([df, pd.DataFrame([journal_entry])], ignore_index=True)

        # Recompute cumulative_pnl
        try:
            df['profit_loss'] = pd.to_numeric(df['profit_loss'], errors='coerce').fillna(0.0)
            df['cumulative_pnl'] = df['profit_loss'].cumsum()
        except Exception:
            df['cumulative_pnl'] = 0.0

        # Write back
        df.to_csv(self.trades_csv, index=False)
        self.cumulative_pnl = float(df['cumulative_pnl'].iloc[-1]) if not df.empty else 0.0
        self.logger.info(f"Saved trade: {journal_entry.get('trade_id')}, P&L={journal_entry.get('profit_loss')}")

    def summarize(self):
        if not os.path.exists(self.trades_csv):
            self.logger.info("No trades found.")
            return
        journal = pd.read_csv(self.trades_csv)
        if not journal.empty:
            self.logger.info("BACKTEST SUMMARY:")
            self.logger.info(f"Total Trades: {len(journal)}")
            self.logger.info(f"Total P&L: {journal['profit_loss'].sum():.2f}")
            self.logger.info(f"Winning Trades: {len(journal[journal['profit_loss'] > 0])}")
            self.logger.info(f"Losing Trades: {len(journal[journal['profit_loss'] < 0])}")
            self.logger.info(f"Win Rate: {len(journal[journal['profit_loss'] > 0]) / len(journal) * 100:.2f}%")


class StrategyRunner:
    """Restored simple runner: aggregates ticks into higher timeframe candles and executes signals only on candle close."""
    def __init__(self, config: AppConfig):
        self.cfg = config
        self.logger = logging.getLogger(__name__)
        self.journal = TradeJournal(config.trades_csv)
        self.strategy = self._get_strategy()
        self.hdm = HistoryDataManager(db_dir=config.db_dir, db_date=config.start_date, db_suffix='history.db')
        self.data_manager = DataManager(
            config.db_dir, config.symbol, config.underlying, config.segment, config.instrument_type,
            multi_db_base_path=config.db_dir, interval=1, unit='seconds'
        )
        self.lot_size = self._get_lot_size()
        # Ensure TradeManager knows session start/end so it can enforce EOD closes
        self.trade_manager = TradeManager(self.lot_size, pl_percent=getattr(self.cfg, 'pl_percent', 0.5),
                                          start_time=getattr(self.cfg, 'start_time', None),
                                          end_time=getattr(self.cfg, 'end_time', None))

        # Aggregation / state
        self.tick_buffer = deque()
        self.current_candle_start = None
        # Use user-selected candle frequency (e.g. '5min')
        self.candle_freq = getattr(config, 'candle_freq', '5min')
        self.candle_interval = pd.Timedelta(self.candle_freq)

        # Candle store
        self.candles_df = pd.DataFrame(columns=['open','high','low','close','volume','signal']).astype({
            'open':'float64','high':'float64','low':'float64','close':'float64','volume':'float64','signal':'object'
        })
        # Add pivot/indicator columns up front so chart code can rely on them
        for col in ['pivot_time','pivot_high','pivot_low','pivot_direction','range_high','range_low']:
            self.candles_df[col] = pd.Series(dtype='float64' if 'high' in col or 'low' in col or 'range' in col else 'object')
        self.max_candles = 1000

        # Chart selection
        self.mpl_chart = MplChart() if getattr(config,'chart_library','mpl') == 'mpl' else None
        self.tv_chart = None
        if getattr(config,'chart_library','mpl') == 'tv':
            try:
                self.tv_chart = TvChart(config)
            except Exception:
                self.logger.exception("Failed to init TvChart; continuing without it")

        # Performance stats (subset retained)
        self.performance_stats = {
            'candles_built':0,
            'jit_ohlc_calls':0,
            'plots_throttled':0
        }
        self.ema_cache = {'last_update':0}

        # Execution counters
        self.signal_count = 0
        self.trade_count = 0
        self.last_signal_candle = None
        self.last_signal_val = None

        # Trade tracking for chart P&L markers
        self.completed_trades = []

        # Plot throttling
        self.last_plot_time = 0.0
        self.ticks_since_last_plot = 0
        self.plot_interval = 2.0
        self.min_ticks_between_plots = 200

        # ORB / trailing helpers kept (safe no-ops for other strategies)
        self._entry_stop_map = {}
        self._first_trail_logged = set()
        # Deferred intra-bar signal storage (first signal seen within candle)
        self.pending_signal = None

        # Parsed end_time for this runner (used by close_trade_on_endtime)
        try:
            # Use runner's internal parser if available
            self.end_time = self._parse_time(getattr(self.cfg, 'end_time', None))
        except Exception:
            # Fallback: keep raw config value
            self.end_time = getattr(self.cfg, 'end_time', None)

    def _get_strategy(self):
        params = self.cfg.strategy_params or {}
        stype = self.cfg.strategy_type
        if not params:
            if stype == 'ema':
                params = {'short_period': 5, 'long_period': 20}
            elif stype == 'rsi':
                params = {'period': 14, 'oversold': 30, 'overbought': 70}
            elif stype == 'scalper':
                params = {'run_candle': 1, 'ema_min': 5, 'ema_period': 21}
            elif stype == 'orb':
                params = {}
        if stype == 'ema':
            return EMAStrategy(**{k:v for k,v in params.items() if k in {'short_period','long_period'}})
        if stype == 'rsi':
            return RSIStrategy(**{k:v for k,v in params.items() if k in {'period','oversold','overbought'}})
        if stype == 'scalper':
            return ScalperStrategy(**{k:v for k,v in params.items() if k in {'run_candle','ema_min','ema_period','stop_loss_pct','trailing_stop_pct'}})
        if stype == 'orb':
            allowed = {'range_minutes','max_trades_per_day','candle_granularity','opening_range_bars','stop_loss_pct','trailing_stop_pct','target_pct','require_boundary_touch'}
            clean = {k:v for k,v in params.items() if k in allowed}
            clean['external_candles'] = True
            if 'candle_granularity' not in clean:
                freq = getattr(self.cfg,'candle_freq','5min')
                clean['candle_granularity'] = 'hour' if 'H' in freq or 'hour' in freq else 'minute'
            if 'target_pct' not in clean:
                legacy_tp = params.get('pl_percent') or getattr(self.cfg,'pl_percent',None)
                if legacy_tp is not None:
                    clean['target_pct'] = legacy_tp
            return ORBStrategy(**clean)
        raise ValueError(f"Unknown strategy_type {stype}")

    # Reuse existing helper implementations by binding to outer functions if present
    def _get_lot_size(self):
        instrument_df = self.hdm.get_instrument_info(self.cfg.symbol)
        df_fut = instrument_df[(instrument_df['name'] == self.cfg.symbol) & (instrument_df['instrument_type'] == "FUT")]
        if not df_fut.empty:
            df_fut = df_fut.copy()
            df_fut['expiry_date'] = pd.to_datetime(df_fut['expiry'])
            df_fut = df_fut.sort_values('expiry_date')
            if len(df_fut) > self.cfg.expiry_index:
                return int(df_fut.iloc[self.cfg.expiry_index]['lot_size'])
        return 0

    def _write_tv_placeholder(self):
        if not self.tv_chart:
            return
        try:
            self.tv_chart.write_placeholder()
        except Exception:
            self.logger.exception("Failed to write TV placeholder")

    def build_candle_from_ticks(self, ticks):
        if not ticks:
            return None, None
        prices = np.array([t['price'] for t in ticks], dtype=np.float64)
        volumes = np.array([t.get('volume',1.0) for t in ticks], dtype=np.float64)
        candle_dt = pd.to_datetime(ticks[0]['datetime']).floor(self.candle_freq)
        o,h,l,c = calculate_ohlc_fast(prices)
        self.performance_stats['candles_built'] += 1
        self.performance_stats['jit_ohlc_calls'] += 1
        candle = {'open':o,'high':h,'low':l,'close':c,'volume':float(volumes.sum()),'signal':None}
        return candle_dt, candle

    def append_candle(self, candle_data):
        if candle_data[0] is None:
            return
        candle_dt, candle = candle_data
        row = pd.DataFrame([candle], index=[candle_dt])
        if candle_dt not in self.candles_df.index:
            if self.candles_df.empty:
                self.candles_df = row.copy()
            else:
                self.candles_df = pd.concat([self.candles_df, row], ignore_index=False)
            self.candles_df = self.candles_df.tail(self.max_candles)
        # No immediate plotting here; handled in run loop

    def run_backtest(self):
        self.logger.info(f"Starting backtest (close-only execution) for {self.cfg.symbol}")
        self._write_tv_placeholder()
        self.data_manager.load_data(
            start_date=self.cfg.start_date,
            end_date=self.cfg.end_date,
            use_multi_db=self.cfg.use_multi_db,
            preprocessing_days=self.cfg.preprocessing_days
        )
        current_date = None
        while True:
            price_dt = self.data_manager.get_next_data_point_with_volume()
            if isinstance(price_dt, tuple):
                price, dt, volume = price_dt
            else:
                # fallback older interface
                price, dt = price_dt
                volume = 1.0
            if price is None:
                if self.tick_buffer:
                    candle = self.build_candle_from_ticks(list(self.tick_buffer))
                    self.append_candle(candle)
                    self.tick_buffer.clear()
                break
            dt = pd.to_datetime(dt)
            if self.current_candle_start is None:
                self.current_candle_start = dt.floor(self.candle_freq)
            tick_candle_start = dt.floor(self.candle_freq)

            # Per-tick strategy update to allow ORB (minute granularity) to build internal state
            per_tick_signal = None
            try:
                per_tick = self.strategy.update(price=price, current_datetime=dt)
                if per_tick:
                    if isinstance(per_tick, dict):
                        per_tick_signal = per_tick.get('signal')
                    else:
                        per_tick_signal = per_tick
                if per_tick_signal in ('buy','sell') and self.pending_signal is None:
                    self.pending_signal = {
                        'signal': per_tick_signal,
                        'raw': per_tick,
                        'bar_start': self.current_candle_start,
                        'price': price,
                        'dt': dt
                    }
            except Exception:
                # Non-fatal; continue
                pass
            # New candle boundary -> finalize previous
            if tick_candle_start > self.current_candle_start:
                if self.tick_buffer:
                    candle = self.build_candle_from_ticks(list(self.tick_buffer))
                    self.append_candle(candle)
                    candle_dt, candle_data = candle
                    # Decide which signal to execute: pending intra-bar takes precedence; otherwise candle-close recompute
                    exec_sig_val = None
                    exec_payload = None
                    # Inject indicators (pivot / range) for this just-closed candle
                    try:
                        inds = getattr(self.strategy,'get_indicators',lambda:{})() or {}
                        if candle_dt in self.candles_df.index:
                            # Map selected fields
                            for k in ['pivot_time','pivot_high','pivot_low','pivot_direction','range_high','range_low']:
                                if k in inds:
                                    self.candles_df.at[candle_dt,k] = inds[k]
                            # Forward fill pivot high/low lines so they persist until change
                            for k in ['pivot_high','pivot_low','range_high','range_low']:
                                try:
                                    self.candles_df[k] = self.candles_df[k].ffill()
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    if self.pending_signal and self.pending_signal.get('bar_start') == self.current_candle_start:
                        exec_sig_val = self.pending_signal['signal']
                        exec_payload = self.pending_signal['raw']
                        #candle_dt  = self.pending_signal.get('dt')
                    else:
                        try:
                            close_out = self.strategy.update(price=candle_data['close'], current_datetime=candle_dt)
                        except TypeError:
                            close_out = self.strategy.update(candle_data['close'], candle_dt)
                        except Exception:
                            close_out = None
                        if close_out:
                            if isinstance(close_out, dict):
                                exec_sig_val = close_out.get('signal')
                                exec_payload = close_out
                            else:
                                exec_sig_val = close_out
                                exec_payload = close_out
                    if exec_sig_val in ('buy','sell'):
                        # allow multiple different signals in the same candle but avoid exact duplicates
                        if not (self.last_signal_candle == candle_dt and self.last_signal_val == exec_sig_val):
                            self.signal_count += 1
                            self.last_signal_candle = candle_dt
                            self.last_signal_val = exec_sig_val
                            self.logger.info(f"Signal #{self.signal_count}: {exec_sig_val} at {candle_dt} close={candle_data['close']} (pending={'yes' if self.pending_signal else 'no'})")
                            # process the signal; it may open and/or close a trade immediately
                            trade_data = self._process_trade_for_signal(candle_dt, candle_data['close'], exec_sig_val)
                            # update candle's signal column to include both entry and any immediate exit
                            try:
                                if candle_dt in self.candles_df.index:
                                    existing = self.candles_df.at[candle_dt, 'signal']
                                    sigs = []
                                    if existing is not None and existing != '':
                                        if isinstance(existing, str):
                                            sigs = [s.strip() for s in existing.split(',') if s.strip()]
                                        elif isinstance(existing, list):
                                            sigs = existing
                                    if exec_sig_val not in sigs:
                                        sigs.append(exec_sig_val)
                                    # If process returned a closed trade, append the exit signal (opposite of position)
                                    if trade_data and isinstance(trade_data, dict) and trade_data.get('position_state') in ['closed','exit']:
                                        pos_type = trade_data.get('position_type')
                                        close_sig = 'sell' if pos_type == 'long' else 'buy'
                                        if close_sig not in sigs:
                                            sigs.append(close_sig)
                                    self.candles_df.at[candle_dt, 'signal'] = ','.join(sigs)
                            except Exception:
                                pass
                    # Clear pending signal used for this bar
                    if self.pending_signal and self.pending_signal.get('bar_start') == self.current_candle_start:
                        self.pending_signal = None
                    # End-of-day close enforcement
                    ses_close = self.close_trade_on_endtime(candle_dt, candle_data['close'])
                    if ses_close in ('buy','sell') and candle_dt in self.candles_df.index:
                        self.candles_df.at[candle_dt,'signal'] = ses_close
                    # Plot/export
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
                    # Trailing event log
                    try:
                        self._maybe_log_first_trail(candle_dt)
                    except Exception:
                        pass
                    self.tick_buffer.clear()
                self.current_candle_start = tick_candle_start
            # Accumulate tick
            self.tick_buffer.append({'price':price,'datetime':dt,'volume':volume})
            # Option chain refresh once per second (simplified)
            date_dt = dt.replace(microsecond=0)
            if current_date is None or date_dt != current_date:
                current_date = date_dt
                try:
                    self.data_manager.load_option_chain(date_dt.strftime('%Y-%m-%d %H:%M:%S'), price)
                except Exception:
                    pass
        self.logger.info(f"Backtest finished: signals={self.signal_count} trades={self.trade_count}")
        try:
            if self.cfg.export_csv and hasattr(self.strategy,'save_plot'):
                base = os.path.splitext(self.cfg.export_csv)[0]
                self.strategy.save_plot(csv_path=self.cfg.export_csv, png_path=base+'.png', html_path=base+'.html')
        except Exception:
            self.logger.exception("Plot export failed")
        self.journal.summarize()
        # Ensure TV chart disables auto-refresh after final export
        if self.tv_chart:
            try:
                self.tv_chart.export_final(self.candles_df, self.completed_trades)
            except Exception:
                self.logger.exception("Failed to export final TV chart without auto-refresh")

    # Placeholder methods using previous helpers (kept minimal for revert)
    def _process_trade_for_signal(self, candle_dt, price, signal_val):
        try:
            option_data = self.get_option_data(candle_dt, price, signal_val) or {}
            if option_data is None or len(option_data) == 0:
                    self.data_manager.clear_all_caches()
                    option_data = self.get_option_data(candle_dt, price, signal_val)
                    if option_data is None:
                        return None
            indicators = getattr(self.strategy,'get_indicators',lambda:{})() or {}
            self.logger.info(f"Processing signal '{signal_val}' at {candle_dt} price={price} option_data_present={bool(option_data)}")
            trade_data = self.trade_manager.process_signal(signal_val, price, candle_dt, indicators, option_data, pl_percent=self.cfg.pl_percent)
            self.logger.info(f"process_signal returned: {trade_data}")
            self.update_trade_data(candle_dt, price, trade_data)
            return trade_data
        except Exception:
            self.logger.exception("Trade processing failed")
        return None

    # Reuse existing methods already defined later in file (get_option_data, update_trade_data, etc.)

    def run(self):
        self.run_backtest()


    def _maybe_log_first_trail(self, candle_dt):
        """Log a journal row the first time a trailing stop moves favorably beyond the entry stop, capturing locked P&L."""
        tm = self.trade_manager
        if tm.position is None:
            return
        trade_id = tm.trade_id
        if trade_id in self._first_trail_logged:
            return
        entry_sl = self._entry_stop_map.get(trade_id)
        if entry_sl is None:
            return
        # Current stop from indicators
        try:
            inds = getattr(self.strategy, 'get_indicators', lambda: {})() or {}
        except Exception:
            inds = {}
        cur_sl = inds.get('stop_loss') or inds.get('stop_loss_price')
        if cur_sl is None:
            return
        try:
            cur_sl = float(cur_sl); entry_sl = float(entry_sl)
        except Exception:
            return
        moved = False
        if tm.position == 'long' and cur_sl > entry_sl:
            moved = True
        elif tm.position == 'short' and cur_sl < entry_sl:
            moved = True
        if not moved:
            return
        # Compute first PL: prefer option P&L if current option price found; fallback to underlying locked points
        first_pl_val = ''
        # Attempt option-based unrealized P&L
        try:
            if self.option_chain_cache is not None and tm.entry_instrument_token is not None:
                oc_row = self.option_chain_cache[self.option_chain_cache['instrument_token'] == tm.entry_instrument_token]
                if not oc_row.empty:
                    cur_opt_price = oc_row.iloc[0].get('option_price', oc_row.iloc[0].get('last_price', None))
                    if cur_opt_price is not None and tm.entry_option_price not in (None, 0):
                        if tm.position == 'long':
                            first_pl_val = (cur_opt_price - tm.entry_option_price) * tm.lot_size
                        else:
                            first_pl_val = (tm.entry_option_price - cur_opt_price) * tm.lot_size
        except Exception:
            pass
        if first_pl_val == '':
            try:
                if tm.position == 'long':
                    locked_points = max(0.0, cur_sl - tm.entry_price)
                else:
                    locked_points = max(0.0, tm.entry_price - cur_sl)
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
            'profit_loss': 0.0,  # unrealized; don't add to cumulative_pnl
            'lot_size': tm.lot_size,
            'first_pl': first_pl_val,
            'stop_loss': cur_sl
        }
        try:
            trail_record.update(inds)
        except Exception:
            pass
        self.journal.save_trade(trail_record, {'symbol': self.cfg.symbol, 'instrument_type': self.cfg.instrument_type})
        self._first_trail_logged.add(trade_id)

    def update_trade_data(self, candle_dt, price, trade_data):
        if trade_data:
            self.trade_count += 1
            self.journal.save_trade(trade_data, {'symbol': self.cfg.symbol, 'instrument_type': self.cfg.instrument_type})
                
                # Track completed trades for P&L display on chart
            if trade_data.get('position_state') in ['closed', 'exit'] and 'profit_loss' in trade_data:
                    # Capture entry and exit datetimes for positioning
                entry_dt = trade_data.get('entry_datetime') or candle_dt
                exit_dt = trade_data.get('exit_datetime') or candle_dt
                position_type = trade_data.get('position_type')  # long or short
                self.completed_trades.append({
                        'entry_datetime': pd.to_datetime(entry_dt),
                        'exit_datetime': pd.to_datetime(exit_dt),
                        'stop_loss' : trade_data.get('stop_loss', None),
                        'position_type': position_type,
                        'entry_price': trade_data.get('entry_price', price),
                        'exit_price': price,
                        'option_symbol': trade_data.get('option_symbol', ''),
                        'entry_option_price': trade_data.get('entry_option_price', 0),
                        'exit_option_price': trade_data.get('exit_option_price', 0),
                        'pl': trade_data['profit_loss'],
                        'trade_id': trade_data.get('trade_id', f'T{self.trade_count}')                       
                    })
                
                # reset position helper if trade closed inside process_signal
            if isinstance(trade_data, dict) and trade_data.get('position_state') in ['closed', 'exit']:
                self.trade_manager.position = None
    
    def get_option_data(self, candle_dt, price, signal):
        option_data = self.get_option_data_with_cache(candle_dt, price, signal)
        if option_data is None or len(option_data) == 0:
            option_data = self.get_option_data_with_cache(candle_dt, price, signal, clear_cache=True)
            counter = 0
            while counter < 20 and (option_data is None or len(option_data) == 0):
                price, dt, volume = self.data_manager.get_next_data_point_with_volume()
                option_data = self.get_option_data_with_cache(dt, price, signal, clear_cache=True)
                counter += 1  
        
        if option_data is None or len(option_data) == 0:
            print("No option data available even after retries")
        return option_data

    def get_option_data_with_cache(self, candle_dt, price, signal, clear_cache=False):
        if clear_cache:
            self.data_manager.clear_all_caches()
        ts_str = candle_dt.strftime('%Y-%m-%d %H:%M:%S')
        self.option_chain_cache = self.data_manager.load_option_chain(ts_str, price)
        option_chain = self.option_chain_cache
        option_data = None
        if self.trade_manager.position is not None:
            entry_option_info = self.option_chain_cache[self.option_chain_cache['instrument_token'] == self.trade_manager.entry_instrument_token]
            if not entry_option_info.empty:
                option_data = {
                        'option_symbol': entry_option_info.iloc[0].get('tradingsymbol', entry_option_info.iloc[0].get('symbol', '')),
                        'option_type': entry_option_info.iloc[0].get('option_type', ''),
                        'strike_price': entry_option_info.iloc[0].get('strike', 0),
                        'option_price': entry_option_info.iloc[0].get('option_price', entry_option_info.iloc[0].get('last_price', 0)),
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
        if t is None:
            return None
        # Already a datetime.time object
        if isinstance(t, dtime):
            return t
        # Integer hour
        if isinstance(t, int):
            if 0 <= t <= 23:
                return dtime(t, 0)
            self.logger.warning(f"_parse_time: invalid hour int {t}")
            return None
        # String input
        if isinstance(t, str):
            s = t.strip()
            if not s:
                return None
            try:
                parts = s.split(':')
                if len(parts) == 2:
                    h = int(parts[0]); m = int(parts[1])
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        return dtime(h, m)
                self.logger.warning(f"_parse_time: invalid time string '{t}'")
            except Exception:
                self.logger.exception(f"_parse_time: failed parsing string '{t}'")
            return None
        self.logger.warning(f"_parse_time: unsupported type {type(t)} value={t}")
        return None
    
    def close_trade_on_endtime(self, candle_dt, price):
        try:
            # Compute the effective time to compare against session end.
            # candle_dt is the candle start; use candle end = start + candle_interval when available
            candle_start = pd.to_datetime(candle_dt)
            try:
                candle_end_dt = candle_start + (getattr(self, 'candle_interval', pd.Timedelta('0s')))
            except Exception:
                candle_end_dt = candle_start
            ct = candle_end_dt.time()
        except Exception:
            return None
        # Prefer runner-parsed end_time, otherwise fall back to trade_manager's configured end_time
        configured_end = getattr(self, 'end_time', None) or getattr(self.trade_manager, '_end_time', None)
        if self.trade_manager.position is not None and configured_end and ct >= configured_end:
            try:
                indicators = getattr(self.strategy, 'get_indicators', lambda: {})()
                option_data = self.get_option_data(candle_dt, price, signal=None)
                if option_data is None:
                    option_data = self.get_option_data(candle_dt, price, signal=None)
                    if option_data is None:
                        return None
                trade_data = self.trade_manager.enforce_session_constraints(price, candle_dt, option_data=option_data, indicators=indicators)
                self.update_trade_data(candle_dt, price, trade_data)  
                if trade_data is not None:    
                    return "sell" if trade_data['position_type'] == 'long' else "buy"
            except Exception:
                self.logger.exception("Failed to enforce session constraints")

    def _get_strategy(self):
        params = self.cfg.strategy_params or {}
        stype = self.cfg.strategy_type
        # Default params if none provided
        if not params:
            if stype == 'ema':
                params = {'short_period': 5, 'long_period': 20}
            elif stype == 'rsi':
                params = {'period': 14, 'oversold': 30, 'overbought': 70}
            elif stype == 'scalper':
                params = {'run_candle': 1, 'ema_min': 5, 'ema_period': 21}
        # Whitelist keys per strategy to avoid unexpected kwargs
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
            # ORB strategy supports range_minutes and max_trades_per_day (default 3)
            allowed = {'range_minutes', 'max_trades_per_day', 'candle_granularity', 'opening_range_bars', 'stop_loss_pct', 'trailing_stop_pct', 'target_pct', 'require_boundary_touch'}
            clean = {k: v for k, v in params.items() if k in allowed}
            # Auto-map legacy pl_percent / pl_percent config key to target_pct if user omitted target_pct
            # This helps when switching from scalper where pl_percent was used for exits.
            if 'target_pct' not in clean:
                legacy_tp = params.get('pl_percent') or getattr(self.cfg, 'pl_percent', None)
                if legacy_tp is not None:
                    try:
                        clean['target_pct'] = legacy_tp
                        self.logger.info(f"ORB: mapped legacy pl_percent={legacy_tp} to target_pct (explicit target_pct not provided)")
                    except Exception:
                        pass
            # Always use external_candles path because we aggregate candles here already
            clean['external_candles'] = True
            if 'candle_granularity' not in clean:
                # Infer from candle_freq if possible (only minute/hour supported)
                freq = getattr(self.cfg, 'candle_freq', '1min')
                if 'hour' in freq or 'H' in freq:
                    clean['candle_granularity'] = 'hour'
                else:
                    clean['candle_granularity'] = 'minute'
            return ORBStrategy(**clean)
        else:
            raise ValueError(f'Unknown strategy_type {stype}')

    def _get_lot_size(self):
        instrument_df = self.hdm.get_instrument_info(self.cfg.symbol)
        df_fut = instrument_df[(instrument_df['name'] == self.cfg.symbol) & (instrument_df['instrument_type'] == "FUT")]
        if not df_fut.empty:
            df_fut = df_fut.copy()
            df_fut['expiry_date'] = pd.to_datetime(df_fut['expiry'])
            df_fut = df_fut.sort_values('expiry_date')
            if len(df_fut) > self.cfg.expiry_index:
                return int(df_fut.iloc[self.cfg.expiry_index]['lot_size'])
        return 0

    def build_candle_from_ticks(self, ticks):
        if not ticks:
            return None, None

        tick_count = len(ticks)
        candle_dt = pd.to_datetime(ticks[0]['datetime']).floor(self.candle_freq)
        
        # Extract prices as numpy array for JIT optimization
        prices = np.array([t['price'] for t in ticks], dtype=np.float64)
        volumes = np.array([t['volume'] for t in ticks], dtype=np.float64)
        
        # Use JIT-compiled OHLC calculation for better performance
        open_price, high_price, low_price, close_price = calculate_ohlc_fast(prices)
        
        # Track performance stats
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
        if candle_data[0] is None:  # Skip if no valid candle
            return

        candle_dt, candle = candle_data
        candle_df_row = pd.DataFrame([candle], index=[candle_dt])

        # Avoid duplicate timestamps
        if candle_dt not in self.candles_df.index:
            # Handle empty DataFrame case to avoid FutureWarning
            if self.candles_df.empty:
                self.candles_df = candle_df_row.copy()
                # Immediately render/export first candle so earliest (e.g., 09:10) candle shows
                if self.mpl_chart:
                    try:
                        self.mpl_chart.update(self.candles_df, self.completed_trades, self.performance_stats)
                    except Exception:
                        pass
                if self.tv_chart:
                    try:
                        # force export of first candle
                        self.tv_chart.maybe_export(self.candles_df, self.completed_trades, force=True)
                    except Exception:
                        pass
            else:
                self.candles_df = pd.concat([self.candles_df, candle_df_row], ignore_index=False)

            # Memory management: keep only recent candles
            self.candles_df = self.candles_df.tail(self.max_candles)
            
            # Invalidate EMA cache when new candle is added
            self.ema_cache['last_update'] = 0
            
            self.logger.debug(f"Added candle for {candle_dt}: O={candle['open']}, H={candle['high']}, L={candle['low']}, C={candle['close']}")

    # plot_live removed; handled by MplChart



if __name__ == "__main__":
    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', "csv"))
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    trades_csv = os.path.join(output_dir, 'nifty_orb.csv')
    export_csv = os.path.join(output_dir, 'nifty_orb_prices_5_tv.html')
    config = AppConfig(
        db_dir=parent_dir,
        symbol='NIFTY',
        underlying='NIFTY 50',
        segment='INDICES',
        instrument_type='EQ',
        strategy_type='orb',
        # EMA strategy should only provide short/long periods
        #strategy_params={'short_period': 5, 'long_period': 20},
        strategy_params={'stop_loss_pct': 0.1, 'trailing_stop_pct': 0.2, 'pl_percent': 0.5},
        trades_csv=trades_csv,
        use_multi_db=True,
        start_date='2025-09-01',
        end_date='2025-09-05',
        start_time="09:30",
        end_time="15:00",
        pl_percent=0.5,
        initialization_periods=0,
        export_csv= export_csv,
        candle_freq='5min',
        chart_library='tv',
        tv_autoupdate=True,
        tv_update_every=1,
        tv_refresh_seconds=3,
        tv_auto_open=True,
        tv_pl_multiline=True,
        tv_pl_color_scale=True,
        tv_pl_padding=1,
        show_pl_line=True,
        plt_line_hover_only=True,
        tv_pl_separate_panel=True
    )
    runner = StrategyRunner(config)
    runner.run()