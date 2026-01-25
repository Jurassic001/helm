import sys
import os
import cv2

from PySide6.QtWidgets import QApplication, QWidget, QLabel
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile

class CameraWidget(QWidget):
    def __init__(self):
        super().__init__()

        # --- Load UI ---
        ui_path = os.path.join(os.path.dirname(__file__), "test.ui")
        if not os.path.exists(ui_path):
            raise RuntimeError(f"UI file not found at: {ui_path}")

        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"Cannot open UI file: {ui_path}")

        loader = QUiLoader()
        self.ui = loader.load(ui_file, self)
        ui_file.close()

        if self.ui is None:
            raise RuntimeError("Failed to load UI")

        # The loaded UI is a child widget; we make it our layout
        self.ui.setParent(self)

        # --- Access QLabel for camera feed ---
        self.cameraLabel = self.ui.findChild(QLabel, "cameraLabel")
        if self.cameraLabel is None:
            raise RuntimeError(
                "cameraLabel not found. Make sure QLabel objectName is 'cameraLabel'"
            )

        # --- Set initial window size ---
        self.resize(800, 600)

        # --- Open webcam ---
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError("Could not open webcam")

        # --- Timer to update frames ---
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)  # ~30 FPS

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

    def closeEvent(self, event):
        self.timer.stop()
        self.cap.release()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CameraWidget()
    window.show()
    sys.exit(app.exec())
