from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from pynput import mouse, keyboard
import cv2

from multiprocessing import Process, Event, freeze_support
from threading import Thread
import traceback
import playsound
import signal
import time
import sys
import os

from utils import vlc, parsing, camera


class SoundPlayer(Thread):
    def __init__(self, event: Event, player: vlc.MediaPlayer):
        super().__init__()
        self.event = event
        self.player = player

    def log(self, string: str):
        self.output.write("%f,%s\n" % (time.time(), string))

    def run(self) -> None:
        self.output = open("./output/probe.txt",'w')
        self.event.wait()

        time_before = 40000  # ms
        while self.player.get_time() >= 0:
            time_now = self.player.get_time()
            if time_now - time_before >= 40000:
                playsound.playsound("./resources/Ding-sound-effect.mp3", True)
                self.log(str(time_now))
                time_before = time_now
            time.sleep(0.1)


class VideoRecorder(Process):
    def __init__(self, event: Event, cam: int):
        super().__init__()
        self.event = event
        self.camera = cam
        self.video_timeline = None
        self.video_cap = None
        self.video_out = None

    def signal_handler(self, sig, frame):
        if sig == signal.SIGINT:
            traceback.print_stack(frame)
            print("SIGINT FROM CHILD!", flush=True)

        self.output.close()
        if self.video_cap is not None:
            self.video_out.release()
            self.video_cap.release()

        self.event.set()
        exit(0)

    def run(self) -> None:
        self.output = open("./output/video_timeline.txt", 'w')

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.video_cap = cv2.VideoCapture(self.camera)
        size = (int(self.video_cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

        fourcc = cv2.VideoWriter_fourcc(*'mpeg')
        self.video_out = cv2.VideoWriter("output/recording.mp4", fourcc, 20.0, size)

        if not self.video_cap.isOpened():
            print("Video Not Opened")

        self.event.wait()

        while self.event.is_set():
            ret, frame = self.video_cap.read()
            curr_time = time.time()
            if ret and frame is not None:
                self.video_out.write(frame)
                self.output.write("%f\n" % curr_time)

        self.video_out.release()
        self.video_cap.release()
        cv2.destroyAllWindows()
        self.output.close()
        self.event.set()


class ActivityRecorder(Process):
    def __init__(self, event: Event):
        super().__init__()
        self.event: Event = event

    def signal_handler(self, sig, frame):
        if sig == signal.SIGINT:
            traceback.print_stack(frame)
            print("SIGINT FROM CHILD!", flush=True)

        self.output.close()
        exit(0)

    def log(self, string: str):
        self.output.write("%f,%s\n" % (time.time(), string))

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

    def run(self) -> None:
        self.output = open("output/activity_log.txt", 'w')

        self.mouse_listener = mouse.Listener(
            on_move=self.onMouseMove,
            on_click=self.onMouseClick,
            on_scroll=self.onMouseScroll
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self.onKeyPress,
            on_release=self.onKeyRelease
        )

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.event.wait()

        self.mouse_listener.start()
        self.keyboard_listener.start()

        self.event.clear()
        self.event.wait()


class ExpApp(QMainWindow):
    def __init__(self, *args, **kwargs):
        QMainWindow.__init__(self, *args, **kwargs)

        self.output = open("output/main_log.txt", 'w')
        self.camera = camera.select_camera()

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        if self.camera is not None:
            self.videoRecordEvent = Event()
            self.videoRecorder = VideoRecorder(self.videoRecordEvent, self.camera)
            self.videoRecorder.daemon = True
            self.videoRecorder.start()

            self.activityRecordEvent = Event()
            self.activityRecorder = ActivityRecorder(self.activityRecordEvent)
            self.activityRecorder.daemon = True
            self.activityRecorder.start()
        else:
            self.log("Camera not found.")

        self.initVLC()
        self.initUI()

    def initVLC(self):
        """
        https://github.com/devos50/vlc-pyqt5-example
        :return:
        """
        self.instance = vlc.Instance()
        self.mediaplayer = self.instance.media_player_new()

        self.soundPlayerEvent = Event()
        self.soundPlayer = SoundPlayer(self.soundPlayerEvent, self.mediaplayer)
        self.soundPlayer.daemon = True
        self.soundPlayer.start()

    def initUI(self):
        self.widget = QStackedWidget(self)
        self.calib_widget = QWidget(self)
        self.vlc_widget = QWidget(self)
        self.widget.addWidget(self.calib_widget)
        self.widget.addWidget(self.vlc_widget)
        self.setCentralWidget(self.widget)

        self.setWindowTitle('Online Experiment Application')
        self.setWindowIcon(QIcon('resources/nmsl_logo_yellow.png'))

        calib_layout = QVBoxLayout(self)
        calib_layout.setContentsMargins(0, 0, 0, 0)
        calib_layout.setSpacing(0)

        self.detail_text = QLabel(
            'Thank you for your participation in this project.\n\n'
            'You will first proceed a process of "Looking at a circle" -> "Clicking the circle".\n\n'
            'After the process, you will watch the lecture.\n'
            'During the lecture, you will hear the "Beep" sound periodically.\n'
            'When you hear the sound, you will press button to respond your attentional state (TBD).',
            self
        )
        self.detail_text.setFont(QFont("Times New Roman", 15))
        self.detail_text.setStyleSheet("background-color: #FFFFFF")
        self.detail_text.setContentsMargins(10, 10, 10, 10)
        calib_layout.addWidget(self.detail_text, 0, alignment=Qt.AlignCenter)

        # Start button: start the experiment
        if self.camera is not None:
            self.start_button = QPushButton('Start\n(Please wait after click)', self)
        else:
            self.start_button = QPushButton("You don't have any camera available", self)
            self.start_button.setDisabled(True)
        self.start_button.setFixedSize(250, 125)
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

        # Set focused and make on-focus checker
        qApp.focusChanged.connect(self.onFocusChanged)

        # Calibration parameters
        self.calib_r = 50
        self.pos = 0
        self.calib_position_center = [()]

        # Calibration button
        self.ellipse_button = QPushButton('', self)
        self.ellipse_button.move(0, 0)
        self.ellipse_button.setStyleSheet("background-color: transparent")
        self.ellipse_button.hide()
        self.ellipse_button.clicked.connect(self.calibrate)

    def signal_handler(self, sig, frame):
        self.close()

    def log(self, string: str):
        self.output.write("%f,%s\n" % (time.time(), string))

    def setVolume(self, volume):
        self.mediaplayer.audio_set_volume(volume)

    @pyqtSlot("QWidget*", "QWidget*")
    def onFocusChanged(self, old, now):
        if now is None:
            self.log("Focus,False")
        else:
            self.log("Focus,True")

    def startExperiment(self):
        url = parsing.get_best_url("https://www.youtube.com/watch?v=njKP3FqW3Sk")
        self.widget.setCurrentWidget(self.vlc_widget)

        self.media = self.instance.media_new(url)
        self.mediaplayer.set_media(self.media)
        if sys.platform.startswith('linux'):  # for Linux using the X Server
            self.mediaplayer.set_xwindow(self.videoframe.winId())
        elif sys.platform == "win32":  # for Windows
            self.mediaplayer.set_hwnd(self.videoframe.winId())
        elif sys.platform == "darwin":  # for MacOS
            self.mediaplayer.set_nsobject(int(self.videoframe.winId()))

        self.activityRecordEvent.set()  # Start recording keyboard & mouse

        self.soundPlayerEvent.set()  # Start sound player
        if self.mediaplayer.play() < 0:  # Failed to play the media
            self.close()

    def calibrate(self):
        self.log("Calibrate,%d" % self.pos)
        if self.pos >= len(self.calib_position_center):
            self.ellipse_button.hide()
            self.startExperiment()
        else:
            if self.pos == 0:
                full_screen = qApp.desktop().screenGeometry()
                self.log('Resolution,%d,%d' % (full_screen.width(), full_screen.height()))
                self.log('InnerArea,%d,%d' % (self.rect().width(), self.rect().height()))
                self.calib_r = int(min(full_screen.width(), full_screen.height()) / 100)
                self.margin = self.calib_r + 10
                self.log('Calibration_Radius,%d' % self.calib_r)

                self.videoRecordEvent.set()
                time.sleep(3.0)
                self.start_button.hide()
                self.detail_text.hide()
                self.ellipse_button.setFixedSize(self.calib_r*2, self.calib_r*2)
                self.ellipse_button.show()
                self.calib_position_center = [
                    (self.margin, self.margin), (self.rect().width() - self.margin, self.margin),
                    (self.rect().width() - self.margin, self.rect().height() - self.margin), (self.margin, self.rect().height() - self.margin),
                    (self.rect().width()/2, self.rect().height()/2),
                    (self.rect().width()/2, self.margin), (self.rect().width() - self.margin, self.rect().height()/2),
                    (self.rect().width()/2, self.rect().height() - self.margin), (self.margin, self.rect().height()/2)
                ]
            self.ellipse_button.move(self.calib_position_center[self.pos][0] - self.calib_r,
                                     self.calib_position_center[self.pos][1] - self.calib_r)
        self.pos += 1
        self.update()

    def paintEvent(self, event):
        qp = QPainter(self)
        if 0 < self.pos <= len(self.calib_position_center):
            qp.setBrush(QColor(180, 0, 0))
            qp.setPen(QPen(QColor(180, self.calib_r, self.calib_r), 1))
            x, y = self.calib_position_center[self.pos-1]
            r = self.calib_r
            qp.drawEllipse(x-r, y-r, 2*r, 2*r)
        qp.end()

    def closeEvent(self, event):
        self.close()

    def close(self):
        try:
            self.output.close()
            self.mediaplayer.stop()
        finally:
            if self.camera is not None and self.pos >= len(self.calib_position_center):
                self.videoRecordEvent.clear()
                self.videoRecordEvent.wait(timeout=5.0)
                self.activityRecordEvent.set()
            self.videoRecorder.terminate()
            self.videoRecorder.join()
            self.activityRecorder.terminate()
            self.activityRecorder.join()
            exit(0)


if __name__ == '__main__':
    if not os.path.exists('output'):
        os.mkdir('output')

    # Pyinstaller fix
    freeze_support()

    # PyQT
    app = QApplication(sys.argv)
    ex = ExpApp()
    sys.exit(app.exec_())
