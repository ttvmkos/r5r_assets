#!/usr/bin/env python3
import json
import os
import re
import shutil
import time
import datetime
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# ----------------------------
# File helpers (encoding/newlines)
# ----------------------------

def detect_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"

def read_text_file(path: str):
    with open(path, "rb") as f:
        raw = f.read()
    enc = detect_encoding(raw)
    text = raw.decode(enc, errors="strict")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text, enc, newline

def write_text_file(path: str, text: str, enc: str):
    with open(path, "wb") as f:
        f.write(text.encode(enc, errors="strict"))

def backup_file(path: str):
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = f"{path}.bak.{ts}"
    shutil.copy2(path, bak)
    return bak

# ----------------------------
# KeyValues insertion logic
# ----------------------------

def kv_escape(s: str) -> str:
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return s

def find_penultimate_unquoted_rbrace_index(text: str) -> int | None:
    """
    Finds the index of the 2nd '}' from the end, ignoring braces inside quoted strings.
    Insert BEFORE this brace to stay inside the Tokens block.
    """
    in_quote = False
    escape = False
    found = 0

    for i in range(len(text) - 1, -1, -1):
        ch = text[i]

        if in_quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_quote = False
            continue

        if ch == '"':
            in_quote = True
            continue

        if ch == "}":
            found += 1
            if found == 2:
                return i

    return None

_TOKEN_LINE_RE = re.compile(r'(?m)^\s*"([^"]+)"\s*"')
_OPEN_BRACE_LINE_RE = re.compile(r'(?m)^(\s*)\{\s*$')
_LAST_TOKENISH_LINE_RE = re.compile(r'^\s*"[^"]+"\s*".*"$')

def detect_token_indent(pre_text: str) -> str:
    lines = pre_text.splitlines()
    for line in reversed(lines):
        if _LAST_TOKENISH_LINE_RE.match(line) and ("{" not in line and "}" not in line):
            return re.match(r"^(\s*)", line).group(1)

    matches = list(_OPEN_BRACE_LINE_RE.finditer(pre_text))
    if matches:
        base = matches[-1].group(1)
        return base + "\t"

    return "\t"

def parse_existing_keys(text: str) -> set[str]:
    return set(_TOKEN_LINE_RE.findall(text))

def replace_existing_value(text: str, key: str, new_value_escaped: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf'(?m)^(?P<indent>\s*)"{re.escape(key)}"\s*"(?P<val>(?:\\.|[^"\\])*)"\s*(?P<suffix>\[[^\]]+\])?\s*$'
    )
    m = pattern.search(text)
    if not m:
        return text, False
    indent = m.group("indent")
    suffix = m.group("suffix") or ""
    repl = f'{indent}"{key}"\t\t"{new_value_escaped}"'
    if suffix:
        repl += f" {suffix}"
    new_text = text[:m.start()] + repl + text[m.end():]
    return new_text, True

def normalize_comment_block(comment_text: str, newline: str, indent: str) -> str:
    comment_text = (comment_text or "").strip()
    if not comment_text:
        return ""

    out_lines = []
    for raw_line in comment_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("//"):
            out_lines.append(f"{indent}{line}")
        else:
            out_lines.append(f"{indent}// {line}")

    if not out_lines:
        return ""
    return newline.join(out_lines) + newline

def insert_tokens_before_penultimate_brace(
    text: str,
    newline: str,
    tokens: list[tuple[str, str]],
    *,
    comment_block: str = "",
    skip_existing: bool = True,
    overwrite_existing: bool = False
) -> tuple[str, dict]:
    idx = find_penultimate_unquoted_rbrace_index(text)
    if idx is None:
        raise ValueError("Could not find two closing braces '}}' to insert before.")

    stats = {"inserted": 0, "skipped": 0, "updated": 0}
    existing = parse_existing_keys(text)

    # Overwrite pass first (optional)
    if overwrite_existing:
        for key, val in tokens:
            key = str(key)
            if key not in existing:
                continue
            val_esc = kv_escape(str(val))
            text, did = replace_existing_value(text, key, val_esc)
            if did:
                stats["updated"] += 1
        existing = parse_existing_keys(text)

    idx = find_penultimate_unquoted_rbrace_index(text)
    if idx is None:
        raise ValueError("After updates, could not find insertion point.")

    pre = text[:idx]
    post = text[idx:]
    indent = detect_token_indent(pre)

    insertion = ""
    if pre and not pre.endswith(("\n", "\r")):
        insertion += newline

    tokens_to_insert = []
    for key, val in tokens:
        key = str(key)
        if skip_existing and (key in existing):
            stats["skipped"] += 1
            continue
        tokens_to_insert.append((key, val))

    if tokens_to_insert:
        if comment_block:
            insertion += normalize_comment_block(comment_block, newline, indent)
        for key, val in tokens_to_insert:
            val_esc = kv_escape(str(val))
            insertion += f'{indent}"{key}"\t\t"{val_esc}"{newline}'
            stats["inserted"] += 1

    if not insertion:
        return text, stats

    return pre + insertion + post, stats

