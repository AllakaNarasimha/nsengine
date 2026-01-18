import pandas as pd
from algo.engine.data_state_manager import DataStateManager
from algo.engine.trade_manager import TradeManager
from algo.utils.app_config import AppConfig
from algo.utils.data_manager import DataManager
from algo.utils.trade_journal import TradeJournal
from algo.utils.ns_tvchart import TvChart

class Controller:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
        self.data_manager = DataManager(app_config.db_file, app_config.db_dir)
        self.tv_chart = TvChart(app_config)

    def run(self):
        # Main control logic for the algorithmic trading engine
        symbol_ticker = f'{self.app_config.exchange}:{self.app_config.symbol}-{self.app_config.instrument_type}'
        if self.app_config.live:
            data = self.data_manager.get_live_stock_data(symbol_ticker)            
            option_chain = self.data_manager.get_live_option_chain(
                self.app_config.symbol, self.app_config.expiry_index)
        else:
            data = self.data_manager.get_historical_data(
                symbol_ticker, self.app_config.start_date, self.app_config.end_date)
        
        data.set_index('timestamp', inplace=True)
        data.index = pd.to_datetime(data.index, unit='s', utc=True).tz_convert('Asia/Kolkata')
        
        data_state_manager = DataStateManager()
        trade_manager = TradeManager(self.app_config)
        trade_journal = TradeJournal(self.app_config)
        self.tv_chart.write_placeholder()
        
        if self.app_config.strategy_type == 'ORB':
            from algo.strategy.orb.orb_strategy import ORBStrategy
            
            self.strategy = ORBStrategy(data, self.app_config, data_state_manager)            

        for col in ['orb_time', 'pivot_time','pivot_high','pivot_low','pivot_direction','range_high','range_low']:
            data[col] = pd.Series(dtype='float64' if 'high' in col or 'low' in col or 'range' in col else 'object')
            
        while True:
            record = data_state_manager.get_latest_record(data)
            if record is None:
                break
            if self.strategy:
                trade_signal = self.strategy._process_candle(record)               
                trade_data = trade_manager.process_signal(record, trade_signal)  
                if trade_data is None:
                    continue
                trade_journal.update_trade_data(record['timestamp'], record['close'], trade_data)
                try:
                    self.tv_chart.maybe_export(data.iloc[:data_state_manager.current_index], trade_journal.trades)
                except Exception:
                    pass
        
        if self.tv_chart:
            try:
                self.tv_chart.export_final(data, trade_journal.trades)
            except Exception:
                self.logger.exception("Failed to export final TV chart without auto-refresh")


 