from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class RollingTextBuffer:
    max_chars: int | None = None
    _chunks: deque[str] = field(default_factory=deque, init=False, repr=False)
    _length: int = field(default=0, init=False, repr=False)
    _start_offset: int = field(default=0, init=False, repr=False)
    _cache: str = field(default="", init=False, repr=False)
    _dirty: bool = field(default=False, init=False, repr=False)

    def append(self, text: str) -> None:
        if not text:
            return
        self._chunks.append(text)
        self._length += len(text)
        self._dirty = True
        self._trim_if_needed()

    def clear(self) -> None:
        self._chunks.clear()
        self._length = 0
        self._start_offset = 0
        self._cache = ""
        self._dirty = False

    def get_text(self) -> str:
        if not self._dirty:
            return self._cache
        self._cache = "".join(self._chunks)
        self._dirty = False
        return self._cache

    def tail(self, max_chars: int) -> str:
        if max_chars <= 0 or self._length == 0:
            return ""
        if self._length <= max_chars:
            return self.get_text()

        remaining = max_chars
        pieces: list[str] = []
        for chunk in reversed(self._chunks):
            if remaining <= 0:
                break
            if len(chunk) <= remaining:
                pieces.append(chunk)
                remaining -= len(chunk)
            else:
                pieces.append(chunk[-remaining:])
                remaining = 0
        pieces.reverse()
        return "".join(pieces)

    @property
    def start_offset(self) -> int:
        return self._start_offset

    @property
    def end_offset(self) -> int:
        return self._start_offset + self._length

    def _trim_if_needed(self) -> None:
        if self.max_chars is None or self._length <= self.max_chars:
            return

        overflow = self._length - self.max_chars
        while overflow > 0 and self._chunks:
            head = self._chunks[0]
            head_length = len(head)
            if head_length <= overflow:
                self._chunks.popleft()
                self._length -= head_length
                self._start_offset += head_length
                overflow -= head_length
                continue

            self._chunks[0] = head[overflow:]
            self._length -= overflow
            self._start_offset += overflow
            overflow = 0
