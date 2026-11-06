import os,json,time,urllib.request,urllib.error,hashlib
from pathlib import Path

URL='https://i.weread.qq.com/api/agent/gateway'
VERSION=os.getenv('WEREAD_SKILL_VERSION','1.0.5')
class APIError(RuntimeError): pass

def gateway(api_name, **kwargs):
    key=os.getenv('WEREAD_API_KEY')
    if not key: raise APIError('缺少 WEREAD_API_KEY')
    payload={'api_name':api_name,'skill_version':VERSION,**kwargs}
    req=urllib.request.Request(URL,data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=25) as r: obj=json.load(r)
            if not isinstance(obj,dict): raise APIError('Unexpected API response')
            if obj.get('upgrade_info'): raise APIError('微信读书 Skill 需要升级: '+str(obj['upgrade_info']))
            if obj.get('errcode',0) not in (0,None): raise APIError(str(obj.get('errmsg',obj['errcode'])))
            return obj
        except (urllib.error.URLError,TimeoutError) as e:
            if attempt==2: raise APIError(f'请求失败: {e}') from e
            time.sleep(2**attempt)

def search(keyword,max_pages=5):
    out=[];seen=set();max_idx=0;cursors=set()
    for _ in range(max_pages):
        data=gateway('/store/search',keyword=keyword,scope=10,maxIdx=max_idx)
        items=[]
        for group in data.get('results',[]):
            for item in group.get('books',[]):
                b=item.get('bookInfo',{});book_id=str(b.get('bookId') or '')
                if book_id and book_id not in seen:
                    seen.add(book_id)
                    out.append({k:b.get(k) for k in ('bookId','title','author','intro','publisher','readerLink','deepLink','newRating','newRatingCount','newRatingDetail')})
                items.append(item)
        if not data.get('hasMore') or not items: break
        cursor=items[-1].get('searchIdx')
        if cursor is None or cursor in cursors or cursor==max_idx: break
        cursors.add(cursor);max_idx=cursor
    return out

def _review_like_count(entry,data):
    # Public review endpoints may omit likes; never substitute star rating.
    candidates=(data,entry.get('review',{}),entry)
    for obj in candidates:
        if not isinstance(obj,dict):continue
        for key in ('likeCount','likesCount','likedCount','agreeCount','praisedCount','upCount'):
            value=obj.get(key)
            if type(value) is int and value>=0:return value
    return None

def collect(book_id, targets=(25,25,25,25), include_discussions=True):
    book=gateway('/book/info',bookId=book_id)
    chapters=gateway('/book/chapterinfo',bookId=book_id)
    reviews=[]; seen=set(); failures=[]; recommend_info=None
    for typ,limit in zip((1,2,4,3),targets):
        max_idx=0; sync=0; cursors=set()
        for _ in range(15):
            if len([r for r in reviews if r['bucket']==typ])>=limit: break
            try: page=gateway('/review/list',bookId=book_id,reviewListType=typ,count=min(20,limit),maxIdx=max_idx,synckey=sync)
            except APIError as e: failures.append(f'review type {typ}: {e}');break
            if recommend_info is None:
                recommend_info={k:page[k] for k in ('deepVRecommendInfo','deepVRecommendValue','deepVUniqueCount') if page.get(k) is not None}
            items=page.get('reviews',[])
            if not items: break
            for entry in items:
                data=entry.get('review',{}).get('review',{})
                rid=str(data.get('reviewId') or hashlib.sha256(str(data).encode()).hexdigest()[:20])
                if rid in seen:continue
                seen.add(rid)
                reviews.append({'id':'R-'+rid,'type':'review','bucket':typ,'text':data.get('content',''),'star':data.get('star'),'finished':data.get('isFinish'),'like_count':_review_like_count(entry,data),'created':data.get('createTime'),'chapter':data.get('chapterName'),'source':'WeRead /review/list','book_id':book_id})
            cursor=(items[-1].get('idx',0),page.get('synckey',0))
            if cursor in cursors or cursor==(max_idx,sync):break
            cursors.add(cursor);max_idx,sync=cursor
            if not page.get('reviewsHasMore'):break
            time.sleep(.15)
    highlights=[]; discussions=[]
    try:
        popular=gateway('/book/bestbookmarks',bookId=book_id,chapterUid=0)
        for item in popular.get('items',[]):
            hid=str(item.get('bookmarkId') or hashlib.sha256(str(item).encode()).hexdigest()[:16])
            highlights.append({'id':'H-'+hid,'type':'highlight','text':item.get('markText',''),'count':item.get('totalCount'),'chapter_uid':item.get('chapterUid'),'range':item.get('range'),'source':'WeRead /book/bestbookmarks','book_id':book_id})
        if include_discussions:
            for h in highlights[:8]:
                if h.get('chapter_uid') is None or not h.get('range'):continue
                try:
                    d=gateway('/book/readreviews',bookId=book_id,chapterUid=h['chapter_uid'],reviews=[{'range':h['range'],'count':10}])
                    for group in d.get('reviews',[]):
                        for entry in group.get('pageReviews',[]):
                            r=entry.get('review',{})
                            if r.get('content'):
                                discussions.append({'id':'D-'+str(entry.get('reviewId') or hashlib.sha256(str(r).encode()).hexdigest()[:16]),'type':'discussion','text':r['content'],'highlight_id':h['id'],'source':'WeRead /book/readreviews','book_id':book_id})
                except APIError as e:failures.append('discussion: '+str(e))
                time.sleep(.15)
    except APIError as e: failures.append('highlights: '+str(e))
    info=book.get('bookInfo',book.get('book',book))
    return {'book':{'bookId':book_id,'title':info.get('title',''), 'author':info.get('author',''),'intro':info.get('intro',''),'publisher':info.get('publisher',''),'readerLink':info.get('readerLink'),'deepLink':info.get('deepLink'),'newRating':info.get('newRating'),'newRatingCount':info.get('newRatingCount'),'newRatingDetail':info.get('newRatingDetail')},'platform_recommendation':recommend_info or {},'chapters':chapters.get('chapters',[]),'evidence':reviews+highlights+discussions,'collection':{'review_count':len(reviews),'highlight_count':len(highlights),'discussion_count':len(discussions),'warnings':failures,'timestamp':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'sampling':'推荐/不行/一般/最新分层采样；不代表全部评论'}}
