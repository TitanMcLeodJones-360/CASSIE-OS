"""Recognize an utterance on TitanGame and discard its audio after transcription."""
import base64
from functools import lru_cache
import json
from pathlib import Path
import site
import sys
import threading


ROOT = Path("/opt/cassie-os/speech")
MODEL = ROOT / "vosk-model-small-en-us-0.15"
PACKAGES = ROOT / "runtime" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
MAX_PCM = 16_000 * 2 * 11
LOCK = threading.Lock()


def available():
    return (PACKAGES / "vosk").is_dir() and (MODEL / "am" / "final.mdl").is_file()


@lru_cache(maxsize=1)
def recognizer_assets():
    if not available():
        raise RuntimeError("Local speech recognition needs the desktop voice update.")
    site.addsitedir(str(PACKAGES))
    try:
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        return KaldiRecognizer, Model(str(MODEL))
    except Exception as error:  # Vosk raises a plain Exception when its model is invalid.
        raise RuntimeError("The local speech model could not load. Run the desktop update again.") from error


def transcribe(encoded):
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_PCM + 2) // 3):
        raise ValueError("Use a microphone clip up to 11 seconds.")
    pcm = base64.b64decode(encoded, validate=True)
    if not pcm or len(pcm) % 2 or len(pcm) > MAX_PCM:
        raise ValueError("Invalid microphone audio.")
    if not LOCK.acquire(blocking=False):
        raise RuntimeError("CASSIE is processing another voice clip. Try again in a moment.")
    try:
        decoder, model = recognizer_assets()
        recognizer = decoder(model, 16_000)
        parts = []
        for offset in range(0, len(pcm), 8000):
            if recognizer.AcceptWaveform(pcm[offset:offset + 8000]):
                parts.append(json.loads(recognizer.Result()).get("text", ""))
        parts.append(json.loads(recognizer.FinalResult()).get("text", ""))
        return " ".join(part for part in parts if part).strip()
    finally:
        LOCK.release()
