#!/usr/bin/env python3
"""Descarga de escenas Sentinel-2 para Urdaibai (2024-2025)."""

import sys
import os

# Agregar src al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import yaml
from downloader import download

if __name__ == '__main__':
    # Cargar config de Urdaibai
    with open('config/urdaibai.yaml', 'r') as f:
        config = yaml.safe_load(f)

    print('=' * 70)
    print(f"Descargando escenas para: {config['location']['name']}")
    print('=' * 70)
    print(f"Bbox: {config['location']['bbox']}")
    print(f"Período: {config['dates']['start']} a {config['dates']['end']}")
    print(f"Filtro: ≤{config['satellite']['max_cloud_pct']}% nubes en escena")
    print(f"Tile: {config['satellite']['tile']}")
    print()

    try:
        download(config)
        print('\n✅ Descarga completada.')
        print('Las escenas están en: data/raw/')
    except Exception as e:
        print(f'\n❌ Error durante la descarga: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
