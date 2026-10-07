"""Personal Codex native Windows desktop client, with a private local model."""
import difflib
import json
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time
import traceback
import uuid
from token_speed import TokenSpeed
from proxy_service import load_proxy_settings, save_proxy_settings, validate_proxy_settings
from core import WORK_CONTEXT_OPTIONS, MAX_WORK_CONTEXT, configured_vision
from task_artifacts import TaskArtifacts, FileLocks
from directive_profiles import DIRECTIVE_MODES, DEFAULT_CUSTOM_TAG, selected_directive, build_directive
from emotion_vectors import EMOTION_MODES,emotion_state,emotion_hint,MIN_EMOTION_STRENGTH,MAX_EMOTION_STRENGTH
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
from conversations import ConversationStore
from thought_log import TraceTail, list_traces, trace_label, export_trace, PHASE_LABELS, VIEW_CHARS
from core import (ROOT, MODEL, MODELS, BACKENDS, HISTORY_MODES, PERFORMANCE_MODES, DECODING_MODES, WORK_CONTEXT, WORK_COMPACT, selected_backend, selected_decoding, vision_file, model_directory, save_settings, MIN_CONTEXT, RpcClient, api, prepare,
                  start_model, stop_model, server_ready, selected_model, model_file, model_supports_vision, model_required_files,
                  context_limits, context_for, compact_for, active_model, kv_cache_location, GPU_CONTEXT_LIMIT,
                  runtime_matches_settings, engine_config, engine_limits, memory_instructions)
from core import refresh_gateway_for_current_app
from core import gateway_api
from generation_guard import GuardStore, guard_options
from session_workspaces import SessionWorkspaces

ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('blue')
BG = '#101317'
PANEL = '#191d23'
ACCENT = '#b9f176'
MUTED = '#98a2b3'
TEXT = '#e6e9ed'
DISPLAY_CHARS = 160000
CACHE_OPTIONS={'自动：按实际对话长度选择':'auto','显卡缓存：优先速度':'gpu','内存缓存：扩展上下文':'ram'}

