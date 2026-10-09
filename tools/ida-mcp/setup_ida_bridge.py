from pathlib import Path
import ast,json,secrets,shutil,datetime
root=Path(r'D:\LocalCodex');out=root/'tools/ida-mcp';out.mkdir(parents=True,exist_ok=True)
up=Path(r'G:\r0env2026\reference\r0idamcp');tree=ast.parse((up/'r0idamcp.py').read_text(encoding='utf-8'))
tools=[]
for n in tree.body:
    if isinstance(n,ast.FunctionDef) and any(isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and isinstance(d.func.value,ast.Name) and d.func.value.id=='mcp' for d in n.decorator_list):
        props={};required=[];defaults=[None]*(len(n.args.args)-len(n.args.defaults))+n.args.defaults
        for arg,default in zip(n.args.args,defaults):
            ann=ast.unparse(arg.annotation) if arg.annotation else 'str'
            typ='integer' if ann.startswith(('int','Annotated[int')) else 'boolean' if ann.startswith(('bool','Annotated[bool')) else 'string'
            props[arg.arg]={'type':typ}
            if arg.annotation:
                for field in ast.walk(arg.annotation):
                    if isinstance(field,ast.Call) and isinstance(field.func,ast.Name) and field.func.id=='Field':
                        for keyword in field.keywords:
                            if keyword.arg=='description' and isinstance(keyword.value,ast.Constant):props[arg.arg]['description']=keyword.value.value
            if default is None:required.append(arg.arg)
        read=not n.name.startswith(('rename','set_','declare_','patch','create_'))
        tools.append({'name':n.name,'description':ast.get_docstring(n) or n.name,'inputSchema':{'type':'object','properties':props,'required':required},'annotations':{'readOnlyHint':read,'destructiveHint':not read,'openWorldHint':False}})
class Compat(ast.NodeTransformer):
    def visit_Call(self,n):
        self.generic_visit(n)
        if isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='ida_hexrays' and n.func.attr=='decompile_func' and n.args:
            n.args[0]=ast.Call(func=ast.Attribute(value=ast.Name(id='idaapi',ctx=ast.Load()),attr='get_func',ctx=ast.Load()),args=[n.args[0]],keywords=[])
        return n
    def visit_ImportFrom(self,n):
        if n.module in ('fastmcp','pydantic'):return None
        if n.module=='typing':n.names=[a for a in n.names if a.name!='Annotated']
        return n
    def visit_FunctionDef(self,n):
        self.generic_visit(n);n.returns=None
        for a in n.args.args+n.args.kwonlyargs:a.annotation=None
        return n
    def visit_AnnAssign(self,n):
        self.generic_visit(n)
        if n.value is None:return None
        return ast.copy_location(ast.Assign(targets=[n.target],value=n.value),n)
    def visit_ClassDef(self,n):
        self.generic_visit(n)
        if not n.body:n.body=[ast.Pass()]
        return n
tree.body=[n for n in tree.body if not (isinstance(n,ast.FunctionDef) and n.name in ('startASYNC','start_server','PLUGIN_ENTRY')) and not (isinstance(n,ast.ClassDef) and n.name in ('r0Plugmod','r0mcp'))]
tree=Compat().visit(tree);ast.fix_missing_locations(tree)
generated=ast.unparse(tree)
generated=generated.replace('ida_hexrays.decompile_func(address, error, ida_hexrays.DECOMP_WARNINGS)','ida_hexrays.decompile_func(idaapi.get_func(address), error, ida_hexrays.DECOMP_WARNINGS)')
generated=generated.replace('ida_hexrays.decompile_func(function_address, error, ida_hexrays.DECOMP_WARNINGS)','ida_hexrays.decompile_func(idaapi.get_func(function_address), error, ida_hexrays.DECOMP_WARNINGS)')
assert 'ida_hexrays.decompile_func(idaapi.get_func(' in generated
cfg=out/'connection.json'
if not cfg.exists():cfg.write_text(json.dumps({'url':'http://127.0.0.1:26868','token':secrets.token_urlsafe(32)}),encoding='utf-8')
prefix='''# Local Python 3.8 compatibility adapter for r0idamcp; see bundled upstream LICENSE.
class FastMCP:
    def __init__(self, **kwargs):self.functions={}
    def tool(self):
        def register(f):self.functions[f.__name__]=f;return f
        return register
'''
suffix='''
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
_config=json.loads(Path(r"D:\\LocalCodex\\tools\\ida-mcp\\connection.json").read_text(encoding="utf-8"))
class _Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        if self.headers.get("Authorization")!="Bearer "+_config["token"]:
            self.send_error(403);return
        try:
            size=int(self.headers.get("Content-Length","0"))
            if not 0<size<1000000:raise ValueError("Invalid request size")
            req=json.loads(self.rfile.read(size))
            result=mcp.functions[req["name"]](**req.get("arguments",{}))
            answer={"result":result}
        except Exception as exc:answer={"error":str(exc)}
        raw=json.dumps(answer,ensure_ascii=False).encode("utf-8")
        self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
_server=None
def start_server():
    global _server
    if _server is None:
        _server=ThreadingHTTPServer(("127.0.0.1",26868),_Handler)
        threading.Thread(target=_server.serve_forever,daemon=True).start()
        print("Codexx IDA bridge ready: 127.0.0.1:26868")
class CodexxIDA(idaapi.plugin_t):
    flags=idaapi.PLUGIN_FIX | idaapi.PLUGIN_KEEP
    comment="Local r0idamcp compatibility bridge"
    help=""
    wanted_name="Codexx IDA MCP"
    wanted_hotkey=""
    def init(self):
        try:start_server();return idaapi.PLUGIN_KEEP
        except Exception as exc:print("Codexx IDA bridge: "+str(exc));return idaapi.PLUGIN_SKIP
    def run(self,arg):start_server()
    def term(self):pass
def PLUGIN_ENTRY():return CodexxIDA()
'''
plugin=Path(r'G:\IDA Pro v7.6.210427\plugins\codexx_ida_mcp.py')
backup=root/'backups'/('ida-mcp-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir(parents=True)
if plugin.exists():shutil.copy2(plugin,backup/plugin.name)
plugin.write_text(prefix+generated+suffix,encoding='utf-8')
shutil.copy2(up/'LICENSE',out/'LICENSE-r0idamcp')
(out/'tools.json').write_text(json.dumps(tools,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'plugin':str(plugin),'tool_count':len(tools),'backup':str(backup)}))
