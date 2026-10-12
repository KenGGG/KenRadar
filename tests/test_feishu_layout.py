import json
from kenradar.notification.feishu import build_kenradar_feishu_card, build_research_feishu_card


def test_digest_is_compact_and_links_remain_buttons():
    title='清华肖星：估值不是看过去，而是赌未来'
    card=build_kenradar_feishu_card('2026-10-12','15:00',[
        {'short_title':title,'short_summary':'简述'*300,'blogger_name':'太学TAIXUE',
         'publish_time':'2026-10-08 22:00','value_score':'4.2','recommended_action':'read',
         'detail_url':'https://example.com/正文.html','video_url':'https://www.douyin.com/video/123'}])
    text=json.dumps(card,ensure_ascii=False)
    assert text.count(title)==1
    assert '简述'*101 not in text
    assert '价值 4.2/5' in text
    elements=card['card']['elements']
    assert any(x['tag']=='note' for x in elements)
    buttons=next(x for x in elements if x['tag']=='action')['actions']
    assert [x['text']['content'] for x in buttons]==['原视频','阅读笔记']
    assert '%E6%AD%A3%E6%96%87' in buttons[1]['url']


def test_batch_status_never_hides_failed_items():
    stats={'fetched':129,'processed':127,'failed':2,'skipped':0,
           'creator_url':'https://www.douyin.com/user/fixture'}
    card=build_research_feishu_card('量化Quantgirl',stats,'https://example.com/notes/index.html')
    assert card['card']['header']['template']=='orange'
    assert '待重试 **2**' in card['card']['elements'][0]['text']['content']
    assert len(card['card']['elements'][1]['actions'])==2
    stats['failed']=0
    assert build_research_feishu_card('量化Quantgirl',stats,'https://example.com')['card']['header']['template']=='green'
