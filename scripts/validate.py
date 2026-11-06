import re

def validate(data, analysis):
    ids={e['id'] for e in data['evidence']}
    errors=[]
    if len(ids)!=len(data['evidence']):errors.append('重复证据 ID')
    for section,fields in [('claims',['support_ids','counter_ids']),('methods',['evidence_ids'])]:
        for idx,item in enumerate(analysis.get(section,[])):
            for field in fields:
                for ref in item.get(field,[]):
                    if ref not in ids: errors.append(f'{section}[{idx}] 引用不存在: {ref}')
            main='support_ids' if section=='claims' else 'evidence_ids'
            if not item.get(main):errors.append(f'{section}[{idx}] 缺少正向证据')
    for i,debate in enumerate(analysis.get('debates',[])):
        for pos in debate.get('positions',[]):
            for ref in pos.get('evidence_ids',[]):
                if ref not in ids:errors.append(f'debates[{i}] 无效引用: {ref}')
    return errors

def confidence(item, evidence):
    lookup={e['id']:e for e in evidence}
    refs=[lookup[x] for x in item.get('support_ids',item.get('evidence_ids',[])) if x in lookup]
    reviews=[r for r in refs if r['type'] in ('review','discussion')]
    unique=len({r['id'] for r in reviews})
    has_highlight=any(r['type']=='highlight' for r in refs)
    opposed=bool(item.get('counter_ids'))
    # Heuristic label, not statistical probability or verification of book content
    if unique>=4 and has_highlight and not opposed:return '中（多源二手证据，未核对原书）'
    if unique>=2:return '中低（二手证据）'
    return '低（证据有限）'
