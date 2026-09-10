import os
import re
import uuid
import shutil
from urllib.parse import urlparse

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

import yt_dlp

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None


# ============================================================
# APP
# ============================================================

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = "/tmp/rajput-downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_QUALITY = 2160


# ============================================================
# ALLOWED HOSTS
# ============================================================

ALLOWED_HOSTS = (
    "tiktok.com",
    "vt.tiktok.com",
    "vm.tiktok.com",

    "instagram.com",

    "facebook.com",
    "fb.watch",

    "youtube.com",
    "youtu.be",
)


# ============================================================
# HELPERS
# ============================================================

def clean_url(url):
    if not url:
        return ""

    url = str(url).strip()

    # Remove surrounding quotes
    url = url.strip("\"'")

    # Remove accidental spaces/newlines
    url = url.replace("\n", "").replace("\r", "").strip()

    return url


def hostname(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def platform_from_url(url):
    host = hostname(url)

    if (
        host == "tiktok.com"
        or host.endswith(".tiktok.com")
    ):
        return "tiktok"

    if (
        host == "instagram.com"
        or host.endswith(".instagram.com")
    ):
        return "instagram"

    if (
        host == "facebook.com"
        or host.endswith(".facebook.com")
        or host == "fb.watch"
    ):
        return "facebook"

    if (
        host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtu.be"
    ):
        return "youtube"

    return "unknown"


def allowed_url(url):
    host = hostname(url)

    if not host:
        return False

    return any(
        host == domain
        or host.endswith("." + domain)
        for domain in ALLOWED_HOSTS
    )


def is_tiktok_short_url(url):
    host = hostname(url)

    return host in (
        "vt.tiktok.com",
        "vm.tiktok.com",
    )


def safe_filename(name):
    if not name:
        return "rajput-video"

    name = re.sub(
        r'[\\/:*?"<>|]+',
        "",
        str(name)
    )

    name = re.sub(
        r"\s+",
        " ",
        name
    ).strip()

    return name[:150] or "rajput-video"


def quality_format(quality):
    try:
        quality = int(quality)
    except Exception:
        quality = 1080

    quality = max(
        144,
        min(quality, MAX_QUALITY)
    )

    return (
        f"bestvideo[height<={quality}]+bestaudio/"
        f"best[height<={quality}]/best"
    )


# ============================================================
# TIKTOK SHORT URL RESOLVER
# ============================================================

def resolve_tiktok_url(url):
    """
    Convert:
        https://vt.tiktok.com/xxxxx/
        https://vm.tiktok.com/xxxxx/

    into the final TikTok webpage URL.

    If resolution fails, return the original URL.
    """

    url = clean_url(url)

    if not is_tiktok_short_url(url):
        return url

    if curl_requests is None:
        return url

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 10; K) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Mobile Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,"
                "image/webp,*/*;q=0.8"
            ),
        }

        response = curl_requests.get(
            url,
            headers=headers,
            impersonate="chrome",
            allow_redirects=True,
            timeout=20,
        )

        final_url = clean_url(
            str(response.url)
        )

        if final_url:
            return final_url

    except Exception:
        pass

    return url


# ============================================================
# YT-DLP OPTIONS
# ============================================================

def ytdlp_options():
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,

        # Browser impersonation
        "impersonate": "chrome",

        # Network retries
        "retries": 5,
        "fragment_retries": 5,

        "socket_timeout": 30,

        # HTTP headers
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 10; K) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Mobile Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    # EJS remote component
    options["remote_components"] = {
        "ejs": ["github"]
    }

    return options


def tiktok_options():
    options = ytdlp_options()

    options["extractor_args"] = {
        "tiktok": {
            "api_hostname": [
                "api16-normal-c-useast1a.tiktokv.com"
            ]
        }
    }

    return options


def get_options(url):
    platform = platform_from_url(url)

    if platform == "tiktok":
        return tiktok_options()

    return ytdlp_options()


# ============================================================
# EXTRACT INFO
# ============================================================

