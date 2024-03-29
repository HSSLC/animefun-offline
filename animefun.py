import requests
import os, sys, time
import re
import shutil

import functions
import multiple_thread_downloading
from acgDetail import acgDetail

# header const
header = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.70', 'referer': 'https://ani.gamer.com.tw/animeVideo.php', 'origin': 'https://ani.gamer.com.tw'}
session = requests.session()
session.headers.update(header)
deviceid = None

# read cookie from file
# paste your BAHARUNE cookie in cookie.txt if you want to download high resolution video
# BAHARUNE=YOUR_BAHARUNE_COOKIE
try:
    # cookies in k=v format
    with open('cookie.txt', 'r') as f:
        cookies = f.read().strip()
        cookies = {i.split('=')[0]: i.split('=')[1] for i in cookies.split('\n')}
        session.cookies.update(cookies)
except:
    print('cookies.txt not found')


def download_sn(sn: str, resolution: int=-1, method: str='mtd', download_dir_name: str='Downloads', group_dir_name: str='.', ep_dir_name: str=None, keep_tmp: bool=False):
    if not method in ['mtd', 'ffmpeg', 'aes128']:
        raise Exception('method must be one of mtd, ffmpeg, aes128')
    
    if ep_dir_name is None:
        ep_dir_name = '{sn}_{resolution}'

    # get device id
    global deviceid
    deviceid_res = session.get(f"https://ani.gamer.com.tw/ajax/getdeviceid.php{'?id=' + deviceid if deviceid is not None else ''}")
    deviceid_res.raise_for_status()
    deviceid = deviceid_res.json()['deviceid']

    # get token
    res = session.get(f"https://ani.gamer.com.tw/ajax/token.php?sn={sn}&device={deviceid}")
    res.raise_for_status()
    token = res.json()
    if 'error' in token:
        print(token)
        return

    if token['time'] == 0:
        # start ad
        ad_data = functions.get_major_ad()
        session.cookies.update(ad_data['cookie'])
        print('start ad')
        # session.get('https://ani.gamer.com.tw/ajax/videoCastcishu.php?s=%s&sn=%s' % (ad_data['adsid'], sn))
        session.get(f"https://ani.gamer.com.tw/ajax/videoCastcishu.php?s={ad_data['adsid']}&sn={sn}")
        ad_countdown = 25
        for countdown in range(ad_countdown):
            print(f'ad {ad_countdown - countdown}s remaining', end='\r')
            time.sleep(1)

        #end ad
        # session.get('https://ani.gamer.com.tw/ajax/videoCastcishu.php?s=%s&sn=%s&ad=end' % (ad_data['adsid'], sn))
        session.get(f"https://ani.gamer.com.tw/ajax/videoCastcishu.php?s={ad_data['adsid']}&sn={sn}&ad=end")
        print('end ad')

    # get m3u8 url form m3u8.php
    # m3u8_php_res = session.get('https://ani.gamer.com.tw/ajax/m3u8.php?sn=%s&device=%s' % (sn, deviceid))
    m3u8_php_res = session.get(f"https://ani.gamer.com.tw/ajax/m3u8.php?sn={sn}&device={deviceid}")
    m3u8_php_res.raise_for_status()
    try:
        playlist_basic_url = m3u8_php_res.json()['src']
    except Exception as ex:
        print(m3u8_php_res.text)
        print('failed to load m3u')
        exit()

    # get playlist_basic.m38u
    meta_base = os.path.dirname(playlist_basic_url) + '/'
    playlist_basic_res = requests.get(playlist_basic_url, headers=header)
    playlist_basic_res.raise_for_status()

    playlist_basic = playlist_basic_res.text.split('\n')

    # list all resolutions' metadata in list
    resolutions_metadata = []
    for i, line in enumerate(playlist_basic):
        if line.startswith('#EXT-X-STREAM-INF'):
            resolutions_metadata.append({'info': line[18:], 'url': playlist_basic[i+1]})

    # select a resolution from argv or stdin
    if resolution is not None and resolution < len(resolutions_metadata):
        print('selected resolution: %s' % resolutions_metadata[resolution]['info'])
    else:
        for j in range(len(resolutions_metadata)):
            print(f"#{j}: {resolutions_metadata[j]['info']}")
        # read selection from console
        resolution = int(input('select a resolution: '))

    # get resolution number for folder name(format ex: 1080x1920)
    resolution_name = resolutions_metadata[resolution]['info'].rsplit('=', 1)[1]

    filename_base = ep_dir_name.format(sn=sn, resolution=resolution_name)

    # prepare work directory
    ep_basedir = os.path.join(download_dir_name, group_dir_name, filename_base)
    os.makedirs(ep_basedir, exist_ok=True)

    if method == 'mtd':
        tmp_dir = os.path.join(ep_basedir, 'tmp')
        os.makedirs(tmp_dir, exist_ok=True)

        # get chunklist m3u8
        chunklist_res = requests.get(meta_base + resolutions_metadata[resolution]['url'], headers=header)

        # save chunklist to disk
        chunklist_filename = os.path.basename(resolutions_metadata[resolution]['url'])
        with open(os.path.join(tmp_dir, chunklist_filename), 'wb') as chunklist_file:
            for chunk in chunklist_res:
                chunklist_file.write(chunk)

        # base for the chunks
        # chunks_base = meta_base + resolutions_metadata[resolution]['url'].rsplit('/', 1)[0] + '/'
        chunks_base = f"{meta_base}{os.path.dirname(resolutions_metadata[resolution]['url'])}/"

        # parse chunklist.m3u8
        chunklist = chunklist_res.text.split('\n')
        mtd_worker = multiple_thread_downloading.mtd(header, chunks_base, tmp_dir)

        for k in range(len(chunklist)):
            line = chunklist[k]
            if line.startswith('#EXTINF'):
                ts_name = chunklist[k+1]
                # push
                mtd_worker.push(ts_name)
            elif line.startswith('#EXT-X-KEY'):
                key_name = re.match('.*URI="(.*)".*$', line).group(1)
                # push
                mtd_worker.push(key_name)
        # wait for all download thread finished
        mtd_worker.join()

        # call ffmpeg to combine all ts
        # os.system('ffmpeg -allowed_extensions ALL -i %s -c copy %s.mp4' % (chunklist_filename, folder_name))
        os.system(f'ffmpeg -allowed_extensions ALL -i "{os.path.join(tmp_dir, chunklist_filename)}" -c copy "{os.path.join(ep_basedir, filename_base)}.mp4" -y')
        # remove tmp
        if not keep_tmp:
            shutil.rmtree(tmp_dir)
    elif method == 'ffmpeg':
        # linux only
        pass

    elif method == 'aes128':
        from Crypto.Cipher import AES
        import binascii

        big_ts = open(os.path.join(ep_basedir, f"{filename_base}.mp4"), 'wb')
        
        # base for the chunks
        chunks_base = f"{meta_base}{os.path.dirname(resolutions_metadata[resolution]['url'])}/"

        # get chunklist m3u8
        chunklist_res = requests.get(meta_base + resolutions_metadata[resolution]['url'], headers=header)
        chunklist = chunklist_res.text.split('\n')

        length = chunklist_res.text.count('.ts')

        iv = None
        for k in range(len(chunklist)):
            line = chunklist[k]
            if line.startswith('#EXT-X-KEY'):
                groups = re.match('.*METHOD=AES-128,URI="([^"]+)".*?(?:,IV=([^,\s]+))?', line).groups()
                key_name = groups[0]
                key_res = requests.get(chunks_base + key_name, headers=header)
                key = key_res.content

                if groups[1] is not None:
                    iv = binascii.unhexlify(groups[1])
            
            elif line.startswith('#EXT-X-MEDIA-SEQUENCE'):
                seq = int(line.split(':')[1])
            
            elif line.startswith('#EXTINF'):
                ts_name = chunklist[k + 1]

                print(f"Downloading {ts_name}...({seq + 1}/{length})")

                ts_res = requests.get(chunks_base + ts_name, headers=header)
                ts = ts_res.content

                if iv is None:
                    chiper = AES.new(key, AES.MODE_CBC, IV=seq.to_bytes(16, 'big'))
                else:
                    chiper = AES.new(key, AES.MODE_CBC, IV=iv)
                
                big_ts.write(chiper.decrypt(ts))
                seq += 1
                pass
        big_ts.close()
                
