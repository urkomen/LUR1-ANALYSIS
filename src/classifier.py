from pathlib import Path

import geopandas as gpd
import joblib
import numpy as np
from rasterio.transform import rowcol
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.model_selection import train_test_split

from indices import calculate_indices
from paths import MODELS_DIR, PRODUCTION_MODELS_DIR

BAND_NAMES = ['B02', 'B03', 'B04', 'B05', 'B08', 'B11', 'B12']
INDEX_NAMES = ['NDVI', 'NDWI', 'MNDWI']


def extract_features(scene, labels_path):
    labels = gpd.read_file(labels_path)
    labels = labels[labels['etiquetas'].notna()]
    if labels.crs is not None and labels.crs.to_string() != scene['crs'].to_string():
        labels = labels.to_crs(scene['crs'])

    indices = calculate_indices(scene['bands'], INDEX_NAMES)
    height, width = scene['bands'][BAND_NAMES[0]].shape

    X, y, coords = [], [], []
    for geom, clase in zip(labels.geometry, labels['etiquetas']):
        row, col = rowcol(scene['transform'], geom.x, geom.y)
        if not (0 <= row < height and 0 <= col < width):
            continue

        vector = [scene['bands'][b][row, col] for b in BAND_NAMES]
        vector += [indices[idx][row, col] for idx in INDEX_NAMES]
        if np.any(np.isnan(vector)):
            continue

        X.append(vector)
        y.append(clase)
        coords.append((geom.x, geom.y))

    print(f'  Puntos etiquetados: {len(labels)} · válidos tras extracción: {len(X)}')
    return np.array(X, dtype=np.float32), np.array(y), np.array(coords)


def spatial_train_test_split(X, y, coords, block_size_m, test_size, random_state):
    block_ids = np.array([
        f'{int(x // block_size_m)}_{int(y // block_size_m)}' for x, y in coords
    ])

    unique_blocks, block_index = np.unique(block_ids, return_inverse=True)
    block_majority_class = []
    for i in range(len(unique_blocks)):
        classes_in_block = y[block_index == i]
        values, counts = np.unique(classes_in_block, return_counts=True)
        block_majority_class.append(values[np.argmax(counts)])

    train_blocks, test_blocks = train_test_split(
        unique_blocks,
        test_size=test_size,
        random_state=random_state,
        stratify=block_majority_class,
    )
    train_blocks, test_blocks = set(train_blocks), set(test_blocks)

    train_mask = np.array([b in train_blocks for b in block_ids])
    test_mask = np.array([b in test_blocks for b in block_ids])

    print(f'  Bloques: {len(unique_blocks)} (train: {len(train_blocks)}, test: {len(test_blocks)})')
    print(f'  Muestras: train={train_mask.sum()}, test={test_mask.sum()}')

    return X[train_mask], X[test_mask], y[train_mask], y[test_mask]


def train(scene, config, model_name='rf', force=False):
    '''
    Entrena un Random Forest con split espacial sobre una única escena
    etiquetada y lo guarda en data/models/<model_name>.joblib.

    Esto NUNCA toca data/models/production/, que es el modelo que usa el
    pipeline (ver load_model). Entrenar aquí es una zona de pruebas: para que
    un modelo entrenado pase a ser el que usa el pipeline hay que copiarlo a
    mano a data/models/production/<model_name>.joblib.
    '''
    clf_config = config['classifier']

    print(f'Extrayendo features de: {Path(scene["scene_dir"]).name}')
    X, y, coords = extract_features(scene, clf_config['labels_path'])

    print('Dividiendo train/test por bloques espaciales...')
    X_train, X_test, y_train, y_test = spatial_train_test_split(
        X, y, coords,
        block_size_m=clf_config['block_size_m'],
        test_size=clf_config['test_size'],
        random_state=clf_config['random_state'],
    )

    print('Entrenando RandomForestClassifier...')
    model = RandomForestClassifier(n_estimators=200, random_state=clf_config['random_state'])
    model.fit(X_train, y_train)

    print('Evaluando sobre test...')
    y_pred = model.predict(X_test)
    accuracy = model.score(X_test, y_test)
    f1_w = f1_score(y_test, y_pred, average='weighted')
    f1_m = f1_score(y_test, y_pred, average='macro')
    labels_sorted = sorted(np.unique(np.concatenate([y_test, y_pred])))
    matrix = confusion_matrix(y_test, y_pred, labels=labels_sorted)

    print(f'  Accuracy: {accuracy:.3f}')
    print(f'  F1 (weighted): {f1_w:.3f}')
    print(f'  F1 (macro): {f1_m:.3f}')
    print(f'  Clases: {labels_sorted}')
    print(f'  Matriz de confusión:\n{matrix}')

    model_path = MODELS_DIR / f'{model_name}.joblib'
    if model_path.exists() and not force:
        print(f'\nYa existe {model_path} y no se ha indicado --force.')
        print('Usa --name para guardarlo con otro nombre, o --force para sobrescribirlo.')
        return model, None

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    print(f'Modelo guardado en: {model_path}')

    return model, {
        'accuracy': accuracy,
        'f1_weighted': f1_w,
        'f1_macro': f1_m,
        'labels': labels_sorted,
        'confusion_matrix': matrix,
    }


