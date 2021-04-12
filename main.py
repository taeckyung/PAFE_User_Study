from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from pynput import mouse, keyboard
import cv2

from multiprocessing import Process, Event, freeze_support, SimpleQueue
from threading import Thread
import traceback
import playsound
import shutil
import random
import signal
import time
import sys
import os

from typing import List, Tuple

from utils import vlc, parsing, camera


def getTime(time_now, total):
    return time_now//60, time_now % 60, total//60, total % 60


class UIUpdater(Thread):
    def __init__(self, player: vlc.MediaPlayer, time_label: QLabel, time_text: str, next_button: QPushButton):
        super().__init__()
        self.event = Event()
        self.player = player
        self.time_text = time_text
        self.time_label = time_label
        self.next_button = next_button

    def execute(self):
        self.event.set()

    def finish(self, timeout=None):
        self.event.clear()
        self.event.wait(timeout=timeout)

    def run(self) -> None:
        self.event.wait()
        while self.player.get_state() != vlc.State(3):
            time.sleep(0.1)
        total_length = self.player.get_length() // 1000

        while self.player.get_state() != vlc.State(6) and self.event.is_set():
            time_now = self.player.get_time()
            self.time_label.setText(self.time_text % getTime(int(time_now / 1000), total_length))
            time.sleep(0.9)

        self.next_button.setEnabled(True)
        self.time_label.setText(self.time_text % (0, 0, 0, 0))

        self.event.set()


class ProbeRunner(Thread):
    def __init__(self, queue: SimpleQueue, player: vlc.MediaPlayer, video: str):
        super().__init__()
        self.event = Event()
        self.queue = queue
        self.player = player
        self.video = video

    def execute(self):
        self.event.set()

    def finish(self, timeout=None):
        self.event.clear()
        self.event.wait(timeout=timeout)

    def run(self) -> None:
        output = open("./output/probe_%s.txt" % self.video, 'w')
        self.event.wait()
        while self.player.get_state() != vlc.State(3):
            time.sleep(0.1)

        padding = 5000  # ms
        interval = 5000  # ms

        clock_before = 0
        idx_before = 0

        output_str = ""

        while self.player.get_state() != vlc.State(6) and self.event.is_set():
            time_now = self.player.get_time()
            clock_now = time.time()

            if (time_now - padding) // interval > idx_before:
                playsound.playsound("./resources/Ding-sound-effect.mp3", True)
                output_str += "%f,%f,sound\n" % (time_now, clock_now)
                idx_before += 1
                clock_before = clock_now

            last_probe = None
            while not self.queue.empty():
                e: Tuple[float, str] = self.queue.get()
                if -0. <= e[0] - clock_before < 10000.:  # Response in 10s
                    last_probe = e
            if last_probe is not None:
                output_str += "%f,%f,probe,%s\n" % (time_now, last_probe[0], last_probe[1])

        output.write(output_str)
        output.close()
        self.event.set()


class VideoRecorder(Process):
    def __init__(self, cam: int):
        super().__init__()
        self.event = Event()
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

    def execute(self):
        self.event.set()

    def finish(self, timeout=None):
        self.event.clear()
        self.event.wait(timeout=timeout)

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

        self.output.write("%f,end" % time.time())
        self.video_out.release()
        self.video_cap.release()
        cv2.destroyAllWindows()
        self.output.close()
        self.event.set()


class ActivityRecorder(Process):
    def __init__(self, queue: SimpleQueue, name: str):
        super().__init__()
        self.event = Event()
        self.finishEvent = Event()
        self.queue = queue
        self.name = name

    def signal_handler(self, sig, frame):
        self.keyboard_listener.stop()
        self.mouse_listener.stop()
        self.output.close()

        if sig == signal.SIGINT:
            traceback.print_stack(frame)
            print("SIGINT FROM CHILD!", flush=True)

        exit(0)

    def execute(self):
        self.event.set()

    def finish(self, timeout=None):
        self.event.set()
        self.finishEvent.wait(timeout=timeout)

    def log(self, string: str):
        self.output.write("%f,%s\n" % (time.time(), string))

    def onMouseMove(self, x, y):
        self.log("mouse,move,%d,%d" % (x, y))

    def onMouseClick(self, x, y, button, pressed):
        self.log("mouse,click,%s,%d,%d,%d" % (button, pressed, x, y))

    def onMouseScroll(self, x, y, dx, dy):
        self.log("mouse,scroll,%d,%d,%d,%d" % (x, y, dx, dy))

    def onKeyPress(self, key):
        self.log("key,press,%s" % key)

    def onKeyRelease(self, key):
        self.log("key,release,%s" % key)
        curr_time = time.time()
        if isinstance(key, keyboard.KeyCode):
            if key == keyboard.KeyCode.from_char('y'):
                self.queue.put((curr_time, 'y'))
            elif key == keyboard.KeyCode.from_char('n'):
                self.queue.put((curr_time, 'n'))

    def run(self) -> None:
        self.output = open("output/activity_log_%s.txt" % self.name, 'w')

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

        self.keyboard_listener.stop()
        self.mouse_listener.stop()
        self.output.close()

        self.finishEvent.set()


