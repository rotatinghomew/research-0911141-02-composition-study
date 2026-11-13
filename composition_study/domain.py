from collections import Counter, defaultdict
from statistics import mean, median
import math

from .validation import require_tables, unique, finite, references


def validate(data):
    require_tables(data, ["samples", "readings", "components"])
    unique(data["samples"], ["sample_id"])
    unique(data["readings"], ["sample_id", "component"])
    references(data["readings"], "sample_id", data["samples"], "sample_id")
    for sample in data["samples"]:
        finite(sample["dilution"], minimum=0.000001)
        if sample["total"] is not None:
            finite(sample["total"], minimum=0)
    for reading in data["readings"]:
        if reading["component"] not in data["components"] or reading["state"] not in {"measured", "below_limit", "not_added", "not_measured"}:
            raise ValueError("未知成分或观测状态")
        finite(reading["limit"], minimum=0)
        if reading["state"] == "measured":
            finite(reading["value"], minimum=0)
        elif reading["state"] == "not_added" and reading["value"] != 0:
            raise ValueError("未加入成分应记为结构零")
        elif reading["state"] in {"below_limit", "not_measured"} and reading["value"] is not None:
            raise ValueError("非定量观测不能提供精确数值")


def explore(data, selection):
    group = selection.get("group", "all")
    samples = {sample["sample_id"]: sample for sample in data["samples"] if group == "all" or sample["group"] == group}
    if not samples:
        raise ValueError("此配方没有样本")
    values, statuses = defaultdict(list), Counter()
    for reading in data["readings"]:
        sample = samples.get(reading["sample_id"])
        if sample is None:
            continue
        statuses[reading["state"]] += 1
        if reading["state"] == "measured":
            values[reading["component"]].append(reading["value"] * sample["dilution"])
    rows = [{"component": component, "quantified_n": len(values[component]),
             "mean_original_concentration": mean(values[component]) if values[component] else None}
            for component in data["components"]]
    return {"summary": {"样本数": len(samples), "有独立总量": sum(sample["total"] is not None for sample in samples.values()),
                        "未定量单元格": statuses["below_limit"] + statuses["not_measured"]},
            "rows": rows, "series": [{"label": row["component"], "y": row["mean_original_concentration"]} for row in rows],
            "notes": ["均值只描述成功定量的观测，不能替代完整组成或组间差异。", "结构零、检出限和未检测分别保留在原始记录中。"]}
