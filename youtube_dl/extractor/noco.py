# encoding: utf-8
from __future__ import unicode_literals

import re
import time
import hashlib

from .common import InfoExtractor
from ..compat import (
    compat_str,
    compat_urllib_parse,
    compat_urllib_request,
)
from ..utils import (
    clean_html,
    ExtractorError,
    int_or_none,
    float_or_none,
    parse_iso8601,
)


class NocoIE(InfoExtractor):
    _VALID_URL = r'http://(?:(?:www\.)?noco\.tv/emission/|player\.noco\.tv/\?idvideo=)(?P<id>\d+)'
    _LOGIN_URL = 'http://noco.tv/do.php'
    _API_URL_TEMPLATE = 'https://api.noco.tv/1.1/%s?ts=%s&tk=%s'
    _SUB_LANG_TEMPLATE = '&sub_lang=%s'
    _NETRC_MACHINE = 'noco'

    _TESTS = [
        {
            'url': 'http://noco.tv/emission/11538/nolife/ami-ami-idol-hello-france/',
            'md5': '0a993f0058ddbcd902630b2047ef710e',
            'info_dict': {
                'id': '11538',
                'ext': 'mp4',
                'title': 'Ami Ami Idol - Hello! France',
                'description': 'md5:4eaab46ab68fa4197a317a88a53d3b86',
                'upload_date': '20140412',
                'uploader': 'Nolife',
                'uploader_id': 'NOL',
                'duration': 2851.2,
            },
            'skip': 'Requires noco account',
        },
        {
            'url': 'http://noco.tv/emission/12610/lbl42/the-guild/s01e01-wake-up-call',
            'md5': 'c190f1f48e313c55838f1f412225934d',
            'info_dict': {
                'id': '12610',
                'ext': 'mp4',
                'title': 'The Guild #1 - Wake-Up Call',
                'timestamp': 1403863200,
                'upload_date': '20140627',
                'uploader': 'LBL42',
                'uploader_id': 'LBL',
                'duration': 233.023,
            },
            'skip': 'Requires noco account',
        }
    ]

    def _real_initialize(self):
        self._login()

    def _login(self):
        (username, password) = self._get_login_info()
        if username is None:
            return

        login_form = {
            'a': 'login',
            'cookie': '1',
            'username': username,
            'password': password,
        }
        request = compat_urllib_request.Request(self._LOGIN_URL, compat_urllib_parse.urlencode(login_form))
        request.add_header('Content-Type', 'application/x-www-form-urlencoded; charset=UTF-8')

        login = self._download_json(request, None, 'Logging in as %s' % username)

        if 'erreur' in login:
            raise ExtractorError('Unable to login: %s' % clean_html(login['erreur']), expected=True)

    def _call_api(self, path, video_id, note, sub_lang=None):
        ts = compat_str(int(time.time() * 1000))
        tk = hashlib.md5((hashlib.md5(ts.encode('ascii')).hexdigest() + '#8S?uCraTedap6a').encode('ascii')).hexdigest()
        url = self._API_URL_TEMPLATE % (path, ts, tk)
        if sub_lang:
            url += self._SUB_LANG_TEMPLATE % sub_lang

        resp = self._download_json(url, video_id, note)

        if isinstance(resp, dict) and resp.get('error'):
            self._raise_error(resp['error'], resp['description'])

        return resp

    def _raise_error(self, error, description):
        raise ExtractorError(
            '%s returned error: %s - %s' % (self.IE_NAME, error, description),
            expected=True)

    def _real_extract(self, url):
        mobj = re.match(self._VALID_URL, url)
        video_id = mobj.group('id')

        medias = self._call_api(
            'shows/%s/medias' % video_id,
            video_id, 'Downloading video JSON')

        show = self._call_api(
            'shows/by_id/%s' % video_id,
            video_id, 'Downloading show JSON')[0]

        options = self._call_api(
            'users/init', video_id,
            'Downloading user options JSON')['options']
        audio_lang_pref = options.get('audio_language') or options.get('language', 'fr')

        if audio_lang_pref == 'original':
            audio_lang_pref = show['original_lang']
        if len(medias) == 1:
            audio_lang_pref = list(medias.keys())[0]
        elif audio_lang_pref not in medias:
            audio_lang_pref = 'fr'

        qualities = self._call_api(
            'qualities',
            video_id, 'Downloading qualities JSON')

        formats = []

        for audio_lang, audio_lang_dict in medias.items():
            preference = 1 if audio_lang == audio_lang_pref else 0
            for sub_lang, lang_dict in audio_lang_dict['video_list'].items():
                for format_id, fmt in lang_dict['quality_list'].items():
                    format_id_extended = 'audio-%s_sub-%s_%s' % (audio_lang, sub_lang, format_id)

                    video = self._call_api(
                        'shows/%s/video/%s/%s' % (video_id, format_id.lower(), audio_lang),
                        video_id, 'Downloading %s video JSON' % format_id_extended,
                        sub_lang if sub_lang != 'none' else None)

                    file_url = video['file']
                    if not file_url:
                        continue

                    if file_url in ['forbidden', 'not found']:
                        popmessage = video['popmessage']
                        self._raise_error(popmessage['title'], popmessage['message'])

                    formats.append({
                        'url': file_url,
                        'format_id': format_id_extended,
                        'width': int_or_none(fmt.get('res_width')),
                        'height': int_or_none(fmt.get('res_lines')),
                        'abr': int_or_none(fmt.get('audiobitrate')),
                        'vbr': int_or_none(fmt.get('videobitrate')),
                        'filesize': int_or_none(fmt.get('filesize')),
                        'format_note': qualities[format_id].get('quality_name'),
                        'quality': qualities[format_id].get('priority'),
                        'preference': preference,
                    })

        self._sort_formats(formats)

        timestamp = parse_iso8601(show.get('online_date_start_utc'), ' ')
        uploader = show.get('partner_name')
        uploader_id = show.get('partner_key')
        duration = float_or_none(show.get('duration_ms'), 1000)

        thumbnails = []
        for thumbnail_key, thumbnail_url in show.items():
            m = re.search(r'^screenshot_(?P<width>\d+)x(?P<height>\d+)$', thumbnail_key)
            if not m:
                continue
            thumbnails.append({
                'url': thumbnail_url,
                'width': int(m.group('width')),
                'height': int(m.group('height')),
            })

        episode = show.get('show_TT') or show.get('show_OT')
        family = show.get('family_TT') or show.get('family_OT')
        episode_number = show.get('episode_number')

        title = ''
        if family:
            title += family
        if episode_number:
            title += ' #' + compat_str(episode_number)
        if episode:
            title += ' - ' + episode

        description = show.get('show_resume') or show.get('family_resume')

        return {
            'id': video_id,
            'title': title,
            'description': description,
            'thumbnails': thumbnails,
            'timestamp': timestamp,
            'uploader': uploader,
            'uploader_id': uploader_id,
            'duration': duration,
            'formats': formats,
        }
