import time
from collections import deque
from typing import Dict, Optional
import json
import statistics


class ThreatEvaluation:
    # Stand alone class that takes in data that'll be passed to it, and outputs a danger evaluation score
    
    def __init__(self):
        # Population-based norms (typical resting values)
        self.baselines = {
            'hr': {'mean': 70, 'std': 12},
            'breathing': {'mean': 16, 'std': 4},
            'eda': {'mean': 0.15, 'std': 0.05},
            'chest_breathing': {'mean': 0.4, 'std': 0.1}
        }
        
        # History for rate of change (last 30 data points)
        self.metric_history = deque(maxlen=30)
        
        # Current threat info
        self.current_threat_score = 0.0
        self.individual_scores = {}
        
    def process_packet(self, packet_string: str) -> Optional[Dict]:
        """
        Process a JSON packet string from Presage
        
        Args:
            packet_string: JSON string like '{"type":"core_metrics",...}'
            
        Returns:
            Threat assessment dict or None
        """
        try:
            message = json.loads(packet_string)
            return self.process_message(message)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            return None
        
    def process_message(self, message: Dict) -> Optional[Dict]:
        """Process incoming Presage messages"""
        msg_type = message.get("type")
        timestamp_ms = message.get("timestamp_ms")
        data = message.get("data", {})
        
        if msg_type == "core_metrics":
            return self._process_core_metrics(data, timestamp_ms)
        elif msg_type == "edge_metrics":
            return self._process_edge_metrics(data, timestamp_ms)
            
        return None
    
    def _process_core_metrics(self, data: Dict, timestamp_ms: int) -> Optional[Dict]:
        """Extract heart rate and breathing from core metrics"""
        metrics = {}
        
        # Get heart rate
        pulse_data = data.get("pulse", {}).get("heart_rate", {})
        if pulse_data.get("stable") and pulse_data.get("confidence", 0) > 0.7:
            metrics['hr'] = pulse_data.get("value")
        
        # Get breathing rate
        breathing_data = data.get("breathing", {}).get("respiratory_rate", {})
        if breathing_data.get("stable"):
            metrics['breathing'] = breathing_data.get("value")
        
        return self._calculate_threat(metrics, timestamp_ms)
    
    def _process_edge_metrics(self, data: Dict, timestamp_ms: int) -> Optional[Dict]:
        """Extract EDA and chest breathing from edge metrics"""
        metrics = {}
        
        # Get chest breathing
        chest_data = data.get("chest_breathing", {})
        if chest_data.get("stable"):
            metrics['chest_breathing'] = chest_data.get("value")
        
        # Get EDA
        eda_data = data.get("eda", {})
        if eda_data.get("value") is not None:
            metrics['eda'] = eda_data.get("value")
            metrics['eda_stable'] = eda_data.get("stable")
        
        return self._calculate_threat(metrics, timestamp_ms)
    
    def _calculate_threat(self, metrics: Dict, timestamp_ms: int) -> Optional[Dict]:
        """Calculate threat score from metrics"""
        
        # Add to history
        metrics['timestamp_ms'] = timestamp_ms
        self.metric_history.append(metrics)
        
        # Normalize each metric to 0-1
        normalized = self._normalize_metrics(metrics)
        
        # Calculate rate of change
        rate_of_change = self._calculate_rate_of_change()
        
        # Combine into final threat score
        threat_score = self._combine_scores(normalized, rate_of_change)
        
        self.current_threat_score = threat_score
        self.individual_scores = normalized
        
        return {
            'timestamp_ms': timestamp_ms,
            'threat_score': threat_score,
            'threat_level': self._get_threat_level(threat_score),
            'individual_scores': normalized,
            'raw_metrics': metrics
        }
    
    def _normalize_metrics(self, metrics: Dict) -> Dict:
        """Normalize each metric to 0-1 score"""
        scores = {}
        
        # Heart rate
        if 'hr' in metrics:
            hr = metrics['hr']
            baseline = self.baselines['hr']
            z_score = (hr - baseline['mean']) / baseline['std']
            scores['hr'] = max(0, min(1, z_score / 3.0))  # Map ±3 std to 0-1
        
        # Breathing rate (deviation in either direction is concerning)
        if 'breathing' in metrics:
            breathing = metrics['breathing']
            baseline = self.baselines['breathing']
            z_score = (breathing - baseline['mean']) / baseline['std']
            scores['breathing'] = max(0, min(1, abs(z_score) / 3.0))
        
        # EDA (increases under stress)
        if 'eda' in metrics:
            eda = metrics['eda']
            baseline = self.baselines['eda']
            percent_change = (eda - baseline['mean']) / baseline['mean']
            scores['eda'] = max(0, min(1, percent_change / 2.0))  # 200% increase = 1.0
            
            # Unstable EDA = higher threat
            if not metrics.get('eda_stable', True):
                scores['eda'] = min(1.0, scores['eda'] * 1.2)
        
        # Chest breathing
        if 'chest_breathing' in metrics:
            chest = metrics['chest_breathing']
            baseline = self.baselines['chest_breathing']
            z_score = (chest - baseline['mean']) / baseline['std']
            scores['chest_breathing'] = max(0, min(1, abs(z_score) / 3.0))
        
        return scores
    
    def _calculate_rate_of_change(self) -> float:
        """How fast is heart rate changing"""
        if len(self.metric_history) < 10:
            return 0.0
        
        current = self.metric_history[-1]
        past = self.metric_history[-10]
        
        # Only calculate if we have HR in both
        if 'hr' not in current or 'hr' not in past:
            return 0.0
        
        time_diff = (current['timestamp_ms'] - past['timestamp_ms']) / 1000.0  # seconds
        if time_diff < 1:
            return 0.0
        
        # bpm per second
        hr_velocity = abs(current['hr'] - past['hr']) / time_diff
        
        # >2 bpm/sec = threat score of 1.0
        return max(0, min(1, hr_velocity / 2.0))
    
    def _combine_scores(self, normalized: Dict, rate_of_change: float) -> float:
        """Combine all scores with weights"""
        
        weights = {
            'hr': 0.30,
            'eda': 0.25,
            'breathing': 0.20,
            'chest_breathing': 0.10,
            'rate_of_change': 0.15
        }
        
        total_score = 0.0
        total_weight = 0.0
        
        # Add each available metric
        for key, weight in weights.items():
            if key == 'rate_of_change':
                total_score += weight * rate_of_change
                total_weight += weight
            elif key in normalized:
                total_score += weight * normalized[key]
                total_weight += weight
        
        # Normalize by total weight used
        if total_weight > 0:
            return total_score / total_weight
        
        return 0.0
    
    def _get_threat_level(self, score: float) -> str:
        """Convert score to threat level"""
        
        if score < 0.30:
            return "LOW"
        elif score < 0.55:
            return "MODERATE"
        elif score < 0.75:
            return "HIGH"
        else:
            return "CRITICAL"


