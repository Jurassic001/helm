import time
from collections import deque
from typing import Dict, Optional


class ThreatDetector:
    def __init__(self, averaging_window=0.5):
        # Population-based norms (typical resting values)
        self.baselines = {
            "hr": {"mean": 70, "std": 12},
            "eda": {"mean": 0.15, "std": 0.05},
            "chest_breathing": {"mean": 0.4, "std": 0.1},
            "micromotion": {"mean": 0.1, "std": 0.05},
        }

        # Averaging window in seconds
        self.averaging_window = averaging_window

        # Buffers to collect data for averaging (store with timestamps)
        self.hr_buffer = deque()
        self.eda_buffer = deque()
        self.chest_breathing_buffer = deque()
        self.talking_buffer = deque()
        self.blink_buffer = deque()
        self.micromotion_buffer = deque()

        # History for rate of change (averaged values)
        self.metric_history = deque(maxlen=30)

        # Current values (latest averages)
        self.current_hr = None
        self.current_eda = None
        self.current_chest_breathing = None
        self.current_talking = None  # Percentage of time talking (0-100)
        self.current_blink_rate = None  # Percentage of time blinking detected
        self.current_micromotion = None
        self.current_threat_score = 0.0

        # Last calculation time
        self.last_calculation_time = time.time()

    def process_message(self, message: dict) -> Optional[float]:
        """Process incoming Presage messages and add to buffers"""
        msg_type = message.get("type")
        timestamp_ms = message.get("timestamp_ms", time.time() * 1000)
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
        if pulse_data.get("confidence", 0) != 0:
            hr = pulse_data.get("value")
            if hr is not None:
                self.hr_buffer.append((current_time, hr))

        # Buffer face metrics (talking and blinking)
        face_data = data.get("face", {})

        # Buffer talking detection (convert bool to 0/1)
        talking_data = face_data.get("talking", {})
        if talking_data.get("stable", False):
            talking = 1.0 if talking_data.get("detected", False) else 0.0
            self.talking_buffer.append((current_time, talking))

        # Buffer blink detection (convert bool to 0/1)
        blinking_data = face_data.get("blinking", {})
        if blinking_data.get("stable", False):
            blink = 1.0 if blinking_data.get("detected", False) else 0.0
            self.blink_buffer.append((current_time, blink))

    def _buffer_edge_metrics(self, data: Dict, timestamp_ms: int):
        """Add edge metrics to buffers"""
        current_time = time.time()

        # Buffer chest breathing (edge metrics use 'stable' not 'confidence')
        chest_data = data.get("chest_breathing", {})
        chest_value = chest_data.get("value")
        if chest_value is not None:
            self.chest_breathing_buffer.append((current_time, chest_value))

        # Buffer EDA (edge metrics use 'stable' not 'confidence')
        eda_data = data.get("eda", {})
        eda_value = eda_data.get("value")
        if eda_value is not None:
            self.eda_buffer.append((current_time, eda_value))

        # Buffer micromotion (average of glutes and knees)
        glutes_data = data.get("micromotion_glutes", {})
        knees_data = data.get("micromotion_knees", {})
        glutes_value = glutes_data.get("value")
        knees_value = knees_data.get("value")
        if glutes_value is not None or knees_value is not None:
            # Average available values
            values = [v for v in [glutes_value, knees_value] if v is not None]
            micromotion = sum(values) / len(values)
            self.micromotion_buffer.append((current_time, micromotion))

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
        avg_eda = self._calculate_average(self.eda_buffer)
        avg_chest_breathing = self._calculate_average(self.chest_breathing_buffer)
        avg_talking = self._calculate_average(self.talking_buffer)
        avg_blink = self._calculate_average(self.blink_buffer)
        avg_micromotion = self._calculate_average(self.micromotion_buffer)

        # Update current values
        if avg_hr is not None:
            self.current_hr = avg_hr
        if avg_eda is not None:
            self.current_eda = avg_eda
        if avg_chest_breathing is not None:
            self.current_chest_breathing = avg_chest_breathing
        if avg_talking is not None:
            self.current_talking = avg_talking * 100  # Convert to percentage
        if avg_blink is not None:
            self.current_blink_rate = avg_blink * 100  # Convert to percentage
        if avg_micromotion is not None:
            self.current_micromotion = avg_micromotion

        # Store in history for rate of change
        metrics = {
            "hr": avg_hr,
            "eda": avg_eda,
            "chest_breathing": avg_chest_breathing,
            "micromotion": avg_micromotion,
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

        # Micromotion (higher values indicate more fidgeting/stress)
        if metrics.get("micromotion") is not None:
            micromotion = metrics["micromotion"]
            baseline = self.baselines["micromotion"]
            z_score = (micromotion - baseline["mean"]) / baseline["std"]
            scores["micromotion"] = max(0, min(1, abs(z_score) / 3.0))

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
        # Weights redistributed: removed breathing (20%), added micromotion (20%)
        weights = {"hr": 0.30, "eda": 0.25, "micromotion": 0.20, "chest_breathing": 0.10, "rate_of_change": 0.15}

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

    def get_talking(self) -> Optional[float]:
        """Get current talking percentage (0-100)"""
        return self.current_talking

    def get_blink_rate(self) -> Optional[float]:
        """Get current blink rate percentage (0-100)"""
        return self.current_blink_rate

    def get_micromotion(self) -> Optional[float]:
        """Get current micromotion value"""
        return self.current_micromotion

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
            "eda": self.current_eda,
            "chest_breathing": self.current_chest_breathing,
            "talking": self.current_talking,
            "blink_rate": self.current_blink_rate,
            "micromotion": self.current_micromotion,
            "threat_score": self.current_threat_score,
        }
