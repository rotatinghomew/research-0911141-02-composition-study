"""配方比较的成分分析。

核心口径：
- 读数乘稀释倍数还原为原液浓度（与 data-contract 一致）。
- 未加入（not_added）是结构零：不代入小数，按配方结构差异单列，不参与对数比。
- 未检出（below_limit）不是零：主要假设默认成对排除；另提供半限、全限两种
  代入假设，全部假设的结果并列在敏感性表中，供复核结论是否依赖处理假设。
- 未检测（not_measured）在任何假设下都成对排除。
- 相对构成用对数比坐标（clr，参照为所选共同成分在样本内可定量子集的几何均值），
  避免百分比总和约束制造的伪相关；整体浓度用独立总量或所选成分小计，与相对构成
  分开报告。效应以倍数变化和置信区间表示，逐列 p 值经 BH 控制为 q 值。
"""
from statistics import mean, variance
import math


SCENARIOS = {
    "pairwise": "成对排除：未检出单元格不代入数值",
    "half_limit": "半限代入：未检出按检出限的一半（乘稀释倍数）计入",
    "at_limit": "全限代入：未检出按检出限（乘稀释倍数）计入",
}
DEFAULT_SCENARIO = "pairwise"
LOW_N = 3  # 单组可比样本低于此数时提示估计不稳定


# ---------------------------------------------------------------- 统计基础

def _betacf(a, b, x):
    """不完全 beta 函数的连分式求值（Numerical Recipes）。"""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-14:
            break
    return h


def _ibeta(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_bt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
              + a * math.log(x) + b * math.log(1.0 - x))
    bt = math.exp(log_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t, df):
    """t 分布累积概率。"""
    if df <= 0:
        raise ValueError("自由度必须为正")
    x = df / (df + t * t)
    ib = _ibeta(df / 2.0, 0.5, x)
    return 1.0 - 0.5 * ib if t >= 0 else 0.5 * ib


def t_ppf(prob, df):
    """t 分布分位数，二分求逆。"""
    lo, hi = -1.0, 1.0
    for _ in range(200):
        if t_cdf(lo, df) <= prob:
            break
        lo *= 2.0
    for _ in range(200):
        if t_cdf(hi, df) >= prob:
            break
        hi *= 2.0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        if t_cdf(mid, df) < prob:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def welch(xs, ys):
    """Welch 双样本比较；样本不足返回 None。效应为均值差（对数尺度）。"""
    if len(xs) < 2 or len(ys) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    diff = mx - my
    vx, vy = variance(xs), variance(ys)
    se2 = vx / len(xs) + vy / len(ys)
    if se2 <= 0:
        return {"effect": diff, "ci_low": diff, "ci_high": diff,
                "p": 1.0 if diff == 0 else 0.0, "df": None}
    se = math.sqrt(se2)
    df = se2 ** 2 / ((vx / len(xs)) ** 2 / (len(xs) - 1) + (vy / len(ys)) ** 2 / (len(ys) - 1))
    p = 2.0 * (1.0 - t_cdf(abs(diff) / se, df))
    crit = t_ppf(0.975, df)
    return {"effect": diff, "ci_low": diff - crit * se, "ci_high": diff + crit * se,
            "p": min(1.0, max(0.0, p)), "df": df}


def benjamini_hochberg(pvalues):
    """BH 控制的 q 值，与输入顺序一致。"""
    n = len(pvalues)
    order = sorted(range(n), key=lambda i: pvalues[i])
    qvalues = [0.0] * n
    prev = 1.0
    for rank in range(n - 1, -1, -1):
        prev = min(prev, pvalues[order[rank]] * n / (rank + 1))
        qvalues[order[rank]] = prev
    return qvalues


# ---------------------------------------------------------------- 方案与取值

def normalize_scheme(data, scheme):
    if not isinstance(scheme, dict):
        raise ValueError("比较方案必须是对象")
    groups = {sample["group"] for sample in data["samples"]}
    group_a, group_b = scheme.get("group_a"), scheme.get("group_b")
    if group_a not in groups or group_b not in groups:
        raise ValueError("比较两端必须是数据中存在的配方")
    if group_a == group_b:
        raise ValueError("比较两端应为不同配方")
    components = scheme.get("components")
    if not isinstance(components, list) or len(components) < 2:
        raise ValueError("至少选择两种成分构成比较子成分")
    if len(set(components)) != len(components):
        raise ValueError("成分选择存在重复")
    unknown = [str(c) for c in components if c not in data["components"]]
    if unknown:
        raise ValueError("选择了数据之外的成分：" + ",".join(unknown))
    below_limit = scheme.get("below_limit", DEFAULT_SCENARIO)
    if below_limit not in SCENARIOS:
        raise ValueError("未知的未检出处理假设：" + str(below_limit))
    return {"group_a": group_a, "group_b": group_b,
            "components": list(components), "below_limit": below_limit}


