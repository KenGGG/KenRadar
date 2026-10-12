"""Render local illustrative previews from the actual Feishu card payloads."""
from pathlib import Path
from html import escape
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from markdown_it import MarkdownIt
from kenradar.notification.feishu import build_kenradar_feishu_card, build_research_feishu_card


def main():
    root=Path('data/test-migration/feishu-layout')
    root.mkdir(parents=True,exist_ok=True)
    proof=json.loads(Path('data/test-migration/hermes-ai-repair/published-result.json').read_text(encoding='utf-8'))
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    digest=build_kenradar_feishu_card(now.strftime('%Y-%m-%d'),now.strftime('%H:%M'),[
        {'short_title':'清华肖星：估值不是看过去，而是赌未来',
         'short_summary':'企业价值来自未来自由现金流，而非历史利润。能长期创造超额价值的关键，是竞争优势与护城河。',
         'blogger_name':'太学TAIXUE','publish_time':'2026-10-08',
         'video_url':'https://www.douyin.com/video/7694252203724262682',
         'detail_url':proof['public_url']}])
    batch=build_research_feishu_card('量化Quantgirl',{'fetched':129,'processed':129,'skipped':0,'failed':0,
        'creator_url':'https://www.douyin.com/user/MS4wLjABAAAA_C2VXT1FT00QgTcH9v14uws4BQRaUXjKMP6JOD-UvWA',
        'note':'129 篇公开笔记均可访问；其中 3 条无口播短片已如实说明。'},
        'https://kenggg.github.io/KenRadar-pages/notes/douyin/%E9%87%8F%E5%8C%96Quantgirl/index.html',
        title='量化Quantgirl｜笔记发布成功')
    cards=[digest,batch]
    (root/'card-payloads.json').write_text(json.dumps(cards,ensure_ascii=False,indent=2),encoding='utf-8')
    md=MarkdownIt('commonmark',{'html':False,'breaks':True})
    output=[]
    for payload in cards:
        card=payload['card']
        body=[]
        for element in card['elements']:
            tag=element['tag']
            if tag=='div': body.append('<section>'+md.render(element['text']['content'])+'</section>')
            elif tag=='hr': body.append('<hr>')
            elif tag=='note': body.append('<aside>'+escape(' '.join(x['content'] for x in element['elements']))+'</aside>')
            elif tag=='action':
                body.append('<nav>'+''.join('<a class="'+escape(a['type'])+'" href="'+escape(a['url'],quote=True)+'">'+escape(a['text']['content'])+'</a>' for a in element['actions'])+'</nav>')
        output.append('<article><header class="'+card['header']['template']+'">'+escape(card['header']['title']['content'])+'</header><div class="body">'+''.join(body)+'</div></article>')
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KenRadar 飞书消息排版预览</title><style>
    *{box-sizing:border-box}body{background:#f5f6f8;color:#20252e;font:15px/1.65 "Segoe UI","Microsoft YaHei",sans-serif;margin:0;padding:30px}h1{font-size:23px;margin:0 0 8px}.intro{color:#646b77;margin-bottom:26px}.cards{display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap}article{width:440px;max-width:100%;border:1px solid #dfe3e8;border-radius:12px;background:white;overflow:hidden;box-shadow:0 4px 16px #20252e08}header{padding:17px 20px;font-size:17px;font-weight:650}.blue{background:#e8f0fe;color:#245bba}.green{background:#e9f6ee;color:#267347}.orange{background:#fff1df;color:#9c5b17}.body{padding:18px 20px}section p{margin:0 0 14px}hr{border:0;border-top:1px solid #e8ebef;margin:17px 0}aside{font-size:12px;line-height:1.6;color:#78818f;margin:10px 0 15px}nav{display:flex;gap:10px;flex-wrap:wrap}nav a{padding:7px 15px;border:1px solid #d6dce5;border-radius:6px;text-decoration:none;color:#3e4856;font-size:14px}nav .primary{background:#3370ff;border-color:#3370ff;color:white}
    </style><h1>飞书消息排版预览</h1><p class="intro">根据实际卡片 JSON 渲染的本地示意。飞书客户端的字体与间距可能有所不同；此预览不发送消息。</p><div class="cards">'''+''.join(output)+'</div></html>'
    (root/'preview.html').write_text(html,encoding='utf-8')
    print(root/'preview.html')


if __name__=='__main__': main()
