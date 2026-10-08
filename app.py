#!/usr/bin/env python3
"""OpenSociometry — локальная программа для социометрии.

Запуск: python app.py  (нужен только Python 3.8+, сторонние пакеты не требуются)
Откроется браузер на http://127.0.0.1:8765
Все данные хранятся в файле data/sociometry.db рядом с этим скриптом.
"""
import csv
import base64
import binascii
import io
import json
import math
import os
import re
import sqlite3
import sys
import threading
import webbrowser
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

def app_paths():
    source_dir = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable)), getattr(sys, "_MEIPASS", source_dir)
    return source_dir, source_dir


BASE_DIR, RESOURCE_DIR = app_paths()
STATIC_DIR = os.path.join(RESOURCE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("SOCIOMETRY_DB", os.path.join(DATA_DIR, "sociometry.db"))
HOST = "127.0.0.1"
PORT = int(os.environ.get("SOCIOMETRY_PORT", "8765"))

KINDS = ("pos", "neg", "ppos", "pneg")  # выбор +, выбор −, ожидание +, ожидание −

SCHEMA = """
CREATE TABLE IF NOT EXISTS studies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    max_pos INTEGER NOT NULL DEFAULT 0,
    max_neg INTEGER NOT NULL DEFAULT 0,
    perceptual INTEGER NOT NULL DEFAULT 0,
    optimistic INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_id INTEGER NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    pos INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS criteria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_id INTEGER NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    pos INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS choices (
    criterion_id INTEGER NOT NULL REFERENCES criteria(id) ON DELETE CASCADE,
    from_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    to_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    PRIMARY KEY (criterion_id, from_id, to_id, kind)
);
CREATE TABLE IF NOT EXISTS questionnaires (
    criterion_id INTEGER NOT NULL REFERENCES criteria(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    PRIMARY KEY (criterion_id, member_id)
);
CREATE TABLE IF NOT EXISTS member_photos (
    member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
    mime TEXT NOT NULL,
    data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_layouts (
    criterion_id INTEGER NOT NULL REFERENCES criteria(id) ON DELETE CASCADE,
    graph_key TEXT NOT NULL,
    positions TEXT NOT NULL,
    PRIMARY KEY (criterion_id, graph_key)
);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(studies)")}
        if "optimistic" not in columns:
            conn.execute("ALTER TABLE studies ADD COLUMN optimistic INTEGER NOT NULL DEFAULT 0")


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- data access

def touch(conn, study_id):
    conn.execute("UPDATE studies SET updated_at=? WHERE id=?", (now(), study_id))


def get_study(conn, study_id):
    s = conn.execute("SELECT * FROM studies WHERE id=?", (study_id,)).fetchone()
    if not s:
        raise ApiError("Социометрия не найдена", 404)
    members = [dict(r) for r in conn.execute(
        "SELECT m.*, EXISTS(SELECT 1 FROM member_photos p WHERE p.member_id=m.id) AS has_photo"
        " FROM members m WHERE m.study_id=? ORDER BY m.pos, m.id", (study_id,))]
    criteria = [dict(r) for r in conn.execute(
        "SELECT * FROM criteria WHERE study_id=? ORDER BY pos, id", (study_id,))]
    choices = [dict(r) for r in conn.execute(
        "SELECT c.* FROM choices c JOIN criteria k ON k.id=c.criterion_id WHERE k.study_id=?",
        (study_id,))]
    filled = [dict(r) for r in conn.execute(
        "SELECT q.* FROM questionnaires q JOIN criteria k ON k.id=q.criterion_id WHERE k.study_id=?",
        (study_id,))]
    out = dict(s)
    out.update(members=members, criteria=criteria, choices=choices, filled=filled)
    return out


def study_of_criterion(conn, criterion_id):
    r = conn.execute("SELECT study_id FROM criteria WHERE id=?", (criterion_id,)).fetchone()
    if not r:
        raise ApiError("Критерий не найден", 404)
    return r["study_id"]


def add_members(conn, study_id, names):
    start = conn.execute("SELECT COALESCE(MAX(pos),0) FROM members WHERE study_id=?",
                         (study_id,)).fetchone()[0]
    added = 0
    for i, name in enumerate(names, 1):
        name = name.strip()
        if name:
            conn.execute("INSERT INTO members(study_id,name,pos) VALUES(?,?,?)",
                         (study_id, name[:200], start + i))
            added += 1
    touch(conn, study_id)
    return added


def add_criterion(conn, study_id, name):
    start = conn.execute("SELECT COALESCE(MAX(pos),0) FROM criteria WHERE study_id=?",
                         (study_id,)).fetchone()[0]
    cur = conn.execute("INSERT INTO criteria(study_id,name,pos) VALUES(?,?,?)",
                       (study_id, name.strip()[:300] or "Критерий", start + 1))
    touch(conn, study_id)
    return cur.lastrowid


def create_study(conn, data):
    name = (data.get("name") or "").strip() or "Новая социометрия"
    cur = conn.execute(
        "INSERT INTO studies(name,description,max_pos,max_neg,perceptual,optimistic,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (name, data.get("description", ""), int(data.get("max_pos") or 0),
         int(data.get("max_neg") or 0), 1 if data.get("perceptual") else 0,
         1 if data.get("optimistic") else 0, now(), now()))
    sid = cur.lastrowid
    crits = data.get("criteria") or ["С кем бы вы хотели работать вместе?"]
    for c in crits:
        if c.strip():
            add_criterion(conn, sid, c)
    if data.get("members"):
        add_members(conn, sid, data["members"])
    return sid


def set_choice(conn, data):
    cid = int(data["criterion_id"])
    sid = study_of_criterion(conn, cid)
    a, b = int(data["from_id"]), int(data["to_id"])
    if a == b:
        raise ApiError("Нельзя выбирать самого себя")
    ok = conn.execute("SELECT COUNT(*) FROM members WHERE study_id=? AND id IN (?,?)",
                      (sid, a, b)).fetchone()[0]
    if ok != 2:
        raise ApiError("Участник не найден")
    perceptual = bool(data.get("perceptual"))
    group = ("ppos", "pneg") if perceptual else ("pos", "neg")
    conn.execute("DELETE FROM choices WHERE criterion_id=? AND from_id=? AND to_id=? AND kind IN (?,?)",
                 (cid, a, b) + group)
    kind = data.get("kind")
    if kind:
        if kind not in group:
            raise ApiError("Неверный тип выбора")
        conn.execute("INSERT INTO choices VALUES(?,?,?,?)", (cid, a, b, kind))
    touch(conn, sid)


def set_questionnaire_filled(conn, criterion_id, member_id, filled):
    sid = study_of_criterion(conn, criterion_id)
    if not conn.execute("SELECT 1 FROM members WHERE id=? AND study_id=?", (member_id, sid)).fetchone():
        raise ApiError("Участник не принадлежит этой социометрии")
    if filled:
        conn.execute("INSERT OR IGNORE INTO questionnaires VALUES(?,?)", (criterion_id, member_id))
    else:
        conn.execute("DELETE FROM questionnaires WHERE criterion_id=? AND member_id=?",
                     (criterion_id, member_id))
    touch(conn, sid)


def set_member_photo(conn, member_id, raw):
    member = conn.execute("SELECT study_id FROM members WHERE id=?", (member_id,)).fetchone()
    if not member:
        raise ApiError("Участник не найден", 404)
    if len(raw) > 3 * 1024 * 1024:
        raise ApiError("Изображение больше 3 МБ")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ApiError("Поддерживаются изображения PNG, JPEG и WebP")
    conn.execute("INSERT OR REPLACE INTO member_photos VALUES(?,?,?)", (member_id, mime, raw))
    touch(conn, member["study_id"])


def get_member_photo(conn, member_id):
    row = conn.execute("SELECT mime,data FROM member_photos WHERE member_id=?", (member_id,)).fetchone()
    if not row:
        raise ApiError("Фото не найдено", 404)
    return row["mime"], row["data"]


def save_graph_layout(conn, criterion_id, graph_key, positions):
    sid = study_of_criterion(conn, criterion_id)
    if graph_key not in ("force", "target", "mutual") or not isinstance(positions, dict):
        raise ApiError("Неверная раскладка графа")
    member_ids = {str(r[0]) for r in conn.execute("SELECT id FROM members WHERE study_id=?", (sid,))}
    if not set(positions).issubset(member_ids):
        raise ApiError("Раскладка содержит участников другой социометрии")
    for point in positions.values():
        if (not isinstance(point, list) or len(point) != 2 or
                any(not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 10000
                    for v in point)):
            raise ApiError("Неверные координаты графа")
    conn.execute("INSERT OR REPLACE INTO graph_layouts VALUES(?,?,?)",
                 (criterion_id, graph_key, json.dumps(positions)))
    touch(conn, sid)


def get_graph_layout(conn, criterion_id, graph_key):
    study_of_criterion(conn, criterion_id)
    row = conn.execute("SELECT positions FROM graph_layouts WHERE criterion_id=? AND graph_key=?",
                       (criterion_id, graph_key)).fetchone()
    return json.loads(row["positions"]) if row else {}


# ---------------------------------------------------------------- calculations

def r3(x):
    return None if x is None else round(x, 3)


def classify_status(pos_in, neg_in, mean_pos, mean_neg, optimistic=False):
    if pos_in == 0 and neg_in == 0:
        return "isolated"
    if mean_pos > 0 and pos_in >= 2 * mean_pos:
        return "star"
    if mean_pos > 0 and pos_in >= round(1.5 * mean_pos) and neg_in <= 3 * mean_neg:
        return "preferred"
    if neg_in and (pos_in == 0 or (not optimistic and pos_in < mean_pos / 3
                                  and neg_in >= 3 * mean_neg)):
        return "rejected"
    if neg_in and neg_in >= 1.5 * pos_in:
        return "neglected"
    return "accepted"


def compute(conn, criterion_id):
    sid = study_of_criterion(conn, criterion_id)
    study = get_study(conn, sid)
    crit = next(c for c in study["criteria"] if c["id"] == criterion_id)
    members = study["members"]
    ids = [m["id"] for m in members]
    n = len(ids)
    sel = {k: set() for k in KINDS}
    for c in study["choices"]:
        if c["criterion_id"] == criterion_id:
            sel[c["kind"]].add((c["from_id"], c["to_id"]))
    d = max(n - 1, 1)

    rows = []
    for m in members:
        i = m["id"]
        pos_out = sum(1 for j in ids if (i, j) in sel["pos"])
        neg_out = sum(1 for j in ids if (i, j) in sel["neg"])
        pos_in = sum(1 for j in ids if (j, i) in sel["pos"])
        neg_in = sum(1 for j in ids if (j, i) in sel["neg"])
        mutual_pos = sum(1 for j in ids if (i, j) in sel["pos"] and (j, i) in sel["pos"])
        mutual_neg = sum(1 for j in ids if (i, j) in sel["neg"] and (j, i) in sel["neg"])
        row = dict(
            id=i, name=m["name"], has_photo=m["has_photo"],
            pos_in=pos_in, neg_in=neg_in, pos_out=pos_out, neg_out=neg_out,
            mutual_pos=mutual_pos, mutual_neg=mutual_neg,
            status_pos=r3(pos_in / d), status_neg=r3(neg_in / d),
            status=r3((pos_in - neg_in) / d),
            exp_pos=r3(pos_out / d), exp_neg=r3(neg_out / d),
            satisfaction=r3(pos_in / pos_out) if pos_out else None,
        )
        # перцептивные выборы: кто, по мнению i, выбрал его
        exp_p = [j for j in ids if (i, j) in sel["ppos"]]
        exp_n = [j for j in ids if (i, j) in sel["pneg"]]
        hit_p = sum(1 for j in exp_p if (j, i) in sel["pos"])
        hit_n = sum(1 for j in exp_n if (j, i) in sel["neg"])
        row.update(
            ppos_out=len(exp_p), pneg_out=len(exp_n), ppos_hit=hit_p, pneg_hit=hit_n,
            accuracy_pos=r3(hit_p / len(exp_p)) if exp_p else None,
            accuracy_neg=r3(hit_n / len(exp_n)) if exp_n else None,
            awareness_pos=r3(hit_p / pos_in) if pos_in else None,
            awareness_neg=r3(hit_n / neg_in) if neg_in else None,
        )
        rows.append(row)

    # Категории по опубликованным порогам Социоматрица.Онлайн.
    received = [r["pos_in"] for r in rows]
    mean = sum(received) / n if n else 0
    mean_neg = sum(r["neg_in"] for r in rows) / n if n else 0
    sd = math.sqrt(sum((x - mean) ** 2 for x in received) / n) if n else 0
    for r in rows:
        r["category"] = classify_status(r["pos_in"], r["neg_in"], mean, mean_neg,
                                         bool(study.get("optimistic", 0)))
    ranked = sorted(rows, key=lambda r: (-r["status"], -r["pos_in"], r["name"]))
    for place, r in enumerate(ranked, 1):
        r["rank"] = place

    pairs = n * (n - 1) / 2 if n > 1 else 1
    total_pos = len(sel["pos"])
    total_neg = len(sel["neg"])
    positive_pairs = sorted([a, b] for a, b in sel["pos"] if a < b and (b, a) in sel["pos"])
    negative_pairs = sorted([a, b] for a, b in sel["neg"] if a < b and (b, a) in sel["neg"])
    paradoxical_pairs = sorted({(min(a, b), max(a, b)) for a, b in sel["pos"]
                                if (b, a) in sel["neg"]})
    mpos_pairs = len(positive_pairs)
    mneg_pairs = len(negative_pairs)
    mixed_pairs = len(paradoxical_pairs)
    counts = {k: sum(1 for r in rows if r["category"] == k)
              for k in ("star", "preferred", "accepted", "neglected", "isolated", "rejected")}
    wellbeing = (counts["star"] + counts["preferred"]) / n if n else 0
    isolation = (counts["isolated"] + counts["rejected"]) / n if n else 0
    total_pp = len(sel["ppos"])
    hits_pp = sum(r["ppos_hit"] for r in rows)
    total_pn = len(sel["pneg"])
    hits_pn = sum(r["pneg_hit"] for r in rows)
    group = dict(
        n=n, total_pos=total_pos, total_neg=total_neg,
        mutual_pos_pairs=mpos_pairs, mutual_neg_pairs=mneg_pairs, mixed_pairs=mixed_pairs,
        expansiveness_total=r3((total_pos + total_neg) / n) if n else 0,
        expansiveness_pos=r3(total_pos / n) if n else None,
        expansiveness_neg=r3(total_neg / n) if n else None,
        cohesion=r3(mpos_pairs / pairs),
        conflict=r3(mneg_pairs / pairs),
        reciprocity=r3(2 * mpos_pairs / total_pos) if total_pos else None,
        reference=r3(mpos_pairs / total_pos) if total_pos else 0,
        tension=r3(total_neg / (total_pos + total_neg)) if (total_pos + total_neg) else None,
        wellbeing=r3(wellbeing), isolation=r3(isolation),
        mean_received=r3(mean), sd_received=r3(sd),
        perceptual_accuracy_pos=r3(hits_pp / total_pp) if total_pp else None,
        perceptual_accuracy_neg=r3(hits_pn / total_pn) if total_pn else None,
        categories=counts,
    )
    edges = [dict(source=a, target=b, kind=k) for k in ("pos", "neg") for (a, b) in sel[k]]
    return dict(study=dict(id=sid, name=study["name"], perceptual=study["perceptual"]),
                criterion=crit, members=rows, group=group, edges=edges,
                pairs=dict(mutual_pos=positive_pairs, mutual_neg=negative_pairs,
                           paradoxical=[list(p) for p in paradoxical_pairs]),
                layouts={key: get_graph_layout(conn, criterion_id, key)
                         for key in ("force", "target", "mutual")})


CAT_RU = dict(star="Звезда", preferred="Предпочитаемый", accepted="Принятый",
              neglected="Пренебрегаемый", isolated="Изолированный", rejected="Отвергнутый")


def results_csv(res):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([res["study"]["name"]])
    w.writerow(["Критерий", res["criterion"]["name"]])
    w.writerow([])
    w.writerow(["Место", "Участник", "Получено +", "Получено −", "Отдано +", "Отдано −",
                "Взаимные +", "Взаимные −", "Статус +", "Статус −", "Сводный статус",
                "Экспансивность +", "Экспансивность −", "Куд", "Категория",
                "Точность ожиданий +", "Осознанность +"])
    for r in sorted(res["members"], key=lambda r: r["rank"]):
        w.writerow([r["rank"], r["name"], r["pos_in"], r["neg_in"], r["pos_out"], r["neg_out"],
                    r["mutual_pos"], r["mutual_neg"], r["status_pos"], r["status_neg"],
                    r["status"], r["exp_pos"], r["exp_neg"], r["satisfaction"],
                    CAT_RU[r["category"]], r["accuracy_pos"], r["awareness_pos"]])
    w.writerow([])
    g = res["group"]
    for label, key in [("Участников", "n"), ("Всего выборов +", "total_pos"),
                       ("Всего выборов −", "total_neg"), ("Взаимных пар +", "mutual_pos_pairs"),
                       ("Взаимных пар −", "mutual_neg_pairs"), ("Групповая экспансивность +", "expansiveness_pos"),
                       ("Сплочённость", "cohesion"), ("Конфликтность", "conflict"),
                       ("Взаимность", "reciprocity"), ("Напряжённость", "tension"),
                       ("КБВ", "wellbeing"), ("Индекс изолированности", "isolation")]:
        w.writerow([label, g[key]])
    w.writerow([])
    ids = [m["id"] for m in res["members"]]
    names = {m["id"]: m["name"] for m in res["members"]}
    e = {(x["source"], x["target"]): ("+" if x["kind"] == "pos" else "-") for x in res["edges"]}
    w.writerow(["Социоматрица"] + [names[i] for i in ids])
    for a in ids:
        w.writerow([names[a]] + [("X" if a == b else e.get((a, b), "")) for b in ids])
    return "﻿" + buf.getvalue()  # BOM, чтобы Excel правильно открыл кириллицу


def render_status_chart_png(counts):
    """Render the six status groups as a local, print-ready flat chart."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.patches import Patch
    except ImportError as exc:
        raise ApiError("Для графика Matplotlib установите зависимости из requirements.txt", 503) from exc

    labels = (
        ("star", "Звёзды", "#4f8a10"),
        ("preferred", "Предпочитаемые", "#b1ec52"),
        ("accepted", "Принятые", "#aeb5c0"),
        ("neglected", "Пренебрегаемые", "#eeb56b"),
        ("rejected", "Отвергаемые", "#e2622f"),
        ("isolated", "Изолированные", "#dadde3"),
    )
    total = sum(counts.get(key, 0) for key, _, _ in labels)
    fig = Figure(figsize=(10, 5.5), facecolor="white")
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0.04, 0.10, 0.50, 0.80))
    if total:
        active = [(key, name, color) for key, name, color in labels if counts.get(key, 0)]
        ax.pie([counts[key] for key, _, _ in active],
               colors=[color for _, _, color in active], startangle=90, counterclock=False,
               wedgeprops={"width": 0.36, "edgecolor": "white", "linewidth": 2},
               autopct=lambda share: "%d%%" % round(share) if share >= 5 else "",
               pctdistance=0.82, textprops={"color": "#15181e", "fontsize": 11, "weight": "bold"})
        ax.text(0, 0.06, str(total), ha="center", va="center", fontsize=31,
                fontweight="bold", color="#15181e")
        ax.text(0, -0.18, "участников", ha="center", va="center", fontsize=12,
                color="#5f6672")
    else:
        ax.text(0, 0, "Нет участников", ha="center", va="center", fontsize=18,
                color="#5f6672")
    ax.set_aspect("equal")
    legend = ["%s — %d чел. (%d%%)" % (name, counts.get(key, 0),
              round(counts.get(key, 0) / total * 100) if total else 0)
              for key, name, _ in labels]
    fig.legend([Patch(facecolor=color) for _, _, color in labels], legend,
               loc="center left", bbox_to_anchor=(0.57, 0.51), frameon=False,
               labelspacing=1.3, fontsize=12)
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=300, facecolor="white")
    return out.getvalue()


