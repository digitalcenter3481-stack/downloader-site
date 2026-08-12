import os
import re
import glob
import uuid
import shutil
import subprocess
from urllib.parse import urlparse

from flask import Flask, request, jsonify, send_file, send_from_directory
import yt_dlp


app = Flask(__name__)

DOWNLOAD_DIR = "/tmp/downloads"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# -------------------------------------------------
# Allowed platforms
# -------------------------------------------------

ALLOWED_DOMAINS = {
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",

    "tiktok.com",

    "instagram.com",

    "facebook.com",
    "fb.watch",

    "x.com",
    "twitter.com",

    "reddit.com",

    "pinterest.com",
}


def is_allowed_url(url):
    """
    Allow only supported social-media domains.
    """

    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        hostname = (parsed.hostname or "").lower()

        if not hostname:
            return False

        for domain in ALLOWED_DOMAINS:
            if hostname == domain or hostname.endswith("." + domain):
                return True

        return False

    except Exception:
        return False


# -------------------------------------------------
# Home page
# -------------------------------------------------

@app.get("/")
def home():
    return send_from_directory(".", "index.html")


# -------------------------------------------------
# Health check
# -------------------------------------------------

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "downloader-site"
    })


# -------------------------------------------------
# Download endpoint
# -------------------------------------------------

@app.post("/api/download")
def download():

    data = request.get_json(silent=True) or {}

    url = data.get("url", "").strip()

    if not url:
        return jsonify({
            "success": False,
            "error": "ضع رابط الفيديو أولاً."
        }), 400

    if len(url) > 2000:
        return jsonify({
            "success": False,
            "error": "الرابط طويل جدًا."
        }), 400

    if not is_allowed_url(url):
        return jsonify({
            "success": False,
            "error": "الرابط غير مدعوم. استخدم YouTube أو TikTok أو Instagram أو Facebook أو X أو Reddit أو Pinterest."
        }), 400

    job_id = uuid.uuid4().hex

    output_template = os.path.join(
        DOWNLOAD_DIR,
        job_id + ".%(ext)s"
    )

    ydl_opts = {
        "outtmpl": output_template,

        # Best quality with audio, then fallback to best single file
        "format": "bv*+ba/b",

        "merge_output_format": "mp4",

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,

        "retries": 2,

        "fragment_retries": 2,

        "socket_timeout": 30,

        # Keep filenames safe
        "restrictfilenames": True,

        # Use FFmpeg installed inside Docker
        "ffmpeg_location": "/usr/bin/ffmpeg",

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            )
        }
    }

    try:

        # Download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            title = info.get("title") or "video"

        # Find generated file
        files = glob.glob(
            os.path.join(DOWNLOAD_DIR, job_id + ".*")
        )

        # Remove temporary files if any
        files = [
            f for f in files
            if not f.endswith(".part")
        ]

        if not files:
            return jsonify({
                "success": False,
                "error": "لم يتم العثور على الملف بعد التحميل."
            }), 500

        # Prefer mp4
        mp4_files = [
            f for f in files
            if f.lower().endswith(".mp4")
        ]

        if mp4_files:
            file_path = mp4_files[0]
        else:
            file_path = files[0]

        extension = os.path.splitext(file_path)[1]

        safe_title = re.sub(
            r'[\\/*?:"<>|]+',
            "_",
            title
        ).strip()

        if not safe_title:
            safe_title = "download"

        filename = safe_title[:100] + extension

        response = send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype="video/mp4"
            if extension.lower() == ".mp4"
            else "application/octet-stream"
        )

        # Delete downloaded file after response
        @response.call_on_close
        def cleanup():

            try:
                if os.path.exists(file_path):
                    os.remove(file_path)

                # Remove related temporary files
                for f in glob.glob(
                    os.path.join(
                        DOWNLOAD_DIR,
                        job_id + ".*"
                    )
                ):
                    try:
                        os.remove(f)
                    except Exception:
                        pass

            except Exception:
                pass

        return response

    except yt_dlp.utils.DownloadError as e:

        # Cleanup
        for f in glob.glob(
            os.path.join(DOWNLOAD_DIR, job_id + ".*")
        ):
            try:
                os.remove(f)
            except Exception:
                pass

        error_text = str(e)

        return jsonify({
            "success": False,
            "error": (
                "تعذر تحميل هذا الرابط. "
                "قد يكون الفيديو خاصًا أو محميًا أو غير متاح حاليًا."
            ),
            "details": error_text[-500:]
        }), 400

    except Exception as e:

        for f in glob.glob(
            os.path.join(DOWNLOAD_DIR, job_id + ".*")
        ):
            try:
                os.remove(f)
            except Exception:
                pass

        return jsonify({
            "success": False,
            "error": "حدث خطأ أثناء التحميل.",
            "details": str(e)[-500:]
        }), 500


# -------------------------------------------------
# Start server
# -------------------------------------------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port
    )
