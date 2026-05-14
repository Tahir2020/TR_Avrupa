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
        "ç": "c", "Ç": "C",
        "ğ": "g", "Ğ": "G",
        "ı": "i", "İ": "I",
        "ö": "o", "Ö": "O",
        "ş": "s", "Ş": "S",
        "ü": "u", "Ü": "U",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)

    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return f"{name or 'channel'}.m3u"


def is_direct_m3u8(url: str) -> bool:
    clean = url.lower().split("?", 1)[0]
    return clean.endswith(".m3u8")


def get_atv_avrupa_token() -> Optional[str]:
    """ATV Avrupa 576p - Tam otomatik token alıcı"""
    headers = {
        "X-isApp": "1",
        "X-Rand": str(int(time.time() * 1000)),
        "Origin": "https://www.atvavrupa.tv",
        "Referer": "https://www.atvavrupa.tv/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "tr,en-US;q=0.9,en;q=0.8,de;q=0.7",
        "DNT": "1",
    }

    stream_url = "https://trkvz-live.ercdn.net/atvavrupa/atvavrupa_576p.m3u8"
    encoded = urllib.parse.quote(stream_url)
    token_url = (
        "https://securevideotoken.tmgrup.com.tr/webtv/secure"
        f"?{random.randint(1, 1000000)}&url={encoded}&url2={encoded}"
    )

    try:
        response = requests.get(token_url, headers=headers, timeout=10)
        print(f"   ATV token status: {response.status_code}")
        response.raise_for_status()
        data = response.json()

        if data.get("Success") and data.get("Url"):
            token_url_result = data.get("Url")
            print("   ✅ ATV Avrupa token alındı")
            return token_url_result

        print(f"   ❌ ATV Avrupa token alınamadı: {data}")
        return None

    except Exception as e:
        print(f"   ❌ ATV Avrupa hatası: {e}")
        return None


