"""Real generation throughput from cumulative model counters, bounded storage."""
from collections import deque
import time


class TokenSpeed:
    def __init__(self, window=5):
        self.window=window
        self.samples=deque(maxlen=64)
        self.identity=None
        self.base=None
        self.last=None

    def update(self, identity, count, now=None, average=None):
        now=time.monotonic() if now is None else now
        count=max(0,int(count))
        if identity!=self.identity or (self.last and count<self.last[1]):
            self.samples.clear();self.identity=identity;self.base=(now,count)
            self.last=None
        if count==0:
            self.samples.clear();self.base=None;self.last=(now,0)
            return ''
        if self.base is None:self.base=(now,count)
        self.samples.append((now,count));self.last=(now,count)
        while len(self.samples)>2 and self.samples[1][0]<now-self.window:
            self.samples.popleft()
        first=self.samples[0]
        duration=now-first[0]
        current=(count-first[1])/duration if duration>=.5 else None
        if average is None and now-self.base[0]>=.5:
            average=(count-self.base[1])/(now-self.base[0])
        live='测量中' if current is None else f'{current:.1f}'
        mean='测量中' if average is None else f'{average:.1f}'
        return f'实时 {live} token/s · 平均 {mean} token/s（含思考）'
