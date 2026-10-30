#!/usr/bin/env python3
"""Adiciona localmente as musicas OP/ED de BT4 como BGM extra no Tenkaichi3Decomp.

Nao inclui arquivos do jogo, nao altera os AFS originais, nem substitui videos.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import struct
import sys

TRACKS = (
    ("ZS4USOP.ADX", "BT4_Abertura.adx", "BT4 Abertura"),
    ("ZS4USED.ADX", "BT4_Encerramento.adx", "BT4 Encerramento"),
)


def sha256(path):
    dig = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            dig.update(block)
    return dig.digest()


def check_adx(path):
    with path.open("rb") as handle:
        head = handle.read(32)
    if len(head) < 20 or head[:2] != b"\x80\x00":
        raise ValueError(f"Nao parece um ADX valido: {path}")
    encoding, block, bits, channels = head[4:8]
    rate = struct.unpack_from(">I", head, 8)[0]
    if (encoding, block, bits) != (3, 18, 4) or channels not in (1, 2) or not 16000 <= rate <= 48000:
        raise ValueError(f"ADX nao reconhecido pelo instalador: {path} (canais={channels}, taxa={rate})")
    return channels, rate


def main():
    parser = argparse.ArgumentParser(description="Adiciona as musicas de abertura/encerramento do BT4 ao seletor de BGM")
    parser.add_argument("--bt4", type=Path, required=True, help="Pasta BT4 que contem DATA/ ou a propria DATA/")
    parser.add_argument("--port", type=Path, required=True, help="Pasta principal do Tenkaichi3Decomp instalada")
    parser.add_argument("--dry-run", action="store_true", help="Exibe operacoes sem criar ou copiar arquivos")
    args = parser.parse_args()
    data = args.bt4.expanduser().resolve()
    if (data / "DATA").is_dir():
        data = data / "DATA"
    base = args.port.expanduser().resolve()
    if not (base / "gamedata").is_dir():
        parser.error(f"Nao existe gamedata/ em {base}. Informe a pasta principal do Tenkaichi3Decomp.")
    target_dir = base / "songs"
    items = []
    for original, destname, title in TRACKS:
        src = data / original
        if not src.is_file():
            parser.error(f"Falta o arquivo: {src}")
        channels, rate = check_adx(src)
        dst = target_dir / destname
        if dst.exists() and sha256(dst) != sha256(src):
            parser.error(f"Arquivo diferente ja existe: {dst}. Nada foi alterado.")
        items.append((src, dst, title, channels, rate))
    manifest = target_dir / "songs.txt"
    old = manifest.read_text(encoding="utf-8-sig") if manifest.exists() else ""
    seen = {line.split("|", 1)[0].strip().lower() for line in old.splitlines() if "|" in line}
    added_lines = [f"{dst.name}|{title}" for _, dst, title, _, _ in items if dst.name.lower() not in seen]
    for src, dst, _, channels, rate in items:
        state = "ja presente" if dst.exists() else "copiar"
        print(f"{state}: {src.name} -> {dst} ({channels} canais, {rate} Hz)")
    for line in added_lines:
        print(f"Adicionar ao songs.txt: {line}")
    if args.dry_run:
        print("Simulacao concluida. Nenhum arquivo foi modificado.")
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for src, dst, _, _, _ in items:
        if not dst.exists():
            shutil.copy2(src, dst)
    if added_lines:
        with manifest.open("a", encoding="utf-8", newline="\n") as f:
            if old and not old.endswith(("\n", "\r")):
                f.write("\n")
            f.write("\n".join(added_lines) + "\n")
    print("Pronto: reinicie o Tenkaichi3Decomp e veja o seletor de musicas das batalhas.")
    print("As musicas sao faixas adicionais e tocam em loop; os videos de abertura nao foram modificados.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1)
