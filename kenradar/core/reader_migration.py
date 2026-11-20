"""Reuse saved analysis and source text when upgrading historical note layout."""
from copy import deepcopy
import re

from kenradar.core.reader_contract import usable_overview


def upgrade_saved_reader_analysis(data, transcript):
    result = deepcopy(data)
    if data.get('reader_contract') == 'reader-v3':
        return result
    overview = str(data.get('brief_summary') or data.get('overview') or '').strip()
    if not usable_overview(overview):
        raise ValueError('已有综述不可用，不能用错误占位转换为成功笔记')
    paragraphs = [overview]
    for section in data.get('content_sections') or []:
        if isinstance(section, dict) and usable_overview(section.get('content')):
            body = section['content'].strip()
            if body not in overview:
                paragraphs.append(body)
    # Map existing headings back to literal ASR anchors. Body text is always
    # assembled from the source so incomplete old corrections cannot omit it.
    positions = [i for i, char in enumerate(transcript) if re.match(r'\w', char)]
    source = ''.join(transcript[i] for i in positions)
    headings, search_from = [], 0
    for section in data.get('corrected_transcript_sections') or []:
        if not isinstance(section, dict) or not str(section.get('title') or '').strip():
            continue
        text = re.sub(r'[^\w]', '', str(section.get('content') or ''))
        matches = []
        for offset in (0, 16, 32, 48, 64, 96):
            anchor = text[offset:offset+16]
            if len(anchor) < 12:
                continue
            found = source.find(anchor, search_from)
            if found >= 0 and found - offset >= search_from:
                matches.append(found-offset)
        if matches:
            found = min(matches)
            start = positions[found]
            boundary = max(transcript.rfind(mark, 0, start) for mark in ('。', '！', '？', '\n')) + 1
            if start-boundary <= 100 and (not headings or boundary > headings[-1][0]):
                start = boundary
            if not headings or start > headings[-1][0]:
                headings.append((start, str(section['title']).strip()))
                search_from = found+1
    if not headings:
        raise ValueError('原有小标题无法可靠映射到转录，需单独核对')
    headings[0] = (0, headings[0][1])
    sections = []
    for i, (start, title) in enumerate(headings):
        end = headings[i+1][0] if i+1 < len(headings) else len(transcript)
        content = re.sub(r'([，。！？；：])\1+', r'\1', transcript[start:end].strip())
        if content:
            sections.append({'title': title, 'content': content})
    result.update(reader_contract='reader-v3', overview='\n\n'.join(paragraphs),
        brief_summary='\n\n'.join(paragraphs), corrected_transcript_sections=sections,
        content_sections=[], format_migration='reader-v3-20261027')
    return result
