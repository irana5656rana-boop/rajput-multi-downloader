import os
import re
import uuid
import shutil
import tempfile
from urllib.parse import urlparse

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp


app = Flask(__name__)
CORS(app)

# ============================================================
# CONFIG
# ============================================================

DOWNLOAD_DIR = "/tmp/rajput-downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_QUALITY = 2160

ALLOWED_HOSTS = [
    "tiktok.com",
    "www.tiktok.com",
    "vt.tiktok.com",
    "vm.tiktok.com",
    "m.tiktok.com",
    "instagram.com",
    "www.instagram.com",
    "facebook.com",
    "www.facebook.com",
    "fb.watch",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "m.youtube.com",
]


# ============================================================
# HELPERS
# ============================================================

def clean_url(url):
    if not url:
        return ""

    url = url.strip()

    # Remove surrounding quotes
    url = url.strip("\"'")

    return url


def get_hostname(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def detect_platform(url):
    host = get_hostname(url)

    if "tiktok.com" in host:
        return "tiktok"

    if "instagram.com" in host:
        return "instagram"

    if "facebook.com" in host or host == "fb.watch":
        return "facebook"

    if "youtube.com" in host or host == "youtu.be":
        return "youtube"

    return "unknown"


def is_allowed_url(url):
    host = get_hostname(url)

    if not host:
        return False

    return any(
        host == allowed or host.endswith("." + allowed)
        for allowed in ALLOWED_HOSTS
    )


def safe_filename(name):
    if not name:
        name = "rajput-video"

    name = re.sub(r'[\\/:*?"<>|]+', "", name)
    name = re.sub(r"\s+", " ", name).strip()

    if len(name) > 150:
        name = name[:150]

    return name or "rajput-video"


def get_video_format(quality):
    try:
        quality = int(quality)
    except Exception:
        quality = 1080

    quality = min(max(quality, 144), MAX_QUALITY)

    return (
        f"bestvideo[height<={quality}]+bestaudio/"
        f"best[height<={quality}]/best"
    )


def base_ydl_options():
    """
    Common yt-dlp options.
    """

    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,

        # Browser-like request handling
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },

        # Try browser impersonation where available.
        "extractor_args": {
            "generic": {
                "impersonate": ["chrome"]
            }
        },

        "retries": 3,
        "fragment_retries": 3,

        "socket_timeout": 30,

        # Do not keep unnecessary files
        "overwrites": True,
    }


# ============================================================
# TIKTOK OPTIONS
# ============================================================

def tiktok_options():
    """
    TikTok-specific fallback configuration.

    yt-dlp supports TikTok's mobile API through app_info.
    We provide a fresh numeric device/install ID for each request.
    """

    iid = str(uuid.uuid4().int)[:19]
    device_id = str(uuid.uuid4().int)[:19]

    return {
        "tiktok": {
            "app_info": [
                f"{iid}/trill/34.1.2/340001/1180"
            ],
            "device_id": device_id,
        }
    }


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return jsonify({
        "name": "RAJPUT Multi-Platform Downloader API",
        "status": "online",
        "version": "2.0",
        "yt_dlp": yt_dlp.version.__version__,
        "platforms": [
            "TikTok",
            "Instagram",
            "Facebook",
            "YouTube"
        ]
    })


# ============================================================
# STATUS
# ============================================================

@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({
        "status": "online",
        "service": "RAJPUT Multi-Platform Downloader",
        "yt_dlp": yt_dlp.version.__version__,
        "max_quality": MAX_QUALITY
    })


# ============================================================
# VIDEO INFO
# ============================================================

@app.route("/api/info", methods=["GET", "POST"])
def info():

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        url = data.get("url", "")
    else:
        url = request.args.get("url", "")

    url = clean_url(url)

    if not url:
        return jsonify({
            "success": False,
            "error": "URL is required"
        }), 400

    if not is_allowed_url(url):
        return jsonify({
            "success": False,
            "error": "Unsupported URL"
        }), 400

    platform = detect_platform(url)

    options = base_ydl_options()
    options["skip_download"] = True

    # TikTok special configuration
    if platform == "tiktok":
        options["extractor_args"] = {
            **options.get("extractor_args", {}),
            **tiktok_options()
        }

    try:

        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(url, download=False)

        if not data:
            raise Exception("No information returned")

        formats = []

        for f in data.get("formats", []):
            height = f.get("height")

            if height:
                try:
                    height = int(height)
                except Exception:
                    continue

                if height <= MAX_QUALITY:
                    formats.append({
                        "format_id": f.get("format_id"),
                        "height": height,
                        "ext": f.get("ext"),
                        "filesize": f.get("filesize"),
                        "vcodec": f.get("vcodec"),
                        "acodec": f.get("acodec")
                    })

        return jsonify({
            "success": True,
            "platform": platform,
            "id": data.get("id"),
            "title": data.get("title") or "RAJPUT Video",
            "thumbnail": data.get("thumbnail"),
            "duration": data.get("duration"),
            "uploader": data.get("uploader"),
            "webpage_url": data.get("webpage_url") or url,
            "formats": formats
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "platform": platform,
            "error": str(e)
        }), 500


