from pathlib import Path
import json

from .composition import compare as run_compare, options as compare_options
from .domain import explore, validate
from .storage import Store, fingerprint


class Workbench:
    def __init__(self, root, state):
        self.root = Path(root)
        self.product = json.loads((self.root / "product.json").read_text(encoding="utf-8"))
        self.store = Store(Path(state) / "research.sqlite3")
        initial = json.loads((self.root / "fixtures" / "data.json").read_text(encoding="utf-8"))
        validate(initial)
        self.default_revision = self.store.put_dataset("演示材料", initial)

    def context(self):
        return {"product": self.product, "default_revision": self.default_revision,
                "datasets": self.store.datasets(), "notebooks": self.store.notebooks(),
                "comparisons": self.store.comparisons()}

    def upload(self, body):
        data = body["data"]
        try:
            validate(data)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("字段结构不完整或类型不符") from error
        return {"revision": self.store.put_dataset(body.get("label", ""), data)}

    def inspect(self, body):
        revision = body.get("revision", self.default_revision)
        selection = body.get("selection", self.product["selection"])
        if not isinstance(selection, dict):
            raise ValueError("选择条件必须是对象")
        data = self.store.dataset(revision)
        result = explore(data, selection)
        return {"revision": revision, "selection": selection, "data_sha256": fingerprint(data), "view": result}

    def save(self, body):
        result = self.inspect(body)
        return self.store.save(body.get("title", ""), result["revision"], result["selection"], result)

    def compare_options(self, revision=None):
        data = self.store.dataset(revision or self.default_revision)
        return compare_options(data)

    def compare(self, body):
        revision = body.get("revision", self.default_revision)
        scheme = body.get("scheme")
        if not isinstance(scheme, dict):
            raise ValueError("比较方案必须是对象")
        data = self.store.dataset(revision)
        view = run_compare(data, scheme)
        return {"revision": revision, "scheme": view["scheme"],
                "data_sha256": fingerprint(data), "view": view}

    def save_comparison(self, body):
        result = self.compare(body)
        return self.store.save_comparison(body.get("title", ""), result["revision"], result["scheme"], result)
