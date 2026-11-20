import json
from kenradar.core.config import AppConfig
from kenradar.core.organizer import ContentOrganizer


def test_reader_batches_every_paragraph_and_reuses_checkpoints(tmp_path, monkeypatch):
    cfg = AppConfig({'ai': {'organizer': {'reader_chunk_chars': 1100, 'reader_checkpoint_dir': str(tmp_path)}}}, tmp_path/'config/c.yaml')
    organizer = ContentOrganizer(cfg)
    transcript = ''.join(f'第{i}段来源。' * 150 for i in range(7))
    prompts = []
    def call(provider, key, prompt):
        prompts.append(prompt)
        return json.dumps({'brief_title': '应用标题', 'overview': '应用综述'+str(len(prompts)), 'sections': [{'title': '应用小标题', 'start_paragraph': 1}]}, ensure_ascii=False)
    monkeypatch.setattr(organizer, '_organize_with_provider', call)
    from kenradar.core.reader_contract import source_paragraphs, assemble_reader_result
    paragraphs = source_paragraphs(transcript)
    provider = {'name': 'fixture', 'model': 'actual-configured'}
    data = organizer._reader_batched_data('原题', paragraphs, provider, '')
    assert len(prompts) > 2
    assert max(map(len, prompts[:-1])) < 3000
    result = json.loads(assemble_reader_result(data, '原题', paragraphs))
    joined = ''.join(x['content'].replace('\n', '') for x in result['corrected_transcript_sections'])
    assert joined == transcript
    assert data['reader_coverage']['source_paragraphs'] == len(paragraphs)
    assert data['reader_coverage']['complete'] is True
    before = len(prompts)
    assert organizer._reader_batched_data('原题', paragraphs, provider, '') == data
    assert len(prompts) == before
