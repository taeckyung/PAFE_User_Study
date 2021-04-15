import functools

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from pynput import mouse, keyboard
import cv2

from multiprocessing import Process, Event, freeze_support, SimpleQueue
from threading import Thread
from enum import Enum
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


class UIUpdater(QThread):
    signal = pyqtSignal()

    def __init__(self, player: vlc.MediaPlayer, time_label: QLabel, time_text: str, next_button: QPushButton,
                 is_end=False, end_funtion=None):
        super().__init__()
        self.event = Event()
        self.player = player
        self.time_text = time_text
        self.time_label = time_label
        self.next_button = next_button
        self.is_end = is_end
        self.end_function = end_funtion

    def execute(self):
        self.event.set()

    def finish(self, timeout=None):
        pass

    def run(self) -> None:
        self.event.wait()

        while self.player.get_state() != vlc.State(3):
            time.sleep(0.1)
        total_length = self.player.get_length() // 1000

        while True:
            try:
                if not (self.player.get_state() != vlc.State(6) and self.event.is_set()):
                    break
            except Exception as e:
                print(str(e))
                break

            time_now = self.player.get_time()
            self.time_label.setText(self.time_text % getTime(int(time_now / 1000), total_length))
            time.sleep(0.2)

        self.player.stop()
        self.player.release()

        self.next_button.setEnabled(True)
        self.time_label.setText(self.time_text % (0, 0, 0, 0))

        if self.is_end:
            self.signal.emit()


class ProbeRunner(QThread):
    signal = pyqtSignal()

    def __init__(self, queue: SimpleQueue, player: vlc.MediaPlayer, video: str, is_demo=False):
        super().__init__()
        self.event = Event()
        self.end_event = Event()
        self.queue = queue
        self.player = player
        self.video = video
        self.is_demo: bool = is_demo

    def execute(self):
        self.event.set()

    def finish(self, timeout=None):
        self.event.clear()
        self.end_event.wait(timeout=timeout)

    def run(self) -> None:
        output = open("./output/probe_%s.txt" % self.video, 'w')

        self.event.wait()

        padding = 10000  # ms
        interval = 40000  # ms
        max_response = 10  # s

        clock_before = 0
        idx_before = 0

        output_str = ""
        last_probe = None
        added = True

        while self.player.get_state() != vlc.State(3):
            time.sleep(0.1)

        while True:
            try:
                if not (self.player.is_playing() and self.player.get_state() != vlc.State(6) and self.event.is_set()):
                    break
            except Exception as e:
                output.write(str(e) + '\n')
                break

            time_now = self.player.get_time()
            clock_now = time.time()

            # Play ding sound
            if (time_now - padding) // interval > idx_before:
                playsound.playsound("./resources/Ding-sound-effect.mp3", True)
                output_str += "%f,%f,sound\n" % (time_now, clock_now)
                idx_before += 1
                clock_before = clock_now
                last_probe = None
                added = False

            # Check demo: Alert if no probing in 10 sec
            if self.is_demo and (last_probe is None) and (not added) and (clock_now - clock_before >= max_response):
                self.signal.emit()
                added = True

            while not self.queue.empty():
                e: Tuple[float, str] = self.queue.get()
                if 0. <= e[0] - clock_before < max_response:
                    last_probe = e
            if last_probe is not None and not added:
                output_str += "%f,%f,probe,%s\n" % (time_now, last_probe[0], last_probe[1])
                added = True

            time.sleep(0.1)

        output.write(output_str)
        output.close()
        self.end_event.set()


