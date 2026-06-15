"""Python 版本兼容模块"""

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum as StrEnum
else:
    # Python 3.10 兼容: 简易 StrEnum
    from enum import Enum

    class StrEnum(str, Enum):
        """Python 3.10 fallback: str + Enum 组合"""

        def __str__(self) -> str:
            return self.value

        @property
        def value(self) -> str:  # type: ignore[override]
            return super().value  # type: ignore[return-value]


__all__ = ["StrEnum"]
