import core

settings=core.load_settings()
settings['model']=core.MODEL
settings.setdefault('model_contexts',{})[core.MODEL]=102400
settings['model_contexts'][core.HUIHUI_MODEL]=core.context_limits()[core.HUIHUI_MODEL]
core.prepare(settings)
print('Default selections restored; credentials omitted',flush=True)
