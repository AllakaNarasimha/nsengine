import logging
import os
import pandas as pd
from .app_config import AppConfig
from .ns_tvchart import TvChart


class TradeJournal:
    def __init__(self, app_config: AppConfig):
        self.cfg = app_config
        self.trades_csv = app_config.trades_csv
        self.trades = []
        self.trade_count = 0
        self.logger = logging.getLogger(__name__)        

    def update_trade_data(self, candle_dt, price, trade_data):
        if trade_data:
            self.trade_count += 1
            self.save_trade(trade_data, {'symbol': self.cfg.symbol, 'instrument_type': self.cfg.instrument_type})
                
            # Track completed trades for P&L display on chart
            if trade_data.get('position_state') in ['closed', 'exit'] and 'profit_loss' in trade_data:
                    # Capture entry and exit datetimes for positioning
                entry_dt = trade_data.get('entry_datetime') or candle_dt
                exit_dt = trade_data.get('exit_datetime') or candle_dt
                position_type = trade_data.get('position_type')  # long or short
                self.trades.append({
                        'entry_datetime': pd.to_datetime(entry_dt),
                        'exit_datetime': pd.to_datetime(exit_dt),
                        'stop_loss' : trade_data.get('stop_loss', None),
                        'position_type': position_type,
                        'entry_price': trade_data.get('entry_price', price),
                        'exit_price': price,
                        'pl': trade_data['profit_loss'],
                        'trade_id': trade_data.get('trade_id', f'T{self.trade_count}')                       
                    })
                
                # reset position helper if trade closed inside process_signal
            if isinstance(trade_data, dict) and trade_data.get('position_state') in ['closed', 'exit']:
                self.position = None            

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
            'lot_size': trade_data.get('lot_size', 0),
            'profit_loss': round(trade_data.get('profit_loss', 0) or 0, 2),
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
        df.to_csv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), self.cfg.trades_csv), index=False)
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

