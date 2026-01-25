import sys
import os
import cv2

from PySide6.QtWidgets import QApplication, QLabel, QComboBox
from PySide6.QtCore import QTimer, Qt, QFile
from PySide6.QtGui import QImage, QPixmap, QColor
from PySide6.QtUiTools import QUiLoader


class MainWindow:
    def __init__(self):
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
        self.cameraLabel = self.window.findChild(QLabel, "cameraLabel")
        if self.cameraLabel is None:
            raise RuntimeError(
                "cameraLabel not found. Make sure QLabel objectName is 'cameraLabel'"
            )

        # --- Set initial window size ---

        # --- Open webcam ---
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
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
        if sec_level_combo:
            # Set text colors: light=green, medium=yellow, heavy=red
            sec_level_combo.setItemData(0, QColor("green"), Qt.ForegroundRole)
            sec_level_combo.setItemData(1, QColor("orange"), Qt.ForegroundRole)
            sec_level_combo.setItemData(2, QColor("red"), Qt.ForegroundRole)
        
        # Threat level label
        self.threat_level_label = self.window.findChild(QLabel, "threat_level_label")
        if self.threat_level_label:
            self.update_threat_level(self.threat_estimate)

    def update_threat_level(self, threat_estimate):
        """Update the threat level label text and color"""
        self.threat_estimate = threat_estimate
        if self.threat_level_label:
            self.threat_level_label.setText(threat_estimate)
            if threat_estimate == "FRAME CLEAR":
                self.threat_level_label.setStyleSheet("color: gray;")
            elif threat_estimate == "SAFE":
                self.threat_level_label.setStyleSheet("color: green;")
            elif threat_estimate == "CAUTION":
                self.threat_level_label.setStyleSheet("color: yellow;")
            elif threat_estimate == "WARNING":
                self.threat_level_label.setStyleSheet("color: orange;")
            elif threat_estimate == "DANGER":
                self.threat_level_label.setStyleSheet("color: red;")

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w

        qt_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image)

        # Scale to fit QLabel
        self.cameraLabel.setPixmap(
            pixmap.scaled(
                self.cameraLabel.width(),
                self.cameraLabel.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        )

    def show(self):
        self.window.show()

    def close(self):
        self.timer.stop()
        self.cap.release()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())