class ExpApp(QMainWindow):
    def __init__(self, *args, **kwargs):
        QMainWindow.__init__(self, *args, **kwargs)

        # Debugging options
        self.do_calibrate = False

        self.videos = [
            ("Intro-to-Organizations",      "https://youtu.be/J3p6wGzLi00"),  # 9m; pre-video
            ("Writing-in-the-Sciences",     "https://youtu.be/J3p6wGzLi00"),  # 11m
            ("Intro-to-Economic-Theories",  "https://youtu.be/8yM_vw9xKnQ"),  # 12m
            ("Intro-to-AI",                 "https://youtu.be/bBaZ05WsTUM"),  # 11m
            ("Game-Theory",                 "https://youtu.be/o5vvcohd1Qg"),  # 10m
            ("What-is-Cryptography",        "https://youtu.be/XnueMv0EUHQ")   # 15m
        ]
        self.videoIndex = 0

        self.output = open("output/main_log.txt", 'w')
        self.camera = camera.select_camera("output/test.png")

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # initVLC
        if True:
            """
            https://github.com/devos50/vlc-pyqt5-example
            :return:
            """
            self.instance = vlc.Instance()
            self.media_player = self.instance.media_player_new()

        # initChild
        if True:
            self.probeQueue = SimpleQueue()

            self.probeRunner = None
            self.updater = None

            if self.camera is not None:
                self.videoRecorder = VideoRecorder(self.camera)
                self.videoRecorder.daemon = True
                self.videoRecorder.start()
            else:
                self.log("cameraNotFound")

            self.activityRecorder = ActivityRecorder(self.probeQueue, "Main")
            self.activityRecorder.daemon = True
            self.activityRecorder.start()
            self.activityRecorder.execute()  # Start recording keyboard & mouse

        # initUI
        if True:
            self.setWindowTitle('Online Experiment Application')
            self.setWindowIcon(QIcon('resources/nmsl_logo_yellow.png'))

            self.widget = QStackedWidget(self)
            self.calib_widget = QWidget(self)
            self.vlc_widget = QWidget(self)
            self.widget.addWidget(self.calib_widget)
            self.widget.addWidget(self.vlc_widget)
            self.setCentralWidget(self.widget)

            # setCalibWidget
            if True:
                calib_layout = QVBoxLayout(self)

                self.detail_text = QLabel(
                    'Thank you for your participation in this project.\n\n'
                    'You will first proceed a iteration of "Looking at a circle" -> "Clicking the circle".\n'
                    'Please avoid moving head during the iteration.\n\n'
                    'After the process, you will watch the lecture.\n'
                    'During the lecture, you will hear the "Beep" sound periodically.\n'
                    'When you hear the sound, press [Y] if you were on-focus;'
                    'press [N] if you were off-focus or doing something else.\n\n'
                    '!!PLEASE AVOID TOUCHING EYEGLASSES OR MOVING LAPTOP!!',
                    self
                )
                self.detail_text.setFont(QFont("Times New Roman", 15))
                self.detail_text.setStyleSheet("background-color: #FFFFFF")
                self.detail_text.setContentsMargins(10, 10, 10, 10)
                calib_layout.addWidget(self.detail_text, 0, alignment=Qt.AlignHCenter)

                self.type_student_id_text = QLabel('Type your EXPERIMENT_ID below.')
                self.type_student_id_text.setFont(QFont("Times New Roman", 15))
                self.type_student_id_text.setContentsMargins(10, 10, 10, 10)
                self.type_student_id_text.setFixedHeight(75)
                calib_layout.addWidget(self.type_student_id_text, 0, alignment=Qt.AlignHCenter)

                self.user_id = QLineEdit(self)
                self.user_id.setFixedSize(250, 75)
                self.user_id.setAlignment(Qt.AlignCenter)
                self.user_id.setValidator(QIntValidator())
                calib_layout.addWidget(self.user_id, 0, alignment=Qt.AlignHCenter)

                # Start button: start the experiment
                if self.camera is not None:
                    self.start_button = QPushButton('Start\n(Please wait after click)', self)
                else:
                    self.start_button = QPushButton("You don't have any camera available", self)
                    self.start_button.setDisabled(True)
                self.start_button.setFixedSize(250, 125)
                self.start_button.clicked.connect(self.calibrate)

                calib_layout.addWidget(self.start_button, 0, alignment=Qt.AlignHCenter)
                calib_layout.setSpacing(10)

                self.calib_widget.setLayout(calib_layout)

            # setVLCWidget
            if True:
                vlc_layout = QVBoxLayout(self)
                # VLC player
                # In this widget, the video will be drawn
                if sys.platform == "darwin":  # for MacOS
                    from PyQt5.QtWidgets import QMacCocoaViewContainer
                    self.video_frame = QMacCocoaViewContainer(0)
                else:
                    self.video_frame = QFrame()
                palette = self.video_frame.palette()
                palette.setColor(QPalette.Window, QColor(255, 255, 255))
                self.video_frame.setPalette(palette)
                self.video_frame.setAutoFillBackground(True)
                vlc_layout.addWidget(self.video_frame)

                # Lower Layout ###################################################################
                vlc_lower_layout = QHBoxLayout(self)

                vlc_lower_layout.addStretch(1)

                self.next_button = QPushButton('Start Video', self)
                self.next_button.setFixedSize(100, 30)
                self.next_button.clicked.connect(self.startVideo)
                vlc_lower_layout.addWidget(self.next_button, alignment=Qt.AlignHCenter)

                self.video_index_text = ' [Video: %01d/%01d] '
                self.video_index_label = QLabel(self.video_index_text % (self.videoIndex, len(self.videos)))
                self.video_index_label.setFixedSize(80, 30)
                vlc_lower_layout.addWidget(self.video_index_label, alignment=Qt.AlignHCenter)

                self.time_text = ' [Time: %02d:%02d/%02d:%02d] '
                self.time_label = QLabel(self.time_text % (0, 0, 0, 0))
                self.time_label.setFixedSize(160, 30)
                vlc_lower_layout.addWidget(self.time_label, alignment=Qt.AlignHCenter)

                vlc_lower_layout.addStretch(1)

                self.probe_text = 'ON-FOCUS: PRESS [Y] / OFF-FOCUS: PRESS [N]'
                self.probe_label = QLabel(self.probe_text)
                font: QFont = self.probe_label.font()
                font.setBold(True)
                self.probe_label.setFont(font)
                self.probe_label.setFixedSize(500, 30)
                vlc_lower_layout.addWidget(self.probe_label, alignment=Qt.AlignHCenter)

                vlc_lower_layout.addStretch(1)

                # Volume Layout ####################################################
                vlc_volume_layout = QHBoxLayout(self)
                vlc_volume_layout.setSpacing(1)

                vlc_volume_layout.addStretch(1)

                volume_label = QLabel('Volume:')
                volume_label.setFixedSize(50, 30)
                vlc_volume_layout.addWidget(volume_label, alignment=Qt.AlignHCenter | Qt.AlignRight)

                volume_slider = QSlider(Qt.Horizontal, self)
                volume_slider.setMaximum(100)
                volume_slider.setFixedWidth(300)
                volume_slider.setFixedHeight(25)
                volume_slider.setValue(self.media_player.audio_get_volume())
                volume_slider.setToolTip("Volume")
                volume_slider.valueChanged.connect(self.setVolume)

                vlc_volume_layout.addWidget(volume_slider, alignment=Qt.AlignHCenter)
                vlc_volume_layout.addStretch(1)

                vlc_lower_layout.addLayout(vlc_volume_layout)
                #####################################################################

                vlc_lower_layout.addStretch(1)
                vlc_layout.addLayout(vlc_lower_layout)
                #################################################################################

                vlc_layout.setSpacing(0)
                vlc_layout.setContentsMargins(0, 0, 0, 0)
                self.vlc_widget.setLayout(vlc_layout)

                # Dialog
                self.dialog = QDialog()
                dialog_layout = QVBoxLayout(self.dialog)
                label = QLabel("Did you hear the beep sound?\n"
                               "After hearing the sound, you should response your attentional state!\n\n"
                               + self.probe_text + "\n\n"
                               "You can check this at the bottom center.")
                label.setAlignment(Qt.AlignCenter)
                button = QPushButton("OK")
                button.clicked.connect(self.closeDialog)

                dialog_layout.addStretch(1)
                dialog_layout.addWidget(label, alignment=Qt.AlignVCenter)
                dialog_layout.addStretch(1)
                dialog_layout.addWidget(button, alignment=Qt.AlignVCenter)
                dialog_layout.addStretch(1)
                self.dialog.setLayout(dialog_layout)

            # Maximize the screen
            self.showMaximized()

            # Set focused and make on-focus checker
            qApp.focusChanged.connect(self.onFocusChanged)

            # Calibration parameters
            self.calib_r = 50
            self.pos = 0
            self.calib_position_center: List[Tuple[int, int]] = [(0, 0)]

            # Calibration button
            self.ellipse_button = QPushButton('', self)
            self.ellipse_button.move(0, 0)
            self.ellipse_button.setStyleSheet("background-color: transparent")
            self.ellipse_button.hide()
            self.ellipse_button.clicked.connect(self.calibrate)

    def signal_handler(self, sig, frame):
        self.close()

    def log(self, string: str):
        print(string)
        self.output.write("%f,%s\n" % (time.time(), string))

    def setVolume(self, volume):
        self.media_player.audio_set_volume(volume)

    @pyqtSlot("QWidget*", "QWidget*")
    def onFocusChanged(self, old, now):
        if now is None:
            self.log("focus,False")
        else:
            self.log("focus,True")

    def calibrate(self):
        self.log("calibrate,%d" % self.pos)
        if self.pos >= len(self.calib_position_center):
            self.ellipse_button.hide()
            self.widget.setCurrentWidget(self.vlc_widget)
        else:
            if self.pos == 0:
                if self.user_id.text() == "":
                    return

                screen = qApp.primaryScreen()
                dpi = screen.physicalDotsPerInch()
                full_screen = screen.size()
                x_mm = 2.54 * full_screen.height() / dpi  # in->cm
                y_mm = 2.54 * full_screen.width() / dpi  # in->cm
                self.calib_r = int(min(full_screen.width(), full_screen.height()) / 100)
                self.margin = self.calib_r*2

                # Leave logs
                self.log('user_id,%s' % (self.user_id.text()))
                self.log('monitor,%f,%f' % (x_mm, y_mm))
                self.log('resolution,%d,%d' % (full_screen.width(), full_screen.height()))
                self.log('inner_area,%d,%d' % (self.rect().width(), self.rect().height()))
                self.log('calibration_Radius,%d' % self.calib_r)

                # Sort URL w.r.t. Student ID
                random.seed(self.user_id.text())
                target = self.videos[1:]
                random.shuffle(target)
                self.videos[1:] = target
                print(self.videos)

                # Start recording
                self.videoRecorder.execute()
                time.sleep(1.5)

                self.type_student_id_text.hide()
                self.start_button.hide()
                self.detail_text.hide()
                self.user_id.hide()

                self.ellipse_button.setFixedSize(self.calib_r*2, self.calib_r*2)
                self.ellipse_button.show()
                self.calib_position_center = [
                    (self.margin,                       self.margin),
                    (self.rect().width()/2,             self.margin),
                    (self.rect().width() - self.margin, self.margin),

                    (self.margin,                       self.rect().height()/2),
                    (self.rect().width()/2,             self.rect().height()/2),
                    (self.rect().width() - self.margin, self.rect().height()/2),

                    (self.margin,                       self.rect().height() - self.margin),
                    (self.rect().width()/2,             self.rect().height() - self.margin),
                    (self.rect().width() - self.margin, self.rect().height() - self.margin),

                    (self.rect().width()/4,             self.rect().height()/4),
                    (self.rect().width()*3/4,           self.rect().height()/4),
                    (self.rect().width()/4,             self.rect().height()*3/4),
                    (self.rect().width()*3/4,           self.rect().height()*3/4),

                    (self.calib_r,                      self.calib_r),
                    (self.rect().width() - self.calib_r,self.calib_r),
                    (self.calib_r,                      self.rect().height() - self.calib_r),
                    (self.rect().width() - self.calib_r,self.rect().height() - self.calib_r),
                ]

            self.ellipse_button.move(self.calib_position_center[self.pos][0] - self.calib_r,
                                     self.calib_position_center[self.pos][1] - self.calib_r)

        self.pos += 1
        if not self.do_calibrate:
            self.ellipse_button.hide()
            self.widget.setCurrentWidget(self.vlc_widget)
        else:
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

    def closeDialog(self):
        self.dialog.close()

    def alertProbing(self):
        self.dialog.setWindowTitle('Alert')
        self.dialog.setWindowModality(Qt.ApplicationModal)
        self.dialog.show()

    def startVideo(self):
        self.next_button.setDisabled(True)

        if self.videoIndex > 0 and self.media_player.get_position() < 0.90:
            self.next_button.setEnabled(True)
            return

        if self.videoIndex == 0:  # First video
            self.alertProbing()
            pass
        else:
            self.probeRunner.finish(timeout=15.0)
            self.updater.finish(timeout=5.0)
            self.probeRunner.join()
            self.updater.join()
            if self.videoIndex >= len(self.videos):  # Finish
                self.close()

        self.activityRecorder.finish(timeout=5.0)  # Stop recording keyboard & mouse
        self.activityRecorder.join()

        self.activityRecorder = ActivityRecorder(self.probeQueue, self.videos[self.videoIndex][0])
        self.activityRecorder.daemon = True
        self.activityRecorder.start()

        self.probeRunner = ProbeRunner(self.probeQueue, self.media_player, self.videos[self.videoIndex][0])
        self.probeRunner.daemon = True
        self.probeRunner.start()

        self.updater = UIUpdater(self.media_player, self.time_label, self.time_text, self.next_button)
        self.updater.daemon = True
        self.updater.start()

        url = parsing.get_best_url(self.videos[self.videoIndex][1])
        self.log("url,%s" % url)

        self.activityRecorder.execute()  # Start recording keyboard & mouse
        self.probeRunner.execute()  # Start sound player
        self.updater.execute()  # Start UI updater
        try:
            media = self.instance.media_new(url)
            self.media_player.set_media(media)
            if sys.platform.startswith('linux'):  # for Linux using the X Server
                self.media_player.set_xwindow(self.video_frame.winId())
            elif sys.platform == "win32":  # for Windows
                self.media_player.set_hwnd(self.video_frame.winId())
            elif sys.platform == "darwin":  # for MacOS
                self.media_player.set_nsobject(int(self.video_frame.winId()))

            if self.media_player.play() < 0:  # Failed to play the media
                self.log("play,%s,Fail" % self.videos[self.videoIndex][0])
            else:
                self.log("play,%s,Start" % self.videos[self.videoIndex][0])
        except Exception as e:
            self.log("play,%s,Fail,%s" % (self.videos[self.videoIndex][0], str(e)))
        finally:
            self.videoIndex += 1
            self.video_index_label.setText(self.video_index_text % (self.videoIndex, len(self.videos)))

    def closeEvent(self, event):
        self.log("click,x")
        self.close()

    def close(self):
        try:
            self.media_player.stop()
        finally:
            if self.camera is not None:
                try:
                    self.videoRecorder.finish(timeout=30.0)
                    self.activityRecorder.finish(timeout=10.0)
                except Exception as e:
                    self.log(str(e))

            try:
                self.probeRunner.finish(timeout=10.0)
                self.probeRunner.join(timeout=1.0)
            except Exception as e:
                self.log(str(e))

            try:
                self.videoRecorder.join(timeout=10.0)
                self.videoRecorder.terminate()
            except Exception as e:
                self.log(str(e))

            try:
                self.activityRecorder.join(timeout=10.0)
                self.activityRecorder.terminate()
            except Exception as e:
                self.log(str(e))

            try:
                shutil.make_archive(os.path.join("./", "output_user_%s" % self.user_id.text()), 'zip', "./output/")
            except Exception as e:
                self.log(str(e))

            self.output.close()
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
