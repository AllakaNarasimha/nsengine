from abc import ABC, abstractmethod

class SignalGeneratorInterface(ABC):
    """Abstract base class for signal generators."""
    
    @abstractmethod
    def update(self, price, current_datetime):
        """Generate trading signal based on price and datetime."""
        pass
    
    @abstractmethod
    def reset(self):
        """Reset signal generator state."""
        pass
    
    @abstractmethod
    def get_indicators(self):
        """Return current indicator values."""
        pass