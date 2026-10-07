"""Skill editor backed by the same revision-aware store the model uses."""
import os
from tkinter import messagebox
import customtkinter as ctk
from skill_memory import SkillMemory


class SkillPanel(ctk.CTkFrame):
    def __init__(self, parent, root, summarize):
        super().__init__(parent, fg_color='transparent')
        self.store = SkillMemory(root)
        self.current = None
        self.summarize = summarize
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        bar = ctk.CTkFrame(self, fg_color='transparent')
        bar.grid(row=0, column=0, sticky='ew', pady=8)
        self.picker = ctk.CTkOptionMenu(bar, values=['暂无技能'], command=self.choose, width=225)
        self.picker.pack(side='left', padx=4)
        for label, command in [('刷新', self.refresh), ('新建', self.new), ('保存修改', self.save),
                               ('总结本轮经验', summarize), ('打开目录', self.open_folder)]:
            ctk.CTkButton(bar, text=label, command=command, width=92).pack(side='left', padx=3)
        self.status = ctk.CTkLabel(self, text='模型可以随时保存或更新技能；修改会自动保留旧版。', anchor='w')
        self.status.grid(row=1, column=0, sticky='ew')
        self.name = ctk.CTkEntry(self, placeholder_text='技能名，例如 android-local-build')
        self.name.grid(row=2, column=0, sticky='ew', pady=5)
        self.description = ctk.CTkEntry(self, placeholder_text='何时调用这个技能')
        self.description.grid(row=3, column=0, sticky='ew', pady=5)
        self.body = ctk.CTkTextbox(self, wrap='word', font=('Microsoft YaHei UI', 13))
        self.body.grid(row=4, column=0, sticky='nsew', pady=5)
        self.refresh()

    def dirty(self):
        if self.current:
            return (self.description.get() != self.current['description'] or
                    self.body.get('1.0', 'end-1c') != self.current['body'])
        return bool(self.name.get() or self.description.get() or self.body.get('1.0', 'end-1c'))

    def refresh(self):
        # Native skill names remain selectable even as the library grows.
        names = sorted(p.name for p in self.store.skills.iterdir()
                       if p.is_dir() and not p.name.startswith('.') and (p / 'SKILL.md').is_file())
        self.picker.configure(values=names or ['暂无技能'])
        if names and not self.current and not self.dirty():
            self.choose(names[0])

    def choose(self, name):
        if name == '暂无技能':
            return
        if self.dirty() and not messagebox.askyesno('未保存修改', '放弃编辑框中的修改并读取技能？'):
            self.picker.set(self.current['name'] if self.current else '新建技能')
            return
        try:
            with self.store.locked():
                row = self.store._read(name)
            self.current = row
            self.name.configure(state='normal')
            self.name.delete(0, 'end')
            self.name.insert(0, row['name'])
            self.name.configure(state='disabled')
            self.description.delete(0, 'end')
            self.description.insert(0, row['description'])
            self.body.delete('1.0', 'end')
            self.body.insert('1.0', row['body'])
            self.picker.set(name)
            self.status.configure(text='已读取：' + row['path'] + ' · UTF-8 保存')
        except (OSError, ValueError) as error:
            messagebox.showinfo('技能读取失败', str(error))

    def new(self):
        if self.dirty() and not messagebox.askyesno('未保存修改', '放弃当前修改并新建？'):
            return
        self.current = None
        self.name.configure(state='normal')
        self.name.delete(0, 'end')
        self.description.delete(0, 'end')
        self.body.delete('1.0', 'end')
        self.status.configure(text='填写技能名称、调用条件和可复用经验，然后保存。')

    def save(self):
        try:
            result = self.store.save(self.name.get(), self.description.get(), self.body.get('1.0', 'end-1c'),
                                     expected_revision=(self.current or {}).get('revision'))
            with self.store.locked():
                self.current = self.store._read(result['name'])
            self.description.delete(0, 'end')
            self.description.insert(0, self.current['description'])
            self.body.delete('1.0', 'end')
            self.body.insert('1.0', self.current['body'])
            self.refresh()
            self.picker.set(result['name'])
            self.name.configure(state='disabled')
            self.status.configure(text='已保存：' + result['path'] + (' · 已备份旧版' if result['backup'] else ''))
        except (OSError, ValueError) as error:
            messagebox.showinfo('技能未保存', str(error))

    def open_folder(self):
        os.startfile(self.store.skills)
