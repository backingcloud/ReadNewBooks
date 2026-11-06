"""Safe-ish local persistence, incremental merges and non-destructive Vault syncing."""
import json,os,shutil,hashlib
from pathlib import Path
from datetime import datetime,timezone
from .build import safe

def atomic_json(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,p)

def merge_evidence(previous,current):
    if previous['book']['bookId']!=current['book']['bookId']:raise ValueError('不能合并不同 bookId 的书')
    merged={e['id']:e for e in previous.get('evidence',[])}
    added=[];changed=[]
    for e in current.get('evidence',[]):
        if e['id'] not in merged:added.append(e['id'])
        elif merged[e['id']]!=e:changed.append(e['id'])
        merged[e['id']]=e
    data={**current,'evidence':list(merged.values())}
    data['collection']={**current.get('collection',{}),'incremental':{'added_ids':added,'updated_ids':changed,'total':len(merged),'note':'保留本地旧证据；接口采样范围有限，并不能保证获取全部新增评论'}}
    return data

def _same(a,b):return a.is_file() and b.is_file() and hashlib.sha256(a.read_bytes()).digest()==hashlib.sha256(b.read_bytes()).digest()

def sync_vault(book_folder,vault):
    source=Path(book_folder).resolve();root=Path(vault).expanduser().resolve()
    if not (root/'.obsidian').is_dir():raise ValueError('必须选择包含 .obsidian 的已有 Obsidian Vault')
    target=root/'Collective Reading'/safe(source.name);target.mkdir(parents=True,exist_ok=True)
    changed=[];unchanged=[]
    for p in source.rglob('*'):
        if not p.is_file():continue
        dest=target/p.relative_to(source)
        dest.parent.mkdir(parents=True,exist_ok=True)
        if _same(p,dest):unchanged.append(str(dest.relative_to(root)));continue
        changed.append((p,dest))
    backup=None
    if any(dest.exists() for _,dest in changed):
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=root/'Collective Reading Backups'/safe(source.name)/stamp
        for _,dest in changed:
            if dest.exists():
                old=backup/dest.relative_to(target);old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,old)
    for p,dest in changed:shutil.copy2(p,dest)
    return {'target':str(target),'updated':[str(d.relative_to(root)) for _,d in changed],'unchanged':unchanged,'backup':str(backup) if backup else None}

def save_library(data,analysis,library_dir):
    p=Path(library_dir)/safe(data['book']['bookId']);p.mkdir(parents=True,exist_ok=True)
    atomic_json(p/'book.json',data);atomic_json(p/'analysis.json',analysis)
    return p

def load_library(library_dir):
    books=[]
    for folder in Path(library_dir).glob('*'):
        if (folder/'book.json').is_file() and (folder/'analysis.json').is_file():
            try:
                d=json.loads((folder/'book.json').read_text(encoding='utf-8'))
                a=json.loads((folder/'analysis.json').read_text(encoding='utf-8'))
                books.append({'data':d,'analysis':a,'path':folder})
            except (json.JSONDecodeError,KeyError):pass
    return sorted(books,key=lambda b:b['data']['book'].get('title',''))

def delete_cache(library_dir,book_id=None):
    root=Path(library_dir).resolve()
    if not root.is_dir():return
    if book_id:
        target=(root/safe(book_id)).resolve()
        if target.parent!=root:raise ValueError('路径越界')
        if target.is_dir():shutil.rmtree(target)
    else:
        for item in root.iterdir():
            if item.is_dir():shutil.rmtree(item)
