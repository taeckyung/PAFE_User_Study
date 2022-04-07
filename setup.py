# -*- coding: utf-8 -*-
from setuptools import setup

# name, description, version등의 정보는 일반적인 setup.py와 같습니다.
setup(name="Online-experiment",
      description="Online-experiment to analyze students' attention during lectures",
      version="0.0.1",
      # 설치시 의존성 추가
      setup_requires=["py2app"],
      app=["main.py"],
      options={
          "py2app": {
              "packages": ["vlc"],
              "includes": ["PyQt5",
                           "PyQt5.QtWidgets",
                           "Quartz",
                           "AppKit",
                           "pynput.keyboard._darwin",
                           "pynput.mouse._darwin",
                           "multiprocessing.Event",
                           "numpy.core.multiarray",
                           "youtube-dl",
                           "vlc",
                           "urlvalidator",
                           "imutils",
                           "dlib",
                           "scipy",
                           "numpy",
                           "cv2",
                           "pafy"]
          }
      })