# Usage with your packet data
if __name__ == "__main__":
    detector = ThreatEvaluation()
    
    # Your actual data packets
    packets = [
        '{"type":"edge_metrics","timestamp_ms":1769308247751,"data":{"chest_breathing":{"value":4.86284,"stable":true}}}',
        '{"type":"core_metrics","timestamp_ms":1769308247784,"data":{"frame_timestamp":1769308247673027,"pulse":{"heart_rate":{"value":102.6,"stable":true,"confidence":0},"trace_latest":{"value":0.0314,"stable":true}},"breathing":{"respiratory_rate":{"value":12.6,"stable":true,"confidence":0},"chest_trace_latest":{"value":2.3812,"stable":true}},"blood_pressure":{},"face":{"blinking":{"detected":false,"stable":true},"talking":{"detected":false,"stable":true}}}}',
        '{"type":"edge_metrics","timestamp_ms":1769308247784,"data":{"chest_breathing":{"value":4.9726,"stable":true}}}',
        '{"type":"edge_metrics","timestamp_ms":1769308247817,"data":{"chest_breathing":{"value":4.9702,"stable":true}}}'
    ]
    
    # Process each packet
    for packet in packets:
        result = detector.process_packet(packet)
        
        if result:
            print(f"\nTimestamp: {result['timestamp_ms']}")
            print(f"Threat Level: {result['threat_level']}")
            print(f"Threat Score: {result['threat_score']:.3f}")
            print(f"Individual Scores: {result['individual_scores']}")
            print(f"Raw Metrics: {result['raw_metrics']}")

    

    
    

    