def extract_video_info(url):
    """
    Resolve TikTok short URLs and then use yt-dlp.
    """

    original_url = clean_url(url)

    resolved_url = resolve_tiktok_url(
        original_url
    )

    platform = platform_from_url(
        resolved_url
    )

    # If short URL resolution failed,
    # still use original TikTok URL.
    if platform == "unknown":
        platform = platform_from_url(
            original_url
        )

    options = get_options(
        resolved_url
    )

    options["skip_download"] = True

    with yt_dlp.YoutubeDL(options) as ydl:

        info = ydl.extract_info(
            resolved_url,
            download=False
        )

    return (
        info,
        resolved_url,
        platform
    )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return jsonify({
        "name": "RAJPUT Multi-Platform Downloader API",
        "status": "online",
        "version": "4.0",
        "yt_dlp": yt_dlp.version.__version__,
        "platforms": [
            "TikTok",
            "Instagram",
            "Facebook",
            "YouTube"
        ],
        "tiktok_short_links": True
    })


# ============================================================
# STATUS
# ============================================================

@app.route("/api/status")
def api_status():

    return jsonify({
        "success": True,
        "status": "online",
        "service": "RAJPUT Multi-Platform Downloader",
        "version": "4.0",
        "yt_dlp": yt_dlp.version.__version__,
        "max_quality": MAX_QUALITY
    })


# ============================================================
# INFO
# ============================================================

@app.route(
    "/api/info",
    methods=["GET", "POST"]
)
def video_info():

    # --------------------------------------------------------
    # GET / POST URL
    # --------------------------------------------------------

    if request.method == "POST":

        data = request.get_json(
            silent=True
        ) or {}

        url = data.get(
            "url",
            ""
        )

    else:

        url = request.args.get(
            "url",
            ""
        )

    url = clean_url(url)

    # --------------------------------------------------------
    # VALIDATE
    # --------------------------------------------------------

    if not url:

        return jsonify({
            "success": False,
            "error": "URL is required"
        }), 400

    if not allowed_url(url):

        return jsonify({
            "success": False,
            "error": "Unsupported URL"
        }), 400

    platform = platform_from_url(
        url
    )

    # --------------------------------------------------------
    # EXTRACT
    # --------------------------------------------------------

    try:

        (
            info,
            resolved_url,
            detected_platform
        ) = extract_video_info(url)

        if not info:

            raise Exception(
                "Video information was not returned."
            )

        platform = detected_platform or platform

        # ----------------------------------------------------
        # FORMATS
        # ----------------------------------------------------

        formats = []

        for fmt in info.get(
            "formats",
            []
        ):

            height = fmt.get(
                "height"
            )

            if not height:
                continue

            try:
                height = int(height)
            except Exception:
                continue

            if height > MAX_QUALITY:
                continue

            formats.append({
                "format_id": fmt.get(
                    "format_id"
                ),
                "height": height,
                "ext": fmt.get(
                    "ext"
                ),
                "vcodec": fmt.get(
                    "vcodec"
                ),
                "acodec": fmt.get(
                    "acodec"
                ),
                "filesize": fmt.get(
                    "filesize"
                )
            })

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        return jsonify({
            "success": True,
            "platform": platform,

            "id": info.get(
                "id"
            ),

            "title": (
                info.get("title")
                or "RAJPUT Video"
            ),

            "thumbnail": info.get(
                "thumbnail"
            ),

            "duration": info.get(
                "duration"
            ),

            "uploader": info.get(
                "uploader"
            ),

            "webpage_url": (
                info.get(
                    "webpage_url"
                )
                or resolved_url
                or url
            ),

            "original_url": url,

            "resolved_url": (
                resolved_url
                or url
            ),

            "formats": formats
        })

    except Exception as e:

        error_message = str(e)

        return jsonify({
            "success": False,
            "platform": platform,
            "error": error_message,
            "message": (
                "Video info nahi mili. "
                "TikTok link public hona chahiye."
            )
        }), 500


# ============================================================
# DOWNLOAD
# ============================================================

