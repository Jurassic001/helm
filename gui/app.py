import sys
import os
import cv2

# Ensure project root is on sys.path for lib imports when running as script
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.ThreatEval import ThreatDetector

from PySide6.QtWidgets import QApplication, QLabel, QComboBox, QMessageBox, QPushButton, QTextBrowser
from PySide6.QtCore import QTimer, Qt, QFile
from PySide6.QtGui import QImage, QPixmap, QColor
from PySide6.QtUiTools import QUiLoader



class MainWindow:
    # Thresholds per security level to avoid rebuilding dicts every call
    THREAT_THRESHOLDS = {
        "LOW": {
            "FRAME CLEAR": 0.0,
            "SAFE": 0.15,
            "CAUTION": 0.40,
            "WARNING": 0.65,
            "DANGER": 0.85,
        },
        "MEDIUM": {
            "FRAME CLEAR": 0.0,
            "SAFE": 0.10,
            "CAUTION": 0.30,
            "WARNING": 0.55,
            "DANGER": 0.75,
        },
        "HIGH": {
            "FRAME CLEAR": 0.0,
            "SAFE": 0.05,
            "CAUTION": 0.20,
            "WARNING": 0.40,
            "DANGER": 0.60,
        },
    }


    def __init__(self, detector: ThreatDetector):
        self.detector = detector
        # Variable for composite threat score
        self.composite_threat_score = 0 # number 0-1 representing overall threat level
        # Variable for current security level
        self.current_security_level = "LOW"  # Possible values: "LOW", "MEDIUM", "HIGH"    
        # Variable for vitals dictionary
        self.vitals = {}

        # Variable to track threat estimate
        self.threat_estimate = "FRAME CLEAR"  # Possible values: "FRAME CLEAR", "SAFE", "CAUTION", "WARNING", "DANGER"

        # --- Load UI ---
        ui_path = os.path.join(os.path.dirname(__file__), "designer2.ui")
        if not os.path.exists(ui_path):
            raise RuntimeError(f"UI file not found at: {ui_path}")

        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"Cannot open UI file: {ui_path}")

        loader = QUiLoader()
        self.window = loader.load(ui_file)
        ui_file.close()

        if self.window is None:
            raise RuntimeError("Failed to load UI")

        # --- Setup UI elements from GUI_buttons ---
        self.setup_ui_elements()

        # --- Access QLabel for camera feed ---
        self.camera_label = self.window.findChild(QLabel, "camera_label")
        if self.camera_label is None:
            raise RuntimeError(
                "camera_label not found. Make sure QLabel objectName is 'camera_label'"
            )

        # --- Set initial window size ---

        # --- Open webcam ---
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError("Could not open webcam")

        # Hint capture resolution toward the display area to reduce scaling
        target_w = self.camera_label.width() or 640
        target_h = self.camera_label.height() or 480
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)

        # --- Timer to update frames ---
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)  # ~30 FPS

    def setup_ui_elements(self):
        """Setup UI elements (security level combo, threat level label, etc.)"""
        # Security level combo box styling
        sec_level_combo = self.window.findChild(QComboBox, "sec_level_combo")
        initial_level_text = None
        if sec_level_combo:
            self.sec_level_combo = sec_level_combo
            # Set text colors: low=green, medium=yellow, heavy=red
            sec_level_combo.setItemData(0, QColor("green"), Qt.ForegroundRole)
            sec_level_combo.setItemData(1, QColor("orange"), Qt.ForegroundRole)
            sec_level_combo.setItemData(2, QColor("red"), Qt.ForegroundRole)
            # Capture initial selection and connect handler
            initial_level_text = sec_level_combo.currentText()
            sec_level_combo.currentTextChanged.connect(self.update_security_level)
        
        # Threat level label
        self.threat_level_label = self.window.findChild(QLabel, "threat_level_label")
        if self.threat_level_label:
            if initial_level_text:
                # Sync internal state with UI selection and refresh display
                self.update_security_level(initial_level_text)
            else:
                self.calculate_threat_estimate()

        # Stats text widget (for displaying vitals)
        self.stats_text = self.window.findChild(QTextBrowser, "stats_text")

        # Help button
        help_button = self.window.findChild(QPushButton, "help_button")
        if help_button:
            help_button.clicked.connect(self.show_help)

        # Quit button
        quit_button = self.window.findChild(QPushButton, "quit_button")
        if quit_button:
            quit_button.setStyleSheet(
                "QPushButton {"
                " background-color: #dc2626; color: #ffffff; border: none;"
                " padding: 8px 16px; border-radius: 6px; font-weight: bold;"
                " }"
                " QPushButton:hover { background-color: #b91c1c; }"
                " QPushButton:pressed { background-color: #991b1b; }"
            )
            quit_button.clicked.connect(self.handle_quit)

    def update_threat_level(self, threat_estimate):
        """Update the threat level label text and color"""
        self.threat_estimate = threat_estimate
        if self.threat_level_label:
            self.threat_level_label.setText(threat_estimate)
            if threat_estimate == "FRAME CLEAR":
                self.threat_level_label.setStyleSheet("color: #666666; font-weight: bold;")
            elif threat_estimate == "SAFE":
                self.threat_level_label.setStyleSheet("color: #008000; font-weight: bold;")
            elif threat_estimate == "CAUTION":
                self.threat_level_label.setStyleSheet("color: #DAA520; font-weight: bold;")
            elif threat_estimate == "WARNING":
                self.threat_level_label.setStyleSheet("color: #FF8C00; font-weight: bold;")
            elif threat_estimate == "DANGER":
                self.threat_level_label.setStyleSheet("color: #DC143C; font-weight: bold;")

    def update_security_level(self, text):
        """Update current_security_level based on combo selection"""
        if text == "Low":
            self.current_security_level = "LOW"
        elif text == "Medium":
            self.current_security_level = "MEDIUM"
        elif text == "High":
            self.current_security_level = "HIGH"

        # Match combo text color to selection
        color_map = {"LOW": "green", "MEDIUM": "orange", "HIGH": "red"}
        if getattr(self, "sec_level_combo", None):
            color = color_map.get(self.current_security_level, "#334155")
            self.sec_level_combo.setStyleSheet(f"color: {color};")
        # Re-calculate threat estimate with new security level
        self.calculate_threat_estimate()

    def calculate_threat_estimate(self):
        """Calculate threat estimate based on composite_threat_score and security level"""
        thresholds = self.THREAT_THRESHOLDS.get(
            self.current_security_level, self.THREAT_THRESHOLDS["MEDIUM"]
        )
        
        # Determine threat estimate based on score
        if self.composite_threat_score == 0.0:
            new_estimate = "FRAME CLEAR"
        elif self.composite_threat_score <= thresholds["SAFE"]:
            new_estimate = "FRAME CLEAR"
        elif self.composite_threat_score <= thresholds["CAUTION"]:
            new_estimate = "SAFE"
        elif self.composite_threat_score <= thresholds["WARNING"]:
            new_estimate = "CAUTION"
        elif self.composite_threat_score <= thresholds["DANGER"]:
            new_estimate = "WARNING"
        else:
            new_estimate = "DANGER"
        
        # Update the threat level if it changed
        if new_estimate != self.threat_estimate:
            self.update_threat_level(new_estimate)

    def show_help(self):
        """Show help dialog"""
        msg_box = QMessageBox(self.window)
        msg_box.setWindowTitle("Help - Helm")
        msg_box.setText(
            "Welcome to Helm! Keep an eye on your surroundings with the live feed and quick status cues.\n\n"
            "Quick Guide\n"
            "- [Security Level] (green/orange/red text): Sets sensitivity (Low, Medium, High). Higher = more cautious.\n"
            "- [Threat Estimate]: Color-coded label (gray/green/gold/orange/crimson) showing current risk.\n"
            "- [Live Feed]: Camera view fills the frame; use the red Quit button to exit cleanly.\n"
            "- [Analysis]: Basic stats (pulse, breathing, expression) to spot changes.\n"
            "- [Summary]: One-line rationale explaining why the threat level is set (e.g., object detected, agitated behavior).\n"
            "- [Accessibility] tab: adjust comfort settings.\n\n"
            "Tips\n"
            "- Start on Medium; move to High if you need stricter alerts.\n"
            "- Watch the threat color and Summary for context before reacting.\n"
            "- If the feed stalls, try switching tabs or restart with Quit then relaunch."
        )
        # Set custom icon from info_icon.png
        icon_pixmap = QPixmap("gui/assets/info_icon.png")
        if not icon_pixmap.isNull():
            # Scale to standard icon size (e.g., 32x32)
            scaled_pixmap = icon_pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            msg_box.setIconPixmap(scaled_pixmap)
        else:
            msg_box.setIcon(QMessageBox.Icon.Information)  # Fallback to default
        msg_box.exec()

    def handle_quit(self):
        """Handle quit button click"""
        # Fast-path quit: let the aboutToQuit hook clean up resources
        app = QApplication.instance()
        if app:
            app.quit()

    def update_frame(self):
        # TODO: Replace with real incoming packet; this is a placeholder sample
        sample_packet = '{"type":"core_metrics","timestamp_ms":1769308247784,"data":{"pulse":{"heart_rate":{"value":85,"stable":true,"confidence":0.95}},"breathing":{"respiratory_rate":{"value":18,"stable":true}}}}'

        threat_score = self.detector.process_packet(sample_packet)
        if threat_score is not None:
            self.composite_threat_score = threat_score
            self.calculate_threat_estimate()
        
        self.vitals = self.detector.get_all_metrics()
        
        # Update stats_text with vitals dictionary
        if self.stats_text and self.vitals:
            # Map keys to plain English with units
            labels = {
                'heart_rate': ('Heart Rate', 'BPM'),
                'breathing_rate': ('Breathing Rate', 'BPM'),
                'eda': ('EDA', ''),
                'chest_breathing': ('Chest Breathing', '')
            }
            
            vitals_lines = []
            for key, value in self.vitals.items():
                label, unit = labels.get(key, (key.replace('_', ' ').title(), ''))
                if value is not None:
                    formatted_value = f"{value:.1f}" if isinstance(value, (int, float)) else str(value)
                    if unit and key != 'threat_score':
                        vitals_lines.append(f"{label}: {formatted_value} {unit}")
                    else:
                        if key != 'threat_score':
                            vitals_lines.append(f"{label}: {formatted_value}")
                else:
                    vitals_lines.append(f"{label}: --")
            
            self.stats_text.setText("\n".join(vitals_lines))

        ret, frame = self.cap.read()
        if not ret:
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w

        qt_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image)

        # Scale to fill the QLabel with center-crop for a better fit
        target_w = self.camera_label.width()
        target_h = self.camera_label.height()
        if target_w <= 0 or target_h <= 0:
            return  # Wait until layout gives the label a real size
        scaled = pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Center-crop to the label's exact size
        x_offset = max(0, (scaled.width() - target_w) // 2)
        y_offset = max(0, (scaled.height() - target_h) // 2)
        cropped = scaled.copy(x_offset, y_offset, target_w, target_h)
        self.camera_label.setPixmap(cropped)

    def show(self):
        self.window.show()

    def close(self):
        self.timer.stop()
        self.cap.release()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    detector = ThreatDetector()

    main_window = MainWindow(detector)

    app.aboutToQuit.connect(main_window.close)

    main_window.show()

    sys.exit(app.exec())
