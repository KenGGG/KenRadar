from kenradar.web.routes.tasks import _task_results


def test_podcast_results_use_platform_and_skip_failed_items():
    row = {'status': 'success', 'stats_json': {'platform': 'xiaoyuzhou', 'items': [
        {'status': 'success', 'content_id': 'episode1', 'title': '播客'},
        {'status': 'skipped', 'content_id': 'episode2'},
        {'status': 'failed', 'content_id': 'episode3'},
    ]}}
    results = _task_results(row)
    assert [r['url'] for r in results] == [
        '/content?platform=xiaoyuzhou&external_id=episode1',
        '/content?platform=xiaoyuzhou&external_id=episode2',
    ]
    assert results[0]['title'] == '播客'


def test_video_result_and_unfinished_tasks():
    stats = {'aweme_id': '123', 'status': 'skipped', 'title': '视频'}
    assert _task_results({'status': 'success', 'stats_json': stats}) == [
        {'title': '视频', 'url': '/content?platform=douyin&external_id=123'}]
    assert _task_results({'status': 'running', 'stats_json': stats}) == []
    assert _task_results({'status': 'success'}) == []
