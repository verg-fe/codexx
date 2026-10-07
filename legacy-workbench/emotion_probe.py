"""Pinned llama.cpp ABI for residual-stream probes, using existing Windows DLLs.

No model is loaded by import or --check-abi. Actual extraction is an explicit,
guarded operation performed only after native tasks have ended.
"""
import ctypes as C
import os
from pathlib import Path
import re
import numpy as np

PINNED_COMMIT='552f18f91'
P=C.c_void_p;I=C.c_int32;U=C.c_uint32;F=C.c_float;B=C.c_bool

class ModelParams(C.Structure):
    _fields_=[('devices',P),('tensor_buft_overrides',P),('n_gpu_layers',I),('split_mode',I),
              ('load_mode',I),('lazy_mode',I),('main_gpu',I),('tensor_split',P),
              ('progress_callback',P),('progress_callback_user_data',P),('kv_overrides',P),
              *[(x,B) for x in ('vocab_only','check_tensors','use_extra_bufts','no_host','no_alloc','load_mtp')]]

class ContextParams(C.Structure):
    _fields_=[*[(x,U) for x in ('n_ctx','n_batch','n_ubatch','n_seq_max','n_rs_seq','n_outputs_max','n_outputs_max_per_seq')],
              ('n_threads',I),('n_threads_batch',I),
              *[(x,I) for x in ('ctx_type','rope_scaling_type','pooling_type','attention_type','flash_attn_type')],
              *[(x,F) for x in ('rope_freq_base','rope_freq_scale','yarn_ext_factor','yarn_attn_factor','yarn_beta_fast','yarn_beta_slow')],
              ('yarn_orig_ctx',U),('defrag_thold',F),('cb_eval',P),('cb_eval_user_data',P),
              ('type_k',I),('type_v',I),('abort_callback',P),('abort_callback_data',P),
              *[(x,B) for x in ('embeddings','offload_kqv','no_perf','op_offload','swa_full','kv_unified')],
              ('samplers',P),('n_samplers',C.c_size_t),('ctx_other',P)]

class Batch(C.Structure):
    _fields_=[('n_tokens',I),('token',C.POINTER(I)),('embd',C.POINTER(F)),('pos',C.POINTER(I)),
              ('n_seq_id',C.POINTER(I)),('seq_id',C.POINTER(C.POINTER(I))),('logits',C.POINTER(C.c_int8))]


