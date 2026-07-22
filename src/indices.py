import numpy as np


def ndvi(nir, red):
    '''
    Normalized Difference Vegetation Index.
    Fórmula: (B08 - B04) / (B08 + B04)
    Rango: -1 a 1. Vegetación sana > 0.3, suelo ~0, agua < 0.
    '''
    nir = nir.astype(np.float32)
    red = red.astype(np.float32)
    denom = nir + red
    result = np.where(denom != 0, (nir - red) / denom, np.nan)
    return result.astype(np.float32)


def ndwi(green, nir):
    '''
    Normalized Difference Water Index.
    Fórmula: (B03 - B08) / (B03 + B08)
    Rango: -1 a 1. Agua > 0, vegetación < 0.
    '''
    green = green.astype(np.float32)
    nir = nir.astype(np.float32)
    denom = green + nir
    result = np.where(denom != 0, (green - nir) / denom, np.nan)
    return result.astype(np.float32)


def mndwi(green, swir):
    '''
    Modified Normalized Difference Water Index.
    Fórmula: (B03 - B11) / (B03 + B11)
    Rango: -1 a 1. Más preciso que NDWI en zonas costeras y urbanas.
    '''
    green = green.astype(np.float32)
    swir = swir.astype(np.float32)
    denom = green + swir
    result = np.where(denom != 0, (green - swir) / denom, np.nan)
    return result.astype(np.float32)


def calculate_indices(bands, index_list):
    '''
    Calcula los índices especificados en index_list a partir del dict de bandas.
    Devuelve dict con un array por índice.
    '''
    calculators = {
        'NDVI':  lambda b: ndvi(b['B08'], b['B04']),
        'NDWI':  lambda b: ndwi(b['B03'], b['B08']),
        'MNDWI': lambda b: mndwi(b['B03'], b['B11']),
    }
    result = {}
    for name in index_list:
        if name not in calculators:
            print(f'  Índice desconocido, omitiendo: {name}')
            continue
        result[name] = calculators[name](bands)
        print(f'  {name} calculado — rango: {np.nanmin(result[name]):.3f} a {np.nanmax(result[name]):.3f}')
    return result
