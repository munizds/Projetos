#!/usr/bin/env python3
"""Diagnostico LOCAL de arquivos AFS BT4 vs gamedata original do Tenkaichi3Decomp.

Nao modifica o jogo, nao converte patches de codigo MIPS e nao infere que
arquivos de mesmo indice tenham o mesmo significado.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import struct
import sys

BLOCK = 1024 * 1024
PAIRS = (
    ("PZS4US0.AFS", "pzs3us0"),
    ("PZS4US1.AFS", "pzs3us1"),
    ("PZS4US2.AFS", "pzs3us2"),
)


def sha_file(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(BLOCK)
            if not chunk:
                break
            result.update(chunk)
    return result.hexdigest()


def sha_entry(stream, offset, length):
    result = hashlib.sha256()
    stream.seek(offset)
    remaining = length
    while remaining:
        chunk = stream.read(min(remaining, BLOCK))
        if not chunk:
            raise OSError("Fim inesperado do AFS")
        result.update(chunk)
        remaining -= len(chunk)
    return result.hexdigest()


def entries(path):
    total = path.stat().st_size
    with path.open("rb") as stream:
        header = stream.read(8)
        if len(header) != 8:
            raise ValueError(f"Cabecalho AFS incompleto: {path}")
        magic, count = struct.unpack("<4sI", header)
        if magic != b"AFS\x00":
            raise ValueError(f"Assinatura AFS invalida: {path}")
        if count > 1_000_000 or 8 + count * 8 > total:
            raise ValueError(f"Contagem AFS invalida: {count}")
        table = stream.read(count * 8)
    if len(table) != count * 8:
        raise ValueError("Tabela AFS incompleta")
    for index in range(count):
        offset, size = struct.unpack_from("<II", table, index * 8)
        if offset + size > total or (size and offset < 8 + count * 8):
            raise ValueError(f"Entrada AFS fora dos limites: {index}")
        yield index, offset, size


def data_path(path):
    path = path.expanduser().resolve()
    return path / "DATA" if (path / "DATA").is_dir() else path


def find_file(folder, filename):
    for item in folder.iterdir():
        if item.is_file() and item.name.lower() == filename.lower():
            return item
    return None


def index_bt3(root):
    same_position = {}
    by_hash = defaultdict(list)
    for _, subfolder in PAIRS:
        folder = root / subfolder
        if not folder.is_dir():
            raise FileNotFoundError(f"Pasta BT3 ausente: {folder}")
        files = sorted(folder.glob("*.bin"))
        print(f"BT3 {subfolder}: {len(files)} entradas", flush=True)
        for item in files:
            if not item.stem.isdigit():
                continue
            number = int(item.stem)
            digest = sha_file(item)
            same_position[(subfolder, number)] = digest
            if len(by_hash[digest]) < 8:
                by_hash[digest].append(f"{subfolder}/{item.name}")
    return same_position, by_hash


def analyze(args):
    mod = data_path(args.bt4)
    original = args.bt3.expanduser().resolve()
    output = args.saida.expanduser().resolve()
    if output in (mod, original) or mod in output.parents or original in output.parents:
        raise ValueError("Use uma pasta de relatorios fora das pastas BT3 e BT4.")
    archives = []
    for afs_name, bt3_folder in PAIRS:
        archive = find_file(mod, afs_name)
        if archive is None:
            raise FileNotFoundError(f"AFS nao encontrado: {mod / afs_name}")
        archives.append((archive, bt3_folder))
    bt3_at, bt3_hashes = index_bt3(original)
    output.mkdir(parents=True, exist_ok=True)
    counts_total = Counter()
    per_afs = {}
    report = output / "comparacao_afs.csv"
    with report.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "arquivo_bt4", "indice", "tamanho_bt4", "sha256_bt4",
            "estado", "arquivo_bt3_mesmo_indice", "outro_recurso_original_identico"
        ])
        for archive, bt3_folder in archives:
            local_counts = Counter()
            print(f"Analisando {archive.name}...", flush=True)
            with archive.open("rb") as stream:
                for number, offset, size in entries(archive):
                    original_rel = f"{bt3_folder}/{number:05d}.bin"
                    if size == 0:
                        state, digest, other = "entrada_vazia", "", []
                    else:
                        digest = sha_entry(stream, offset, size)
                        key = (bt3_folder, number)
                        if bt3_at.get(key) == digest:
                            state, other = "identico_mesmo_indice", []
                        elif digest in bt3_hashes:
                            state, other = "identico_em_outro_local", bt3_hashes[digest]
                        elif key in bt3_at:
                            state, other = "conteudo_diferente_mesmo_indice", []
                        else:
                            state, other = "sem_indice_original", []
                    writer.writerow([
                        archive.name, number, size, digest, state,
                        original_rel if (bt3_folder, number) in bt3_at else "",
                        "; ".join(other)
                    ])
                    local_counts[state] += 1
                    counts_total[state] += 1
            per_afs[archive.name] = {
                "entradas": sum(local_counts.values()),
                "estados": dict(local_counts),
                "tamanho_bytes": archive.stat().st_size
            }
    data = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "diagnostico": "NAO e uma conversao automatica",
        "aviso": "Indices iguais entre BT3 e BT4 podem ter significados diferentes.",
        "quantidade_arquivos_bt3": len(bt3_at),
        "totais": dict(counts_total),
        "arquivos_afs": per_afs
    }
    summary = output / "resumo.json"
    summary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatorios criados: {summary} e {report}")


def extract(args):
    archive = args.afs.expanduser().resolve()
    target = args.saida.expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"Nao vou sobrescrever: {target}")
    with archive.open("rb") as stream:
        for number, offset, size in entries(archive):
            if number != args.indice:
                continue
            if size == 0:
                raise ValueError("Esta entrada esta vazia")
            target.parent.mkdir(parents=True, exist_ok=True)
            stream.seek(offset)
            remaining = size
            with target.open("xb") as out:
                while remaining:
                    chunk = stream.read(min(BLOCK, remaining))
                    if not chunk:
                        raise OSError("Fim inesperado do AFS")
                    out.write(chunk)
                    remaining -= len(chunk)
            print(f"Extraido indice {number}: {target} ({size} bytes)")
            return
    raise IndexError(f"Indice nao localizado no AFS: {args.indice}")


def main():
    parser = argparse.ArgumentParser(description="Diagnostico BT4 -> Tenkaichi3Decomp")
    sub = parser.add_subparsers(dest="acao", required=True)

    p = sub.add_parser("analisar", help="Compara os AFS BT4 com os dados originais BT3")
    p.add_argument("--bt4", type=Path, required=True)
    p.add_argument("--bt3", type=Path, required=True)
    p.add_argument("--saida", type=Path, required=True)
    p.set_defaults(func=analyze)

    p = sub.add_parser("extrair", help="Extrai um indice especifico de um AFS local")
    p.add_argument("--afs", type=Path, required=True)
    p.add_argument("--indice", type=int, required=True)
    p.add_argument("--saida", type=Path, required=True)
    p.set_defaults(func=extract)

    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, FileNotFoundError, FileExistsError, IndexError, OSError) as error:
        print(f"ERRO: {error}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
