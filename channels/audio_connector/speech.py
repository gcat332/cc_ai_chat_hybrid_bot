"""Speech for the phone line: Thai speech recognition and Thai voice, both by Azure Speech.

Audio on a Genesys call is G.711 µ-law (PCMU), 8 kHz, mono. Azure reads and writes that format
directly, so no conversion is needed.

FakeSpeech stands in for Azure in tests and local trials (no key, no network): see its notes.
"""
import asyncio
import logging
import os
from xml.sax.saxutils import escape

log = logging.getLogger("audio_connector.speech")

# Words customers say often: Azure recognises them better when it knows them in advance.
PHRASES = [
    "ยอดค้างชำระ", "ยอดชำระขั้นต่ำ", "สินเชื่อบ้าน", "สินเชื่อส่วนบุคคล", "รีไฟแนนซ์",
    "ปิดบัญชีสินเชื่อ", "บัตรเครดิต", "เพิ่มวงเงิน", "ยกเลิกบัตร", "บัตรหาย", "ยอดเงินในบัญชี",
    "บัญชีเงินฝาก", "รายการที่ไม่ได้ทำ", "แจ้งปัญหา", "ร้องเรียน", "เลขบัตรประชาชน",
    "คุยกับเจ้าหน้าที่", "ช่องทางชำระเงิน", "เวลาทำการ", "ใช่", "ไม่ใช่", "ยกเลิก",
    "ขอบคุณ", "ลาก่อน", "ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า",
]


class AzureSpeech:
    """One instance per server. make_recognizer() gives one recognizer per call."""

    def __init__(self, key: str = None, region: str = None, language: str = None, voice: str = None,
                 rate: str = None, end_of_speech_ms: int = None):
        import azure.cognitiveservices.speech as speechsdk   # only needed when Azure is used
        self.sdk = speechsdk
        self.key = key or os.environ.get("AZURE_SPEECH_KEY", "")
        self.region = region or os.environ.get("AZURE_SPEECH_REGION", "southeastasia")
        self.language = language or os.environ.get("AZURE_SPEECH_LANGUAGE", "th-TH")
        self.voice = voice or os.environ.get("AZURE_SPEECH_VOICE", "th-TH-NiwatNeural")   # male: the bot says ครับ
        self.rate = rate or os.environ.get("AZURE_SPEECH_RATE", "0%")   # e.g. "-10%" slower, "+10%" faster
        # Silence that ends the caller's sentence. Thai callers pause inside sentences; 800 ms is safer than 500.
        self.end_of_speech_ms = end_of_speech_ms or int(os.environ.get("AZURE_SPEECH_END_SILENCE_MS", "800"))
        if not self.key:
            raise RuntimeError("Set AZURE_SPEECH_KEY (and AZURE_SPEECH_REGION) to use Azure Speech")

    def _config(self):
        config = self.sdk.SpeechConfig(subscription=self.key, region=self.region)
        config.speech_recognition_language = self.language
        return config

    # ---- listening ------------------------------------------------------------------------
    def make_recognizer(self, loop: asyncio.AbstractEventLoop, on_event):
        """on_event(kind, text) runs on `loop`: kind is "partial", "final" or "error"."""
        sdk = self.sdk
        config = self._config()
        config.set_property(sdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, str(self.end_of_speech_ms))
        fmt = sdk.audio.AudioStreamFormat(samples_per_second=8000, bits_per_sample=8, channels=1,
                                         wave_stream_format=sdk.audio.AudioStreamWaveFormat.MULAW)
        stream = sdk.audio.PushAudioInputStream(stream_format=fmt)
        recognizer = sdk.SpeechRecognizer(speech_config=config,
                                          audio_config=sdk.audio.AudioConfig(stream=stream))
        phrases = sdk.PhraseListGrammar.from_recognizer(recognizer)
        for phrase in PHRASES:
            phrases.addPhrase(phrase)

        def emit(kind, text):   # SDK callbacks run on SDK threads: hand over to the call's loop
            loop.call_soon_threadsafe(on_event, kind, text)

        recognizer.recognizing.connect(lambda e: e.result.text and emit("partial", e.result.text))
        recognizer.recognized.connect(
            lambda e: e.result.reason == sdk.ResultReason.RecognizedSpeech and e.result.text
            and emit("final", e.result.text))

        def canceled(e):
            details = getattr(e, "error_details", "") or str(getattr(e, "reason", ""))
            if details:
                emit("error", details)
        recognizer.canceled.connect(canceled)
        recognizer.start_continuous_recognition_async()
        return _AzureRecognizer(recognizer, stream)

    # ---- speaking -------------------------------------------------------------------------
    def _ssml(self, text: str) -> str:
        return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{self.language}">'
                f'<voice name="{self.voice}"><prosody rate="{escape(self.rate)}">{escape(text)}</prosody>'
                f'</voice></speak>')

    def _synthesize_blocking(self, text: str) -> bytes:
        sdk = self.sdk
        config = self._config()
        config.set_speech_synthesis_output_format(sdk.SpeechSynthesisOutputFormat.Raw8Khz8BitMonoMULaw)
        synthesizer = sdk.SpeechSynthesizer(speech_config=config, audio_config=None)
        result = synthesizer.speak_ssml_async(self._ssml(text)).get()
        if result.reason != sdk.ResultReason.SynthesizingAudioCompleted:
            details = getattr(result, "cancellation_details", None)
            raise RuntimeError(f"Azure text-to-speech failed: {getattr(details, 'error_details', result.reason)}")
        return result.audio_data

    async def synthesize(self, text: str) -> bytes:
        """Thai speech for `text` as PCMU 8 kHz bytes."""
        return await asyncio.get_running_loop().run_in_executor(None, self._synthesize_blocking, text)


class _AzureRecognizer:
    def __init__(self, recognizer, stream):
        self.recognizer, self.stream = recognizer, stream

    def push(self, pcmu: bytes):
        self.stream.write(pcmu)

    def close(self):
        try:
            self.stream.close()
            self.recognizer.stop_continuous_recognition_async()
        except Exception:
            log.debug("recognizer already stopped", exc_info=True)


# ---- Fake speech: tests and local trials without Azure --------------------------------------
class FakeSpeech:
    """What the caller "says" is an audio frame that starts with b"SAY:" followed by UTF-8 text.
    What the bot "says" is audio made of the bytes b"TTS:<text>\\n" padded with µ-law silence
    (0xFF) to `seconds_per_char` per character, so a test can read it back and timing is real."""

    SILENCE = b"\xff"

    def __init__(self, seconds_per_char: float = 0.0):
        self.seconds_per_char = seconds_per_char

    def make_recognizer(self, loop, on_event):
        return _FakeRecognizer(loop, on_event)

    async def synthesize(self, text: str) -> bytes:
        data = f"TTS:{text}\n".encode()
        target = int(len(text) * self.seconds_per_char * 8000)
        return data + self.SILENCE * max(0, target - len(data))


class _FakeRecognizer:
    def __init__(self, loop, on_event):
        self.loop, self.on_event = loop, on_event

    def push(self, pcmu: bytes):
        if pcmu.startswith(b"SAY:"):
            text = pcmu[4:].rstrip(FakeSpeech.SILENCE).decode()
            self.loop.call_soon(self.on_event, "partial", text)
            self.loop.call_soon(self.on_event, "final", text)

    def close(self):
        pass