# ---------------------------------------------------------------- import (CSV / XLSX)

def read_xlsx(raw):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    z = zipfile.ZipFile(io.BytesIO(raw))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    if not sheets:
        raise ApiError("В файле не найдено листов")
    root = ET.fromstring(z.read(sheets[0]))
    table = []
    for row in root.iter("{%s}row" % ns["m"]):
        cells = {}
        for c in row.findall("m:c", ns):
            ref = c.get("r", "")
            col_letters = re.match(r"[A-Z]+", ref)
            col = 0
            for ch in (col_letters.group(0) if col_letters else "A"):
                col = col * 26 + ord(ch) - 64
            t = c.get("t")
            v = c.find("m:v", ns)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
            else:
                val = v.text if v is not None else ""
                if val and re.fullmatch(r"-?\d+\.0", val):
                    val = val[:-2]
            cells[col - 1] = val or ""
        if cells:
            width = max(cells) + 1
            table.append([cells.get(i, "") for i in range(width)])
    return table


def read_table(filename, raw):
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".xlsx":
        return read_xlsx(raw)
    if ext == ".xls":
        from vendor import xlrd
        try:
            book = xlrd.open_workbook(file_contents=raw)
            sheet = book.sheet_by_index(0)
            def cell_string(value):
                return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value or "")
            return [[cell_string(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
                    for r in range(sheet.nrows)]
        except (xlrd.XLRDError, IndexError, ValueError) as e:
            raise ApiError("Не удалось прочитать файл .xls: %s" % e)
    if ext not in (".csv", ".txt"):
        raise ApiError("Неподдерживаемый формат файла. Используйте XLS, XLSX или CSV")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:2000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    if "\t" in sample and sample.count("\t") > sample.count(delim):
        delim = "\t"
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim)]


