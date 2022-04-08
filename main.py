import functools

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from pynput import mouse, keyboard
import cv2

from multiprocessing import Event, freeze_support, SimpleQueue, Value
from imutils import face_utils
from threading import Thread
from enum import Enum, auto
import traceback
import imutils
import shutil
import random
import signal
import dlib
import time
import sys
import os

from typing import List, Tuple

from utils import vlc, camera, sound, notification, parsing


def getResource(name):
    if sys.platform=="darwin":
        return name
    else:
        return "./resources/"+name

def getTime(time_now, total):
    return time_now//60, time_now % 60, total//60, total % 60


class UIUpdater(QThread):
    signal = pyqtSignal()

    def __init__(self, frame: QFrame, player: vlc.MediaPlayer, time_label: QLabel, time_text: str,
                 video_label: QLabel, video_text: str, next_button: QPushButton, is_end=False):
        super().__init__()
        self.event = Event()
        self.probeEvent = Event()
        self.closeEvent = Event()
        self.frame = frame
        self.player = player
        self.time_text = time_text
        self.time_label = time_label
        self.video_text = video_text
        self.video_label = video_label
        self.next_button = next_button
        # self.quiz_url = quiz_url
        self.is_end = is_end

    def execute(self):
        self.event.set()

    def finish(self, timeout=None):
        self.event.clear()
        self.closeEvent.wait(timeout)

    def alertProbeRunnerFinished(self):
        self.probeEvent.set()

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
                print(str(e), flush=True)
                break

            time_now = self.player.get_time()
            self.time_label.setText(self.time_text % getTime(int(time_now / 1000), total_length))
            time.sleep(0.5)

        # Wait for ProbeRunner
        self.probeEvent.wait()
        self.player.release()

        self.video_label.setText(self.video_text)
        self.time_label.setText(self.time_text % (0, 0, 0, 0))
        # if self.event.is_set():  # Normal ending with video finished
        #     os.system(f"start {self.quiz_url}")
        self.next_button.setEnabled(True)

        if self.is_end:
            self.signal.emit()
        self.closeEvent.set()


class ProbeRunner(QThread):
    signal = pyqtSignal()
    ui_signal = pyqtSignal()

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
        output = open("./output/probe_%s.txt" % self.video, 'w', buffering=1, encoding='UTF-8')

        self.event.wait()

        padding = 5000  # ms
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
                if not (self.player.get_state() != vlc.State(6) and self.event.is_set()):
                    break
            except Exception as e:
                output.write(str(e) + '\n')
                break

            time_now = self.player.get_time()
            clock_now = time.time()

            # Play ding sound
            if (time_now - padding) // interval > idx_before:
                sound.play(getResource("Ding-sound-effect.mp3"))
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

        self.ui_signal.emit()
        output.write(output_str)
        output.close()
        self.end_event.set()


