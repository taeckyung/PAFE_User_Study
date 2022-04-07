import cv2
import os, sys


def select_camera(path="test.png"):
    port_list = []
    for i in range(10):
        if sys.platform == "darwin":
            cap = cv2.VideoCapture(i)
        else:
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        try:
            success = 0
            if cap.isOpened():
                for _ in range(5):
                    ret, frame = cap.read()
                    if ret is True or frame is not None:
                        cv2.imwrite(path, frame)
                        success += 1
                    cv2.waitKey(1)
            if success == 5:
                port_list.append(i)
        finally:
            cap.release()
            cv2.destroyAllWindows()

    try:
        os.remove(path)
    except OSError:
        pass

    if len(port_list) == 0:
        return None
    else:
        return port_list[0]
