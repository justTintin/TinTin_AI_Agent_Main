"""core/product_miner.py — 产品挖掘统计与配置验证。

从 product_library_page.py 下沉的纯逻辑函数。
"""
from typing import Any


def count_mined_products(items: list[dict[str, Any]]) -> tuple[int, int]:
    """统计已挖掘和待挖掘的产品数量。

    判定规则：features 和 selling_points 均非空且非纯空白，视为已挖掘。

    Args:
        items: 产品列表，每个产品包含 features, selling_points 字段

    Returns:
        (already_count, pending_count)
    """
    already = 0
    for it in items:
        features = (it.get("features") or "").strip()
        selling_points = (it.get("selling_points") or "").strip()
        if features and selling_points:
            already += 1
    return already, len(items) - already


def validate_mine_config(
    model: str = "",
    server_url: str = "",
) -> list[str]:
    """验证一键挖掘所需的配置是否完整。

    Args:
        model: LLM 模型名称
        server_url: 服务端地址

    Returns:
        错误信息列表（空列表表示配置完整）
    """
    errors = []
    if not model or not model.strip():
        errors.append("大模型未配置，请先填写模型名称")
    if not server_url or not server_url.strip():
        errors.append("服务端未配置，请先配置统一计算节点地址")
    return errors
