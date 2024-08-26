"""Module to re-organize FLDPLN segment-based library into tile-based library for fast mapping.
"""

#
# imports
#
# imports from Python standard libraries
import os
import math
import glob
import shutil
import json
# for downloading segment-based library files
import zipfile
import urllib.request
import re

# imports from third-party libraries
import numpy as np
import pandas as pd
import geopandas as gpd
import scipy.io as sio # imports loadmat, savemat
import h5py # for reading some .mat file
from shapely.geometry import LineString

# import the common module from THIS package
from .common import *

############################################################################################################################################
# Functions--convert segment-based library to tiled library
############################################################################################################################################

############################################################################################################################################
def TileLibrary(segLibFolder, cellSize, tiledLibFolder, tileSize, fileFormat):
    """ Tile a library. Turn segment-based FSP-FPP relations to tile-based. Note that 'snappy' format needs to install the 'fastparquet' python package

        Args:
            segLibFolder (str): folder containing the segment-based library.
            cellSize (float): cell size in meters.
            tiledLibFolder (str): folder for the tiled library.
            tileSize (int): number of cells in a tile.
            fileFormat (str): 'snappy' or 'mat'.

        Return:
            dict: metadata of the tiled library
    """
    #     Parameters:
    #         segLibFolder: folder containing the segment-based library
    #         cellSize: cell size in meters
    #         tiledLibFolder: folder for the tiled library
    #         tileSize: number of cells in a tile
    #         fileFormat: 'snappy' or 'mat'. 'snappy' format needs to install the 'fastparquet' python package
    #     Return: metadata of the tiled library
    # """
    # This function uses the fsp_info.csv file (under tiledLibFolder) to get FSP IDs
    # fileFormat: 'snappy' or 'mat'. 'snappy' format needs to install the 'fastparquet' python package
    # tileSize changed to the number of cells on May 27, 2024 to avoid partial cells within a tile and also works for GCS system

    # create the tiledLibFolder folder for all tiled libraries if it doesn't exist
    os.makedirs(tiledLibFolder,exist_ok=True)

    # 
    # copy FSP and segment info CSV files to tiled library folder
    # 
    shutil.copyfile(os.path.join(segLibFolder, fspInfoFileName), os.path.join(tiledLibFolder, fspInfoFileName))
    shutil.copyfile(os.path.join(segLibFolder, segInfoFileName), os.path.join(tiledLibFolder, segInfoFileName))

    #
    # save tile size, cell size and spatial reference in a metadata file 
    #
    # read in spatial reference for the library
    srFile = os.path.join(segLibFolder,prjFileName)
    with open(srFile, 'r') as srf:
        srText = srf.read()
    metaData = {'TileSize': tileSize, 'CellSize': cellSize, 'SpatialReference': srText}
    # save metedata
    with open(os.path.join(tiledLibFolder, metaDataFileName), 'w') as jf:
        json.dump(metaData,jf)

    #
    # calculate library and segment extents
    libExt, segExts = CalculateLibraryExtent(segLibFolder,cellSize)
    minX,maxX,minY,maxY = libExt

    # Calculate tile boundaries
    tb = CalculateTileBoundary(minX,maxX,minY,maxY,tileSize*cellSize,tileSize*cellSize)
    print('Number of (possible) tiles:', len(tb))
    print('Tile extents:\n', tb, '\n')

    #
    # Create tiles
    #
    print('Build tiles (tiling FSP-FPP relations) ...')
    hcs = cellSize/2
    # read in FSP ID and coordinates
    # need to set float_precision='round_trip' to prevent rounding while reading the text file! float_precision='high' DOESN'T work.
    # For Verdigris 10-m library, FSP ID of 22246, its FspX of -1003.7918248322967 in fsp_info.csv was read into memory as -1003.7918248322968 without using float_precision='round_trip'
    fspIds = pd.read_csv(os.path.join(segLibFolder,fspInfoFileName),float_precision='round_trip',index_col=False)[['FspId','FspX','FspY']]

    # initialize the index DFs and tile ID
    fspIdxDf = pd.DataFrame(columns=fspIdxColumnNames)
    tileIdxDf = pd.DataFrame(columns=tileIdxColumnNames)
    tileId = 1
    for t in tb:
        print('Processing tile: ', tileId)

        # tile boundary, not the cell center boundary!
        tminX, tmaxX,tminY, tmaxY = t
        print('Tile extent (minX, maxX, minY, maxY) :',(tminX, tmaxX,tminY, tmaxY))

        # find the segments that intersect the tile rectangle
        segs = segExts[~((segExts['MinX']>tmaxX) | (segExts['MaxX']<tminX))] # rectangles are NOT on left or right of each other
        segs = segs[~((segs['MinY']>tmaxY) | (segs['MaxY']<tminY))] # rectangles are NOT on top or bottom of each other
        segs = segs['FileName'].to_list()
        print('Number of segments interseting with the tile: ', len(segs))

        # find the FPP-FSP relations in the tile from all the intersecting segments
        # Initialize the df
        tdf = pd.DataFrame()
        for mf in segs: #segMatFileFullNames:
            # read mat file
            matVar = ReadMatFile(mf,matRelVarName)
            # converting array to a dataframe
            sdf = pd.DataFrame(matVar, columns=matRelColumnNames)

            # rename columns to better names
            betterColumnNames = ["FspX", "FspY", "FppX", "FppY", "Dtf", "FilledDepth"]
            d=dict(zip(matRelColumnNames,betterColumnNames))
            sdf.rename(columns=d,inplace=True) # inplace changing column name
        
            # Code used to find out which segment file (e.g., SLIE_segment40.mat) in library 'midkan" has problem 
            # where column “DTF + fill depth” is LESS than the "DTF" column
            # t  =  sdf['FilledDepth'] - sdf['Dtf']
            # t  =  t < -0.1
            # if t.any():
            #     print('Segment: ', mf)
            #     print(f'Found negative depression in {mf}!')

            # select the FPPs within the tile
            sdf = sdf[(sdf['FppX']>=tminX) & (sdf['FppX']<=tmaxX) & (sdf['FppY']>=tminY) & (sdf['FppY']<=tmaxY)].copy() # tell pandas we want a copy to avoid "SettingWithCopyWarning" in line 86 when there is only one segment mat file read
            # print('Segment:', segId, 'Number of FSP-FPP relations:', len(sdf))
            if tdf.empty:
                tdf = sdf
            else:
                # tdf = tdf.append(sdf)
                tdf = pd.concat([tdf, sdf])
        print('Total number of FSP-FPP relations in the tile:', len(tdf))
               
        # save the FSP-FPP relations and update the index dfs
        if (not (tdf.empty)) and (len(tdf) != 0): # there are some FPPs in the tile
            # #calculate FilledDepth
            # tdf['FilledDepth'] = tdf['FilledDepth']-tdf['Dtf'] # This is NOT necessary as FLDPLN model output changed to save "sink fill depth" in v8. Modified by Xingong on 7/1/24

            # Calculate FSP center extent for the tile
            fspMinX = tdf['FspX'].min()
            fspMaxX = tdf['FspX'].max()
            fspMinY = tdf['FspY'].min()
            fspMaxY = tdf['FspY'].max()
            
            # Calculate FPP center extent within the tile
            fppMinX = tdf['FppX'].min()
            fppMaxX = tdf['FppX'].max()
            fppMinY = tdf['FppY'].min()
            fppMaxY = tdf['FppY'].max()
            
            # turn FPP coordinates into row and column within the tile
            # Note that the row and column start at (fppMinX, fppMaxY)!
            tdf['FppX'] = ((tdf.FppX-fppMinX)/cellSize).round()
            tdf['FppY'] = ((fppMaxY-tdf.FppY)/cellSize).round()
            # tdf['FppIdx'] = tdf.FppX * tRows + tdf.FppY

            # rename ['FppX','FppY'] to ['Col','Row']
            tdf.rename(columns={'FppX':'FppCol','FppY':'FppRow'},inplace=True)

            # merge relations with FSP IDs
            tdf = tdf.merge(fspIds,how='left',on=['FspX','FspY'])

            # # check FSP IDs
            # if tdf.isnull().values.any():
            #     print('There are NAN in the dataframe!')

            # remove FspX & FspY
            tdf.drop(['FspX','FspY'],axis=1,inplace=True)

            # reorder columns
            tdf = tdf[relColumnNames]

            # set datatypes for the columns
            tdf=tdf.astype(dtype={"FspId":np.int32, "FppCol":np.int32, "FppRow":np.int32, "Dtf":np.float32, "FilledDepth":np.float32},copy=False)
            # convert float64 to float32 before saving and create index on FspX and FspY for speed up merge during mapping
            # tdf.astype(np.float32,copy=False).set_index(keys=['FspX','FspY'],inplace=True)

            # save the relations in the tile in a file
            print('Saving FSP-FPP relations in a file...')
            if fileFormat == 'snappy':
                # filePathName = os.path.join(segLibFolder, tileFileMainName+'_'+str(tileId)+'.gzip') # for gzip format
                filePathName = os.path.join(tiledLibFolder, tileFileMainName+'_'+str(tileId)+'.snz') # for snappy format
                
                # save to parquet file. Can only save one DataFrame!
                # tdf.to_parquet(filePathName,engine='fastparquet',compression='gzip',index=False) # gzip
                tdf.to_parquet(filePathName,engine='fastparquet',compression='snappy',index=False) # snappy fast processing
                # tdf.to_parquet(filePathName,engine='fastparquet',compression='snappy',index=True) # snappy fast processing
            elif fileFormat == 'mat':
                # separate columns by datatypes (int32 and float32)
                fspFppsArray = tdf[relColumnNames[0:3]].to_numpy(dtype=np.int32)
                dtfFilledDepthArray = tdf[relColumnNames[-2::]].to_numpy(dtype=np.float32)
                # Save to compressed .mat file
                dfDic = {'FspFpps': fspFppsArray,'DtfFilledDepth': dtfFilledDepthArray}
                # Tile cannot be too large which may cause failure in writing into .mat file. See https://github.com/scipy/scipy/issues/12465
                filePathName = os.path.join(tiledLibFolder, tileFileMainName+'_'+str(tileId)+'.mat')
                sio.savemat(filePathName, dfDic, do_compression=True) 
            else:
                print('Unsupported file format!')
                return

            # calculate the min and max DTF for each FSPs in the tile
            fspDf = tdf.groupby(['FspId'], as_index=False).agg(MinDtf = ('Dtf', min),MaxDtf = ('Dtf', max))
            print('Number of unique FSPs in the tile:', len(fspDf))
            # print(fspDf)
            
            # add tile ID to fsp-tile index
            fspDf['TileId'] = tileId
            # reorder columns
            fspDf = fspDf[fspIdxColumnNames]
            # append to the index table
            # fspIdxDf = fspIdxDf.append(fspDf,ignore_index=True)
            fspIdxDf = pd.concat([fspIdxDf, fspDf], ignore_index=True)
            # print('Fsp-Tile index for the tile:')
            # print(fspIdxDf)

            # Calculate FSP & FPP external extents for saving in the tile-index file
            fspMinX,fspMaxX,fspMinY,fspMaxY = fspMinX-hcs,fspMaxX+hcs,fspMinY-hcs,fspMaxY+hcs
            fppMinX,fppMaxX,fppMinY,fppMaxY = fppMinX-hcs,fppMaxX+hcs,fppMinY-hcs,fppMaxY+hcs
            print('Tile FSP extent (fspMinX,fspMaxX,fspMinY,fspMaxY): ', (fspMinX,fspMaxX,fspMinY,fspMaxY))
            print('Tile FPP extent (fppMinX,fppMaxX,fppMinY,fppMaxY): ', (fppMinX,fppMaxX,fppMinY,fppMaxY))

            # Calculate the min & max DTF within the tile
            minTileDtf = fspDf['MinDtf'].min()
            maxTileDtf = fspDf['MaxDtf'].max()

            # calculate number of relations and number of FPPs in the tile
            numOfRels = len(tdf)
            numOfFpps = len(tdf[['FppCol','FppRow']].drop_duplicates()) # groupby for fast?
            
            # add tile ID and additional tile-related info to the tile index file
            tileIdx = pd.DataFrame([[tileId,tminX,tmaxX,tminY,tmaxY,fppMinX,fppMaxX,fppMinY,fppMaxY,fspMinX,fspMaxX,fspMinY,fspMaxY,minTileDtf,maxTileDtf,numOfRels,numOfFpps]],columns=tileIdxColumnNames)
            # append to the index table
            # tileIdxDf = tileIdxDf.append(tileIdx,ignore_index=True)
            tileIdxDf = pd.concat([tileIdxDf, tileIdx],ignore_index=True)
            # print('Tile index for the tile:')
            # print(tileIdxDf)

            # move to the next tile
            tileId +=1

    # Save the index as a file
    # print('Number of items in the fsp-tile index:', len(fspIdxDf))
    # print('fsp-tile Index table:\n',fspIdxDf)
    # save index to a csv file
    print('Save fsp-tile index as a CSV file ...')
    fspIdxDf.to_csv(os.path.join(tiledLibFolder, tileFileMainName+'_fsp_index.csv'),index=False)

    # print('Number of items in the tile-extent index:', len(tileIdxDf))
    # print('Tile index table:\n',tileIdxDf)
    # save index to a csv file
    print('Save tile index as a CSV file ...')
    tileIdxDf.to_csv(os.path.join(tiledLibFolder, tileFileMainName+'_tile_index.csv'),index=False)

    return metaData

