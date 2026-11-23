"""Genesys Cloud Audio Connector (AudioHook protocol, version 2): the messages this server sends.

Genesys opens a WebSocket to the server. Text frames carry JSON control messages, binary frames
carry audio: PCMU (G.711 µ-law), 8 kHz, in frames of 1600 bytes (0.2 s).

  Genesys -> server: open, ping, close, paused, resumed, dtmf, update, error, playback_*
  server -> Genesys: opened, pong, closed, event (barge_in), disconnect

Every message has: version "2", type, seq (the sender's own counter), clientseq (the last seq
received from the other side), id (the session id from "open") and parameters.

Field names follow Genesys' public AudioHook protocol as implemented by Pipecat's Genesys
serializer and Genesys' DigitalOcean speech-to-speech connector, because Genesys' developer site
could not be reached while this was written. Check them against
https://developer.genesys.cloud/devapps/audiohook before going live.
"""
import json

VERSION = "2"
FRAME_BYTES = 1600            # 0.2 s of PCMU 8 kHz
BYTES_PER_SECOND = 8000
PROBE_ID = "00000000-0000-0000-0000-000000000000"


class Protocol:
    """Builds server messages with the right counters for one session."""

    def __init__(self):
        self.session_id = None
        self.server_seq = 0
        self.client_seq = 0

    def received(self, message: dict):
        """Call for every JSON message from Genesys, before answering it."""
        self.client_seq = message.get("seq", self.client_seq)
        if message.get("type") == "open":
            self.session_id = message.get("id")

    def _message(self, kind: str, parameters: dict = None) -> str:
        self.server_seq += 1
        return json.dumps({
            "version": VERSION,
            "type": kind,
            "seq": self.server_seq,
            "clientseq": self.client_seq,
            "id": self.session_id,
            "parameters": parameters or {},
        }, ensure_ascii=False)

    def opened(self, media: list) -> str:
        return self._message("opened", {"startPaused": False, "media": media})

    def pong(self) -> str:
        return self._message("pong")

    def closed(self, output_variables: dict = None) -> str:
        return self._message("closed", {"outputVariables": output_variables} if output_variables else {})

    def barge_in(self) -> str:
        """Tell Genesys the caller interrupted: it drops the bot audio it has queued."""
        return self._message("event", {"entities": [{"type": "barge_in", "data": {}}]})

    def disconnect(self, reason: str = "completed", info: str = "", output_variables: dict = None) -> str:
        """End the bot part of the call. Architect continues after the Call Audio Connector action
        and can read output_variables (all values strings)."""
        return self._message("disconnect", {
            "reason": reason,
            "info": info,
            "outputVariables": {k: "" if v is None else str(v) for k, v in (output_variables or {}).items()},
        })


def choose_media(offered: list):
    """Pick PCMU 8 kHz from what Genesys offers in "open". Returns (media entry, stereo?) or (None, False)."""
    for media in offered or []:
        if media.get("type", "audio") == "audio" and media.get("format") == "PCMU" and media.get("rate") == 8000:
            channels = media.get("channels") or ["external"]
            return media, len(channels) > 1
    return None, False


def caller_audio(frame: bytes, stereo: bool) -> bytes:
    """The caller's side of the audio. Stereo frames interleave external (caller) and internal."""
    return frame[0::2] if stereo else frame


def is_probe(open_message: dict) -> bool:
    """Genesys tests the connection with an all-zero conversation before real calls."""
    params = open_message.get("parameters", {})
    return params.get("conversationId") == PROBE_ID and (params.get("participant") or {}).get("id") == PROBE_ID
