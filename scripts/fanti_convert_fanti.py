#!/usr/bin/env python3
"""
繁體轉換工具 - 簡體中文轉繁體
用法: python3 fanti_convert.py convert <file_or_dir> [--output DIR] [--dry-run]
"""

import argparse
import os
import sys
from pathlib import Path

# 優先使用 opencc-python-reborn（功能最完整）
try:
    import opencc

    OPENCC_AVAILABLE = True
except ImportError:
    OPENCC_AVAILABLE = False

# 備用 zhconv
try:
    import zhconv

    ZHCONV_AVAILABLE = True
except ImportError:
    ZHCONV_AVAILABLE = False

# ─── 依賴檢查 ────────────────────────────────────────────────
def check_deps():
    if not OPENCC_AVAILABLE and not ZHCONV_AVAILABLE:
        print("❌ 缺少依賴，請安裝：pip install opencc-python-reborn  或  pip install zhconv", file=sys.stderr)
        sys.exit(1)
    return "opencc" if OPENCC_AVAILABLE else "zhconv"


# ─── 轉換器工廠 ──────────────────────────────────────────────
def make_converter(backend):
    if backend == "opencc":
        # s2tw.json = 簡體→繁體（臺灣正體，含慣用詞轉換）
        return opencc.OpenCC("s2tw.json")
    else:
        # zhconv: 傳回閉包而非可呼叫物件，保持介面一致
        def convert(text):
            return zhconv.convert(text, "zh-hant")
        return convert


def do_convert(converter, text):
    """統一的轉換呼叫介面"""
    if hasattr(converter, "convert"):
        return converter.convert(text)
    return converter(text)


# ─── 判斷是否需要轉換 ───────────────────────────────────────
NEEDS_SKIP = {
    ".pyc", ".so", ".dll", ".exe", ".bin", ".jpg", ".png",
    ".gif", ".mp4", ".mp3", ".pdf", ".zip", ".tar", ".gz",
    ".DS_Store", ".git",
}

def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in (
        ".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml",
        ".ini", ".cfg", ".sh", ".zsh", ".bash", ".conf",
        ".html", ".xml", ".sql", ".proto", ".env",
    )

def needs_conversion(text: str, converter) -> bool:
    """轉換後文字有變化才需要處理。空檔案直接跳過。"""
    if not text.strip():
        return False
    return do_convert(converter, text) != text


# ─── 單檔處理 ────────────────────────────────────────────────
def convert_file(src_path: Path, output_dir: Path | None, dry_run: bool, converter):
    try:
        text = src_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"⚠️ 讀取失敗 {src_path}: {e}", file=sys.stderr)
        return 0

    if not needs_conversion(text, converter):
        print(f"⏩ 跳過（無需轉換）: {src_path}")
        return 0

    if dry_run:
        print(f"🟡 [dry-run] 會轉換: {src_path}")
        return 0

    converted = do_convert(converter, text)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        dst_path = output_dir / src_path.name
    else:
        stem = src_path.stem
        suffix = src_path.suffix
        dst_path = src_path.parent / f"{stem}_fanti{suffix}"

    dst_path.write_text(converted, encoding="utf-8")
    print(f"✅ 已轉換: {src_path}  →  {dst_path}")
    return 1


# ─── 目錄遞迴處理 ───────────────────────────────────────────
def convert_dir(src_dir: Path, output_dir: Path | None, dry_run: bool, converter):
    count = 0
    for root, dirs, files in os.walk(src_dir):
        root_path = Path(root)
        # 遞迴時跳過明顯非文字目錄（可加速）
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", ".venv")]

        for fname in files:
            fpath = root_path / fname
            if fpath.is_symlink():
                continue
            if not is_text_file(fpath):
                continue
            rel = fpath.relative_to(src_dir)
            out = (output_dir / rel.parent) if output_dir else None
            count += convert_file(fpath, out, dry_run, converter)
    return count


# ─── CLI ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="簡體中文 → 繁體中文 轉換工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    conv = sub.add_parser("convert", help="轉換檔案或目錄")
    conv.add_argument("path", help="檔案或目錄路徑")
    conv.add_argument("--output", "-o", type=Path, help="輸出目錄（不指定則在原目錄產生 *_fanti 檔）")
    conv.add_argument("--dry-run", action="store_true", help="只顯示會轉換的檔案，不實際寫入")

    args = parser.parse_args()

    backend = check_deps()
    converter = make_converter(backend)
    print(f"ℹ️  使用轉換引擎: {backend}")

    p = Path(args.path).resolve()

    if not p.exists():
        print(f"❌ 路徑不存在: {p}", file=sys.stderr)
        sys.exit(1)

    if p.is_file():
        count = convert_file(p, args.output, args.dry_run, converter)
    else:
        count = convert_dir(p, args.output, args.dry_run, converter)

    print(f"\n完成：{count} 個檔案已轉換")


if __name__ == "__main__":
    main()
