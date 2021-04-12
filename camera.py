import cv2
import pickle
import numpy as np

from utils.exit_after import exit_after


@exit_after(10)
def findCorners(gray):
    return cv2.findChessboardCorners(gray, (9, 6), None)


@exit_after(10)
def calculation(gray, corners, criteria, frame_copy, ret):
    cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
    # Draw and display the corners
    cv2.drawChessboardCorners(frame_copy, (9, 6), corners, ret)


def cam_calibrate(cam_idx, cap, cam_calib):

    # termination criteria
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

    # prepare object points, like (0,0,0), (1,0,0), (2,0,0) ....,(6,5,0)
    pts = np.zeros((6 * 9, 3), np.float32)
    pts[:, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2)

    # capture calibration frames
    obj_points = []  # 3d point in real world space
    img_points = []  # 2d points in image plane.
    frames = None
    while True:
        ret, frame = cap.read()
        frame_copy = frame.copy()

        corners = []
        if ret:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            retc, corners = findCorners(gray)
            if retc:
                calculation(gray, corners, criteria, frame_copy, ret)
                cv2.imshow('points', frame_copy)
                # s to save, c to continue, q to quit
                if cv2.waitKey(0) & 0xFF == ord('s'):
                    img_points.append(corners)
                    obj_points.append(pts)
                    frames = frame
                elif cv2.waitKey(0) & 0xFF == ord('c'):
                    continue
                elif cv2.waitKey(0) & 0xFF == ord('q'):
                    print("Calibrating camera...")
                    cv2.destroyAllWindows()
                    break

    # compute calibration matrices

    if frames is None:
        return

    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(obj_points, img_points, frames.shape[0:2], None, None)

    # check
    error = 0.0
    for i in range(len(obj_points)):
        proj_imgpoints, _ = cv2.projectPoints(obj_points[i], rvecs[i], tvecs[i], mtx, dist)
        error += (cv2.norm(img_points[i], proj_imgpoints, cv2.NORM_L2) / len(proj_imgpoints))
    print("Camera calibrated successfully, total re-projection error: %f" % (error / len(obj_points)))

    cam_calib['mtx'] = mtx
    cam_calib['dist'] = dist
    print("Camera parameters:")
    print(cam_calib)

    pickle.dump(cam_calib, open("calib_cam%d.pkl" % (cam_idx), "wb"))


cam_idx = 0

cam_cap = cv2.VideoCapture(cam_idx)
cam_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cam_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# calibrate camera
cam_calib = {'mtx': np.eye(3), 'dist': np.zeros((1, 5))}
print("Calibrate camera once. Print pattern.png, paste on a clipboard, show to camera and capture non-blurry images in which points are detected well.")
print("Press s to save frame, c to continue to next frame and q to quit collecting data and proceed to calibration.")
cam_calibrate(cam_idx, cam_cap, cam_calib)
cam_cap.release()
