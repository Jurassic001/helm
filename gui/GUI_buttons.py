import sys
from PySide6.QtWidgets import QApplication, QPushButton, QLineEdit, QComboBox, QTextEdit, QTabWidget, QLabel
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt
from PySide6.QtGui import QColor

def main():
    # Variable to track threat estimate
    threat_estimate = "FRAME CLEAR"  # Possible values: "FRAME CLEAR", "SAFE", "CAUTION", "WARNING", "DANGER"
    app = QApplication(sys.argv)
    
    # Load the UI file
    loader = QUiLoader()
    file = QFile("gui/designer2.ui")  # Assuming UI file is in gui/ folder
    window = loader.load(file)
    file.close()
    
    if window:
        # Access UI elements (assuming object names from Qt Designer)
        sec_level_combo = window.findChild(QComboBox, "sec_level_combo")
        if sec_level_combo:
            # Set text colors: light=green, medium=yellow, heavy=red
            sec_level_combo.setItemData(0, QColor("green"), Qt.ForegroundRole)
            sec_level_combo.setItemData(1, QColor("yellow"), Qt.ForegroundRole)
            sec_level_combo.setItemData(2, QColor("red"), Qt.ForegroundRole)
        
        
        # Threat level label
        threat_level_label = window.findChild(QLabel, "threat_level_label")
        if threat_level_label:
            threat_level_label.setText(threat_estimate)
            if threat_estimate == "FRAME CLEAR":
                threat_level_label.setStyleSheet("color: gray;")
            elif threat_estimate == "SAFE":
                threat_level_label.setStyleSheet("color: green;")
            elif threat_estimate == "CAUTION":
                threat_level_label.setStyleSheet("color: yellow;")
            elif threat_estimate == "WARNING":
                threat_level_label.setStyleSheet("color: orange;")
            elif threat_estimate == "DANGER":
                threat_level_label.setStyleSheet("color: red;")
        
        window.show()
        sys.exit(app.exec())
    else:
        print("Failed to load UI file")

if __name__ == "__main__":
    main()
