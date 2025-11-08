try:
    import talib  # type: ignore
    _HAS_TALIB = True
except Exception:
    talib = None
    _HAS_TALIB = False
import mplfinance as mpf
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

class MplChart:
    """Encapsulates MPL live plotting logic (candles, EMA, signals, P&L)."""
    def __init__(self):
        self.fig, self.axs = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]}, sharex=True)
        plt.ion()
        self.fig.show()
        self.fig.canvas.draw()
        # Simple EMA cache
        self._ema_cache_len = 0
        self._ema_cached = False
        self._pl_line = None
        self._hover_only = False  # set externally

        def _on_move(event):
            if not self._hover_only or self._pl_line is None:
                return
            if event.inaxes == self.axs[1]:
                self._pl_line.set_visible(True)
            else:
                self._pl_line.set_visible(False)
            self.fig.canvas.draw_idle()

        self.fig.canvas.mpl_connect('motion_notify_event', _on_move)

    def update(self, df: pd.DataFrame, completed_trades, performance_stats: dict | None = None):
        # Render from the very first candle (avoid skipping the initial 5-min candle)
        if df is None or df.empty:
            return
        # Ensure datetime index
        df.index = pd.to_datetime(df.index)

        # Normalize signals
        if 'signal' in df.columns:
            df['signal'] = df['signal'].apply(lambda x: x.get('signal') if isinstance(x, dict) else x)

        # EMA caching
        if self._ema_cache_len != len(df) or 'ema5' not in df.columns or 'ema20' not in df.columns:
            if _HAS_TALIB:
                df['ema5'] = talib.EMA(df['close'].astype(np.float64), timeperiod=5)
                df['ema20'] = talib.EMA(df['close'].astype(np.float64), timeperiod=20)
            else:
                df['ema5'] = df['close'].rolling(5, min_periods=1).mean()
                df['ema20'] = df['close'].rolling(20, min_periods=1).mean()
            self._ema_cache_len = len(df)
            self._ema_cached = True
        else:
            if performance_stats is not None:
                performance_stats['ema_cache_hits'] = performance_stats.get('ema_cache_hits', 0) + 1

        apds = [
            mpf.make_addplot(df['ema5'], color='yellow', width=1, ax=self.axs[0]),
            mpf.make_addplot(df['ema20'], color='cyan', width=1, ax=self.axs[0])
        ]

        signal_buys = pd.Series(index=df.index, dtype='float64')
        signal_sells = pd.Series(index=df.index, dtype='float64')

        if 'signal' in df.columns:
            buys_mask = df['signal'] == 'buy'
            sells_mask = df['signal'] == 'sell'
        else:
            buys_mask = sells_mask = pd.Series(False, index=df.index)

        num_candles = len(df)
        if num_candles <= 50:
            marker_size = 100
        elif num_candles <= 100:
            marker_size = 75
        elif num_candles <= 200:
            marker_size = 25
        else:
            marker_size = 15

        if buys_mask.any():
            signal_buys[buys_mask] = df.loc[buys_mask, 'low'] * 0.9999
            apds.append(mpf.make_addplot(signal_buys, type='scatter', markersize=marker_size, marker='^', color='g', ax=self.axs[0]))
        if sells_mask.any():
            signal_sells[sells_mask] = df.loc[sells_mask, 'high'] * 1.0001
            apds.append(mpf.make_addplot(signal_sells, type='scatter', markersize=marker_size, marker='v', color='r', ax=self.axs[0]))

        for ax in self.axs:
            ax.clear()

        mpf.plot(
            df,
            type='candle',
            style='yahoo',
            addplot=apds,
            ax=self.axs[0],
            volume=self.axs[1],
            volume_panel=1,
            show_nontrading=False,
            axtitle='Live Candlestick Chart with EMA and Signals',
            block=False
        )

        # Draw pivot vertical line if pivot_time column supplied (strategy indicators could merge it)
        # Simpler: if dataframe has 'pivot_time' single value accessible via last row, or we can store externally.
        try:
            pivot_time = None
            pivot_high = None
            pivot_low = None
            pivot_dir = None
            if 'pivot_time' in df.columns and df['pivot_time'].dropna().size:
                pivot_time = pd.to_datetime(df['pivot_time'].dropna().iloc[-1])
            if 'pivot_high' in df.columns and df['pivot_high'].dropna().size:
                pivot_high = float(df['pivot_high'].dropna().iloc[-1])
            if 'pivot_low' in df.columns and df['pivot_low'].dropna().size:
                pivot_low = float(df['pivot_low'].dropna().iloc[-1])
            if 'pivot_direction' in df.columns and df['pivot_direction'].dropna().size:
                pivot_dir = str(df['pivot_direction'].dropna().iloc[-1])
            # Fallback: if no pivot_direction but we have high/low, treat as neutral provisional opening range
            color = '#26a69a' if pivot_dir == 'bull' else ('#ef5350' if pivot_dir == 'bear' else '#ff9800')
            if pivot_time is not None:
                # If pivot candle scrolled out (history trimmed), start from first visible candle
                if pivot_time in df.index:
                    start_ts = pivot_time
                else:
                    # Clamp to first index (so lines still show)
                    start_ts = df.index[0]
                end_ts = df.index[-1]
                if pivot_high is not None:
                    self.axs[0].hlines(pivot_high, xmin=start_ts, xmax=end_ts, colors=color, linestyles='dotted', linewidth=1)
                if pivot_low is not None:
                    self.axs[0].hlines(pivot_low, xmin=start_ts, xmax=end_ts, colors=color, linestyles='dotted', linewidth=1)
                if pivot_time not in df.index:
                    print(f"[Pivot] Original pivot candle {pivot_time} not in window; drawing from {start_ts}")
        except Exception:
            pass

        # Cumulative P&L line (overlay on volume axis) if data available
        if completed_trades:
            closed = [t for t in completed_trades if t.get('exit_datetime') is not None]
            if closed:
                closed_sorted = sorted(closed, key=lambda x: pd.to_datetime(x.get('exit_datetime')))
                running = 0.0
                pl_points = {}
                for t in closed_sorted:
                    exit_dt = pd.to_datetime(t.get('exit_datetime'))
                    running += float(t.get('pl', 0))
                    pl_points[exit_dt] = running
                # Build aligned series with same x positioning (index location)
                x_vals = []
                y_vals = []
                for ts in df.index:
                    if ts in pl_points:
                        x_vals.append(df.index.get_loc(ts))
                        y_vals.append(pl_points[ts])
                if len(x_vals) > 1:
                    if self._pl_line is not None:
                        self._pl_line.remove()
                    (self._pl_line,) = self.axs[1].plot(x_vals, y_vals, color='#ffa600', linewidth=1.4, label='Cum P&L', visible=not self._hover_only)
                    # Legend
                    if not self.axs[1].get_legend():
                        self.axs[1].legend(loc='upper left', fontsize=8, framealpha=0.3)

        # P&L annotations
        price_range = df['high'].max() - df['low'].min()
        for trade in completed_trades:
            entry_dt = trade.get('entry_datetime')
            if entry_dt in df.index:
                try:
                    idx_pos = df.index.get_loc(entry_dt)
                    pl = trade.get('pl', 0)
                    pl_color = 'darkgreen' if pl > 0 else 'darkred'
                    pl_text = f"+{pl:.1f}" if pl > 0 else f"{pl:.1f}"
                    candle_high = df.loc[entry_dt, 'high']
                    candle_low = df.loc[entry_dt, 'low']
                    if trade.get('position_type') == 'short':
                        text_y = candle_low - (price_range * 0.025)
                        valign = 'top'
                    else:
                        text_y = candle_high + (price_range * 0.025)
                        valign = 'bottom'
                    self.axs[0].text(
                        idx_pos, text_y, pl_text,
                        color='white', fontsize=9, fontweight='bold', ha='center', va=valign,
                        bbox=dict(boxstyle='round,pad=0.25', facecolor=pl_color, alpha=0.4, edgecolor='black', linewidth=1),
                        zorder=10
                    )
                except Exception:
                    continue

        self.fig.canvas.draw()
        plt.pause(0.05)

    def finalize(self, df, completed_trades):
        # Optionally could save a static image; currently no-op
        pass
