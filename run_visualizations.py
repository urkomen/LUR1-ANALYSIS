#!/usr/bin/env python3
"""Genera las visualizaciones RGB+clasificación y RGB+NIR de las anomalías para una zona."""
import sys
import argparse
sys.path.insert(0, 'src')

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import yaml
from preprocessor import preprocess
from classifier import classify_scene, load_model, model_name_from_config
from paths import RAW_DIR, zone_from_config, zone_dir, figures_dir

parser = argparse.ArgumentParser(
    description='Figuras RGB + clasificación y RGB + falso color NIR de las escenas anómalas.'
)
parser.add_argument('--config', default='config/costa_vasca.yaml')
parser.add_argument('--sigma', type=float, default=None,
                    help='Umbral en sigmas para seleccionar escenas (por defecto, el del config)')
args = parser.parse_args()

with open(args.config) as f:
    config = yaml.safe_load(f)

zone = zone_from_config(args.config)
zone_label = config['location']['name']
out_dir = zone_dir(zone)

SIGMA = args.sigma if args.sigma is not None else config['anomaly_detector']['threshold_sigma']
indices = config.get('indices', ['NDVI', 'NDWI', 'MNDWI'])

# Los z-scores vienen de anomalies.csv, que ya los calcula leave-one-out.
# Recalcularlos aquí duplicaría la lógica y volvería a divergir.
anomalies_path = out_dir / 'anomalies.csv'
if not anomalies_path.exists():
    print(f'No existe {anomalies_path}.')
    print(f'Ejecuta antes: python src/pipeline.py --config {args.config} --steps anomalies')
    sys.exit(1)

scored = pd.read_csv(anomalies_path)
if scored.empty:
    print(f'[{zone}] Sin escenas evaluables en {anomalies_path}.')
    sys.exit(0)
scored['date'] = pd.to_datetime(scored['date'])

zscore_cols = [f'{idx}_zscore' for idx in indices]
selected = scored[scored[zscore_cols].abs().gt(SIGMA).any(axis=1)].sort_values('date')

print(f'[{zone}] Escenas por encima de {SIGMA}σ: {len(selected)}')

if len(selected) == 0:
    print(f'[{zone}] Sin anomalías, no se generan visualizaciones de escenas.')
    sys.exit(0)

model = load_model(model_name_from_config(config))

anomaly_scenes = []
for _, row in selected.iterrows():
    zscores_dict = {
        idx: row[f'{idx}_zscore'] for idx in indices if pd.notna(row[f'{idx}_zscore'])
    }
    driver = max(zscores_dict, key=lambda k: abs(zscores_dict[k]))
    scene_dir = RAW_DIR / row['scene']
    anomaly_scenes.append({
        'date': row['date'].strftime('%Y-%m-%d'),
        'scene_dir': scene_dir,
        'cloud_pct': row['cloud_pct'],
        'driver': driver,
        'zscore': zscores_dict[driver],
    })
    print(f'  {row["date"].strftime("%Y-%m-%d")} — {driver} z={zscores_dict[driver]:+.2f}')


def stretch(band, p_low=2, p_high=98):
    valid_px = band[~np.isnan(band)]
    lo, hi = np.percentile(valid_px, [p_low, p_high])
    return np.clip((band - lo) / (hi - lo), 0, 1)


class_colors = {'agua': 'royalblue', 'vegetacion': 'forestgreen', 'urbano': 'dimgray',
                'litoral': 'goldenrod', 'sin_datos': 'white'}
class_order = ['agua', 'vegetacion', 'urbano', 'litoral', 'sin_datos']

for item in anomaly_scenes:
    print(f'\nProcesando {item["date"]}...')
    scene = preprocess(item['scene_dir'], config)
    item['classification_map'] = classify_scene(scene, model)

    rgb = np.stack(
        [stretch(scene['bands']['B04']), stretch(scene['bands']['B03']), stretch(scene['bands']['B02'])],
        axis=-1,
    )
    item['rgb'] = np.where(np.isnan(rgb), 1.0, rgb)

    nir = np.stack(
        [stretch(scene['bands']['B08']), stretch(scene['bands']['B04']), stretch(scene['bands']['B03'])],
        axis=-1,
    )
    item['nir'] = np.where(np.isnan(nir), 1.0, nir)

fig_dir = figures_dir(zone)

# --- Fig 1: RGB + clasificación ---
n = len(anomaly_scenes)
fig, axes = plt.subplots(n, 2, figsize=(13, 5.5 * n))
if n == 1:
    axes = axes.reshape(1, 2)

for row_ax, item in zip(axes, anomaly_scenes):
    ax_rgb, ax_class = row_ax
    ax_rgb.imshow(item['rgb'])
    ax_rgb.set_title(f'{item["date"]} — RGB (nubes bbox: {item["cloud_pct"]:.1f}%)', fontsize=11)
    ax_rgb.axis('off')

    color_map = np.zeros((*item['classification_map'].shape, 3))
    for c in class_order:
        color_map[item['classification_map'] == c] = mcolors.to_rgb(class_colors[c])
    ax_class.imshow(color_map)
    ax_class.set_title(f'Clasificación — {item["driver"]} z={item["zscore"]:+.2f}', fontsize=11)
    ax_class.axis('off')

handles = [plt.Rectangle((0, 0), 1, 1, color=class_colors[c]) for c in class_order[:-1]]
fig.legend(handles, class_order[:-1], loc='lower center', ncol=4, fontsize=10,
           bbox_to_anchor=(0.5, -0.01 / n))
fig.suptitle(f'Anomalías detectadas — {zone_label} — visible y clasificación',
             fontsize=15, fontweight='bold', y=1.0)
plt.tight_layout(rect=[0, 0.02, 1, 0.98])
out_png = fig_dir / 'anomalias_rgb_clasificacion.png'
plt.savefig(out_png, dpi=150, bbox_inches='tight')
print(f'Guardado: {out_png}')
plt.close()

# --- Fig 2: RGB + NIR ---
fig, axes = plt.subplots(n, 2, figsize=(13, 5.5 * n))
if n == 1:
    axes = axes.reshape(1, 2)

for row_ax, item in zip(axes, anomaly_scenes):
    ax_rgb, ax_nir = row_ax
    ax_rgb.imshow(item['rgb'])
    ax_rgb.set_title(f'{item["date"]} — RGB visible (nubes bbox: {item["cloud_pct"]:.1f}%)', fontsize=11)
    ax_rgb.axis('off')

    ax_nir.imshow(item['nir'])
    ax_nir.set_title(f'{item["date"]} — Falso color NIR — {item["driver"]} z={item["zscore"]:+.2f}', fontsize=11)
    ax_nir.axis('off')

fig.suptitle(f'Anomalías detectadas — {zone_label} — visible vs. falso color NIR',
             fontsize=15, fontweight='bold', y=1.0)
plt.tight_layout(rect=[0, 0, 1, 0.98])
out_png = fig_dir / 'anomalias_rgb_nir.png'
plt.savefig(out_png, dpi=150, bbox_inches='tight')
print(f'Guardado: {out_png}')
plt.close()

print(f'\n[{zone}] Visualizaciones generadas.')
