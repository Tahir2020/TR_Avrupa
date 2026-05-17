#!/usr/bin/env python3

import json
import re
import subprocess
import sys
import requests
import random
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

CONFIG_FILE = "config.json"
COOKIE_FILE = "cookies.txt"

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)


def load_config() -> Dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    if "channels" not in config or not isinstance(config["channels"], list):
        raise ValueError("config.json içinde 'channels' listesi bulunamadı.")

    if not config["channels"]:
        raise ValueError("config.json içinde kanal listesi boş.")

    config.setdefault("quality", "best[height<=1080][fps<=50]/best")
    config.setdefault("output_folder", "playlist")
    config.setdefault("output_playlist", "playerlist.m3u")
    return config


def safe_filename(name: str) -> str:
    replacements = {
        "ç": "c", "Ç": "C", "ğ": "g", "Ğ": "G",
        "ı": "i", "İ": "I", "ö": "o", "Ö": "O",
        "ş": "s", "Ş": "S", "ü": "u", "Ü": "U",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return f"{name or 'channel'}.m3u"


def is_direct_m3u8(url: str) -> bool:
    clean = url.lower().split("?", 1)[0]
    return clean.endswith(".m3u8")


def is_atv_avrupa_name(name: str) -> bool:
    lower = name.lower()
    return "atv" in lower and "avrupa" in lower


def is_eurostar_name(name: str) -> bool:
    lower = name.lower()
    return "euro star" in lower or "eurostar" in lower or "star avrupa" in lower


def is_show_turk_name(name: str) -> bool:
    lower = name.lower()
    return "show" in lower and ("türk" in lower or "turk" in lower)


def load_netscape_cookies(cookie_file: str = COOKIE_FILE) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    path = Path(cookie_file)

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
    except Exception:
        pass
    return cookies


def get_atv_avrupa_token() -> Optional[str]:
    headers = {
        "X-isApp": "1",
        "X-Rand": str(int(time.time() * 1000)),
        "Origin": "https://www.atvavrupa.tv",
        "Referer": "https://www.atvavrupa.tv/",
        "User-Agent": CHROME_UA,
    }

    stream_url = "https://trkvz-live.ercdn.net/atvavrupa/atvavrupa_576p.m3u8"
    encoded = urllib.parse.quote(stream_url)
    token_url = f"https://securevideotoken.tmgrup.com.tr/webtv/secure?{random.randint(1, 1000000)}&url={encoded}&url2={encoded}"

    cookies = load_netscape_cookies()

    try:
        response = requests.get(token_url, headers=headers, cookies=cookies if cookies else None, timeout=15)
        data = response.json()
        if data.get("Success") and data.get("Url"):
            return data.get("Url")
    except Exception:
        pass
    return None


def get_eurostar_token() -> Optional[str]:
    page_url = "https://www.eurostartv.com.tr/canli-izle"
    try:
        response = requests.get(page_url, headers={"User-Agent": CHROME_UA}, timeout=15)
        html = response.text
        match = re.search(r"var liveUrl = 'https://dygvideo\.dygdigital\.com/live/hls/staravrupa\?token=([a-f0-9]+)';", html)
        if not match:
            return None
        token = match.group(1)
        token_url = f"https://dygvideo.dygdigital.com/live/hls/staravrupa?token={token}"
        response2 = requests.get(token_url, headers={"Origin": "https://www.eurostartv.com.tr", "User-Agent": CHROME_UA}, allow_redirects=False, timeout=10)
        if response2.status_code == 302:
            master_url = response2.headers.get("Location")
            if master_url:
                match = re.match(r"(.*/)live\.m3u8\?(.*)", master_url)
                if match:
                    return f"{match.group(1)}live_1080p3000000kbps/index.m3u8?{match.group(2)}"
                return master_url
    except Exception:
        pass
    return None


def get_show_turk_token() -> Optional[str]:
    url = "https://www.showturk.com.tr/canli-yayin"
    try:
        response = requests.get(url, headers={"User-Agent": CHROME_UA}, timeout=10)
        html = response.text
        match = re.search(r"playlist\.m3u8\?e=(\d+)&st=([^\"\s&]+)", html)
        if match:
            e, st = match.groups()
            return f"https://ciner-live.ercdn.net/showturk/playlist.m3u8?e={e}&st={st}&tv=1"
    except Exception:
        pass
    return None


def get_youtube_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    """YouTube'dan stream URL'sini alır - çoklu format dener"""
    
    # Denenecek formatlar (başarılı olana kadar)
    formats_to_try = [
        f"best[height<=1080][ext=m3u8]/best[ext=m3u8]",
        f"best[height<=720][ext=m3u8]",
        "best[ext=m3u8]",
        "best",
        quality
    ]
    
    cookies = load_netscape_cookies()
    cookie_args = ["--cookies", COOKIE_FILE] if cookies else []
    
    for fmt in formats_to_try:
        cmd = [
            "yt-dlp", "-g",
            *cookie_args,
            "--extractor-args", "youtube:player_client=android,web",
            "--no-check-certificate",
            "-f", fmt,
            youtube_url
        ]
        
        try:
            print(f"   🎬 Denenen format: {fmt}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line and ("manifest.googlevideo.com" in line or ".m3u8" in line):
                        # URL'yi temizle
                        clean_url = line.split('#')[0].strip()
                        if clean_url.startswith("http"):
                            print(f"   ✅ YouTube URL alındı")
                            return clean_url
        except subprocess.TimeoutExpired:
            print(f"   ⏱️ Zaman aşımı: {fmt}")
            continue
        except Exception as e:
            print(f"   ⚠️ Hata ({fmt}): {str(e)[:50]}")
            continue
    
    # Son çare: yt-dlp --geo-bypass ile dene
    try:
        print("   🌍 Coğrafi engeli aşmayı dene...")
        cmd = ["yt-dlp", "-g", "--geo-bypass", "--extractor-args", "youtube:player_client=android", youtube_url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            url = result.stdout.strip().split('\n')[0]
            if url and url.startswith("http"):
                print("   ✅ YouTube URL alındı (geo-bypass ile)")
                return url
    except Exception:
        pass
    
    return None


def get_stream_url(channel: Dict, quality: str) -> Optional[str]:
    name = channel.get("name", "")
    url = channel.get("url") or channel.get("youtube_url")

    if not url:
        return None

    # Token gerektiren özel kanallar
    if is_atv_avrupa_name(name):
        print("🔐 ATV Avrupa token alınıyor...")
        return get_atv_avrupa_token()
    if is_eurostar_name(name):
        print("🔐 EuroStar token alınıyor...")
        return get_eurostar_token()
    if is_show_turk_name(name):
        print("🔐 Show Türk token alınıyor...")
        return get_show_turk_token()

    # Direkt m3u8
    if is_direct_m3u8(url):
        print("🔗 Direkt m3u8 linki")
        return url

    # YouTube
    print("🎬 YouTube stream alınıyor...")
    return get_youtube_stream_url(url, quality)


def create_clean_hls_playlist(stream_url: str) -> str:
    return f"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720
{stream_url}"""


def create_main_entry(name: str, stream_url: str) -> str:
    return f"#EXTINF:-1,{name}\n{stream_url}"


def write_single_channel_file(channel: Dict, stream_url: str, output_folder: Path) -> Path:
    output_folder.mkdir(parents=True, exist_ok=True)
    filename = channel.get("m3u_file") or safe_filename(channel["name"])
    path = output_folder / filename

    content = create_clean_hls_playlist(stream_url)
    path.write_text(content, encoding="utf-8")
    return path


def write_main_playlist(entries: List[str], output_folder: Path, output_playlist: str) -> Path:
    output_folder.mkdir(parents=True, exist_ok=True)
    path = output_folder / output_playlist
    content = "#EXTM3U\n#EXT-X-VERSION:3\n" + "\n".join(entries)
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    print("=" * 60)
    print("🎬 TV Kanalları M3U Güncelleyici (TEMIZ HLS Formatında)")
    print("=" * 60)
    print(f"🕐 Başlangıç: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        config = load_config()
    except Exception as e:
        print(f"❌ Config okunamadı: {e}")
        return 1

    quality = config["quality"]
    output_folder = Path(config["output_folder"])
    output_playlist = config["output_playlist"]

    output_folder.mkdir(parents=True, exist_ok=True)

    # Eski dosyaları temizle (playerlist hariç)
    for old_file in output_folder.glob("*.m3u"):
        if old_file.name != "playerlist.m3u":
            old_file.unlink()

    playlist_entries: List[str] = []
    failed_channels: List[str] = []

    for index, channel in enumerate(config["channels"], start=1):
        name = channel.get("name", f"Kanal {index}")

        if not (channel.get("url") or channel.get("youtube_url")):
            print(f"\n⚠️ [{index}/{len(config['channels'])}] {name}: URL yok, atlandı")
            failed_channels.append(name)
            continue

        print(f"\n🔄 [{index}/{len(config['channels'])}] {name}")
        print("-" * 40)
        
        stream_url = get_stream_url(channel, quality)

        if not stream_url:
            print(f"❌ {name}: Stream URL alınamadı")
            failed_channels.append(name)
            continue

        single_file = write_single_channel_file(channel, stream_url, output_folder)
        playlist_entries.append(create_main_entry(name, stream_url))
        print(f"✅ {name}: {single_file} oluşturuldu")
        time.sleep(0.5)

    if playlist_entries:
        main_playlist = write_main_playlist(playlist_entries, output_folder, output_playlist)
        print(f"\n✅ Toplu liste: {main_playlist}")
        print(f"✅ Başarılı: {len(playlist_entries)}/{len(config['channels'])}")
    else:
        print("\n❌ Hiçbir kanal alınamadı")
        return 1

    if failed_channels:
        print(f"\n⚠️ Alınamayanlar ({len(failed_channels)}):")
        for ch in failed_channels[:10]:
            print(f"   - {ch}")
        if len(failed_channels) > 10:
            print(f"   ... ve {len(failed_channels)-10} kanal daha")

    return 0


if __name__ == "__main__":
    sys.exit(main())
