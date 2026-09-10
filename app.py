from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import yt_dlp
import os
import uuid
import re

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = "/tmp/hd-downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_HEIGHT = 2160
ALLOWED_PLATFORMS = {
    "tiktok": ["tiktok.com"],
    "instagram": ["instagram.com"],
    "facebook": ["facebook.com", "fb.watch"],
    "youtube": ["youtube.com", "youtu.be"],
}

def detect_platform(url):
    u = url.lower()
    for name, domains in ALLOWED_PLATFORMS.items():
        if any(d in u for d in domains):
            return name
    return "unknown"

def clean_url(url):
    return url.strip()

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/status")
def status():
    return jsonify({
        "name": "Multi-Platform HD Video Downloader API",
        "status": "online",
        "max_quality": "2160p"
    })

@app.route("/api/info", methods=["POST"])
def info():
    data = request.get_json(silent=True) or {}
    url = clean_url(data.get("url", ""))
    if not url:
        return jsonify({"success": False, "error": "Video URL enter karo."}), 400

    platform = detect_platform(url)
    if platform == "unknown":
        return jsonify({
            "success": False,
            "error": "Sirf TikTok, Instagram, Facebook ya YouTube URL support hai."
        }), 400

    try:
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "extract_flat": False,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info_data = ydl.extract_info(url, download=False)

        heights = sorted({
            int(f["height"])
            for f in info_data.get("formats", [])
            if f.get("height") and int(f["height"]) <= MAX_HEIGHT
        }, reverse=True)

        return jsonify({
            "success": True,
            "platform": platform,
            "title": info_data.get("title", "Video"),
            "thumbnail": info_data.get("thumbnail", ""),
            "duration": info_data.get("duration", 0),
            "formats": heights
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/download", methods=["POST"])
def download():
    data = request.get_json(silent=True) or {}
    url = clean_url(data.get("url", ""))
    quality = str(data.get("quality", "best")).lower()
    mode = str(data.get("mode", "video")).lower()

    if not url:
        return jsonify({"success": False, "error": "Video URL enter karo."}), 400

    platform = detect_platform(url)
    if platform == "unknown":
        return jsonify({
            "success": False,
            "error": "Sirf TikTok, Instagram, Facebook ya YouTube URL support hai."
        }), 400

    try:
        if mode == "audio":
            job_id = uuid.uuid4().hex
            output_template = os.path.join(DOWNLOAD_DIR, job_id + ".%(ext)s")
            options = {
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                info_data = ydl.extract_info(url, download=True)
                downloaded = ydl.prepare_filename(info_data)

            audio_file = os.path.splitext(downloaded)[0] + ".mp3"
            if not os.path.exists(audio_file):
                candidates = [
                    os.path.join(DOWNLOAD_DIR, x)
                    for x in os.listdir(DOWNLOAD_DIR)
                    if x.startswith(job_id) and x.endswith(".mp3")
                ]
                if not candidates:
                    raise Exception("Audio file nahi mila.")
                audio_file = candidates[0]

            return send_file(
                audio_file,
                as_attachment=True,
                download_name="Song.mp3"
            )

        if quality.isdigit():
            requested = min(int(quality), MAX_HEIGHT)
            format_selector = (
                f"bestvideo[height<={requested}]+bestaudio/"
                f"best[height<={requested}]"
            )
        else:
            format_selector = "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best"

        job_id = uuid.uuid4().hex
        output_template = os.path.join(DOWNLOAD_DIR, job_id + ".%(ext)s")

        options = {
            "format": format_selector,
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "max_filesize": None,
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            info_data = ydl.extract_info(url, download=True)
            downloaded = ydl.prepare_filename(info_data)

        base_name = os.path.splitext(downloaded)[0]
        mp4_file = base_name + ".mp4"

        if os.path.exists(mp4_file):
            final_file = mp4_file
        elif os.path.exists(downloaded):
            final_file = downloaded
        else:
            candidates = [
                os.path.join(DOWNLOAD_DIR, x)
                for x in os.listdir(DOWNLOAD_DIR)
                if x.startswith(job_id)
            ]
            if not candidates:
                raise Exception("Downloaded file nahi mila.")
            final_file = candidates[0]

        return send_file(
            final_file,
            as_attachment=True,
            download_name="Video_4K.mp4"
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