def options(data):
    groups = sorted({sample["group"] for sample in data["samples"]})
    return {"groups": groups, "components": list(data["components"]),
            "component_groups": data.get("component_groups") or {},
            "scenarios": dict(SCENARIOS), "default_scenario": DEFAULT_SCENARIO}


def _cell_value(reading, dilution, scenario):
    """返回原液浓度；不可用的单元格返回 None。结构零始终不参与。"""
    state = reading["state"]
    if state == "measured":
        return reading["value"] * dilution
    if state == "below_limit" and scenario != "pairwise":
        factor = 0.5 if scenario == "half_limit" else 1.0
        return reading["limit"] * dilution * factor
    return None


# ---------------------------------------------------------------- 主流程

def compare(data, scheme):
    scheme = normalize_scheme(data, scheme)
    group_a, group_b = scheme["group_a"], scheme["group_b"]
    selected = scheme["components"]
    samples = {g: [s for s in data["samples"] if s["group"] == g] for g in (group_a, group_b)}
    readings = {}
    for reading in data["readings"]:
        if reading["component"] in selected:
            readings[(reading["sample_id"], reading["component"])] = reading

    def cell(sample, component):
        return readings.get((sample["sample_id"], component))

    # 结构差异：成分在一端全部未加入时不进入对数比，单列说明。
    structural, shared, limitations = [], [], []
    for component in selected:
        states = {g: [(cell(s, component) or {"state": "not_measured"})["state"] for s in samples[g]]
                  for g in (group_a, group_b)}
        absent = [g for g in (group_a, group_b) if states[g] and all(s == "not_added" for s in states[g])]
        sporadic = {g: sum(s == "not_added" for s in states[g]) for g in (group_a, group_b)}
        if len(absent) == 2:
            structural.append({"component": component, "absent_in": [group_a, group_b],
                               "note": "两端配方均未加入，不参与比较"})
        elif absent:
            present = group_b if absent[0] == group_a else group_a
            quantified = sum(s == "measured" for s in states[present])
            structural.append({"component": component, "absent_in": absent,
                               "note": f"仅在 {present} 配方中存在（可定量 {quantified} 个样本），"
                                       "属于配方结构差异，不做对数比检验"})
        else:
            shared.append(component)
            for g in (group_a, group_b):
                if sporadic[g]:
                    limitations.append(f"成分 {component} 在 {g} 组内有 {sporadic[g]} 个样本记为未加入，"
                                       "这些单元格不参与对数比，请核对该配方记录是否一致")
    if len(shared) < 2:
        raise ValueError("两端共同可比较的成分不足两种，无法构成对数比坐标")

    group_info = {}
    for g in (group_a, group_b):
        cells = [cell(s, c) for s in samples[g] for c in selected]
        cells = [r for r in cells if r is not None]
        group_info[g] = {
            "samples": len(samples[g]),
            "batches": sorted({s["batch"] for s in samples[g]}),
            "with_total": sum(s["total"] is not None for s in samples[g]),
            "below_limit_cells": sum(r["state"] == "below_limit" for r in cells),
            "not_measured_cells": sum(r["state"] == "not_measured" for r in cells),
        }

    def sample_values(g, scenario):
        """每组每样本：共同成分 -> 原液浓度（按假设处理未检出）。"""
        rows = []
        for sample in samples[g]:
            values = {}
            for component in shared:
                reading = cell(sample, component)
                if reading is None:
                    continue
                value = _cell_value(reading, sample["dilution"], scenario)
                if value is not None and value > 0:
                    values[component] = value
            rows.append((sample, values))
        return rows

    def clr_rows(g, scenario):
        rows = []
        for sample, values in sample_values(g, scenario):
            if len(values) >= 2:
                reference = mean(math.log(v) for v in values.values())
                rows.append({c: math.log(v) - reference for c, v in values.items()})
        return rows

    def component_contrasts(scenario):
        rows_by_group = {g: clr_rows(g, scenario) for g in (group_a, group_b)}
        results = []
        for component in shared:
            xs = [row[component] for row in rows_by_group[group_a] if component in row]
            ys = [row[component] for row in rows_by_group[group_b] if component in row]
            test = welch(xs, ys)
            row = {"component": component, "n_a": len(xs), "n_b": len(ys),
                   "effect_log": None, "fold": None, "ci_low": None, "ci_high": None,
                   "p": None, "q": None, "flags": []}
            if test is None:
                row["flags"].append("可比样本不足，仅作描述")
            else:
                row.update({"effect_log": test["effect"], "fold": math.exp(test["effect"]),
                            "ci_low": test["ci_low"], "ci_high": test["ci_high"], "p": test["p"]})
                if min(len(xs), len(ys)) < LOW_N:
                    row["flags"].append("样本较少，区间估计不稳定")
            results.append(row)
        return results

    def balance_contrasts(scenario):
        component_groups = data.get("component_groups") or {}
        rows_by_group = {g: sample_values(g, scenario) for g in (group_a, group_b)}
        results = []
        for name, members in component_groups.items():
            inside = [c for c in members if c in shared]
            outside = [c for c in shared if c not in members]
            if not inside or not outside:
                continue
            series = {}
            for g in (group_a, group_b):
                values = []
                for _, cell_values in rows_by_group[g]:
                    head = [math.log(cell_values[c]) for c in inside if c in cell_values]
                    tail = [math.log(cell_values[c]) for c in outside if c in cell_values]
                    if head and tail:
                        values.append(mean(head) - mean(tail))
                series[g] = values
            test = welch(series[group_a], series[group_b])
            row = {"balance": name, "members": list(members), "n_a": len(series[group_a]),
                   "n_b": len(series[group_b]), "effect_log": None, "fold": None,
                   "ci_low": None, "ci_high": None, "p": None, "q": None, "flags": []}
            if test is None:
                row["flags"].append("可比样本不足，仅作描述")
            else:
                row.update({"effect_log": test["effect"], "fold": math.exp(test["effect"]),
                            "ci_low": test["ci_low"], "ci_high": test["ci_high"], "p": test["p"]})
                if min(len(series[group_a]), len(series[group_b])) < LOW_N:
                    row["flags"].append("样本较少，区间估计不稳定")
            results.append(row)
        return results

    def apply_q(rows_list):
        flat = [row for rows in rows_list for row in rows]
        testable = [row for row in flat if row["p"] is not None]
        for row, q in zip(testable, benjamini_hochberg([row["p"] for row in testable])):
            row["q"] = q

    def level_contrasts(scenario):
        rows = []
        totals = {g: [math.log(s["total"]) for s in samples[g]
                      if s["total"] is not None and s["total"] > 0] for g in (group_a, group_b)}
        test = welch(totals[group_a], totals[group_b])
        row = {"kind": "independent_total", "label": "独立总量",
               "n_a": len(totals[group_a]), "n_b": len(totals[group_b]),
               "effect_log": None, "fold": None, "ci_low": None, "ci_high": None, "p": None}
        if test is not None:
            row.update({"effect_log": test["effect"], "fold": math.exp(test["effect"]),
                        "ci_low": test["ci_low"], "ci_high": test["ci_high"], "p": test["p"]})
        rows.append(row)
        subtotals = {g: [] for g in (group_a, group_b)}
        for g in (group_a, group_b):
            for sample in samples[g]:
                total, complete = 0.0, True
                for component in selected:
                    reading = cell(sample, component)
                    if reading is None:
                        complete = False
                        break
                    if reading["state"] == "not_added":
                        continue  # 结构零真实贡献 0
                    value = _cell_value(reading, sample["dilution"], scenario)
                    if value is None:
                        complete = False
                        break
                    total += value
                if complete and total > 0:
                    subtotals[g].append(math.log(total))
        test = welch(subtotals[group_a], subtotals[group_b])
        row = {"kind": "selected_subtotal", "label": "所选成分小计（完整样本）",
               "n_a": len(subtotals[group_a]), "n_b": len(subtotals[group_b]),
               "effect_log": None, "fold": None, "ci_low": None, "ci_high": None, "p": None}
        if test is not None:
            row.update({"effect_log": test["effect"], "fold": math.exp(test["effect"]),
                        "ci_low": test["ci_low"], "ci_high": test["ci_high"], "p": test["p"]})
        rows.append(row)
        return rows

    # 主要假设下的结果
    primary = scheme["below_limit"]
    contrasts = component_contrasts(primary)
    balances = balance_contrasts(primary)
    apply_q([contrasts, balances])
    level = level_contrasts(primary)

    # 敏感性：全部假设重算，比较方向与显著性是否稳定
    scenario_results = {}
    for scenario in SCENARIOS:
        s_contrasts = component_contrasts(scenario)
        s_balances = balance_contrasts(scenario)
        apply_q([s_contrasts, s_balances])
        scenario_results[scenario] = {("成分", r["component"]): r for r in s_contrasts}
        scenario_results[scenario].update({("成分组", r["balance"]): r for r in s_balances})
    targets = ([("成分", r["component"]) for r in contrasts]
               + [("成分组", r["balance"]) for r in balances])
    sensitivity = []
    for kind, name in targets:
        row = {"target": f"{kind}:{name}", "stability": None}
        directions, significance = [], []
        for scenario in SCENARIOS:
            found = scenario_results[scenario].get((kind, name))
            testable = found is not None and found["p"] is not None
            row[f"{scenario}_fold"] = found["fold"] if testable else None
            row[f"{scenario}_q"] = found["q"] if testable else None
            if testable:
                directions.append(math.copysign(1, found["effect_log"]) if found["effect_log"] else 0.0)
                significance.append(found["q"] < 0.05)
        if len(directions) < 2:
            row["stability"] = "数据不足，部分假设下不可检验"
        elif len(set(directions)) > 1:
            row["stability"] = "方向依赖处理假设，结论不稳健"
        elif len(set(significance)) > 1:
            row["stability"] = "方向稳定，显著性随假设变化"
        else:
            row["stability"] = "方向与显著性均稳定"
        sensitivity.append(row)

    # 可比性限制
    batches_a, batches_b = (set(group_info[g]["batches"]) for g in (group_a, group_b))
    if not batches_a & batches_b:
        limitations.append(f"检测批次在两组间完全不重叠（{group_a}：{sorted(batches_a)}；"
                           f"{group_b}：{sorted(batches_b)}），配方差异与批次效应不可分")
    else:
        only_a, only_b = sorted(batches_a - batches_b), sorted(batches_b - batches_a)
        if only_a or only_b:
            limitations.append(f"部分检测批次仅出现在一端（仅 {group_a}：{only_a}；仅 {group_b}：{only_b}），"
                               "这些批次覆盖的差异无法用共同批次核对")
    for g in (group_a, group_b):
        info = group_info[g]
        if info["with_total"] < info["samples"]:
            limitations.append(f"{g} 组 {info['samples'] - info['with_total']}/{info['samples']} 个样本"
                               "缺少独立总量，整体浓度对比部分依赖所选成分小计，未测成分的影响无法排除")
    for row in contrasts + balances:
        name = row.get("component") or row.get("balance")
        if row["p"] is None:
            limitations.append(f"{name} 在主要假设下可比样本不足（{group_a} n={row['n_a']}，"
                               f"{group_b} n={row['n_b']}），未给出检验")
        elif min(row["n_a"], row["n_b"]) < LOW_N:
            limitations.append(f"{name} 可比样本较少（{group_a} n={row['n_a']}，{group_b} n={row['n_b']}），"
                               "区间与 q 值仅供参考")
    imputed = sum(group_info[g]["below_limit_cells"] for g in (group_a, group_b))
    if imputed and primary == "pairwise":
        limitations.append(f"所选范围内有 {imputed} 个未检出单元格在主要假设下被成对排除，"
                           "相关结论请在敏感性表中对照代入假设复核")
    if primary != "pairwise" and imputed:
        limitations.append(f"主要假设对 {imputed} 个未检出单元格作了代入，"
                           "结果解释依赖该假设，请对照敏感性表")
    if structural:
        limitations.append("对数比参照集为两端共同成分：" + "、".join(shared)
                           + "；结构差异成分不进入参照，单列于结构差异表")

    notes = [
        "读数已乘稀释倍数还原为原液浓度；未加入（结构零）不代入小数，按配方结构差异单列。",
        "百分比归一会强制成分此消彼长，逐列检验会把总和约束误报为差异；这里用对数比坐标，"
        "效应为相对共同成分几何均值的倍数变化（fold），并给出 95% 置信区间。",
        "整体浓度与相对构成分开报告：前者看独立总量或所选成分小计，后者看对数比对比，"
        "两者结论可以不一致，例如总量翻倍而构成不变。",
        "q 值对本方案内全部成分与成分组对比做 BH 控制；探索中改选成分会改变控制范围，"
        "所选成分与处理假设已随方案留档，旧结果按当时方案解释。",
        "敏感性表在全部处理假设下重算同一方案；标注“依赖假设”的差异不应按单一假设下结论。",
    ]

    return {"scheme": scheme, "groups": group_info, "level": level,
            "contrasts": contrasts, "balances": balances, "structural": structural,
            "sensitivity": sensitivity, "limitations": limitations, "notes": notes}
