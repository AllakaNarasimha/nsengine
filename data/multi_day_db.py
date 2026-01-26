import datetime
import os
import glob

class MultiDayDatabaseManager:
    def __init__(self, base_path, db_pattern="*-history.db"):
        self.base_path = base_path
        self.db_pattern = db_pattern
        self.available_dates = []
        self.db_files = {}
        self._scan_database_files()
    
    def _scan_database_files(self):
        date_folders = glob.glob(os.path.join(self.base_path, "????-??-??"))
        for folder in date_folders:
            date_str = os.path.basename(folder)
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                db_files = glob.glob(os.path.join(folder, self.db_pattern))
                if db_files:
                    self.available_dates.append(date_obj)
                    self.db_files[date_obj] = db_files[0]
            except ValueError:
                continue
        self.available_dates.sort()
    
    def get_available_dates(self):
        return self.available_dates.copy()
    
    def get_db_path(self, date):
        if isinstance(date, str):
            date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        return self.db_files.get(date)
    
    def get_date_range_db_files(self, start_date, end_date):
        if isinstance(start_date, str):
            start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        if isinstance(end_date, str):
            end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
        return [(date, self.db_files[date]) for date in self.available_dates if start_date <= date <= end_date]
    
    def get_latest_n_days(self, n_days):
        return [(date, self.db_files[date]) for date in self.available_dates[-n_days:]]