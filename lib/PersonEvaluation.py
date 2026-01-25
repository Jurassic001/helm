import time
from collections import deque
from typing import Dict, Optional
import statistics


class PersonEvaluaton:
    # Stand alone class that takes in data that'll be passed to it, and outputs a danger evaluation score
    
    def __init__(self):
        
        self.baseline = {
            'hr': {'mean': 70, 'std': 12},  # Typical resting HR
            'breathing': {'mean': 16, 'std': 4},  # Typical breathing rate
            'eda': {'mean': 0.15, 'std': 0.05},  # Typical EDA (adjust based on sensor)
            'chest_breathing': {'mean': 0.4, 'std': 0.1}  # Normalized chest movement
        }
        

    
    

    