#!/usr/bin/env python3
"""BT Mod Manager - instalador e auditor de modificacoes para Tenkaichi3Decomp.

Somente bibliotecas padrao. Le pasta, ZIP, AFS ou ISO 9660 do PS2 sem
modificar o jogo original. Os mapeamentos de BT4 por indice sao experimentais.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import shutil
import struct
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import uuid
import zipfile

CHUNK = 1024 * 1024
MAX_AFS_ENTRIES = 200000
MAX_ZIP_ENTRIES = 300000
PROJECT_DIR = '.bt_mod_manager'
RE_AFS = re.compile(r'^PZS([34])US([012])\.AFS$', re.I)
RE_BIN = re.compile(r'^(pzs3us[012]/[0-9]{5}\.bin)$', re.I)
RE_DISC = re.compile(r'^disc/DATA/(ZS3US(?:OP|ED)\.(?:PSS|ADX))$', re.I)
DIRECT_EXT = {'textures': {'.png', '.dds'}, 'stages': {'.unk'}, 'songs': {'.adx', '.mp3', '.wav', '.flac'}}
SPECIAL_ADX = {'ZS4USOP.ADX': ('BT4_Abertura.adx', 'BT4 Abertura'), 'ZS4USED.ADX': ('BT4_Encerramento.adx', 'BT4 Encerramento')}
SPECIAL_PSS = {'ZS4USOP.PSS': 'ZS3USOP.PSS', 'ZS4USED.PSS': 'ZS3USED.PSS'}


@dataclass(frozen=True)
class Ref:
    kind: str                   # slice | zip
    container: str              # arquivo fisico
    entry: str = ''             # membro zip
    offset: int = 0            # offset absoluto no container
    size: int = 0


@dataclass
class Change:
    origin: str
    dest: str
    category: str
    status: str
    risk: str
    size: int
    source_sha256: str
    current_sha256: str
    explanation: str
    ref: Ref
    checked: bool = False


def digest_stream(stream, size=None):
    h = hashlib.sha256()
    count = 0
    while size is None or count < size:
        b = stream.read(CHUNK if size is None else min(CHUNK, size - count))
        if not b:
            break
        count += len(b)
        h.update(b)
    if size is not None and count != size:
        raise ValueError('Arquivo interrompido durante leitura')
    return h.hexdigest()


def digest_path(p):
    with Path(p).open('rb') as f:
        return digest_stream(f)


@contextmanager
def open_ref(ref):
    if ref.kind == 'slice':
        f = open(ref.container, 'rb')
        try:
            f.seek(ref.offset)
            yield f
        finally:
            f.close()
    elif ref.kind == 'zip':
        z = zipfile.ZipFile(ref.container)
        f = z.open(ref.entry)
        try:
            yield f
        finally:
            f.close()
            z.close()
    else:
        raise ValueError('Fonte desconhecida')


def digest_ref(ref):
    with open_ref(ref) as f:
        return digest_stream(f, ref.size)


def copy_ref(ref, target):
    with open_ref(ref) as src, open(target, 'xb') as dst:
        remaining = ref.size
        while remaining:
            data = src.read(min(CHUNK, remaining))
            if not data:
                raise ValueError('Fonte incompleta')
            dst.write(data)
            remaining -= len(data)


def normalize_name(raw):
    raw = raw.replace('\\', '/')
    if '\x00' in raw or raw.startswith('/') or re.match(r'^[A-Za-z]:', raw):
        return None
    parts = raw.split('/')
    if any(x in ('.', '..', '') for x in parts):
        return None
    return '/'.join(parts)


def validate_game(root):
    root = Path(root).expanduser().resolve()
    for n in ('pzs3us0', 'pzs3us1', 'pzs3us2'):
        if not (root / 'gamedata' / n).is_dir():
            raise ValueError(f'Instalacao incompleta: falta gamedata/{n} em {root}')
    return root


def iso_members(file):
    """Le diretórios ISO9660 primários; extents sao offsets físicos no ISO."""
    result = []
    length = file.stat().st_size
    with file.open('rb') as f:
        f.seek(16 * 2048)
        pvd = f.read(2048)
        if len(pvd) != 2048 or pvd[:7] != b'\x01CD001\x01':
            raise ValueError('Nao e ISO9660 com Primary Volume Descriptor reconhecido')
        def record(buf, pos):
            n = buf[pos]
            if n < 34 or pos + n > len(buf):
                return None
            r = buf[pos:pos+n]
            lba = int.from_bytes(r[2:6], 'little')
            sz = int.from_bytes(r[10:14], 'little')
            flags = r[25]
            m = r[32]
            name = r[33:33+m].decode('ascii', errors='replace').split(';')[0]
            return lba, sz, flags, name
        rootrec = record(pvd, 156)
        if rootrec is None:
            raise ValueError('Diretorio raiz ISO invalido')
        visited = set()
        def walk(lba, size, prefix, depth):
            if depth > 10 or (lba, size) in visited:
                return
            visited.add((lba, size))
            if lba * 2048 + size > length or size > 32 * 1024 * 1024:
                raise ValueError('Diretorio ISO invalido ou excessivo')
            f.seek(lba * 2048)
            buf = f.read(size)
            pos = 0
            while pos < len(buf):
                if not buf[pos]:
                    pos = ((pos // 2048) + 1) * 2048
                    continue
                ent = record(buf, pos)
                step = buf[pos]
                pos += step
                if not ent:
                    continue
                elba, esize, flags, name = ent
                if name in ('\x00', '\x01', '.', '..'):
                    continue
                normalized = normalize_name(prefix + name)
                if not normalized or elba * 2048 + esize > length:
                    continue
                if flags & 2:
                    walk(elba, esize, normalized + '/', depth + 1)
                else:
                    result.append((normalized, Ref('slice', str(file), offset=elba*2048, size=esize)))
        walk(rootrec[0], rootrec[1], '', 0)
    return result


def source_members(source):
    source = Path(source).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f'Mod nao encontrado: {source}')
    if source.is_dir():
        members = []
        for p in source.rglob('*'):
            if p.is_symlink():
                continue
            if p.is_file():
                name = normalize_name(p.relative_to(source).as_posix())
                if name:
                    members.append((name, Ref('slice', str(p), size=p.stat().st_size)))
                if len(members) > MAX_ZIP_ENTRIES:
                    raise ValueError('Pasta com entradas demais')
        return members
    if source.suffix.lower() == '.zip':
        members = []
        with zipfile.ZipFile(source) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = normalize_name(info.filename)
                if not name:
                    raise ValueError(f'Entrada ZIP com caminho inseguro: {info.filename}')
                # Nao descompacta symlinks do Unix
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('ZIP contendo link simbolico nao permitido')
                if info.file_size > 8 * 1024**3:
                    raise ValueError('Entrada ZIP acima do limite de 8 GiB')
                members.append((name, Ref('zip', str(source), entry=info.filename, size=info.file_size)))
                if len(members) > MAX_ZIP_ENTRIES:
                    raise ValueError('ZIP com entradas demais')
        return members
    if source.suffix.lower() == '.iso':
        return iso_members(source)
    if source.suffix.lower() == '.afs':
        return [(source.name, Ref('slice', str(source), size=source.stat().st_size))]
    if source.suffix.lower() in {'.7z', '.rar'}:
        raise ValueError('Para .7z ou .rar, extraia a pasta primeiro. ZIP, ISO, AFS e pastas ja sao suportados.')
    return [(source.name, Ref('slice', str(source), size=source.stat().st_size))]


def inspect_afs(ref):
    if ref.kind == 'zip':
        raise ValueError('AFS dentro de ZIP: extraia o ZIP primeiro; o AFS requer acesso aleatorio eficiente.')
    with open_ref(ref) as f:
        head = f.read(8)
        if len(head) != 8 or head[:4] != b'AFS\x00':
            raise ValueError('AFS com cabecalho invalido')
        count = struct.unpack_from('<I', head, 4)[0]
        if count > MAX_AFS_ENTRIES or 8 + count*8 > ref.size:
            raise ValueError(f'Contagem AFS invalida: {count}')
        table = f.read(count*8)
    base = ref.offset
    for index in range(count):
        off, size = struct.unpack_from('<II', table, index*8)
        if off + size > ref.size or (size and off < 8+count*8):
            raise ValueError(f'Entrada AFS {index} fora do limite')
        if size:
            yield index, Ref('slice', ref.container, offset=base+off, size=size)


def split_member(path):
    path = path.replace('\\', '/')
    pieces = path.split('/')
    # Nao mapear local arbitrario em outros diretorios.
    for start in range(len(pieces)):
        rest = '/'.join(pieces[start:])
        if rest.lower().startswith('gamedata/mods/'):
            tail = rest[len('gamedata/mods/'):]
            if RE_BIN.fullmatch(tail) or RE_DISC.fullmatch(tail):
                return 'gamedata/mods/' + tail, 'dados', 'normal', 'Override explicito em gamedata/mods'
        if rest.lower().startswith('mods/'):
            tail = rest[len('mods/'):]
            if RE_BIN.fullmatch(tail) or RE_DISC.fullmatch(tail):
                return 'gamedata/mods/' + tail, 'dados', 'normal', 'Override explicito'
        if RE_BIN.fullmatch(rest):
            return 'gamedata/mods/' + rest.lower(), 'dados', 'normal', 'Recurso indexado original BT3'
        for folder, exts in DIRECT_EXT.items():
            if rest.lower().startswith(folder + '/') and Path(rest).suffix.lower() in exts and len(rest.split('/')) >= 2:
                return rest, folder, 'normal', f'Recurso na pasta {folder}'
    filename = pieces[-1]
    if filename.upper() in SPECIAL_ADX:
        dest, _ = SPECIAL_ADX[filename.upper()]
        return 'songs/' + dest, 'songs', 'normal', 'Musica BT4 adicionada ao seletor de BGM'
    if filename.upper() in SPECIAL_PSS:
        return 'gamedata/mods/disc/DATA/' + SPECIAL_PSS[filename.upper()], 'video', 'experimental', 'Video PSS BT4: decoder do port precisa ser validado'
    return '', 'nao_reconhecido', 'bloqueado', 'Formato/posicao sem mapeamento automatico'


def destination_safe(root, rel):
    normalized = normalize_name(rel)
    if normalized != rel or not rel:
        raise ValueError('Destino relativo inseguro')
    path = root.joinpath(*PurePosixPath(rel).parts)
    resolved = path.resolve()
    if root not in resolved.parents:
        raise ValueError('Destino sai da instalacao do jogo')
    allowed = ('gamedata/mods/', 'textures/', 'songs/', 'stages/')
    if not rel.replace('\\', '/').lower().startswith(allowed):
        raise ValueError('O instalador so pode gravar overrides, texturas, sons ou arenas')
    return resolved


def scan(source, game, progress=None):
    root = validate_game(game)
    progress = progress or (lambda x: None)
    members = source_members(source)
    changes = []
    hash_cache = {}
    seen_dest = set()
    def old_digest(p):
        if p not in hash_cache:
            hash_cache[p] = digest_path(p) if p.is_file() else ''
        return hash_cache[p]
    def add(name, dest, category, risk, reason, ref, baseline=None):
        if not dest:
            changes.append(Change(name, '', category, 'NAO SUPORTADO', 'bloqueado', ref.size, '', '', reason, ref))
            return
        if dest in seen_dest:
            changes.append(Change(name, dest, category, 'DESTINO REPETIDO', 'bloqueado', ref.size, '', '', 'Dois recursos disputam o mesmo destino', ref))
            return
        seen_dest.add(dest)
        target = destination_safe(root, dest)
        current = old_digest(target)
        incoming = digest_ref(ref)
        if incoming == current:
            status = 'JA INSTALADO'
            checked = False
        elif baseline is not None and incoming == baseline:
            status = 'IDENTICO AO BT3'
            checked = False
        elif risk == 'experimental':
            status = 'REVISAR - EXPERIMENTAL'
            checked = False
        else:
            status = 'SUBSTITUI OVERRIDE' if current else 'NOVO ARQUIVO'
            checked = True
        changes.append(Change(name, dest, category, status, risk, ref.size, incoming, current, reason, ref, checked))

    for k, (name, ref) in enumerate(members):
        upper = Path(name).name.upper()
        match = RE_AFS.fullmatch(upper)
        if match:
            is_bt4 = match.group(1) == '4'
            partition = int(match.group(2))
            progress(f'Lendo {upper}: entradas AFS...')
            for index, part in inspect_afs(ref):
                orig = root / 'gamedata' / f'pzs3us{partition}' / f'{index:05d}.bin'
                baseline = old_digest(orig)
                if index % 1000 == 0:
                    progress(f'{upper}: entrada {index}...')
                add(f'{name} :: {index:05d}', f'gamedata/mods/pzs3us{partition}/{index:05d}.bin',
                    'AFS BT4' if is_bt4 else 'AFS BT3', 'experimental',
                    'BT4->BT3 por mesmo indice; SEM garantia de equivalencia' if is_bt4 else
                    'AFS por indice; confirme compatibilidade do recurso', part, baseline)
        else:
            dest, category, risk, reason = split_member(name)
            # .txt de manifesto opcional e tratado como copia direta somente em paths explicitos
            if name.lower().endswith('/songs.txt') and any('/songs/' in '/' + name.lower() for _ in (0,)):
                dest, category, risk, reason = '', 'nao_reconhecido', 'bloqueado', 'Manifesto songs.txt requer merge manual; instalador nao o sobrescreve'
            add(name, dest, category, risk, reason, ref)
        if k % 10 == 0:
            progress(f'Arquivos-fonte analisados: {k+1}/{len(members)} | entradas: {len(changes)}')
    progress(f'Varredura concluida: {len(changes)} entradas. Nenhum arquivo do jogo foi alterado.')
    return changes


def csv_report(changes, destination):
    fields = ['origin', 'dest', 'category', 'status', 'risk', 'size', 'source_sha256', 'current_sha256', 'explanation', 'checked']
    with open(destination, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for c in changes:
            writer.writerow({key: getattr(c, key) for key in fields})


def _write_json_atomic(path, obj):
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def install(game, changes, selected_indices, allow_experimental=False, progress=None):
    root = validate_game(game)
    progress = progress or (lambda x: None)
    chosen = [changes[i] for i in sorted(selected_indices)]
    if not chosen:
        raise ValueError('Nenhuma modificacao selecionada')
    used = set()
    for c in chosen:
        if c.risk == 'bloqueado' or c.status in ('IDENTICO AO BT3', 'JA INSTALADO', 'NAO SUPORTADO'):
            raise ValueError('Selecao contem recurso nao instalavel: ' + c.origin)
        if c.risk == 'experimental' and not allow_experimental:
            raise ValueError('Modificacao experimental selecionada; habilite a autorizacao explicitamente')
        if c.dest in used:
            raise ValueError('Destino duplicado: ' + c.dest)
        used.add(c.dest)
        dest = destination_safe(root, c.dest)
        actual = digest_path(dest) if dest.exists() else ''
        if actual != c.current_sha256:
            raise ValueError(f'Arquivo de destino mudou desde a analise: {c.dest}. Reanalise antes de instalar.')
    txn_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8]
    hist = root / PROJECT_DIR / 'history' / txn_id
    hist.mkdir(parents=True, exist_ok=False)
    record = {'id': txn_id, 'created': datetime.now(timezone.utc).isoformat(), 'state': 'in_progress', 'items': []}
    manifest = hist / 'record.json'
    _write_json_atomic(manifest, record)
    try:
        for i, c in enumerate(chosen):
            dest = destination_safe(root, c.dest)
            backup_rel = 'backups/' + f'{i:06d}.bak' if dest.is_file() else ''
            if backup_rel:
                backup = hist / backup_rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup)
                if digest_path(backup) != c.current_sha256:
                    raise ValueError('Backup nao confere: ' + c.dest)
            entry = {'dest': c.dest, 'origin': c.origin, 'before': c.current_sha256, 'after': c.source_sha256,
                     'backup': backup_rel, 'state': 'prepared'}
            record['items'].append(entry)
            _write_json_atomic(manifest, record)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.parent / ('.btmod_' + uuid.uuid4().hex + '.tmp')
            try:
                copy_ref(c.ref, tmp)
                if digest_path(tmp) != c.source_sha256:
                    raise ValueError('Verificacao de SHA-256 falhou: ' + c.origin)
                # dest != fonte: apenas overlay, texturas, musica ou arena; jogo original intacto
                os.replace(tmp, dest)
            finally:
                if tmp.exists():
                    tmp.unlink()
            entry['state'] = 'installed'
            _write_json_atomic(manifest, record)
            progress(f'Instalado {i+1}/{len(chosen)}: {c.dest}')
        record['state'] = 'installed'
        _write_json_atomic(manifest, record)
        return txn_id
    except Exception:
        # Em caso de erro mantemos journal para recuperacao via interface.
        record['state'] = 'interrupted'
        _write_json_atomic(manifest, record)
        raise


def list_history(game):
    root = validate_game(game)
    folder = root / PROJECT_DIR / 'history'
    result = []
    for p in sorted(folder.glob('*/record.json'), reverse=True) if folder.is_dir() else []:
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            result.append(data)
        except (OSError, ValueError):
            continue
    return result


def undo(game, transaction_id, progress=None):
    root = validate_game(game)
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z_[a-f0-9]{8}', transaction_id):
        raise ValueError('Identificador de historico invalido')
    hist = root / PROJECT_DIR / 'history' / transaction_id
    manifest = hist / 'record.json'
    rec = json.loads(manifest.read_text(encoding='utf-8'))
    if rec['state'] not in ('installed', 'interrupted', 'partial_undo'):
        raise ValueError('Este registro nao esta marcado como instalado')
    progress = progress or (lambda _: None)
    # Uma instalacao interrompida pode ter arquivos com estado "prepared".
    # Compare antes/depois para verificar se a substituicao realmente aconteceu.
    pending = []
    for c in reversed(rec['items']):
        if c['state'] == 'undone':
            continue
        if c['state'] not in ('installed', 'prepared'):
            raise ValueError('Estado desconhecido no historico: ' + c['dest'])
        dest = destination_safe(root, c['dest'])
        actual = digest_path(dest) if dest.is_file() else ''
        if actual == c['before'] and c['state'] == 'prepared':
            # Foi registrado, mas o arquivo ainda nao chegou a ser modificado.
            pending.append((c, False))
            continue
        if actual != c['after']:
            raise ValueError(f'Arquivo alterado depois da instalacao: {c["dest"]}. Nao vou sobrescrever.')
        if c['backup']:
            backup = (hist / c['backup']).resolve()
            if hist.resolve() not in backup.parents or not backup.is_file() or digest_path(backup) != c['before']:
                raise ValueError('Backup ausente ou corrompido: ' + c['dest'])
        pending.append((c, True))
    for c, should_restore in pending:
        if should_restore:
            dest = destination_safe(root, c['dest'])
            if c['backup']:
                tmp = dest.parent / ('.btmod_undo_' + uuid.uuid4().hex)
                try:
                    shutil.copy2(hist / c['backup'], tmp)
                    os.replace(tmp, dest)
                finally:
                    if tmp.exists():
                        tmp.unlink()
            else:
                dest.unlink()
            progress('Desfeito: ' + c['dest'])
        c['state'] = 'undone'
        rec['state'] = 'partial_undo'
        _write_json_atomic(manifest, rec)
    rec['state'] = 'undone'
    _write_json_atomic(manifest, rec)
    return len(rec['items'])


class ModApp:
    def __init__(self, win):
        self.win = win
        win.title('BT Mod Manager | Tenkaichi3Decomp')
        win.geometry('1120x720')
        self.source = tk.StringVar()
        self.game = tk.StringVar()
        self.experimental = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Selecione um mod e a pasta do Tenkaichi3Decomp.')
        self.filter_var = tk.StringVar(value='Todos')
        self.changes = []
        self.selected = set()
        self.visible_index = {}
        self.events = queue.Queue()
        self.busy = False
        self._layout()
        self.win.after(100, self._poll)

    def _layout(self):
        main = ttk.Frame(self.win, padding=12)
        main.pack(fill='both', expand=True)
        ttk.Label(main, text='BT MOD MANAGER', font=('Segoe UI', 21, 'bold')).pack(anchor='w')
        ttk.Label(main, text='Leia, compare e instale mods com relatorio e restauracao. Os arquivos originais do BT3 nao sao substituidos.').pack(anchor='w', pady=(0, 12))
        for name, var, callback in [('Mod (pasta, ZIP, ISO ou AFS)', self.source, self.pick_mod),
                                    ('Pasta do Tenkaichi3Decomp', self.game, self.pick_game)]:
            row = ttk.Frame(main)
            row.pack(fill='x', pady=3)
            ttk.Label(row, text=name, width=33).pack(side='left')
            ttk.Entry(row, textvariable=var).pack(side='left', fill='x', expand=True, padx=5)
            ttk.Button(row, text='Procurar...', command=callback).pack(side='left')
        row = ttk.Frame(main)
        row.pack(fill='x', pady=(12, 5))
        self.btn_scan = ttk.Button(row, text='1. Analisar mod', command=self.analyze)
        self.btn_scan.pack(side='left', padx=(0, 7))
        ttk.Button(row, text='Exportar relatorio CSV', command=self.export).pack(side='left', padx=7)
        ttk.Button(row, text='Ver historico / desfazer', command=self.history).pack(side='left', padx=7)
        ttk.Label(row, text='Filtro:').pack(side='left', padx=(18, 3))
        cmb = ttk.Combobox(row, textvariable=self.filter_var, state='readonly', width=16,
                           values=('Todos', 'Novos/alterados', 'Experimentais', 'Ignorados'))
        cmb.pack(side='left')
        cmb.bind('<<ComboboxSelected>>', lambda e: self.render())
        box = ttk.Frame(main)
        box.pack(fill='both', expand=True, pady=10)
        cols = ('sel', 'category', 'source', 'target', 'status', 'size')
        self.tree = ttk.Treeview(box, columns=cols, show='headings', selectmode='extended')
        labels = ('Instalar', 'Tipo', 'Origem no mod', 'Destino no PC', 'Analise', 'Tamanho')
        widths = (65, 95, 295, 320, 175, 90)
        for col, label, width in zip(cols, labels, widths):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=60, stretch=col in ('source', 'target'))
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(box, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<Button-1>', self._click)
        row = ttk.Frame(main)
        row.pack(fill='x')
        ttk.Button(row, text='Marcar todos seguros', command=self.select_safe).pack(side='left', padx=(0, 5))
        ttk.Button(row, text='Desmarcar tudo', command=self.clear).pack(side='left', padx=5)
        ttk.Button(row, text='Alternar linhas destacadas', command=self.toggle_highlight).pack(side='left', padx=5)
        ttk.Button(row, text='Detalhes', command=self.details).pack(side='left', padx=5)
        ttk.Checkbutton(row, text='Autorizar instalacao experimental de recursos nao comprovados',
                        variable=self.experimental).pack(side='left', padx=12)
        self.btn_install = ttk.Button(row, text='2. Instalar selecionados', command=self.apply)
        self.btn_install.pack(side='right')
        ttk.Separator(main).pack(fill='x', pady=10)
        ttk.Label(main, textvariable=self.status, wraplength=1060).pack(anchor='w')
        ttk.Label(main, text='ISO/AFS BT4: correspondencia por indice nao e garantida. A selecao experimental inicia desmarcada.',
                  foreground='#a65413').pack(anchor='w', pady=(6, 0))

    def pick_mod(self):
        path = filedialog.askopenfilename(title='Escolha mod: ZIP, ISO, AFS', filetypes=[('Mods', '*.zip *.iso *.afs'), ('Todos', '*.*')])
        if not path:
            path = filedialog.askdirectory(title='Ou selecione uma pasta ja extraida')
        if path:
            self.source.set(path)

    def pick_game(self):
        path = filedialog.askdirectory(title='Pasta onde fica gamedata')
        if path:
            self.game.set(path)

    def _work(self, fn, callback):
        if self.busy:
            return
        self.busy = True
        self.btn_scan.configure(state='disabled')
        self.btn_install.configure(state='disabled')
        def worker():
            try:
                result = fn(lambda s: self.events.put(('status', s)))
                self.events.put(('success', (callback, result)))
            except Exception as e:
                self.events.put(('error', str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'status':
                    self.status.set(payload)
                elif kind == 'success':
                    callback, result = payload
                    self.busy = False
                    self.btn_scan.configure(state='normal')
                    self.btn_install.configure(state='normal')
                    callback(result)
                elif kind == 'error':
                    self.busy = False
                    self.btn_scan.configure(state='normal')
                    self.btn_install.configure(state='normal')
                    self.status.set('Erro: ' + payload)
                    messagebox.showerror('Nao foi possivel concluir', payload)
        except queue.Empty:
            pass
        self.win.after(100, self._poll)

    def analyze(self):
        if not self.source.get() or not self.game.get():
            return messagebox.showinfo('Escolha arquivos', 'Selecione o mod e a pasta do jogo.')
        self.status.set('Analisando...')
        self._work(lambda status: scan(self.source.get(), self.game.get(), status), self.scan_done)

    def scan_done(self, changes):
        self.changes = changes
        self.selected = {i for i, c in enumerate(changes) if c.checked}
        self.render()
        self.status.set(f'Concluido: {len(changes)} recursos identificados; {len(self.selected)} marcados como instalaveis. Confira os destinos.')

    def _filtered(self, c):
        v = self.filter_var.get()
        if v == 'Experimentais':
            return c.risk == 'experimental'
        if v == 'Ignorados':
            return c.risk == 'bloqueado' or c.status in ('JA INSTALADO', 'IDENTICO AO BT3')
        if v == 'Novos/alterados':
            return c.status in ('NOVO ARQUIVO', 'SUBSTITUI OVERRIDE')
        return True

    def render(self):
        self.tree.delete(*self.tree.get_children())
        self.visible_index = {}
        displayed = 0
        for i, c in enumerate(self.changes):
            if not self._filtered(c):
                continue
            if displayed >= 3000:
                break
            iid = str(i)
            self.visible_index[iid] = i
            self.tree.insert('', 'end', iid=iid, values=(
                '[x]' if i in self.selected else '[ ]', c.category, c.origin, c.dest or '—', c.status,
                f'{c.size / (1024*1024):.2f} MiB'))
            displayed += 1
        if len(self.changes) > 3000:
            self.status.set(f'Exibindo ate 3000 recursos do filtro para manter a interface responsiva; o CSV contem todos os {len(self.changes)}.')

    def _click(self, event):
        row = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if row and col == '#1':
            self._toggle(int(row))

    def _toggle(self, idx):
        c = self.changes[idx]
        if c.risk == 'bloqueado' or c.status in ('JA INSTALADO', 'IDENTICO AO BT3'):
            return
        if idx in self.selected:
            self.selected.remove(idx)
        else:
            self.selected.add(idx)
        self.tree.set(str(idx), 'sel', '[x]' if idx in self.selected else '[ ]')

    def select_safe(self):
        self.selected = {i for i, c in enumerate(self.changes) if c.checked}
        self.render()

    def clear(self):
        self.selected.clear()
        self.render()

    def toggle_highlight(self):
        for iid in self.tree.selection():
            self._toggle(int(iid))

    def details(self):
        selected = self.tree.selection()
        if not selected:
            return messagebox.showinfo('Detalhes', 'Selecione uma linha da tabela.')
        c = self.changes[int(selected[0])]
        value = '\n'.join((
            'Origem: ' + c.origin,
            'Destino: ' + (c.dest or 'nao reconhecido'),
            'Categoria: ' + c.category,
            'Situacao: ' + c.status,
            'Risco: ' + c.risk,
            'Tamanho: ' + str(c.size) + ' bytes',
            'Hash de origem SHA-256: ' + (c.source_sha256 or 'n/a'),
            'Hash do override atual: ' + (c.current_sha256 or 'nao existe'),
            'Observacao: ' + c.explanation,
        ))
        messagebox.showinfo('Detalhes do recurso', value)

    def export(self):
        if not self.changes:
            return messagebox.showinfo('Relatorio', 'Analise um mod primeiro.')
        path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')],
                                            initialfile='relatorio_mod_bt.csv')
        if path:
            try:
                csv_report(self.changes, path)
                messagebox.showinfo('Relatorio gerado', path)
            except Exception as exc:
                messagebox.showerror('Erro', str(exc))

    def apply(self):
        if not self.selected:
            return messagebox.showinfo('Nenhum recurso', 'Marque os recursos que deseja instalar.')
        risky = sum(self.changes[i].risk == 'experimental' for i in self.selected)
        if risky and not self.experimental.get():
            return messagebox.showwarning('Exige autorizacao', 'Selecoes experimentais requerem marcar a autorizacao.')
        explanation = f'Instalar {len(self.selected)} arquivos de override no jogo?\n\n'
        if risky:
            explanation += f'ATENCAO: {risky} recursos experimentais. Mapeamento de indices AFS nao validado; podem provocar travamentos.\n\n'
        explanation += 'Os arquivos do jogo original nao serao substituidos; um historico de backups sera registrado.'
        if not messagebox.askyesno('Confirmar instalacao', explanation):
            return
        indexes = set(self.selected)
        allow = self.experimental.get()
        self._work(lambda p: install(self.game.get(), self.changes, indexes, allow, p), self.install_done)

    def install_done(self, txn_id):
        self.status.set('Instalacao concluida. Historico: ' + txn_id)
        messagebox.showinfo('Mod instalado', 'Os arquivos selecionados foram aplicados.\nHistorico: ' + txn_id)
        self.analyze()

    def history(self):
        if not self.game.get():
            return messagebox.showinfo('Selecione jogo', 'Selecione a pasta do jogo primeiro.')
        try:
            data = list_history(self.game.get())
        except Exception as exc:
            return messagebox.showerror('Erro', str(exc))
        popup = tk.Toplevel(self.win)
        popup.title('Historico e restauracao')
        popup.geometry('850x420')
        tree = ttk.Treeview(popup, columns=('id', 'state', 'total', 'date'), show='headings', selectmode='browse')
        for k, t in [('id', 'Instalacao'), ('state', 'Estado'), ('total', 'Arquivos'), ('date', 'Data UTC')]:
            tree.heading(k, text=t)
            tree.column(k, width=280 if k == 'id' else 150)
        tree.pack(fill='both', expand=True, padx=10, pady=10)
        for i, row in enumerate(data):
            tree.insert('', 'end', iid=str(i), values=(row.get('id'), row.get('state'), len(row.get('items', [])), row.get('created')))
        def restore():
            chosen = tree.selection()
            if not chosen:
                return
            item = data[int(chosen[0])]
            if not messagebox.askyesno('Desfazer', f'Restaurar {item["id"]}?\nO programa verificara os hashes antes de desfazer.'):
                return
            try:
                undo(self.game.get(), item['id'], lambda s: self.status.set(s))
                messagebox.showinfo('Concluido', 'Instalacao desfeita com verificacao de integridade.')
                popup.destroy()
                self.changes.clear()
                self.selected.clear()
                self.render()
            except Exception as exc:
                messagebox.showerror('Nao foi possivel restaurar', str(exc))
        ttk.Button(popup, text='Desfazer instalacao selecionada', command=restore).pack(pady=(0, 12))


def main():
    cli = argparse.ArgumentParser(description='BT Mod Manager')
    sub = cli.add_subparsers(dest='action')
    s = sub.add_parser('scan', help='Analisa mod e salva relatorio CSV')
    s.add_argument('--mod', required=True)
    s.add_argument('--game', required=True)
    s.add_argument('--csv', required=True)
    s = sub.add_parser('install-safe', help='Instala apenas arquivos classificados como diretos')
    s.add_argument('--mod', required=True)
    s.add_argument('--game', required=True)
    s = sub.add_parser('undo', help='Desfaz instalacao de um historico')
    s.add_argument('--game', required=True)
    s.add_argument('--id', required=True)
    args = cli.parse_args()
    if args.action == 'scan':
        changes = scan(args.mod, args.game, print)
        csv_report(changes, args.csv)
        print(f'Relatorio salvo: {args.csv}')
    elif args.action == 'install-safe':
        changes = scan(args.mod, args.game, print)
        selected = {i for i, c in enumerate(changes) if c.checked}
        print('Instalando somente diretos/seguros:', len(selected))
        if selected:
            print('Historico:', install(args.game, changes, selected, False, print))
    elif args.action == 'undo':
        print('Arquivos restaurados:', undo(args.game, args.id, print))
    else:
        win = tk.Tk()
        ModApp(win)
        win.mainloop()


if __name__ == '__main__':
    main()