def parse_mark(v):
    v = (v or "").strip().lower().replace("−", "-").replace("–", "-")
    if v in ("+", "1", "+1", "да", "x", "х", "v"):
        return "pos"
    if v in ("-", "-1", "нет"):
        return "neg"
    return None


def import_file(conn, study_id, criterion_id, filename, raw, mode="auto"):
    table = [[(c or "").strip() for c in r] for r in read_table(filename, raw)]
    table = [r for r in table if any(r)]
    if not table:
        raise ApiError("Файл пустой")
    if mode not in ("auto", "members", "matrix"):
        raise ApiError("Неверный режим импорта")
    header = table[0]
    # Формат Социоматрица.Онлайн: №, ФИО, 1, 2, ...; в строках номер, имя, выборы.
    numbered_matrix = (mode != "members" and len(header) >= 4 and
                       header[0].lower().strip(". ") in ("№", "номер", "n", "no") and
                       header[1].lower().strip(". ") in ("фио", "ф.и.о", "имя", "name"))
    if numbered_matrix:
        rows = [r for r in table[1:] if any(r)]
        numbers = [r[0] for r in rows]
        columns = [h for h in header[2:] if h]
        if (len(numbers) < 2 or len(set(numbers)) != len(numbers) or
                len(columns) != len(header) - 2 or len(set(columns)) != len(columns) or
                set(numbers) != set(columns) or
                any(len(r) < 2 or not r[1] for r in rows)):
            raise ApiError("Номера участников и столбцов выборов должны совпадать")
        by_number = {r[0]: r[1] for r in rows}
        table = [["", *[by_number[h] for h in columns]]] + [
            [r[1], *[r[i] if i < len(r) else "" for i in range(2, len(header))]]
            for r in rows]
        header = table[0]
    names_in_cols = [h for h in header[1:] if h]
    is_matrix = mode == "matrix" or (mode == "auto" and len(names_in_cols) >= 2
        and len(table) >= 3 and set(n.lower() for n in names_in_cols)
        == set(r[0].lower() for r in table[1:] if r))
    existing = {m["name"].lower(): m["id"] for m in get_study(conn, study_id)["members"]}
    if not is_matrix:
        numbered = len(header) >= 2 and header[0].lower().strip(". ") in ("№", "номер", "n", "no")
        if not numbered and len(table) > 1:
            numbered = all(len(r) >= 2 and r[0].strip().isdigit() for r in table[1:])
        names = [r[1] if numbered and len(r) > 1 else r[0] for r in table if r]
        if names and names[0].lower() in ("фио", "ф.и.о.", "имя", "участник", "участники", "name", "№"):
            names = names[1:]
        names = [x for x in names if x]
        lowered = [x.casefold() for x in names]
        if len(lowered) != len(set(lowered)):
            raise ApiError("В файле повторяются имена участников")
        names = [x for x in names if x.casefold() not in existing]
        return dict(mode="members", added=add_members(conn, study_id, names))
    # матрица выборов: строки — кто выбирает, столбцы — кого выбирают
    row_names = [r[0] for r in table[1:] if r and r[0]]
    col_keys = [x.casefold() for x in names_in_cols]
    row_keys = [x.casefold() for x in row_names]
    if len(names_in_cols) < 2 or len(col_keys) != len(set(col_keys)) or len(row_keys) != len(set(row_keys)):
        raise ApiError("В матрице мало участников или повторяются имена")
    if set(col_keys) != set(row_keys):
        raise ApiError("Имена в строках и столбцах матрицы должны совпадать")
    marks = []
    for row in table[1:]:
        if not row or not row[0]:
            continue
        for col, target in enumerate(header[1:], 1):
            if not target:
                continue
            value = row[col] if col < len(row) else ""
            kind = parse_mark(value)
            if value and kind is None:
                raise ApiError("Неизвестный выбор «%s» для %s → %s" % (value, row[0], target))
            if kind and row[0].casefold() != target.casefold():
                marks.append((row[0].casefold(), target.casefold(), kind))
    new = [x for x in names_in_cols if x.casefold() not in existing]
    add_members(conn, study_id, new)
    existing = {m["name"].lower(): m["id"] for m in get_study(conn, study_id)["members"]}
    if not criterion_id:
        # единственный пустой критерий используем, а не плодим новый
        crits = conn.execute(
            "SELECT k.id, (SELECT COUNT(*) FROM choices c WHERE c.criterion_id=k.id) AS n"
            " FROM criteria k WHERE k.study_id=?", (study_id,)).fetchall()
        if len(crits) == 1 and crits[0]["n"] == 0:
            criterion_id = crits[0]["id"]
    if not criterion_id:
        criterion_id = add_criterion(conn, study_id, os.path.splitext(filename)[0])
    if study_of_criterion(conn, criterion_id) != study_id:
        raise ApiError("Критерий не принадлежит этой социометрии")
    for source, target, kind in marks:
        set_choice(conn, dict(criterion_id=criterion_id, from_id=existing[source],
                              to_id=existing[target], kind=kind))
    for name in row_names:
        set_questionnaire_filled(conn, criterion_id, existing[name.casefold()], True)
    return dict(mode="matrix", added=len(new), choices=len(marks), criterion_id=criterion_id)