class VideoRecorder(Thread):
    def __init__(self, cam: int):
        super().__init__()
        self.event = Event()
        self.proceed_event = Event()
        self.cam = cam
        self.video_timeline = None
        self.video_cap = None
        self.video_out = None
        self.val = Value('i', 0, lock=True)
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, sig, frame):
        if sig == signal.SIGINT:
            traceback.print_stack(frame)
            print("SIGINT FROM CHILD!", flush=True)

        self.output.close()
        if self.video_cap is not None:
            self.video_out.release()

        self.event.set()
        sys.exit(0)

    def execute(self):
        self.event.set()
        self.proceed_event.wait()

    def finish(self, timeout=None):
        self.event.clear()
        self.event.wait(timeout=timeout)

    def setFrameCount(self):
        with self.val.get_lock():
            self.val.value = 0

    def getFrameCount(self):
        return self.val.value

    def run(self) -> None:
        self.output = open("./output/video_timeline.txt", 'w', buffering=1, encoding='UTF-8')
        if sys.platform=="darwin":
            self.video_cap = cv2.VideoCapture(self.cam)
        else:
            self.video_cap = cv2.VideoCapture(self.cam, cv2.CAP_DSHOW)
        self.video_cap.set(cv2.CAP_PROP_FPS, 30)
        
        size = (int(self.video_cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

        assert(self.video_cap.isOpened())
        
        fourcc = cv2.VideoWriter_fourcc(*'mpeg')
        self.video_out = cv2.VideoWriter("output/recording.mp4", fourcc, 30.0, size)
        self.event.wait()
        self.proceed_event.set()
        while self.event.is_set():
            ret, frame = self.video_cap.read()
            curr_time = time.time()
            if ret and frame is not None:
                self.video_out.write(frame)
                self.output.write("%f\n" % curr_time)
                with self.val.get_lock():
                    self.val.value += 1
        self.output.write("%f,end" % time.time())
        self.video_out.release()
        cv2.destroyAllWindows()
        self.output.close()
        self.event.set()


class ActivityRecorder(Thread):
    def __init__(self, queue: SimpleQueue, name: str):
        super().__init__()
        self.event = Event()
        self.finishEvent = Event()
        self.queue = queue
        self.name = name
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

    def signal_handler(self, sig, frame):
        try:
            self.keyboard_listener.stop()
            self.mouse_listener.stop()
        except Exception as e:
            print(e)

        try:
            self.keyboard_output.close()
            self.mouse_output.close()
        except Exception as e:
            print(e)

        if sig == signal.SIGINT:
            traceback.print_stack(frame)
            print("SIGINT FROM CHILD!", flush=True)

        sys.exit(0)

    def execute(self):
        self.event.set()

    def finish(self, timeout=None):
        self.event.set()
        self.finishEvent.wait(timeout=timeout)

    def key_log(self, string: str):
        self.keyboard_output.write("%f,%s\n" % (time.time(), string))

    def mouse_log(self, string: str):
        self.mouse_output.write("%f,%s\n" % (time.time(), string))

    def onMouseMove(self, x, y):
        self.mouse_log("mouse,move,%d,%d" % (x, y))

    def onMouseClick(self, x, y, button, pressed):
        self.mouse_log("mouse,click,%s,%d,%d,%d" % (button, pressed, x, y))

    def onMouseScroll(self, x, y, dx, dy):
        self.mouse_log("mouse,scroll,%d,%d,%d,%d" % (x, y, dx, dy))

    def onKeyPress(self, key):
        self.key_log("key,press,%s" % str(key))

    def onKeyRelease(self, key):
        self.key_log("key,release,%s" % str(key))
        curr_time = time.time()
        if isinstance(key, keyboard.KeyCode):
            if key in [keyboard.KeyCode.from_char('f'), keyboard.KeyCode.from_char('F'), keyboard.KeyCode.from_char('ㄹ')]:
                self.queue.put((curr_time, 'y'))
                sound.play(getResource("Keyboard.mp3"))
            elif key in [keyboard.KeyCode.from_char('n'), keyboard.KeyCode.from_char('N'), keyboard.KeyCode.from_char('ㅜ')]:
                self.queue.put((curr_time, 'n'))
                sound.play(getResource("Keyboard.mp3"))
        elif key == keyboard.Key.space:
            self.queue.put((curr_time, 'p'))
            sound.play(getResource("Keyboard.mp3"))

    def run(self) -> None:

        self.mouse_output = open("output/mouse_log_%s.txt" % self.name, 'w', buffering=1, encoding='UTF-8')
        self.keyboard_output = open("output/keyboard_log_%s.txt" % self.name, 'w', buffering=1, encoding='UTF-8')
        '''
        self.mouse_listener = mouse.Listener(
            on_move=self.onMouseMove,
            on_click=self.onMouseClick,
            on_scroll=self.onMouseScroll
        )
        print(2)
        self.keyboard_listener = keyboard.Listener(
            on_press=self.onKeyPress,
            on_release=self.onKeyRelease
        )
        print(3)
        #signal.signal(signal.SIGINT, self.signal_handler)
        #signal.signal(signal.SIGTERM, self.signal_handler)
        '''
        self.event.wait()

        self.mouse_listener.start()
        self.keyboard_listener.start()

        self.event.clear()
        self.event.wait()

        self.mouse_listener.stop()
        self.keyboard_listener.stop()

        self.mouse_output.close()
        self.keyboard_output.close()

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
        def __init__(self, probe_text, close_dialog):
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
            self.closeDialog = close_dialog

        def connect(self, f):
            self.button.clicked.connect(f)

        def closeEvent(self, a0: QCloseEvent) -> None:
            self.closeDialog()
            return super().closeEvent(a0)

    class State(Enum):
        START = auto()
        SET_DISTRACTION = auto()
        SET_PARAMETERS = auto()
        CALIB_INSTRUCTION = auto()
        SET_CAMERA = auto()
        CALIBRATION = auto()
        LECTURE_INSTRUCTION = auto()
        DEMO_VIDEO = auto()
        MAIN_VIDEO = auto()
        FINISH = auto()
        ERROR = auto()

    _state = State.START

    def signal_handler(self, sig, frame):
        if sig == signal.SIGINT:
            traceback.print_stack(frame)
        self.close()

    def log(self, string: str):
        print(string, flush=True)
        self.output.write("%f,%s,%s\n" % (time.time(), self._state, string))

    @pyqtSlot("QWidget*", "QWidget*")
    def onFocusChanged(self, old, now):
        if now is None:
            self.log("focus,False")
        else:
            self.log("focus,True")

    def closeEvent(self, event):
        self.log("click,x")
        self.close()

    def close(self):
        try:
            self.media_player.stop()
        except Exception as e:
            self.log(str(e))

        try:
            self.probeRunner.finish(timeout=5.0)
            self.probeRunner.terminate()
            self.updater.finish(timeout=1.0)
            self.updater.terminate()
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
            self.videoRecorder.finish(timeout=10.0)
            self.videoRecorder.join()
            #self.videoRecorder.join(timeout=2.0)
            #self.videoRecorder.terminate()
        except Exception as e:
            self.log(str(e))

        try:
            self.activityRecorder.finish(timeout=3.0)
            self.activityRecorder.join()
            #self.activityRecorder.join(timeout=2.0)
            #self.activityRecorder.terminate()
        except Exception as e:
            self.log(str(e))

        try:
            if sys.platform == "darwin":
                output_name = os.path.join("../../../", "output_user_%s" % self.user_id.text())
                save_idx = 0
                while os.path.isfile(output_name+".zip"):
                    save_idx += 1
                    output_name = output_name.split("(")[0] + ("(%d)" % save_idx)
                shutil.make_archive(output_name, 'zip', "./output/")

            
            output_name = os.path.join("./", "output_user_%s" % self.user_id.text())
            save_idx = 0
            while os.path.isfile(output_name+".zip"):
                save_idx += 1
                output_name = output_name.split("(")[0] + ("(%d)" % save_idx)
            shutil.make_archive(output_name, 'zip', "./output/")
            #shutil.make_archive(os.path.join("./", "output_user_%s" % self.user_id.text()), 'zip', "./output/")
        except Exception as e:
            self.log(str(e))

        self.output.close()

        # os.system("start https://forms.gle/UUVqMUMvwvGFKSet6")
        # taskbar.unhide_taskbar()
        sys.exit(0)

    def __init__(self, *args, **kwargs):
        QMainWindow.__init__(self, *args, **kwargs)

        # taskbar.hide_taskbar()

        # Debugging options (Disable camera setting & calibration)
        self._skip_camera = False
        self._skip_calib = False

        ########### MODIFY HERE! ######################################
        self.videos = [
            # Convention:
            # File: (VIDEO_TITLE, getResource(VIDEO_PATH))
            # Youtube: (VIDEO_TITLE, YOUTUBE_URL)
            ("Pre-video", "https://www.youtube.com/watch?v=ElnxAu6X_s4"),
            ("Main-video", "https://www.youtube.com/watch?v=ElnxAu6X_s4"),
        ]
        ###############################################################

        self.videoIndex = 0

        self.output = open("output/main_log.txt", 'w', buffering=1, encoding='UTF-8')
        self.camera = camera.select_camera("output/test.png")
        if self.camera is None:
            self.log("cameraNotFound")

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.small_font = QFont("Roboto")
        self.small_font.setPixelSize(13)
        self.small_font.setBold(False)

        # initVLC
        if True:
            """
            https://github.com/devos50/vlc-pyqt5-example
            :return:
            """
            self.instance = vlc.Instance()
            self.media_player: vlc.MediaPlayer = None

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
            #self.setWindowIcon(QIcon('resources/nmsl_logo_yellow.png'))
            self.setWindowIcon(QIcon(getResource('nmsl_logo_yellow.png')))

            self.widget = QStackedWidget(self)
            self.distraction_instruction_widget = QWidget(self)
            self.calib_instruction_widget = QWidget(self)
            self.camera_setting_widget = QWidget(self)
            self.calibration_widget = QWidget(self)
            self.lecture_instruction_widget = QWidget(self)
            self.lecture_video_widget = QWidget(self)
            self.finish_widget = QWidget(self)

            self.widget.addWidget(self.distraction_instruction_widget)
            self.widget.addWidget(self.calib_instruction_widget)
            self.widget.addWidget(self.camera_setting_widget)
            self.widget.addWidget(self.calibration_widget)
            self.widget.addWidget(self.lecture_instruction_widget)
            self.widget.addWidget(self.lecture_video_widget)
            self.widget.addWidget(self.finish_widget)

            self.setCentralWidget(self.widget)
            self.widget.setCurrentWidget(self.calib_instruction_widget)

            # Set Camera Setting Screen
            if True:
                camera_layout = QVBoxLayout(self)
                camera_text = QLabel(
                    'Please move your monitor/laptop close and center your face so it exceeds BLUE rectangle.\n\n'
                    'Please avoid direct lights into the camera.'
                    , self
                )
                camera_text.setAlignment(Qt.AlignCenter)
                camera_text.setFixedHeight(100)

                self.camera_label = QLabel(self)
                self.camera_label.setAlignment(Qt.AlignCenter)

                self.camera_finish_button = QPushButton("Next", self)
                self.camera_finish_button.setFixedHeight(50)

                camera_layout.addWidget(camera_text, alignment=Qt.AlignVCenter)
                camera_layout.addWidget(self.camera_label, alignment=Qt.AlignVCenter)
                camera_layout.addWidget(self.camera_finish_button, alignment=Qt.AlignVCenter)

                self.camera_running = Event()

                self.camera_setting_widget.setLayout(camera_layout)

            # Set Notification Widget
            if True:
                notification_layout = QVBoxLayout(self)

                noti_text = QLabel(
                    'Thank you for your participation in the project.\n'
                    'Your participation will help to improve the understanding of online learning.\n'
                    'Please make sure you completed pre-experiment survey and pre-quiz.\n\n'
                    'Please disable every external distractions:\n'
                    '- Mute your phone, tablet, etc.\n'
                    '- Disable notifications from Messenger programs (Slack, KakaoTalk, etc.)\n'
                    '- Disconnect every external monitor (if you are connected)\n'
                    '- Please do not let others disturb you\n'
                    '- (Mac) In the control center, click 🌙 (moon) icon, and turn on do-not-disturb mode for at least 2 hours.\n'
                    '- (Windows) Disable notification as below image'
                    , self
                )
                noti_text.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
                noti_text.setContentsMargins(10, 10, 10, 10)

                noti_image = QLabel(self)
                noti_image.setFixedSize(758, 270)
                #noti_image.setPixmap(QPixmap("./resources/focus_assistant.png"))
                noti_image.setPixmap(QPixmap(getResource("focus_assistant.png")))

                noti_open = QPushButton('Open Settings (Only Windows)')
                noti_open.setFixedSize(758, 50)
                noti_open.clicked.connect(notification.open_settings)

                type_student_id_text = QLabel('Type your Participation ID below.')
                type_student_id_text.setFixedHeight(75)

                self.user_id = QLineEdit(self)
                self.user_id.setFixedSize(758, 50)
                self.user_id.setAlignment(Qt.AlignCenter)
                self.user_id.setValidator(QIntValidator())

                self.noti_proceed = QPushButton('Next')
                self.noti_proceed.setFixedSize(758, 50)
                self.noti_proceed.clicked.connect(self.proceed)

                notification_layout.addStretch(10)
                notification_layout.addWidget(noti_text, alignment=Qt.AlignHCenter)
                notification_layout.addStretch(1)
                notification_layout.addWidget(noti_image, alignment=Qt.AlignHCenter)
                notification_layout.addStretch(3)
                notification_layout.addWidget(noti_open, alignment=Qt.AlignHCenter)
                notification_layout.addStretch(3)
                notification_layout.addWidget(type_student_id_text, alignment=Qt.AlignHCenter)
                notification_layout.addStretch(1)
                notification_layout.addWidget(self.user_id, alignment=Qt.AlignHCenter)
                notification_layout.addStretch(1)
                notification_layout.addWidget(self.noti_proceed, alignment=Qt.AlignHCenter)
                notification_layout.addStretch(10)

                notification_layout.setSpacing(10)
                self.distraction_instruction_widget.setLayout(notification_layout)

            # Set Calibration Instruction Widget
            if True:
                instruction_layout = QVBoxLayout(self)

                detail_text = QLabel(
                    'Now, you will proceed an loop of "Looking at a circle" -> "Clicking the circle".\n\n'
                    '- Please do not move your head during the step.\n\n'
                    '- You may need to click multiples times.',
                    self
                )
                detail_text.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
                detail_text.setContentsMargins(10, 10, 10, 10)

                self.start_calib_button = QPushButton('Next', self)
                self.start_calib_button.setFixedSize(758, 50)

                instruction_layout.addStretch(10)
                instruction_layout.addWidget(detail_text, 0, alignment=Qt.AlignHCenter)
                instruction_layout.addStretch(1)
                instruction_layout.addWidget(self.start_calib_button, 0, alignment=Qt.AlignHCenter)
                instruction_layout.addStretch(10)

                self.calib_instruction_widget.setLayout(instruction_layout)

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

            # Set Lecture Instruction Widget
            if True:
                instruction_layout = QVBoxLayout(self)

                lecture_text = QLabel(
                    'Now, you will watch one short + one long lecture.\n\n'
                    '-----------------------------------------IMPORTANT-----------------------------------------\n\n'
                    'During the experiment, please avoid moving laptop or touching eyeglasses.\n\n'
                    'During the lecture, you will periodically hear the "beep" sound.\n\n'
                    'When you hear the sound, based on your state JUST BEFORE hearing the sound:\n\n'
                    '- Press [F]: if you were Focusing (thinking of anything related to the lecture)\n\n'
                    '- Press [N]: if you were NOT focusing (thinking or doing something unrelated to the lecture)\n\n'
                    '- Press [SpaceBar]: if you cannot decide\n\n'
                    'Please report as promptly and honestly as you can; your report will NOT affect your monetary reward.\n\n'
                    'If you pressed the wrong key, then just press again.\n\n\n'
                    '----------------------------------------------------------------------------------------------------\n\n'
                    'Please adjust your system volume to make sure you hear the beep sound.',
                    self
                )
                lecture_text.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
                lecture_text.setContentsMargins(10, 10, 10, 10)

                beep_button = QPushButton('Test Beep Sound', self)
                beep_button.setFixedSize(758, 50)

                def launch_beep():
                    #sound.play("./resources/Ding-sound-effect.mp3")
                    sound.play(getResource("Ding-sound-effect.mp3"))
                    
                beep_button.clicked.connect(launch_beep)

                start_button = QPushButton('Next', self)
                start_button.setFixedSize(758, 50)
                start_button.clicked.connect(self.proceed)

                instruction_layout.addStretch(10)
                instruction_layout.addWidget(lecture_text, 0, alignment=Qt.AlignHCenter)
                instruction_layout.addStretch(1)
                instruction_layout.addWidget(beep_button, 0, alignment=Qt.AlignHCenter)
                instruction_layout.addStretch(1)
                instruction_layout.addWidget(start_button, 0, alignment=Qt.AlignHCenter)
                instruction_layout.addStretch(10)

                self.lecture_instruction_widget.setLayout(instruction_layout)

            # Set Lecture Video Widget
            if True:
                vlc_layout = QVBoxLayout(self)
                # VLC player
                # In this widget, the video will be drawn
                self.video_frame = QFrame()

                palette = self.video_frame.palette()
                palette.setColor(QPalette.Window, QColor(255, 255, 255))
                self.video_frame.setPalette(palette)
                self.video_frame.setAutoFillBackground(True)
                vlc_layout.addWidget(self.video_frame, alignment=Qt.AlignVCenter)
                #vlc_layout.updateGeometry()
                #self.video_frame.updateGeometry()

                # Lower Layout ###################################################################
                vlc_lower_layout = QHBoxLayout(self)

                vlc_lower_layout.addStretch(1)

                self.next_button = QPushButton('Start Video', self)
                self.next_button.setFixedSize(100, 30)
                self.next_button.clicked.connect(self.proceed)
                self.next_button.setFont(self.small_font)
                vlc_lower_layout.addWidget(self.next_button, alignment=Qt.AlignHCenter)

                self.video_index_text = ' [Video: %01d/%01d] '
                self.video_index_label = QLabel(self.video_index_text % (1, len(self.videos)))
                self.video_index_label.setFixedSize(80, 30)
                self.video_index_label.setFont(self.small_font)
                vlc_lower_layout.addWidget(self.video_index_label, alignment=Qt.AlignHCenter)

                self.time_text = ' [Time: %02d:%02d/%02d:%02d] '
                self.time_label = QLabel(self.time_text % (0, 0, 0, 0))
                self.time_label.setFixedSize(160, 30)
                self.time_label.setFont(self.small_font)
                vlc_lower_layout.addWidget(self.time_label, alignment=Qt.AlignHCenter)

                vlc_lower_layout.addStretch(1)

                self.probe_text = 'FOCUSED: [F] / NOT FOCUSED: [N] / SKIP: [Space]'
                self.probe_label = QLabel(self.probe_text)
                font: QFont = self.probe_label.font()
                font.setFamily('Roboto')
                font.setPixelSize(13)
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
                volume_label.setFont(self.small_font)
                vlc_volume_layout.addWidget(volume_label, alignment=Qt.AlignHCenter | Qt.AlignRight)

                volume_slider = QSlider(Qt.Horizontal, self)
                volume_slider.setMaximum(100)
                volume_slider.setMaximumWidth(300)
                volume_slider.setFixedHeight(25)
                volume_slider.setValue(100)
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
                self.lecture_video_widget.setLayout(vlc_layout)
                # Dialog
                self.dialog = self.ProbingDialog(self.probe_text, self.closeDialog)
                self.dialog.connect(self.closeDialog)

            # Finish scene
            if True:
                finish_layout = QVBoxLayout(self)
                self.finish_text = 'Thank you for the participation!\n'\
                                   'Please do not forget to submit the result :)\n\n'
                self.finish_label = QLabel(self.finish_text)
                self.finish_label.setAlignment(Qt.AlignCenter)
                self.finish_label.setFixedHeight(200)
                font: QFont = self.finish_label.font()
                font.setBold(True)
                font.setPixelSize(30)
                self.finish_label.setFont(font)
                finish_layout.addWidget(self.finish_label, alignment=Qt.AlignHCenter)

                finish_button = QPushButton('Finish\n(Please Wait)', self)
                finish_button.setFixedSize(758, 100)
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
            self.clicks = 0
            self.calib_started = False
            self.calib_position_center: List[Tuple[int, int]] = [(0, 0)]

        self._state = self.State.SET_DISTRACTION
        self.widget.setCurrentWidget(self.distraction_instruction_widget)

    def proceed(self):
        """
        Every non-inherited methods are executed here.
        This function is only called at proceedFunction().

        :return:
        """
        self.log(f'proceed: {self._state}')
        if self._state is self.State.SET_DISTRACTION:
            self.set_notification()
        elif self._state is self.State.SET_PARAMETERS:
            if self.user_id.text() != "":
                self.initialize()
        elif self._state is self.State.CALIB_INSTRUCTION:
            self.set_instruction()
        elif self._state is self.State.SET_CAMERA:
            self.set_camera()
        elif self._state is self.State.CALIBRATION:
            self.calibrate()
        elif self._state is self.State.LECTURE_INSTRUCTION:
            self.lecture_instruction()
        elif self._state is self.State.DEMO_VIDEO:
            self.start_video(demo=True)
        elif self._state is self.State.MAIN_VIDEO:
            self.start_video()
        elif self._state is self.State.FINISH:
            self.final()

    @proceedFunction(State.SET_DISTRACTION, State.SET_PARAMETERS)
    def set_notification(self):
        return

    @proceedFunction(State.SET_PARAMETERS, State.SET_CAMERA)
    def initialize(self):
        self.noti_proceed.setDisabled(True)

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
        self.log('experimenter,%s' % self.user_id.text())
        self.log('monitor,%f,%f' % (x_mm, y_mm))
        self.log('resolution,%d,%d' % (full_screen.width(), full_screen.height()))
        self.log('inner_area,%d,%d' % (self.rect().width(), self.rect().height()))
        self.log('calibration_Radius,%d' % self.calib_r)

        # Resize frames
        self.camera_label.setFixedHeight(self.rect().height() - 200)
        self.video_frame.setFixedHeight(self.rect().height() - 30)

        # Sort URL w.r.t. Student ID
        random.seed(self.user_id.text())
        target = self.videos[1:]
        random.shuffle(target)
        self.videos[1:] = target
        self.log(f'videos,{self.videos}')

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

    @proceedFunction(State.SET_CAMERA, None)  # Next: CALIB_INSTRUCTION
    def set_camera(self):
        if not self._skip_camera:
            self.camera_finish_button.setDisabled(True)
        self.widget.setCurrentWidget(self.camera_setting_widget)

        cap = None
        success = self.camera is not None

        if success:
            if sys.platform=="darwin":
                cap = cv2.VideoCapture(self.camera)
            else:
                cap = cv2.VideoCapture(self.camera, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FPS, 30)

            if not cap.isOpened():
                success = False

        if not success:
            self.camera_finish_button.setText("Quit")
            def quick_exit():
                sys.exit(0)
            self.camera_finish_button.clicked.connect(quick_exit)
            self.camera_finish_button.setEnabled(True)
            self.log("setMonitor,fail")
            self.camera_label.setText("No Camera Detected.\n\nPlease check if\n"
                                      " - Camera is properly connected.\n"
                                      " - (Mac) You allowed camera permission.\n"
                                      " - (Windows) No other app is using camera.")
            return

        width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        self.log("cameraCapture,%d,%d" % (int(width), int(height)))

        def distance2(p1, p2):
            return (p1[0]-p2[0])**2 + (p1[1]-p2[1])**2

        def frame_thread_run(success: Event):
            detector = dlib.get_frontal_face_detector()
            while not self.camera_running.is_set():
                try:
                    ret, img = cap.read()
                    if ret:
                        img = img.copy()
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        img = cv2.flip(img, 1)
                        img = imutils.resize(img, width=500)

                        # Detect face bounding box
                        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        rect = detector(gray, 1)
                        h, w, c = img.shape
                        t_size = w/5  # target size
                        if len(rect) > 0:
                            (x, y, x_d, y_d) = face_utils.rect_to_bb(rect[0])
                            img = cv2.rectangle(img, (x, y), (x+x_d, y+y_d), (255, 0, 0), 2)
                            rect_center = (x+int(x_d/2), y+int(y_d/2))
                            img = cv2.circle(img, rect_center, 1, (255, 0, 0), -1)
                            if x_d >= t_size and distance2(rect_center, (int(w/2), int(h/2))) < t_size**2:
                                self.camera_finish_button.setEnabled(True)
                                success.set()

                        # Draw target box
                        img = cv2.rectangle(img, (int((w-t_size)/2), int((h-t_size)/2)),
                                            (int((w+t_size)/2), int((h+t_size)/2)), (0, 0, 255), 2)
                        img = cv2.circle(img, (int(w/2), int(h/2)), 1, (0, 0, 255), -1)
                        img = imutils.resize(img, height=int(self.camera_label.height()))

                        # Draw in PyQT
                        h, w, c = img.shape
                        image = QImage(img.data, w, h, w*c, QImage.Format_RGB888)
                        pixmap = QPixmap.fromImage(image)
                        self.camera_label.setPixmap(pixmap)
                    else:
                        break
                except Exception as e:
                    self.log(str(e))
                    break
        success = Event()
        frame_thread = Thread(target=frame_thread_run, args=(success,))
        frame_thread.daemon = True
        frame_thread.start()

        def camera_finished_wrapper():
            if success.is_set() or self._skip_camera:
                self.camera_finished(frame_thread, cap)

        self.camera_finish_button.clicked.connect(camera_finished_wrapper)

    @proceedFunction(State.SET_CAMERA, State.CALIB_INSTRUCTION)
    def camera_finished(self, frame_thread, cap):
        self.camera_running.set()

        frame_thread.join()
        cap.release()
        # Start recording
        self.videoRecorder = VideoRecorder(self.camera)
        #self.videoRecorder.video_cap = cap
        self.videoRecorder.daemon = True
        self.videoRecorder.start()
        self.videoRecorder.execute()

    @proceedFunction(State.CALIB_INSTRUCTION, None)  # Next: CALIBRATION
    def set_instruction(self):
        self.widget.setCurrentWidget(self.calib_instruction_widget)

        def set_instruction_finished_wrapper():
            self.set_instruction_finished()

        self.start_calib_button.clicked.connect(set_instruction_finished_wrapper)

    @proceedFunction(State.CALIB_INSTRUCTION, State.CALIBRATION)
    def set_instruction_finished(self):
        self.widget.setCurrentWidget(self.calibration_widget)

    def paintEvent(self, event):
        qp = QPainter(self)
        if self._state == self.State.CALIBRATION:
            if 0 <= self.pos < len(self.calib_position_center):
                qp.setBrush(QColor(180, 0, 0))
                qp.setPen(QPen(QColor(180, self.calib_r, self.calib_r), 1))
                x, y = self.calib_position_center[self.pos]
                r = self.calib_r
                qp.drawEllipse(x-r, y-r, 2*r, 2*r)
        qp.end()

    @proceedFunction(State.CALIBRATION, None)  # Next: LECTURE_INSTRUCTION
    def calibrate(self):
        self.log("calibrate,%d" % self.pos)

        if self._skip_calib:
            self.pos = len(self.calib_position_center) + 1
            self.ellipse_button.hide()
            self.end_calibrate()
            return
        if self.clicks == 0:  # First click on the point
            self.videoRecorder.setFrameCount()
            self.clicks += 1
        elif self.videoRecorder.getFrameCount() < 15:
            self.clicks += 1
        else:
            self.clicks = 0
            self.pos += 1
        if self.pos >= len(self.calib_position_center):
            self.ellipse_button.hide()
            self.end_calibrate()
            return
        self.ellipse_button.move(self.calib_position_center[self.pos][0] - self.calib_r,
                                 self.calib_position_center[self.pos][1] - self.calib_r)
        self.update()

    @proceedFunction(State.CALIBRATION, State.LECTURE_INSTRUCTION)
    def end_calibrate(self):
        return

    @proceedFunction(State.LECTURE_INSTRUCTION, None)  # Next: DEMO_VIDEO
    def lecture_instruction(self):
        self.widget.setCurrentWidget(self.lecture_instruction_widget)
        self._state = self.State.DEMO_VIDEO

    def showDialog(self):
        self.media_player.pause()
        self.dialog.show()

    def closeDialog(self):
        self.dialog.close()
        self.media_player.play()

    def getVolume(self):
        return self.media_player.audio_get_volume()

    def setVolume(self, vol):
        self.media_player.audio_set_volume(vol)

    @proceedFunction([State.DEMO_VIDEO, State.MAIN_VIDEO], None)
    def start_video(self, demo=False):
        assert (self.videoIndex == 0 or not demo)

        # Initialize UI without starting the video
        if self.widget.currentWidget() != self.lecture_video_widget:
            self.widget.setCurrentWidget(self.lecture_video_widget)
            return

        self.next_button.setDisabled(True)

        if self.videoIndex >= len(self.videos):  # Finish (includes probeRunner cleanup)
            self.finishVideo()
            return
        elif self.videoIndex > 0:
            self.probeRunner.finish()

        self.media_player = self.instance.media_player_new()

        self.activityRecorder.finish(timeout=5.0)  # Stop recording keyboard & mouse
        self.activityRecorder.join()

        self.activityRecorder = ActivityRecorder(self.probeQueue, self.videos[self.videoIndex][0])
        self.activityRecorder.daemon = True
        self.activityRecorder.start()

        self.updater = UIUpdater(self.video_frame, self.media_player, self.time_label, self.time_text,
                                 self.video_index_label, (self.video_index_text % (self.videoIndex+2, len(self.videos))),
                                 self.next_button, is_end=self.videoIndex == len(self.videos)-1)
        self.updater.daemon = True
        self.updater.start()
        self.updater.signal.connect(self.finishVideo)

        self.probeRunner = ProbeRunner(self.probeQueue, self.media_player, self.videos[self.videoIndex][0], demo)
        self.probeRunner.daemon = True
        self.probeRunner.start()
        self.probeRunner.signal.connect(self.showDialog)
        self.probeRunner.ui_signal.connect(self.updater.alertProbeRunnerFinished)

        url = parsing.get_best_url(self.videos[self.videoIndex][1])
        # url = self.videos[self.videoIndex][1]
        self.log("url,%s" % url)
        try:
            media = self.instance.media_new(url)
            self.media_player.set_media(media)
            if sys.platform.startswith('linux'):  # for Linux using the X Server
                self.media_player.set_xwindow(self.video_frame.winId())
            elif sys.platform == "win32":  # for Windows
                self.media_player.set_hwnd(self.video_frame.winId())
            elif sys.platform == "darwin":  # for MacOS
                self.media_player.set_nsobject(int(self.video_frame.winId()))

            self.activityRecorder.execute()  # Start recording keyboard & mouse
            self.probeRunner.execute()  # Start sound player
            self.updater.execute()  # Start UI updater
            self.video_frame.show()

            pw, ph = self.getScreenSize()
            #dpi = screen.physicalDotsPerInch()
            #full_screen = screen.size()
            #width_scale = float(full_screen.width())/960.0
            #height_scale = float(full_screen.height())/540.0
            width_scale = float(pw)/960.0
            height_scale = float(ph)/540.0
            scale = min(width_scale, height_scale)
            #self.log("Screen resolution: %d x %d" %(full_screen.width(), full_screen.height()))
            #self.log("Width scale: %f\nHeight scale: %f\nFinalized scale: %f" %(width_scale, height_scale, scale))
            #self.media_player.video_set_scale(min(float(full_screen.width())/960.0, float(full_screen.height())/540.0))
            self.media_player.video_set_scale(scale)
            if self.media_player.play() < 0:  # Failed to play the media
                self.log("play,%s,Fail" % self.videos[self.videoIndex][0])
            else:
                self.log("play,%s,Start" % self.videos[self.videoIndex][0])
                
                while(self.media_player.get_state() != vlc.State.Playing):
                    time.sleep(0.1)
                self.showFullScreen()
        except Exception as e:
            self.log("play,%s,Fail,%s" % (self.videos[self.videoIndex][0], str(e)))
            self.next_button.setEnabled(True)
        finally:
            self.videoIndex += 1
            self._state = self.State.MAIN_VIDEO

    def getScreenSize(self):
        if sys.platform == 'darwin':
            from AppKit import NSScreen, NSDeviceSize, NSDeviceResolution
            from Quartz import CGDisplayScreenSize
            screen = NSScreen.mainScreen()
            description = screen.deviceDescription()
            pw, ph = description[NSDeviceSize].sizeValue()
            rx, ry = description[NSDeviceResolution].sizeValue()
            mmw, mmh = CGDisplayScreenSize(description["NSScreenNumber"])
            scaleFactor = screen.backingScaleFactor()
            pw *= scaleFactor
            ph *= scaleFactor
            self.log(f"display: {mmw:.1f}×{mmh:.1f} mm; {pw:.0f}×{ph:.0f} pixels; {rx:.0f}×{ry:.0f} dpi")
            return pw, ph
        else:
            return self.rect().width(), self.rect().height()


    @proceedFunction(State.MAIN_VIDEO, State.FINISH)
    def finishVideo(self):
        self.probeRunner.finish(timeout=5.0)
        self.probeRunner.terminate()
        self.updater.terminate()
        return

    def final(self):
        self.finish_label.setText(self.finish_text)
        self.widget.setCurrentWidget(self.finish_widget)


if __name__ == '__main__':
    if not os.path.exists('output'):
        os.mkdir('output')

    with open('./output/stdout.txt', 'w', buffering=1, encoding='UTF-8') as stdout:
        sys.stdout = stdout

        with open('./output/stderr.txt', 'w', buffering=1, encoding='UTF-8') as stderr:
            sys.stderr = stderr

            # Pyinstaller fix
            freeze_support()

            # PyQT
            app = QApplication(sys.argv)
            font = QFont("Roboto")
            font.setBold(True)
            font.setPixelSize(20)
            app.setFont(font)
            ex = ExpApp()
            sys.exit(app.exec_())
