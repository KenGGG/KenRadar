from kenradar.web.routes.tasks import _task_results


def test_git_paths_are_batched_below_windows_command_limit():
    from kenradar.publishing.github_sync import GithubSyncManager
    paths=[f'notes/douyin/中文博主/{i}_'+('长标题'*30)+'.html' for i in range(1000)]
    batches=list(GithubSyncManager._path_batches(paths))
    assert len(batches)>1
    assert [path for batch in batches for path in batch]==paths
    assert all(sum(len(p.encode('utf-16-le'))//2+4 for p in batch)<=12000 for batch in batches)


def test_hermes_gets_ready_public_url_and_local_fallback():
    row={'status':'success','stats_json':{'status':'success','aweme_id':'123',
        'public_url':'https://example.github.io/notes/123.html','public_url_ready':True,'github_synced':True}}
    result=_task_results(row)[0]
    assert result['url']==row['stats_json']['public_url']
    assert result['public_url_ready'] and result['github_synced']
    row['stats_json']['public_url_ready']=False
    assert _task_results(row)[0]['url'].startswith('/content?')
    row['status']='failed'
    assert _task_results(row)==[]