def create_study_from_file(conn, data, filename, raw, mode="auto"):
    sid = create_study(conn, data)
    result = import_file(conn, sid, None, filename, raw, mode)
    return dict(id=sid, **result)


def parse_multipart(content_type, body):
    m = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type or "")
    if not m:
        raise ApiError("Нет файла")
    boundary = (m.group(1) or m.group(2)).encode()
    fields, files = {}, {}
    for part in body.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        data = data[:-2] if data.endswith(b"\r\n") else data
        head = head.decode("utf-8", "replace")
        name = re.search(r'name="([^"]*)"', head)
        fn = re.search(r'filename="([^"]*)"', head)
        if not name:
            continue
        if fn:
            files[name.group(1)] = (fn.group(1), data)
        else:
            fields[name.group(1)] = data.decode("utf-8", "replace")
    return fields, files


# ---------------------------------------------------------------- demo data

DEMO_NAMES = ["Анна К.", "Борис Л.", "Вера М.", "Глеб Н.", "Дарья О.", "Егор П.", "Жанна Р.",
              "Иван С.", "Карина Т.", "Лев У.", "Мария Ф.", "Никита Х."]


def create_demo(conn):
    import random
    rnd = random.Random(7)
    sid = create_study(conn, dict(
        name="Демо: 8 «Б» класс", description="Пример с вымышленными данными",
        max_pos=3, max_neg=2, perceptual=1, members=DEMO_NAMES,
        criteria=["С кем бы ты хотел сидеть за одной партой?", "Кого бы ты пригласил на день рождения?"]))
    st = get_study(conn, sid)
    ids = [m["id"] for m in st["members"]]
    groups = [ids[:4], ids[4:8], ids[8:11]]
    for crit in st["criteria"]:
        for a in ids:
            own = next((g for g in groups if a in g), [])
            pool = [b for b in own if b != a] * 3 + [b for b in ids if b != a and b != ids[11]]
            pos = []
            while len(pos) < 3:
                b = rnd.choice(pool)
                if b not in pos:
                    pos.append(b)
            neg_pool = [b for b in ids if b != a and b not in pos]
            negs = rnd.sample(neg_pool, rnd.randint(0, 2))
            if ids[11] != a and ids[11] not in pos and rnd.random() < 0.5 and ids[11] not in negs:
                negs = (negs + [ids[11]])[-2:]
            for b in pos:
                set_choice(conn, dict(criterion_id=crit["id"], from_id=a, to_id=b, kind="pos"))
            for b in negs:
                set_choice(conn, dict(criterion_id=crit["id"], from_id=a, to_id=b, kind="neg"))
            guess = rnd.sample([b for b in ids if b != a], 2)
            for b in guess:
                set_choice(conn, dict(criterion_id=crit["id"], from_id=a, to_id=b,
                                      kind="ppos", perceptual=True))
    return sid


