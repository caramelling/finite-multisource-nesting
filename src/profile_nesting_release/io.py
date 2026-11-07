from pathlib import Path
import csv
import json


ROOT = Path(__file__).resolve().parents[2]


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_csv(path, rows, columns):
    with Path(path).open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def demands_from_csv(path):
    from .frozen.algorithms import Demand

    return [Demand(**{**row, 'net_length_mm': float(row['net_length_mm'])}) for row in read_csv(path)]


def stocks_from_csv(path):
    from .frozen.algorithms import StockUnit

    return [StockUnit(**{**row, 'stock_length_mm': float(row['stock_length_mm']),
                        'unit_weight_kg_per_m': float(row['unit_weight_kg_per_m']) if row['unit_weight_kg_per_m'] else None})
            for row in read_csv(path)]


def rules_from_csv(path):
    from .frozen.algorithms import normalize_material, normalize_profile_type

    return {(normalize_material(row['demand_material']), normalize_material(row['stock_material']),
             normalize_profile_type(row['profile_type'])): float(row['penalty']) for row in read_csv(path)}