@app.route(
    "/api/download",
    methods=["POST"]
)
def download_video():

    data = request.get_json(
        silent=True
    ) or {}

    url = clean_url(
        data.get(
            "url",
            ""
        )
    )

    # --------------------------------------------------------
    # VALIDATE URL
    # --------------------------------------------------------

    if not url:

        return jsonify({
            "success": False,
            "error": "URL is required"
        }), 400

    if not allowed_url(url):

        return jsonify({
            "success": False,
            "error": "Unsupported URL"
        }), 400

    # --------------------------------------------------------
    # RESOLVE TIKTOK SHORT URL
    # --------------------------------------------------------

    resolved_url = resolve_tiktok_url(
        url
    )

    platform = platform_from_url(
        resolved_url
    )

    if platform == "unknown":

        platform = platform_from_url(
            url
        )

    # --------------------------------------------------------
    # QUALITY
    # --------------------------------------------------------

    try:

        quality = int(
            data.get(
                "quality",
                1080
            )
        )

    except Exception:

        quality = 1080

    quality = max(
        144,
        min(
            quality,
            MAX_QUALITY
        )
    )

    # --------------------------------------------------------
    # MODE
    # --------------------------------------------------------

    mode = str(
        data.get(
            "mode",
            "video"
        )
    ).lower()

    # --------------------------------------------------------
    # JOB DIRECTORY
    # --------------------------------------------------------

    job_id = uuid.uuid4().hex

    job_dir = os.path.join(
        DOWNLOAD_DIR,
        job_id
    )

    os.makedirs(
        job_dir,
        exist_ok=True
    )

    # ========================================================
    # VIDEO
    # ========================================================

    if mode != "audio":

        output = os.path.join(
            job_dir,
            "%(title).150s.%(ext)s"
        )

        options = get_options(
            resolved_url
        )

        options.update({

            "format": quality_format(
                quality
            ),

            "outtmpl": output,

            "merge_output_format": "mp4",

            "postprocessors": [
                {
                    "key":
                        "FFmpegVideoConvertor",

                    "preferedformat":
                        "mp4"
                }
            ]
        })

        try:

            with yt_dlp.YoutubeDL(
                options
            ) as ydl:

                ydl.extract_info(
                    resolved_url,
                    download=True
                )

            # ------------------------------------------------
            # FIND FILES
            # ------------------------------------------------

            files = []

            for filename in os.listdir(
                job_dir
            ):

                path = os.path.join(
                    job_dir,
                    filename
                )

                if os.path.isfile(
                    path
                ):
                    files.append(
                        path
                    )

            if not files:

                raise Exception(
                    "No video file was created."
                )

            # ------------------------------------------------
            # PREFER MP4
            # ------------------------------------------------

            mp4_files = [
                f
                for f in files
                if f.lower().endswith(
                    ".mp4"
                )
            ]

            if mp4_files:

                final_file = max(
                    mp4_files,
                    key=os.path.getsize
                )

            else:

                final_file = max(
                    files,
                    key=os.path.getsize
                )

            # ------------------------------------------------
            # SEND FILE
            # ------------------------------------------------

            return send_file(

                final_file,

                as_attachment=True,

                download_name=os.path.basename(
                    final_file
                ),

                mimetype="video/mp4"
            )

        except Exception as e:

            shutil.rmtree(
                job_dir,
                ignore_errors=True
            )

            return jsonify({
                "success": False,
                "platform": platform,
                "error": str(e)
            }), 500

    # ========================================================
    # AUDIO / MP3
    # ========================================================

    output = os.path.join(
        job_dir,
        "%(title).150s.%(ext)s"
    )

    options = get_options(
        resolved_url
    )

    options.update({

        "format":
            "bestaudio/best",

        "outtmpl":
            output,

        "postprocessors": [
            {
                "key":
                    "FFmpegExtractAudio",

                "preferredcodec":
                    "mp3",

                "preferredquality":
                    "320"
            }
        ]
    })

    try:

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            ydl.extract_info(
                resolved_url,
                download=True
            )

        # ----------------------------------------------------
        # FIND FILES
        # ----------------------------------------------------

        files = []

        for filename in os.listdir(
            job_dir
        ):

            path = os.path.join(
                job_dir,
                filename
            )

            if os.path.isfile(
                path
            ):

                files.append(
                    path
                )

        mp3_files = [
            f
            for f in files
            if f.lower().endswith(
                ".mp3"
            )
        ]

        if not mp3_files:

            raise Exception(
                "MP3 file was not created."
            )

        final_file = max(
            mp3_files,
            key=os.path.getsize
        )

        return send_file(

            final_file,

            as_attachment=True,

            download_name=os.path.basename(
                final_file
            ),

            mimetype="audio/mpeg"
        )

    except Exception as e:

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )

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
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            8080
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
)