# ---------------------------------------------------------------- full-study backup

def export_study(conn, sid):
    st = get_study(conn, sid)
    idx = {m["id"]: k for k, m in enumerate(st["members"])}
    cidx = {c["id"]: k for k, c in enumerate(st["criteria"])}
    photos = [[idx[r["member_id"]], r["mime"], base64.b64encode(r["data"]).decode("ascii")]
              for r in conn.execute("SELECT p.* FROM member_photos p JOIN members m ON m.id=p.member_id"
                                    " WHERE m.study_id=?", (sid,))]
    layouts = []
    for r in conn.execute("SELECT l.* FROM graph_layouts l JOIN criteria c ON c.id=l.criterion_id"
                          " WHERE c.study_id=?", (sid,)):
        positions = {str(idx[int(mid)]): point for mid, point in json.loads(r["positions"]).items()}
        layouts.append([cidx[r["criterion_id"]], r["graph_key"], positions])
    return dict(format="opensociometry/3", name=st["name"], description=st["description"],
                max_pos=st["max_pos"], max_neg=st["max_neg"], perceptual=st["perceptual"],
                optimistic=st["optimistic"],
                members=[m["name"] for m in st["members"]],
                criteria=[c["name"] for c in st["criteria"]],
                choices=[[cidx[c["criterion_id"]], idx[c["from_id"]], idx[c["to_id"]], c["kind"]]
                         for c in st["choices"]],
                filled=[[cidx[q["criterion_id"]], idx[q["member_id"]]] for q in st["filled"]],
                photos=photos, layouts=layouts)


