import json
import os
from pathlib import Path

import cv2
import mediapipe as mp
from loguru import logger
from PySide6.QtCore import QFile, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPalette, QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QMessageBox, QPushButton, QTextBrowser

from lib.threat_eval import ThreatDetector
from lib.threat_summery import ThreatSummaryGenerator


class SummaryWorker(QThread):
    """QThread worker for generating AI threat summaries without blocking the UI."""

    finished = Signal(str)  # Emits the summary text on success
    error = Signal(str)  # Emits error message on failure

    def __init__(self, generator: ThreatSummaryGenerator, metrics: dict):
        super().__init__()
        self.generator = generator
        self.metrics = metrics

    def run(self):
        """Generate summary in background thread."""
        try:
            summary = self.generator.generate_summary(self.metrics)
            self.finished.emit(summary)
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            self.error.emit(str(e))


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

    def __init__(self):
        # --- Initialize variables ---
        self.detector = ThreatDetector()
        # Variable for composite threat score
        self.composite_threat_score = 0  # number 0-1 representing overall threat level
        # Variable for current security level
        self.current_security_level = "LOW"  # Possible values: "LOW", "MEDIUM", "HIGH"
        # Variable for vitals dictionary
        self.vitals = {}
        self.threat_score = None

        # Variable to track threat estimate
        self.threat_estimate = "FRAME CLEAR"  # Possible values: "FRAME CLEAR", "SAFE", "CAUTION", "WARNING", "DANGER"
        self.wireframe_color = (255, 255, 255)

        # Theme tracking
        self.current_theme = "System"  # Possible values: "System", "Light", "Dark"

        # --- Load Anthropic API key for summary generation ---
        self.summary_generator = None
        self._summary_thread = None
        anthropic_key = self._load_anthropic_api_key()
        if anthropic_key:
            try:
                self.summary_generator = ThreatSummaryGenerator(anthropic_key)
                logger.info("Threat summary generator initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize summary generator: {e}")
        else:
            logger.warning("No Anthropic API key found - summary generation disabled")

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
        self.camera_label2 = self.window.findChild(QLabel, "camera_feed_2")
        if self.camera_label is None or self.camera_label2 is None:
            raise RuntimeError(
                "camera_label(s) not found. Make sure QLabel objectName is 'camera_label' and 'camera_label2'"
            )

        # --- Set initial window size ---

        # --- Open webcam ---
        self.cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError("Could not open webcam")

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

        # Theme combo box
        theme_combo = self.window.findChild(QComboBox, "theme_combo")
        if theme_combo:
            self.theme_combo = theme_combo
            theme_combo.currentTextChanged.connect(self.apply_theme)
            # Apply system theme on startup
            self.apply_theme("System")

        # Summary text widget and generate button
        self.summary_text = self.window.findChild(QTextBrowser, "stats_text_2")
        generate_button = self.window.findChild(QPushButton, "pushButton")
        if generate_button:
            self.generate_button = generate_button
            generate_button.clicked.connect(self.on_generate_summary)
            # Disable button if no API key configured
            if not self.summary_generator:
                generate_button.setEnabled(False)
                generate_button.setToolTip("Add 'anthropic_api_key' to gui/settings.json to enable")

    def update_threat_level(self, threat_estimate):
        """Update the threat level label text and color"""
        self.threat_estimate = threat_estimate
        if self.threat_level_label:
            self.threat_level_label.setText(threat_estimate)
            if threat_estimate == "FRAME CLEAR":
                self.threat_level_label.setStyleSheet("color: #666666; font-weight: bold;")
                self.wireframe_color = (255, 255, 255)
            elif threat_estimate == "SAFE":
                self.threat_level_label.setStyleSheet("color: #008000; font-weight: bold;")
                self.wireframe_color = (0, 255, 0)
            elif threat_estimate == "CAUTION":
                self.threat_level_label.setStyleSheet("color: #DAA520; font-weight: bold;")
                self.wireframe_color = (0, 255, 255)
            elif threat_estimate == "WARNING":
                self.threat_level_label.setStyleSheet("color: #FF8C00; font-weight: bold;")
                self.wireframe_color = (0, 165, 255)
            elif threat_estimate == "DANGER":
                self.threat_level_label.setStyleSheet("color: #DC143C; font-weight: bold;")
                self.wireframe_color = (0, 0, 255)

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

    def _is_system_dark_mode(self) -> bool:
        """Detect if the system is using dark mode"""
        app = QApplication.instance()
        if app:
            palette = app.palette()
            # Compare window background lightness - dark themes have low lightness
            bg_color = palette.color(QPalette.ColorRole.Window)
            return bg_color.lightness() < 128
        return False

    def apply_theme(self, theme: str):
        """Apply the selected theme (System, Light, or Dark)"""
        self.current_theme = theme

        # Determine effective theme
        if theme == "System":
            use_dark = self._is_system_dark_mode()
        elif theme == "Dark":
            use_dark = True
        else:  # Light
            use_dark = False

        # Clear inline stylesheets from child widgets (they override parent styles)
        self._clear_child_stylesheets()

        if use_dark:
            self._apply_dark_theme()
        else:
            self._apply_light_theme()

        # Re-apply threat level styling after theme change
        self.update_threat_level(self.threat_estimate)
        # Re-apply security level combo styling
        self.update_security_level(self.sec_level_combo.currentText() if hasattr(self, "sec_level_combo") else "Low")

    def _clear_child_stylesheets(self):
        """Clear inline stylesheets from child widgets so parent theme can apply"""
        from PySide6.QtWidgets import QWidget

        # Find all child widgets and clear their inline stylesheets
        for child in self.window.findChildren(QWidget):
            if child.styleSheet():
                child.setStyleSheet("")

    def _apply_light_theme(self):
        """Apply light theme stylesheet"""
        light_style = """
            QDialog {
                background-color: #f8fafc;
            }
            QTabWidget::pane {
                border: none;
                background-color: #ffffff;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #e2e8f0;
                color: #64748b;
                padding: 10px 24px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #ffffff;
                color: #1e40af;
            }
            QTabBar::tab:hover:!selected {
                background-color: #cbd5e1;
                color: #1e40af;
            }
            QLabel {
                color: #334155;
            }
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QPushButton:pressed {
                background-color: #1d4ed8;
            }
            QComboBox {
                background-color: #ffffff;
                color: #334155;
                border: 1px solid #cbd5e1;
                padding: 6px 12px;
                border-radius: 6px;
            }
            QComboBox:hover {
                border-color: #3b82f6;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #334155;
                selection-background-color: #dbeafe;
            }
            QTextBrowser {
                background-color: #f1f5f9;
                color: #334155;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                padding: 8px;
            }
            QFrame#left_feed_frame, QFrame#analysis_frame, QFrame#right_feed_frame, QFrame#controls_frame {
                background-color: #f8fafc;
                border-radius: 10px;
                border: 1px solid #e2e8f0;
            }
            QLabel#camera_label, QLabel#camera_feed_2 {
                background-color: #1e293b;
                border: 2px solid #cbd5e1;
                border-radius: 8px;
                color: #94a3b8;
            }
            QLabel#live_feed_title, QLabel#augmented_feed_title, QLabel#analysis_label, QLabel#controls_label {
                color: #475569;
                background: transparent;
            }
            QLabel#sec_level_label, QLabel#theme_label {
                color: #334155;
                background: transparent;
            }
            QLabel#summary_label {
                color: #64748b;
                background: transparent;
            }
            QLabel#status_label {
                color: #22c55e;
                background: transparent;
            }
        """
        self.window.setStyleSheet(light_style)

    def _apply_dark_theme(self):
        """Apply dark theme stylesheet"""
        dark_style = """
            QDialog {
                background-color: #0f172a;
            }
            QTabWidget::pane {
                border: none;
                background-color: #1e293b;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #334155;
                color: #94a3b8;
                padding: 10px 24px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #1e293b;
                color: #60a5fa;
            }
            QTabBar::tab:hover:!selected {
                background-color: #475569;
                color: #60a5fa;
            }
            QLabel {
                color: #e2e8f0;
            }
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QPushButton:pressed {
                background-color: #1d4ed8;
            }
            QComboBox {
                background-color: #334155;
                color: #e2e8f0;
                border: 1px solid #475569;
                padding: 6px 12px;
                border-radius: 6px;
            }
            QComboBox:hover {
                border-color: #3b82f6;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #334155;
                color: #e2e8f0;
                selection-background-color: #1e40af;
            }
            QTextBrowser {
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px;
            }
            QFrame#left_feed_frame, QFrame#analysis_frame, QFrame#right_feed_frame, QFrame#controls_frame {
                background-color: #1e293b;
                border-radius: 10px;
                border: 1px solid #334155;
            }
            QLabel#camera_label, QLabel#camera_feed_2 {
                background-color: #0f172a;
                border: 2px solid #475569;
                border-radius: 8px;
                color: #64748b;
            }
            QLabel#live_feed_title, QLabel#augmented_feed_title, QLabel#analysis_label, QLabel#controls_label {
                color: #94a3b8;
                background: transparent;
            }
            QLabel#sec_level_label, QLabel#theme_label {
                color: #cbd5e1;
                background: transparent;
            }
            QLabel#summary_label {
                color: #94a3b8;
                background: transparent;
            }
            QLabel#status_label {
                color: #22c55e;
                background: transparent;
            }
        """
        self.window.setStyleSheet(dark_style)

    def calculate_threat_estimate(self):
        """Calculate threat estimate based on composite_threat_score and security level"""
        thresholds = self.THREAT_THRESHOLDS.get(self.current_security_level, self.THREAT_THRESHOLDS["MEDIUM"])

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
            scaled_pixmap = icon_pixmap.scaled(
                32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
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
        if self.threat_score is not None:
            self.composite_threat_score = self.threat_score
            self.calculate_threat_estimate()

        self.vitals = self.detector.get_all_metrics()

        # Update stats_text with vitals dictionary
        if self.stats_text and self.vitals:
            # Map keys to plain English with units
            labels = {
                "heart_rate": ("Heart Rate", "BPM"),
                "eda": ("EDA", ""),
                "chest_breathing": ("Chest Breathing", ""),
                "talking": ("Talking", "%"),
                "blink_rate": ("Blink Rate", "%"),
                "micromotion": ("Micromotion", ""),
            }

            # Define display order for metrics
            display_order = ["heart_rate", "eda", "chest_breathing", "talking", "blink_rate", "micromotion"]

            vitals_lines = []
            for key in display_order:
                if key not in self.vitals:
                    continue
                value = self.vitals[key]
                label, unit = labels.get(key, (key.replace("_", " ").title(), ""))
                if value is not None:
                    formatted_value = f"{value:.1f}" if isinstance(value, (int, float)) else str(value)
                    if unit:
                        vitals_lines.append(f"{label}: {formatted_value} {unit}")
                    else:
                        vitals_lines.append(f"{label}: {formatted_value}")
                else:
                    vitals_lines.append(f"{label}: N/A")

            self.stats_text.setText("\n".join(vitals_lines))

        ret, frame = self.cap.read()
        if not ret:
            return

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w

        qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
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

        # Create wireframe overlay for camera_label2
        wireframe = self._create_wireframe_overlay(frame)
        wireframe_rgb = cv2.cvtColor(wireframe, cv2.COLOR_BGR2RGB)
        wf_h, wf_w, wf_ch = wireframe_rgb.shape
        wf_bytes_per_line = wf_ch * wf_w
        wf_image = QImage(wireframe_rgb.data, wf_w, wf_h, wf_bytes_per_line, QImage.Format.Format_RGB888)
        wf_pixmap = QPixmap.fromImage(wf_image)

        target_w2 = self.camera_label2.width()
        target_h2 = self.camera_label2.height()
        if target_w2 > 0 and target_h2 > 0:
            scaled_wf = wf_pixmap.scaled(
                target_w2,
                target_h2,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off2 = max(0, (scaled_wf.width() - target_w2) // 2)
            y_off2 = max(0, (scaled_wf.height() - target_h2) // 2)
            cropped_wf = scaled_wf.copy(x_off2, y_off2, target_w2, target_h2)
            self.camera_label2.setPixmap(cropped_wf)

    def _create_wireframe_overlay(self, frame):
        """Create a wireframe overlay with face mesh, hand landmarks, and body pose"""

        # Initialize mediapipe Holistic (lazy init) - combines face, hands, and pose
        if not hasattr(self, "_mp_holistic"):
            self._mp_holistic = mp.solutions.holistic.Holistic(
                static_image_mode=False,
                model_complexity=0,  # 0=Lite for speed, 1=Full, 2=Heavy
                smooth_landmarks=True,
                enable_segmentation=False,
                refine_face_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._mp_drawing = mp.solutions.drawing_utils
            self._mp_drawing_styles = mp.solutions.drawing_styles
            self._mp_face_mesh_module = mp.solutions.face_mesh
            self._mp_hands_module = mp.solutions.hands
            self._mp_pose_module = mp.solutions.pose

        # Create dark background for wireframe
        wireframe = frame.copy()
        wireframe = cv2.addWeighted(wireframe, 0.2, wireframe * 0, 0.8, 0)

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Process with Holistic (single pass for face, hands, and pose)
        results = self._mp_holistic.process(frame_rgb)

        # Draw face mesh
        if results.face_landmarks:
            self._mp_drawing.draw_landmarks(
                image=wireframe,
                landmark_list=results.face_landmarks,
                connections=self._mp_face_mesh_module.FACEMESH_TESSELATION,
                landmark_drawing_spec=None,
                connection_drawing_spec=self._mp_drawing.DrawingSpec(
                    color=self.wireframe_color, thickness=1, circle_radius=1
                ),
            )
            # Draw contours
            self._mp_drawing.draw_landmarks(
                image=wireframe,
                landmark_list=results.face_landmarks,
                connections=self._mp_face_mesh_module.FACEMESH_CONTOURS,
                landmark_drawing_spec=None,
                connection_drawing_spec=self._mp_drawing.DrawingSpec(
                    color=self.wireframe_color, thickness=1, circle_radius=1
                ),
            )

        # Draw left hand landmarks
        if results.left_hand_landmarks:
            self._mp_drawing.draw_landmarks(
                image=wireframe,
                landmark_list=results.left_hand_landmarks,
                connections=self._mp_hands_module.HAND_CONNECTIONS,
                landmark_drawing_spec=self._mp_drawing.DrawingSpec(
                    color=self.wireframe_color, thickness=2, circle_radius=3
                ),
                connection_drawing_spec=self._mp_drawing.DrawingSpec(
                    color=self.wireframe_color, thickness=2, circle_radius=3
                ),
            )

        # Draw right hand landmarks
        if results.right_hand_landmarks:
            self._mp_drawing.draw_landmarks(
                image=wireframe,
                landmark_list=results.right_hand_landmarks,
                connections=self._mp_hands_module.HAND_CONNECTIONS,
                landmark_drawing_spec=self._mp_drawing.DrawingSpec(
                    color=self.wireframe_color, thickness=2, circle_radius=3
                ),
                connection_drawing_spec=self._mp_drawing.DrawingSpec(
                    color=self.wireframe_color, thickness=2, circle_radius=3
                ),
            )

        return wireframe

    def gui_message_handler(self, message: dict):
        """Evaluate threat score from incoming message"""
        msg_type = message.get("type", "unknown")

        if msg_type in ("core_metrics", "edge_metrics"):
            self.threat_score = self.detector.process_message(message)

    def _load_anthropic_api_key(self) -> str:
        """Load Anthropic API key from gui/settings.json."""
        settings_path = Path(__file__).parent / "settings.json"
        if not settings_path.exists():
            logger.warning(f"Settings file not found: {settings_path}")
            return ""
        try:
            with open(settings_path) as f:
                settings = json.load(f)
                return settings.get("anthropic_api_key", "")
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to load settings: {e}")
            return ""

    def on_generate_summary(self):
        """Handle generate summary button click - runs API call in background QThread."""
        if not self.summary_generator:
            return

        # Prevent multiple concurrent requests
        if self._summary_thread and self._summary_thread.isRunning():
            logger.warning("Summary generation already in progress")
            return

        # Update UI to show loading state
        if self.summary_text:
            self.summary_text.setText("Generating summary...")
        if hasattr(self, "generate_button"):
            self.generate_button.setEnabled(False)

        # Create and configure worker thread
        self._summary_thread = SummaryWorker(self.summary_generator, self.vitals.copy())
        self._summary_thread.finished.connect(self._on_summary_complete)
        self._summary_thread.error.connect(self._on_summary_error)
        self._summary_thread.start()

    def _on_summary_complete(self, summary: str):
        """Handle successful summary generation (called on main thread)."""
        if self.summary_text:
            self.summary_text.setText(summary)
        if hasattr(self, "generate_button"):
            self.generate_button.setEnabled(True)

    def _on_summary_error(self, error_msg: str):
        """Handle summary generation error (called on main thread)."""
        if self.summary_text:
            self.summary_text.setText(f"Error: {error_msg}")
        if hasattr(self, "generate_button"):
            self.generate_button.setEnabled(True)

    def show(self):
        # Use WindowStaysOnTopHint temporarily to force window to front on Windows
        from PySide6.QtCore import Qt as QtCore

        original_flags = self.window.windowFlags()
        self.window.setWindowFlags(original_flags | QtCore.WindowStaysOnTopHint)
        self.window.show()
        # Remove the always-on-top flag but keep window in front
        self.window.setWindowFlags(original_flags)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def close(self):
        self.timer.stop()
        self.cap.release()
        logger.success("MainWindow closed and resources released")
