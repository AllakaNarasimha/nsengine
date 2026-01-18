import xml.etree.ElementTree as ET

class AppConfig:
    def __init__(self, **kwargs):
        default_cfg = dict(
            db_dir=None, db_file=None, symbol=None, underlying=None, segment=None,
            instrument_type=None, exchange=None, strategy_type='ema', strategy_params=None,
            data_mode='historical', initialization_periods=50, live=False,
            trades_csv='trading_journal.csv', expiry_index=0, start_date=None,
            end_date=None, start_time="09:15", end_time="15:00", use_multi_db=False, preprocessing_days=3,
            export_csv=None, pl_percent=0.5, candle_freq='1min',
            tv_autoupdate=False,   # if True, regenerate TV HTML every tv_update_every candles
            tv_update_every=5,     # frequency (in completed candles) for auto export
            tv_refresh_seconds=0,  # if >0, inject meta refresh tag into HTML for auto reload
            tv_auto_open=False,    # if True, open HTML in browser on first export
            tv_pl_padding=2,       # number of "\n" lines to pad P&L marker text to shift vertically
            tv_pl_multiline=False, # if True show each P&L on its own line when multiple trades exit same candle
            tv_pl_color_scale=True, # scale marker color intensity by absolute P&L
            show_pl_line=True,      # plot cumulative P&L line in TV (and MPL) charts
            pl_line_hover_only=False, # if True show PL line only on hover
            tv_volume_ratio=0.25,     # fraction (0.10-0.50) of vertical space for volume pane
            tv_pl_separate_panel=False, # if True render cumulative P&L in its own chart below
            volume_mode='tick_count' # how to derive volume: tick_count | price_range | abs_return | real
            # session_close_time removed: strategy now responsible for EOD logic
        )
        for k, v in default_cfg.items():
            setattr(self, k, kwargs.get(k, v))
    
    @classmethod
    def from_xml(cls, xml_path):
        """Load configuration from XML file"""
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        config_dict = {}
        
        # Helper function to convert string values to appropriate types
        def convert_value(value_str):
            if value_str is None:
                return None
            value_str = value_str.strip()
            if not value_str:
                return None
            # Boolean conversion
            if value_str.lower() in ('true', 'false'):
                return value_str.lower() == 'true'
            # Try integer conversion
            try:
                if '.' not in value_str:
                    return int(value_str)
            except ValueError:
                pass
            # Try float conversion
            try:
                return float(value_str)
            except ValueError:
                pass
            # Return as string
            return value_str
        
        # Parse all elements
        for elem in root:
            if elem.tag == 'strategy':
                for subelem in elem:
                    if subelem.tag == 'strategy_name':
                        config_dict['strategy_type'] = convert_value(subelem.text)
                    elif subelem.tag == 'strategy_params':
                        # Parse nested strategy parameters
                        strategy_params = {}
                        for param in subelem:
                            strategy_params[param.tag] = convert_value(param.text)
                        config_dict['strategy_params'] = strategy_params
            else:
                config_dict[elem.tag] = convert_value(elem.text)
        
        return cls(**config_dict)
