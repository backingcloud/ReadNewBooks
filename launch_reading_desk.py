"""D-drive-only launcher for the one-page reading desk."""
import os,sys,tempfile,subprocess
from pathlib import Path
from datetime import datetime
PROJECT=Path(__file__).resolve().parent
BASE=Path(os.environ.get("READNEWBOOK_HOME",PROJECT)).expanduser().resolve()
def find_data_root(base):
 for parent in (base,*base.parents):
  if parent.name.casefold()=="readnewbooktest":return parent.resolve()
 return base.parent.resolve()
DATA_ROOT=find_data_root(BASE)
_ALLOWED_WRITE_ROOTS=(BASE,DATA_ROOT)
if not PROJECT.is_relative_to(BASE):raise RuntimeError("程序目录必须位于运行目录之内")
os.chdir(PROJECT);sys.path.insert(0,str(PROJECT));sys.dont_write_bytecode=True
def load_local_env(path):
 allowed={"WEREAD_API_KEY","DEEPSEEK_API_KEY","DEEPSEEK_BASE_URL","DEEPSEEK_MODEL"}
 if not path.is_file():return
 for raw in path.read_text(encoding="utf-8-sig").splitlines():
  line=raw.strip()
  if not line or line.startswith("#") or "=" not in line:continue
  name,value=line.split("=",1);name=name.strip();value=value.strip()
  if name not in allowed:continue
  if len(value)>=2 and value[0]==value[-1] and value[0] in ("'",'"'):value=value[1:-1]
  if value and name not in os.environ:os.environ[name]=value
load_local_env(PROJECT/"secrets.env")
temp_dir=BASE/"runtime"/"temp";temp_dir.mkdir(parents=True,exist_ok=True)
for name in ("TEMP","TMP","TMPDIR"):os.environ[name]=str(temp_dir)
tempfile.tempdir=str(temp_dir);(BASE/"runtime"/"logs").mkdir(parents=True,exist_ok=True)
_log_file=(BASE/"runtime"/"logs"/"reading-desk.log").open("a",encoding="utf-8",buffering=1)
class _Tee:
 def __init__(self,console,log):self.console=console;self.log=log
 def write(self,value):self.console.write(value);self.log.write(value);return len(value)
 def flush(self):self.console.flush();self.log.flush()
 def isatty(self):return self.console.isatty()
sys.stdout=_Tee(sys.__stdout__,_log_file);sys.stderr=_Tee(sys.__stderr__,_log_file)
def ensure_path(path):
 if isinstance(path,int) or path is None:return
 target=Path(os.fsdecode(path)).resolve()
 if not any(target.is_relative_to(root) for root in _ALLOWED_WRITE_ROOTS):raise PermissionError("程序只能在便携包工作区及其子目录写入文件")
def audit(event,args):
 if event=="open":
  path,mode,flags=args
  if (mode and any(c in mode for c in "wax+")) or flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):ensure_path(path)
 elif event in ("os.mkdir","os.remove","os.rmdir","os.chmod","os.utime"):ensure_path(args[0])
 elif event in ("os.rename","os.link","os.symlink"):ensure_path(args[0]);ensure_path(args[1])
sys.addaudithook(audit)
from scripts.web_server import serve
server=serve();print(datetime.now().isoformat(),"LOCAL_SERVER_READY",flush=True)
url="http://127.0.0.1:"+str(server.server_port)+"/"
edge_candidates=[Path(os.environ.get("PROGRAMFILES(X86)","C:/Program Files (x86)"))/"Microsoft/Edge/Application/msedge.exe",Path(os.environ.get("PROGRAMFILES","C:/Program Files"))/"Microsoft/Edge/Application/msedge.exe"]
edge=next((p for p in edge_candidates if p.is_file()),None)
if edge:
 profile=BASE/"runtime"/"browser-profile";profile.mkdir(parents=True,exist_ok=True)
 flags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)|getattr(subprocess,"DETACHED_PROCESS",0)
 edge_log=BASE/"runtime"/"logs"/"edge-launch.log"
 with edge_log.open("a",encoding="utf-8") as output:
  subprocess.Popen([str(edge),"--user-data-dir="+str(profile),"--inprivate",url],stdout=output,stderr=output,creationflags=flags)
else:print("请在浏览器打开 "+url+"；程序缓存和日志保存在程序文件夹内。",flush=True)
try:server.serve_forever()
except KeyboardInterrupt:pass
finally:server.server_close()