############################################################################################################################################
def CalculateTileBoundary(minX, maxX, minY, maxY, tileSizeX, tileSizeY, padding=True):
    """ Calculate each tile's boundary as (minX, maxX,minY, maxY).
        Args:
            minX (float): min x of the external border (not the cell center) coordinates of the area needs to be tiled.
            maxX (float): max x of the external border (not the cell center) coordinates of the area needs to be tiled.
            minY (float): min y of the external border (not the cell center) coordinates of the area needs to be tiled.
            maxY (float): max y of the external border (not the cell center) coordinates of the area needs to be tiled.
            tileSizeX (float): tile external border size (not the cell center size) in x axis.
            tileSizeY (float): tile external border size (not the cell center size) in y axis.
            padding (bool): whether the tiles have the same size and not reduced to the border of the tiled area. Default is True.
        Return:
            list: list of tile boundaries of (minX, maxX,minY, maxY)
    """

    # helper function to generate tile boundary in one dimension
    def TileInOneDimension(min, max, tileSize, padding=True):
        # generate tile marker coordinates
        bs = np.arange(min, max, tileSize)
        # handle the last coordinate as np.arange() is inclusive
        if padding: #all the tiles have the same length whether it's outside the border of the tiled area or not
            bs = np.append(bs, bs[-1]+tileSize)
        else: # the last tile stops at the border of the area
            bs = np.append(bs, max)

        # generate tile border coordinate pairs
        tb = [(bs[t], bs[t+1]) for t in range(bs.size-1)]
        return tb
        
    xb = TileInOneDimension(minX,maxX,tileSizeX,padding)
    yb = TileInOneDimension(minY,maxY,tileSizeY,padding)
    tb = [(x, y) for x in xb for y in yb] # in ((minX, maxX),(minY, maxY))
    # convert to (minX, maxX,minY, maxY)
    tb = [(minX, maxX,minY, maxY) for ((minX,maxX),(minY,maxY)) in tb]
    return tb

