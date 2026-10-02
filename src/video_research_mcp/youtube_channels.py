"""Bounded YouTube channel metadata and uploads catalog without media downloads."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import unquote, urlparse

from .youtube import YouTubeClient

_CHANNEL_ID = re.compile(r'UC[A-Za-z0-9_-]{22}')
_HANDLE = re.compile(r'@[\w.\-·]{3,30}', re.UNICODE)


def channel_selector(reference: str) -> dict:
    """Accept explicit channel IDs, handles or their canonical YouTube URLs."""
    value = reference.strip()
    if '://' in value:
        parsed = urlparse(value)
        if (parsed.scheme != 'https' or parsed.hostname not in {'youtube.com', 'www.youtube.com', 'm.youtube.com'}
                or parsed.username or parsed.password or parsed.port not in {None, 443}):
            raise ValueError('Expected a canonical HTTPS YouTube channel URL')
        segments = unquote(parsed.path).strip('/').split('/')
        if len(segments) == 2 and segments[0] == 'channel':
            value = segments[1]
        elif len(segments) == 1 and segments[0].startswith('@'):
            value = segments[0]
        else:
            raise ValueError('Use a channel ID or @handle URL; custom /c/ and /user/ aliases are unsupported')
    if _CHANNEL_ID.fullmatch(value):
        return {'id': value}
    if _HANDLE.fullmatch(value):
        return {'forHandle': value}
    raise ValueError('Expected a UC channel ID or an @handle with 3 to 30 characters')


async def channel_metadata(reference: str) -> dict:
    """Resolve a channel through Data API v3 without downloading media."""
    selector = channel_selector(reference)

    def fetch():
        return YouTubeClient.get().channels().list(
            part='snippet,statistics,contentDetails', maxResults=1, **selector,
        ).execute(num_retries=0)

    response = await asyncio.to_thread(fetch)
    items = response.get('items', [])
    if not items:
        raise ValueError('YouTube channel not found or unavailable')
    item = items[0]
    channel_id = item['id']
    if not _CHANNEL_ID.fullmatch(channel_id) or ('id' in selector and selector['id'] != channel_id):
        raise ValueError('YouTube channel response identity does not match the request')
    snippet, stats = item.get('snippet', {}), item.get('statistics', {})
    return {
        'channel_id': channel_id, 'title': snippet.get('title', ''),
        'description': snippet.get('description', ''), 'published_at': snippet.get('publishedAt', ''),
        'custom_url': snippet.get('customUrl', ''), 'thumbnails': snippet.get('thumbnails', {}),
        'country': snippet.get('country', ''),
        'subscriber_count': int(stats['subscriberCount']) if 'subscriberCount' in stats else None,
        'hidden_subscriber_count': bool(stats.get('hiddenSubscriberCount', False)),
        'video_count': int(stats['videoCount']) if 'videoCount' in stats else None,
        'view_count': int(stats['viewCount']) if 'viewCount' in stats else None,
        'uploads_playlist_id': item.get('contentDetails', {}).get('relatedPlaylists', {}).get('uploads'),
        'provenance': {'provider': 'youtube-data-api-v3', 'operation': 'channels.list',
                       'media_downloaded': False, 'source_bytes_state': 'unknown'},
    }


async def channel_catalog(reference: str, max_items: int, page_token: str | None) -> dict:
    """Fetch one uploads page; retain the continuation without claiming full coverage."""
    channel = await channel_metadata(reference)
    playlist_id = channel['uploads_playlist_id']
    if not playlist_id:
        raise ValueError('Channel uploads playlist is unavailable')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', playlist_id):
        raise ValueError('Invalid channel uploads playlist identity')

    def fetch():
        args = {'part': 'snippet', 'playlistId': playlist_id, 'maxResults': max_items}
        if page_token:
            args['pageToken'] = page_token
        return YouTubeClient.get().playlistItems().list(**args).execute(num_retries=0)

    response = await asyncio.to_thread(fetch)
    items = []
    for entry in response.get('items', [])[:max_items]:
        snippet = entry.get('snippet', {})
        items.append({'video_id': snippet.get('resourceId', {}).get('videoId', ''),
                      'title': snippet.get('title', ''), 'position': snippet.get('position'),
                      'published_at': snippet.get('publishedAt', ''),
                      'url': 'https://www.youtube.com/watch?v=' + snippet.get('resourceId', {}).get('videoId', '')})
    return {'channel': channel, 'items': items, 'returned_items': len(items),
            'playlist_reported_total': response.get('pageInfo', {}).get('totalResults'),
            'next_page_token': response.get('nextPageToken'),
            'coverage': 'one_api_page',
            'provenance': {'provider': 'youtube-data-api-v3', 'operation': 'playlistItems.list',
                           'media_downloaded': False, 'source_bytes_state': 'unknown'}}
