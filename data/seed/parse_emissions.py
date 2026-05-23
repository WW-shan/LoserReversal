"""Parse DefiLlama emissions-adapters manual schedules into unlock seed CSV."""

from __future__ import annotations

import ast
import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOLS_DIR = Path("/tmp/emissions-adapters/protocols")
COINS_LIST_PATH = REPO_ROOT / "data" / "cache" / "seed_build" / "coins_list.json"
OUT_CSV = REPO_ROOT / "data" / "seed" / "unlocks_curated.csv"

HL_INFO = "https://api.hyperliquid.xyz/info"
WINDOW_START = date(2023, 1, 1)
WINDOW_END = max(date(2026, 5, 22), datetime.now(timezone.utc).date())
MIN_UNLOCK_PCT = 0.005
MAX_UNLOCK_PCT = 0.30

PERIOD_SECONDS = {
    "day": 86_400,
    "days": 86_400,
    "week": 604_800,
    "weeks": 604_800,
    "month": 2_628_000,
    "months": 2_628_000,
    "year": 31_536_000,
    "years": 31_536_000,
    "hour": 3_600,
    "minute": 60,
}

CATEGORY_CANON = {
    "airdrop": "airdrop",
    "insiders": "insiders",
    "privatesale": "privateSale",
    "noncirculating": "noncirculating",
    "community": "community",
    "publicsale": "publicSale",
}


@dataclass(frozen=True)
class Coin:
    id: str
    symbol: str
    name: str


@dataclass(frozen=True)
class ManualCall:
    kind: str
    args: list[str]


