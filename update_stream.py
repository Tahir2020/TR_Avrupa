#!/usr/bin/env python3

import json
import re
import subprocess
import sys
import requests
import time
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
    config.setdefault("output_playlist", "playlist.m3u8")
    config.setdefault("github_raw_base", "")
    return config


def safe_filename(name: str) -> str:
    """Kanal adını güvenli dosya adına çevirir - alt tire kullanır"""
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

    # Boşlukları alt çizgiye çevir
    name = name.replace(" ", "_")
    # Özel karakterleri temizle
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
    except Exception:
        pass

    return cookies


def get_eurostar_token() -> Optional[str]:
    """EuroStar stream URL al"""
    headers = {
        "User-Agent": CHROME_UA,
        "Accept": "text/html,application/xhtml+xml",
    }

    page_url = "https://www.eurostartv.com.tr/canli-izle"

    try:
        response = requests.get(page_url, headers=headers, timeout=15)
        html = response.text

        pattern = r"var liveUrl = 'https://dygvideo\.dygdigital\.com/live/hls/staravrupa\?token=([a-f0-9]+)';"
        match = re.search(pattern, html)

        if not match:
            return None

        token = match.group(1)
        token_url = f"https://dygvideo.dygdigital.com/live/hls/staravrupa?token={token}"

        headers2 = {
            "Origin": "https://www.eurostartv.com.tr",
            "Referer": "https://www.eurostartv.com.tr/",
            "User-Agent": CHROME_UA,
        }

        response2 = requests.get(token_url, headers=headers2, allow_redirects=False, timeout=10)

        if response2.status_code == 302:
            master_url = response2.headers.get("Location")
            if not master_url:
                return None

            match = re.match(r"(.*/)live\.m3u8\?(.*)", master_url)
            if match:
                stream_url = f"{match.group(1)}live_1080p3000000kbps/index.m3u8?{match.group(2)}"
                return stream_url

            return master_url

        return None

    except Exception:
        return None


