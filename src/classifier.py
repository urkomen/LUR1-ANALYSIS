from pathlib import Path

import geopandas as gpd
import joblib
import numpy as np
from rasterio.transform import rowcol
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.model_selection import train_test_split

from indices import calculate_indices

BAND_NAMES = ['B02', 'B03', 'B04', 'B05', 'B08', 'B11', 'B12']
INDEX_NAMES = ['NDVI', 'NDWI', 'MNDWI']
FEATURE_NAMES = BAND_NAMES + INDEX_NAMES


def extract_features(scene, labels_path):
    '''
    Extrae el vector de 10 features (7 bandas + 3 índices) para cada punto
    etiquetado que cae dentro de la escena. Descarta puntos fuera del recorte
    o sobre píxeles enmascarados (nube/sin datos).
    Devuelve X (n_muestras, 10), y (etiquetas de clase) y coords (x, y en CRS de la escena).
    '''
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
    '''
    Divide el área de estudio en bloques cuadrados de block_size_m y asigna
    bloques completos (no píxeles individuales) a train o test, estratificando
    por la clase mayoritaria de cada bloque. Evita que píxeles vecinos —
    espectralmente casi idénticos por autocorrelación espacial — se repartan
    entre train y test e inflen las métricas de forma artificial.
    '''
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


def train_classifier(X_train, y_train, random_state):
    '''Entrena un RandomForestClassifier sobre los features de train.'''
    model = RandomForestClassifier(n_estimators=200, random_state=random_state)
    model.fit(X_train, y_train)
    return model


def evaluate_classifier(model, X_test, y_test):
    '''
    Evalúa el modelo sobre test: accuracy global, F1 por clase (weighted y
    macro) y matriz de confusión. Devuelve un dict con las métricas.
    '''
    y_pred = model.predict(X_test)
    accuracy = model.score(X_test, y_test)
    f1_weighted = f1_score(y_test, y_pred, average='weighted')
    f1_macro = f1_score(y_test, y_pred, average='macro')
    labels_sorted = sorted(np.unique(np.concatenate([y_test, y_pred])))
    matrix = confusion_matrix(y_test, y_pred, labels=labels_sorted)

    print(f'  Accuracy: {accuracy:.3f}')
    print(f'  F1 (weighted): {f1_weighted:.3f}')
    print(f'  F1 (macro): {f1_macro:.3f}')
    print(f'  Clases: {labels_sorted}')
    print(f'  Matriz de confusión:\n{matrix}')

    return {
        'accuracy': accuracy,
        'f1_weighted': f1_weighted,
        'f1_macro': f1_macro,
        'labels': labels_sorted,
        'confusion_matrix': matrix,
    }


def classify(scenes, config):
    '''
    Extrae features de la escena de referencia, entrena un Random Forest con
    split espacial train/test y guarda el modelo entrenado en data/models/.
    Devuelve el modelo y las métricas de evaluación.
    '''
    clf_config = config['classifier']
    reference_tag = clf_config['reference_scene']

    scene = next(
        (s for s in scenes if reference_tag in s['scene_dir']),
        None,
    )
    if scene is None:
        print(f'  No se encontró la escena de referencia ({reference_tag}) entre las procesadas.')
        return None, None

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
    model = train_classifier(X_train, y_train, clf_config['random_state'])

    print('Evaluando sobre test...')
    metrics = evaluate_classifier(model, X_test, y_test)

    model_path = Path('data/models/rf_costa_vasca.joblib')
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    print(f'Modelo guardado en: {model_path}')

    return model, metrics