def import_study_json(conn, data):
    if not isinstance(data, dict) or data.get("format") not in (
            "opensociometry/1", "opensociometry/2", "opensociometry/3", "sociometry-local/1"):
        raise ApiError("Это не файл резервной копии OpenSociometry")
    conn.execute("SAVEPOINT restore_study")
    try:
        sid = create_study(conn, dict(data, criteria=data["criteria"] or ["Критерий"],
                                      members=data["members"]))
        st = get_study(conn, sid)
        mids = [m["id"] for m in st["members"]]
        cids = [c["id"] for c in st["criteria"]]
        for ci, a, b, kind in data["choices"]:
            if kind not in KINDS or a == b:
                raise ApiError("Неверный выбор в резервной копии")
            conn.execute("INSERT OR IGNORE INTO choices VALUES(?,?,?,?)", (cids[ci], mids[a], mids[b], kind))
        for ci, member in data.get("filled", []):
            set_questionnaire_filled(conn, cids[ci], mids[member], True)
        for member, _mime, encoded in data.get("photos", []):
            raw = base64.b64decode(encoded, validate=True)
            set_member_photo(conn, mids[member], raw)
        for ci, key, positions in data.get("layouts", []):
            remapped = {str(mids[int(member)]): point for member, point in positions.items()}
            save_graph_layout(conn, cids[ci], key, remapped)
        conn.execute("RELEASE SAVEPOINT restore_study")
        return sid
    except (ApiError, IndexError, KeyError, ValueError, TypeError, AttributeError,
            binascii.Error, sqlite3.IntegrityError) as e:
        conn.execute("ROLLBACK TO SAVEPOINT restore_study")
        conn.execute("RELEASE SAVEPOINT restore_study")
        if isinstance(e, ApiError):
            raise
        raise ApiError("Повреждённая резервная копия") from e


