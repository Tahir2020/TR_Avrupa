#!/usr/bin/env python3

import json
import re
import subprocess
import sys
import requests
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CONFIG_FILE = "config.json"
COOKIE_FILE = "cookies.txt"

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)


# ------------------------------------------------------------
# Config / helpers
# ------------------------------------------------------------
def load_config() -> Dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    if "channels" not in config or not isinstance(config["channels"], list):
        raise ValueError("config.json içinde 'channels' listesi bulunamadı.")

    if not config["channels"]:
        raise ValueError("config.json içinde kanal listesi boş.")

    config.setdefault("quality", "best[height<=1080][fps<=50]/best")
    config.setdefault("output_folder", "playlist")
    config.setdefault("output_playlist", "playlist.m3u8")
    config.setdefault("github_raw_base", "https://raw.githubusercontent.com/Tahir2020/TR_Avrupa/main")
    return config


def safe_filename(name: str) -> str:
    """Kanal adını güvenli dosya adına çevirir."""
    replacements = {
        "ç": "c", "Ç": "C",
        "ğ": "g", "Ğ": "G",
        "ı": "i", "İ": "I",
        "ö": "o", "Ö": "O",
        "ş": "s", "Ş": "S",
        "ü": "u", "Ü": "U",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)

    name = name.replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return f"{name or 'channel'}.m3u8"


def is_token_kanal(url: str) -> bool:
    return url == "token_kanal"


def is_eurostar_name(name: str) -> bool:
    lower = name.lower()
    return "euro_star" in lower or "eurostar" in lower or "star_avrupa" in lower


def is_show_turk_name(name: str) -> bool:
    lower = name.lower()
    return "show_turk" in lower or ("show" in lower and "turk" in lower)


def cookie_file_exists() -> bool:
    path = Path(COOKIE_FILE)
    return path.exists() and path.stat().st_size > 0


def load_netscape_cookies() -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    path = Path(COOKIE_FILE)

    if not path.exists():
        return cookies

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    name = parts[5].strip()
                    value = parts[6].strip()
                    if name:
                        cookies[name] = value
    except Exception as e:
        print(f"⚠️ Cookie okunamadı: {e}")

    return cookies


def print_yt_dlp_version() -> None:
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=20)
        version = result.stdout.strip() or result.stderr.strip()
        print(f"ℹ️ yt-dlp sürümü: {version}")
    except Exception as e:
        print(f"⚠️ yt-dlp sürümü okunamadı: {e}")


# ------------------------------------------------------------
# Token-based channels
# ------------------------------------------------------------
def get_eurostar_token() -> Optional[str]:
    """EuroStar stream URL al."""
    headers = {
        "User-Agent": CHROME_UA,
        "Accept": "text/html,application/xhtml+xml",
    }

    page_url = "https://www.eurostartv.com.tr/canli-izle"

    try:
        response = requests.get(page_url, headers=headers, timeout=15)
        html = response.text

        patterns = [
            r"var\s+liveUrl\s*=\s*'https://dygvideo\.dygdigital\.com/live/hls/staravrupa\?token=([a-f0-9]+)'",
            r"https://dygvideo\.dygdigital\.com/live/hls/staravrupa\?token=([a-f0-9]+)",
        ]

        token = None
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                token = match.group(1)
                break

        if not token:
            print("⚠️ EuroStar token sayfada bulunamadı")
            return None

        token_url = f"https://dygvideo.dygdigital.com/live/hls/staravrupa?token={token}"

        headers2 = {
            "Origin": "https://www.eurostartv.com.tr",
            "Referer": "https://www.eurostartv.com.tr/",
            "User-Agent": CHROME_UA,
        }

        response2 = requests.get(token_url, headers=headers2, allow_redirects=False, timeout=15)

        if response2.status_code in (301, 302, 303, 307, 308):
            master_url = response2.headers.get("Location")
            if not master_url:
                return None

            match = re.match(r"(.*/)live\.m3u8\?(.*)", master_url)
            if match:
                return f"{match.group(1)}live_1080p3000000kbps/index.m3u8?{match.group(2)}"

            return master_url

        if ".m3u8" in response2.text:
            return token_url

        print(f"⚠️ EuroStar beklenmeyen cevap: HTTP {response2.status_code}")
        return None

    except Exception as e:
        print(f"❌ EuroStar token hatası: {e}")
        return None


