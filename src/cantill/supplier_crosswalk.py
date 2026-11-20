"""Explicit company-specific supervised supplier aliases; never auto-load labels."""

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path

from cantill.config import ConfigError
from cantill.entities import opaque_key
from cantill.matching import supplier_key


PROTOCOL = "cantill-supplier-crosswalk-v1"


@dataclass
class SupplierCrosswalk:
    company_id: str
    names: dict[str, str]
    ambiguous_names: tuple[str, ...] = ()

    @classmethod
    def fit(cls, company_id, records, labels):
        """Only supplied training labels contribute; conflicting names abstain."""
        joined = records[["record_id", "supplier_name"]].merge(
            labels[["record_id", "supplier_key"]], on="record_id", validate="one_to_one")
        groups = defaultdict(set)
        for name, golden in joined[["supplier_name", "supplier_key"]].itertuples(index=False, name=None):
            name, golden = supplier_key(name), golden.strip()
            if len(name) >= 4 and golden:
                groups[name].add(opaque_key("supervised_supplier", company_id, golden))
        return cls(company_id, {name: next(iter(keys)) for name, keys in sorted(groups.items()) if len(keys) == 1},
                   tuple(sorted(name for name, keys in groups.items() if len(keys) > 1)))

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Refuse to replace an existing trained artifact accidentally.
        with path.open("x", encoding="utf-8") as stream:
            json.dump({"protocol": PROTOCOL, "company_id": self.company_id,
                       "names": self.names, "ambiguous_names": self.ambiguous_names}, stream, indent=2)
            stream.write("\n")

    @classmethod
    def load(cls, path, *, company_id):
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ConfigError("Cannot read supplier crosswalk") from exc
        if (not isinstance(value, dict) or value.get("protocol") != PROTOCOL
                or value.get("company_id") != company_id):
            raise ConfigError("Supplier crosswalk protocol/company mismatch")
        names, ambiguous = value.get("names"), value.get("ambiguous_names")
        if (not isinstance(names, dict) or not isinstance(ambiguous, list)
                or any(not isinstance(k, str) or len(k) < 4 or supplier_key(k) != k
                       or not isinstance(v, str) or not v.startswith("supervised_supplier_") for k, v in names.items())
                or any(not isinstance(k, str) or len(k) < 4 or supplier_key(k) != k for k in ambiguous)
                or set(names).intersection(ambiguous)):
            raise ConfigError("Invalid supplier crosswalk entries")
        return cls(company_id, names, tuple(ambiguous))
