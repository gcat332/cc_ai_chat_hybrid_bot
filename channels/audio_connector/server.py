"""Audio Connector server: Genesys Cloud calls connect here and talk to the Thai bot.

    pip install -r requirements-voice.txt
    export AUDIO_CONNECTOR_API_KEY='long-random-string'   # same value as in the Genesys integration
    export AZURE_SPEECH_KEY='...'  AZURE_SPEECH_REGION='southeastasia'
    python -m channels.audio_connector.server            # ws://0.0.0.0:8080/audiohook

Genesys reaches it only over public wss:// with a valid certificate. Either give this server the
certificate itself (no proxy needed):

    export TLS_CERT_FILE=/etc/letsencrypt/live/bot.example.com/fullchain.pem
    export TLS_KEY_FILE=/etc/letsencrypt/live/bot.example.com/privkey.pem
    python -m channels.audio_connector.server --port 443      # wss://bot.example.com/audiohook

or put it behind something that adds TLS (Cloudflare Tunnel, Caddy, a cloud load balancer...).
GET / answers "OK" for health checks.

    --fake-speech   no Azure: callers "speak" with text frames (for tests and local trials)
    --ai            answer questions the rules don't cover with Claude, as in the web chat
"""
import argparse
import asyncio
import hmac
import logging
import os
import ssl
from http import HTTPStatus

from websockets.asyncio.server import serve

from callcenter_bot import Bot, db

from .call import CallSession, Settings
from .speech import AzureSpeech, FakeSpeech

PATH = os.environ.get("AUDIO_CONNECTOR_PATH", "/audiohook")
log = logging.getLogger("audio_connector")


def tls_context(cert_file: str, key_file: str) -> ssl.SSLContext:
    """TLS for wss:// straight from this server. Use the full chain (e.g. Let's Encrypt
    fullchain.pem), or Genesys will not trust the certificate."""
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_file, key_file)
    return context


def make_server(speech, bot: Bot, api_key: str, host: str = "0.0.0.0", port: int = 8080,
                settings: Settings = None, tls: ssl.SSLContext = None):
    """Returns an un-started websockets server (use `async with`)."""

    def check(connection, request):
        path = request.path.split("?")[0]
        if path in ("/", "/health"):
            return connection.respond(HTTPStatus.OK, "OK\n")
        # Genesys may add the Connector ID after the base URI: /audiohook/<connector id>
        if path != PATH and not path.startswith(PATH + "/"):
            log.warning("refused a connection to %s: the integration's URI must end with %s", path, PATH)
            return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
        if not api_key:
            return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "Set AUDIO_CONNECTOR_API_KEY\n")
        received = request.headers.get("x-api-key", "")
        if not hmac.compare_digest(received.encode(), api_key.encode()):
            log.warning("refused a connection: wrong or missing x-api-key")
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Invalid API key\n")
        return None   # carry on with the WebSocket handshake

    async def handle(connection):
        await CallSession(connection, speech, bot, settings).run()

    # Audio frames are small (1600 bytes); compression only adds delay.
    return serve(handle, host, port, process_request=check, compression=None, max_size=2 ** 20, ssl=tls)


async def main_async(args):
    db.use_database(db.DEFAULT_PATH)
    if args.fake_speech:
        speech = FakeSpeech()
        log.warning("FAKE speech: for testing only, callers cannot really talk")
    else:
        speech = AzureSpeech()
    bot = Bot()
    if args.ai:
        from callcenter_bot.ai_fallback import make_claude_fallback
        bot = Bot(fallback=make_claude_fallback())
    api_key = os.environ.get("AUDIO_CONNECTOR_API_KEY", "")
    if not api_key:
        log.warning("AUDIO_CONNECTOR_API_KEY is not set: every call will be refused")
    cert = args.cert or os.environ.get("TLS_CERT_FILE")
    key = args.key or os.environ.get("TLS_KEY_FILE")
    tls = tls_context(cert, key) if cert and key else None
    async with make_server(speech, bot, api_key, args.host, args.port, tls=tls) as server:
        scheme = "wss" if tls else "ws"
        print(f"Audio Connector on {scheme}://{args.host}:{args.port}{PATH}  (database: {db.DEFAULT_PATH})")
        if not tls:
            print("No TLS: Genesys needs wss://. Set TLS_CERT_FILE and TLS_KEY_FILE, or put a TLS proxy in front.")
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Genesys Audio Connector for the Thai call-center bot")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    parser.add_argument("--fake-speech", action="store_true", help="no Azure: for tests and local trials")
    parser.add_argument("--ai", action="store_true", help="AI answers for questions the rules don't cover")
    parser.add_argument("--cert", help="TLS certificate chain (PEM), or set TLS_CERT_FILE")
    parser.add_argument("--key", help="TLS private key (PEM), or set TLS_KEY_FILE")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
