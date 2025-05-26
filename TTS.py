import io, logging, asyncio, re
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, Response, render_template, jsonify
from edge_tts import Communicate, exceptions as edgetts_exceptions

app = Flask(__name__, template_folder="templates")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cấu hình
VOICES = {
    'female': 'vi-VN-HoaiMyNeural',
    'male':   'vi-VN-NamMinhNeural'
}
DEFAULT_VOICE = VOICES['female']
CHUNK_SIZE    = 100    # nhỏ đi cho nhanh chunk đầu
MAX_WORKERS   = 6      # song song
executor      = ThreadPoolExecutor(max_workers=MAX_WORKERS)

def split_chunks(text):
    """Chia text thành mảng ≤ CHUNK_SIZE, cắt sau dấu câu ưu tiên."""
    parts = re.split(r'(?<=[\.\!\?])\s+', text)
    chunks, cur = [], ""
    for p in parts:
        if len(cur) + len(p) + 1 <= CHUNK_SIZE:
            cur = (cur + " " + p).strip()
        else:
            if cur: chunks.append(cur)
            cur = p
    if cur: chunks.append(cur)
    return chunks

async def synthesize_async(chunk, voice):
    """Sinh 1 chunk async, trả về bytes MP3."""
    buf = io.BytesIO()
    comm = Communicate(chunk, voice)
    async for msg in comm.stream():
        if msg["type"] == "audio":
            buf.write(msg["data"])
    return buf.getvalue()

def synthesize_sync(chunk, voice):
    """Gọi async synth ở sync context."""
    return asyncio.run(synthesize_async(chunk, voice))

@app.route("/")
def index():
    return render_template("TTS.html")

@app.route("/api/tts")
def api_tts():
    text = (request.args.get("text") or "").strip()
    voice = request.args.get("voice", DEFAULT_VOICE)
    if not text or voice not in VOICES.values():
        return jsonify({"error":"Invalid input"}), 400

    chunks = split_chunks(text)
    logger.info(f"Synthesizing in {len(chunks)} chunks (size≤{CHUNK_SIZE})")

    def generate():
        # 1) Synthesize chunk đầu ngay
        first = chunks[0]
        try:
            data0 = synthesize_sync(first, voice)
            yield data0
        except Exception as e:
            logger.exception("Error in first chunk")
        
        # 2) Song song hóa các chunk sau
        rest = chunks[1:]
        futures = [executor.submit(synthesize_sync, c, voice) for c in rest]
        # 3) Lần lượt đợi và yield
        for fut in futures:
            try:
                data = fut.result()
                yield data
            except Exception:
                logger.exception("Error in later chunk")

    # Trả về stream MP3 progressive
    return Response(generate(), mimetype="audio/mpeg")

if __name__ == "__main__":
    app.run(debug=True, threaded=True)
