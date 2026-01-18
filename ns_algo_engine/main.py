import os
from algo.engine.controller import Controller
from algo.utils.app_config import AppConfig


class BackTestController:
    def run(self):
        config = AppConfig.from_xml("config.xml")
        config.db_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), config.db_dir))
       
        controller = Controller(config)       
        controller.run()

if __name__ == "__main__":
    backtest_controller = BackTestController()
    backtest_controller.run()
    