def clone_study(conn, sid):
    data = export_study(conn, sid)
    data["name"] += " (копия)"
    return import_study_json(conn, data)


# ---------------------------------------------------------------- HTTP

MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenSociometry/0.1.0"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, body, ctype, filename=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            from urllib.parse import quote
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 30 * 1024 * 1024:
            raise ApiError("Файл слишком большой (максимум 30 МБ)", 413)
        return self.rfile.read(n) if n else b""

    def json_body(self):
        raw = self.body()
        return json.loads(raw.decode() or "{}") if raw else {}

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        url = urlparse(self.path)
        path = url.path
        try:
            if not path.startswith("/api/"):
                return self.static(path)
            # защита от запросов с чужих сайтов
            origin = self.headers.get("Origin")
            if method != "GET" and origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
                raise ApiError("Запрещено", 403)
            with db() as conn:
                return self.api(conn, method, path, parse_qs(url.query))
        except ApiError as e:
            self.send_json({"error": str(e)}, e.status)
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            self.send_json({"error": "Неверные данные: %s" % e}, 400)
        except zipfile.BadZipFile:
            self.send_json({"error": "Файл повреждён или не является .xlsx"}, 400)

    def static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if os.path.commonpath((STATIC_DIR, full)) != STATIC_DIR or not os.path.isfile(full):
            full = os.path.join(STATIC_DIR, "index.html")
        with open(full, "rb") as f:
            self.send_file(f.read(), MIME.get(os.path.splitext(full)[1], "application/octet-stream"))

    def api(self, conn, method, path, query):
        p = path.strip("/").split("/")[1:]  # без "api"
        if p == ["studies"] and method == "GET":
            rows = conn.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM members m WHERE m.study_id=s.id) AS n_members,"
                " (SELECT COUNT(*) FROM criteria c WHERE c.study_id=s.id) AS n_criteria,"
                " (SELECT COUNT(*) FROM questionnaires q JOIN criteria c ON c.id=q.criterion_id"
                " WHERE c.study_id=s.id) AS n_filled"
                " FROM studies s ORDER BY s.updated_at DESC, s.id DESC").fetchall()
            return self.send_json([dict(r) for r in rows])
        if p == ["studies"] and method == "POST":
            return self.send_json({"id": create_study(conn, self.json_body())})
        if p == ["studies", "import"] and method == "POST":
            fields, files = parse_multipart(self.headers.get("Content-Type"), self.body())
            if "file" not in files:
                raise ApiError("Файл не выбран")
            fn, raw = files["file"]
            data = json.loads(fields.get("study", "{}"))
            return self.send_json(create_study_from_file(conn, data, fn, raw,
                                                         fields.get("mode", "auto")))
        if p == ["demo"] and method == "POST":
            return self.send_json({"id": create_demo(conn)})
        if p == ["restore"] and method == "POST":
            return self.send_json({"id": import_study_json(conn, self.json_body())})
        if len(p) >= 2 and p[0] == "studies":
            sid = int(p[1])
            if len(p) == 2:
                if method == "GET":
                    return self.send_json(get_study(conn, sid))
                if method == "PUT":
                    d = self.json_body()
                    get_study(conn, sid)
                    conn.execute("UPDATE studies SET name=?,description=?,max_pos=?,max_neg=?,perceptual=?,optimistic=?,updated_at=? WHERE id=?",
                                 (d["name"].strip() or "Без названия", d.get("description", ""),
                                  int(d.get("max_pos") or 0), int(d.get("max_neg") or 0),
                                  1 if d.get("perceptual") else 0,
                                  1 if d.get("optimistic") else 0, now(), sid))
                    return self.send_json(get_study(conn, sid))
                if method == "DELETE":
                    conn.execute("DELETE FROM studies WHERE id=?", (sid,))
                    return self.send_json({"ok": True})
            if p[2:] == ["members"] and method == "POST":
                get_study(conn, sid)
                names = self.json_body().get("names", [])
                return self.send_json({"added": add_members(conn, sid, names)})
            if p[2:] == ["copy"] and method == "POST":
                return self.send_json({"id": clone_study(conn, sid)})
            if p[2:] == ["criteria"] and method == "POST":
                get_study(conn, sid)
                return self.send_json({"id": add_criterion(conn, sid, self.json_body().get("name", ""))})
            if p[2:] == ["import"] and method == "POST":
                get_study(conn, sid)
                fields, files = parse_multipart(self.headers.get("Content-Type"), self.body())
                if "file" not in files:
                    raise ApiError("Файл не выбран")
                fn, raw = files["file"]
                crit = int(fields.get("criterion_id") or 0) or None
                return self.send_json(import_file(conn, sid, crit, fn, raw, fields.get("mode", "auto")))
            if p[2:] == ["backup"] and method == "GET":
                data = export_study(conn, sid)
                body = json.dumps(data, ensure_ascii=False, indent=1).encode()
                return self.send_file(body, "application/json", "%s.opensociometry.json" % safe_name(data["name"]))
        if len(p) == 3 and p[0] == "members" and p[2] == "photo":
            mid = int(p[1])
            if method == "GET":
                mime, raw = get_member_photo(conn, mid)
                return self.send_file(raw, mime)
            if method == "POST":
                _, files = parse_multipart(self.headers.get("Content-Type"), self.body())
                if "file" not in files:
                    raise ApiError("Фото не выбрано")
                set_member_photo(conn, mid, files["file"][1])
                return self.send_json({"ok": True})
            if method == "DELETE":
                member = conn.execute("SELECT study_id FROM members WHERE id=?", (mid,)).fetchone()
                if not member:
                    raise ApiError("Участник не найден", 404)
                conn.execute("DELETE FROM member_photos WHERE member_id=?", (mid,))
                touch(conn, member["study_id"])
                return self.send_json({"ok": True})
        if len(p) == 2 and p[0] == "members":
            mid = int(p[1])
            r = conn.execute("SELECT study_id FROM members WHERE id=?", (mid,)).fetchone()
            if not r:
                raise ApiError("Участник не найден", 404)
            if method == "PUT":
                d = self.json_body()
                conn.execute("UPDATE members SET name=? WHERE id=?", (d["name"].strip()[:200] or "?", mid))
            elif method == "DELETE":
                conn.execute("DELETE FROM members WHERE id=?", (mid,))
            touch(conn, r["study_id"])
            return self.send_json({"ok": True})
        if len(p) >= 2 and p[0] == "criteria":
            cid = int(p[1])
            sid = study_of_criterion(conn, cid)
            if len(p) == 2 and method == "PUT":
                conn.execute("UPDATE criteria SET name=? WHERE id=?", (self.json_body()["name"].strip() or "Критерий", cid))
                touch(conn, sid)
                return self.send_json({"ok": True})
            if len(p) == 2 and method == "DELETE":
                conn.execute("DELETE FROM criteria WHERE id=?", (cid,))
                touch(conn, sid)
                return self.send_json({"ok": True})
            if p[2:] == ["clear"] and method == "POST":
                conn.execute("DELETE FROM choices WHERE criterion_id=?", (cid,))
                touch(conn, sid)
                return self.send_json({"ok": True})
            if len(p) == 4 and p[2] == "layout":
                if method == "GET":
                    return self.send_json(get_graph_layout(conn, cid, p[3]))
                if method == "POST":
                    save_graph_layout(conn, cid, p[3], self.json_body())
                    return self.send_json({"ok": True})
            if p[2:] == ["results"] and method == "GET":
                return self.send_json(compute(conn, cid))
            if p[2:] == ["status-chart.png"] and method == "GET":
                res = compute(conn, cid)
                body = render_status_chart_png(res["group"]["categories"])
                filename = ("%s - статусы.png" % safe_name(res["study"]["name"])) if query.get("download") else None
                return self.send_file(body, "image/png", filename)
            if p[2:] == ["results.csv"] and method == "GET":
                res = compute(conn, cid)
                body = results_csv(res).encode("utf-8")
                return self.send_file(body, "text/csv; charset=utf-8",
                                      "%s - %s.csv" % (safe_name(res["study"]["name"]), safe_name(res["criterion"]["name"])[:40]))
        if p == ["choice"] and method == "POST":
            set_choice(conn, self.json_body())
            return self.send_json({"ok": True})
        if p == ["questionnaire"] and method == "POST":
            data = self.json_body()
            set_questionnaire_filled(conn, int(data["criterion_id"]),
                                     int(data["member_id"]), bool(data["filled"]))
            return self.send_json({"ok": True})
        raise ApiError("Не найдено", 404)


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip() or "sociometry"


def main():
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    init_db()
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        url = "http://%s:%d/" % (HOST, PORT)
        print("Порт %d занят — похоже, приложение уже запущено. Открываю %s" % (PORT, url))
        webbrowser.open(url)
        return
    url = "http://%s:%d/" % (HOST, PORT)
    print("OpenSociometry запущена: %s" % url)
    print("База данных: %s" % DB_PATH)
    print("Чтобы остановить — закройте это окно или нажмите Ctrl+C.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")


if __name__ == "__main__":
    main()