############################################################################################################################################
def CalculateLibraryExtent(segLibFolder, cellSize):
    """ Calculate library external border extent. Also calculate segment extents (FPP cell center) and save them in a data frame.
        Args:
            segLibFolder (str): folder containing the segment-based library.
            cellSize (float): cell size in meters.
        Return:
            tuple: external border extent (minX, maxX,minY, maxY), segment extent data frame of ['MinX','MaxX','MinY','MaxY','FileName'] (FPP cell center)
    """

    # Get all the segment mat files in the library/watershed
    segMatFileFullNames = glob.glob(os.path.join(segLibFolder, segMatFileMainName+'*.mat'))
    hcs = cellSize/2

    # initialize extent
    minX,maxX,minY,maxY = (math.inf,-math.inf,math.inf,-math.inf)
    relNum = 0 # number of FSP-FPP relation
    segExts = pd.DataFrame(columns=['MinX','MaxX','MinY','MaxY','FileName']) # empty df storing each segment's FPP extent and corresponding mat file name
    # update the extent by all the segments
    print('Calculate library extent ...')
    for mf in segMatFileFullNames:
        # read mat file
        matVar = ReadMatFile(mf,matRelVarName)
        # converting array to a dataframe
        df = pd.DataFrame(matVar, columns=matRelColumnNames)

        relNum += len(df)
        # print('Segment:', segId, 'Number of FSP-FPP relations:', len(df))

        # Calculate segment external border extent
        sminX = df['floodplain_pixel_x'].min()-hcs
        sminY = df['floodplain_pixel_y'].min()-hcs
        smaxX = df['floodplain_pixel_x'].max()+hcs
        smaxY = df['floodplain_pixel_y'].max()+hcs
        segExt= pd.DataFrame([[sminX,smaxX,sminY,smaxY,mf]],columns=['MinX','MaxX','MinY','MaxY','FileName'])
        # add the segment extent to the df
        # segExts = segExts.append(segExt)
        segExts = pd.concat([segExts,segExt])

        #update library extent
        if sminX < minX: minX = sminX
        if sminY < minY: minY = sminY
        if smaxX > maxX: maxX = smaxX
        if smaxY > maxY: maxY = smaxY
 
    print('Library external border extent (minX, maxX, minY, maxY) :',(minX, maxX,minY, maxY))
    # print('Library segment FPP extents:\n', segExts)
    print('Total number of FSP-FPP relations:', relNum)
    
    return (minX, maxX,minY, maxY), segExts 

