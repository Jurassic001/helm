from typing import Dict

import anthropic
from loguru import logger


class ThreatSummaryGenerator:
    """Generate AI-powered summaries of threat assessments using Claude"""

    def __init__(self, anthropic_api_key: str):
        """
        Initialize the summary generator

        Args:
            anthropic_api_key: Your Anthropic API key
        """
        self.api_key = anthropic_api_key
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)

        # Baseline values for context
        self.baselines = {"hr": 70, "breathing": 16, "eda": 0.15, "chest_breathing": 0.4}

    def generate_summary(self, metrics: Dict) -> str:
        """
        Generate a short summary of threat level using Claude AI

        Args:
            metrics: Dictionary containing:
                - threat_score: float (0.0 to 1.0)
                - heart_rate: Optional[float] (bpm)
                - breathing_rate: Optional[float] (breaths/min)
                - eda: Optional[float]
                - chest_breathing: Optional[float]

        Returns:
            String summary of the threat assessment
        """

        # Extract values from dictionary
        threat_score = metrics.get("threat_score", 0.0)
        heart_rate = metrics.get("heart_rate")
        breathing_rate = metrics.get("breathing_rate")
        eda = metrics.get("eda")
        chest_breathing = metrics.get("chest_breathing")

        # Build metrics summary
        metrics_text = self._build_metrics_text(heart_rate, breathing_rate, eda, chest_breathing)

        # Create prompt for Claude
        prompt = self._create_prompt(threat_score, metrics_text)

        try:
            # Call Claude API
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514", max_tokens=150, messages=[{"role": "user", "content": prompt}]
            )

            text = message.content[0].text
            text = "".join(block.text for block in message.content if hasattr(block, "text"))
            return text.strip()

        except Exception as e:
            logger.error(f"Error generating summary: {str(e)}")
            raise  # Re-raise so the caller knows something went wrong

    def _build_metrics_text(self, heart_rate, breathing_rate, eda, chest_breathing) -> str:
        """Build formatted metrics text for the prompt"""
        metrics_text = []

        if heart_rate is not None:
            deviation = ((heart_rate - self.baselines["hr"]) / self.baselines["hr"]) * 100
            metrics_text.append(
                f"Heart rate: {heart_rate:.1f} bpm (baseline: {self.baselines['hr']} bpm, {deviation:+.0f}%)"
            )

        if breathing_rate is not None:
            deviation = ((breathing_rate - self.baselines["breathing"]) / self.baselines["breathing"]) * 100
            metrics_text.append(
                f"Breathing rate: {breathing_rate:.1f} breaths/min "
                f"(baseline: {self.baselines['breathing']} breaths/min, {deviation:+.0f}%)"
            )

        if eda is not None:
            deviation = ((eda - self.baselines["eda"]) / self.baselines["eda"]) * 100
            metrics_text.append(
                f"EDA (skin conductance): {eda:.3f} (baseline: {self.baselines['eda']:.3f}, {deviation:+.0f}%)"
            )

        if chest_breathing is not None:
            metrics_text.append(f"Chest breathing: {chest_breathing:.2f}")

        return "\n".join(metrics_text) if metrics_text else "No biometric data available"

    def _create_prompt(self, threat_score: float, metrics_text: str) -> str:
        """Create the prompt for Claude"""
        return f"""You are analyzing biometric data for threat detection. Based on the following information, provide a brief 2-3 sentence summary of the person's current physiological state:

Threat Score: {threat_score:.3f} (scale: 0.0 = calm, 1.0 = high threat/stress)

Current Biometrics:
{metrics_text}

Provide a concise, factual assessment of what these readings suggest. Be direct and professional."""
