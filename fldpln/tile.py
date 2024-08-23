"""This module contains functions to tile segment-based library for fast mapping.
"""

# # imports
# from lib2to3.pgen2 import driver
# import os
# import math
# import json
# import numpy as np
# import pandas as pd
# import geopandas as gpd
# import scipy.io as sio #import loadmat, savemat
# import h5py # for reading some .mat file
# import glob
# from pyproj import CRS
# from shapely.geometry import LineString
# # from osgeo import ogr
# import zipfile
# import shutil
# import urllib.request
# import re

# import common module
from .common import *

############################################################################################################################################
# Functions--convert segment-based library to tiled library
############################################################################################################################################
#
# Tile a library. Turn segment-based FSP-FPP relations to tile-based
#
def TileLibrary(segLibFolder,cellSize,tiledLibFolder,tileSize,fileFormat):
    """Tile a library. Turn segment-based FSP-FPP relations to tile-based
    Parameters:
        segLibFolder (str): The folder containing the segment-based library.
        cellSize (float): The cell size of the library.
        tiledLibFolder (str): The folder to save the tiled library.
        tileSize (int): The size of a tile in number of cells.
        fileFormat (str): The file format to save the tile-based library. 'snappy' or 'mat'.
    """
    print('Tile a library ...')