############################################################################################################################################
def ReadMatFile(matFile, varName):
    """ Read matlab files with different versions. scipy.io DOES NOT support MATLAB files version 7.3 yet! Some of the libraries are in 7.3 while the others are not.
        Args:
            matFile (str): matlab file name.
            varName (str): variable name in the matlab file.
        Return:
            data frame: variable matrix in the matlab file.
    """

    try: 
        # load the segment FSP-FPP-DTF table in mat file as < 7.3. 
        vars = sio.loadmat(matFile)
        var = vars[varName]
    except NotImplementedError:
        vars = {}
        f = h5py.File(matFile,'r')
        for k, v in f.items():
            vars[k] = np.array(v)
        # get the variable and transpose it for dataframe!
        var = vars[varName].transpose()
    except:
        ValueError('Could not read the mat file at all...')
        var = None

    return var

############################################################################################################################################
# Functions--clean up and calculate FSP and segment downstream distance
############################################################################################################################################

def CalculateFspSegmentDownstreamDistance(libFolder,libName):
    """ Cleanup segments (some segments don't exist in FSPs) and save library FSP and segment information as two csv files (fsp_info.csv & segment_info.csv). 
        It reads in the SpatialReference.prj and save it in CellSizeSpatialReference.json. For stage interpolation, it also calculates FSP and segment 
        downstream distance (i.e., distance to library outlet(s)) which involves:

            1. Calculate FSP's within-segment downstream distance
            2. Calculate segment length which is more accurate than "CellCount" * cell size
            3. Calculate segment's downstream distance (to watershed outlet) for speeding up 
            4. Calculate FSP's downstream distance

        Note that FSPs and segments are based on raster cell centers. Segment and its downstream segment has a gap (1 cell or sqrt(2) cell).

        Args:
            libFolder (str): folder containing the library.
            libName (str): library name.

        Return:
            tuple: FSP data frame. segment data frame.
    """
   
    #
    # read in fsp (flood source pixel) and segment network info Excel files
    #
    # fspInfoColumnNames = ['FspX','FspY','SegId','FilledElev'], columns 'DsDist' will be calculated by this function
    # segInfoColumnNames = ['SegId','CellCount','DsSegId', 'StFac','EdFac'], columns 'Length','DsDist' will be added by this function
    fspInfoFile = os.path.join(libFolder, libName, fspInfoFileName)
    segInfoFile = os.path.join(libFolder, libName, segInfoFileName)
 

    # read in FSP ID and coordinates
    # need to set float_precision='round_trip' to prevent rounding while reading the text file! float_precision='high' DOESN'T work.
    # For Verdigris 10-m library, FSP ID of 22246, its FspX of -1003.7918248322967 in fsp_info.csv was read into memory as -1003.7918248322968 without using float_precision='round_trip'
    fspDf = pd.read_csv(fspInfoFile,float_precision='round_trip',index_col=False)
    segDf = pd.read_csv(segInfoFile,float_precision='round_trip',index_col=False)

    #
    # Clean up the segment table.
    # 1. Remove the segment if it's not in the FSP table
    # 2. If the missing segment is the downstream segment of another segment, set it as 0. 
    # Those missing segments are usually because of they are close to or in waterbodies. 
    # By removing those segment, a library may have several separate watersheds/outlets!
    #
    # get the segment IDs
    segIds = segDf['SegId'].to_list()
    for sid in segIds:
        fsps = fspDf[fspDf['SegId']==sid]
        if len(fsps)==0:
            # segment not found in the FSP table. delete the row
            segDf = segDf.loc[segDf['SegId']!=sid]
            # set downstream segment ID to 0
            segDf.loc[segDf['DsSegId']==sid,'DsSegId'] = 0

    #
    # Calculate FSP within-segment distance, segment length, and segment dowstream distance, and FSP downstream distance
    #
    # add field for FSP within-segment distance
    fspDf['DsDist'] = 0.0
    # add field for segment length
    segDf['Length'] = 0.0

    # Calculate FSP within-segment DOWNSTREAM distance and segment length
    for segIdx, row in segDf.iterrows():
        segID = row['SegId']
        # print(segID)

        # select FSP on the segment
        fsps = fspDf[fspDf['SegId']==segID][['FspX','FspY']]
        
        # calculate fsp downstream within segment length
        segDist = 0.0
        if len(fsps)==0:
            # this should not happen as we have already clean up the segment table!
            print(f"Segment {segID} is missing in {fspInfoFileName}!")
        else:  
            first=True
            for idx, row in fsps[::-1].iterrows():
                # Note the idx in fsps is the index in fspDf!!!
                # calculate distance
                if first:
                    fspx1, fspy1 = row['FspX'], row['FspY']
                    dist=0.0
                    first=False
                else:
                    fspx2, fspy2 = row['FspX'], row['FspY']
                    dist=math.sqrt((fspx1-fspx2)**2+(fspy1-fspy2)**2)
                    fspx1, fspy1 = fspx2, fspy2
                segDist += dist
                fspDf.at[idx,'DsDist']=segDist

        # update segment distance in segDf
        segDf.at[segIdx,'Length'] = segDist

    # show the DFs
    # print(fspDf[:1136])
    # print(segDf)

    #
    # Calculate segment downstream length
    #
    # only for the segments that exist in the FSP table
    # But this not necessary as segments don't exist in FSP table already removed
    # Also this line will remove the segment which has just one FSP!
    # segDf = segDf[segDf['Length']>0]

    # add field for segment downstream distance for speeding up calculating FSP downstream distance
    segDf['DsDist'] = 0.0
    for segIdx, row in segDf.iterrows():
        segID = row['SegId']
        dsSegID = row['DsSegId']

        dsDist = 0.0
        while dsSegID != 0:
            # get downstream segment length and ID
            tempDf = segDf[segDf['SegId']==dsSegID][['Length','DsSegId']]
            length, segID_ds = tempDf.iat[0,0], tempDf.iat[0,1]
            dsDist += length

            # There is a GAP between two segments as they are consisted of FSP cell centers
            # Calculate the GAP and add it to segment downstream dist
            # last fsp in upstream segment
            lastFspXy = fspDf[fspDf['SegId']==segID][['FspX','FspY']].tail(1)    
            fspx1, fspy1 = lastFspXy.iat[0,0],lastFspXy.iat[0,1]
            # first FSP in downstream segment
            firstFspXy = fspDf[fspDf['SegId']==dsSegID][['FspX','FspY']].head(1)
            fspx2, fspy2 = firstFspXy.iat[0,0], firstFspXy.iat[0,1]
            dist=math.sqrt((fspx1-fspx2)**2+(fspy1-fspy2)**2)
            dsDist += dist

            # move to ownstream segment
            segID = dsSegID
            dsSegID = segID_ds

        segDf.at[segIdx,'DsDist'] = dsDist
    # print(segDf)

    # Calculate FSP downstream distance
    for idx, row in fspDf.iterrows():
        segID = row['SegId']
        inSegDist = row['DsDist']

        # get segment downstream distance
        tempDf = segDf[segDf['SegId']==segID][['DsDist']]
        segDsDist = tempDf.iat[0,0]

        # reset FSP downstream distance
        fspDf.at[idx,'DsDist'] = inSegDist + segDsDist
    # print(fspDf)

    # save the updated info files
    fspDf.to_csv(fspInfoFile,index=False,mode='w+')
    segDf.to_csv(segInfoFile,index=False,mode='w+')

    return fspDf, segDf

