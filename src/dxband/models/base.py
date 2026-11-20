# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """持久化模型基类：拒绝隐式类型转换和未知字段。"""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)
