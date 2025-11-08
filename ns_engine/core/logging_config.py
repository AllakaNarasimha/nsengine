"""
Logging configuration module for NS Engine backtesting framework.
Centralizes logging setup with proper output directory handling.
"""

import os
import logging


def setup_logging(log_filename='trading.log'):
    """
    Set up logging with output directory.
    
    Args:
        log_filename (str): Name of the log file
        
    Returns:
        logging.Logger: Configured logger instance
    """
    # Create output directory if it doesn't exist
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    # Full path to log file
    log_path = os.path.join(output_dir, log_filename)
    
    # Configure logging
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    return logging.getLogger(__name__)


def get_output_dir():
    """
    Get the output directory path.
    
    Returns:
        str: Path to output directory
    """
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output')
    os.makedirs(output_dir, exist_ok=True)
    return output_dir