# ----------------------------
# UI
# ----------------------------

class LocalizeAppenderUI(tk.Tk):
    def __init__(self, initial_json_path: str | None = None):
        super().__init__()
        self.title("Localization Token Updater (JSON → VDF/KeyValues)")
        self.geometry("1020x820")

        self.loc_dir = tk.StringVar()
        self.prefix = tk.StringVar(value="flowstate_")
        self.ext = tk.StringVar(value=".txt")

        # JSON inputs
        self.json_source = tk.StringVar(value="file")  # "file" or "paste"
        self.json_path = tk.StringVar(value=initial_json_path or "")

        self.backup_var = tk.BooleanVar(value=True)
        self.skip_existing_var = tk.BooleanVar(value=True)
        self.overwrite_existing_var = tk.BooleanVar(value=False)

        today = datetime.date.today().strftime("%m/%d/%y")
        self.default_comment_template = f"// added on {today}"

        self._build()
        self._apply_json_source_state()

    def _build(self):
        pad = {"padx": 8, "pady": 6}

        top = tk.Frame(self)
        top.pack(fill="x")

        # Localization dir
        row1 = tk.Frame(top)
        row1.pack(fill="x", **pad)
        tk.Label(row1, text="Localization folder:").pack(side="left")
        tk.Entry(row1, textvariable=self.loc_dir, width=70).pack(side="left", padx=8, fill="x", expand=True)
        tk.Button(row1, text="Browse…", command=self.browse_dir).pack(side="left")

        # Prefix + ext
        row2 = tk.Frame(top)
        row2.pack(fill="x", **pad)
        tk.Label(row2, text="Formatter/prefix:").pack(side="left")
        tk.Entry(row2, textvariable=self.prefix, width=18).pack(side="left", padx=8)
        tk.Label(row2, text="Extension:").pack(side="left", padx=(16, 0))
        tk.Entry(row2, textvariable=self.ext, width=8).pack(side="left", padx=8)
        tk.Label(row2, text='Example: flowstate_english.txt').pack(side="left", padx=(16, 0))

        # JSON source selector
        row3 = tk.Frame(top)
        row3.pack(fill="x", **pad)
        tk.Label(row3, text="JSON source:").pack(side="left")
        tk.Radiobutton(row3, text="File", variable=self.json_source, value="file",
                       command=self._apply_json_source_state).pack(side="left", padx=(10, 0))
        tk.Radiobutton(row3, text="Paste", variable=self.json_source, value="paste",
                       command=self._apply_json_source_state).pack(side="left", padx=(10, 0))

        # JSON file picker row
        row4 = tk.Frame(top)
        row4.pack(fill="x", **pad)
        tk.Label(row4, text="JSON file:").pack(side="left")
        self.json_file_entry = tk.Entry(row4, textvariable=self.json_path, width=70)
        self.json_file_entry.pack(side="left", padx=8, fill="x", expand=True)
        self.json_browse_btn = tk.Button(row4, text="Browse…", command=self.browse_json)
        self.json_browse_btn.pack(side="left")

        # JSON paste box
        row5 = tk.Frame(top)
        row5.pack(fill="both", **pad)
        tk.Label(row5, text="Paste JSON here (used when JSON source = Paste):").pack(anchor="w")
        self.json_paste_box = ScrolledText(row5, height=10, wrap="word")
        self.json_paste_box.pack(fill="x", expand=True, pady=(4, 0))
        # leave empty by default

        # Options
        row6 = tk.Frame(top)
        row6.pack(fill="x", **pad)
        tk.Checkbutton(row6, text="Create .bak backup", variable=self.backup_var).pack(side="left")
        tk.Checkbutton(row6, text="Skip tokens that already exist", variable=self.skip_existing_var).pack(side="left", padx=(18, 0))
        tk.Checkbutton(row6, text="Overwrite existing token values", variable=self.overwrite_existing_var).pack(side="left", padx=(18, 0))

        # Comment box
        row7 = tk.Frame(top)
        row7.pack(fill="both", **pad)
        tk.Label(row7, text="Optional comment to add above inserted tokens (per file):").pack(anchor="w")
        self.comment_box = ScrolledText(row7, height=4, wrap="word")
        self.comment_box.pack(fill="x", expand=True, pady=(4, 0))
        self.comment_box.insert("1.0", self.default_comment_template)

        # Run
        row8 = tk.Frame(top)
        row8.pack(fill="x", **pad)
        tk.Button(row8, text="Run update", command=self.run_update, height=2).pack(side="left")
        tk.Button(row8, text="Clear log", command=lambda: self.log.delete("1.0", "end")).pack(side="left", padx=10)

        # Log
        self.log = ScrolledText(self, wrap="word")
        self.log.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._log("Tip: You can drag a .json onto this .py file to prefill JSON file path.\n")

    def _apply_json_source_state(self):
        src = self.json_source.get()
        if src == "file":
            self.json_file_entry.configure(state="normal")
            self.json_browse_btn.configure(state="normal")
            self.json_paste_box.configure(state="disabled")
        else:
            self.json_file_entry.configure(state="disabled")
            self.json_browse_btn.configure(state="disabled")
            self.json_paste_box.configure(state="normal")

    def _log(self, msg: str):
        self.log.insert("end", msg)
        self.log.see("end")

    def browse_dir(self):
        d = filedialog.askdirectory(title="Select localization folder")
        if d:
            self.loc_dir.set(d)

    def browse_json(self):
        p = filedialog.askopenfilename(
            title="Select JSON file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if p:
            self.json_path.set(p)

    def _load_json_data(self) -> dict:
        src = self.json_source.get()

        if src == "paste":
            # Get everything except trailing newline (common in Text widgets)
            raw = self.json_paste_box.get("1.0", "end-1c")  # standard pattern [web:34]
            if not raw.strip():
                raise ValueError("Paste box is empty.")
            return json.loads(raw)

        # file mode
        jpath = self.json_path.get().strip()
        if not jpath or not os.path.isfile(jpath):
            raise ValueError("Pick a valid JSON file path (or switch JSON source to Paste).")
        with open(jpath, "r", encoding="utf-8") as f:
            return json.load(f)

    def run_update(self):
        loc_dir = self.loc_dir.get().strip()
        prefix = self.prefix.get()
        ext = self.ext.get().strip()
        comment_block = self.comment_box.get("1.0", "end-1c").strip()

        if not loc_dir or not os.path.isdir(loc_dir):
            messagebox.showerror("Missing folder", "Pick a valid localization folder.")
            return
        if not ext.startswith("."):
            messagebox.showerror("Invalid extension", "Extension must start with a dot, e.g. .txt")
            return

        try:
            data = self._load_json_data()
        except Exception as e:
            messagebox.showerror("JSON error", f"Failed to load JSON:\n{e}")
            return

        if not isinstance(data, dict):
            messagebox.showerror("JSON error", "Top-level JSON must be an object/dict of languages.")
            return

        total = {"files": 0, "inserted": 0, "skipped": 0, "updated": 0, "missing": 0, "errors": 0}
        self._log("\n--- Running update ---\n")

        for lang, items in data.items():
            if not isinstance(items, list):
                self._log(f"[WARN] Language '{lang}' is not a list; skipping.\n")
                continue

            file_path = os.path.join(loc_dir, f"{prefix}{lang}{ext}")
            if not os.path.isfile(file_path):
                total["missing"] += 1
                self._log(f"[MISS] {lang}: file not found: {file_path}\n")
                continue

            tokens = []
            for entry in items:
                if not isinstance(entry, dict) or "token" not in entry or "text" not in entry:
                    continue
                tokens.append((entry["token"], entry["text"]))

            if not tokens:
                self._log(f"[INFO] {lang}: no valid tokens to apply.\n")
                continue

            try:
                text, enc, newline = read_text_file(file_path)

                if self.backup_var.get():
                    bak = backup_file(file_path)
                    self._log(f"[BACKUP] {lang}: {os.path.basename(bak)}\n")

                updated_text, stats = insert_tokens_before_penultimate_brace(
                    text,
                    newline,
                    tokens,
                    comment_block=comment_block,
                    skip_existing=self.skip_existing_var.get(),
                    overwrite_existing=self.overwrite_existing_var.get(),
                )

                if updated_text != text:
                    write_text_file(file_path, updated_text, enc)
                    self._log(
                        f"[OK] {lang}: inserted={stats['inserted']} skipped={stats['skipped']} updated={stats['updated']} "
                        f"({os.path.basename(file_path)})\n"
                    )
                else:
                    self._log(f"[OK] {lang}: no changes needed ({os.path.basename(file_path)})\n")

                total["files"] += 1
                total["inserted"] += stats["inserted"]
                total["skipped"] += stats["skipped"]
                total["updated"] += stats["updated"]

            except Exception as e:
                total["errors"] += 1
                self._log(f"[ERR] {lang}: {e}\n")

        self._log(
            f"--- Done --- files={total['files']} inserted={total['inserted']} skipped={total['skipped']} "
            f"updated={total['updated']} missing={total['missing']} errors={total['errors']}\n"
        )

def _argv_json_path() -> str | None:
    # Drag/drop onto script typically becomes sys.argv[1:] [web:28]
    for a in sys.argv[1:]:
        p = a.strip('"')
        if p.lower().endswith(".json") and os.path.isfile(p):
            return p
    return None

def main():
    initial = _argv_json_path()
    app = LocalizeAppenderUI(initial_json_path=initial)
    if initial:
        app.json_source.set("file")
        app._apply_json_source_state()
        app._log(f"[INFO] JSON file from drag/drop argv: {initial}\n")
    app.mainloop()

if __name__ == "__main__":
    main()
