"""Lossless source ingestion and separate runtime reference tables."""

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cantill.config import CompanyConfig, ConfigError, FIELDS, TableConfig


@dataclass
class IngestedCompany:
    config: CompanyConfig
    records: pd.DataFrame
    taxonomy: tuple[tuple[str, ...], ...]
    fx: pd.DataFrame | None
    labels: pd.DataFrame | None

    def summary(self) -> dict:
        return {
            "company_id": self.config.company_id,
            "reporting_currency": self.config.reporting_currency,
            "record_count": len(self.records),
            "sources": {s.name: int((self.records["source"] == s.name).sum()) for s in self.config.sources},
            "taxonomy_paths": len(self.taxonomy),
            "taxonomy_depth": max(map(len, self.taxonomy)),
            "fx_rows": len(self.fx) if self.fx is not None else 0,
            "labels_loaded": self.labels is not None,
            "label_rows": len(self.labels) if self.labels is not None else 0,
        }


def read_table(base_dir: Path, spec: TableConfig, name: str) -> list[dict[str, str]]:
    path = base_dir / spec.path
    try:
        with path.open(encoding=spec.csv.encoding, newline="") as stream:
            reader = csv.DictReader(stream, delimiter=spec.csv.delimiter, strict=True)
            columns = reader.fieldnames
            if not columns or len(set(columns)) != len(columns) or any(not c.strip() for c in columns):
                raise ConfigError(f"{name}: missing, blank or duplicate CSV headers")
            if set(spec.fields.values()) - set(columns):
                raise ConfigError(f"{name}: missing mapped CSV columns: {sorted(set(spec.fields.values()) - set(columns))}")
            rows = []
            for index, row in enumerate(reader, start=1):
                if None in row or any(v is None for v in row.values()):
                    raise ConfigError(f"{name}: inconsistent column count at data row {index}")
                rows.append(row)
            return rows
    except (OSError, UnicodeError, LookupError, csv.Error) as exc:
        raise ConfigError(f"{name}: cannot read configured CSV") from exc


def mapped_rows(rows, spec):
    return [{field: row[column] for field, column in spec.fields.items()} for row in rows]


def ingest_company(config: CompanyConfig, *, load_labels: bool = False) -> IngestedCompany:
    canonical, seen, paths = [], set(), set()
    for source in config.sources:
        path = (config.base_dir / source.table.path).resolve()
        if path in paths:
            raise ConfigError("Multiple sources reference the same input file")
        paths.add(path)
        for index, raw in enumerate(read_table(config.base_dir, source.table, source.name), start=1):
            row = dict.fromkeys(FIELDS, "")
            row.update(source.constants)
            row.update({field: raw[column] for field, column in source.table.fields.items()})
            if not row["source_record_id"].strip():
                raise ConfigError(f"{source.name}: blank record ID at data row {index}")
            record_id = source.table.record_id_prefix + row["source_record_id"]
            if record_id in seen:
                raise ConfigError(f"{source.name}: duplicate output record ID at data row {index}")
            seen.add(record_id)
            canonical.append({**row, "record_id": record_id, "company_id": config.company_id,
                              "source": source.name, "source_row": index, "raw": raw})
    records = pd.DataFrame(canonical, columns=[*FIELDS, "record_id", "company_id", "source", "source_row", "raw"])

    tree_rows = mapped_rows(read_table(config.base_dir, config.taxonomy, "taxonomy"), config.taxonomy)
    taxonomy = []
    for row in tree_rows:
        values = [row[f"l{i}"] for i in range(1, len(config.taxonomy.fields) + 1)]
        while values and values[-1] == "":
            values.pop()
        if not values or any(not v.strip() for v in values):
            raise ConfigError("taxonomy: blank level or gap in category path")
        taxonomy.append(tuple(values))
    if not taxonomy or len(set(taxonomy)) != len(taxonomy):
        raise ConfigError("taxonomy: empty tree or duplicate category path")

    fx = None
    if config.fx is not None:
        rows = mapped_rows(read_table(config.base_dir, config.fx, "fx"), config.fx)
        fx = pd.DataFrame(rows, columns=list(config.fx.fields))
        if any(not r[c].strip() for r in rows for c in ("currency", "month")) or fx.duplicated(["currency", "month"]).any():
            raise ConfigError("fx: blank or duplicate currency/month key")

    labels = None
    if load_labels:
        if config.labels is None:
            raise ConfigError("Labels requested but no label file is configured")
        rows = mapped_rows(read_table(config.base_dir, config.labels, "labels"), config.labels)
        label_ids = set()
        for row in rows:
            original_id = row["record_id"]
            row["record_id"] = config.labels.record_id_prefix + original_id
            key = row["record_id"]
            if not original_id.strip() or key in label_ids or key not in seen:
                raise ConfigError("labels: blank, duplicate or unmatched record ID")
            label_ids.add(key)
        labels = pd.DataFrame(rows, columns=list(config.labels.fields))

    return IngestedCompany(config, records, tuple(taxonomy), fx, labels)