def model_name_from_config(config):
    '''Modelo que debe usarse para una zona; "rf_prod" es el que trae el repositorio.'''
    return (config.get('classifier') or {}).get('model_name', 'rf_prod')


def load_model(model_name='rf_prod'):
    '''
    Carga el modelo de producción (data/models/production/<model_name>.joblib)
    — el que usa el pipeline para clasificar. Es distinto del que genera
    train(): ese escribe en data/models/, no en production/.
    '''
    model_path = PRODUCTION_MODELS_DIR / f'{model_name}.joblib'
    if not model_path.exists():
        raise FileNotFoundError(
            f'Modelo no encontrado: {model_path}.\n'
            f'El repositorio incluye data/models/production/rf_prod.joblib; si lo has '
            f'borrado, recupéralo con "git checkout data/models/production/rf_prod.joblib" '
            f'o entrena uno propio con "python src/classifier.py --config <config con '
            f'etiquetas>" y cópialo a mano a data/models/production/.'
        )
    print(f'Modelo cargado: {model_path}')
    return joblib.load(model_path)


def classify_scene(scene, model):
    '''
    Clasifica una escena preprocesada y devuelve el mapa de clases con la
    misma forma que las bandas. Los píxeles enmascarados (nube, sin datos)
    quedan como "sin_datos".
    '''
    height, width = scene['bands'][BAND_NAMES[0]].shape
    idx_arrays = calculate_indices(scene['bands'], INDEX_NAMES)

    stack = np.stack(
        [scene['bands'][b].ravel() for b in BAND_NAMES]
        + [idx_arrays[i].ravel() for i in INDEX_NAMES],
        axis=1,
    )
    valid = ~np.any(np.isnan(stack), axis=1)
    predictions = np.full(stack.shape[0], 'sin_datos', dtype=object)
    predictions[valid] = model.predict(stack[valid])
    return predictions.reshape(height, width)


def class_composition(classification_map):
    '''Porcentaje de píxeles de cada clase, excluyendo los enmascarados.'''
    classes, counts = np.unique(classification_map, return_counts=True)
    keep = classes != 'sin_datos'
    classes, counts = classes[keep], counts[keep]
    total = counts.sum()
    if total == 0:
        return {}
    return {c: round(n / total * 100, 2) for c, n in zip(classes, counts)}


if __name__ == '__main__':
    import argparse
    import sys
    import yaml

    sys.path.insert(0, str(Path(__file__).parent))
    from preprocessor import preprocess
    from paths import zone_from_config, zone_scene_dirs

    parser = argparse.ArgumentParser(
        description='Entrena un clasificador de cobertura terrestre en data/models/ '
                    '(zona de pruebas). El repositorio ya incluye uno de producción '
                    '(data/models/production/rf_prod.joblib); esto solo hace falta '
                    'si quieres entrenar el tuyo propio.'
    )
    parser.add_argument('--config', required=True,
                        help='Config YAML con classifier.labels_path y classifier.reference_scene')
    parser.add_argument('--name', default=None,
                        help='Nombre del modelo de salida en data/models/ (por defecto, "rf")')
    parser.add_argument('--force', action='store_true',
                        help='Sobrescribe el modelo si ya existe')
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    clf_cfg = cfg.get('classifier') or {}
    missing = [k for k in ('labels_path', 'reference_scene') if not clf_cfg.get(k)]
    if missing:
        print(f'El config {args.config} no sirve para entrenar: falta classifier.{", classifier.".join(missing)}')
        print('Solo las zonas con etiquetas manuales pueden entrenar un modelo.')
        sys.exit(1)

    zone = zone_from_config(args.config)
    reference_tag = clf_cfg['reference_scene']

    # Solo se preprocesa la escena de referencia: es la única que se usa para
    # entrenar, y preprocesar la serie entera consumiría memoria para nada.
    scene_dirs = zone_scene_dirs(zone)
    reference_dir = next((sd for sd in scene_dirs if reference_tag in sd.name), None)
    if reference_dir is None:
        print(f'No se encontró la escena de referencia "{reference_tag}" entre las {len(scene_dirs)} de la zona "{zone}".')
        sys.exit(1)

    print(f'Preprocesando escena de referencia: {reference_dir.name}')
    scene = preprocess(reference_dir, cfg)
    scene['indices'] = calculate_indices(scene['bands'], cfg.get('indices', INDEX_NAMES))

    # Fijo, no lee classifier.model_name del config: esa clave dice qué modelo
    # de producción usa el pipeline, no qué nombre debe tener un entrenamiento
    # de pruebas nuevo — son cosas distintas aunque compartan config.
    model_name = args.name or 'rf'
    train(scene, cfg, model_name=model_name, force=args.force)