def get_show_turk_token() -> Optional[str]:
    """Show Türk stream URL al."""
    url = "https://www.showturk.com.tr/canli-yayin"
    patterns = [
        r"playlist\.m3u8\?e=(\d+)&st=([^\"\s&]+)",
        r"https?://[^\"'\s]+showturk[^\"'\s]+playlist\.m3u8\?e=(\d+)&st=([^\"'\s&]+)",
    ]

    headers = {
        "User-Agent": CHROME_UA,
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://www.showturk.com.tr/",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        html = response.text

        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                e, st = match.groups()
                return f"https://ciner-live.ercdn.net/showturk/playlist.m3u8?e={e}&st={st}&tv=1"

        print("⚠️ Show Türk token sayfada bulunamadı")
        return None

    except Exception as e:
        print(f"❌ Show Türk token hatası: {e}")
        return None


# ------------------------------------------------------------
# YouTube live handling
# ------------------------------------------------------------
def normalize_youtube_url(youtube_url: str) -> str:
    """YouTube URL'sini mümkün olduğunca standart watch URL'sine çevir."""
    youtube_url = youtube_url.strip()

    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/live/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
        r"(?:v=)([a-zA-Z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, youtube_url)
        if match:
            return f"https://www.youtube.com/watch?v={match.group(1)}"

    return youtube_url


def run_yt_dlp(cmd: List[str], label: str, timeout: int = 90) -> Tuple[str, str, int]:
    """yt-dlp komutunu çalıştır ve kısa debug yazdır."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if stderr:
            # Secret/cookie içeriği basmıyoruz; sadece hata mesajının başını gösteriyoruz.
            print(f"⚠️ yt-dlp stderr ({label}): {stderr[:500]}")

        return stdout, stderr, result.returncode
    except subprocess.TimeoutExpired:
        print(f"⏱️ yt-dlp zaman aşımı ({label})")
        return "", "timeout", 124
    except Exception as e:
        print(f"❌ yt-dlp çalıştırılamadı ({label}): {e}")
        return "", str(e), 1


def extract_first_http_url(text: str, prefer_m3u8: bool = True) -> Optional[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if prefer_m3u8:
        for line in lines:
            if line.startswith("http") and ".m3u8" in line:
                return line

    for line in lines:
        if line.startswith("http"):
            return line

    return None


def get_youtube_stream_url_from_json(youtube_url: str) -> Optional[str]:
    """yt-dlp -J ile JSON çekip HLS/m3u8 URL seç."""
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "--user-agent", CHROME_UA,
        "-J",
    ]

    if cookie_file_exists():
        cmd.extend(["--cookies", COOKIE_FILE])

    cmd.append(youtube_url)

    stdout, _, code = run_yt_dlp(cmd, "json", timeout=120)
    if code != 0 or not stdout:
        return None

    try:
        info = json.loads(stdout)
    except json.JSONDecodeError as e:
        print(f"⚠️ yt-dlp JSON okunamadı: {e}")
        return None

    # Bazen root url zaten m3u8 olur.
    root_url = info.get("url")
    if isinstance(root_url, str) and root_url.startswith("http") and ".m3u8" in root_url:
        print("✅ YouTube JSON root m3u8 bulundu")
        return root_url

    formats = info.get("formats") or []
    if not isinstance(formats, list):
        return None

    # HLS formatları tercih et. Önce yüksek çözünürlük, sonra yüksek bitrate.
    candidates = []
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        url = fmt.get("url")
        protocol = str(fmt.get("protocol", ""))
        ext = str(fmt.get("ext", ""))
        if not isinstance(url, str) or not url.startswith("http"):
            continue

        is_hls = ".m3u8" in url or "m3u8" in protocol or ext == "m3u8"
        if not is_hls:
            continue

        height = fmt.get("height") or 0
        tbr = fmt.get("tbr") or 0
        candidates.append((int(height or 0), float(tbr or 0), url))

    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        print("✅ YouTube JSON içinden HLS stream bulundu")
        return candidates[0][2]

    return None


def get_youtube_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    """
    YouTube canlı yayın URL al.

    Mantık:
    1) Önce -g ile m3u8/stream dene.
    2) Farklı player_client seçeneklerini dene.
    3) Son çare JSON içinden HLS formatı seç.
    4) Stderr'i logla ki gerçek hata GitHub Actions'ta görülsün.
    """
    youtube_url = normalize_youtube_url(youtube_url)

    if not cookie_file_exists():
        print("⚠️ cookies.txt yok veya boş. YouTube bazı yayınlarda bot/oturum hatası verebilir.")

    format_variants = [
        quality,
        "best[protocol=m3u8_native]/best[protocol=m3u8]/best",
        "best",
    ]

    client_variants = [
        "android",
        "ios",
        "web",
        "tv",
        "mweb",
    ]

    for client in client_variants:
        for fmt in format_variants:
            cmd = [
                "yt-dlp",
                "--no-warnings",
                "--no-playlist",
                "--user-agent", CHROME_UA,
                "--extractor-args", f"youtube:player_client={client}",
                "-f", fmt,
                "-g",
            ]

            if cookie_file_exists():
                cmd.extend(["--cookies", COOKIE_FILE])

            cmd.append(youtube_url)

            stdout, _, code = run_yt_dlp(cmd, f"{client}/{fmt}", timeout=100)
            if code == 0 and stdout:
                found = extract_first_http_url(stdout, prefer_m3u8=True)
                if found:
                    print(f"✅ YouTube stream bulundu ({client})")
                    return found

    # JSON fallback: bazı durumlarda -g yerine JSON daha stabil bilgi verir.
    json_url = get_youtube_stream_url_from_json(youtube_url)
    if json_url:
        return json_url

    # Force generic en son denensin.
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--force-generic-extractor",
        "-g",
        youtube_url,
    ]
    stdout, _, code = run_yt_dlp(cmd, "generic", timeout=90)
    if code == 0 and stdout:
        found = extract_first_http_url(stdout, prefer_m3u8=True)
        if found:
            print("✅ YouTube generic extractor ile stream bulundu")
            return found

    return None


# ------------------------------------------------------------
# Playlist writing
# ------------------------------------------------------------
def get_direct_stream_url(url: str) -> Optional[str]:
    if url and (url.endswith(".m3u8") or ".m3u8?" in url):
        return url
    return None


def get_stream_url(channel: Dict, quality: str) -> Optional[str]:
    """Kanal tipine göre stream URL'sini al."""
    channel_name = channel.get("name", "")
    url = channel.get("url", "")

    if is_token_kanal(url):
        if is_eurostar_name(channel_name):
            print("🔐 EuroStar token alınıyor...")
            return get_eurostar_token()
        if is_show_turk_name(channel_name):
            print("🔐 Show Türk token alınıyor...")
            return get_show_turk_token()
        return None

    if url and get_direct_stream_url(url):
        print("🔗 Direkt M3U8 linki kullanılıyor")
        return url

    if url and ("youtube.com" in url or "youtu.be" in url):
        print("🎬 YouTube manifest alınıyor...")
        return get_youtube_stream_url(url, quality)

    return None


