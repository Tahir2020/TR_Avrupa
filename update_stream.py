#!/usr/bin/env python3

import subprocess
import json
import sys
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional


def load_config() -> Dict:
    """JSON config dosyasını yükler"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ config.json bulunamadı!")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ config.json hatalı: {e}")
        sys.exit(1)


def get_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    """
    YouTube canlı yayın URL'sinden m3u8 manifest adresini alır
    """
    cmd = [
        'yt-dlp',
        '-g',
        '--cookies', 'cookies.txt',
        '--js-runtimes', 'deno',
        '--remote-components', 'ejs:github',
        '--extractor-args', 'youtube:player_client=default',
        '-f', quality,
        youtube_url
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=90
        )

        stream_url = result.stdout.strip().splitlines()[0]

        if stream_url and ('manifest' in stream_url or '.m3u8' in stream_url):
            return stream_url
        else:
            print(f"⚠️  Geçersiz URL formatı: {stream_url[:100] if stream_url else 'Boş'}")
            return None

    except subprocess.CalledProcessError as e:
        print(f"❌ yt-dlp hatası ({youtube_url}):")
        if e.stderr:
            print(f"   {e.stderr[:200]}")
        return None
    except subprocess.TimeoutExpired:
        print(f"❌ Zaman aşımı (90 sn): {youtube_url}")
        return None
    except Exception as e:
        print(f"❌ Beklenmeyen hata: {e}")
        return None


def save_channel_m3u(channel: Dict, stream_url: str) -> bool:
    """
    Her kanal için ayrı M3U dosyası oluşturur
    """
    if not stream_url:
        return False

    # Dosya adını güvenli hale getir
    safe_name = channel['channel_name'].replace(' ', '_').replace('/', '_')
    filename = os.path.join('output', f"{safe_name}.m3u")

    m3u_content = f"""#EXTM3U
#EXTINF:-1 tvg-id="{safe_name.lower()}" tvg-name="{channel['channel_name']}" tvg-logo="{channel['channel_logo']}" group-title="{channel['group_title']}", {channel['channel_name']}
{stream_url}
"""

    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(m3u_content)
        return True
    except Exception as e:
        print(f"❌ Dosya yazma hatası {filename}: {e}")
        return False


def save_master_playlist(channels_data: List[Dict], output_file: str) -> None:
    """
    Tüm kanalları gruplandırarak ana playlist'i oluşturur
    """
    # Gruplara göre ayır
    groups = {}
    for ch in channels_data:
        group = ch['group_title']
        if group not in groups:
            groups[group] = []
        groups[group].append(ch)

    m3u_content = "#EXTM3U\n"
    m3u_content += f"# Playlist oluşturulma: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    for group_name, channels in sorted(groups.items()):
        m3u_content += f"\n# === {group_name.upper()} GRUBU ===\n"
        for ch in channels:
            if ch['stream_url']:
                m3u_content += f'#EXTINF:-1 tvg-id="{ch["channel_name"].lower().replace(" ", "")}" tvg-name="{ch["channel_name"]}" tvg-logo="{ch["channel_logo"]}" group-title="{ch["group_title"]}", {ch["channel_name"]}\n'
                m3u_content += f'{ch["stream_url"]}\n'
            else:
                m3u_content += f'#EXTINF:-1 group-title="{ch["group_title"]}", {ch["channel_name"]} (KULLANILAMIYOR)\n'
                m3u_content += f'# STREAM ALINAMADI\n'

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(m3u_content)
        print(f"✅ Master playlist oluşturuldu: {output_file}")
    except Exception as e:
        print(f"❌ Master playlist yazma hatası: {e}")


def process_channel(channel: Dict, quality: str) -> Dict:
    """
    Tek bir kanalı işler (thread pool için)
    """
    print(f"🔄 İşleniyor: {channel['channel_name']} ({channel['group_title']})")
    stream_url = get_stream_url(channel['youtube_url'], quality)

    channel_copy = channel.copy()
    channel_copy['stream_url'] = stream_url

    if stream_url:
        if save_channel_m3u(channel, stream_url):
            print(f"   ✅ {channel['channel_name']} -> M3U oluşturuldu")
        else:
            print(f"   ⚠️ {channel['channel_name']} -> M3U kaydedilemedi")
    else:
        print(f"   ❌ {channel['channel_name']} -> Stream URL alınamadı")

    return channel_copy


def main():
    print("=" * 60)
    print("🎬 TÜRKİYE IPTV - 25 KANAL YAYIN GÜNCELLEYİCİ")
    print("=" * 60)

    config = load_config()

    # Output dizinini oluştur
    if not os.path.exists(config['output_dir']):
        os.makedirs(config['output_dir'])
        print(f"📁 Output dizini oluşturuldu: {config['output_dir']}")

    channels = config['channels']
    quality = config['quality']
    master_playlist = config['master_playlist']

    print(f"\n📡 {len(channels)} kanal taranacak...")
    print(f"🎯 Kalite: {quality}")
    print(f"🍪 Cookies: {'Var' if os.path.exists('cookies.txt') else 'Yok'}\n")

    start_time = datetime.now()
    processed_channels = []

    # Thread pool ile paralel işleme (max 5 eş zamanlı)
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_channel = {
            executor.submit(process_channel, channel, quality): channel
            for channel in channels
        }

        for future in as_completed(future_to_channel):
            try:
                result = future.result()
                processed_channels.append(result)
            except Exception as e:
                channel = future_to_channel[future]
                print(f"❌ {channel['channel_name']} işlenirken hata: {e}")
                # Hatalı kanalı da ekle (stream_url None ile)
                channel_copy = channel.copy()
                channel_copy['stream_url'] = None
                processed_channels.append(channel_copy)

    # Master playlist'i oluştur
    save_master_playlist(processed_channels, master_playlist)

    # İstatistikleri göster
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    successful = sum(1 for ch in processed_channels if ch['stream_url'])

    print("\n" + "=" * 60)
    print("📊 TARAMA RAPORU")
    print("=" * 60)
    print(f"✅ Başarılı: {successful}/{len(processed_channels)} kanal")
    print(f"⏱️  Süre: {duration:.2f} saniye")
    print(f"📁 Master playlist: {master_playlist}")
    print(f"📂 Kanal dosyaları: {config['output_dir']}/")

    # Grup bazında istatistik
    print("\n📺 GRUP BAZLI DURUM:")
    groups = {}
    for ch in processed_channels:
        group = ch['group_title']
        if group not in groups:
            groups[group] = {'total': 0, 'success': 0}
        groups[group]['total'] += 1
        if ch['stream_url']:
            groups[group]['success'] += 1

    for group, stats in sorted(groups.items()):
        status = "✅" if stats['success'] == stats['total'] else "⚠️"
        print(f"   {status} {group}: {stats['success']}/{stats['total']}")

    if successful == len(processed_channels):
        print("\n🎉 TÜM KANALLAR BAŞARIYLA GÜNCELLENDİ!")
        sys.exit(0)
    else:
        print("\n⚠️ Bazı kanallarda hata oluştu, tekrar denenebilir.")
        sys.exit(1)


if __name__ == "__main__":
    main()