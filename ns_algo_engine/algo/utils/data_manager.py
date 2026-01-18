from nslogger.option_chain_manager import OptionChainManager
from nslogger.history_data_manager import HistoryDataManager
import os

class DataManager:
    def __init__(self, db_file, db_dir):
        db_path = os.path.join(db_dir, db_file)
        self.option_chain_manager = OptionChainManager(db_file, db_path)
        self.history_data_manager = HistoryDataManager(db_file, db_path)
    
    # returns a dataframe with live stock data
    def get_live_stock_data(self, symbol):
        return self.history_data_manager.sql.get_live_data(symbol)
    
    def get_live_option_chain(self, symbol, expiry_index):
        expiry = self.option_chain_manager.get_expiry_by_index(symbol, expiry_index)
        return self.option_chain_manager.get_live_option_chain_by_expiry(expiry[1] if expiry else None)
    
    # returns a dataframe with historical data
    def get_historical_data(self, symbol, start_date, end_date):
        return self.history_data_manager.get_historical_data(symbol, start_date, end_date)
    
    