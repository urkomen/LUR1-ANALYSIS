#!/usr/bin/env python3
'''
Extrae todos los .zip válidos de data/raw/ que no estén ya extraídos como .SAFE.
Omite zips corruptos o incompletos.
'''

import zipfile
from pathlib import Path

raw_dir = Path('data/raw')
zips = sorted(raw_dir.glob('*.zip'))

if not zips:
    print('No hay archivos .zip en data/raw/')
else:
    print(f'Encontrados {len(zips)} archivos .zip')
    extracted = 0
    skipped = 0
    corrupted = []

    for i, zpath in enumerate(zips, 1):
        safe_name = zpath.stem + '.SAFE'
        safe_path = raw_dir / safe_name

        if safe_path.exists():
            print(f'[{i}/{len(zips)}] Ya extraído: {safe_name}')
            extracted += 1
            continue

        # Verifica que el zip es válido antes de intentar extraer
        try:
            with zipfile.ZipFile(zpath, 'r') as zf:
                zf.testzip()  # Valida el zip
            print(f'[{i}/{len(zips)}] Extrayendo: {zpath.name}')
            with zipfile.ZipFile(zpath, 'r') as zf:
                zf.extractall(raw_dir)
            extracted += 1
        except (zipfile.BadZipFile, Exception) as e:
            print(f'[{i}/{len(zips)}] ERROR (omitiendo): {zpath.name} — {e}')
            corrupted.append(zpath.name)
            skipped += 1

    print(f'\n✓ Extracción completada.')
    print(f'  Extraídas: {extracted}')
    print(f'  Omitidas (corruptas): {len(corrupted)}')

    if corrupted:
        print(f'\nZips corruptos o incompletos ({len(corrupted)}):')
        for name in corrupted:
            print(f'  - {name}')

    safes = list(raw_dir.glob('*.SAFE'))
    print(f'\nEscenas SAFE disponibles: {len(safes)}')