class App(ctk.CTk):
    def __init__(self, smoke=False):
        super().__init__()
        self.title('我的 Codex · 本地编程工作台 · v37')
        self.geometry('1360x880')
        self.minsize(1060, 700)
        self.configure(fg_color=BG)
        self.settings = prepare()
        self.workspace_store=SessionWorkspaces(ROOT)
        self.session_workspace=self.workspace_store.create(self.settings)
        self.project = Path(self.session_workspace['project'])
        self.guard_seen=None
        self.events = queue.Queue()
        self.rpc = None
        self.thread_id = None
        self.turn_id = None
        self.artifact_task = None
        self.artifact_locks = FileLocks()
        self.steer_pending = False
        self.busy = False
        self.transcript = []
        self.open_path = None
        self.original = ''
        self.sessions = self.load_sessions()
        self.session_store = ConversationStore(ROOT)
        self.session_action_pending = False
        self.model_proc = None
        self.loading_model = False
        self.current_item = None
        self.last_speed = ''
        self.attachments = []
        self.message_buffers = {}
        self.turn_visible_output = False
        self.turn_started_at = None
        self.last_turn_tokens = None
        self.token_speed = TokenSpeed()
        self.speed_label = ''
        self.thought_reader = TraceTail()
        self.thought_paths = {}
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.build_sidebar()
        self.build_workspace()
        self.protocol('WM_DELETE_WINDOW', self.close_app)
        self.after(60, self.poll_events)
        self.after(500, self.refresh_status)
        self.after(250,self.poll_generation_guard)
        if '--resume-after-update' in sys.argv:self.after(800,self.restore_after_update)
        self.auto_launch_model = not smoke and '--no-auto-model' not in sys.argv
        if not smoke:
            threading.Thread(target=self.connect, daemon=True).start()

    def button(self, parent, text, command, **kw):
        return ctk.CTkButton(parent, text=text, command=command, height=36,
               fg_color=kw.pop('fg_color', '#262c35'), hover_color='#39424f',
               text_color=kw.pop('text_color', TEXT), corner_radius=8, **kw)

    def build_sidebar(self):
        side = ctk.CTkFrame(self, width=232, corner_radius=0, fg_color='#14181d')
        side.grid(row=0, column=0, sticky='nsew')
        side.grid_propagate(False)
        ctk.CTkLabel(side, text='◈  我的 Codex', text_color=ACCENT,
                     font=('Microsoft YaHei UI', 23, 'bold')).pack(anchor='w', padx=22, pady=(30, 4))
        ctk.CTkLabel(side, text='PERSONAL · LOCAL · PRIVATE', text_color=MUTED,
                     font=('Segoe UI', 10)).pack(anchor='w', padx=24, pady=(0, 28))
        self.button(side, '+  新对话', self.new_chat, fg_color=ACCENT,
                    text_color=BG).pack(fill='x', padx=18, pady=(0, 8))
        self.button(side, '打开项目文件夹', self.choose_project).pack(fill='x', padx=18, pady=4)
        self.button(side, '会话文件夹位置', self.choose_workspace_root).pack(fill='x', padx=18, pady=4)
        self.draft_button=self.button(side, '打开本轮文件与草稿', self.open_task_files)
        self.draft_button.pack(fill='x', padx=18, pady=4)
        self.project_label = ctk.CTkLabel(side, text=str(self.project), wraplength=190,
                     justify='left', text_color=MUTED, font=('Microsoft YaHei UI', 11))
        self.project_label.pack(anchor='w', padx=22, pady=(12, 22))
        ctk.CTkLabel(side, text='最近会话', text_color=MUTED,
                     font=('Microsoft YaHei UI', 11)).pack(anchor='w', padx=22)
        self.session_frame = ctk.CTkScrollableFrame(side, fg_color='transparent', height=340)
        self.session_frame.pack(fill='both', expand=True, padx=10, pady=8)
        self.undo_delete_button=self.button(side,'撤销上次删除',self.undo_delete_session)
        self.undo_delete_button.pack(fill='x',padx=18,pady=(0,6))
        self.render_sessions()
        bottom = ctk.CTkFrame(side, fg_color='#1d2520', corner_radius=12)
        bottom.pack(fill='x', padx=16, pady=20)
        self.sidebar_model = ctk.CTkLabel(bottom, text=MODELS[selected_model(self.settings)]['label'], text_color=ACCENT,
                     font=('Segoe UI', 13, 'bold'), wraplength=195, justify='left')
        self.sidebar_model.pack(anchor='w', padx=14, pady=(12, 2))
        self.sidebar_context = ctk.CTkLabel(bottom, text=f"RX 9070 / 16GB\n{self.settings['context']:,} token · 自动确认", justify='left',
                     text_color=MUTED, font=('Microsoft YaHei UI', 11))
        self.sidebar_context.pack(anchor='w', padx=14, pady=(0, 12))

    def build_workspace(self):
        main = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        main.grid(row=0, column=1, sticky='nsew', padx=24, pady=16)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(main, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        ctk.CTkLabel(head, text='本地编程工作台', font=('Microsoft YaHei UI', 20, 'bold')).pack(side='left')
        self.status = ctk.CTkLabel(head, text='正在连接…', text_color=MUTED)
        self.status.pack(side='right')
        self.tabs = ctk.CTkTabview(main, fg_color=PANEL,
                  segmented_button_selected_color='#33482d', segmented_button_selected_hover_color='#415b38')
        self.tabs.grid(row=1, column=0, sticky='nsew')
        for label in ['对话', '思考日志', '项目文件', '模型与性能']:
            self.tabs.add(label)
        chat = self.tabs.tab('对话')
        chat.grid_columnconfigure(0, weight=1)
        chat.grid_rowconfigure(0, weight=1)
        self.chat = ctk.CTkTextbox(chat, fg_color=PANEL, text_color=TEXT,
                   font=('Microsoft YaHei UI', 14), wrap='word', corner_radius=0)
        self.chat.grid(row=0, column=0, sticky='nsew', padx=14, pady=14)
        self.chat._textbox.configure(undo=False)
        self.chat.configure(state='disabled')
        self.append('◈ 新对话\n本会话文件夹：'+str(self.project)+'\n\n直接描述你想完成的工作；需要修改已有项目时，点击左侧“打开项目文件夹”。\n', save=False)
        composer = ctk.CTkFrame(chat, fg_color='#222831', corner_radius=12)
        composer.grid(row=1, column=0, sticky='ew', padx=14, pady=(0, 14))
        composer.grid_columnconfigure(0, weight=1)
        self.input = ctk.CTkTextbox(composer, height=100, fg_color='transparent',
                      font=('Microsoft YaHei UI', 14), wrap='word')
        self.input.grid(row=0, column=0, columnspan=3, sticky='ew', padx=10, pady=(8, 0))
        self.input.bind('<Control-Return>', lambda e: (self.send_prompt(), 'break')[1])
        self.effort = ctk.CTkOptionMenu(composer, values=['均衡思考', '深入思考', '快速思考'],
                          fg_color='#303742', button_color='#303742', width=125)
        self.effort.grid(row=1, column=0, sticky='w', padx=12, pady=10)
        self.attach_button = self.button(composer, '添加图片', self.attach_image, width=90)
        self.attach_button.grid(row=1, column=0, sticky='w', padx=(148, 0), pady=10)
        self.stop_button = self.button(composer, '停止', self.interrupt, width=76)
        self.stop_button.grid(row=1, column=1, padx=6, pady=10)
        self.send_button = self.button(composer, '发送  ↗', self.send_prompt, width=100,
                                      fg_color=ACCENT, text_color=BG)
        self.send_button.grid(row=1, column=2, padx=(6, 12), pady=10)
        self.steer_note=ctk.CTkLabel(composer,text='Ctrl+Enter 发送；生成中可提交引导。',anchor='w',
            font=('Microsoft YaHei UI',11),text_color=MUTED)
        self.steer_note.grid(row=2,column=0,columnspan=3,sticky='ew',padx=12,pady=(0,8))
        self.usage = ctk.CTkLabel(main, text='本地推理 · 文件按需读取 · 自动压缩 · KV 缓存复用',
                     text_color=MUTED, font=('Microsoft YaHei UI', 11))
        self.usage.grid(row=2, column=0, sticky='w', pady=(10, 0))
        self.build_files(self.tabs.tab('项目文件'))
        self.build_model(self.tabs.tab('模型与性能'))
        self.build_thought_log(self.tabs.tab('思考日志'))

    def build_thought_log(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)
        bar = ctk.CTkFrame(parent, fg_color='transparent')
        bar.grid(row=0,column=0,sticky='ew',padx=14,pady=12)
        self.thought_follow = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(bar,text='跟随最新请求',variable=self.thought_follow).pack(side='left',padx=(0,16))
        self.thought_picker = ctk.CTkOptionMenu(bar,values=['暂无记录'],command=self.choose_thought_log,
            width=250,fg_color='#303742',button_color='#303742')
        self.thought_picker.pack(side='left')
        self.thought_export_button = self.button(bar,'导出完整日志',self.export_thought_log,width=120)
        self.thought_export_button.pack(side='right',padx=4)
        self.button(bar,'打开日志目录',self.open_thought_directory,width=120).pack(side='right',padx=4)
        self.thought_status = ctk.CTkLabel(parent,text='等待生成记录。这里显示模型实际返回的内容，不代表固定完成百分比。',
            text_color=MUTED,anchor='w',justify='left')
        self.thought_status.grid(row=1,column=0,sticky='ew',padx=14,pady=(0,8))
        self.thought_box = ctk.CTkTextbox(parent,fg_color='#11161b',font=('Microsoft YaHei UI',13),wrap='word')
        self.thought_box.grid(row=2,column=0,sticky='nsew',padx=14,pady=(0,12))
        self.thought_box._textbox.configure(undo=False)
        self.thought_box.configure(state='disabled')
        ctk.CTkLabel(parent,text='界面保留最近内容；完整记录可以导出。滚动查看旧内容时暂停跟随，返回底部后继续。',
            text_color=MUTED,anchor='w').grid(row=3,column=0,sticky='ew',padx=14,pady=(0,12))
        self.after(300,self.refresh_thought_log)

    def open_thought_directory(self):
        try:
            directory=ROOT/'logs/generation'
            directory.mkdir(parents=True,exist_ok=True)
            os.startfile(directory)
        except OSError as error:
            self.thought_status.configure(text='打开日志目录失败：'+str(error))

    def choose_thought_log(self, label):
        self.thought_follow.set(False)
        path=self.thought_paths.get(label)
        if path:self.select_thought_log(path)

    def select_thought_log(self, path):
        try:
            self.thought_reader.select(path)
            self.thought_box.configure(state='normal')
            self.thought_box.delete('1.0','end')
            self.thought_box.insert('end','[显示最近已保存内容]\n')
            self.thought_box.configure(state='disabled')
            self.thought_picker.set(trace_label(path))
        except OSError as error:
            self.thought_status.configure(text='读取日志失败：'+str(error))

    def refresh_thought_log(self):
        try:
            paths=list_traces(ROOT/'logs/generation')
            self.thought_paths={trace_label(path):path for path in paths}
            values=list(self.thought_paths) or ['暂无记录']
            self.thought_picker.configure(values=values)
            if self.thought_follow.get() and paths and paths[0]!=self.thought_reader.path:
                self.select_thought_log(paths[0])
            text=self.thought_reader.read()
            if text:
                at_bottom=self.thought_box._textbox.yview()[1]>=0.98
                self.thought_box.configure(state='normal')
                self.thought_box.insert('end',text)
                count=int((self.thought_box._textbox.count('1.0','end-1c','chars') or (0,))[0])
                if count>VIEW_CHARS:self.thought_box.delete('1.0',f'1.0+{count-VIEW_CHARS}c')
                if at_bottom:self.thought_box.see('end')
                self.thought_box.configure(state='disabled')
            reader=self.thought_reader
            if reader.path:
                phase='本次请求已结束' if reader.finished else PHASE_LABELS.get(reader.phase,'正在生成')
                if not reader.finished and reader.tool_name=='apply_patch':phase='正在生成文件修改'
                self.thought_status.configure(text=f'{trace_label(reader.path)} · {phase} · 最新记录在请求开始后 {reader.last_elapsed:.1f} 秒')
        except (OSError,ValueError,tk.TclError):
            pass
        self.after(1000,self.refresh_thought_log)

    def export_thought_log(self):
        path=self.thought_reader.path
        if not path:return
        self.thought_export_button.configure(state='disabled')
        def work():
            try:
                result=export_trace(path,ROOT/'logs/generation-readable')
                self.events.put({'local':'thought_exported','path':str(result)})
            except (OSError,ValueError,TypeError) as error:
                self.events.put({'local':'thought_export_failed','text':str(error)})
        self.background(work)

    def build_files(self, parent):
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(parent, fg_color='transparent')
        bar.grid(row=0, column=0, columnspan=2, sticky='ew', pady=8)
        self.button(bar, '刷新文件', self.refresh_files, width=90).pack(side='left', padx=5)
        self.button(bar, '保存文件', self.save_file, width=90).pack(side='left', padx=5)
        self.button(bar, '查看修改差异', self.show_diff, width=110).pack(side='left', padx=5)
        self.file_label = ctk.CTkLabel(bar, text='双击文件打开', text_color=MUTED)
        self.file_label.pack(side='left', padx=15)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Treeview', background=PANEL, foreground=TEXT,
                        fieldbackground=PANEL, borderwidth=0, rowheight=28, font=('Segoe UI', 11))
        style.map('Treeview', background=[('selected', '#34442e')])
        self.tree = ttk.Treeview(parent, show='tree', selectmode='browse')
        self.tree.grid(row=1, column=0, sticky='nsew', padx=(4, 10))
        self.tree.bind('<<TreeviewOpen>>', self.expand_folder)
        self.tree.bind('<Double-1>', self.open_file)
        self.editor = ctk.CTkTextbox(parent, fg_color='#11161b', font=('Consolas', 13), wrap='none')
        self.editor.grid(row=1, column=1, sticky='nsew', padx=(0, 4), pady=(0, 6))
        self.refresh_files()

    def build_model(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color='transparent')
        scroll.pack(fill='both', expand=True)
        parent = scroll
        parent.grid_columnconfigure(0, weight=1)
        guards=ctk.CTkFrame(parent,fg_color='#222831')
        guards.grid(row=9,column=0,sticky='ew',padx=28,pady=12)
        ctk.CTkLabel(guards,text='防止思考和报错循环',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w',padx=18,pady=(14,5))
        self.guard_picker=ctk.CTkOptionMenu(guards,values=['标准：思考 60 秒 · 单次生成 150 秒','严格：思考 30 秒 · 单次生成 90 秒','宽松：思考 120 秒 · 单次生成 300 秒'],
            command=self.change_guard_limits,width=420,fg_color='#303742',button_color='#415b38')
        self.guard_picker.pack(anchor='w',padx=18,pady=8)
        seconds=guard_options(self.settings)['reasoning_seconds']
        self.guard_picker.set('严格：思考 30 秒 · 单次生成 90 秒' if seconds<=30 else
            '宽松：思考 120 秒 · 单次生成 300 秒' if seconds>60 else '标准：思考 60 秒 · 单次生成 150 秒')
        ctk.CTkLabel(guards,text='同一异常重复 3 次暂停；单任务最多 10 分钟。异常会保留日志并取消后台推理。\nAPI 报错后查证接口；未知工具、残缺参数和伪工具标记会被拦截。',
            text_color=MUTED,justify='left',wraplength=800).pack(anchor='w',padx=18,pady=(4,14))
        ctk.CTkLabel(parent, text='为这台电脑配置的模型', font=('Microsoft YaHei UI', 23, 'bold')).grid(row=0, column=0, sticky='w', padx=28, pady=(25, 8))
        self.model_title = ctk.CTkLabel(parent, text=selected_model(self.settings)+'  ·  '+BACKENDS[selected_backend(self.settings)]['label'],
                     text_color=ACCENT, font=('Segoe UI', 15))
        self.model_title.grid(row=1, column=0, sticky='w', padx=28, pady=4)
        location = ctk.CTkFrame(parent, fg_color='transparent')
        location.grid(row=2, column=0, sticky='ew', padx=28, pady=8)
        location.grid_columnconfigure(0, weight=1)
        self.model_location_info = ctk.CTkLabel(location, text='模型目录：'+str(model_directory(self.settings)),
            text_color=MUTED, wraplength=600, justify='left', anchor='w')
        self.model_location_info.grid(row=0, column=0, sticky='ew', padx=(0,12))
        self.model_location_button = self.button(location, '选择模型目录', self.choose_model_directory, width=150)
        self.model_location_button.grid(row=0, column=1, sticky='e')
        self.model_info = ctk.CTkLabel(parent, text='', justify='left', anchor='w', font=('Microsoft YaHei UI', 14))
        self.model_info.grid(row=4, column=0, sticky='ew', padx=28, pady=(25, 8))
        self.progress = ctk.CTkProgressBar(parent, progress_color=ACCENT)
        self.progress.grid(row=5, column=0, sticky='ew', padx=28, pady=10)
        buttons = ctk.CTkFrame(parent, fg_color='transparent')
        buttons.grid(row=6, column=0, sticky='w', padx=24, pady=15)
        self.button(buttons, '启动模型', self.launch_model, fg_color=ACCENT, text_color=BG).pack(side='left', padx=4)
        self.button(buttons, '释放显存', self.unload_model).pack(side='left', padx=4)
        self.button(buttons, '打开运行日志', lambda: os.startfile(ROOT / 'logs')).pack(side='left', padx=4)
        self.button(buttons, '模型调研报告', lambda: os.startfile(ROOT / '模型调研与使用说明.md')).pack(side='left', padx=4)
        options = ctk.CTkFrame(parent, fg_color='#222831')
        options.grid(row=7, column=0, sticky='ew', padx=28, pady=(15, 8))
        options.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(options, text='模型、后端与上下文', font=('Microsoft YaHei UI', 18, 'bold')).grid(row=0,column=0,sticky='w',padx=18,pady=(16,8))
        self.model_picker = ctk.CTkOptionMenu(options, values=[s['label'] for s in MODELS.values()],
            command=self.preview_model, width=360, fg_color='#303742', button_color='#415b38')
        self.model_picker.grid(row=1,column=0,sticky='w',padx=18,pady=8)
        self.model_picker.set(MODELS[selected_model(self.settings)]['label'])
        backend_line = ctk.CTkFrame(options, fg_color='transparent')
        backend_line.grid(row=2,column=0,sticky='w',padx=18,pady=8)
        ctk.CTkLabel(backend_line,text='推理后端',text_color=MUTED).pack(side='left',padx=(0,12))
        self.backend_picker = ctk.CTkOptionMenu(backend_line,values=[s['label'] for s in BACKENDS.values()],
            width=280,fg_color='#303742',button_color='#415b38',command=self.preview_backend)
        self.backend_picker.pack(side='left')
        self.backend_picker.set(BACKENDS[selected_backend(self.settings)]['label'])
        ctk.CTkLabel(options,text='MoE4All 可选配置：仅 Jack、RAM 辅助、纯文字、最高 70K。输入处理较慢；日常建议 Vulkan。应用失败会恢复原后端。',
            text_color=MUTED,wraplength=840,justify='left').grid(row=21,column=0,sticky='w',padx=18,pady=(8,14))
        ctk.CTkLabel(backend_line,text='输出加速',text_color=MUTED).pack(side='left',padx=(24,12))
        self.decoding_picker=ctk.CTkOptionMenu(backend_line,values=list(DECODING_MODES.values()),width=230,
            fg_color='#303742',button_color='#415b38')
        self.decoding_picker.pack(side='left')
        self.decoding_picker.set(DECODING_MODES[selected_decoding(self.settings)])
        self.history_picker = ctk.CTkOptionMenu(options,values=list(HISTORY_MODES.values()),
            command=lambda value:self.preview_context(self.context_slider.get()),width=380,
            fg_color='#303742',button_color='#415b38')
        self.history_picker.grid(row=3,column=0,sticky='w',padx=18,pady=8)
        self.history_picker.set(HISTORY_MODES[self.settings.get('history_mode','full')])
        work_line=ctk.CTkFrame(options,fg_color='transparent')
        work_line.grid(row=4,column=0,sticky='w',padx=18,pady=8)
        ctk.CTkLabel(work_line,text='工作上下文',text_color=MUTED).pack(side='left',padx=(0,12))
        self.work_picker=ctk.CTkOptionMenu(work_line,values=[f'{k}K' for k in WORK_CONTEXT_OPTIONS],width=140,
            command=lambda value:self.preview_context(self.context_slider.get()),fg_color='#303742',button_color='#415b38')
        self.work_picker.pack(side='left')
        self.work_picker.set(str(self.settings.get('work_context',WORK_CONTEXT)//1024)+'K')
        ctk.CTkLabel(work_line,text='性能调度',text_color=MUTED).pack(side='left',padx=(24,12))
        self.performance_picker=ctk.CTkOptionMenu(work_line,values=list(PERFORMANCE_MODES.values()),width=230,
            fg_color='#303742',button_color='#415b38')
        self.performance_picker.pack(side='left')
        self.performance_picker.set(PERFORMANCE_MODES[self.settings.get('performance_mode','standard')])
        self.context_value = ctk.CTkLabel(options,text='',anchor='w',font=('Microsoft YaHei UI',14))
        self.context_value.grid(row=5,column=0,sticky='ew',padx=18,pady=(8,4))
        self.context_slider = ctk.CTkSlider(options,from_=MIN_CONTEXT,to=context_limits()[selected_model(self.settings)],
            command=self.preview_context,progress_color=ACCENT,button_color=ACCENT)
        self.context_slider.grid(row=6,column=0,sticky='ew',padx=18,pady=12)
        self.context_range = ctk.CTkLabel(options,text='',text_color=MUTED,anchor='w')
        self.context_range.grid(row=7,column=0,sticky='ew',padx=18,pady=(0,8))
        self.apply_button = self.button(options,'应用模型、后端与上下文',self.apply_model_options,fg_color=ACCENT,text_color=BG,width=240)
        self.apply_button.grid(row=16,column=0,sticky='w',padx=18,pady=(4,12))
        self.cache_picker=ctk.CTkOptionMenu(options,values=list(CACHE_OPTIONS),
            command=lambda value:self.preview_context(self.context_slider.get()),width=380,
            fg_color='#303742',button_color='#415b38')
        self.cache_picker.grid(row=8,column=0,sticky='w',padx=18,pady=8)
        self.cache_picker.set(next(label for label,value in CACHE_OPTIONS.items() if value==self.settings.get('kv_cache_location','auto')))
        self.cache_hint=ctk.CTkLabel(options,text='',text_color=MUTED,justify='left',wraplength=740,anchor='w')
        self.cache_hint.grid(row=9,column=0,sticky='w',padx=18,pady=4)
        directive_line=ctk.CTkFrame(options,fg_color='transparent')
        directive_line.grid(row=10,column=0,sticky='w',padx=18,pady=(12,8))
        ctk.CTkLabel(directive_line,text='最高指令预设',text_color=MUTED).pack(side='left',padx=(0,12))
        self.directive_picker=ctk.CTkOptionMenu(directive_line,values=list(DIRECTIVE_MODES.values()),
            command=self.directive_choice,width=390,fg_color='#303742',button_color='#415b38')
        self.directive_picker.pack(side='left')
        self.directive_picker.set(DIRECTIVE_MODES[selected_directive(self.settings)])
        self.jack_xml_var=ctk.BooleanVar(value=selected_directive(self.settings)=='legacy')
        self.jack_xml_switch=ctk.CTkSwitch(options,text='恢复 Jack 原始 XML 强制流程',
            variable=self.jack_xml_var,command=self.toggle_legacy_directive,progress_color=ACCENT)
        self.jack_xml_switch.grid(row=11,column=0,sticky='w',padx=18,pady=6)
        self.custom_directive_frame=ctk.CTkFrame(options,fg_color='transparent')
        self.custom_directive_frame.grid(row=12,column=0,sticky='ew',padx=18,pady=8)
        self.custom_directive_frame.grid_columnconfigure(0,weight=1)
        self.directive_tag=ctk.CTkEntry(self.custom_directive_frame,width=330,
            placeholder_text='标签名，例如 my_preferences')
        self.directive_tag.grid(row=0,column=0,sticky='w',pady=(0,6))
        self.directive_tag.insert(0,self.settings.get('directive_custom_tag',DEFAULT_CUSTOM_TAG))
        ctk.CTkLabel(self.custom_directive_frame,text='标签用英文字母或下划线开头；下面填写具体指令。',
            text_color=MUTED).grid(row=1,column=0,sticky='w')
        self.directive_text=ctk.CTkTextbox(self.custom_directive_frame,height=130,wrap='word')
        self.directive_text.grid(row=2,column=0,sticky='ew',pady=6)
        self.directive_text.insert('1.0',self.settings.get('directive_custom_text',''))
        self.directive_preview_button=self.button(options,'查看实际最高指令',self.preview_directive,width=180)
        self.directive_preview_button.grid(row=13,column=0,sticky='w',padx=18,pady=6)
        ctk.CTkLabel(options,text='预设替换原有最高指令，原生思考仍保留。开放回答是减少无故拒答的提示，模型权重不变。',
            text_color=MUTED,justify='left',wraplength=740).grid(row=14,column=0,sticky='w',padx=18,pady=6)
        emotion_line=ctk.CTkFrame(options,fg_color='transparent')
        emotion_line.grid(row=15,column=0,sticky='ew',padx=18,pady=10)
        emotion_line.grid_columnconfigure(1,weight=1)
        ctk.CTkLabel(emotion_line,text='情绪通道 A · 实验',text_color=MUTED).grid(row=0,column=0,sticky='w',padx=(0,12))
        self.emotion_picker=ctk.CTkOptionMenu(emotion_line,values=list(EMOTION_MODES.values()),width=300,
            command=lambda value:self.preview_emotion(),fg_color='#303742',button_color='#415b38')
        self.emotion_picker.grid(row=0,column=1,sticky='w')
        self.emotion_picker.set(EMOTION_MODES[self.settings.get('emotion_mode','off')])
        self.emotion_value=ctk.CTkLabel(emotion_line,text='',text_color=MUTED)
        self.emotion_value.grid(row=1,column=0,sticky='w',pady=8)
        self.emotion_slider=ctk.CTkSlider(emotion_line,from_=MIN_EMOTION_STRENGTH,to=MAX_EMOTION_STRENGTH,number_of_steps=10000,
            command=lambda value:self.preview_emotion(),progress_color=ACCENT)
        self.emotion_slider.grid(row=1,column=1,sticky='ew',pady=8)
        self.emotion_slider.set(self.settings.get('emotion_strength',0.002))
        self.emotion_value.configure(text=f'A 强度 {self.emotion_slider.get():+.4f}')
        self.emotion_hint_label=ctk.CTkLabel(emotion_line,text='',wraplength=740,text_color=MUTED,justify='left')
        self.emotion_hint_label.grid(row=2,column=0,columnspan=2,sticky='w')
        ctk.CTkLabel(emotion_line,text='情绪通道 B · 可选混合',text_color=MUTED).grid(row=3,column=0,sticky='w',padx=(0,12),pady=(14,0))
        self.emotion_secondary_picker=ctk.CTkOptionMenu(emotion_line,values=list(EMOTION_MODES.values()),width=300,
            command=lambda value:self.preview_emotion(),fg_color='#303742',button_color='#415b38')
        self.emotion_secondary_picker.grid(row=3,column=1,sticky='w',pady=(14,0))
        self.emotion_secondary_picker.set(EMOTION_MODES[self.settings.get('emotion_secondary_mode','off')])
        self.emotion_secondary_value=ctk.CTkLabel(emotion_line,text='',text_color=MUTED)
        self.emotion_secondary_value.grid(row=4,column=0,sticky='w',pady=8)
        self.emotion_secondary_slider=ctk.CTkSlider(emotion_line,from_=MIN_EMOTION_STRENGTH,to=MAX_EMOTION_STRENGTH,
            number_of_steps=10000,command=lambda value:self.preview_emotion(),progress_color=ACCENT)
        self.emotion_secondary_slider.grid(row=4,column=1,sticky='ew',pady=8)
        self.emotion_secondary_slider.set(self.settings.get('emotion_secondary_strength',0.002))
        self.emotion_secondary_hint=ctk.CTkLabel(emotion_line,text='',wraplength=740,text_color=MUTED,justify='left')
        self.emotion_secondary_hint.grid(row=5,column=0,columnspan=2,sticky='w')
        self.emotion_mix_hint=ctk.CTkLabel(emotion_line,text='',wraplength=740,text_color=MUTED,justify='left')
        self.emotion_mix_hint.grid(row=6,column=0,columnspan=2,sticky='w',pady=8)
        self.button(emotion_line,'两路归零',self.reset_emotion_strengths,width=120).grid(row=7,column=0,sticky='w',pady=4)
        self.preview_emotion()
        ctk.CTkLabel(options,text='选择后点击应用。切换指令或后端会重新加载模型；当前任务结束后才能应用。失败会恢复原设置。',
            text_color=MUTED,justify='left',wraplength=740).grid(row=17,column=0,sticky='w',padx=18,pady=(0,16))
        self.directive_choice(self.directive_picker.get())
        self.context_info = ctk.CTkLabel(parent,text='',justify='left',text_color=MUTED,font=('Microsoft YaHei UI',13))
        self.context_info.grid(row=8,column=0,sticky='w',padx=28,pady=12)
        proxy = ctk.CTkFrame(parent, fg_color='#222831')
        proxy.grid(row=3, column=0, sticky='ew', padx=28, pady=(8,12))
        proxy.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(proxy, text='Codex 网络代理', font=('Microsoft YaHei UI',18,'bold')).grid(
            row=0,column=0,sticky='w',padx=18,pady=(16,8))
        try:
            proxy_config = load_proxy_settings(ROOT)
        except (OSError,ValueError):
            proxy_config = {'enabled':False}
        self.proxy_enabled_var = ctk.BooleanVar(value=bool(proxy_config.get('enabled')))
        self.proxy_apply_button = self.button(proxy,'关闭代理' if proxy_config.get('enabled') else '开启代理',
            self.toggle_proxy,width=170,fg_color=ACCENT,text_color=BG)
        self.proxy_apply_button.grid(row=1,column=0,sticky='w',padx=18,pady=8)
        ctk.CTkLabel(proxy,text='模型可以调用“搜索资料”和“读取网页”工具。',text_color=MUTED).grid(
            row=1,column=1,sticky='w',padx=18,pady=8)
        self.proxy_status = ctk.CTkLabel(proxy,text='',text_color=MUTED,justify='left',anchor='w',wraplength=780)
        self.proxy_status.grid(row=2,column=0,columnspan=2,sticky='ew',padx=18,pady=(4,16))
        self.refresh_proxy_status()
        self.preview_model(self.model_picker.get())
        self.update_model_labels()

    def choose_model_directory(self):
        if self.busy or self.loading_model or self.session_action_pending or self.steer_pending:
            messagebox.showinfo('正在运行','当前任务或模型加载结束后可以修改模型目录。')
            return
        if os.environ.get('LOCAL_CODEX_MODELS'):
            messagebox.showinfo('模型目录由启动配置指定','请先移除 LOCAL_CODEX_MODELS 启动设置，再使用目录按钮。')
            return
        initial = model_directory(self.settings)
        path = filedialog.askdirectory(title='选择存放 GGUF 模型与视觉组件的文件夹',
            initialdir=str(initial if initial.exists() else initial.parent), mustexist=True)
        if not path:
            return
        selected = Path(path).resolve(strict=True)
        candidate = {**self.settings, 'model_directory':str(selected)}
        try:
            save_settings(candidate)
        except OSError as error:
            messagebox.showerror('模型目录未保存',str(error))
            return
        self.settings = candidate
        self.model_location_info.configure(text='模型目录：'+str(selected))
        missing = [file.name for file in model_required_files(selected_model(self.settings)) if not file.is_file()]
        note = '请将这些文件放到该目录：'+ '、'.join(missing) if missing else '点击“启动模型”从所选目录载入模型。'
        self.append('\n› 模型目录已保存：'+str(selected)+'\n› '+note+'\n',save=False)

    def refresh_proxy_status(self):
        try:
            config = load_proxy_settings(ROOT)
            lease = getattr(self.rpc,'proxy_lease',None)
            if lease and lease.active:
                text = 'VLESS 代理运行中 · '+config.get('server','')+':'+str(config.get('port',443))
            elif config.get('enabled'):
                text = '代理已配置；编程引擎连接成功后启用。启动错误可在运行日志中的 proxy.log 查看。'
            else:
                text = 'VLESS 代理已关闭。'
            if self.proxy_enabled_var.get()!=bool(config.get('enabled')):
                text += '\n代理按钮的设置正在应用。'
            self.proxy_status.configure(text=text+'\n本地模型连接保持直连；该开关用于 Codex 及其工具的出站网络。')
        except (OSError,ValueError):
            self.proxy_status.configure(text='代理配置无法读取，请检查 proxy-settings.json。')

    def toggle_proxy(self):
        if self.busy or self.loading_model or self.session_action_pending or self.steer_pending:
            messagebox.showinfo('正在运行','当前任务结束后可以切换代理。')
            return
        self.proxy_enabled_var.set(not bool(load_proxy_settings(ROOT).get('enabled')))
        self.apply_proxy_settings()

    def apply_proxy_settings(self):
        if self.busy or self.loading_model or self.session_action_pending or self.steer_pending:
            messagebox.showinfo('正在运行','当前任务结束后可以应用代理设置。')
            return
        try:
            previous = load_proxy_settings(ROOT)
            candidate = {**previous,'enabled':bool(self.proxy_enabled_var.get())}
            validate_proxy_settings(candidate)
        except (OSError,ValueError,TypeError) as error:
            messagebox.showerror('代理设置未应用',str(error))
            return
        thread_id, project = self.thread_id, str(self.project)
        self.save_transcript()
        self.busy=True
        self.send_button.configure(state='disabled')
        self.proxy_apply_button.configure(state='disabled')
        def connect_with_saved_proxy():
            self.rpc=RpcClient(self.events.put)
            if thread_id:
                self.rpc.request('thread/resume',{'threadId':thread_id,'cwd':project,'excludeTurns':True,
                    'model':selected_model(self.settings),'modelProvider':'qwen_local',
                    'approvalPolicy':'never','sandbox':'danger-full-access','config':engine_config(self.settings)})
        def work():
            try:
                if self.rpc:self.rpc.close()
                self.rpc=None
                save_proxy_settings(ROOT,candidate)
                connect_with_saved_proxy()
                self.events.put({'local':'proxy_changed','ok':True})
            except Exception as error:
                try:
                    if self.rpc:self.rpc.close()
                    self.rpc=None
                    save_proxy_settings(ROOT,previous)
                    connect_with_saved_proxy()
                    detail='已恢复原设置：'+str(error)
                except Exception as restored_error:
                    detail=str(error)+'；重新连接时：'+str(restored_error)
                self.events.put({'local':'proxy_changed','ok':False,'text':detail})
        self.background(work)

    def pending_model(self):
        return next(name for name,spec in MODELS.items() if spec['label']==self.model_picker.get())

    def preview_emotion(self):
        strength=round(float(self.emotion_slider.get()),4)
        mode=next(key for key,label in EMOTION_MODES.items() if label==self.emotion_picker.get())
        self.emotion_value.configure(text=f'A 强度 {strength:+.4f}')
        self.emotion_hint_label.configure(text=emotion_hint(ROOT,mode,strength))
        second_strength=round(float(self.emotion_secondary_slider.get()),4)
        second=next(key for key,label in EMOTION_MODES.items() if label==self.emotion_secondary_picker.get())
        self.emotion_secondary_value.configure(text=f'B 强度 {second_strength:+.4f}')
        self.emotion_secondary_hint.configure(text=emotion_hint(ROOT,second,second_strength))
        both=mode!='off' and second!='off' and strength!=0 and second_strength!=0
        self.emotion_mix_hint.configure(text=('两路向量直接相加，不自动减弱；单路短测边界不适用于组合。'
            if both else '可单独使用任一路，也可开启两路混合。')+'正值增强、负值反向、零值停用。'
            '同一向量等强正负可抵消；两种相反情绪不一定抵消。拖动只预览，点击应用后生效。')

    def reset_emotion_strengths(self):
        self.emotion_slider.set(0);self.emotion_secondary_slider.set(0);self.preview_emotion()

    def directive_choice(self,label):
        mode=next(mode for mode,text in DIRECTIVE_MODES.items() if text==label)
        self.jack_xml_var.set(mode=='legacy')
        if mode=='custom':self.custom_directive_frame.grid()
        else:self.custom_directive_frame.grid_remove()

    def toggle_legacy_directive(self):
        mode='legacy' if self.jack_xml_var.get() else 'native'
        self.directive_picker.set(DIRECTIVE_MODES[mode])
        self.directive_choice(self.directive_picker.get())

    def directive_candidate(self):
        return {**self.settings,
            'directive_mode':next(mode for mode,label in DIRECTIVE_MODES.items() if label==self.directive_picker.get()),
            'directive_custom_tag':self.directive_tag.get().strip(),
            'directive_custom_text':self.directive_text.get('1.0','end-1c')}

    def preview_directive(self):
        try:
            candidate=self.directive_candidate();mode=selected_directive(candidate)
            text=build_directive(candidate)
            if mode=='legacy':
                from gguf_info import read_metadata
                from model_templates import native_thinking_template
                _,text=native_thinking_template(read_metadata(model_file(MODEL))['tokenizer.chat_template'])
            elif mode=='native':text='此模式不注入额外最高指令，保留原生思考和工具协议。'
        except ValueError as error:
            self.append('\n⚠ '+str(error)+'\n',save=False);return
        window=ctk.CTkToplevel(self);window.title('最高指令 · '+DIRECTIVE_MODES[mode]);window.geometry('850x650')
        view=ctk.CTkTextbox(window,wrap='word',font=('Microsoft YaHei UI',14))
        view.pack(fill='both',expand=True,padx=18,pady=18);view.insert('1.0',text);view.configure(state='disabled')

    def preview_model(self, label):
        name = self.pending_model()
        self.decoding_picker.configure(state='normal' if name==MODEL else 'disabled')
        self.jack_xml_switch.configure(state='normal' if name==MODEL else 'disabled')
        self.directive_picker.configure(state='normal' if name==MODEL else 'disabled')
        self.directive_preview_button.configure(state='normal' if name==MODEL else 'disabled')
        self.emotion_picker.configure(state='normal' if name==MODEL else 'disabled')
        self.emotion_slider.configure(state='normal' if name==MODEL else 'disabled')
        self.emotion_secondary_picker.configure(state='normal' if name==MODEL else 'disabled')
        self.emotion_secondary_slider.configure(state='normal' if name==MODEL else 'disabled')
        self.decoding_picker.set(DECODING_MODES[selected_decoding(self.settings,name)])
        cap = context_limits()[name]
        self.context_slider.configure(from_=MIN_CONTEXT,to=cap,number_of_steps=max(1,(cap-MIN_CONTEXT)//1024))
        self.context_slider.set(context_for(self.settings,name))
        self.context_range.configure(text=f'{MIN_CONTEXT:,} token  —  设置上限 {cap:,} token（{cap/1024:g}K）')
        self.preview_context(self.context_slider.get())

    def preview_context(self, value):
        cap=context_limits()[self.pending_model()]
        if self.backend_picker.get()==BACKENDS['moe4all']['label']:cap=min(cap,71680)
        value=cap if float(value)>=cap-0.5 else max(MIN_CONTEXT,min(cap,round(float(value)/1024)*1024))
        self.pending_context=value
        memory_mode=self.history_picker.get()==HISTORY_MODES['memory']
        self.context_slider.configure(state='disabled' if memory_mode else 'normal')
        self.work_picker.configure(state='normal' if memory_mode else 'disabled')
        if memory_mode:
            requested=max(MIN_CONTEXT,min(MAX_WORK_CONTEXT,int(self.work_picker.get()[:-1])*1024))
            if self.backend_picker.get()==BACKENDS['moe4all']['label']:
                requested=min(requested,71680)
                self.work_picker.set(str(requested//1024)+'K')
            # A larger working window needs an equally large service ceiling.
            # This is a preview; saved settings change only when Apply is used.
            value=min(cap,max(value,requested))
            self.pending_context=value
            self.context_slider.set(value)
            candidate={**self.settings,'history_mode':'memory','work_context':requested,
                'model_contexts':{**self.settings.get('model_contexts',{}),self.pending_model():value}}
            working,compact=engine_limits(candidate,self.pending_model())
            self.context_value.configure(text=f'工作上下文 {working:,} token · {compact:,} token 自动整理\n完整模式上限保留为 {value:,} token；下方滑条仅用于完整模式。')
        else:
            self.context_value.configure(text=f'选择 {value:,} token（{value/1024:g}K）  ·  自动压缩阈值 {compact_for(value):,}')
        if hasattr(self,'cache_picker'):
            choice=CACHE_OPTIONS[self.cache_picker.get()]
            location=kv_cache_location(value,{'kv_cache_location':choice})
            hint=('所选值是对话总上限。实际输入加生成预留空间在 107K 以内时用显卡缓存；超过后自动切换到内存。'
                  '切换时会重新加载，模型权重仍在显卡。' if choice=='auto' else
                  'KV 缓存留在显卡，优先速度。' if location=='gpu' else
                  '整个 KV 缓存放入系统内存，模型权重仍在显卡；长上下文速度可能下降。')
            self.cache_hint.configure(text=hint)
            if self.backend_picker.get()==BACKENDS['moe4all']['label']:
                self.cache_hint.configure(text='MoE4All 使用 Q8 KV，最多 512MiB 留在显卡，其余放 RAM。当前仅支持 Jack 纯文字，最高 70K；冷输入明显较慢，未保证长任务速度。')

    def update_model_labels(self):
        name=selected_model(self.settings)
        moe=selected_backend(self.settings)=='moe4all'
        execution='CPU/GPU 混合' if self.settings.get('cpu_offload',False) else '模型层全部在显卡 · CPU 卸载关闭'
        cache_text='按实际长度自动选择' if self.settings.get('kv_cache_location','auto')=='auto' else (
            '显卡' if self.settings['kv_cache_location']=='gpu' else '系统内存')
        self.sidebar_model.configure(text=MODELS[name]['label'])
        self.attach_button.configure(state='normal' if configured_vision(name,self.settings) else 'disabled',
            text='添加图片' if configured_vision(name,self.settings) else '当前配置仅文字')
        working,compact=engine_limits(self.settings)
        self.sidebar_context.configure(text=f"RX 9070 / 16GB\n工作上下文 {working:,} token · 自动确认")
        self.model_title.configure(text=name+'  ·  '+BACKENDS[selected_backend(self.settings)]['label'])
        self.backend_picker.set(BACKENDS[selected_backend(self.settings)]['label'])
        self.performance_picker.set(PERFORMANCE_MODES[self.settings.get('performance_mode','standard')])
        self.decoding_picker.set(DECODING_MODES[selected_decoding(self.settings)])
        self.history_picker.set(HISTORY_MODES[self.settings.get('history_mode','full')])
        self.work_picker.set(str(self.settings.get('work_context',WORK_CONTEXT)//1024)+'K')
        self.directive_picker.set(DIRECTIVE_MODES[selected_directive(self.settings)])
        self.directive_choice(self.directive_picker.get())
        self.emotion_picker.set(EMOTION_MODES[self.settings.get('emotion_mode','off')])
        self.emotion_slider.set(self.settings.get('emotion_strength',0.002))
        self.emotion_secondary_picker.set(EMOTION_MODES[self.settings.get('emotion_secondary_mode','off')])
        self.emotion_secondary_slider.set(self.settings.get('emotion_secondary_strength',0.002))
        self.preview_emotion()
        self.context_info.configure(text=f"当前已应用：{HISTORY_MODES[self.settings.get('history_mode','full')]} · 工作上下文 {working:,} token · {compact:,} token 自动整理\n"
            +(f'GPU 计算 · 自动分页\nQ8 动态 KV · 空闲缓存到 G 盘（5GiB）' if moe else f'{execution} · {PERFORMANCE_MODES[self.settings.get("performance_mode","standard")]}\nQ4 KV 缓存位置：{cache_text} · 4 个有界检查点 · 旧提示 RAM 缓存关闭')+'\n自动确认 · 思考无额外 token 上限 · 按需读取函数与代码片段'
            + ('\n原始会话和思考日志完整留存；历史工具按需查回，摘要可能遗漏信息。单次长思考仍可能变慢。' if self.settings.get('history_mode')=='memory' else '')
            + ('\nMTP 预测候选 token，再由 Jack 主模型验证；不使用未经验证的预测结果。' if selected_decoding(self.settings)=='draft-mtp' else '')
            + ('\n最高指令：'+DIRECTIVE_MODES[selected_directive(self.settings)]+' · 原生思考保持无限\n内部情绪 A：'+EMOTION_MODES[self.settings.get('emotion_mode','off')]
                +f" {self.settings.get('emotion_strength',0.002):+.4f}"+'\n内部情绪 B：'+EMOTION_MODES[self.settings.get('emotion_secondary_mode','off')]
                +f" {self.settings.get('emotion_secondary_strength',0.002):+.4f}" if name==MODEL else '')
            + ('\nHuihui Q4_K 全显卡运行需更多显存或更小量化。' if not self.settings.get('cpu_offload',False) else ''))

    def preview_backend(self, value):
        if value==BACKENDS['moe4all']['label'] and self.pending_context>262144:
            self.context_slider.set(262144)
            self.preview_context(262144)
        elif hasattr(self,'context_slider'):
            self.preview_context(self.context_slider.get())

    def apply_model_options(self):
        if self.busy or self.loading_model or not self.rpc:
            self.append('\n› 等当前任务或模型加载完成后，再应用设置。\n',save=False)
            return
        name=self.pending_model()
        context=self.pending_context
        old_settings=json.loads(json.dumps(self.settings))
        candidate=json.loads(json.dumps(self.settings))
        candidate['model']=name
        candidate['backend']=next(backend for backend,spec in BACKENDS.items() if spec['label']==self.backend_picker.get())
        candidate['performance_mode']=next(mode for mode,label in PERFORMANCE_MODES.items() if label==self.performance_picker.get())
        candidate['speculative_type']=next(mode for mode,label in DECODING_MODES.items() if label==self.decoding_picker.get())
        candidate['history_mode']=next(mode for mode,label in HISTORY_MODES.items() if label==self.history_picker.get())
        candidate['work_context']=int(self.work_picker.get()[:-1])*1024
        candidate['kv_cache_location']=CACHE_OPTIONS[self.cache_picker.get()]
        try:
            directive=self.directive_candidate();build_directive(directive)
        except ValueError as error:
            self.append('\n⚠ '+str(error)+'\n',save=False);return
        for field in ('directive_mode','directive_custom_tag','directive_custom_text'):
            candidate[field]=directive[field]
        candidate['jack_xml_enabled']=candidate['directive_mode']=='legacy'
        candidate['emotion_mode']=next(mode for mode,label in EMOTION_MODES.items() if label==self.emotion_picker.get())
        candidate['emotion_strength']=round(float(self.emotion_slider.get()),4)
        candidate['emotion_secondary_mode']=next(mode for mode,label in EMOTION_MODES.items() if label==self.emotion_secondary_picker.get())
        candidate['emotion_secondary_strength']=round(float(self.emotion_secondary_slider.get()),4)
        try:emotion_state(ROOT,model_file(name),candidate)
        except (ValueError,OSError) as error:
            self.append('\n⚠ '+str(error)+'\n',save=False);return
        candidate.setdefault('model_contexts',{})[name]=context
        if candidate['backend']=='moe4all':
            candidate.update(moe_kv_mode='ram',moe_vision_enabled=False,moe_ssd_cache=False)
            context=min(context,71680)
            candidate['model_contexts'][name]=context
            candidate['work_context']=min(candidate['work_context'],context)
            try:
                from moe4all_backend import validate
                from core import chat_template_state
                validate(candidate,name,context,chat_template_state(name,candidate),
                         emotion_state(ROOT,model_file(name),candidate),selected_decoding(candidate,name))
            except (ValueError,OSError) as error:
                self.append('\n⚠ '+str(error)+'\n',save=False);return
        thread_id=self.thread_id
        project=str(self.project)
        self.save_transcript()
        self.busy=True
        self.loading_model=True
        self.send_button.configure(state='disabled')
        self.apply_button.configure(state='disabled')
        self.append(f'\n› 正在应用 {MODELS[name]["label"]} · {BACKENDS[candidate["backend"]]["label"]}，上下文 {context:,} token…\n',save=False)
        def work():
            try:
                self.rpc.close()
                self.rpc=None
                prepared=prepare(candidate)
                self.model_proc=start_model(name,context,wait=True)
                self.rpc=RpcClient(self.events.put)
                if thread_id:
                    self.rpc.request('thread/resume',{'threadId':thread_id,'cwd':project,'excludeTurns':True,
                        'model':name,'modelProvider':'qwen_local','approvalPolicy':'never','sandbox':'danger-full-access',
                        'config':engine_config(prepared)})
                self.events.put({'local':'settings_applied','settings':prepared})
            except Exception as error:
                restored_ok=False
                try:
                    with (ROOT/'logs/settings-errors.log').open('a',encoding='utf-8') as log:
                        log.write(time.strftime('%Y-%m-%d %H:%M:%S')+' apply settings\n'+traceback.format_exc()+'\n')
                except OSError:
                    pass
                try:
                    if self.rpc:
                        self.rpc.close()
                        self.rpc=None
                    restored=prepare(old_settings)
                    self.model_proc=start_model(wait=True)
                    self.rpc=RpcClient(self.events.put)
                    if thread_id:
                        self.rpc.request('thread/resume',{'threadId':thread_id,'cwd':project,'excludeTurns':True,
                            'model':selected_model(restored),'modelProvider':'qwen_local',
                            'approvalPolicy':'never','sandbox':'danger-full-access',
                            'config':engine_config(restored)})
                    restored_ok=True
                except Exception as restore_error:
                    error=RuntimeError(str(error)+'；恢复时：'+str(restore_error))
                self.events.put({'local':'settings_failed','settings':old_settings,'text':str(error),'restored':restored_ok})
        self.background(work)

    def append(self, text, save=True):
        self.chat.configure(state='normal')
        self.chat.insert('end', text)
        self.chat.see('end')
        self.chat.configure(state='disabled')
        if save:
            self.transcript.append(text)
        self.trim_display()

    def trim_display(self):
        # Full history stays on disk; Tk only renders a bounded recent tail.
        count = int((self.chat._textbox.count('1.0', 'end-1c', 'chars') or (0,))[0])
        if count > DISPLAY_CHARS:
            remove = count - DISPLAY_CHARS
            # Never trim a message that is currently being replaced by streaming.
            if self.message_buffers and 'assistant_begin' in self.chat._textbox.mark_names():
                remove = min(remove, int((self.chat._textbox.count('1.0', 'assistant_begin', 'chars') or (0,))[0]))
            if remove > 0:
                self.chat.configure(state='normal')
                self.chat.delete('1.0', f'1.0+{remove}c')
                self.chat.configure(state='disabled')

    def clear_stream_buffers(self):
        # Interrupted/error turns may never receive item/completed.
        for text in self.message_buffers.values():
            shown=self.clean_answer(text)
            self.transcript.append(shown)
            if shown.strip():
                self.turn_visible_output=True
        self.message_buffers.clear()
        self.current_item = None
        self.trim_display()

    def background(self, fn):
        def worker():
            try:
                fn()
            except Exception as e:
                self.events.put({'local': 'error', 'text': str(e)})
        threading.Thread(target=worker, daemon=True).start()

    def connect(self):
        try:
            refresh_gateway_for_current_app()
            self.rpc = RpcClient(self.events.put)
            self.events.put({'local': 'connected'})
        except Exception as e:
            self.events.put({'local': 'error', 'text': str(e)})

    def launch_model(self):
        if self.loading_model:
            return
        self.loading_model = True
        def work():
            try:
                self.model_proc = start_model(wait=True)
                self.events.put({'local': 'model_started'})
            finally:
                self.loading_model = False
        self.background(work)

    def unload_model(self):
        if self.busy or self.loading_model:
            messagebox.showinfo('正在运行', '请先停止当前任务，再释放显存。')
            return
        def work():
            if server_ready() and any(slot.get('is_processing') for slot in api('/slots')):
                raise RuntimeError('本地模型正在处理其他会话，请等任务完成后再释放显存。')
            stop_model()
            self.model_proc=None
        self.background(work)

    def send_prompt(self):
        prompt = self.input.get('1.0', 'end').strip()
        if not prompt or self.steer_pending or self.session_action_pending:
            return
        if self.busy:
            if self.turn_id and self.rpc:
                self.submit_steer(prompt)
            return
        if not self.rpc:
            messagebox.showinfo('正在连接', '编程引擎正在连接，请稍后再试。')
            return
        live=active_model()
        if not server_ready() or not runtime_matches_settings(live,self.settings):
            self.launch_model()
            self.append('\n◈  模型正在加载，准备完成后请再次发送。\n', save=False)
            return
        self.input.delete('1.0', 'end')
        self.append('\n\n你\n' + prompt + '\n\nCodex\n')
        self.busy = True
        self.turn_visible_output = False
        self.turn_started_at = time.monotonic()
        self.last_turn_tokens = None
        self.append('› 模型正在处理，请稍候…\n',save=False)
        self.send_button.configure(state='disabled')
        self.current_item = None
        self.message_buffers.clear()
        effort = {'均衡思考': 'medium', '深入思考': 'xhigh', '快速思考': 'low'}[self.effort.get()]
        project = str(self.project)
        images = list(self.attachments)
        self.attachments.clear()
        self.attach_button.configure(text='添加图片')
        def work():
            if not self.thread_id:
                result = self.rpc.request('thread/start', {'cwd': project, 'model': selected_model(self.settings),
                         'modelProvider': 'qwen_local', 'sandbox': 'danger-full-access',
                         'approvalPolicy': 'never','config':engine_config(self.settings)})
                self.thread_id = result['thread']['id']
                if self.session_workspace:
                    self.session_workspace['thread_id']=self.thread_id
                    self.workspace_store.save(self.session_workspace)
                self.events.put({'local': 'new_thread', 'title': prompt[:30], 'project': project,
                                 'threadId': self.thread_id,'workspace':self.session_workspace})
            gateway_api('/guard/reset',{'thread_id':self.thread_id})
            self.artifact_locks.close()
            self.artifact_task,self.artifact_locks=TaskArtifacts(ROOT).begin(self.thread_id,project,prompt,images)
            self.events.put({'local':'task_artifacts','state':self.artifact_task})
            task_instructions=memory_instructions(self.thread_id)+TaskArtifacts(ROOT).instructions(self.thread_id)
            task_instructions+=self.workspace_store.instructions(self.session_workspace)
            result = self.rpc.request('turn/start', {'threadId': self.thread_id,
                     'cwd':self.artifact_task['workdir'],
                     'model': selected_model(self.settings),
                     'collaborationMode':{'mode':'default','settings':{'model':selected_model(self.settings),
                         'reasoning_effort':effort,'developer_instructions':task_instructions}},
                     'input': [{'type': 'text', 'text': prompt}] +
                              [{'type': 'localImage', 'path': path} for path in images], 'effort': effort})
            self.turn_id = result['turn']['id']
        self.background(work)

    def sync_send_button(self):
        steering = bool(self.busy and self.turn_id)
        enabled = not self.session_action_pending and not self.steer_pending and not self.loading_model and (not self.busy or steering)
        self.send_button.configure(state='normal' if enabled else 'disabled',
            text='引导  ↗' if steering else '发送  ↗')
        self.steer_note.configure(text='正在提交引导…' if self.steer_pending else
            '补充要求会接入后续处理，当前生成继续。' if steering else 'Ctrl+Enter 发送；生成中可提交引导。')

    def submit_steer(self, prompt):
        # Never restart a turn, release its locks, or clear its streamed output.
        thread_id,turn_id=self.thread_id,self.turn_id
        images=list(self.attachments)
        self.artifact_locks.allow_references(images)
        TaskArtifacts(ROOT).update_locks(thread_id,self.artifact_locks.paths)
        self.attachments.clear();self.attach_button.configure(text='添加图片')
        self.input.delete('1.0','end')
        self.steer_pending=True;self.sync_send_button()
        self.append('\n\n你 · 引导\n'+prompt+'\n')
        def work():
            try:
                result=self.rpc.request('turn/steer',{'threadId':thread_id,'expectedTurnId':turn_id,
                    'clientUserMessageId':str(uuid.uuid4()),
                    'input':[{'type':'text','text':prompt}]+[{'type':'localImage','path':path} for path in images]})
                if result.get('turnId')!=turn_id:
                    raise RuntimeError('引导返回了不同的任务编号，未更改当前任务。')
                self.events.put({'local':'steer_accepted','turnId':turn_id,'threadId':thread_id})
            except Exception as error:
                self.events.put({'local':'steer_failed','turnId':turn_id,'threadId':thread_id,
                    'text':str(error),'prompt':prompt,'images':images})
        self.background(work)

    def open_task_files(self):
        state=TaskArtifacts(ROOT).current(self.thread_id) if self.thread_id else None
        if state:
            os.startfile(state['workdir'])
            os.startfile(state['draft_directory'])
        else:
            os.startfile(str(ROOT/'tasks')) if (ROOT/'tasks').exists() else os.startfile(str(self.project))

    def release_artifact_locks(self):
        self.artifact_locks.close()
        if self.thread_id:
            TaskArtifacts(ROOT).finish(self.thread_id)

    def interrupt(self):
        if self.rpc and self.thread_id and self.turn_id and self.busy:
            self.background(lambda: self.rpc.request('turn/interrupt',
                   {'threadId': self.thread_id, 'turnId': self.turn_id}))

    def poll_generation_guard(self):
        if self.busy and self.thread_id:
            state=GuardStore(ROOT).read(self.thread_id)
            elapsed=time.monotonic()-self.turn_started_at if self.turn_started_at else 0
            if not state.get('blocked') and elapsed>guard_options(self.settings)['turn_seconds']:
                state=GuardStore(ROOT).write(self.thread_id,'本次任务超过 10 分钟，已暂停并保留进度；请查看结果后继续。','turn_timeout')
            if state.get('blocked') and state.get('id')!=self.guard_seen and self.turn_id:
                self.guard_seen=state['id']
                self.append('\n⚠ 已暂停：'+state['reason']+'\n',save=True)
                self.interrupt()
        self.after(250,self.poll_generation_guard)

    def change_guard_limits(self,value):
        if self.busy:
            self.append('\n› 当前任务结束后再修改防循环限制。\n',save=False)
            current=guard_options(self.settings)['reasoning_seconds']
            self.guard_picker.set('严格：思考 30 秒 · 单次生成 90 秒' if current<=30 else
                '宽松：思考 120 秒 · 单次生成 300 秒' if current>60 else '标准：思考 60 秒 · 单次生成 150 秒')
            return
        reasoning,generation=(30,90) if value.startswith('严格') else (120,300) if value.startswith('宽松') else (60,150)
        options=guard_options(self.settings);options.update(reasoning_seconds=reasoning,generation_seconds=generation)
        self.settings['generation_guard']=options;save_settings(self.settings)
        self.append('\n› 已保存限制：思考 '+str(reasoning)+' 秒，单次生成 '+str(generation)+' 秒。\n',save=False)

    def poll_events(self):
        try:
            for _ in range(150):
                event = self.events.get_nowait()
                self.handle_event(event)
        except queue.Empty:
            pass
        self.after(60, self.poll_events)

    def handle_event(self, event):
        local = event.get('local')
        params = event.get('params', {})
        method = event.get('method', '')
        if local=='resume_after_update':
            self.input.delete('1.0','end');self.input.insert('1.0',event['text'])
            self.send_prompt()
            return
        if local in ('thought_exported','thought_export_failed'):
            self.thought_export_button.configure(state='normal')
            if local=='thought_exported':
                self.thought_status.configure(text='完整日志已导出：'+event['path'])
                try:os.startfile(event['path'])
                except OSError:pass
            else:self.thought_status.configure(text='导出失败：'+event['text'])
            return
        if local in ('steer_accepted','steer_failed'):
            self.steer_pending=False
            if local=='steer_accepted':
                self.append('› 引导已提交；当前生成继续，后续步骤会接入补充要求。\n')
            else:
                existing=self.input.get('1.0','end').strip()
                self.input.delete('1.0','end')
                self.input.insert('1.0',event['prompt']+('\n\n'+existing if existing else ''))
                self.attachments=list(dict.fromkeys(event['images']+self.attachments))
                self.attach_button.configure(text=f'图片 {len(self.attachments)}' if self.attachments else '添加图片')
                self.append('⚠ 引导未应用，内容已保留在输入框：'+event['text']+'\n')
            self.sync_send_button()
            return
        if 'id' not in event and params.get('threadId') and params['threadId'] != self.thread_id:
            return
        if local == 'connected':
            self.refresh_proxy_status()
            if self.auto_launch_model and all(path.exists() for path in model_required_files(selected_model(self.settings))):
                self.auto_launch_model=False
                self.launch_model()
        elif local == 'error':
            if self.turn_id is None:self.release_artifact_locks()
            self.clear_stream_buffers()
            self.append('\n\n⚠ ' + event['text'] + '\n')
            if self.turn_id is None:
                self.busy = False
                self.send_button.configure(state='normal')
        elif local == 'task_artifacts':
            state=event['state']
            if state['isolated']:
                self.append('\n› 本轮输出目录：'+state['workdir']+'\n› 旧产物读取已锁；代码草稿自动保存，可点“打开本轮文件与草稿”。\n')
        elif local == 'proxy_changed':
            self.busy=False
            self.send_button.configure(state='normal')
            self.proxy_apply_button.configure(state='normal')
            self.proxy_enabled_var.set(bool(load_proxy_settings(ROOT).get('enabled')))
            self.proxy_apply_button.configure(text='关闭代理' if self.proxy_enabled_var.get() else '开启代理')
            self.refresh_proxy_status()
            self.append('\n› 代理设置已应用，可以继续当前对话。\n' if event.get('ok') else
                '\n⚠ 代理设置未应用：'+event.get('text','')+'\n',save=False)
        elif local in ('settings_applied','settings_failed'):
            self.settings=event['settings']
            self.busy=False
            self.loading_model=False
            self.send_button.configure(state='normal')
            self.apply_button.configure(state='normal')
            self.update_model_labels()
            self.cache_picker.set(next(label for label,value in CACHE_OPTIONS.items() if value==self.settings.get('kv_cache_location','auto')))
            self.model_picker.set(MODELS[selected_model(self.settings)]['label'])
            self.preview_model(self.model_picker.get())
            if local=='settings_applied':
                self.append('\n› 模型与上下文已应用，可以继续当前对话。\n',save=False)
            else:
                outcome='设置未应用，已恢复原设置：' if event.get('restored') else '设置未应用，恢复尚未完成，请重新启动模型：'
                self.append('\n⚠ '+outcome+event['text']+'\n',save=False)
        elif local in ('session_deleted','session_restored','session_action_failed'):
            self.session_action_pending=False
            self.send_button.configure(state='normal')
            self.sessions=self.load_sessions()
            self.render_sessions()
            if local=='session_deleted':
                if self.thread_id==event['thread_id']:
                    self.thread_id=None
                    self.new_chat()
                self.append('\n› 会话已删除，可以点击“撤销上次删除”恢复。\n',save=False)
            elif local=='session_restored':
                self.append('\n› 已恢复删除的会话。\n',save=False)
            else:
                self.append('\n⚠ '+event['text']+'\n',save=False)
        elif local == 'new_thread':
            self.sessions.insert(0, {'id': event['threadId'], 'title': event['title'],
                                   'project': event['project'],'workspace':event.get('workspace')})
            self.persist_sessions()
            self.render_sessions()
        elif local == 'resumed':
            self.thread_id = event['threadId']
        elif method == 'item/agentMessage/delta':
            if self.current_item != params.get('itemId'):
                if self.current_item:
                    self.append('\n\n')
                self.current_item = params.get('itemId')
                self.chat._textbox.mark_set('assistant_begin','end-1c')
                self.chat._textbox.mark_gravity('assistant_begin','left')
                self.chat._textbox.mark_set('assistant_end','end-1c')
                self.chat._textbox.mark_gravity('assistant_end','left')
            item_id = params.get('itemId')
            text = self.message_buffers.get(item_id,'') + params.get('delta','')
            self.message_buffers[item_id] = text
            shown = self.clean_answer(text)
            self.chat.configure(state='normal')
            self.chat.delete('assistant_begin','assistant_end')
            self.chat._textbox.mark_gravity('assistant_end','right')
            self.chat.insert('assistant_begin', shown or '正在整理回答…')
            self.chat._textbox.mark_gravity('assistant_end','left')
            self.chat.see('end')
            self.chat.configure(state='disabled')
        elif method in ('item/reasoning/textDelta', 'item/reasoning/summaryTextDelta'):
            self.status.configure(text='正在思考…', text_color=ACCENT)
        elif method == 'turn/started':
            self.turn_id = params.get('turn', {}).get('id', self.turn_id)
            self.turn_visible_output=False
            self.turn_started_at=time.monotonic()
            self.last_turn_tokens=None
        elif method == 'turn/completed':
            self.release_artifact_locks()
            self.clear_stream_buffers()
            self.busy = False
            self.send_button.configure(state='normal')
            self.turn_id = None
            self.append('\n')
            error = params.get('turn', {}).get('error')
            if error:
                self.append('\n⚠ ' + str(error.get('message', error)) + '\n')
            elif not self.turn_visible_output:
                used=(self.last_turn_tokens or {}).get('totalTokens',0)
                reason='本轮可能已耗尽服务窗口，' if used>=active_model().get('context',self.settings['context'])-256 else ''
                self.append('\n⚠ '+reason+'模型没有产生正文或工具结果。请检查运行日志，或压缩对话后重试。\n')
            self.turn_started_at=None
            self.save_transcript()
            self.refresh_files()
        elif method == 'item/started':
            item = params.get('item', {})
            kind = item.get('type')
            if kind == 'commandExecution':
                self.turn_visible_output=True
                self.append('\n\n› 执行：' + item.get('command', '')[:900] + '\n')
            elif kind == 'fileChange':
                self.turn_visible_output=True
                self.append('\n\n› 修改文件\n')
            elif kind == 'contextCompaction':
                self.append('\n› 正在压缩上下文并保留任务进度…\n')
        elif method == 'item/completed':
            item = params.get('item', {})
            if item.get('type') == 'agentMessage':
                streamed=item.get('id') in self.message_buffers
                text = self.message_buffers.pop(item.get('id'),item.get('text',''))
                shown=self.clean_answer(text)
                if shown.strip():
                    self.turn_visible_output=True
                    if not streamed:
                        self.append(shown,save=False)
                self.transcript.append(shown)
            elif item.get('type') == 'commandExecution':
                output = item.get('aggregatedOutput', '')
                if output:
                    self.append(output[:6000] + ('\n[界面已折叠较长输出]' if len(output) > 6000 else '') + '\n')
            elif item.get('type') == 'fileChange':
                for change in item.get('changes', []):
                    self.append('  ' + change.get('path', '') + '\n')
            elif item.get('type') == 'contextCompaction':
                self.clear_stream_buffers()
                self.save_transcript()
                self.append('› 上下文已压缩，临时缓冲已清理。\n')
        elif method == 'thread/tokenUsage/updated':
            token = params.get('tokenUsage', {})
            last = token.get('last', {})
            self.last_turn_tokens=last
            working,compact=engine_limits(self.settings)
            self.usage.configure(text=f"上次请求输入 {last.get('inputTokens', 0):,} · 缓存 {last.get('cachedInputTokens', 0):,} · 输出 {last.get('outputTokens', 0):,} · 工作上下文 {working:,} · 自动确认")
        elif method == 'error':
            self.append('\n⚠ ' + str(params.get('error', params)) + '\n')
        if 'id' in event and method:
            if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
                self.rpc.send({'id': event['id'], 'result': {'decision': 'accept'}})
            elif method == 'item/permissions/requestApproval':
                self.rpc.send({'id': event['id'], 'result': {
                    'permissions': params.get('permissions', {}), 'scope': 'session'}})
            elif method == 'item/tool/requestUserInput':
                self.user_questions(event)
            else:
                self.rpc.send({'id': event['id'], 'error': {'code': -32601, 'message': 'Unsupported client request'}})
        self.sync_send_button()

    @staticmethod
    def clean_answer(text):
        # Hide Jack's state XML in the UI while preserving it in the engine's model history.
        tags = 'workspace_state|grounded_source|anchor_fact|deterministic_check|pitfall_check'
        text = re.sub(r'<('+tags+r')\b[^>]*>.*?</\1>', '', text, flags=re.S|re.I)
        text = re.sub(r'<('+tags+r')\b[^>]*>.*$', '', text, flags=re.S|re.I)
        text = re.sub(r'^\s*FINAL ANSWER\s*:\s*', '', text, flags=re.I)
        text = re.sub(r'<tool_call>.*?(?:</tool_call>|$)',
            '\n⚠ 模型将工具调用写成了文本，这项操作尚未执行。可以重新引导它使用实际工具。\n',
            text,flags=re.S|re.I)
        return text.lstrip()

    def user_questions(self, event):
        from tkinter.simpledialog import askstring
        answers = {}
        for q in event['params'].get('questions', []):
            labels = '\n'.join(o.get('label', '') for o in q.get('options', []))
            answer = askstring('需要你的补充', q.get('question', '') + '\n' + labels, parent=self)
            answers[q['id']] = {'answers': [answer or '']}
        self.rpc.send({'id': event['id'], 'result': {'answers': answers}})

    def refresh_status(self):
        ready = server_ready()
        if self.busy:
            elapsed=int(time.monotonic()-self.turn_started_at) if self.turn_started_at else 0
            label=f'任务运行中 · {elapsed} 秒'
            try:
                routing=json.loads((ROOT/'request-routing.json').read_text(encoding='utf-8'))
                if routing.get('phase')=='switching':
                    label=f'正在切换上下文缓存 · {elapsed} 秒'
            except (OSError,ValueError):
                pass
            visible_stream=any(self.clean_answer(text).strip() for text in self.message_buffers.values())
            if ready:
                try:
                    slot=next((slot for slot in api('/slots',timeout=1) if slot.get('is_processing')),None)
                    if slot:
                        decoded=(slot.get('next_token') or [{}])[0].get('n_decoded',0)
                        self.speed_label=self.token_speed.update(
                            (active_model().get('pid'),slot.get('id_task'),self.turn_id), decoded,
                            average=slot.get('generation_average_tps'))
                        stage='等待正文'
                        try:
                            generation=json.loads((ROOT/'generation-status.json').read_text(encoding='utf-8'))
                            if generation.get('phase') in ('function_call','custom_tool_call'):
                                stage='正在生成文件修改' if generation.get('tool_name')=='apply_patch' else '正在生成工具调用'
                            elif generation.get('phase')=='reasoning':
                                stage='正在思考'
                            elif generation.get('phase')=='message':
                                stage='正在整理正文'
                        except (OSError,ValueError):
                            pass
                        label=f'{stage} · 本轮 {elapsed} 秒 · 当前生成 {decoded:,} token（含思考）'
                        if decoded==0:
                            processed=slot.get('n_prompt_tokens_processed')
                            try:total=json.loads((ROOT/'request-routing.json').read_text(encoding='utf-8')).get('prompt_tokens')
                            except (OSError,ValueError):total=None
                            if isinstance(processed,int):
                                label=f'正在处理输入 · {processed:,}'+(f' / 约 {total:,} token' if total else ' token')
                                label+=f' · 已复用 {slot.get("n_prompt_tokens_cache",0):,} token · 本轮 {elapsed} 秒'
                            elif slot.get('generation_phase')=='prefill':label=f'正在处理输入 · 本轮 {elapsed} 秒'
                        if self.speed_label:label+='\n'+self.speed_label
                except (OSError,ValueError):
                    pass
        elif ready:
            label = '●  本地模型已就绪'
            if self.speed_label:label+=' · 上次 '+self.speed_label
        elif self.loading_model or (self.model_proc and self.model_proc.poll() is None):
            label = '模型加载中…'
        else:
            label = '模型未启动'
        self.status.configure(text=label, text_color=ACCENT if ready else MUTED)
        name=selected_model(self.settings)
        file=model_file(name)
        partial = file.with_suffix('.gguf.partial')
        size = file.stat().st_size if file.exists() else partial.stat().st_size if partial.exists() else 0
        projector = vision_file(self.settings)
        vision_partial = projector.with_suffix('.gguf.partial')
        vision_size = (projector.stat().st_size if projector.exists() else vision_partial.stat().st_size if vision_partial.exists() else 0) if model_supports_vision(name) else 0
        total=MODELS[name]['size']+(931146528 if model_supports_vision(name) else 0)
        percent = min((size + vision_size) / total, 1)
        progress_path = ROOT / 'logs' / 'download-progress.json'
        if progress_path.exists() and not all(path.exists() for path in model_required_files(name)):
            try:
                data = json.loads(progress_path.read_text(encoding='utf-8'))
                size, vision_size = data['bytes'], 0
                percent = min(data['bytes'] / data['total'], 1)
            except (OSError, ValueError, KeyError):
                pass
        self.progress.set(percent)
        live=active_model()
        live_text=(f"{MODELS.get(live.get('model'),{}).get('label','未启动')} / {BACKENDS.get(live.get('backend','vulkan'),{}).get('label','未知后端')} / 服务窗口 {live.get('context',0):,} token / "
                   f"{'动态显卡' if live.get('kv_cache_location')=='dynamic' else '显卡' if live.get('kv_cache_location')=='gpu' else '内存'}缓存 / 对话上限 {self.settings['context']:,} token") if ready else label
        component_label = '模型与视觉组件' if model_supports_vision(name) else '纯文字模型'
        self.model_info.configure(text=f"{component_label}：{percent:.1%}  ({(size + vision_size) / 1e9:.2f} / {total / 1e9:.2f} GB)\n状态：{label}\n当前服务：{live_text}\n模型目录：{file.parent}")
        self.refresh_proxy_status()
        self.after(1000, self.refresh_status)

    def choose_project(self):
        if self.busy or self.steer_pending:
            return
        path = filedialog.askdirectory(initialdir=str(self.project), title='选择你的项目')
        if path:
            self.settings['project'] = path
            from core import save_settings
            save_settings(self.settings)
            self.new_chat(project_override=path)
            self.refresh_files()

    def choose_workspace_root(self):
        if self.busy:return
        path=filedialog.askdirectory(initialdir=self.settings['session_workspace_root'],title='选择新会话文件夹的保存位置')
        if path:
            self.settings['session_workspace_root']=str(Path(path).resolve())
            save_settings(self.settings)
            self.append('\n› 后续新会话文件夹将保存在：'+self.settings['session_workspace_root']+'\n',save=False)

    def attach_image(self):
        if not model_supports_vision(selected_model(self.settings)):
            self.append('\n› 当前模型不支持图片；请在模型设置中选择支持视觉的模型。\n',save=False)
            return
        paths = filedialog.askopenfilenames(title='添加图片', filetypes=[('图片', '*.png *.jpg *.jpeg *.webp')])
        self.attachments.extend(paths)
        self.attach_button.configure(text=f'{len(self.attachments)} 张图片' if self.attachments else '添加图片')

    def new_chat(self,project_override=None):
        if self.busy or self.steer_pending or self.session_action_pending:
            return
        try:workspace=self.workspace_store.create(self.settings)
        except OSError as error:
            self.append('\n⚠ 无法创建会话文件夹：'+str(error)+'\n',save=False)
            return
        self.save_transcript()
        self.detach_thread()
        self.session_workspace=workspace
        if project_override:
            self.session_workspace['project']=str(Path(project_override).resolve())
            self.workspace_store.save(self.session_workspace)
        self.project=Path(self.session_workspace['project'])
        self.project_label.configure(text=str(self.project))
        self.guard_seen=None
        self.thread_id = None
        self.turn_id = None
        self.current_item = None
        self.message_buffers.clear()
        self.transcript = []
        self.chat.configure(state='normal')
        self.chat.delete('1.0', 'end')
        self.chat.configure(state='disabled')
        self.attachments.clear();self.attach_button.configure(text='添加图片')
        self.input.delete('1.0','end')
        self.append('◈ 新对话\n本会话文件夹：'+self.session_workspace['workspace']+'\n当前项目：' + str(self.project) + '\n', save=False)
        self.refresh_files()
        self.tabs.set('对话')

    def detach_thread(self):
        # Let the engine expire an unused conversation; its rollout remains on disk.
        old_id = self.thread_id
        if self.rpc and old_id:
            self.background(lambda: self.rpc.request('thread/unsubscribe', {'threadId': old_id}))

    def load_sessions(self):
        try:
            return json.loads((ROOT / 'conversations' / 'index.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return []

    def persist_sessions(self):
        (ROOT / 'conversations' / 'index.json').write_text(json.dumps(self.sessions, ensure_ascii=False, indent=2), encoding='utf-8')

    def render_sessions(self):
        for widget in self.session_frame.winfo_children():
            widget.destroy()
        for session in self.sessions[:40]:
            row=ctk.CTkFrame(self.session_frame,fg_color='transparent')
            row.pack(fill='x',pady=3)
            self.button(row,session['title'][:12],lambda s=session:self.resume_session(s),
                        anchor='w',width=130).pack(side='left',fill='x',expand=True)
            self.button(row,'删除',lambda s=session:self.delete_session(s),width=42,
                        text_color=MUTED).pack(side='right',padx=(3,0))
        self.undo_delete_button.configure(state='normal' if self.session_store.deleted_sessions()
                                          and not self.session_action_pending else 'disabled')

    def delete_session(self, session):
        if self.busy or self.steer_pending or self.session_action_pending:
            self.append('\n› 请等当前任务完成后再删除会话。\n',save=False)
            return
        if not self.rpc:
            self.append('\n› 编程引擎正在连接，请稍后再删除。\n',save=False)
            return
        self.save_transcript()
        self.session_action_pending=True
        self.send_button.configure(state='disabled')
        thread_id=session['id']
        def work():
            archived=False
            try:
                self.rpc.request('thread/archive',{'threadId':thread_id})
                archived=True
                self.session_store.delete(thread_id)
                self.events.put({'local':'session_deleted','thread_id':thread_id})
            except Exception as error:
                if archived:
                    try:self.rpc.request('thread/unarchive',{'threadId':thread_id})
                    except Exception:pass
                self.events.put({'local':'session_action_failed','text':str(error)})
        self.background(work)

    def undo_delete_session(self):
        if self.busy or self.steer_pending or self.session_action_pending or not self.rpc:
            return
        records=self.session_store.deleted_sessions()
        if not records:return
        thread_id=records[-1]['session']['id']
        self.session_action_pending=True
        self.send_button.configure(state='disabled')
        def work():
            unarchived=False
            try:
                self.rpc.request('thread/unarchive',{'threadId':thread_id})
                unarchived=True
                self.session_store.restore(thread_id)
                self.events.put({'local':'session_restored','thread_id':thread_id})
            except Exception as error:
                if unarchived:
                    try:self.rpc.request('thread/archive',{'threadId':thread_id})
                    except Exception:pass
                self.events.put({'local':'session_action_failed','text':str(error)})
        self.background(work)

    def save_transcript(self):
        if self.thread_id and self.transcript:
            with (ROOT / 'conversations' / (self.thread_id + '.txt')).open('a', encoding='utf-8') as file:
                file.write(''.join(self.transcript))
            self.transcript.clear()

    def restore_after_update(self):
        if not self.rpc:
            self.after(500,self.restore_after_update);return
        try:
            path=ROOT/'resume-after-moe32.json'
            data=json.loads(path.read_text(encoding='utf-8'))
            if data.get('consumed') or not data.get('authorized_by_user'):return
            session=next(s for s in self.sessions if s['id']==data['thread_id'])
            data['consumed']=True;path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
            self.resume_session(session,continue_text=data['prompt'])
        except (OSError,ValueError,KeyError,StopIteration) as error:
            self.append('\n⚠ 更新后恢复任务失败：'+str(error)+'\n',save=False)

    def resume_session(self, session, continue_text=None):
        if self.busy or self.steer_pending or self.session_action_pending or not self.rpc:
            return
        self.save_transcript()
        if session['id'] != self.thread_id:
            self.detach_thread()
        self.project = Path(session['project'])
        self.session_workspace=session.get('workspace')
        self.guard_seen=None
        self.project_label.configure(text=str(self.project))
        self.thread_id = session['id']
        path = ROOT / 'conversations' / (session['id'] + '.txt')
        if path.exists():
            with path.open('rb') as file:
                file.seek(max(0, path.stat().st_size - DISPLAY_CHARS * 4))
                transcript = file.read().decode('utf-8', errors='ignore')[-DISPLAY_CHARS:]
        else:
            transcript = '会话已恢复。\n'
        self.transcript = []
        self.message_buffers.clear()
        self.current_item = None
        self.chat.configure(state='normal')
        self.chat.delete('1.0', 'end')
        self.chat.configure(state='disabled')
        self.append(transcript, save=False)
        self.tabs.set('对话')
        self.refresh_files()
        def work():
            self.rpc.request('thread/resume', {'threadId': session['id'],
                'cwd': str(self.project), 'excludeTurns': True, 'approvalPolicy': 'never',
                'sandbox': 'danger-full-access','model':selected_model(self.settings),'modelProvider':'qwen_local',
                'config':engine_config(self.settings)})
            if continue_text:self.events.put({'local':'resume_after_update','text':continue_text})
        self.background(work)

    def refresh_files(self):
        self.tree.delete(*self.tree.get_children())
        if self.project.is_dir():
            self.populate('', self.project)

    def populate(self, parent, directory):
        ignored = {'.git', 'node_modules', '__pycache__', '.venv', 'build', 'dist', 'research'}
        try:
            files = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            for p in files[:400]:
                if p.name in ignored:
                    continue
                item = self.tree.insert(parent, 'end', text=('▸ ' if p.is_dir() else '  ') + p.name, values=[str(p)])
                if p.is_dir():
                    self.tree.insert(item, 'end', text='…')
        except OSError:
            pass

    def expand_folder(self, event=None):
        item = self.tree.focus()
        values = self.tree.item(item, 'values')
        if not values:
            return
        children = self.tree.get_children(item)
        if len(children) == 1 and self.tree.item(children[0], 'text') == '…':
            self.tree.delete(children[0])
            self.populate(item, Path(values[0]))

    def open_file(self, event=None):
        item = self.tree.focus()
        values = self.tree.item(item, 'values')
        if not values:
            return
        path = Path(values[0])
        if not path.is_file():
            return
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('文件超过 2MB，请用外部编辑器打开。')
            text = path.read_text(encoding='utf-8-sig')
            if '\x00' in text:
                raise ValueError('此文件为二进制，不能作为文本编辑。')
            if self.open_path and self.editor.get('1.0', 'end-1c') != self.original:
                if not messagebox.askyesno('未保存修改', '放弃当前文件的未保存修改？'):
                    return
            self.open_path, self.original = path, text
            self.editor.delete('1.0', 'end')
            self.editor.insert('1.0', text)
            self.file_label.configure(text=path.name)
        except (OSError, UnicodeError, ValueError) as e:
            messagebox.showinfo('不能打开文件', str(e))

    def save_file(self):
        if not self.open_path:
            return
        if self.busy:
            messagebox.showinfo('文件正在被使用', '请等当前任务完成后再手动保存。')
            return
        if self.open_path.read_text(encoding='utf-8-sig') != self.original:
            messagebox.showinfo('文件已更改', '磁盘文件已被其他程序修改，请重新打开后编辑。')
            return
        text = self.editor.get('1.0', 'end-1c')
        import hashlib
        name = time.strftime('%Y%m%d-%H%M%S') + '-' + hashlib.sha256(str(self.open_path).encode()).hexdigest()[:8] + '-' + self.open_path.name
        (ROOT / 'backups' / name).write_bytes(self.open_path.read_bytes())
        self.open_path.write_text(text, encoding='utf-8')
        self.original = text
        self.file_label.configure(text=self.open_path.name + ' · 已保存')

    def show_diff(self):
        if not self.open_path:
            return
        diff = ''.join(difflib.unified_diff(self.original.splitlines(True),
                   self.editor.get('1.0', 'end-1c').splitlines(True), fromfile='修改前', tofile='修改后'))
        win = ctk.CTkToplevel(self)
        win.title('修改差异 · ' + self.open_path.name)
        win.geometry('900x650')
        box = ctk.CTkTextbox(win, font=('Consolas', 13))
        box.pack(fill='both', expand=True, padx=15, pady=15)
        box.insert('1.0', diff or '当前没有修改。')
        box.configure(state='disabled')

    def close_app(self):
        if self.session_action_pending or self.steer_pending:
            self.append('\n› 正在提交引导或保存会话变更，请稍候。\n',save=False)
            return
        if self.busy:
            if getattr(self,'closing_after_interrupt',False):return
            if not messagebox.askyesno('任务还在运行', '停止当前任务并退出？'):
                return
            self.closing_after_interrupt=True
            self.interrupt()
            self.after(200,self.close_after_interrupt)
            return
        self.save_transcript()
        self.artifact_locks.close()
        if self.rpc:
            self.rpc.close()
        self.thought_reader.close()
        self.destroy()

    def close_after_interrupt(self):
        # Keep the RPC consumer alive until the native turn has actually ended.
        # Closing stdin immediately after queuing interrupt leaves orphan work.
        if self.busy:
            self.after(200,self.close_after_interrupt)
        else:
            self.closing_after_interrupt=False
            self.close_app()

if __name__ == '__main__':
    if '--web-tools' in sys.argv:
        from web_tools import serve
        serve()
        sys.exit(0)
    if '--verify-moe35' in sys.argv:
        from verify_moe35 import widgets
        result=widgets()
        (ROOT/'verification-moe35-widgets.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        sys.exit(0 if result['ok'] else 1)
    if '--verify-work33' in sys.argv:
        from verify_work33 import verify_widgets
        report=verify_widgets()
        (ROOT/'verification-work33-widgets.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        sys.exit(0 if report['ok'] else 1)
    if '--verify-speed32' in sys.argv:
        from verify_moe32 import verify_widgets
        report=verify_widgets()
        (ROOT/'verification-widgets32.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        sys.exit(0 if report['ok'] else 1)
    if '--prepare-directive-profiles' in sys.argv:
        from core import load_settings
        candidate=load_settings()
        candidate['directive_mode']='obedient'
        candidate['jack_xml_enabled']=False
        prepare(candidate)
        sys.exit(0)
    if '--prepare-native-thinking' in sys.argv:
        from core import load_settings
        candidate=load_settings()
        candidate['directive_mode']='native'
        candidate['jack_xml_enabled']=False
        prepare(candidate)
        sys.exit(0)
    if '--prepare-history-repair' in sys.argv:
        candidate=prepare()
        candidate.update(history_mode='memory',work_context=WORK_CONTEXT)
        prepare(candidate)
        sys.exit(0)
    if '--verify-history-repair' in sys.argv or '--verify-draft-guard' in sys.argv:
        from core import load_settings
        original_settings=(ROOT/'settings.json').read_bytes()
        candidate={**load_settings(),'history_mode':'memory','work_context':WORK_CONTEXT}
        # The frozen UI check must not prepare or rewrite the user's saved home.
        prepare=lambda:candidate
        app=App(smoke=True)
        app.withdraw();app.update()
        working,compact=engine_limits(app.settings)
        checks={'work_context_95k':working==WORK_CONTEXT,'auto_compact_82k':compact==WORK_COMPACT,
                'picker_95k':app.work_picker.get()==str(WORK_CONTEXT//1024)+'K','send_button':bool(app.send_button.winfo_exists()),
                'draft_button':bool(app.draft_button.winfo_exists()),
                'steer_hint':bool(app.steer_note.winfo_exists()),
                'jack_xml_switch':bool(app.jack_xml_switch.winfo_exists()),
                'jack_xml_value':app.jack_xml_var.get()==(selected_directive(candidate)=='legacy'),
                'directive_picker':bool(app.directive_picker.winfo_exists()),
                'directive_picker_value':app.directive_picker.get()==DIRECTIVE_MODES[selected_directive(candidate)],
                'custom_tag_editor':bool(app.directive_tag.winfo_exists()),
                'custom_text_editor':bool(app.directive_text.winfo_exists()),
                'emotion_picker':bool(app.emotion_picker.winfo_exists()),
                'emotion_strength_slider':bool(app.emotion_slider.winfo_exists()),
                'emotion_signed_range':app.emotion_slider.cget('from_')==-0.5 and app.emotion_slider.cget('to')==0.5,
                'emotion_slider_resolution':app.emotion_slider.cget('number_of_steps')==10000,
                'emotion_strength_preserved':round(app.emotion_slider.get(),4)==round(candidate.get('emotion_strength',0.002),4),
                'emotion_second_signed_range':app.emotion_secondary_slider.cget('from_')==-0.5 and app.emotion_secondary_slider.cget('to')==0.5,
                'emotion_second_default_matches':app.emotion_secondary_picker.get()==EMOTION_MODES[candidate.get('emotion_secondary_mode','off')],
                'joy_sad_choices':all(EMOTION_MODES[mode] in app.emotion_picker.cget('values') for mode in ('joyful','sad')),
                'emotion_defaults_match':app.emotion_picker.get()==EMOTION_MODES[candidate.get('emotion_mode','off')],
                'project_files':bool(app.tree.get_children()),
                'user_settings_unchanged':original_settings==(ROOT/'settings.json').read_bytes()}
        app.busy=True;app.turn_id='private-ui-check';app.sync_send_button()
        checks['steer_button_enabled']=app.send_button.cget('state')=='normal' and app.send_button.cget('text')=='引导  ↗'
        app.steer_pending=True;app.sync_send_button()
        checks['steer_duplicate_disabled']=app.send_button.cget('state')=='disabled'
        app.steer_pending=False;app.busy=False;app.turn_id=None;app.sync_send_button()
        checks['normal_send_restored']=app.send_button.cget('state')=='normal' and app.send_button.cget('text')=='发送  ↗'
        if selected_directive(candidate)!='legacy':
            from core import chat_template_state
            template=chat_template_state(MODEL,candidate)
            checks['native_template_in_bundle']=template['policy'] in ('jack-native-v25','jack-profile-v26')
            source=Path(template['file']).read_text(encoding='utf-8')
            checks['replacement_is_loaded']=('<Prime_Directive>' not in source if selected_directive(candidate)=='native'
                else json.dumps(build_directive(candidate),ensure_ascii=False) in source)
        report_name='verification-build23.json' if '--verify-draft-guard' in sys.argv else 'verification-build21.json'
        (ROOT/report_name).write_text(json.dumps({'ok':all(checks.values()),'checks':checks},indent=2),encoding='utf-8')
        app.destroy()
        sys.exit(0 if all(checks.values()) else 1)
    if '--prepare-history-performance' in sys.argv:
        candidate=prepare()
        candidate.update(history_mode='memory',work_context=WORK_CONTEXT,performance_mode='max',cpu_offload=False,kv_cache_location='auto')
        prepare(candidate)
        sys.exit(0)
    if '--history-server' in sys.argv:
        from history_memory import serve
        serve(sys.argv[sys.argv.index('--history-root')+1])
        sys.exit(0)
    if '--signal-model-console' in sys.argv:
        from core import signal_model_console_in_helper
        pid=int(sys.argv[sys.argv.index('--signal-model-console')+1])
        sys.exit(0 if signal_model_console_in_helper(pid) else 1)
    if '--verify-window-switch' in sys.argv:
        from verify_window_switch import main
        main()
        sys.exit(0)
    if '--verify-visible-output' in sys.argv:
        from verify_visible_output import main
        main()
        sys.exit(0)
    if '--gateway' in sys.argv:
        from gateway import serve
        serve()
        sys.exit(0)
    smoke = '--smoke-test' in sys.argv
    if not smoke and os.name == 'nt':
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\PersonalLocalCodexDesktop')
        if ctypes.windll.kernel32.GetLastError() == 183:
            sys.exit(0)
    app = App(smoke=smoke)
    if '--show-thought-log' in sys.argv:
        app.tabs.set('思考日志')
    if '--show-model-options' in sys.argv:
        app.tabs.set('模型与性能')
    if smoke:
        app.update()
        assert app.tree.get_children(), 'Project browser is empty'
        assert app.send_button.winfo_exists()
        assert app.tabs.get() == '对话'
        app.tabs.set('项目文件')
        app.update()
        app.tabs.set('模型与性能')
        for name, spec in MODELS.items():
            app.model_picker.set(spec['label'])
            app.preview_model(spec['label'])
            assert app.pending_model() == name
            cap = context_limits()[name]
            app.context_slider.set(MIN_CONTEXT)
            app.preview_context(app.context_slider.get())
            assert app.pending_context == MIN_CONTEXT
            app.context_slider.set(cap)
            app.preview_context(app.context_slider.get())
            assert abs(app.pending_context - cap) < 1024
            assert 0 < compact_for(app.pending_context) < app.pending_context
        app.model_picker.set(MODELS[selected_model(app.settings)]['label'])
        app.preview_model(app.model_picker.get())
        app.refresh_status()
        app.update()
        print('Native desktop UI smoke test OK')
        app.after(200, app.destroy)
    app.mainloop()
