"""The common module contains common variables, functions and classes used by the other modules.
"""
#
# variables, functions, and classes used by the other modules
#
###############################################################################################################
# Segment-based library file information. Only need when turn segment-based library to tile-based library
###############################################################################################################
# segment library mat file main name
# segMatFileMainName = 'SLIE_segment'
segMatFileMainName = 'fldpln_segment'
# columns in the segment .mat file, can also be read from the mat file
matRelVarName='fldpln' # variable name storing the FSP-FPP relations in the mat file
# matRelColumnNames = ["FSP_x", "FSP_y", "floodplain_pixel_x", "floodplain_pixel_y", "DTF", "DTF_fill_depth"] # for FLDPLN v6
matRelColumnNames = ["FSP_x", "FSP_y", "floodplain_pixel_x", "floodplain_pixel_y", "DTF", "sink_fill_depth"] # changed on 7/1/24 to reflect changes in FLDPLN v8

# FSP info CSV file: 
fspInfoFileName = 'fsp_info.csv'
fspInfoColumnNames= ['FspId','FspX','FspY','SegId','FilledElev','DsDist','StrOrd'] # initial columns are: 'FspId','FspX','FspY','SegId','FilledElev'
# they were:
# fspFileName = "fsp_info.csv"
# fspColumnNames = ['FspId','FspX','FspY','SegId','FilledElev','DsDist','StrOrd']

# Segment info CSV file:
segInfoFileName = "segment_info.csv"
segInfoColumnNames = ['SegId','CellCount','DsSegId','StFac','EdFac','Length', 'DsDist','StrOrd'] # initial columns are: 'SegId','CellCount','DsSegId','StFac','EdFac'
# column types and schema for creating segment shapefiles
segColSchema = {'SegId':'int32:10','CellCount':'int32:10','DsSegId':'int32:10','StFac':'int32:10','EdFac':'int32:10','Length':'float:15.3', 'DsDist':'float:15.3','StrOrd':'int32:10'}
# they were:
# segFileName = "segment_info.csv"
# segColumnNames = ['SegId','CellCount','DsSegId','Length','DsDist','StrOrd']

# segment library .prj file name
prjFileName = 'lib.prj'

############################################################################################################
# Tile-based library file information. Need to map a library
############################################################################################################
# meta data: cell size and spatial reference
metaDataFileName = 'TileCellSizeSpatialReference.json'

# tile file main name and FSP-FPP relation columnNames
tileFileMainName = 'FLDPLN_tiled'
relColumnNames = ["FspId", "FppCol", "FppRow", "Dtf", "FilledDepth"]

# FSP-tile index file and its column names
fspTileIndexFileName = f"{tileFileMainName}_fsp_index.csv"
fspIdxColumnNames=['TileId','FspId', 'MinDtf', 'MaxDtf'] # DTF--"FSP's depth" to flood a FPP

# Tile index file and its column names
tileIndexFileName = f"{tileFileMainName}_tile_index.csv"
tileIdxColumnNames=['TileId','TileMinX','TileMaxX','TileMinY','TileMaxY','FppMinX','FppMaxX','FppMinY','FppMaxY','FspMinX','FspMaxX','FspMinY','FspMaxY','MinDtf','MaxDtf','NumOfRels','NumOfFpps']

# # Segment shapefile columns for manually assign segment stream order
# segShpColumnNames = ['geometry','LibName','SegId','StrOrd'] # stream order has to be defined manually!

# Stream order column name in FSP and segment info CSV files
strOrdColName = 'StrOrd'

# Stream-order network information file for DOF interpolation
strOrdNetFileName = 'stream_order_info.csv' # was strOrdFileName
strOrdNetColumnNames = ['StrOrd', 'DsStrOrd', 'JunctionFspX', 'JunctionFspY'] # was strOrdColumnNames