############################################################################################################################################
def GenerateSegmentShapefilesFromFspSegmentInfoFiles(segInfoFile, fspInfoFile, crs, outShpFile):
    """ Generate segment shapefiles from FSP and segment info files.

        Args:
            segInfoFile (str): segment info file.
            fspInfoFile (str): FSP info file.
            crs (str): coordinate reference system.
            outShpFile (str): output shapefile.

        Return: 
            None
     """

    # read in FSP ID and coordinates
    # need to set float_precision='round_trip' to prevent rounding while reading the text file! float_precision='high' DOESN'T work.
    # For Verdigris 10-m library, FSP ID of 22246, its FspX of -1003.7918248322967 in fsp_info.csv was read into memory as -1003.7918248322968 without using float_precision='round_trip'
    # read column names
    segColNames = pd.read_csv(segInfoFile, index_col=0, nrows=0).columns.tolist()
    # read in all the segments
    segDf = pd.read_csv(segInfoFile,float_precision='round_trip',index_col=False)

    # read in FSP's SegId and its coordinates
    fspDf = pd.read_csv(fspInfoFile,float_precision='round_trip',index_col=False)[['SegId','FspX','FspY']]

    # Create segment geometry list using FSP coordinates on a segment
    segGeometry = []
    for row in segDf.itertuples(): # itertuples() is the fastest way of iterating a df
        segID,dsSegID = (getattr(row,'SegId'),getattr(row,'DsSegId'))

        # select FSP on the segment
        fsps = fspDf[fspDf['SegId']==segID][['FspX','FspY']]
            
        # There is a GAP between two segments as they are consisted of FSP cell centers
        # Upstream sgements are EXTENDED to the first FSP of the downstream segment!
        if dsSegID != 0:
            # first FSP in downstream segment
            firstFspXy = fspDf[fspDf['SegId']==dsSegID][['FspX','FspY']].head(1)
            # append to the fsps
            # fsps = fsps.append(firstFspXy)
            fsps = pd.concat([fsps,firstFspXy])
        # print(fsps)

        # turn the FSPs into a LineString
        # create Points, a GeometryArray, from fsps
        points = gpd.points_from_xy(fsps['FspX'],fsps['FspY'])
        segLineStr = LineString(points)
        # print(segLineStr)

        # Insert the line into the geometry list
        segGeometry.append(segLineStr)

    # create a geodataframe for writing shapefile
    libSegs = gpd.GeoDataFrame(segDf, crs=crs, geometry=segGeometry)

    # Write the data into that Shapefile
    schema = gpd.io.file.infer_schema(libSegs)
    for c in segColNames:
        schema['properties'][c] = segColSchema[c]
    libSegs.to_file(outShpFile, driver= "ESRI Shapefile",schema=schema) # existing shapefile will be replaced automatically!!!

    return #libSegs