def strip_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    quote: str | None = None
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            out.append("\n")
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def find_matching(text: str, open_pos: int, open_ch: str, close_ch: str) -> int | None:
    depth = 0
    quote: str | None = None
    i = open_pos
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def split_top_level(value: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    pairs = {"(": ")", "[": "]", "{": "}"}
    closers = set(pairs.values())
    for i, ch in enumerate(value):
        if quote:
            if ch == "\\":
                continue
            if ch == quote:
                quote = None
            continue
        if ch in "\"'`":
            quote = ch
            continue
        if ch in pairs:
            depth += 1
            continue
        if ch in closers:
            depth -= 1
            continue
        if ch == sep and depth == 0:
            part = value[start:i].strip()
            if part:
                parts.append(part)
            start = i + 1
    tail = value[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def split_property(segment: str) -> tuple[str, str | None] | None:
    segment = segment.strip().rstrip(",")
    if not segment:
        return None
    match = re.match(r"""(?s)\s*(?:"([^"]+)"|'([^']+)'|`([^`]+)`|([A-Za-z_$][\w$-]*))\s*:""", segment)
    if match:
        key = next(group for group in match.groups() if group is not None)
        return key, segment[match.end() :].strip()
    if re.match(r"^[A-Za-z_$][\w$]*$", segment):
        return segment, None
    return None


def object_properties(block: str) -> list[tuple[str, str | None]]:
    inner = block.strip()
    if inner.startswith("{") and inner.endswith("}"):
        inner = inner[1:-1]
    props: list[tuple[str, str | None]] = []
    for segment in split_top_level(inner):
        prop = split_property(segment)
        if prop:
            props.append(prop)
    return props


def find_protocol_block(text: str) -> str | None:
    match = re.search(r"\bconst\s+[A-Za-z_$][\w$]*\s*:\s*Protocol\b[^=]*=\s*{", text)
    if not match:
        return None
    start = text.find("{", match.start())
    end = find_matching(text, start, "{", "}")
    if end is None:
        return None
    return text[start : end + 1]


def iso_to_timestamp(value: str, date_format: str | None = None) -> int:
    raw = value.strip().strip("\"'`")
    if re.fullmatch(r"\d{10}", raw):
        return int(raw)
    if date_format and "/" in raw:
        pieces = [int(part) for part in raw.split("/")]
        fmt = date_format.upper()
        if fmt == "DD/MM/YYYY":
            day, month, year = pieces
        elif fmt == "MM/DD/YYYY":
            month, day, year = pieces
        else:
            year, month, day = pieces
        return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())
    normalized = raw.replace("/", "-")
    if "T" in normalized:
        dt = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    parts = [int(part) for part in normalized.split("-")]
    if len(parts) == 3:
        year, month, day = parts
        dt = datetime(year, month, 1, tzinfo=timezone.utc) + timedelta(days=day - 1)
        return int(dt.timestamp())
    raise ValueError(f"unsupported date: {value}")


def timestamp_to_date(ts: float) -> date:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()


def normalize_expr(expr: str) -> str:
    expr = expr.strip().rstrip(",")
    expr = re.sub(r"(?<=\d)_(?=\d)", "", expr)
    expr = re.sub(r"\bas\s+const\b", "", expr)
    expr = re.sub(r"\bas\s+[A-Za-z_$][\w$<>]*", "", expr)

    def replace_new_date(match: re.Match[str]) -> str:
        return str(iso_to_timestamp(match.group(1)))

    expr = re.sub(
        r"""new\s+Date\s*\(\s*["']([^"']+)["']\s*\)\.getTime\s*\(\s*\)\s*/\s*1000""",
        replace_new_date,
        expr,
    )
    if expr.startswith("`") and expr.endswith("`") and "${" not in expr:
        return repr(expr[1:-1])
    return expr


class Evaluator:
    def __init__(self, env: dict[str, Any]) -> None:
        self.env = env

    def eval(self, expr: str) -> Any:
        normalized = normalize_expr(expr)
        node = ast.parse(normalized, mode="eval")
        return self.visit(node.body)

    def visit(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.env:
                return self.env[node.id]
            raise ValueError(f"unknown name: {node.id}")
        if isinstance(node, ast.Attribute):
            dotted = self.dotted_name(node)
            if dotted.startswith("periodToSeconds."):
                key = dotted.split(".", 1)[1]
                if key in PERIOD_SECONDS:
                    return PERIOD_SECONDS[key]
            if dotted in self.env:
                return self.env[dotted]
            raise ValueError(f"unknown attribute: {dotted}")
        if isinstance(node, ast.UnaryOp):
            value = self.visit(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
        if isinstance(node, ast.BinOp):
            left = self.visit(node.left)
            right = self.visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left**right
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.Subscript):
            target = self.visit(node.value)
            index = self.visit(node.slice)
            return target[index]
        raise ValueError(f"unsupported expression: {ast.dump(node)}")

    def dotted_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self.dotted_name(node.value)}.{node.attr}"
        raise ValueError("not a dotted name")

    def call(self, node: ast.Call) -> Any:
        name = self.dotted_name(node.func)
        args = [self.visit(arg) for arg in node.args]
        if name.startswith("periodToSeconds."):
            unit = name.split(".", 1)[1]
            if unit in PERIOD_SECONDS and len(args) == 1:
                return args[0] * PERIOD_SECONDS[unit]
        if name in {"Math.floor", "floor"} and len(args) == 1:
            return math.floor(args[0])
        if name in {"Math.ceil", "ceil"} and len(args) == 1:
            return math.ceil(args[0])
        if name in {"Math.round", "round"} and len(args) == 1:
            return round(args[0])
        if name in {"readableToSeconds", "stringToTimestamp"} and args:
            return iso_to_timestamp(str(args[0]), str(args[1]) if len(args) > 1 else None)
        if name in {"months", "years", "weeks", "days"}:
            if len(args) == 1:
                return args[0] * PERIOD_SECONDS[name]
            if len(args) == 2:
                return round((args[0] + args[1] * PERIOD_SECONDS[name]) / 86_400) * 86_400
        raise ValueError(f"unsupported call: {name}")


def eval_value(expr: str, env: dict[str, Any]) -> Any:
    return Evaluator(env).eval(expr)


def const_declarations(text: str) -> list[tuple[str, str]]:
    decls: list[tuple[str, str]] = []
    for match in re.finditer(r"(?m)^\s*const\s+([A-Za-z_$][\w$]*)\b[^=]*=\s*", text):
        name = match.group(1)
        pos = match.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            continue
        if text[pos] == "{":
            end = find_matching(text, pos, "{", "}")
            if end is not None:
                decls.append((name, text[pos : end + 1]))
            continue
        line_end = text.find("\n", pos)
        semi = text.find(";", pos)
        if semi != -1 and (line_end == -1 or semi < line_end):
            end = semi
        else:
            end = line_end if line_end != -1 else len(text)
        expr = text[pos:end].strip()
        if expr and "=>" not in expr and not expr.startswith(("[", "{")):
            decls.append((name, expr))
    return decls


def build_env(text: str) -> dict[str, Any]:
    env: dict[str, Any] = {}
    decls = const_declarations(text)
    for _ in range(4):
        changed = False
        for name, expr in decls:
            try:
                if expr.strip().startswith("{"):
                    for key, value_expr in object_properties(expr):
                        if value_expr is None:
                            continue
                        value = eval_value(value_expr, env)
                        flat_key = f"{name}.{key}"
                        if env.get(flat_key) != value:
                            env[flat_key] = value
                            changed = True
                    continue
                value = eval_value(expr, env)
                if env.get(name) != value:
                    env[name] = value
                    changed = True
            except Exception:
                continue
        if not changed:
            break
    return env


def parse_meta(protocol_block: str, env: dict[str, Any]) -> tuple[float | None, str | None]:
    props = dict(object_properties(protocol_block))
    meta_expr = props.get("meta")
    if not meta_expr or not meta_expr.strip().startswith("{"):
        return None, None
    total: float | None = None
    token: str | None = None
    for key, value_expr in object_properties(meta_expr):
        if key == "total":
            if value_expr is None:
                value = env.get("total")
            else:
                value = eval_value(value_expr, env)
            total = float(value)
        elif key == "token" and value_expr is not None:
            try:
                token_value = eval_value(value_expr, env)
            except Exception:
                token_value = None
            if isinstance(token_value, str) and token_value.startswith("coingecko:"):
                token = token_value.split(":", 1)[1]
    return total, token


def parse_categories(protocol_block: str) -> dict[str, str]:
    props = dict(object_properties(protocol_block))
    categories_expr = props.get("categories")
    out: dict[str, str] = {}
    if not categories_expr or not categories_expr.strip().startswith("{"):
        return out
    for key, value_expr in object_properties(categories_expr):
        canonical = CATEGORY_CANON.get(key.lower())
        if not canonical or not value_expr:
            continue
        for section in re.findall(r"""["']([^"']+)["']""", value_expr):
            out[section.lower().strip()] = canonical
    return out


def extract_manual_calls(value: str) -> list[ManualCall]:
    calls: list[ManualCall] = []
    for match in re.finditer(r"\bmanual(Cliff|Step|Linear)\s*\(", value):
        open_pos = value.find("(", match.start())
        close_pos = find_matching(value, open_pos, "(", ")")
        if close_pos is None:
            continue
        args = split_top_level(value[open_pos + 1 : close_pos])
        calls.append(ManualCall(match.group(1).lower(), args))
    return calls


def to_timestamp(value: Any, date_format: str | None = None) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        return iso_to_timestamp(value, date_format)
    raise ValueError(f"unsupported timestamp value: {value!r}")


def load_coins() -> tuple[dict[str, Coin], dict[str, list[Coin]]]:
    coins = [Coin(row["id"], row["symbol"].upper(), row["name"]) for row in json.loads(COINS_LIST_PATH.read_text())]
    by_id = {coin.id.lower(): coin for coin in coins}
    by_symbol: dict[str, list[Coin]] = defaultdict(list)
    for coin in coins:
        by_symbol[coin.symbol.upper()].append(coin)
    return by_id, by_symbol


def normalize_slug(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = value.replace("_", "-")
    value = re.sub(r"[^A-Za-z0-9]+", "-", value)
    return value.strip("-").lower()


def resolve_coin(path: Path, meta_coin_id: str | None, by_id: dict[str, Coin], by_symbol: dict[str, list[Coin]]) -> Coin | None:
    if meta_coin_id and meta_coin_id.lower() in by_id:
        return by_id[meta_coin_id.lower()]
    stem = path.stem
    candidates = [stem.lower(), normalize_slug(stem)]
    for candidate in candidates:
        if candidate in by_id:
            return by_id[candidate]
    symbol_key = re.sub(r"[^A-Za-z0-9]", "", stem).upper()
    symbol_matches = by_symbol.get(symbol_key, [])
    if len(symbol_matches) == 1:
        return symbol_matches[0]
    if meta_coin_id:
        normalized_meta = meta_coin_id.lower()
        for coin in symbol_matches:
            if coin.id.lower() == normalized_meta:
                return coin
    return None


def hyperliquid_symbols() -> set[str]:
    response = requests.post(
        HL_INFO,
        json={"type": "meta"},
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    return {item["name"].upper() for item in response.json().get("universe", [])}


def add_event(
    rows: list[dict[str, Any]],
    token: str,
    coingecko_id: str,
    event_date: date,
    amount: float,
    total: float,
    category: str,
    has_hl_perp: bool,
    vesting_type: str,
) -> None:
    if not (WINDOW_START <= event_date <= WINDOW_END) or amount <= 0 or total <= 0:
        return
    rows.append(
        {
            "token": token,
            "coingecko_id": coingecko_id,
            "unlock_date": event_date.isoformat(),
            "unlock_pct": amount / total,
            "category": category,
            "has_hl_perp": has_hl_perp,
            "vesting_type": vesting_type,
        }
    )


def parse_file(path: Path, by_id: dict[str, Coin], by_symbol: dict[str, list[Coin]], hl_symbols: set[str]) -> list[dict[str, Any]]:
    text = strip_comments(path.read_text())
    protocol_block = find_protocol_block(text)
    if not protocol_block:
        return []
    env = build_env(text)
    total, meta_coin_id = parse_meta(protocol_block, env)
    if total is None or total <= 0:
        return []
    coin = resolve_coin(path, meta_coin_id, by_id, by_symbol)
    if not coin:
        return []

    section_categories = parse_categories(protocol_block)
    token = coin.symbol.upper()
    has_hl_perp = token in hl_symbols
    rows: list[dict[str, Any]] = []

    for section, value_expr in object_properties(protocol_block):
        if section in {"meta", "categories"} or not value_expr:
            continue
        category = section_categories.get(section.lower().strip(), "other")
        for call in extract_manual_calls(value_expr):
            try:
                date_format = None
                if len(call.args) >= 3 and call.kind == "cliff":
                    try:
                        fmt_value = eval_value(call.args[2], env)
                        date_format = str(fmt_value) if isinstance(fmt_value, str) else None
                    except Exception:
                        date_format = None
                if len(call.args) >= 4 and call.kind in {"linear", "step"}:
                    try:
                        fmt_index = 4 if call.kind == "step" else 3
                        if len(call.args) > fmt_index:
                            fmt_value = eval_value(call.args[fmt_index], env)
                            date_format = str(fmt_value) if isinstance(fmt_value, str) else None
                    except Exception:
                        date_format = None

                if call.kind == "cliff" and len(call.args) >= 2:
                    start = to_timestamp(eval_value(call.args[0], env), date_format)
                    amount = float(eval_value(call.args[1], env))
                    add_event(
                        rows,
                        token,
                        coin.id,
                        timestamp_to_date(start),
                        amount,
                        total,
                        category,
                        has_hl_perp,
                        call.kind,
                    )
                elif call.kind == "step" and len(call.args) >= 4:
                    start = to_timestamp(eval_value(call.args[0], env), date_format)
                    step = float(eval_value(call.args[1], env))
                    steps = int(float(eval_value(call.args[2], env)))
                    amount = float(eval_value(call.args[3], env))
                    if step <= 0 or steps <= 0 or steps > 10_000:
                        continue
                    for i in range(steps):
                        add_event(
                            rows,
                            token,
                            coin.id,
                            timestamp_to_date(start + step * i),
                            amount,
                            total,
                            category,
                            has_hl_perp,
                            call.kind,
                        )
                elif call.kind == "linear" and len(call.args) >= 3:
                    start = to_timestamp(eval_value(call.args[0], env), date_format)
                    end = to_timestamp(eval_value(call.args[1], env), date_format)
                    amount = float(eval_value(call.args[2], env))
                    if end <= start or amount <= 0:
                        continue
                    days = max(1, math.ceil((end - start) / 86_400))
                    daily_amount = amount / days
                    for i in range(days):
                        add_event(
                            rows,
                            token,
                            coin.id,
                            timestamp_to_date(start + i * 86_400),
                            daily_amount,
                            total,
                            category,
                            has_hl_perp,
                            call.kind,
                        )
            except Exception:
                continue
    return rows


def aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, bool, str], float] = defaultdict(float)
    for row in rows:
        key = (
            row["token"],
            row["coingecko_id"],
            row["unlock_date"],
            row["category"],
            bool(row["has_hl_perp"]),
            row["vesting_type"],
        )
        grouped[key] += float(row["unlock_pct"])

    out: list[dict[str, Any]] = []
    for (
        token,
        coingecko_id,
        unlock_date,
        category,
        has_hl_perp,
        vesting_type,
    ), unlock_pct in grouped.items():
        if MIN_UNLOCK_PCT <= unlock_pct <= MAX_UNLOCK_PCT:
            out.append(
                {
                    "token": token,
                    "coingecko_id": coingecko_id,
                    "unlock_date": unlock_date,
                    "unlock_pct": unlock_pct,
                    "category": category,
                    "has_hl_perp": has_hl_perp,
                    "vesting_type": vesting_type,
                }
            )
    return sorted(
        out,
        key=lambda row: (row["unlock_date"], row["token"], row["category"], row["vesting_type"]),
    )


def main() -> int:
    if not PROTOCOLS_DIR.exists():
        raise SystemExit(f"missing protocols dir: {PROTOCOLS_DIR}")

    by_id, by_symbol = load_coins()
    hl_symbols = hyperliquid_symbols()
    raw_rows: list[dict[str, Any]] = []
    parsed_files = 0
    for path in sorted(PROTOCOLS_DIR.glob("*.ts")):
        rows = parse_file(path, by_id, by_symbol, hl_symbols)
        if rows:
            parsed_files += 1
            raw_rows.extend(rows)

    rows = aggregate_rows(raw_rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "token",
                "coingecko_id",
                "unlock_date",
                "unlock_pct",
                "category",
                "has_hl_perp",
                "vesting_type",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "token": row["token"],
                    "coingecko_id": row["coingecko_id"],
                    "unlock_date": row["unlock_date"],
                    "unlock_pct": f"{row['unlock_pct']:.6f}",
                    "category": row["category"],
                    "has_hl_perp": str(row["has_hl_perp"]).lower(),
                    "vesting_type": row["vesting_type"],
                }
            )

    categories = defaultdict(int)
    for row in rows:
        categories[row["category"]] += 1
    print(f"scanned_files: {len(list(PROTOCOLS_DIR.glob('*.ts')))}")
    print(f"parsed_files: {parsed_files}")
    print(f"rows: {len(rows)}")
    print(f"categories: {dict(sorted(categories.items()))}")
    print(f"wrote: {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