# ============================================================
# DOWNLOAD
# ============================================================

@app.route("/api/download", methods=["POST"])
def download():

    data = request.get_json(silent=True) or {}

    url = clean_url(data.get("url", ""))

    if not url:
        return jsonify({
            "success": False,
            "error": "URL is required"
        }), 400

    if not is_allowed_url(url):
        return jsonify({
            "success": False,
            "error": "Unsupported URL"
        }), 400

    platform = detect_platform(url)

    quality = data.get("quality", 1080)

    try:
        quality = int(quality)
    except Exception:
        quality = 1080

    quality = min(max(quality, 144), MAX_QUALITY)

    mode = str(data.get("mode", "video")).lower()

    job_id = uuid.uuid4().hex

    job_dir = os.path.join(
        DOWNLOAD_DIR,
        job_id
    )

    os.makedirs(job_dir, exist_ok=True)

    # ========================================================
    # VIDEO
    # ========================================================

    if mode != "audio":

        output_template = os.path.join(
            job_dir,
            "%(title).150s.%(ext)s"
        )

        options = base_ydl_options()

        options.update({
            "format": get_video_format(quality),
            "outtmpl": output_template,

            # Merge video + audio
            "merge_output_format": "mp4",

            # Prefer MP4-compatible streams
            "format_sort": [
                f"res:{quality}",
                "codec:h264",
                "ext:mp4",
                "hasaud"
            ],
        })

        if platform == "tiktok":
            options["extractor_args"] = {
                **options.get("extractor_args", {}),
                **tiktok_options()
            }

        try:

            with yt_dlp.YoutubeDL(options) as ydl:

                info_data = ydl.extract_info(
                    url,
                    download=True
                )

                title = safe_filename(
                    info_data.get("title")
                    or "rajput-video"
                )

            files = []

            for filename in os.listdir(job_dir):
                path = os.path.join(job_dir, filename)

                if os.path.isfile(path):
                    files.append(path)

            if not files:
                raise Exception(
                    "Video was extracted but no output file was created."
                )

            # Prefer mp4
            mp4_files = [
                f for f in files
                if f.lower().endswith(".mp4")
            ]

            final_file = (
                max(mp4_files, key=os.path.getsize)
                if mp4_files
                else max(files, key=os.path.getsize)
            )

            return send_file(
                final_file,
                as_attachment=True,
                download_name=os.path.basename(final_file),
                mimetype="video/mp4"
            )

        except Exception as e:

            shutil.rmtree(job_dir, ignore_errors=True)

            return jsonify({
                "success": False,
                "platform": platform,
                "error": str(e)
            }), 500

    # ========================================================
    # AUDIO / MP3
    # ========================================================

    output_template = os.path.join(
        job_dir,
        "%(title).150s.%(ext)s"
    )

    options = base_ydl_options()

    options.update({
        "format": "bestaudio/best",
        "outtmpl": output_template,

        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ],
    })

    if platform == "tiktok":
        options["extractor_args"] = {
            **options.get("extractor_args", {}),
            **tiktok_options()
        }

    try:

        with yt_dlp.YoutubeDL(options) as ydl:

            info_data = ydl.extract_info(
                url,
                download=True
            )

        files = []

        for filename in os.listdir(job_dir):
            path = os.path.join(job_dir, filename)

            if os.path.isfile(path):
                files.append(path)

        mp3_files = [
            f for f in files
            if f.lower().endswith(".mp3")
        ]

        if not mp3_files:
            raise Exception(
                "Audio was extracted but MP3 file was not created."
            )

        final_file = max(
            mp3_files,
            key=os.path.getsize
        )

        return send_file(
            final_file,
            as_attachment=True,
            download_name=os.path.basename(final_file),
            mimetype="audio/mpeg"
        )

    except Exception as e:

        shutil.rmtree(job_dir, ignore_errors=True)

        return jsonify({
            "success": False,
            "platform": platform,
            "error": str(e)
        }), 500


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Endpoint not found"
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "success": False,
        "error": "Internal server error"
    }), 500


# ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