############################################################################################################################################
def GetStreamOrdersForFspsSegments(libFolder,strOrdShpFile,shpSegIdName,shpStrOrdColName):
    """ Get stream order for FSPs and segments from segment stream order shapefile and save them in fsp_info.csv and segment_info.csv files. 
        It also creates file stream_order_info.csv which stores the network info at the level of stream orders for FSP DOF interpolation.

        Args:
            libFolder (str): library folder.
            strOrdShpFile (str): stream order shapefile.
            shpSegIdName (str): segment ID column name in the shapefile.
            shpStrOrdColName (str): stream order column name in the shapefile.

        Return:
            tuple: FSP data frame, segment data frame, stream order network data frame.
    """
     
    # get stream order from the shapefile
    shpDf = gpd.read_file(strOrdShpFile)
    
    # select columns
    streamOrderColumns = [shpSegIdName,shpStrOrdColName]
    segOrdDf = shpDf[streamOrderColumns]
    # rename shp order column to 'StrOrd'
    segOrdDf = segOrdDf.rename(columns={shpSegIdName: 'SegId', shpStrOrdColName: strOrdColName})
    # print(segOrdDf)
   
    # read fsp and segment info csv files
    fspCsvFile = os.path.join(libFolder,fspInfoFileName)
    segCsvFile = os.path.join(libFolder,segInfoFileName)
    # need to set float_precision='round_trip' to prevent rounding while reading the text file! float_precision='high' DOESN'T work.
    # For Verdigris 10-m library, FSP ID of 22246, its FspX of -1003.7918248322967 in fsp_info.csv was read into memory as -1003.7918248322968 without using float_precision='round_trip'
    fspDf = pd.read_csv(fspCsvFile,float_precision='round_trip',index_col=False)
    segDf = pd.read_csv(segCsvFile,float_precision='round_trip',index_col=False)

    # remove existing "StrOrd" column
    if ('StrOrd' in fspDf.columns):
        fspDf.drop(['StrOrd'], axis=1,inplace=True)
    if ('StrOrd' in segDf.columns):
        segDf.drop(['StrOrd'], axis=1,inplace=True)

    # Get segment stream order by merging DFs based on segment ID
    segDf = pd.merge(segDf, segOrdDf, how='left', on='SegId')
    # print(segDf)

    # Get FSP's stream order by merging
    fspDf = pd.merge(fspDf, segOrdDf, how='left', on='SegId')
    # print(segDf)

    # save the DFs in CSVs
    fspDf.to_csv(fspCsvFile,index=False,mode='w+')
    segDf.to_csv(segCsvFile,index=False,mode='w+')

    #
    # Create another table storing stream order network information with the columns:
    # [‘StrOrd’, ‘DsStrOrd’, ‘JunctionFspX’, ‘JunctionFspY’] for use in interpolting FSP DOF
    #
    strOrdDf = pd.DataFrame(columns=strOrdNetColumnNames)
    strOrds = segDf['StrOrd'].drop_duplicates().sort_values().to_list()
    for so in strOrds:
        # find the most downstream segment in the stream order
        mostDsSeg = segDf[segDf['StrOrd']==so].sort_values('DsDist')[['DsSegId']].head(1)
        # print(mostDsSeg)
        # get its downstream segment ID
        dsSegId = mostDsSeg.iat[0,0]
        if dsSegId != 0:
            # get downstream stream order
            dsOrd = segDf[segDf['SegId']==dsSegId]['StrOrd'].iat[0]
            # get the first FSP in the downstream segment
            firstFspXy = fspDf[fspDf['SegId']==dsSegId][['FspX','FspY']].head(1)
            fspx, fspy = firstFspXy.iat[0,0], firstFspXy.iat[0,1]
        else:
            # no downstream segment
            dsOrd,fspx,fspy = 0,0,0

        # add the connectivity information to the table
        temp = pd.DataFrame([[so,dsOrd,fspx,fspy]],columns=strOrdNetColumnNames)    
        # append to the index table
        # strOrdDf = strOrdDf.append(temp,ignore_index=True)
        strOrdDf = pd.concat([strOrdDf, temp],ignore_index=True)
    
    # save the table as a CSV file
    strOrdCsvFile = os.path.join(libFolder, strOrdNetFileName)
    strOrdDf.to_csv(strOrdCsvFile,index=False)

    return fspDf, segDf, strOrdDf

