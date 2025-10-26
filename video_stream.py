# modules/video_stream.py
import cv2
import time

class VideoCamera:
    def __init__(self, url, backend=None):
        self.url = url
        if backend is None and self.url.startswith("rtsp://"):
            backend = cv2.CAP_FFMPEG
        self.backend = backend if backend is not None else 0
        self.video = None
        self._open()

    def _open(self):
        if self.video is not None:
            try:
                self.video.release()
            except Exception:
                pass
        self.video = cv2.VideoCapture(self.url, self.backend)
        self.video.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _ensure_open(self):
        if self.video is None or not self.video.isOpened():
            self._open()

    def __del__(self):
        try:
            if self.video is not None:
                self.video.release()
        except Exception:
            pass

    def get_frame(self):
        self._ensure_open()
        ok, frame = self.video.read()
        if not ok or frame is None:
            time.sleep(0.08)
            self._open()
            ok, frame = self.video.read()
            if not ok or frame is None:
                return None
        ok, jpeg = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        return jpeg.tobytes()
