import subprocess
import json
import threading
import time
import logging


class XM5Monitor(threading.Thread):
    def __init__(self, description_match="WF-1000XM5"):
        super().__init__(daemon=True)
        self._stop = threading.Event()
        self.description_match = description_match
        self.connected = False
        self.lock = threading.Lock()

    def run(self):
        while not self._stop.is_set():
            try:
                out = subprocess.check_output(
                    ["pw-dump"],
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                )
                nodes = json.loads(out)
                found = False
                for obj in nodes:
                    props = obj.get("info", {}).get("props", {})
                    if props.get("media.class") == "Audio/Sink" and \
                       self.description_match in (props.get("node.description", "") or ""):
                        found = True
                        break
                with self.lock:
                    self.connected = found
            except subprocess.TimeoutExpired:
                logging.warning("XM5: pw-dump timeout")
            except Exception as e:
                logging.warning(f"XM5: pw-dump error: {e}")
                with self.lock:
                    self.connected = False
            finally:
                time.sleep(2.0)

    def stop(self):
        self._stop.set()

    def is_audio_ready(self):
        with self.lock:
            return self.connected