class VideoRecorder(Process):
    def __init__(self, cam: int):
        super().__init__()
        self.event = Event()
        self.cam = cam
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

        self.video_cap = cv2.VideoCapture(self.cam, cv2.CAP_DSHOW)
        self.video_cap.set(cv2.CAP_PROP_FPS, 30)
        size = (int(self.video_cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

        assert(self.video_cap.isOpened())

        fourcc = cv2.VideoWriter_fourcc(*'mpeg')
        self.video_out = cv2.VideoWriter("output/recording.mp4", fourcc, 30.0, size)

        self.event.wait()

        while self.event.is_set():
            ret, frame = self.video_cap.read()
            curr_time = time.time()
            if ret and frame is not None:
                self.video_out.write(frame)
                self.output.write("%f\n" % curr_time)

        self.output.write("%f,end" % time.time())
        self.video_out.release()
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
                playsound.playsound("./resources/Keyboard.mp3", True)
            elif key == keyboard.KeyCode.from_char('n'):
                self.queue.put((curr_time, 'n'))
                playsound.playsound("./resources/Keyboard.mp3", True)

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


def proceedFunction(state_before, state_after):
    """
    These functions will call function `proceed`.

    :param state_after:
    :param state_before:
    :return:
    """
    def proceedFunction(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            assert(self._state == state_before or self._state in state_before)
            func(self, *args, **kwargs)
            if state_after is not None:
                self._state = state_after
                self.proceed()
        return wrapper
    return proceedFunction


class ExpApp(QMainWindow):

    class ProbingDialog(QDialog):
        def __init__(self, probe_text, closeDialog):
            super().__init__()
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

            dialog_layout = QVBoxLayout(self)
            self.label = QLabel("Did you hear the beep sound?\n"
                               "After hearing the sound, you should response your attentional state!\n\n"
                               + probe_text + "\n\n"
                               "You can check this guide below.")
            self.label.setAlignment(Qt.AlignCenter)
            self.button = QPushButton("OK")

            dialog_layout.addStretch(1)
            dialog_layout.addWidget(self.label, alignment=Qt.AlignVCenter)
            dialog_layout.addStretch(1)
            dialog_layout.addWidget(self.button, alignment=Qt.AlignVCenter)
            dialog_layout.addStretch(1)
            self.setLayout(dialog_layout)
            self.setWindowTitle('Alert')
            self.setWindowModality(Qt.ApplicationModal)
            self.closeDialog = closeDialog

        def connect(self, f):
            self.button.clicked.connect(f)

        def closeEvent(self, a0: QCloseEvent) -> None:
            self.closeDialog()
            return super().closeEvent(a0)

    class State(Enum):
        START = 0
        INITIALIZE = 1
        INSTRUCTION = 2
        SET_MONITOR = 3
        CALIBRATION = 4
        DEMO_VIDEO = 5
        MAIN_VIDEO = 6
        FINISH = 7
        ERROR = -1

    _state = State.START

    def signal_handler(self, sig, frame):
        if sig == signal.SIGINT:
            traceback.print_stack(frame)
        self.close()

    def log(self, string: str):
        print(string)
        self.output.write("%f,%s,%s\n" % (time.time(), self._state, string))

    @pyqtSlot("QWidget*", "QWidget*")
    def onFocusChanged(self, old, now):
        if now is None:
            self.log("focus,False")
        else:
            self.log("focus,True")

    def paintEvent(self, event):
        qp = QPainter(self)
        if self._state == self.State.CALIBRATION:
            if 0 < self.pos <= len(self.calib_position_center):
                qp.setBrush(QColor(180, 0, 0))
                qp.setPen(QPen(QColor(180, self.calib_r, self.calib_r), 1))
                x, y = self.calib_position_center[self.pos-1]
                r = self.calib_r
                qp.drawEllipse(x-r, y-r, 2*r, 2*r)
        qp.end()

    def closeEvent(self, event):
        self.log("click,x")
        self.close()

    def close(self):
        try:
            self.media_player.stop()
        except Exception as e:
            self.log(str(e))

        try:
            self.videoRecorder.finish(timeout=5.0)
            self.activityRecorder.finish(timeout=5.0)
        except Exception as e:
            self.log(str(e))

        try:
            self.probeRunner.finish(timeout=5.0)
            self.probeRunner.terminate()
        except Exception as e:
            self.log(str(e))

        try:
            self.videoRecorder.join(timeout=2.0)
            self.videoRecorder.terminate()
        except Exception as e:
            self.log(str(e))

        try:
            self.activityRecorder.join(timeout=2.0)
            self.activityRecorder.terminate()
        except Exception as e:
            self.log(str(e))

        try:
            shutil.make_archive(os.path.join("./", "output_user_%s" % self.user_id.text()), 'zip', "./output/")
        except Exception as e:
            self.log(str(e))

        self.output.close()
        exit(0)

    def __init__(self, *args, **kwargs):
        QMainWindow.__init__(self, *args, **kwargs)

        # Debugging options
        self.do_calibrate = True

        self.videos = [
            # ("10-Second-Timer", "https://www.youtube.com/watch?v=61QSHrOuGEA"),
            ("Writing-in-the-Sciences",     "https://youtu.be/J3p6wGzLi00"),  # 11m; pre-video
            ("Intro-to-Forensic-Science",   "https://youtu.be/FmPBNPFwiws"),  # 12m
            ("Intro-to-Economic-Theories",  "https://youtu.be/8yM_vw9xKnQ"),  # 12m
            ("Intro-to-AI",                 "https://youtu.be/bBaZ05WsTUM"),  # 11m
            ("Game-Theory",                 "https://youtu.be/o5vvcohd1Qg"),  # 10m
            ("What-is-Cryptography",        "https://youtu.be/XnueMv0EUHQ")   # 15m
        ]
        self.videoIndex = 0

        self.output = open("output/main_log.txt", 'w')
        self.camera = camera.select_camera("output/test.png")
        if self.camera is None:
            self.log("cameraNotFound")

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # initVLC
        if True:
            """
            https://github.com/devos50/vlc-pyqt5-example
            :return:
            """
            self.instance = vlc.Instance()
            self.media_player: vlc.MediaPlayer = self.instance.media_player_new()

        # initChild
        if True:
            self.probeQueue = SimpleQueue()

            self.probeRunner = None
            self.updater = None

            self.videoRecorder = None

            self.activityRecorder = ActivityRecorder(self.probeQueue, "Main")
            self.activityRecorder.daemon = True
            self.activityRecorder.start()
            self.activityRecorder.execute()  # Start recording keyboard & mouse

        # initUI
        if True:
            self.setWindowTitle('Online Experiment Application')
            self.setWindowIcon(QIcon('resources/nmsl_logo_yellow.png'))

            self.widget = QStackedWidget(self)
            self.camera_widget = QWidget(self)
            self.instruction_widget = QWidget(self)
            self.calibration_widget = QWidget(self)
            self.vlc_widget = QWidget(self)
            self.finish_widget = QWidget(self)

            self.widget.addWidget(self.instruction_widget)
            self.widget.addWidget(self.camera_widget)
            self.widget.addWidget(self.calibration_widget)
            self.widget.addWidget(self.vlc_widget)
            self.widget.addWidget(self.finish_widget)

            self.setCentralWidget(self.widget)
            self.widget.setCurrentWidget(self.instruction_widget)

            # Set Camera Setting Screen
            if True:
                camera_layout = QVBoxLayout(self)
                camera_text = QLabel(
                    'Please move your monitor/laptop to make face larger than the rectangle.', self
                )
                camera_text.setAlignment(Qt.AlignCenter)
                camera_text.setFixedHeight(30)
                font: QFont = camera_text.font()
                font.setBold(True)
                font.setPixelSize(15)
                camera_text.setFont(font)

                self.camera_label = QLabel(self)
                self.camera_label.setAlignment(Qt.AlignCenter)

                self.camera_finish_button = QPushButton("Continue", self)
                self.camera_finish_button.setFixedHeight(30)

                camera_layout.addWidget(camera_text, alignment=Qt.AlignVCenter)
                camera_layout.addWidget(self.camera_label, alignment=Qt.AlignVCenter)
                camera_layout.addWidget(self.camera_finish_button, alignment=Qt.AlignVCenter)

                self.camera_running = Event()

                self.camera_widget.setLayout(camera_layout)

            # setCalibWidget
            if True:
                instruction_layout = QVBoxLayout(self)

                self.detail_text = QLabel(
                    'Thank you for your participation in the project.\n\n'
                    'You will proceed\n'
                    '1) Setting proper camera angle & distance,\n'
                    '2) Perform an iteration of "Looking at a circle" -> "Clicking the circle",\n'
                    '   (Please do not move your head during the step)\n'
                    '3) Watch total 6 lectures and TAKE A QUIZ after each lecture.\n'
                    '   (You can have a short break between each lectures)\n\n'
                    'During the lecture, you will hear the "Beep" sound periodically.\n'
                    'When you hear the sound,\n'
                    '- Press [Y]: if you were on-focus (thinking of anything related to the lecture)\n'
                    '- Press [N]: if you were off-focus (thinking or doing something unrelated)\n\n'
                    'During the experiment, PLEASE AVOID MOVING LAPTOP or TOUCHING EYEGLASSES.',
                    self
                )
                font: QFont = self.detail_text.font()
                font.setPixelSize(15)
                font.setBold(True)
                self.detail_text.setFont(font)
                self.detail_text.setStyleSheet("background-color: #FFFFFF")
                self.detail_text.setContentsMargins(10, 10, 10, 10)
                instruction_layout.addWidget(self.detail_text, 0, alignment=Qt.AlignHCenter)

                self.type_student_id_text = QLabel('Type your EXPERIMENT_ID below.')
                self.type_student_id_text.setFont(QFont("Times New Roman", 15))
                self.type_student_id_text.setContentsMargins(10, 10, 10, 10)
                self.type_student_id_text.setFixedHeight(75)
                instruction_layout.addWidget(self.type_student_id_text, 0, alignment=Qt.AlignHCenter)

                self.user_id = QLineEdit(self)
                self.user_id.setFixedSize(250, 75)
                self.user_id.setAlignment(Qt.AlignCenter)
                self.user_id.setValidator(QIntValidator())
                instruction_layout.addWidget(self.user_id, 0, alignment=Qt.AlignHCenter)

                # Start button: start the experiment
                if self.camera is not None:
                    self.start_button = QPushButton('Start\n(Please wait after click)', self)
                else:
                    self.start_button = QPushButton("You don't have any camera available", self)
                    self.start_button.setDisabled(True)
                self.start_button.setFixedSize(250, 125)
                self.start_button.clicked.connect(self.proceed)

                instruction_layout.addWidget(self.start_button, 0, alignment=Qt.AlignHCenter)
                instruction_layout.setSpacing(10)

                self.instruction_widget.setLayout(instruction_layout)

            # Set Calibration Widget
            if True:
                calib_layout = QVBoxLayout(self)
                # Calibration button
                self.ellipse_button = QPushButton('', self)
                self.ellipse_button.move(0, 0)
                self.ellipse_button.setStyleSheet("background-color: transparent")
                self.ellipse_button.hide()
                self.ellipse_button.clicked.connect(self.proceed)

                calib_layout.addWidget(self.ellipse_button, alignment=Qt.AlignAbsolute)
                self.calibration_widget.setLayout(calib_layout)

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
                vlc_layout.addWidget(self.video_frame, alignment=Qt.AlignVCenter)

                # Lower Layout ###################################################################
                vlc_lower_layout = QHBoxLayout(self)

                vlc_lower_layout.addStretch(1)

                self.next_button = QPushButton('Start Video', self)
                self.next_button.setFixedSize(100, 30)
                self.next_button.clicked.connect(self.proceed)
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
                volume_slider.setMaximumWidth(300)
                volume_slider.setFixedHeight(25)
                volume_slider.setValue(self.media_player.audio_get_volume())
                volume_slider.setToolTip("Volume")
                volume_slider.valueChanged.connect(self.media_player.audio_set_volume)

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
                self.dialog = self.ProbingDialog(self.probe_text, self.closeDialog)
                self.dialog.connect(self.closeDialog)

            # Finish scene
            if True:
                finish_layout = QVBoxLayout(self)
                self.finish_text = 'Thank you for the participation!\n'\
                                   'Please do not forget to submit the result :)\n\n'\
                                   'Your PARTICIPANT_ID is [%s]'
                self.finish_label = QLabel(self.finish_text)
                self.finish_label.setAlignment(Qt.AlignCenter)
                self.finish_label.setFixedHeight(200)
                font: QFont = self.finish_label.font()
                font.setBold(True)
                font.setPixelSize(30)
                self.finish_label.setFont(font)
                finish_layout.addWidget(self.finish_label, alignment=Qt.AlignHCenter)

                finish_button = QPushButton('Finish\n(Please Wait)', self)
                finish_button.setFixedSize(400, 100)
                finish_button.clicked.connect(self.close)
                finish_layout.addWidget(finish_button, alignment=Qt.AlignHCenter)

                self.finish_widget.setLayout(finish_layout)

            # Maximize the screen
            self.showMaximized()

            # Set focused and make on-focus checker
            qApp.focusChanged.connect(self.onFocusChanged)

            # Calibration parameters
            self.margin = 0
            self.calib_r = 50
            self.pos = 0
            self.calib_position_center: List[Tuple[int, int]] = [(0, 0)]

        self._state = self.State.INSTRUCTION

    def proceed(self):
        """
        Every non-inherited methods are executed here.

        :return:
        """
        self.log(f'proceed: {self._state}')
        if self._state is self.State.INITIALIZE:
            self.initialize()
        elif self._state is self.State.INSTRUCTION:
            self.set_instruction()
        elif self._state is self.State.SET_MONITOR:
            self.set_monitor()
        elif self._state is self.State.CALIBRATION:
            self.calibrate()
        elif self._state is self.State.DEMO_VIDEO:
            self.startVideo(demo=True)
        elif self._state is self.State.MAIN_VIDEO:
            self.startVideo()
        elif self._state is self.State.FINISH:
            self.final()

    @proceedFunction(State.INSTRUCTION, State.INITIALIZE)
    def set_instruction(self):
        pass

    @proceedFunction(State.INITIALIZE, State.SET_MONITOR)
    def initialize(self):
        screen = qApp.primaryScreen()
        dpi = screen.physicalDotsPerInch()
        full_screen = screen.size()
        # self.setFixedHeight(full_screen.height())
        # self.setFixedWidth(full_screen.width())

        x_mm = 2.54 * full_screen.height() / dpi  # in->cm
        y_mm = 2.54 * full_screen.width() / dpi  # in->cm
        self.calib_r = int(min(full_screen.width(), full_screen.height()) / 100)
        self.margin = self.calib_r * 2

        # Leave logs
        self.log('monitor,%f,%f' % (x_mm, y_mm))
        self.log('resolution,%d,%d' % (full_screen.width(), full_screen.height()))
        self.log('inner_area,%d,%d' % (self.rect().width(), self.rect().height()))
        self.log('calibration_Radius,%d' % self.calib_r)

        # Resize frames
        self.camera_label.setFixedHeight(self.rect().height() - 100)
        self.video_frame.setFixedHeight(self.rect().height() - 30)

        # Sort URL w.r.t. Student ID
        random.seed(self.user_id.text())
        target = self.videos[1:]
        random.shuffle(target)
        self.videos[1:] = target
        print(self.videos)

        self.type_student_id_text.hide()
        self.start_button.hide()
        self.detail_text.hide()
        self.user_id.hide()

        self.ellipse_button.setFixedSize(self.calib_r * 2, self.calib_r * 2)
        self.ellipse_button.show()
        self.calib_position_center = [
            (self.margin, self.margin),
            (self.rect().width() / 2, self.margin),
            (self.rect().width() - self.margin, self.margin),

            (self.margin, self.rect().height() / 2),
            (self.rect().width() / 2, self.rect().height() / 2),
            (self.rect().width() - self.margin, self.rect().height() / 2),

            (self.margin, self.rect().height() - self.margin),
            (self.rect().width() / 2, self.rect().height() - self.margin),
            (self.rect().width() - self.margin, self.rect().height() - self.margin),

            (self.rect().width() / 4, self.rect().height() / 4),
            (self.rect().width() * 3 / 4, self.rect().height() / 4),
            (self.rect().width() / 4, self.rect().height() * 3 / 4),
            (self.rect().width() * 3 / 4, self.rect().height() * 3 / 4),

            (self.calib_r, self.calib_r),
            (self.rect().width() - self.calib_r, self.calib_r),
            (self.calib_r, self.rect().height() - self.calib_r),
            (self.rect().width() - self.calib_r, self.rect().height() - self.calib_r),
        ]

    @proceedFunction(State.SET_MONITOR, None)  # Asynchronously proceed CALIBRATION
    def set_monitor(self):
        if self.user_id.text() == "":
            return
        self.log('user_id,%s' % (self.user_id.text()))

        self.widget.setCurrentWidget(self.camera_widget)

        cap = None
        success = self.camera is not None

        if success:
            cap = cv2.VideoCapture(self.camera, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FPS, 30)

            if not cap.isOpened():
                success = False

        if not success:
            self.camera_finish_button.setDisabled(True)
            self.log("setMonitor,fail")
            self.camera_label.setText("No Camera Detected")
            return

        width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        self.log("cameraCapture,%d,%d" % (int(width), int(height)))

        def frame_thread_run():
            while not self.camera_running.is_set():
                try:
                    ret, img = cap.read()
                    if ret:
                        img = img.copy()
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        img = cv2.flip(img, 1)
                        h, w, c = img.shape
                        img = cv2.resize(img, dsize=(int(self.camera_label.height() * w/h), int(self.camera_label.height())))
                        h, w, c = img.shape
                        img = cv2.rectangle(img, (int(w/3), int(h/4)), (int(2*w/3), int(3*h/4)), (0, 0, 255), 3)
                        image = QImage(img.data, w, h, w*c, QImage.Format_RGB888)
                        pixmap = QPixmap.fromImage(image)
                        self.camera_label.setPixmap(pixmap)
                    else:
                        break
                except Exception as e:
                    self.log(str(e))
                    break

        frame_thread = Thread(target=frame_thread_run, args=())
        frame_thread.daemon = True
        frame_thread.start()

        def camera_finished_wrapper():
            self.camera_finished(frame_thread, cap)

        self.camera_finish_button.clicked.connect(camera_finished_wrapper)

    @proceedFunction(State.SET_MONITOR, State.CALIBRATION)
    def camera_finished(self, frame_thread, cap):
        self.camera_running.set()

        frame_thread.join()
        cap.release()

        # Start recording
        self.videoRecorder = VideoRecorder(self.camera)
        self.videoRecorder.daemon = True
        self.videoRecorder.start()
        self.videoRecorder.execute()

        self.widget.setCurrentWidget(self.calibration_widget)

    @proceedFunction(State.CALIBRATION, None)  # Calibrate will proceed when done
    def calibrate(self):
        self.log("calibrate,%d" % self.pos)

        if self.pos >= len(self.calib_position_center):
            self.ellipse_button.hide()
            self.widget.setCurrentWidget(self.vlc_widget)
            self._state = self.State.DEMO_VIDEO
            return
        else:
            self.ellipse_button.move(self.calib_position_center[self.pos][0] - self.calib_r,
                                     self.calib_position_center[self.pos][1] - self.calib_r)

        if not self.do_calibrate:
            self.pos = len(self.calib_position_center) + 1
            self.ellipse_button.hide()
            self.widget.setCurrentWidget(self.vlc_widget)
            self._state = self.State.DEMO_VIDEO
        else:
            self.pos += 1
            self.update()

    def showDialog(self):
        self.media_player.pause()
        self.dialog.show()

    def closeDialog(self):
        self.dialog.close()
        self.media_player.play()

    @proceedFunction([State.DEMO_VIDEO, State.MAIN_VIDEO], None)
    def startVideo(self, demo=False):
        assert(self.videoIndex == 0 or not demo)

        self.next_button.setDisabled(True)

        if self.videoIndex >= len(self.videos):  # Finish (includes probeRunner cleanup)
            self.finishVideo()
            return

        if self.videoIndex != 0:
            self.probeRunner.finish(timeout=15.0)
            self.probeRunner.terminate()
            self.updater.terminate()

        self.activityRecorder.finish(timeout=5.0)  # Stop recording keyboard & mouse
        self.activityRecorder.join()

        self.activityRecorder = ActivityRecorder(self.probeQueue, self.videos[self.videoIndex][0])
        self.activityRecorder.daemon = True
        self.activityRecorder.start()

        self.probeRunner = ProbeRunner(self.probeQueue, self.media_player, self.videos[self.videoIndex][0], demo)
        self.probeRunner.daemon = True
        self.probeRunner.start()
        # self.dialog.moveToThread(self.probeRunner)  # You should move before connecting the signal
        self.probeRunner.signal.connect(self.showDialog)

        self.updater = UIUpdater(self.media_player, self.time_label, self.time_text, self.next_button,
                                 is_end=self.videoIndex == len(self.videos)-1)
        self.updater.daemon = True
        self.updater.start()
        self.updater.signal.connect(self.finishVideo)

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
            self._state = self.State.MAIN_VIDEO
            self.video_index_label.setText(self.video_index_text % (self.videoIndex, len(self.videos)))

    @proceedFunction(State.MAIN_VIDEO, State.FINISH)
    def finishVideo(self):
        self.probeRunner.finish(timeout=15.0)
        self.probeRunner.terminate()
        self.updater.terminate()
        return

    def final(self):
        self.finish_label.setText(self.finish_text % self.user_id.text())
        self.widget.setCurrentWidget(self.finish_widget)


if __name__ == '__main__':
    if not os.path.exists('output'):
        os.mkdir('output')

    # Pyinstaller fix
    freeze_support()

    # PyQT
    app = QApplication(sys.argv)
    ex = ExpApp()
    sys.exit(app.exec_())