############################################################################################################################################
def DownloadSegmentLibrary(segUrl, libName, localLibFolder ):
    """ Download segment-based library from the web and unzip it. Not implemented yet! 
        The zip file name may vary from library to library as the max DOF may be different for different libraries.
        For example: SLIE_KS_AOI_spring_DTF_49ft_(15m).zip, SLIE_KS_AOI_ninnescah_DTF_33ft_(10m).zip.

        Args:
            segUrl (str): URL of the segment-based library.
            libName (str): library name.
            localLibFolder (str): local folder to store the library.
        Return:
            None
    """

    # Should use import requests instead of urllib.request

    # # get the zipped segment library file name, 	
    # #
    # segUrl = segUrl+'/'+libName
    # # remove space in the URL
    # url = segUrl.replace(" ","%20")
    # # create a request
    # req = urllib.request.Request(url)
    # # open and read the HTML page
    # htmlPage = urllib.request.urlopen(req).read()
    # # turn the HTML page from byte into string
    # htmlPageStr = str(htmlPage)

    # # get segment library zip file from the HTML page
    # p1 = 'href=\"SLIE_KS_AOI_'+libName+'_DTF_\d{,3}ft_\(\d{,3}m\)\.zip\"'
    # hrefStr = re.findall(p1,str(htmlPageStr))[0]
    # p2 = 'SLIE_KS_AOI_'+libName+'_DTF_\d{,3}ft_\(\d{,3}m\)\.zip'
    # zipFile = re.findall(p2,hrefStr)[0]
    
    # # create local folder if not existing
    # os.makedirs(localLibFolder,exist_ok=True)

    # # If you need to redownload for whatever reason
    # if os.path.exists(os.path.join(localLibFolder, libName)):
    #     shutil.rmtree(os.path.join(localLibFolder, libName))
    # os.mkdir(os.path.join(localLibFolder, libName))

    # # Download base library
    # print(f'Downloading library {libName} ...')
    # urllib.request.urlretrieve(segUrl+'/'+zipFile,os.path.join(localLibFolder, libName, zipFile))
    
    # # Download FSP info Excel file
    # print("Downloading FSP Excel file ...")
    # urllib.request.urlretrieve(segUrl+'/SLIE_KS_AOI_'+libName+'_fsp_info.xlsx', 
    #     os.path.join(localLibFolder, libName, 'SLIE_KS_AOI_'+libName+'_fsp_info.xlsx'))

    # # Download segment info Excel file
    # print("Downloading segment Excel file ...") #	segment_network_info_spring.xlsx
    # urllib.request.urlretrieve(segUrl+'/segment_network_info_'+libName+'.xlsx', 
    #     os.path.join(localLibFolder, libName, 'segment_network_info_'+libName+'.xlsx'))

    # # unzip library
    # print("Unzipping ...")
    # # both shutil and zipFile do NOT support "Deflated64" or "compression type 9"
    # with zipfile.ZipFile(os.path.join(localLibFolder, libName, zipFile),'r') as zip_ref:
    #     zip_ref.extractall(os.path.join(localLibFolder, libName)) 
    # # shutil.unpack_archive(os.path.join(localLibFolder, libName, zipFile),os.path.join(localLibFolder, libName),'zip')

    # # clean up folder
    # os.remove(os.path.join(localLibFolder, libName, zipFile))
    # print("Done for "+libName)

    return