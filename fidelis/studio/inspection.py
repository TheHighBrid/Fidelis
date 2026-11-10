"""Read-only native pixel crops. Coordinates are never resampled or wrapped."""
import numpy as np

MAX_CROP_SIDE = 512


def crop_bounds(shape, *, x, y, width, height):
    """Validate the complete rectangle before slicing a mapped RGB artifact."""
    if any(type(value) is not int for value in (x, y, width, height)):
        raise ValueError('Crop coordinates and dimensions must be integers')
    if x < 0 or y < 0 or not 1 <= width <= MAX_CROP_SIDE or not 1 <= height <= MAX_CROP_SIDE:
        raise ValueError('Crop origin must be nonnegative and sides must be 1..512 pixels')
    if x + width > shape[1] or y + height > shape[0]:
        raise ValueError('Crop extends outside the original image')
    return x, y, width, height


def native_crop(array, **rectangle):
    x, y, width, height = crop_bounds(array.shape, **rectangle)
    return np.array(array[y:y+height, x:x+width], copy=True, order='C')
