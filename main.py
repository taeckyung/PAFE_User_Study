from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from urlvalidator import URLValidator, ValidationError
from pynput import mouse, keyboard
import numpy as np
import pafy
import vlc
import cv2

from multiprocessing import Process, Event
import traceback
import signal
import time
import sys


class VideoRecorder(Process):
    def __init__(self, event: Event):
        super().__init__()
        self.event = event
        self.video_timeline = None
        self.video_cap = None
        self.video_out = None

    def signal_handler(self, sig, frame):
        if sig == signal.SIGINT:
            traceback.print_stack(frame)
            print("SIGINT FROM CHILD!", flush=True)

        if self.video_timeline is not None:
            np.save("video_timeline.npy", np.array(self.video_timeline))
        if self.video_cap is not None:
            self.video_out.release()
            self.video_cap.release()

        exit(0)

    def run(self):
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.video_timeline = np.array([])
        self.video_cap = cv2.VideoCapture(0)
        size = (int(self.video_cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

        fourcc = cv2.VideoWriter_fourcc(*'mpeg')
        self.video_out = cv2.VideoWriter("output.mp4", fourcc, 20.0, size)
        self.event.wait()

        while self.event.is_set():
            ret, frame = self.video_cap.read()
            curr_time = time.time()
            if ret and frame is not None:
                self.video_out.write(frame)
                self.video_timeline = np.append(self.video_timeline, curr_time)

        np.save("video_timeline.npy", np.array(self.video_timeline))
        self.video_out.release()
        self.video_cap.release()
        cv2.destroyAllWindows()
        self.event.set()


def get_best_url(path: str) -> str:
    validate = URLValidator()
    try:
        validate(path)
        video = pafy.new(path)
        best = video.getbest()
        return best.url

    except ValidationError:
        return path


class ExpApp(QMainWindow):
    def __init__(self, recorder: Process, record_event: Event, *args, **kwargs):
        QMainWindow.__init__(self, *args, **kwargs)
        self.recorder = recorder
        self.record_event = record_event
        self.output = open("log.txt", 'w')
        self.initVLC()
        self.initUI()

    def initVLC(self):
        """
        https://github.com/devos50/vlc-pyqt5-example
        :return:
        """
        self.instance = vlc.Instance()
        self.mediaplayer = self.instance.media_player_new()

    def initUI(self):
        self.widget = QStackedWidget(self)
        self.calib_widget = QWidget(self)
        self.vlc_widget = QWidget(self)
        self.widget.addWidget(self.calib_widget)
        self.widget.addWidget(self.vlc_widget)
        self.setCentralWidget(self.widget)

        self.setWindowTitle('Online Experiment Application')
        self.setWindowIcon(QIcon('resources/nmsl_logo_yellow.png'))

        calib_layout = QHBoxLayout(self)
        calib_layout.setContentsMargins(10, 10, 10, 10)
        calib_layout.setSpacing(10)

        # Start button: start the experiment
        self.start_button = QPushButton('Start\n(Please wait after click)', self)
        self.start_button.setFixedSize(500, 250)
        self.start_button.clicked.connect(self.calibrate)

        calib_layout.addWidget(self.start_button, 0, alignment=Qt.AlignCenter)

        self.calib_widget.setLayout(calib_layout)

        vlc_layout = QVBoxLayout(self)
        vlc_layout.setContentsMargins(0, 0, 0, 0)
        vlc_layout.setSpacing(0)
        # VLC player
        # In this widget, the video will be drawn
        if sys.platform == "darwin": # for MacOS
            from PyQt5.QtWidgets import QMacCocoaViewContainer
            self.videoframe = QMacCocoaViewContainer(0)
        else:
            self.videoframe = QFrame()
        self.palette = self.videoframe.palette()
        self.palette.setColor (QPalette.Window,
                               QColor(255, 255, 255))
        self.videoframe.setPalette(self.palette)
        self.videoframe.setAutoFillBackground(True)
        vlc_layout.addWidget(self.videoframe)

        self.volumeslider = QSlider(Qt.Horizontal, self)
        self.volumeslider.setMaximum(100)
        self.volumeslider.setFixedWidth(300)
        self.volumeslider.setValue(self.mediaplayer.audio_get_volume())
        self.volumeslider.setToolTip("Volume")
        self.volumeslider.valueChanged.connect(self.setVolume)
        vlc_layout.addWidget(self.volumeslider, alignment=Qt.AlignRight)

        self.vlc_widget.setLayout(vlc_layout)

        # Maximize the screen
        self.showMaximized()

        # Calibration parameters
        self.calib_r = 50
        self.pos = 0
        self.calib_position_center = [()]

        # Calibration button
        self.ellipse_button = QPushButton('', self)
        self.ellipse_button.setFixedSize(self.calib_r*2, self.calib_r*2)
        self.ellipse_button.move(0, 0)
        self.ellipse_button.setStyleSheet("background-color: transparent")
        self.ellipse_button.hide()
        self.ellipse_button.clicked.connect(self.calibrate)

    def setVolume(self, volume):
        self.mediaplayer.audio_set_volume(volume)

    def log(self, string: str):
        self.output.write("%d,%s\n" % (time.time(), string))

    def onMouseMove(self, x, y):
        self.log("Mouse,Move,%d,%d" % (x, y))

    def onMouseClick(self, x, y, button, pressed):
        self.log("Mouse,Click,%s,%d,%d,%d" % (button, pressed, x, y))

    def onMouseScroll(self, x, y, dx, dy):
        self.log("Mouse,Scroll,%d,%d,%d,%d" % (x, y, dx, dy))

    def onKeyPress(self, key):
        self.log("Key,Press,%s" % key)

    def onKeyRelease(self, key):
        self.log("Key,Release,%s" % key)

    def startExperiment(self):
        url = get_best_url("https://www.youtube.com/watch?v=njKP3FqW3Sk")
        self.widget.setCurrentWidget(self.vlc_widget)

        self.media = self.instance.media_new(url)
        self.mediaplayer.set_media(self.media)
        if sys.platform.startswith('linux'):  # for Linux using the X Server
            self.mediaplayer.set_xwindow(self.videoframe.winId())
        elif sys.platform == "win32":  # for Windows
            self.mediaplayer.set_hwnd(self.videoframe.winId())
        elif sys.platform == "darwin":  # for MacOS
            self.mediaplayer.set_nsobject(int(self.videoframe.winId()))

        self.mouse_listener = mouse.Listener(
            on_move=self.onMouseMove,
            on_click=self.onMouseClick,
            on_scroll=self.onMouseScroll
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self.onKeyPress,
            on_release=self.onKeyRelease
        )

        self.mouse_listener.start()
        self.keyboard_listener.start()

        if self.mediaplayer.play() < 0:  # Failed to play the media
            self.close()

    def calibrate(self):
        self.log("Calibrate,%d" % self.pos)
        if self.pos >= len(self.calib_position_center):
            self.ellipse_button.hide()
            self.startExperiment()
        else:
            if self.pos == 0:
                self.record_event.set()
                time.sleep(3.0)
                self.start_button.hide()
                self.ellipse_button.show()
                self.calib_position_center = [
                    (60, 60), (self.rect().width() - 60, 60),
                    (self.rect().width() - 60, self.rect().height() - 60), (60, self.rect().height() - 60),
                    (self.rect().width()/2, self.rect().height()/2),
                    (self.rect().width()/2, 60), (self.rect().width() - 60, self.rect().height()/2),
                    (self.rect().width()/2, self.rect().height() - 60), (60, self.rect().height()/2)
                ]
            self.ellipse_button.move(self.calib_position_center[self.pos][0] - self.calib_r,
                                     self.calib_position_center[self.pos][1] - self.calib_r)
        self.pos += 1
        self.update()

    def paintEvent(self, event):
        qp = QPainter(self)
        if 0 < self.pos <= len(self.calib_position_center):
            if self.pos <= 5:
                qp.setBrush(QColor(180, 0, 0))
                qp.setPen(QPen(QColor(180, 60, 60), 1))
            else:
                qp.setBrush(QColor(0, 0, 180))
                qp.setPen(QPen(QColor(60, 180, 60), 1))
            x, y = self.calib_position_center[self.pos-1]
            r = self.calib_r
            qp.drawEllipse(x-r, y-r, 2*r, 2*r)
        qp.end()

    def closeEvent(self, event):
        self.close()

    def close(self):
        try:
            self.mediaplayer.stop()
            self.output.close()
            self.mouse_listener.stop()
            self.keyboard_listener.stop()
        finally:
            self.record_event.clear()
            self.record_event.wait()
            self.recorder.join()
            return


if __name__ == '__main__':
    record_event = Event()
    recorder = VideoRecorder(record_event)
    recorder.daemon = True
    recorder.start()
    app = QApplication(sys.argv)
    ex = ExpApp(recorder=recorder, record_event=record_event)
    sys.exit(app.exec_())