def get_show_turk_token() -> Optional[str]:
    """Show Türk stream URL al"""
    url = "https://www.showturk.com.tr/canli-yayin"
    pattern = r"playlist\.m3u8\?e=(\d+)&st=([^\"\s&]+)"

    headers = {
        "User-Agent": CHROME_UA,
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        html = response.text
        match = re.search(pattern, html)

        if match:
            e, st = match.groups()
            stream_url = f"https://ciner-live.ercdn.net/showturk/playlist.m3u8?e={e}&st={st}&tv=1"
            return stream_url

        return None

    except Exception:
        return None


def get_youtube_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    """YouTube manifest URL al - beIN Sports formatında"""
    cmd = [
        "yt-dlp",
        "-g",
        "--cookies", COOKIE_FILE,
        "--js-runtimes", "deno",
        "--remote-components", "ejs:github",
        "--extractor-args", "youtube:player_client=default",
        "-f", quality,
        youtube_url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        
        # Manifest URL'ini bul
        for line in lines:
            if "manifest" in line and ".m3u8" in line:
                return line
        
        for line in lines:
            if ".m3u8" in line:
                return line

        if lines:
            return lines[0]

        return None

    except subprocess.CalledProcessError as e:
        print(f"   ❌ yt-dlp hatası: {e.stderr[:200]}")
        return None
    except Exception as e:
        print(f"   ❌ Hata: {e}")
        return None


def get_direct_stream_url(url: str) -> Optional[str]:
    """Direkt M3U8 URL'ini kontrol et ve döndür"""
    if url and (url.endswith(".m3u8") or ".m3u8?" in url):
        return url
    return None


def get_stream_url(channel: Dict, quality: str) -> Optional[str]:
    """Kanal tipine göre stream URL'sini al"""
    channel_name = channel.get("name", "")
    
    # Token kanal kontrolü
    url = channel.get("url", "")
    if is_token_kanal(url):
        if is_eurostar_name(channel_name):
            print("🔐 EuroStar token alınıyor...")
            return get_eurostar_token()
        elif is_show_turk_name(channel_name):
            print("🔐 Show Türk token alınıyor...")
            return get_show_turk_token()
        return None
    
    # Direkt M3U8 URL kontrolü
    if url and get_direct_stream_url(url):
        print("🔗 Direkt M3U8 linki kullanılıyor")
        return url
    
    # YouTube kanalı
    youtube_url = channel.get("youtube_url", "")
    if youtube_url:
        print("🎬 YouTube manifest alınıyor...")
        return get_youtube_stream_url(youtube_url, quality)
    
    return None


def create_m3u8_content(stream_url: str) -> str:
    """
    Temiz M3U8 formatında içerik oluşturur:
    #EXTM3U
    #EXT-X-VERSION:3
    #EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720
    [STREAM_URL]
    """
    return (
        f"#EXTM3U\n"
        f"#EXT-X-VERSION:3\n"
        f"#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720\n"
        f"{stream_url}\n"
    )


def write_channel_m3u8(stream_url: str, output_path: Path) -> Path:
    """Tek kanal için M3U8 dosyası oluşturur"""
    content = create_m3u8_content(stream_url)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def write_main_playlist(channels: List[Dict], output_folder: Path, output_playlist: str, github_raw_base: str) -> Path:
    """
    Ana playlist dosyasını oluşturur - sadece kanal adı ve GitHub raw linki
    #EXTM3U
    #EXTINF:-1,Kanal_Adi
    https://raw.githubusercontent.com/.../playlist/Kanal_Adi.m3u8
    """
    output_folder.mkdir(parents=True, exist_ok=True)
    path = output_folder / output_playlist
    
    content = "#EXTM3U\n"
    for channel in channels:
        name = channel.get("name", "Unknown")
        filename = safe_filename(name)
        raw_url = f"{github_raw_base}/playlist/{filename}"
        content += f'#EXTINF:-1,{name}\n'
        content += f'{raw_url}\n'
    
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    print("=" * 60)
    print("🎬 M3U8 Playlist Oluşturucu (Temiz Format)")
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
    github_raw_base = config.get("github_raw_base", "")

    if not github_raw_base:
        print("⚠️ Uyarı: github_raw_base config.json'da tanımlanmamış!")
        print("   Ana playlist oluşturulurken raw linkler kullanılacak")

    output_folder.mkdir(parents=True, exist_ok=True)

    # Eski M3U8 dosyalarını temizle (ana playlist hariç)
    for old_file in output_folder.glob("*.m3u8"):
        if old_file.name != output_playlist:
            old_file.unlink()

    successful_channels: List[Dict] = []
    failed_channels: List[str] = []

    for index, channel in enumerate(config["channels"], start=1):
        name = channel.get("name", f"Kanal {index}")

        # URL veya youtube_url kontrolü
        has_url = channel.get("url") or channel.get("youtube_url")
        if not has_url:
            print(f"\n⚠️ [{index}/{len(config['channels'])}] {name}: url/youtube_url yok, atlandı")
            failed_channels.append(name)
            continue

        print(f"\n🔄 [{index}/{len(config['channels'])}] {name} taranıyor...")
        stream_url = get_stream_url(channel, quality)

        if not stream_url:
            print(f"❌ {name}: Stream URL alınamadı")
            failed_channels.append(name)
            continue

        # Kanal için ayrı M3U8 dosyası oluştur
        filename = safe_filename(name)
        output_path = output_folder / filename
        write_channel_m3u8(stream_url, output_path)
        
        successful_channels.append(channel)
        print(f"✅ {name} -> {filename}")
        print(f"   📹 URL: {stream_url[:80]}...")

    # Ana playlist oluştur
    if successful_channels and github_raw_base:
        main_playlist = write_main_playlist(successful_channels, output_folder, output_playlist, github_raw_base)
        print(f"\n✅ Ana playlist oluşturuldu: {main_playlist}")
        print(f"✅ Başarılı: {len(successful_channels)}/{len(config['channels'])}")
    elif successful_channels:
        print(f"\n✅ {len(successful_channels)} kanal başarıyla oluşturuldu")
        print("⚠️ github_raw_base tanımlı olmadığı için ana playlist oluşturulmadı")
    else:
        print("\n❌ Hiçbir kanal için link alınamadı")
        return 1

    if failed_channels:
        print("\n⚠️ Alınamayan kanallar:")
        for channel_name in failed_channels:
            print(f"   - {channel_name}")

    print(f"\n📄 Oluşan M3U8 dosyaları ({output_folder}/):")
    for file in sorted(output_folder.glob("*.m3u8")):
        if file.name != output_playlist:
            print(f"   - {file.name}")

    print(f"\n✅ İşlem tamamlandı: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
