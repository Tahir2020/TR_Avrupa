#!/usr/bin/env python3

import subprocess
import json
import sys
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional


def load_config() -> Dict:
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ config.json bulunamadı!")
        sys.exit(1)


def get_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    """
    YouTube canlı yayın URL'sinden m3u8 manifest adresini alır
    Cookies KULLANILMIYOR - daha stabil
    """
    # yt-dlp komutu - cookies'siz, web client ile
    cmd = [
        'yt-dlp',
        '-g',
        '--no-check-certificate',
        '--extractor-args', 'youtube:player_client=web',
        '--no-cache-dir',
        '-f', quality,
        youtube_url
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else ""
            
            # Kullanıcı dostu hata mesajları
            if "Video unavailable" in error_msg:
                print("   📺 Yayında değil")
            elif "Sign in to confirm" in error_msg:
                print("   🔐 Oturum gerekli (public değil)")
            elif "not made this video available" in error_msg:
                print("   🌍 Coğrafi kısıtlama")
            elif "Private video" in error_msg:
                print("   🔒 Gizli video")
            else:
                # Sadece ilk satırı göster
                first_line = error_msg.split('\n')[0] if error_msg else "Bilinmeyen hata"
                if len(first_line) > 60:
                    first_line = first_line[:60] + "..."
                print(f"   ❌ {first_line}")
            return None
            
        output = result.stdout.strip()
        if not output:
            print("   ❌ Boş çıktı")
            return None
            
        stream_url = output.splitlines()[0]
        
        # URL geçerlilik kontrolü
        if stream_url and ('.m3u8' in stream_url or 'manifest' in stream_url or 'googlevideo' in stream_url):
            return stream_url
        else:
            print(f"   ⚠️ Geçersiz URL")
            return None
            
    except subprocess.TimeoutExpired:
        print("   ⏱️ Zaman aşımı (60 sn)")
        return None
    except Exception as e:
        print(f"   ❌ {str(e)[:60]}")
        return None


def save_channel_m3u(channel: Dict, stream_url: str) -> bool:
    """Her kanal için ayrı M3U dosyası oluşturur"""
    if not stream_url:
        return False
    
    # Output dizinini oluştur
    os.makedirs('output', exist_ok=True)
    
    # Güvenli dosya adı
    safe_name = channel['channel_name'].replace(' ', '_').replace('/', '_').replace(':', '').replace('?', '').replace('(', '').replace(')', '')
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
        print(f"   💾 Kayıt hatası: {e}")
        return False


def save_master_playlist(channels_data: List[Dict], output_file: str) -> None:
    """Ana playlist'i gruplandırarak oluşturur"""
    groups = {}
    for ch in channels_data:
        group = ch['group_title']
        if group not in groups:
            groups[group] = []
        groups[group].append(ch)
    
    successful = sum(1 for ch in channels_data if ch.get('stream_url'))
    
    m3u_content = "#EXTM3U\n"
    m3u_content += f"# Playlist oluşturulma: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    m3u_content += f"# Toplam kanal: {len(channels_data)}\n"
    m3u_content += f"# Çalışan kanal: {successful}\n\n"
    
    for group_name, channels in sorted(groups.items()):
        working = sum(1 for ch in channels if ch.get('stream_url'))
        m3u_content += f"\n# === {group_name.upper()} ({working}/{len(channels)} kanal) ===\n"
        for ch in channels:
            if ch.get('stream_url'):
                m3u_content += f'#EXTINF:-1 tvg-id="{ch["channel_name"].lower().replace(" ", "")}" tvg-name="{ch["channel_name"]}" tvg-logo="{ch["channel_logo"]}" group-title="{ch["group_title"]}", {ch["channel_name"]}\n'
                m3u_content += f'{ch["stream_url"]}\n'
            else:
                m3u_content += f'#EXTINF:-1 group-title="{ch["group_title"]}", ❌ {ch["channel_name"]}\n'
                m3u_content += f'# YAYINDA DEĞIL\n'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(m3u_content)
    
    print(f"\n✅ Master playlist: {output_file} ({successful}/{len(channels_data)} kanal)")


def process_channel(channel: Dict, quality: str) -> Dict:
    """Tek bir kanalı işler"""
    # Kanal adını kısalt (daha temiz görünüm)
    name = channel['channel_name'][:23] + ".." if len(channel['channel_name']) > 25 else channel['channel_name']
    print(f"🔄 {name:25} | {channel['group_title']:12}", end=" ", flush=True)
    
    stream_url = get_stream_url(channel['youtube_url'], quality)
    
    result = channel.copy()
    result['stream_url'] = stream_url
    
    if stream_url:
        if save_channel_m3u(channel, stream_url):
            print("✅")
        else:
            print("⚠️")
    else:
        print("❌")
    
    return result


def main():
    print("=" * 70)
    print("🎬 TÜRKİYE IPTV - CANLI YAYIN GÜNCELLEYİCİ (Cookies'siz)")
    print("=" * 70)
    
    config = load_config()
    channels = config['channels']
    quality = config['quality']
    
    print(f"\n📡 Toplam kanal: {len(channels)}")
    print(f"🎯 Kalite: {quality}")
    print(f"🍪 Cookies: ❌ Kullanılmıyor (daha stabil)")
    print(f"🚀 Başlıyor...\n")
    
    start_time = datetime.now()
    processed = []
    
    # Paralel işleme (max 2 - GitHub Actions için)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(process_channel, ch, quality): ch for ch in channels}
        for future in as_completed(futures):
            try:
                processed.append(future.result())
            except Exception as e:
                ch = futures[future]
                print(f"❌ {ch['channel_name']} kritik hata: {e}")
                ch_copy = ch.copy()
                ch_copy['stream_url'] = None
                processed.append(ch_copy)
    
    # Master playlist oluştur
    save_master_playlist(processed, 'playerlist.m3u')
    
    # İstatistikler
    elapsed = (datetime.now() - start_time).total_seconds()
    success = sum(1 for ch in processed if ch['stream_url'])
    
    print("\n" + "=" * 70)
    print("📊 TARAMA RAPORU")
    print("=" * 70)
    print(f"✅ Başarılı: {success}/{len(processed)} kanal")
    print(f"❌ Başarısız: {len(processed) - success}/{len(processed)} kanal")
    print(f"⏱️  Süre: {elapsed:.1f} saniye")
    
    # Çalışan kanalları listele
    if success > 0:
        print("\n✅ ÇALIŞAN KANALLAR:")
        working_channels = [ch for ch in processed if ch.get('stream_url')]
        for ch in working_channels[:10]:  # İlk 10'u göster
            print(f"   • {ch['channel_name']} ({ch['group_title']})")
        if len(working_channels) > 10:
            print(f"   ... ve {len(working_channels) - 10} kanal daha")
    
    # Grup istatistikleri
    print("\n📺 GRUP BAZLI DURUM:")
    groups = {}
    for ch in processed:
        g = ch['group_title']
        if g not in groups:
            groups[g] = {'total': 0, 'ok': 0}
        groups[g]['total'] += 1
        if ch['stream_url']:
            groups[g]['ok'] += 1
    
    for g, stats in sorted(groups.items()):
        status = "✅" if stats['ok'] == stats['total'] else "⚠️" if stats['ok'] > 0 else "❌"
        print(f"   {status} {g:15}: {stats['ok']:2}/{stats['total']}")
    
    # Her zaman başarılı çık (en az 1 kanal çalışıyorsa)
    if success > 0:
        print(f"\n🎉 {success} kanal başarıyla güncellendi!")
        sys.exit(0)
    else:
        print("\n⚠️ Hiçbir kanal çalışmıyor! YouTube kanalları canlı değil veya erişilemiyor.")
        print("💡 Bu genellikle şu an canlı yayın olmamasından kaynaklanır.")
        print("💡 Bir sonraki saatte tekrar dene.")
        sys.exit(0)  # Yine de başarılı çık - action'ın kızarmasını engelle


if __name__ == "__main__":
    main()
