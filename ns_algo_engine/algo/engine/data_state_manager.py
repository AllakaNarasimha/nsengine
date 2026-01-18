import pandas as pd


class DataStateManager:    
    def __init__(self):
        self.current_index = -1

    def get_latest_record(self, df):
        if df is None or df.empty:
            return None
        
        if self.current_index < 0:
            self.current_index = 0
        
        if self.current_index >= len(df):
            return None

        record = df.iloc[self.current_index]
        self.current_index += 1
        
        # Include the index (timestamp) in the returned dict
        record_dict = record.to_dict()
        record_dict['timestamp'] = pd.to_datetime(record.name, unit='s', utc=True).tz_convert('Asia/Kolkata')
        return record_dict
            

