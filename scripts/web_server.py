"""Loopback-only API; never serves secrets.env."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import json,math,os,sys,threading,re
from datetime import datetime
from scripts.collect import search,collect,APIError
from scripts.storage import merge_evidence,save_library
from scripts.build import safe
from scripts.llm import Client,LLMError,BudgetError
from scripts.converse import chat_evidence,recommend_book
class LocalThreadingHTTPServer(ThreadingHTTPServer):
 allow_reuse_address=False
PROJECT=Path(__file__).resolve().parent.parent;DEFAULT_LIB=PROJECT/"data"/"library";PAGE=PROJECT/"web"/"reading_desk.html";PORT=8765;MAX_REQUEST_BUDGET_USD=0.05

def find_save_root(project):
 for candidate in (project,*project.parents):
  if candidate.name.casefold()=="readnewbooktest":return candidate.resolve()
 return project.parent.resolve()
SAVE_ROOT=PROJECT.resolve();SETTINGS_FILE=PROJECT/"runtime"/"save_location.json"
def validate_save_dir(raw=None):
 value=str(raw or CURRENT_SAVE_DIR or DEFAULT_LIB).strip()
 path=Path(value).expanduser()
 if not path.is_absolute():raise ValueError("保存位置必须填写完整路径")
 path=path.resolve()
 if path==SAVE_ROOT or not path.is_relative_to(SAVE_ROOT):raise ValueError("为便于随程序文件夹一起移动，请选择程序文件夹内的路径："+str(SAVE_ROOT))
 return path
def load_save_dir():
 try:
  cfg=json.loads(SETTINGS_FILE.read_text(encoding="utf-8"));rel=Path(str(cfg.get("relative_path","")))
  candidate=(SAVE_ROOT/rel).resolve()
  if rel.is_absolute() or candidate==SAVE_ROOT or not candidate.is_relative_to(SAVE_ROOT):return DEFAULT_LIB.resolve()
  return candidate
 except (OSError,ValueError,TypeError,AttributeError):return DEFAULT_LIB.resolve()
def store_save_dir(path):
 global CURRENT_SAVE_DIR
 rel=path.relative_to(SAVE_ROOT).as_posix();SETTINGS_FILE.parent.mkdir(parents=True,exist_ok=True)
 tmp=SETTINGS_FILE.with_suffix(".tmp");tmp.write_text(json.dumps({"relative_path":rel},ensure_ascii=False,indent=2),encoding="utf-8");os.replace(tmp,SETTINGS_FILE);CURRENT_SAVE_DIR=path
CURRENT_SAVE_DIR=load_save_dir()
def choose_folder(initial):
 if os.name!="nt":raise ValueError("当前系统不支持本机文件夹选择")
 import ctypes
 from ctypes import wintypes
 class BROWSEINFO(ctypes.Structure):
  _fields_=[("hwndOwner",wintypes.HWND),("pidlRoot",ctypes.c_void_p),("pszDisplayName",wintypes.LPWSTR),("lpszTitle",wintypes.LPCWSTR),("ulFlags",wintypes.UINT),("lpfn",ctypes.c_void_p),("lParam",ctypes.c_ssize_t),("iImage",ctypes.c_int)]
 callback_type=ctypes.WINFUNCTYPE(ctypes.c_int,wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t)
 initial_text=ctypes.create_unicode_buffer(str(initial))
 send_message=ctypes.windll.user32.SendMessageW
 send_message.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t]
 send_message.restype=ctypes.c_ssize_t
 @callback_type
 def callback(hwnd,msg,wparam,lparam):
  if msg==1:send_message(hwnd,0x467,1,ctypes.addressof(initial_text))
  return 0
 display=ctypes.create_unicode_buffer(260);info=BROWSEINFO();info.hwndOwner=None;info.pidlRoot=None;info.pszDisplayName=ctypes.cast(display,wintypes.LPWSTR);info.lpszTitle="选择本地资料保存文件夹";info.ulFlags=0x0001|0x0010|0x0040;info.lpfn=ctypes.cast(callback,ctypes.c_void_p);info.lParam=0;info.iImage=0
 shell32=ctypes.windll.shell32;shell32.SHBrowseForFolderW.argtypes=[ctypes.POINTER(BROWSEINFO)];shell32.SHBrowseForFolderW.restype=ctypes.c_void_p
 pidl=shell32.SHBrowseForFolderW(ctypes.byref(info))
 if not pidl:return None
 buf=ctypes.create_unicode_buffer(32768);shell32.SHGetPathFromIDListW.argtypes=[ctypes.c_void_p,wintypes.LPWSTR];shell32.SHGetPathFromIDListW.restype=wintypes.BOOL
 ok=shell32.SHGetPathFromIDListW(pidl,buf);ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(pidl))
 if not ok or not buf.value:return None
 return Path(buf.value)
SESSIONS={};PERSISTED_SESSIONS={};LOCK=threading.Lock()
EMPTY={"claims":[],"debates":[],"methods":[],"reading":{"groups":[]},"verification":{"status":"not_run"}}
def response_data(d):return {"book":d.get("book",{}),"platform_recommendation":d.get("platform_recommendation") or {},"chapters":d.get("chapters",[]),"evidence":d.get("evidence",[]),"collection":d.get("collection",{}),"ai_recommendation":d.get("ai_recommendation")}
def parse_budget(raw):
 try:amount=float(raw)
 except (TypeError,ValueError):raise ValueError("预算格式不正确")
 if not math.isfinite(amount) or amount<=0 or amount>MAX_REQUEST_BUDGET_USD:raise ValueError("单次模型预算最多约 ¥0.50；页面按保守汇率折算为美元上限")
 return amount
def export_chat_file(book_id,title,turns):
 book_id=str(book_id or "").strip();title=str(title or "未命名书籍").strip()
 if not book_id or len(book_id)>80:raise ValueError("书籍编号无效")
 if len(title)>200:raise ValueError("书名过长")
 if not isinstance(turns,list) or len(turns)>500:raise ValueError("对话记录数量无效")
 rows=[]
 for turn in turns:
  if not isinstance(turn,dict) or turn.get("pending") or turn.get("error"):continue
  question=str(turn.get("question") or "").strip();result=turn.get("result")
  answer=str(result.get("answer") or "").strip() if isinstance(result,dict) else ""
  if not question or not answer:continue
  if len(question)>2000 or len(answer)>30000:raise ValueError("单条对话内容过长，无法导出")
  refs=result.get("used_ids",[]) if isinstance(result,dict) else []
  if not isinstance(refs,list):refs=[]
  refs=list(dict.fromkeys(str(i) for i in refs if re.fullmatch(r"(?:R|H|D)-[A-Za-z0-9_-]+",str(i))))
  refs.extend(i for i in re.findall(r"\[((?:R|H|D)-[A-Za-z0-9_-]+)\]",answer) if i not in refs)
  rows.append((question,answer,refs))
 if not rows:raise ValueError("当前没有可导出的已完成对话")
 safe_id=safe(book_id) or "book";safe_title=safe(title) or "未命名书籍"
 folder=(PROJECT/"exports"/safe_id).resolve()
 if not folder.is_relative_to(PROJECT.resolve()):raise ValueError("导出位置无效")
 folder.mkdir(parents=True,exist_ok=True)
 stamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f")
 target=folder/(safe_title+"_对话记录_"+stamp+".md")
 lines=["# 《"+title+"》对话记录","", "导出时间："+datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),""]
 for index,(question,answer,refs) in enumerate(rows,1):
  lines.extend(["## 问题 "+str(index),"",question,"","### 回答","",answer])
  if refs:lines.extend(["","引用证据编号："+"、".join(refs)])
  lines.append("")
 target.write_text("\n".join(lines),encoding="utf-8")
 return target,len(rows)
class Handler(BaseHTTPRequestHandler):
 server_version="ReadNewBookDesk/1.0"
 def log_message(self,fmt,*args):sys.stdout.write("HTTP "+str(args[1] if len(args)>1 else "")+" "+self.path.split("?")[0]+"\n")
 def send_json(self,obj,status=200):
  raw=json.dumps(obj,ensure_ascii=False).encode("utf-8");self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff");self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  path=urlparse(self.path).path
  if path=="/":
   raw=PAGE.read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(raw);return
  if path=="/api/health":self.send_json({"ok":True,"weread_configured":bool(os.getenv("WEREAD_API_KEY")),"model_configured":bool(os.getenv("DEEPSEEK_API_KEY"))});return
  if path=="/api/settings":self.send_json({"default_save_dir":str(DEFAULT_LIB.resolve()),"save_dir":str(CURRENT_SAVE_DIR),"save_root":str(SAVE_ROOT)});return
  self.send_error(404)
 def read_body(self,cap=200000):
  try:n=int(self.headers.get("Content-Length","0"))
  except ValueError:raise ValueError("格式无效")
  if n<1 or n>cap:raise ValueError("请求内容过大或为空")
  d=json.loads(self.rfile.read(n).decode("utf-8"))
  if not isinstance(d,dict):raise ValueError("格式无效")
  return d
 def do_POST(self):
  global CURRENT_SAVE_DIR
  origin=self.headers.get("Origin")
  port=self.server.server_port;allowed=("http://127.0.0.1:"+str(port),"http://localhost:"+str(port))
  if origin and origin not in allowed:self.send_json({"error":"请求来源无效"},403);return
  path=urlparse(self.path).path
  try:b=self.read_body(50000 if path=="/api/search" else 2000000 if path=="/api/export_chat" else 200000)
  except Exception:self.send_json({"error":"请求内容格式无效"},400);return
  try:
   if path=="/api/save_location":
    save_dir=validate_save_dir(b.get("save_dir"));save_dir.mkdir(parents=True,exist_ok=True);store_save_dir(save_dir)
    self.send_json({"save_dir":str(CURRENT_SAVE_DIR),"default_save_dir":str(DEFAULT_LIB.resolve())});return
   if path=="/api/pick_folder":
    initial=validate_save_dir(b.get("save_dir"));chosen=choose_folder(initial)
    if chosen is None:self.send_json({"cancelled":True});return
    chosen=validate_save_dir(str(chosen));self.send_json({"cancelled":False,"save_dir":str(chosen)});return
   if path=="/api/search":
    q=str(b.get("keyword","")).strip()
    if not q or len(q)>100:raise ValueError("请输入不超过 100 字的书名或作者")
    self.send_json({"books":search(q)});return
   if path=="/api/local_status":
    book_id=str(b.get("book_id"," ")).strip()
    if not book_id or len(book_id)>80:raise ValueError("书籍编号无效")
    save_dir=validate_save_dir(b.get("save_dir"));f=save_dir/safe(book_id)/"book.json"
    if not f.is_file():self.send_json({"saved":False});return
    d=json.loads(f.read_text(encoding="utf-8"));c=d.get("collection",{})
    self.send_json({"saved":True,"review_count":c.get("review_count",0),"highlight_count":c.get("highlight_count",0),"timestamp":c.get("timestamp")});return
   if path=="/api/export_chat":
    target,count=export_chat_file(b.get("book_id"),b.get("book_title"),b.get("turns"))
    self.send_json({"path":str(target),"turn_count":count});return
   if path=="/api/load":
    book_id=str(b.get("book_id"," ")).strip()
    if not book_id or len(book_id)>80:raise ValueError("请先选书")
    save_dir=validate_save_dir(b.get("save_dir"));f=save_dir/safe(book_id)/"book.json"
    if not f.is_file():raise ValueError("所选本地文件夹中没有这本书的已保存资料，请先采集")
    data=json.loads(f.read_text(encoding="utf-8"))
    with LOCK:SESSIONS[book_id]=data;PERSISTED_SESSIONS[book_id]=save_dir
    self.send_json({"data":response_data(data)});return
   if path=="/api/collect":
    book_id=str(b.get("book_id","")).strip()
    if not book_id or len(book_id)>80:raise ValueError("请先选书")
    save_to_disk=b.get("save_to_disk") is True
    save_dir=validate_save_dir(b.get("save_dir")) if save_to_disk else None
    data=collect(book_id);previous=(save_dir/safe(book_id)/"book.json") if save_to_disk else None
    if save_to_disk and previous.is_file():
     try:data=merge_evidence(json.loads(previous.read_text(encoding="utf-8")),data)
     except (ValueError,KeyError,TypeError):pass
    if save_to_disk:save_library(data,EMPTY,save_dir)
    with LOCK:
     SESSIONS[book_id]=data
     if save_to_disk:PERSISTED_SESSIONS[book_id]=save_dir
     else:PERSISTED_SESSIONS.pop(book_id,None)
    self.send_json({"data":response_data(data)});return
   if path=="/api/chat":
    book_id=str(b.get("book_id","")).strip();question=str(b.get("question","")).strip()
    if not book_id or not question or len(question)>2000:raise ValueError("请输入书籍和不超过 2000 字的问题")
    if b.get("allow_model_upload") is not True:raise PermissionError("请先确认允许把本书样本发送给 DeepSeek")
    with LOCK:data=SESSIONS.get(book_id)
    if data is None:
     save_dir=validate_save_dir(b.get("save_dir"));f=save_dir/safe(book_id)/"book.json"
     if not f.is_file():raise ValueError("请先采集这本书")
     data=json.loads(f.read_text(encoding="utf-8"))
    c=Client(model=os.getenv("DEEPSEEK_MODEL","deepseek-chat"),base_url=os.getenv("DEEPSEEK_BASE_URL","https://api.deepseek.com"),budget_usd=parse_budget(b.get("budget_usd",0.05)),input_per_million=0.40,output_per_million=1.60,allow_upload=True)
    answer,ids=chat_evidence(data,question,c);self.send_json({"answer":answer,"used_ids":ids,"cost":c.stats()});return
   if path=="/api/recommend":
    book_id=str(b.get("book_id","")).strip();profile=str(b.get("profile",""))
    if not book_id or len(book_id)>80:raise ValueError("请先采集这本书")
    if len(profile)>1000:raise ValueError("阅读兴趣或目的不能超过 1000 字")
    if b.get("allow_model_upload") is not True:raise PermissionError("请先确认允许把本书样本发送给 DeepSeek")
    with LOCK:data=SESSIONS.get(book_id)
    if data is None:
     save_dir=validate_save_dir(b.get("save_dir"));f=save_dir/safe(book_id)/"book.json"
     if not f.is_file():raise ValueError("请先采集这本书")
     data=json.loads(f.read_text(encoding="utf-8"))
    c=Client(model=os.getenv("DEEPSEEK_MODEL","deepseek-chat"),base_url=os.getenv("DEEPSEEK_BASE_URL","https://api.deepseek.com"),budget_usd=parse_budget(b.get("budget_usd",0.05)),input_per_million=0.40,output_per_million=1.60,allow_upload=True)
    answer,ids,samples=recommend_book(data,profile,c);result={"answer":answer,"used_ids":ids,"samples":samples,"cost":c.stats()}
    with LOCK:persist_dir=PERSISTED_SESSIONS.get(book_id)
    if persist_dir:data["ai_recommendation"]=result;save_library(data,EMPTY,persist_dir)
    self.send_json(result);return
   self.send_error(404)
  except PermissionError as e:self.send_json({"error":str(e)},403)
  except ValueError as e:self.send_json({"error":str(e)},400)
  except BudgetError as e:self.send_json({"error":str(e)},402)
  except APIError as e:
   if str(e)=="缺少 WEREAD_API_KEY":self.send_json({"error":"未配置微信读书 API Key。请将 secrets.env 放在程序文件夹内，并重启工作台。"},503)
   else:self.send_json({"error":"微信读书请求失败，请检查 API 配置、网络和接口权限后重试。"},502)
  except LLMError as e:
   # LLMError messages are deliberately sanitized by scripts.llm; never log API keys or response bodies.
   sys.stdout.write("DeepSeek 安全错误类别："+str(e)+"\n");sys.stdout.flush()
   self.send_json({"error":str(e)},502)
  except Exception:self.send_json({"error":"处理失败；请查看程序文件夹中的本机日志"},500)
def serve():
 last_error=None
 for port in range(PORT,PORT+20):
  try:server=LocalThreadingHTTPServer(("127.0.0.1",port),Handler);print("工作台地址：http://127.0.0.1:"+str(port),flush=True);return server
  except OSError as e:last_error=e
 raise OSError("本机 8765–8784 端口都不可用，请关闭其他工作台后重试") from last_error
