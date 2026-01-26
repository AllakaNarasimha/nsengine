"""
Trade journal management module for NS Engine backtesting framework.
Handles trade recording, updating, and persistence to CSV.
"""

import os
import logging
import pandas as pd
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging_config import setup_logging, get_output_dir


class TradeJournal:
    """Manages trade journaling with CSV persistence and cumulative P&L tracking."""
    
    def __init__(self, trades_csv):
        """
        Initialize TradeJournal.
        
        Args:
            trades_csv (str): Path to trades CSV file
        """
        # Ensure output directory exists and save in output folder
        output_dir = get_output_dir()
        self.trades_csv = os.path.join(output_dir, trades_csv)
        self.cumulative_pnl = 0
        
        # Configure logging
        setup_logging()
        self.logger = logging.getLogger(__name__)

    def save_trade(self, trade_data, meta):
        """
        Save or update a trade in the journal CSV.
        
        Args:
            trade_data (dict): Trade data including entry/exit prices, P&L, etc.
            meta (dict): Metadata including symbol and instrument_type
        """
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

        # Prepare the journal entry
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

        # Load existing CSV or create new DataFrame
        if os.path.exists(self.trades_csv):
            try:
                df = pd.read_csv(self.trades_csv)
            except Exception:
                df = pd.DataFrame()
        else:
            df = pd.DataFrame()

        # Try to update an existing row or append new
        updated = self._update_or_append_trade(df, journal_entry)

        if not updated:
            # Append new row
            df = pd.concat([df, pd.DataFrame([journal_entry])], ignore_index=True)

        # Recompute cumulative P&L
        self._update_cumulative_pnl(df)

        # Write back to CSV
        df.to_csv(self.trades_csv, index=False)
        self.cumulative_pnl = float(df['cumulative_pnl'].iloc[-1]) if not df.empty else 0.0
        self.logger.info(f"Saved trade: {journal_entry.get('trade_id')}, P&L={journal_entry.get('profit_loss')}")

    def _update_or_append_trade(self, df, journal_entry):
        """
        Attempt to update existing trade or mark for append.
        
        Args:
            df (pd.DataFrame): Current trades dataframe
            journal_entry (dict): New journal entry
            
        Returns:
            bool: True if updated, False if should append
        """
        if df.empty:
            return False

        updated = False
        tid = journal_entry.get('trade_id')
        sym = journal_entry.get('symbol')
        action = journal_entry.get('action')

        if tid is not None:
            # Try to find and update existing open row
            try:
                exit_empty = df['exit_datetime'].isna() | (df['exit_datetime'].astype(str).str.strip() == '')
            except Exception:
                exit_empty = pd.Series([False] * len(df))

            mask_open = (df.get('trade_id') == tid) & (df.get('symbol') == sym) & exit_empty
            
            if mask_open.any():
                # Update existing open row
                idx = df[mask_open].index[-1]
                if journal_entry['exit_datetime']:
                    df.at[idx, 'exit_datetime'] = journal_entry['exit_datetime']
                if journal_entry['exit_price']:
                    df.at[idx, 'exit_price'] = journal_entry['exit_price']
                if journal_entry['exit_option_price']:
                    df.at[idx, 'exit_option_price'] = journal_entry['exit_option_price']
                df.at[idx, 'profit_loss'] = journal_entry['profit_loss']
                df.at[idx, 'position_state'] = journal_entry['position_state']
                df.at[idx, 'action'] = journal_entry['action']
                updated = True
            elif action == 'entry':
                # Check for duplicate entry
                same_entry_mask = (
                    (df.get('symbol') == sym) &
                    (df.get('action') == 'entry') &
                    (df.get('position_type') == journal_entry.get('position_type')) &
                    ((df.get('entry_datetime').astype(str) == journal_entry.get('entry_datetime')))
                )
                if same_entry_mask.any():
                    updated = True  # Skip append
            else:
                # Try to update any matching row by trade_id
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

        return updated

    def _update_cumulative_pnl(self, df):
        """Update cumulative P&L column in dataframe."""
        try:
            df['profit_loss'] = pd.to_numeric(df['profit_loss'], errors='coerce').fillna(0.0)
            df['cumulative_pnl'] = df['profit_loss'].cumsum()
        except Exception:
            df['cumulative_pnl'] = 0.0

    def summarize(self):
        """Print backtest summary statistics to log."""
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
            
            total_trades = len(journal)
            if total_trades > 0:
                win_rate = len(journal[journal['profit_loss'] > 0]) / total_trades * 100
                self.logger.info(f"Win Rate: {win_rate:.2f}%")
