import json
import time
from collections import deque
from typing import Dict, Optional


class ThreatDetector:
    def __init__(self, averaging_window=0.5):
        # Population-based norms (typical resting values)
        self.baselines = {
            "hr": {"mean": 70, "std": 12},
            "breathing": {"mean": 16, "std": 4},
            "eda": {"mean": 0.15, "std": 0.05},
            "chest_breathing": {"mean": 0.4, "std": 0.1},
        }

        # Averaging window in seconds
        self.averaging_window = averaging_window

        # Buffers to collect data for averaging (store with timestamps)
        self.hr_buffer = deque()
        self.breathing_buffer = deque()
        self.eda_buffer = deque()
        self.chest_breathing_buffer = deque()

        # History for rate of change (averaged values)
        self.metric_history = deque(maxlen=30)

        # Current values (latest averages)
        self.current_hr = None
        self.current_breathing = None
        self.current_eda = None
        self.current_chest_breathing = None
        self.current_threat_score = 0.0

        # Last calculation time
        self.last_calculation_time = time.time()

    def process_packet(self, packet_string: str) -> Optional[float]:
        """
        Process a JSON packet string from Presage
        Collects data and calculates threat score every 0.5 seconds

        Returns:
            Threat score (0-1) or None if not ready yet
        """
        try:
            message = json.loads(packet_string)
            return self.process_message(message)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            return None

    def process_message(self, message: Dict) -> Optional[float]:
        """Process incoming Presage messages and add to buffers"""
        msg_type = message.get("type")
        timestamp_ms = message.get("timestamp_ms")
        data = message.get("data", {})

        current_time = time.time()

        # Extract and buffer data
        if msg_type == "core_metrics":
            self._buffer_core_metrics(data, timestamp_ms)
        elif msg_type == "edge_metrics":
            self._buffer_edge_metrics(data, timestamp_ms)

        # Check if it's time to calculate (every 0.5 seconds)
        if current_time - self.last_calculation_time >= self.averaging_window:
            self.last_calculation_time = current_time
            return self._calculate_threat_from_averages()

        return None

    def _buffer_core_metrics(self, data: Dict, timestamp_ms: int):
        """Add core metrics to buffers"""
        current_time = time.time()

        # Buffer heart rate
        pulse_data = data.get("pulse", {}).get("heart_rate", {})
        if pulse_data.get("stable"):
            hr = pulse_data.get("value")
            if hr is not None:
                self.hr_buffer.append((current_time, hr))

        # Buffer breathing rate
        breathing_data = data.get("breathing", {}).get("respiratory_rate", {})
        if breathing_data.get("stable"):
            breathing = breathing_data.get("value")
            if breathing is not None:
                self.breathing_buffer.append((current_time, breathing))

    def _buffer_edge_metrics(self, data: Dict, timestamp_ms: int):
        """Add edge metrics to buffers"""
        current_time = time.time()

        # Buffer chest breathing
        chest_data = data.get("chest_breathing", {})
        if chest_data.get("stable"):
            chest = chest_data.get("value")
            if chest is not None:
                self.chest_breathing_buffer.append((current_time, chest))

        # Buffer EDA
        eda_data = data.get("eda", {})
        if eda_data.get("value") is not None:
            eda = eda_data.get("value")
            self.eda_buffer.append((current_time, eda))

    def _clean_old_buffer_data(self, buffer: deque):
        """Remove data older than averaging window"""
        current_time = time.time()
        cutoff_time = current_time - self.averaging_window

        while buffer and buffer[0][0] < cutoff_time:
            buffer.popleft()

    def _calculate_average(self, buffer: deque) -> Optional[float]:
        """Calculate average from buffer, excluding old data"""
        self._clean_old_buffer_data(buffer)

        if not buffer:
            return None

        values = [value for _, value in buffer]
        return sum(values) / len(values)

    def _calculate_threat_from_averages(self) -> float:
        """Calculate threat score from averaged data"""

        # Calculate averages from buffers
        avg_hr = self._calculate_average(self.hr_buffer)
        avg_breathing = self._calculate_average(self.breathing_buffer)
        avg_eda = self._calculate_average(self.eda_buffer)
        avg_chest_breathing = self._calculate_average(self.chest_breathing_buffer)

        # Update current values
        if avg_hr is not None:
            self.current_hr = avg_hr
        if avg_breathing is not None:
            self.current_breathing = avg_breathing
        if avg_eda is not None:
            self.current_eda = avg_eda
        if avg_chest_breathing is not None:
            self.current_chest_breathing = avg_chest_breathing

        # Store in history for rate of change
        metrics = {
            "hr": avg_hr,
            "breathing": avg_breathing,
            "eda": avg_eda,
            "chest_breathing": avg_chest_breathing,
            "timestamp_ms": int(time.time() * 1000),
        }
        self.metric_history.append(metrics)

        # Normalize metrics
        normalized = self._normalize_metrics(metrics)

        # Calculate rate of change
        rate_of_change = self._calculate_rate_of_change()

        # Combine into final threat score
        threat_score = self._combine_scores(normalized, rate_of_change)
        self.current_threat_score = threat_score

        return threat_score

    def _normalize_metrics(self, metrics: Dict) -> Dict:
        """Normalize each metric to 0-1 score"""
        scores = {}

        # Heart rate
        if metrics.get("hr") is not None:
            hr = metrics["hr"]
            baseline = self.baselines["hr"]
            z_score = (hr - baseline["mean"]) / baseline["std"]
            scores["hr"] = max(0, min(1, z_score / 3.0))

        # Breathing rate
        if metrics.get("breathing") is not None:
            breathing = metrics["breathing"]
            baseline = self.baselines["breathing"]
            z_score = (breathing - baseline["mean"]) / baseline["std"]
            scores["breathing"] = max(0, min(1, abs(z_score) / 3.0))

        # EDA
        if metrics.get("eda") is not None:
            eda = metrics["eda"]
            baseline = self.baselines["eda"]
            percent_change = (eda - baseline["mean"]) / baseline["mean"]
            scores["eda"] = max(0, min(1, percent_change / 2.0))

        # Chest breathing
        if metrics.get("chest_breathing") is not None:
            chest = metrics["chest_breathing"]
            baseline = self.baselines["chest_breathing"]
            z_score = (chest - baseline["mean"]) / baseline["std"]
            scores["chest_breathing"] = max(0, min(1, abs(z_score) / 3.0))

        return scores

    def _calculate_rate_of_change(self) -> float:
        """How fast is heart rate changing"""
        if len(self.metric_history) < 2:
            return 0.0

        current = self.metric_history[-1]
        past = self.metric_history[-2]

        if current.get("hr") is None or past.get("hr") is None:
            return 0.0

        time_diff = (current["timestamp_ms"] - past["timestamp_ms"]) / 1000.0
        if time_diff < 0.1:
            return 0.0

        hr_velocity = abs(current["hr"] - past["hr"]) / time_diff
        return max(0, min(1, hr_velocity / 2.0))

    def _combine_scores(self, normalized: Dict, rate_of_change: float) -> float:
        """Combine all scores with weights"""
        weights = {"hr": 0.30, "eda": 0.25, "breathing": 0.20, "chest_breathing": 0.10, "rate_of_change": 0.15}

        total_score = 0.0
        total_weight = 0.0

        for key, weight in weights.items():
            if key == "rate_of_change":
                total_score += weight * rate_of_change
                total_weight += weight
            elif key in normalized:
                total_score += weight * normalized[key]
                total_weight += weight

        if total_weight > 0:
            return total_score / total_weight

        return 0.0

    # ===== GETTER METHODS FOR INDIVIDUAL METRICS =====

    def get_heart_rate(self) -> Optional[float]:
        """Get current averaged heart rate (bpm)"""
        return self.current_hr

    def get_breathing_rate(self) -> Optional[float]:
        """Get current averaged breathing rate (breaths/min)"""
        return self.current_breathing

    def get_eda(self) -> Optional[float]:
        """Get current averaged EDA value"""
        return self.current_eda

    def get_chest_breathing(self) -> Optional[float]:
        """Get current averaged chest breathing value"""
        return self.current_chest_breathing

    def get_threat_score(self) -> float:
        """Get current threat score (0-1)"""
        return self.current_threat_score

    def get_all_metrics(self) -> Dict:
        """Get all current metrics at once"""
        return {
            "heart_rate": self.current_hr,
            "breathing_rate": self.current_breathing,
            "eda": self.current_eda,
            "chest_breathing": self.current_chest_breathing,
            "threat_score": self.current_threat_score,
        }


# Simple usage example
if __name__ == "__main__":
    detector = ThreatDetector(averaging_window=0.5)

    # Example: process a JSON packet
    packet = '{"type":"core_metrics","timestamp_ms":1769308247784,"data":{"pulse":{"heart_rate":{"value":85,"stable":true,"confidence":0.95}},"breathing":{"respiratory_rate":{"value":18,"stable":true}}}}'

    threat_score = detector.process_packet(packet)

    if threat_score is not None:
        print(f"Threat Score: {threat_score:.3f}")
        print(f"Heart Rate: {detector.get_heart_rate():.1f}")
