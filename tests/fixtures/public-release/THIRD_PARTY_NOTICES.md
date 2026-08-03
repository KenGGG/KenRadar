# Third-Party Notices

KenRadar contains a small, localized Douyin integration under
`kenradar/vendor/douyin_downloader/`. The files in that directory have the
following provenance.

## Third-party algorithm implementations

- `kenradar/vendor/douyin_downloader/abogus.py` is adapted from the `f2`
  project by Johnserf-Seed. The upstream project is licensed under the Apache
  License 2.0. Its original attribution header is retained in the source.
  Upstream: <https://github.com/Johnserf-Seed/f2>
- `kenradar/vendor/douyin_downloader/xbogus.py` is adapted from
  `Douyin_TikTok_Download_API` by Evil0ctal. It is licensed under the Apache
  License 2.0 and retains the upstream copyright and license header.
  Upstream: <https://github.com/Evil0ctal/Douyin_TikTok_Download_API>

## KenRadar integration code

The following files are KenRadar integration and packaging code. They are
licensed with KenRadar under the Apache License 2.0; they call the attributed
algorithm implementations above but are not claimed to be copies of those
upstream projects:

- `kenradar/vendor/douyin_downloader/__init__.py`
- `kenradar/vendor/douyin_downloader/api_client.py`
- `kenradar/vendor/douyin_downloader/browser_resolver.py`
- `kenradar/vendor/douyin_downloader/file_manager.py`