def get_eurostar_token() -> Optional[str]:
    """EuroStar 1080p - HTML'den token çek (HER SEFERİNDE YENİ)"""
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    
    page_url = "https://www.eurostartv.com.tr/canli-izle"
    
    try:
        response = requests.get(page_url, headers=headers, timeout=15)
        html = response.text
        
        # Token'ı HTML'den regex ile bul
        pattern = r"var liveUrl = 'https://dygvideo\.dygdigital\.com/live/hls/staravrupa\?token=([a-f0-9]+)';"
        match = re.search(pattern, html)
        
        if not match:
            print("   ❌ EuroStar token HTML'de bulunamadı")
            return None
        
        token = match.group(1)
        
        # Token ile stream URL'sini al (302 redirect)
        token_url = f"https://dygvideo.dygdigital.com/live/hls/staravrupa?token={token}"
        
        headers2 = {
            "Origin": "https://www.eurostartv.com.tr",
            "Referer": "https://www.eurostartv.com.tr/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        
        response2 = requests.get(token_url, headers=headers2, allow_redirects=False, timeout=10)
        
        if response2.status_code == 302:
            master_url = response2.headers.get("Location")
            
            # 1080p URL oluştur
            match = re.match(r'(.*/)live\.m3u8\?(.*)', master_url)
            if match:
                stream_url = f"{match.group(1)}live_1080p3000000kbps/index.m3u8?{match.group(2)}"
                print(f"   ✅ EuroStar 1080p token alındı")
                return stream_url
            return master_url
        else:
            print(f"   ❌ EuroStar redirect alınamadı: {response2.status_code}")
            return None
            
    except Exception as e:
        print(f"   ❌ EuroStar hatası: {e}")
        return None


def get_show_turk_token() -> Optional[str]:
    """Show Türk - Tam otomatik token alıcı"""
    url = "https://www.showturk.com.tr/canli-yayin"
    pattern = r'playlist\.m3u8\?e=(\d+)&st=([^"\s&]+)'
    
    try:
        response = requests.get(url, timeout=10)
        html = response.text
        match = re.search(pattern, html)
        
        if match:
            e, st = match.groups()
            stream_url = f"https://ciner-live.ercdn.net/showturk/playlist.m3u8?e={e}&st={st}&tv=1"
            print(f"   ✅ Show Türk token alındı")
            return stream_url
        else:
            print(f"   ❌ Show Türk token bulunamadı")
            return None
    except Exception as e:
        print(f"   ❌ Show Türk hatası: {e}")
        return None


def get_youtube_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    cmd = [
        "yt-dlp",
        "-g",
        "--cookies", "cookies.txt",
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
        for line in lines:
            if "manifest" in line or ".m3u8" in line:
                return line

        if lines:
            return lines[0]

        return None

    except subprocess.CalledProcessError as e:
        print("❌ yt-dlp hatası:")
        print(e.stderr)
        return None
    except Exception as e:
        print(f"❌ Hata: {e}")
        return None


def get_stream_url(channel: Dict, quality: str) -> Optional[str]:
    """Kanal tipine göre stream URL'sini al"""
    
    channel_name = channel.get("name", "")
    channel_name_lower = channel_name.lower()

    if "atv" in channel_name_lower and "avrupa" in channel_name_lower:
        print("🔐 ATV Avrupa için token alınıyor...")
        return get_atv_avrupa_token()

    if "euro star" in channel_name_lower or "star avrupa" in channel_name_lower:
        print("🔐 EuroStar için token alınıyor...")
        return get_eurostar_token()

    if "show türk" in channel_name_lower or "show turk" in channel_name_lower:
        print("🔐 Show Türk için token alınıyor...")
        return get_show_turk_token()
    
    url = channel.get("url") or channel.get("youtube_url")
    
    if not url:
        return None

    if is_direct_m3u8(url):
        print("🔗 Direkt m3u8 linki kullanılıyor")
        return url

    print("🎬 YouTube stream alınıyor...")
    return get_youtube_stream_url(url, quality)


def create_extinf(channel: Dict, stream_url: str) -> str:
    name = channel["name"]
    logo = channel.get("logo", "")
    group = channel.get("group", "Genel")
    tvg_id = channel.get("tvg_id", safe_filename(name).replace(".m3u", "").lower())

    extra = ""
    if "atv" in name.lower() and "avrupa" in name.lower():
        extra = (
            "#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36\n"
            "#EXTVLCOPT:http-referrer=https://www.atvavrupa.tv/\n"
            "#KODIPROP:inputstream.adaptive.stream_headers=User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36&Referer=https://www.atvavrupa.tv/&Origin=https://www.atvavrupa.tv\n"
        )

    return (
        f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" '
        f'tvg-logo="{logo}" group-title="{group}",{name}\n'
        f'{extra}'
        f'{stream_url}\n'
    )


def write_single_channel_file(channel: Dict, stream_url: str, output_folder: Path) -> Path:
    output_folder.mkdir(parents=True, exist_ok=True)
    filename = channel.get("m3u_file") or safe_filename(channel["name"])
    path = output_folder / filename

    content = "#EXTM3U\n" + create_extinf(channel, stream_url)
    path.write_text(content, encoding="utf-8")
    return path


def write_main_playlist(entries: List[str], output_folder: Path, output_playlist: str) -> Path:
    output_folder.mkdir(parents=True, exist_ok=True)
    path = output_folder / output_playlist
    content = "#EXTM3U\n" + "\n".join(entries)
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    print("=" * 60)
    print("🎬 TV Kanalları M3U Güncelleyici (Tam Otomatik Token Desteği)")
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

    for old_file in output_folder.glob("*.m3u"):
        old_file.unlink()

    playlist_entries: List[str] = []
    failed_channels: List[str] = []

    for index, channel in enumerate(config["channels"], start=1):
        name = channel.get("name", f"Kanal {index}")

        if not (channel.get("url") or channel.get("youtube_url")):
            print(f"\n⚠️ [{index}/{len(config['channels'])}] {name}: url/youtube_url yok, atlandı")
            failed_channels.append(name)
            continue

        print(f"\n🔄 [{index}/{len(config['channels'])}] {name} taranıyor...")
        stream_url = get_stream_url(channel, quality)

        if not stream_url:
            print(f"❌ {name}: Stream URL alınamadı")
            failed_channels.append(name)
            continue

        single_file = write_single_channel_file(channel, stream_url, output_folder)
        playlist_entries.append(create_extinf(channel, stream_url))
        print(f"✅ {name}: {single_file} oluşturuldu")

    if playlist_entries:
        main_playlist = write_main_playlist(playlist_entries, output_folder, output_playlist)
        print(f"\n✅ Toplu liste oluşturuldu: {main_playlist}")
        print(f"✅ Başarılı kanal sayısı: {len(playlist_entries)}/{len(config['channels'])}")
    else:
        print("\n❌ Hiçbir kanal için link alınamadı")
        return 1

    if failed_channels:
        print("\n⚠️ Alınamayan kanallar:")
        for channel_name in failed_channels:
            print(f"   - {channel_name}")

    print(f"\n📄 Oluşan M3U dosyaları ({output_folder}/):")
    for file in sorted(output_folder.glob("*.m3u")):
        print(f"   - {file.name}")

    print(f"\n✅ İşlem tamamlandı: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