def create_m3u8_content(stream_url: str) -> str:
    """Temiz M3U8 formatı."""
    return (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720\n"
        f"{stream_url}\n"
    )


def write_channel_m3u8(stream_url: str, output_path: Path) -> Path:
    content = create_m3u8_content(stream_url)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def write_main_playlist(channels: List[Dict], output_folder: Path, output_playlist: str, github_raw_base: str) -> Path:
    output_folder.mkdir(parents=True, exist_ok=True)
    path = output_folder / output_playlist

    content = "#EXTM3U\n"
    for channel in channels:
        name = channel.get("name", "Unknown")
        filename = safe_filename(name)
        raw_url = f"{github_raw_base}/playlist/{filename}"
        content += f"#EXTINF:-1,{name}\n"
        content += f"{raw_url}\n"

    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    print("=" * 60)
    print("🎬 M3U8 Playlist Oluşturucu")
    print("=" * 60)
    print(f"🕐 Başlangıç: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    print_yt_dlp_version()

    if cookie_file_exists():
        print("✅ cookies.txt bulundu")
    else:
        print("⚠️ cookies.txt bulunamadı veya boş")

    try:
        config = load_config()
    except Exception as e:
        print(f"❌ Config okunamadı: {e}")
        return 1

    quality = config["quality"]
    output_folder = Path(config["output_folder"])
    output_playlist = config["output_playlist"]
    github_raw_base = config.get("github_raw_base", "")

    output_folder.mkdir(parents=True, exist_ok=True)

    # Eski M3U8 dosyalarını temizle.
    for old_file in output_folder.glob("*.m3u8"):
        if old_file.name != output_playlist:
            old_file.unlink()

    successful_channels: List[Dict] = []
    failed_channels: List[str] = []

    for index, channel in enumerate(config["channels"], start=1):
        name = channel.get("name", f"Kanal {index}")

        if not channel.get("url"):
            print(f"\n⚠️ [{index}/{len(config['channels'])}] {name}: url yok, atlandı")
            failed_channels.append(name)
            continue

        print(f"\n🔄 [{index}/{len(config['channels'])}] {name} taranıyor...")
        stream_url = get_stream_url(channel, quality)

        if not stream_url:
            print(f"❌ {name}: Stream URL alınamadı")
            failed_channels.append(name)
            continue

        filename = safe_filename(name)
        output_path = output_folder / filename
        write_channel_m3u8(stream_url, output_path)

        successful_channels.append(channel)
        print(f"✅ {name} -> {filename}")

        # YouTube'a çok hızlı art arda yüklenmemek için küçük bekleme.
        time.sleep(1)

    if successful_channels and github_raw_base:
        main_playlist = write_main_playlist(successful_channels, output_folder, output_playlist, github_raw_base)
        print(f"\n✅ Ana playlist: {main_playlist}")
        print(f"✅ Başarılı: {len(successful_channels)}/{len(config['channels'])}")
    elif successful_channels:
        print(f"\n✅ {len(successful_channels)} kanal başarıyla oluşturuldu")
    else:
        print("\n❌ Hiçbir kanal için link alınamadı")
        return 1

    if failed_channels:
        print(f"\n⚠️ Alınamayan kanallar ({len(failed_channels)}):")
        for channel_name in failed_channels[:30]:
            print(f"   - {channel_name}")
        if len(failed_channels) > 30:
            print(f"   ... ve {len(failed_channels) - 30} kanal daha")

    print(f"\n📄 Oluşan M3U8 dosyaları ({output_folder}/):")
    for file in sorted(output_folder.glob("*.m3u8")):
        if file.name != output_playlist:
            print(f"   - {file.name}")

    print(f"\n✅ İşlem tamamlandı: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