class ResidualProbe:
    def __init__(self,runtime,device):
        self.runtime=Path(runtime);self.device_name=device
        self.directories=[];self.model=None;self.context=None;self.error=None
        self.means={};self.norms={};self.device_array=None
        paths=[self.runtime]+[Path(x) for x in os.environ.get('PATH','').split(os.pathsep) if x]
        for path in paths:
            if path.is_dir():
                try:self.directories.append(os.add_dll_directory(str(path)))
                except OSError:pass
        self.llama=C.CDLL(str(self.runtime/'llama.dll'))
        self.ggml=C.CDLL(str(self.runtime/'ggml.dll'))
        self.base=C.CDLL(str(self.runtime/'ggml-base.dll'))
        def bind(lib,name,args,result):
            fn=getattr(lib,name);fn.argtypes=args;fn.restype=result;return fn
        self.mp=bind(self.llama,'llama_model_default_params',[],ModelParams)
        self.cp=bind(self.llama,'llama_context_default_params',[],ContextParams)
        self.backend_init=bind(self.llama,'llama_backend_init',[],None)
        self.load_backends=bind(self.ggml,'ggml_backend_load_all_from_path',[C.c_char_p],None)
        self.device=bind(self.ggml,'ggml_backend_dev_by_name',[C.c_char_p],P)
        self.load_model=bind(self.llama,'llama_model_load_from_file',[C.c_char_p,ModelParams],P)
        self.load_context=bind(self.llama,'llama_init_from_model',[P,ContextParams],P)
        self.free_model=bind(self.llama,'llama_model_free',[P],None)
        self.free_context=bind(self.llama,'llama_free',[P],None)
        self.get_vocab=bind(self.llama,'llama_model_get_vocab',[P],P)
        self.get_layers=bind(self.llama,'llama_model_n_layer',[P],I)
        self.get_dimensions=bind(self.llama,'llama_model_n_embd',[P],I)
        self.tokenize=bind(self.llama,'llama_tokenize',[P,C.c_char_p,I,C.POINTER(I),I,B,B],I)
        self.decode=bind(self.llama,'llama_decode',[P,Batch],I)
        self.memory=bind(self.llama,'llama_get_memory',[P],P)
        self.clear=bind(self.llama,'llama_memory_clear',[P,B],None)
        self.name=bind(self.base,'ggml_get_name',[P],C.c_char_p)
        self.elements=bind(self.base,'ggml_nelements',[P],C.c_int64)
        self.rows=bind(self.base,'ggml_nrows',[P],C.c_int64)
        self.contiguous=bind(self.base,'ggml_is_contiguous',[P],B)
        self.read_tensor=bind(self.base,'ggml_backend_tensor_get',[P,P,C.c_size_t,C.c_size_t],None)
        self.callback=C.CFUNCTYPE(B,P,B,P)(self._capture)

    def abi_check(self):
        mp,cp=self.mp(),self.cp()
        if not (64<=cp.n_ctx<=1048576 and 1<=cp.n_batch<=1048576 and 0<=cp.type_k<=100
                and cp.cb_eval is None and cp.ctx_other is None):
            raise RuntimeError('llama.cpp ABI 默认值异常，未加载权重。')
        return {'model_params_bytes':C.sizeof(ModelParams),'context_params_bytes':C.sizeof(ContextParams),
                'batch_bytes':C.sizeof(Batch),'default_context':cp.n_ctx,'default_batch':cp.n_batch,
                'model_loaded':False}

    def open(self,path):
        self.abi_check();self.load_backends(os.fsencode(self.runtime));self.backend_init()
        device=self.device(self.device_name.encode())
        if not device:raise RuntimeError('指定的 GPU 后端设备不可用。')
        self.device_array=(P*2)(device,None)
        mp=self.mp();mp.devices=C.cast(self.device_array,P);mp.n_gpu_layers=-1;mp.load_mode=0;mp.load_mtp=False
        self.model=self.load_model(os.fsencode(path),mp)
        if not self.model:raise RuntimeError('残差提取器加载模型失败。')
        self.dimensions=self.get_dimensions(self.model);self.layers=self.get_layers(self.model)
        self.layer_ids=list(range(max(1,self.layers//4),max(2,3*self.layers//4)))
        cp=self.cp();cp.n_ctx=512;cp.n_batch=512;cp.n_ubatch=512;cp.n_seq_max=1
        cp.n_threads=2;cp.n_threads_batch=6;cp.type_k=2;cp.type_v=2;cp.offload_kqv=True;cp.op_offload=True
        cp.cb_eval=C.cast(self.callback,P);cp.cb_eval_user_data=None
        self.context=self.load_context(self.model,cp)
        if not self.context:raise RuntimeError('残差提取上下文初始化失败。')
        self.vocab=self.get_vocab(self.model)

    def _capture(self,tensor,ask,user):
        try:
            match=re.fullmatch(rb'l_out-(\d+)',self.name(tensor) or b'')
            needed=bool(match and int(match[1]) in self.layer_ids)
            if ask:return needed
            if not needed:return True
            layer=int(match[1]);rows=self.rows(tensor);elements=self.elements(tensor)
            if rows!=self.token_count or elements!=rows*self.dimensions:
                raise RuntimeError('残差图的 token/维度不匹配，未使用不完整激活。')
            if C.cast(tensor,C.POINTER(I))[0]!=0 or not self.contiguous(tensor):
                raise RuntimeError('残差张量不是连续 F32，未提取。')
            values=np.empty((rows,self.dimensions),dtype=np.float32)
            self.read_tensor(tensor,values.ctypes.data,0,values.nbytes)
            selected=values[49:]
            self.means[layer]=selected.mean(axis=0,dtype=np.float64).astype(np.float32)
            self.norms[layer]=float(np.linalg.norm(selected,axis=1).mean())
            return True
        except Exception as error:
            self.error=error;return False

    def read(self,text):
        raw=text.encode('utf-8');tokens=(I*512)()
        n=self.tokenize(self.vocab,raw,len(raw),tokens,512,True,False)
        if not 50<n<=512:raise ValueError('每篇故事需为 51–512 token；不截断训练资料。')
        self.token_count=n;self.means={};self.norms={};self.error=None
        self.clear(self.memory(self.context),True)
        batch=Batch(n,tokens,None,None,None,None,None)
        status=self.decode(self.context,batch)
        if self.error:raise self.error
        if status!=0:raise RuntimeError('模型残差提取失败，返回 '+str(status))
        if sorted(self.means)!=self.layer_ids:raise RuntimeError('模型未返回全部所需层的残差。')
        return np.stack([self.means[x] for x in self.layer_ids]),np.array([self.norms[x] for x in self.layer_ids]),n

    def close(self):
        if self.context:self.free_context(self.context);self.context=None
        if self.model:self.free_model(self.model);self.model=None
        self.means.clear();self.norms.clear()
        for handle in reversed(self.directories):handle.close()
        self.directories.clear()
