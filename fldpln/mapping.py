"""Module for mapping tile-based library.
"""

# imports from Python standard library
import os
from math import sqrt
import numbers
import json
import shutil
import zipfile
import urllib.request
import urllib.parse

# imports from 3rd party libraries
import numpy as np
import pandas as pd
import scipy.io as sio

import rasterio
from rasterio.merge import merge # for some reason, cannot use it as rasterio.merge.merge()!
from rasterio.io import MemoryFile

# from osgeo import ogr # import ogr # ok on desktop but not on laptop
from osgeo import gdal # import gdal # ok on desktop but not on laptop

from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

# import the common module from THIS package
from .common import *

############################################################################################################################################
# Functions
############################################################################################################################################

#
# Build folder for storing temporary file and output maps
#
def CreateFolders(outFolder,scratchFolderName='scratch',outMapFolderName='maps',removeExist=True):
    """ Create folders for storing temporary files and output maps
        Parameters:
            outFolder: output folder
            scratchFolderName: name of the folder for storing temporary files
            outMapFolderName: name of the folder for storing output maps
            removeExist: bool whether to remove existing folders
        Returns: folder names for storing output maps and temporary files
    """
    # create output folder if it doesn't exist
    os.makedirs(outFolder, exist_ok=True)

    # scratch folder
    scratchFolder = os.path.join(outFolder, scratchFolderName)
    # map output folder
    outMapFolder = os.path.join(outFolder, outMapFolderName)

    # Create the folders for storing temp and output files
    if removeExist:
        if os.path.isdir(scratchFolder): shutil.rmtree(scratchFolder)
        if os.path.isdir(outMapFolder): shutil.rmtree(outMapFolder)

    os.makedirs(scratchFolder, exist_ok=True)
    os.makedirs(outMapFolder, exist_ok=True)

    return outMapFolder,scratchFolder


#
# Join two sets of points by nearest distance
# The returned DF will have, in addition to p1df fields, a new distance field (i.e., distFieldName), plus other fields (i.e., otherColumns) copied from p2df
# Note that this function DOESN'T change p1df!
#
def NearestPoint(p1df, x1FieldName, y1FieldName, p2df, x2FieldName, y2FieldName, distFieldName='dist',otherColumns=None):
    # # make sure the input DFs have unique index so that deltaX, deltaY and p2df['Dist'] = deltaX*deltaX + deltaY*deltaY can work
    p1df.reset_index(inplace=True)
    p2df.reset_index(inplace=True)

    # Create a temp DF for storing the nearest points from p2df
    if otherColumns is None:
        cols = [distFieldName]
    else:
        cols = [distFieldName] + otherColumns
    nearestP2Df =pd.DataFrame(columns=cols)

    # find the nearest point from p2df for each point in p1df
    for row in p1df.itertuples(): # itertuples() is the fastest way of iterating a df
        # find the nearest pt2
        idx,x1,y1 = (getattr(row,'Index'),getattr(row,x1FieldName),getattr(row,y1FieldName))
        deltaX = p2df[x2FieldName]-x1
        deltaY = p2df[y2FieldName]-y1
        # calculate distance to all the points in p2df
        distDf = deltaX*deltaX + deltaY*deltaY

        # get the nearest point's index and dist
        s = distDf.sort_values().head(1)
        idxp2, dist = (s.index[0],s.values[0])
        # update dist
        dist = sqrt(dist)

        # get additional fields from p2df by index
        values = [dist] + p2df.loc[idxp2,otherColumns].values.flatten().tolist()

        # add the nearest point to the nearest point DF
        t = pd.DataFrame([values], index=[idx], columns=cols)
        # nearestP2Df = nearestP2Df.append(t,ignore_index=False)
        nearestP2Df = pd.concat([nearestP2Df,t],ignore_index=False)

    # merge p1df points with their nearest points using their index
    p1df = p1df.merge(nearestP2Df, how = 'left', left_index=True, right_index=True)

    return p1df

#
# Join two sets of points by nearest distance
# p1df will have a new distance field (i.e., distFieldName), plus other fields (i.e., otherColumns) copied from p2df
# Note that this function changes p1df. This is the only difference between this function and NearestPoint()!
# Not fully tested and might have bugs!
#
def NearestPointInPlace(p1df, x1FieldName, y1FieldName, p2df, x2FieldName, y2FieldName, distFieldName='dist', otherColumns=None):
    # # make sure the input DFs have unique index so that deltaX, deltaY and p2df['Dist'] = deltaX*deltaX + deltaY*deltaY can work
    p1df.reset_index(inplace=True)
    p2df.reset_index(inplace=True)

    # Create a temp DF for storing the nearest points from p2df
    if otherColumns is None:
        cols = [distFieldName]
    else:
        cols = [distFieldName] + otherColumns
    
    # find the nearest point from p2df for each point in p1df
    # find the nearest pt2 for each pt1
    for idx in p1df.index: 
        # find the nearest point in pt2df
        x1,y1 = (p1df.at[idx,x1FieldName],p1df.at[idx,y1FieldName])
        deltaX = p2df[x2FieldName]-x1
        deltaY = p2df[y2FieldName]-y1
        # calculate distance to all the points in p2df
        distDf = deltaX*deltaX + deltaY*deltaY

        # get the nearest point's index and dist
        s = distDf.sort_values().head(1)
        idxp2, dist = (s.index[0],s.values[0])
        # update dist
        dist = sqrt(dist)

        # get additional fields from p2df by index
        nearestPt = p2df.loc[idxp2,otherColumns].values.flatten().tolist()

        # add the dist and other fields to p1df
        p1df.at[idx,cols] = [dist] + nearestPt

    return p1df

#
# Find the nearest FSP to each gauge in each library
# Note that multiple FSPs from different libraries might be snapped to the same gauge!
#
def SnapGauges2Fsps(libFolder,libNames,gauges,snapDist=350,gaugeXField='X',gaugeYField='Y',fspColumns=['FspId','FspX','FspY','FilledElev']):
# gauges -- can be a pandas DF or a text file. It must have the columns of 'X' and 'Y' in FSP's coordinate system
    
    if isinstance(gauges,(str)):
        # assume gauges are a text file
        allGaugesDf = pd.read_csv(gauges,index_col=False)
    
    if isinstance(gauges, pd.DataFrame):
        # gauges is a DF
        allGaugesDf = gauges
    
    # snape gauges to all the FSPs in each library
    # initialization
    snappedGauges = pd.DataFrame()
    # snap library by library
    for libName in libNames:
        # read fsp info csv files
        fspDf = pd.read_csv(os.path.join(libFolder, libName, fspInfoFileName),index_col=False)[fspColumns]

        # Find FSP extent + snap distance
        fspMinX = fspDf['FspX'].min()-snapDist # half cell size?
        fspMaxX = fspDf['FspX'].max()+snapDist
        fspMinY = fspDf['FspY'].min()-snapDist
        fspMaxY = fspDf['FspY'].max()+snapDist

        # select the gauges within the FSP extent of the library
        gaugesDf = allGaugesDf[(allGaugesDf[gaugeXField]>=fspMinX) & (allGaugesDf[gaugeXField]<=fspMaxX) & (allGaugesDf[gaugeYField]>=fspMinY) &(allGaugesDf[gaugeYField]<=fspMaxY)]
        
        # find the nearest FSP for each gauge
        distFieldName = 'd2NearestFsp'
        gaugesDf = NearestPoint(gaugesDf,gaugeXField,gaugeYField,fspDf,'FspX','FspY',distFieldName,fspColumns)
        
        # select gauges within snap distance
        gaugesDf = gaugesDf[(gaugesDf[distFieldName]<=snapDist)]
        # add library name 
        gaugesDf['lib_name'] = libName

        if snappedGauges.empty:
            snappedGauges = gaugesDf
        else:
            snappedGauges = pd.concat([snappedGauges,gaugesDf])

    return snappedGauges

#
# Snap gauges to library FSPs. NOT CHECKED YET
#
def SnapGauges2FspsBlob(libBlobSerClient,libName,gaugesDf,snapDist=350,gaugeIdField='GaugeLID',gaugeXField='X',gaugeYField='Y'):
# gauges -- a pandas DF. It must have the columns of 'X' and 'Y' in FSP's coordinate system
    
    # create a container client, assuming the container already exists
    container_client = libBlobSerClient.get_container_client(container=libName)

    # read fsp info csv files
    blob_client = container_client.get_blob_client(fspInfoFileName)
    # create a SAS token
    sas_token = azure.storage.blob.generate_blob_sas(
        container_client.account_name,
        container_client.container_name,
        blob_client.blob_name,
        account_key=container_client.credential.account_key,
        permission=["read"],
    )
    # construct the URL
    url = blob_client.url + "?" + urllib.parse.quote_plus(sas_token)
    # read the blob
    fspDf = pd.read_csv(url,index_col=False)[['FspX','FspY','FilledElev']]

    # Find FSP's border extent + snap distance
    fspMinX = fspDf['FspX'].min()-snapDist # half cell size?
    fspMaxX = fspDf['FspX'].max()+snapDist
    fspMinY = fspDf['FspY'].min()-snapDist
    fspMaxY = fspDf['FspY'].max()+snapDist

    # select the gauges within the extent
    gaugesDf = gaugesDf[(gaugesDf[gaugeXField]>=fspMinX) & (gaugesDf[gaugeXField]<=fspMaxX) & (gaugesDf[gaugeYField]>=fspMinY) &(gaugesDf[gaugeYField]<=fspMaxY)]
        
    # Create a temp DF for nearest FSPs
    cols = [gaugeIdField,'FspX','FspY','FspFilledElev','Dist']
    nearestFspDf =pd.DataFrame(columns=cols)

    # find the nearest FSP for each gauge
    for row in gaugesDf.itertuples(index=False): # itertuples() is the fastest way of iterating a df
        # find the nearest FSP
        glid,x,y = (getattr(row,gaugeIdField),getattr(row,gaugeXField),getattr(row,gaugeYField))
        deltaX = fspDf['FspX']-x
        deltaY = fspDf['FspY']-y
        fspDf['Dist'] = deltaX*deltaX + deltaY*deltaY
        nearestFsp = fspDf.sort_values('Dist').head(1)
        fspX,fspY,elev,dist = nearestFsp[['FspX','FspY','FilledElev','Dist']].values.flatten().tolist()
        dist = sqrt(dist)
        # add the nearest FSP to the gauge DF
        t = pd.DataFrame([[glid,fspX,fspY,elev,dist]],columns=cols)
        # nearestFspDf = nearestFspDf.append(t,ignore_index=True)
        nearestFspDf = pd.concat([nearestFspDf,t],ignore_index=True)

    # merge gauge and their nearest FSPs
    gaugesDf = gaugesDf.merge(nearestFspDf, how = 'left', on=gaugeIdField)
    # select gauges within snap distance
    snappedGauges = gaugesDf[(gaugesDf['Dist']<=snapDist)]
    
    return snappedGauges

#
# Snap gauges to library FSPs
#
def SnapGaugesToFsps(libFolder,libName,gauges,snapDist=250,gaugeIdField='GaugeLID',gaugeXField='X',gaugeYField='Y'):
# gauges -- can be a pandas DF or a text file. It must have the columns of 'X' and 'Y' in FSP's coordinate system
    
    if isinstance(gauges,(str)):
        # assume gauges are a text file
        gaugesDf = pd.read_csv(gauges,index_col=False)
    
    if isinstance(gauges, pd.DataFrame):
        # gauges is a DF
        gaugesDf = gauges
        
    # read fsp info csv files
    fspDf = pd.read_csv(os.path.join(libFolder, libName, fspInfoFileName),index_col=False)[['FspX','FspY','FilledElev']]

    # Find FSP's border extent + snap distance
    fspMinX = fspDf['FspX'].min()-snapDist # half cell size?
    fspMaxX = fspDf['FspX'].max()+snapDist
    fspMinY = fspDf['FspY'].min()-snapDist
    fspMaxY = fspDf['FspY'].max()+snapDist

    # select the gauges within the extent
    gaugesDf = gaugesDf[(gaugesDf[gaugeXField]>=fspMinX) & (gaugesDf[gaugeXField]<=fspMaxX) & (gaugesDf[gaugeYField]>=fspMinY) &(gaugesDf[gaugeYField]<=fspMaxY)]
        
    # Create a temp DF for nearest FSPs
    cols = [gaugeIdField,'FspX','FspY','FspFilledElev','Dist']
    nearestFspDf =pd.DataFrame(columns=cols)

    # find the nearest FSP for each gauge
    for row in gaugesDf.itertuples(index=False): # itertuples() is the fastest way of iterating a df
        # find the nearest FSP
        glid,x,y = (getattr(row,gaugeIdField),getattr(row,gaugeXField),getattr(row,gaugeYField))
        deltaX = fspDf['FspX']-x
        deltaY = fspDf['FspY']-y
        fspDf['Dist'] = deltaX*deltaX + deltaY*deltaY
        nearestFsp = fspDf.sort_values('Dist').head(1)
        fspX,fspY,elev,dist = nearestFsp[['FspX','FspY','FilledElev','Dist']].values.flatten().tolist()
        dist = sqrt(dist)
        # add the nearest FSP to the gauge DF
        t = pd.DataFrame([[glid,fspX,fspY,elev,dist]],columns=cols)
        # nearestFspDf = nearestFspDf.append(t,ignore_index=True)
        nearestFspDf = pd.concat([nearestFspDf,t],ignore_index=True)

    # merge gauge and their nearest FSPs
    gaugesDf = gaugesDf.merge(nearestFspDf, how = 'left', on=gaugeIdField)
    # select gauges within snap distance
    snappedGauges = gaugesDf[(gaugesDf['Dist']<=snapDist)]
    
    return snappedGauges

#
# Snap gauges to library FSPs
#
def SnapGaugesToFspsBlob(libBlobSerClient,libName,gaugesDf,snapDist=250,gaugeIdField='GaugeLID',gaugeXField='X',gaugeYField='Y'):
# gauges -- a pandas DF. It must have the columns of 'X' and 'Y' in FSP's coordinate system
    
    # create a container client, assuming the container already exists
    container_client = libBlobSerClient.get_container_client(container=libName)

    # read fsp info csv files
    blob_client = container_client.get_blob_client(fspInfoFileName)
    # create a SAS token
    sas_token = azure.storage.blob.generate_blob_sas(
        container_client.account_name,
        container_client.container_name,
        blob_client.blob_name,
        account_key=container_client.credential.account_key,
        permission=["read"],
    )
    # construct the URL
    url = blob_client.url + "?" + urllib.parse.quote_plus(sas_token)
    # read the blob
    fspDf = pd.read_csv(url,index_col=False)[['FspX','FspY','FilledElev']]

    # Find FSP's border extent + snap distance
    fspMinX = fspDf['FspX'].min()-snapDist # half cell size?
    fspMaxX = fspDf['FspX'].max()+snapDist
    fspMinY = fspDf['FspY'].min()-snapDist
    fspMaxY = fspDf['FspY'].max()+snapDist

    # select the gauges within the extent
    gaugesDf = gaugesDf[(gaugesDf[gaugeXField]>=fspMinX) & (gaugesDf[gaugeXField]<=fspMaxX) & (gaugesDf[gaugeYField]>=fspMinY) &(gaugesDf[gaugeYField]<=fspMaxY)]
        
    # Create a temp DF for nearest FSPs
    cols = [gaugeIdField,'FspX','FspY','FspFilledElev','Dist']
    nearestFspDf =pd.DataFrame(columns=cols)

    # find the nearest FSP for each gauge
    for row in gaugesDf.itertuples(index=False): # itertuples() is the fastest way of iterating a df
        # find the nearest FSP
        glid,x,y = (getattr(row,gaugeIdField),getattr(row,gaugeXField),getattr(row,gaugeYField))
        deltaX = fspDf['FspX']-x
        deltaY = fspDf['FspY']-y
        fspDf['Dist'] = deltaX*deltaX + deltaY*deltaY
        nearestFsp = fspDf.sort_values('Dist').head(1)
        fspX,fspY,elev,dist = nearestFsp[['FspX','FspY','FilledElev','Dist']].values.flatten().tolist()
        dist = sqrt(dist)
        # add the nearest FSP to the gauge DF
        t = pd.DataFrame([[glid,fspX,fspY,elev,dist]],columns=cols)
        # nearestFspDf = nearestFspDf.append(t,ignore_index=True)
        nearestFspDf = pd.concat([nearestFspDf,t],ignore_index=True)

    # merge gauge and their nearest FSPs
    gaugesDf = gaugesDf.merge(nearestFspDf, how = 'left', on=gaugeIdField)
    # select gauges within snap distance
    snappedGauges = gaugesDf[(gaugesDf['Dist']<=snapDist)]
    
    return snappedGauges

#
# Interpolate FSP DOF (fy) based on FSP's elevation (fe) or distance (fx) between two gauges
# fx, fe -- FSP's distance from downstream outlet and elevation. Can be vectors
# gx1, ge1, gy1 -- gauge1's distance, elevation and DOF
# gx2, ge2, gy2 -- gauge2's distance, elevation and DOF
# This function assumes gx1 < gx2 and ge1<=ge2, and fx>=gx1 and fx<=gx2
#
def InterpBetweenTwoGauges(fx, fe, gx1, ge1, gy1, gx2, ge2, gy2, weightingType='V'):
    if weightingType == 'H':
        # distance-based (hirizontal) linear interpolation
        fy = gy1+(fx-gx1)/(gx2-gx1)*(gy2-gy1)
    else:
        # elevation-based (vertical) linear interpolation
        # when two gauges have the same elevation, using distance-based (horizontal) interpolation    
        if (ge1 == ge2):
            fy = gy1+(fx-gx1)/(gx2-gx1)*(gy2-gy1)
        else:
            # elevation-based (vertical) interpolation
            fy = gy1+(fe-ge1)/(ge2-ge1)*(gy2-gy1)

    return fy

#
# Interpolate FSP DOF using the DOFs observaed at a list of gauges
#
# fx, fe -- FSP distance from downstream outlet and FSP filled DEM elevation
# gx, ge, gy --  gauge distance from downstream outlet, filled DEM elevation and DOF
#
def InterpDofWithGauges(fx,fe,gx,ge,gy,weightingType='V'):
    # initialize the return vector as NAN
    fy = np.empty(fx.size)
    fy[:] = np.nan

    # interpolate by gauge pairs
    for i in range(gy.size-1):
        # get a pair of gauges
        gx1,ge1,gy1=gx[i],ge[i],gy[i]
        gx2,ge2,gy2=gx[i+1],ge[i+1],gy[i+1]

        # prepare the FSPs for interpolation
        ind = np.where((fx>=gx1) & (fx<=gx2))
        fxi, fei=fx[ind], fe[ind]
        fy[ind] = InterpBetweenTwoGauges(fxi, fei, gx1, ge1, gy1, gx2, ge2, gy2, weightingType)
    return fy

#
# Interpolate FSP DOF (Depth of Flow, i.e., FSP stage) from observed gauge DOFs using 
# distance-(horizontal) or elevation-based (vertical) linear interpolation
#
# Different from EstimateFspDofFromGauge(), this function assumes gauge FSPs already have their DOF calculated!
#
def InterpolateFspDofFromGauge(libFolder,libName,gaugeFspDf,minGaugeDof=0.0328084,weightingType='V'):
# gaugeFspDf--A DF of gauge FSPs (i.e., FSPs to which gauges are snapped). 
#       It should have at least 4 columns['lib_name','FspX','FspY','Dof'].
# minGaugeDof--min DOF a gauge should have, by default is 1 cm = 0.0328083989501312 foot. Negative may occur as incorrect gauge datum
# weightingType--V (vertical distance-based) or H (horizontal, i.e. horizontal distance-based)
    
    # select the gauge FSPs in the library
    gaugeFspDf = gaugeFspDf[gaugeFspDf['lib_name']==libName]

    # read in FSP and stream order network files
    fspFile = os.path.join(libFolder, libName, fspInfoFileName)
    strOrdFile = os.path.join(libFolder, libName, strOrdNetFileName)
    fspDf = pd.read_csv(fspFile) 
    strOrdDf = pd.read_csv(strOrdFile) 

    # reset gauge FSP DOF, if it's < 0 or nodata, to minGaugeDof
    gaugeFspDf.loc[(gaugeFspDf['Dof']<=minGaugeDof)|gaugeFspDf['Dof'].isna(),['Dof']] = minGaugeDof
    # print(gaugeFspDf)

    # create an empty DF to store interpolated FSP DOFs
    fspDof = pd.DataFrame(columns=['FspId','FspX','FspY','DsDist','FilledElev','Dof'])
    # interpolate DoF for each stream order from low to high (low order means high priority!)
    # get the stream orders with gauges on them
    strOrds = gaugeFspDf['StrOrd'].drop_duplicates().sort_values().tolist()
    if len(strOrds)==0:
        print('No stream order found for the gauges!')
        return None

    for ord in strOrds:
        # gauges on the stream order
        gaugeOrd = gaugeFspDf[gaugeFspDf['StrOrd']==ord].sort_values('DsDist')

        #
        # create the upstream ending gauge assuming a level water elevation at the gauge
        #
        # get upstream gauge's segment IDs
        t = gaugeOrd.tail(1)[['SegId','FilledElev','Dof','FspX','FspY']].values.flatten().tolist()
        upSegId, gElev, dof, gx,gy = t 
        # get segment FSPs and find the level-off FSP
        t = fspDf[fspDf['SegId']==upSegId].copy() # tell pandas we want a copy to avoid "SettingWithCopyWarning"
        t['Dof'] = gElev+dof-t['FilledElev']
        t = t[t['Dof']>=0].sort_values('DsDist').tail(1)[['FspX','FspY','DsDist','FilledElev','Dof']]
        # check if the ending gauge is the gauge itself
        tx,ty = t.iat[0,0], t.iat[0,1]
        # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
        if (gx==tx) and (gy==ty):
            # the gauge is the ending gauge.
            usEndGauge = pd.DataFrame() # an empty DF
        else:
            usEndGauge = t
        # print(usEndGauge)
        
        #
        # create downstream ending gauge
        #
        # get the downstream order and junction FSP's coordinates
        t = strOrdDf[strOrdDf['StrOrd']==ord][['DsStrOrd','JunctionFspX', 'JunctionFspY']].values.flatten().tolist()
        dsStrOrd,fspx,fspy = t 

        # whether there is a junction/confluence gauge
        if dsStrOrd !=0:
            # there is a downstream order. see whether the junction's DOF has an interpolated DOF
            juncDf = fspDof[(fspDof['FspX']==fspx) &(fspDof['FspY']==fspy)]
            if len(juncDf) != 0:
                # Junction has DOF. Create downstream ending gauge with the junction FSP
                dsEndGauge = juncDf[['FspX','FspY','DsDist','FilledElev','Dof']]
            else:
                juncDf = None

        # No downstream order or junction FSP
        if (dsStrOrd == 0) or (juncDf is None):
            # Create downstream ending gauge with the last FSP in the segment
            # get the downstream and upstream segment IDs
            dsSegId, gx,gy = gaugeOrd.head(1)[['SegId','FspX','FspY']].values.flatten().tolist()
            # get the first FSP on the downstream segment
            t = fspDf[fspDf['SegId']==dsSegId].tail(1)[['FspX','FspY','DsDist','FilledElev']]
            # check if the ending gauge is the gauge itself
            tx,ty = t.iat[0,0], t.iat[0,1]
            # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
            if (gx==tx) and (gy==ty):
                # the gauge is the ending gauge.
                dsEndGauge = pd.DataFrame() # an empty DF
            else:
                dsEndGauge = t
                dsEndGauge['Dof']=0
        # print(dsEndGauge)
                  
        # put all the gauges together
        gaugeOrd = gaugeOrd[['FspX','FspY','DsDist','FilledElev','Dof']]
        # gaugeOrd = gaugeOrd.append(usEndGauge)
        gaugeOrd = pd.concat([gaugeOrd,usEndGauge])
        # gaugeOrd = gaugeOrd.append(dsEndGauge)
        gaugeOrd = pd.concat([gaugeOrd,dsEndGauge])
        # print(f"Gauges with DOFs on stream order ({ord}): \n",gaugeOrd)
        
        # calculate the min and max downstream distance
        minDist = gaugeOrd['DsDist'].min()
        maxDist = gaugeOrd['DsDist'].max()

        # select the FSPs on the stream order
        fspOrd = fspDf[fspDf['StrOrd']==ord][['FspId','FspX','FspY','DsDist','FilledElev']]
        fspOrd = fspOrd[(fspOrd['DsDist']>=minDist) & (fspOrd['DsDist']<=maxDist)]
        fx, fe = fspOrd['DsDist'].to_numpy(),fspOrd['FilledElev'].to_numpy()

        # prepare gauges
        gaugeOrd = gaugeOrd.sort_values('DsDist')
        gx, ge, gy = gaugeOrd['DsDist'].to_numpy(), gaugeOrd['FilledElev'].to_numpy(), gaugeOrd['Dof'].astype(np.float64).to_numpy()
        
        # interpolate
        fspOrd['Dof'] = InterpDofWithGauges(fx,fe,gx,ge,gy,weightingType)

        # append the interpolated SFPs
        # fspDof = fspDof.append(fspOrd,ignore_index=True)
        fspDof = pd.concat([fspDof,fspOrd],ignore_index=True)
        # print(fspDof)
    
    # select columns
    fspDof = fspDof[['FspId','Dof']]
    # fspDof = fspDof[['FspId','DsDist','FilledElev','Dof']] # keep more columns for checking the interpolation
    # print(fspDof)

    # return interpolated DOF for the FSPs
    return fspDof

#
# Estimate/interpolate FSP DOF (Depth of Flow, i.e., FSP stage) from observed gauge DOFs using 
# distance-(horizontal) or elevation-based (vertical) linear interpolation
#
def EstimateFspDofFromGauge(libFolder,libName,gaugeFspDf,minGaugeDof=0.0328084,weightingType='V'):
# gaugeFspDf--A DF of gauge FSPs (i.e., FSPs to which gauges are snapped). 
#       It should have at least 4 columns['stage_elevation','lib_name','FspX','FspY'].
# minGaugeDof--min DOF a gauge should have, by default is 1 cm = 0.0328083989501312 foot. Negative may occur as incorrect gauge datum
# weightingType--V (vertical distance-based) or H (horizontal, i.e. horizontal distance-based)
    
    # select the gauge FSPs in the library
    gaugeFspDf = gaugeFspDf[gaugeFspDf['lib_name']==libName]

    # read in FSP and stream order network files
    fspFile = os.path.join(libFolder, libName, fspInfoFileName)
    strOrdFile = os.path.join(libFolder, libName, strOrdNetFileName)
    fspDf = pd.read_csv(fspFile) 
    strOrdDf = pd.read_csv(strOrdFile) 

    # Get gauge stream order for interpolation by stream orders
    gaugeFspDf = pd.merge(gaugeFspDf,fspDf,how='inner',on=['FspX','FspY'])[['FspX','FspY','StrOrd','DsDist','SegId','FilledElev','stage_elevation']]
    # print(gaugeFspDf)

    # calculate gauge FSP's DOF
    gaugeFspDf['Dof'] = gaugeFspDf['stage_elevation'] - gaugeFspDf['FilledElev']
    # reset gauge FSP DOF, if it's < 0 or nodata, to minGaugeDof
    gaugeFspDf.loc[(gaugeFspDf['Dof']<=minGaugeDof)|gaugeFspDf['Dof'].isna(),['Dof']] = minGaugeDof
    # print(gaugeFspDf)

    # create an empty DF to store interpolated FSP DOFs
    fspDof = pd.DataFrame(columns=['FspId','FspX','FspY','DsDist','FilledElev','Dof'])
    # interpolate DoF for each stream order from low to high (low order means high priority!)
    # get the stream orders with gauges on them
    strOrds = gaugeFspDf['StrOrd'].drop_duplicates().sort_values().tolist()
    if len(strOrds)==0:
        print('No stream found for the gauges!')
        return None

    for ord in strOrds:
        # gauges on the stream order
        gaugeOrd = gaugeFspDf[gaugeFspDf['StrOrd']==ord].sort_values('DsDist')

        #
        # create the upstream ending gauge assuming a level water elevation at the gauge
        #
        # get upstream gauge's segment IDs
        t = gaugeOrd.tail(1)[['SegId','FilledElev','Dof','FspX','FspY']].values.flatten().tolist()
        upSegId, gElev, dof, gx,gy = t 
        # get segment FSPs and find the level-off FSP
        t = fspDf[fspDf['SegId']==upSegId].copy() # tell pandas we want a copy to avoid "SettingWithCopyWarning"
        t['Dof'] = gElev+dof-t['FilledElev']
        t = t[t['Dof']>=0].sort_values('DsDist').tail(1)[['FspX','FspY','DsDist','FilledElev','Dof']]
        # check if the ending gauge is the gauge itself
        tx,ty = t.iat[0,0], t.iat[0,1]
        # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
        if (gx==tx) and (gy==ty):
            # the gauge is the ending gauge.
            usEndGauge = pd.DataFrame() # an empty DF
        else:
            usEndGauge = t
        # print(usEndGauge)
        
        #
        # create downstream ending gauge
        #
        # get the downstream order and junction FSP's coordinates
        t = strOrdDf[strOrdDf['StrOrd']==ord][['DsStrOrd','JunctionFspX', 'JunctionFspY']].values.flatten().tolist()
        dsStrOrd,fspx,fspy = t 

        # whether there is a junction/confluence gauge
        if dsStrOrd !=0:
            # there is a downstream order. see whether the junction's DOF has an interpolated DOF
            juncDf = fspDof[(fspDof['FspX']==fspx) &(fspDof['FspY']==fspy)]
            if len(juncDf) != 0:
                # Junction has DOF. Create downstream ending gauge with the junction FSP
                dsEndGauge = juncDf[['FspX','FspY','DsDist','FilledElev','Dof']]
            else:
                juncDf = None

        # No downstream order or junction FSP
        if (dsStrOrd == 0) or (juncDf is None):
            # Create downstream ending gauge with the last FSP in the segment
            # get the downstream and upstream segment IDs
            dsSegId, gx,gy = gaugeOrd.head(1)[['SegId','FspX','FspY']].values.flatten().tolist()
            # get the first FSP on the downstream segment
            t = fspDf[fspDf['SegId']==dsSegId].tail(1)[['FspX','FspY','DsDist','FilledElev']]
            # check if the ending gauge is the gauge itself
            tx,ty = t.iat[0,0], t.iat[0,1]
            # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
            if (gx==tx) and (gy==ty):
                # the gauge is the ending gauge.
                dsEndGauge = pd.DataFrame() # an empty DF
            else:
                dsEndGauge = t
                dsEndGauge['Dof']=0
        # print(dsEndGauge)
                  
        # put all the gauges together
        gaugeOrd = gaugeOrd[['FspX','FspY','DsDist','FilledElev','Dof']]
        # gaugeOrd = gaugeOrd.append(usEndGauge)
        # gaugeOrd = gaugeOrd.append(dsEndGauge)
        gaugeOrd = pd.concat([gaugeOrd,usEndGauge])
        gaugeOrd = pd.concat([gaugeOrd,dsEndGauge])
        # print(f"Gauges with DOFs on stream order ({ord}): \n",gaugeOrd)
        
        # calculate the min and max downstream distance
        minDist = gaugeOrd['DsDist'].min()
        maxDist = gaugeOrd['DsDist'].max()

        # select the FSPs on the stream order
        fspOrd = fspDf[fspDf['StrOrd']==ord][['FspId','FspX','FspY','DsDist','FilledElev']]
        fspOrd = fspOrd[(fspOrd['DsDist']>=minDist) & (fspOrd['DsDist']<=maxDist)]
        fx, fe = fspOrd['DsDist'].to_numpy(),fspOrd['FilledElev'].to_numpy()

        # prepare gauges
        gaugeOrd = gaugeOrd.sort_values('DsDist')
        gx, ge, gy = gaugeOrd['DsDist'].to_numpy(), gaugeOrd['FilledElev'].to_numpy(), gaugeOrd['Dof'].astype(np.float64).to_numpy()
        
        # interpolate
        fspOrd['Dof'] = InterpDofWithGauges(fx,fe,gx,ge,gy,weightingType)

        # append the interpolated SFPs
        # fspDof = fspDof.append(fspOrd,ignore_index=True)
        fspDof = pd.concat([fspDof,fspOrd],ignore_index=True)
        # print(fspDof)
    
    # select columns
    fspDof = fspDof[['FspId','Dof']]
    # fspDof = fspDof[['FspId','DsDist','FilledElev','Dof']] # keep more columns for checking the interpolation
    # print(fspDof)

    # return interpolated DOF for the FSPs
    return fspDof

#
# Estimate/interpolate FSP Depth of Flow (i.e., FSP stage) from gauge DOF
#
def EstimateFspDofFromGaugeOld(libFolder,libName,gaugeFspDf,minGaugeDof=0.0328084):
# gaugeFspDf--A DF of gauge FSPs (i.e., FSPs to which gauges are snapped). 
#       It should have at least 4 columns['stage_elevation','lib_name','FspX','FspY'].
# minGaugeDof--min DOF a gauge should have, by default is 1 cm = 0.0328083989501312 foot. Negative may occur as incorrect gauge datum
    
    # select the gauge FSPs in the library
    gaugeFspDf = gaugeFspDf[gaugeFspDf['lib_name']==libName]

    # read in FSP and stream order network files
    fspFile = os.path.join(libFolder, libName, fspInfoFileName)
    strOrdFile = os.path.join(libFolder, libName, strOrdNetFileName)
    fspDf = pd.read_csv(fspFile) 
    strOrdDf = pd.read_csv(strOrdFile) 

    # Get gauge stream order for interpolation by stream orders
    gaugeFspDf = pd.merge(gaugeFspDf,fspDf,how='inner',on=['FspX','FspY'])[['FspX','FspY','StrOrd','DsDist','SegId','FilledElev','stage_elevation']]
    # print(gaugeFspDf)

    # calculate gauge FSP's DOF
    gaugeFspDf['Dof'] = gaugeFspDf['stage_elevation'] - gaugeFspDf['FilledElev']
    # reset gauge FSP DOF, if it's < 0 or nodata, to minGaugeDof
    gaugeFspDf.loc[(gaugeFspDf['Dof']<=minGaugeDof)|gaugeFspDf['Dof'].isna(),['Dof']] = minGaugeDof
    # print(gaugeFspDf)

    # create an empty DF to store interpolated FSP DOFs
    fspDof = pd.DataFrame(columns=['FspId','FspX','FspY','DsDist','Dof'])
    # interpolate DoF for each stream order from low to high (low order means high priority!)
    # get the stream orders with gauges on them
    strOrds = gaugeFspDf['StrOrd'].drop_duplicates().sort_values().tolist()
    if len(strOrds)==0:
        print('No stream found for the gauges!')
        return None

    for ord in strOrds:
        # gauges on the stream order
        gaugeOrd = gaugeFspDf[gaugeFspDf['StrOrd']==ord].sort_values('DsDist')

        #
        # create the upstream ending gauge assuming a level water elevation at the gauge
        #
        # get upstream gauge's segment IDs
        t = gaugeOrd.tail(1)[['SegId','FilledElev','Dof','FspX','FspY']].values.flatten().tolist()
        upSegId, gElev, dof, gx,gy = t 
        # get segment FSPs and find the level-off FSP
        t = fspDf[fspDf['SegId']==upSegId].copy() # tell pandas we want a copy to avoid "SettingWithCopyWarning"
        t['Dof'] = gElev+dof-t['FilledElev']
        t = t[t['Dof']>=0].sort_values('DsDist').tail(1)[['FspX','FspY','DsDist','Dof']]
        # check if the ending gauge is the gauge itself
        tx,ty = t.iat[0,0], t.iat[0,1]
        # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
        if (gx==tx) and (gy==ty):
            # the gauge is the ending gauge.
            usEndGauge = pd.DataFrame() # an empty DF
        else:
            usEndGauge = t
        # print(usEndGauge)
        
        #
        # create downstream ending gauge
        #
        # get the downstream order and junction FSP's coordinates
        t = strOrdDf[strOrdDf['StrOrd']==ord][['DsStrOrd','JunctionFspX', 'JunctionFspY']].values.flatten().tolist()
        dsStrOrd,fspx,fspy = t 

        # whether there is a junction/confluence gauge
        if dsStrOrd !=0:
            # there is a downstream order. see whether the junction's DOF has an interpolated DOF
            juncDf = fspDof[(fspDof['FspX']==fspx) &(fspDof['FspY']==fspy)]
            if len(juncDf) != 0:
                # Junction has DOF. Create downstream ending gauge with the junction FSP
                dsEndGauge = juncDf[['FspX','FspY','DsDist','Dof']]
            else:
                juncDf = None

        # No downstream order or junction FSP
        if (dsStrOrd == 0) or (juncDf is None):
            # Create downstream ending gauge with the last FSP in the segment
            # get the downstream and upstream segment IDs
            dsSegId, gx,gy = gaugeOrd.head(1)[['SegId','FspX','FspY']].values.flatten().tolist()
            # get the first FSP on the downstream segment
            t = fspDf[fspDf['SegId']==dsSegId].tail(1)[['FspX','FspY','DsDist']]
            # check if the ending gauge is the gauge itself
            tx,ty = t.iat[0,0], t.iat[0,1]
            # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
            if (gx==tx) and (gy==ty):
                # the gauge is the ending gauge.
                dsEndGauge = pd.DataFrame() # an empty DF
            else:
                dsEndGauge = t
                dsEndGauge['Dof']=0
        # print(dsEndGauge)
                  
        # put all the gauges together
        gaugeOrd = gaugeOrd[['FspX','FspY','DsDist','Dof']]
        # gaugeOrd = gaugeOrd.append(usEndGauge)
        # gaugeOrd = gaugeOrd.append(dsEndGauge)
        gaugeOrd = pd.concat([gaugeOrd,usEndGauge])
        gaugeOrd = pd.concat([gaugeOrd,dsEndGauge])
        # print(f"Gauges with DOFs on stream order ({ord}): \n",gaugeOrd)
        
        # calculate the min and max downstream distance
        minDist = gaugeOrd['DsDist'].min()
        maxDist = gaugeOrd['DsDist'].max()

        # select the FSPs on the stream order
        fspOrd = fspDf[fspDf['StrOrd']==ord][['FspId','FspX','FspY','DsDist']]
        fspOrd = fspOrd[(fspOrd['DsDist']>=minDist) & (fspOrd['DsDist']<=maxDist)]

        # interpolate DOF for the FSPs with the gauges
        gaugeOrd = gaugeOrd.sort_values('DsDist') # for using np.interp(), x must be ascending!
        fspOrd['Dof'] = np.interp(fspOrd['DsDist'], gaugeOrd['DsDist'], gaugeOrd['Dof'].astype(np.float64))
        # print(fspOrd)

        # append the interpolated SFPs
        # fspDof = fspDof.append(fspOrd,ignore_index=True)
        fspDof = pd.concat([fspDof,fspOrd],ignore_index=True)
        # print(fspDof)
    
    # select and rename columns
    fspDof = fspDof[['FspId','Dof']]
    # print(fspDof)

    # return interpolated DOF for the FSPs
    return fspDof

#
# Estimate FSP Depth of Flow (DoF), i.e., FSP stage from gauges
#
def EstimateFspDofFromGaugeReallyOld(libFolder,libName,gaugeDf,gaugeElevField,minGaugeDof=0.0328084):
# gaugeElevField --  field in gaugeDf that stores gauge's water surface elevation
# gaugeDf--A DF with snapped FSP columns ['FspX','FspY','FspFilledElev','Dist']
# minGaugeDof--min DOF a gauge should have, by default is 1 cm = 0.0328083989501312 foot. Negative may occur as incorrect gauge datum
    
    # calculate FSP DOF
    gaugeDf['Dof'] = gaugeDf[gaugeElevField] - gaugeDf['FspFilledElev']
    # reset DOF, if it's < 0 or nodata, to minGaugeDof
    gaugeDf.loc[(gaugeDf['Dof']<=minGaugeDof)|gaugeDf['Dof'].isna(),['Dof']] = minGaugeDof
    # print(gaugeDf)

    # read in FSP and stream order network files
    fspFile = os.path.join(libFolder, libName, fspInfoFileName)
    strOrdFile = os.path.join(libFolder, libName, strOrdNetFileName)
    fspDf = pd.read_csv(fspFile) 
    strOrdDf = pd.read_csv(strOrdFile) 

    # Get gauge stream order for interpolation by stream orders
    gaugeDf = pd.merge(gaugeDf,fspDf,how='inner',on=['FspX','FspY'])[['FspX','FspY','Dof','StrOrd','DsDist','SegId','FilledElev']]
    # print(gaugeDf)

    # create an empty DF to store interpolated FSP DOFs
    fspDof = pd.DataFrame(columns=['FspId','FspX','FspY','DsDist','Dof'])
    # interpolate DoF for each stream order from low to high (low order means high priority!)
    # get the stream orders with gauges on them
    strOrds = gaugeDf['StrOrd'].drop_duplicates().sort_values().tolist()
    if len(strOrds)==0:
        print('No stream found for the gauges!')
        return None

    for ord in strOrds:
        # gauges on the stream order
        gaugeOrd = gaugeDf[gaugeDf['StrOrd']==ord].sort_values('DsDist')

        #
        # create the upstream ending gauge assuming a level water elevation at the gauge
        #
        # get upstream gauge's segment IDs
        t = gaugeOrd.tail(1)[['SegId','FilledElev','Dof','FspX','FspY']].values.flatten().tolist()
        upSegId, gElev, dof, gx,gy = t 
        # get segment FSPs and find the level-off FSP
        t = fspDf[fspDf['SegId']==upSegId].copy() # tell pandas we want a copy to avoid "SettingWithCopyWarning"
        t['Dof'] = gElev+dof-t['FilledElev']
        t = t[t['Dof']>=0].sort_values('DsDist').tail(1)[['FspX','FspY','DsDist','Dof']]
        # check if the ending gauge is the gauge itself
        tx,ty = t.iat[0,0], t.iat[0,1]
        # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
        if (gx==tx) and (gy==ty):
            # the gauge is the ending gauge.
            usEndGauge = pd.DataFrame() # an empty DF
        else:
            usEndGauge = t
        # print(usEndGauge)
        
        #
        # create downstream ending gauge
        #
        # get the downstream order and junction FSP's coordinates
        t = strOrdDf[strOrdDf['StrOrd']==ord][['DsStrOrd','JunctionFspX', 'JunctionFspY']].values.flatten().tolist()
        dsStrOrd,fspx,fspy = t 

        # whether there is a junction/confluence gauge
        if dsStrOrd !=0:
            # there is a downstream order. see whether the junction's DOF has an interpolated DOF
            juncDf = fspDof[(fspDof['FspX']==fspx) &(fspDof['FspY']==fspy)]
            if len(juncDf) != 0:
                # Junction has DOF. Create downstream ending gauge with the junction FSP
                dsEndGauge = juncDf[['FspX','FspY','DsDist','Dof']]
            else:
                juncDf = None

        # No downstream order or junction FSP
        if (dsStrOrd == 0) or (juncDf is None):
            # Create downstream ending gauge with the last FSP in the segment
            # get the downstream and upstream segment IDs
            dsSegId, gx,gy = gaugeOrd.head(1)[['SegId','FspX','FspY']].values.flatten().tolist()
            # get the first FSP on the downstream segment
            t = fspDf[fspDf['SegId']==dsSegId].tail(1)[['FspX','FspY','DsDist']]
            # check if the ending gauge is the gauge itself
            tx,ty = t.iat[0,0], t.iat[0,1]
            # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
            if (gx==tx) and (gy==ty):
                # the gauge is the ending gauge.
                dsEndGauge = pd.DataFrame() # an empty DF
            else:
                dsEndGauge = t
                dsEndGauge['Dof']=0
        # print(dsEndGauge)
                  
        # put all the gauges together
        gaugeOrd = gaugeOrd[['FspX','FspY','DsDist','Dof']]
        # gaugeOrd = gaugeOrd.append(usEndGauge)
        # gaugeOrd = gaugeOrd.append(dsEndGauge)
        gaugeOrd = pd.concat([gaugeOrd,usEndGauge])
        gaugeOrd = pd.concat([gaugeOrd,dsEndGauge])
        # print(f"Gauges with DOFs on stream order ({ord}): \n",gaugeOrd)
        
        # calculate the min and max downstream distance
        minDist = gaugeOrd['DsDist'].min()
        maxDist = gaugeOrd['DsDist'].max()

        # select the FSPs on the stream order
        fspOrd = fspDf[fspDf['StrOrd']==ord][['FspId','FspX','FspY','DsDist']]
        fspOrd = fspOrd[(fspOrd['DsDist']>=minDist) & (fspOrd['DsDist']<=maxDist)]

        # interpolate DOF for the FSPs with the gauges
        gaugeOrd = gaugeOrd.sort_values('DsDist') # for using np.interp(), x must be ascending!
        fspOrd['Dof'] = np.interp(fspOrd['DsDist'], gaugeOrd['DsDist'], gaugeOrd['Dof'].astype(np.float64))
        # print(fspOrd)

        # append the interpolated SFPs
        # fspDof = fspDof.append(fspOrd,ignore_index=True)
        fspDof = pd.concat([fspDof,fspOrd],ignore_index=True)
        # print(fspDof)
    
    # select and rename columns
    fspDof = fspDof[['FspId','Dof']]
    # print(fspDof)

    # reset DOF if it's less than minGaugeDof
    fspDof.loc[(fspDof['Dof']<=minGaugeDof),['Dof']] = minGaugeDof

    # return interpolated DOF for the FSPs
    return fspDof

#
# Estimate FSP Depth of Flow (DoF), i.e., FSP stage from gauges
#
def EstimateFspDofFromGaugeBlob(libBlobSerClient,libName,gaugeDf,gaugeElevField,minGaugeDof=0.0328084):
# gaugeElevField --  field in gaugeDf that stores gauge's water surface elevation
# gaugeDf--A DF with snapped FSP columns ['FspX','FspY','FspFilledElev','Dist']
# minGaugeDof--min DOF a gauge should have, by default is 1 cm = 0.0328083989501312 foot. Negative may occur as incorrect gauge datum
    
    # calculate FSP DOF
    gaugeDf['Dof'] = gaugeDf[gaugeElevField] - gaugeDf['FspFilledElev']
    # reset DOF, if it's < 0, to minGaugeDof
    gaugeDf.loc[gaugeDf['Dof']<=minGaugeDof,['Dof']] = minGaugeDof
    print(gaugeDf)

    #
    # read in FSP and stream order network files 
    #
    # create a container client, assuming the container already exists
    container_client = libBlobSerClient.get_container_client(container=libName)

    # read fsp info csv files
    blob_client = container_client.get_blob_client(fspInfoFileName)
    # create a SAS token
    sas_token = azure.storage.blob.generate_blob_sas(
        container_client.account_name,
        container_client.container_name,
        blob_client.blob_name,
        account_key=container_client.credential.account_key,
        permission=["read"],
    )
    # construct the URL
    url = blob_client.url + "?" + urllib.parse.quote_plus(sas_token)
    # read the blob
    fspDf = pd.read_csv(url)
    
    # read stream order text file
    blob_client = container_client.get_blob_client(strOrdNetFileName)
    # create a SAS token
    sas_token = azure.storage.blob.generate_blob_sas(
        container_client.account_name,
        container_client.container_name,
        blob_client.blob_name,
        account_key=container_client.credential.account_key,
        permission=["read"],
    )
    # construct the URL
    url = blob_client.url + "?" + urllib.parse.quote_plus(sas_token)
    # read the blob
    strOrdDf = pd.read_csv(url)
    
    # Get gauge stream order for interpolation by stream orders
    gaugeDf = pd.merge(gaugeDf,fspDf,how='inner',on=['FspX','FspY'])[['FspX','FspY','Dof','StrOrd','DsDist','SegId','FilledElev']]
    # print(gaugeDf)

    # create an empty DF to store interpolated FSP DOFs
    fspDof = pd.DataFrame(columns=['FspId','FspX','FspY','DsDist','Dof'])
    # interpolate DoF for each stream order from low to high (low order means high priority!)
    # get the stream orders with gauges on them
    strOrds = gaugeDf['StrOrd'].drop_duplicates().sort_values().tolist()
    if len(strOrds)==0:
        print('No stream found for the gauges!')
        return None

    for ord in strOrds:
        # gauges on the stream order
        gaugeOrd = gaugeDf[gaugeDf['StrOrd']==ord].sort_values('DsDist')

        #
        # create the upstream ending gauge assuming a level water elevation at the gauge
        #
        # get upstream gauge's segment IDs
        t = gaugeOrd.tail(1)[['SegId','FilledElev','Dof','FspX','FspY']].values.flatten().tolist()
        upSegId, gElev, dof, gx,gy = t 
        # get segment FSPs and find the level-off FSP
        t = fspDf[fspDf['SegId']==upSegId].copy() # tell pandas we want a copy to avoid "SettingWithCopyWarning"
        t['Dof'] = gElev+dof-t['FilledElev']
        t = t[t['Dof']>=0].sort_values('DsDist').tail(1)[['FspX','FspY','DsDist','Dof']]
        # check if the ending gauge is the gauge itself
        tx,ty = t.iat[0,0], t.iat[0,1]
        # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
        if (gx==tx) and (gy==ty):
            # the gauge is the ending gauge.
            usEndGauge = pd.DataFrame() # an empty DF
        else:
            usEndGauge = t
        # print(usEndGauge)
        
        #
        # create downstream ending gauge
        #
        # get the downstream order and junction FSP's coordinates
        t = strOrdDf[strOrdDf['StrOrd']==ord][['DsStrOrd','JunctionFspX', 'JunctionFspY']].values.flatten().tolist()
        dsStrOrd,fspx,fspy = t 

        # whether there is a junction/confluence gauge
        if dsStrOrd !=0:
            # there is a downstream order. see whether the junction's DOF has an interpolated DOF
            juncDf = fspDof[(fspDof['FspX']==fspx) &(fspDof['FspY']==fspy)]
            if len(juncDf) != 0:
                # Junction has DOF. Create downstream ending gauge with the junction FSP
                dsEndGauge = juncDf[['FspX','FspY','DsDist','Dof']]
            else:
                juncDf = None

        # No downstream order or junction FSP
        if (dsStrOrd == 0) or (juncDf is None):
            # Create downstream ending gauge with the last FSP in the segment
            # get the downstream and upstream segment IDs
            dsSegId, gx,gy = gaugeOrd.head(1)[['SegId','FspX','FspY']].values.flatten().tolist()
            # get the first FSP on the downstream segment
            t = fspDf[fspDf['SegId']==dsSegId].tail(1)[['FspX','FspY','DsDist']]
            # check if the ending gauge is the gauge itself
            tx,ty = t.iat[0,0], t.iat[0,1]
            # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
            if (gx==tx) and (gy==ty):
                # the gauge is the ending gauge.
                dsEndGauge = pd.DataFrame() # an empty DF
            else:
                dsEndGauge = t
                dsEndGauge['Dof']=0
        # print(dsEndGauge) 
                  
        # put all the gauges together
        gaugeOrd = gaugeOrd[['FspX','FspY','DsDist','Dof']]
        # gaugeOrd = gaugeOrd.append(usEndGauge)
        # gaugeOrd = gaugeOrd.append(dsEndGauge)
        gaugeOrd = pd.concat([gaugeOrd,usEndGauge])
        gaugeOrd = pd.concat([gaugeOrd,dsEndGauge])
        # print(f"Gauges with DOFs on stream order ({ord}): \n",gaugeOrd)
        
        # calculate the min and max downstream distance
        minDist = gaugeOrd['DsDist'].min()
        maxDist = gaugeOrd['DsDist'].max()

        # select the FSPs on the stream order
        fspOrd = fspDf[fspDf['StrOrd']==ord][['FspId','FspX','FspY','DsDist']]
        fspOrd = fspOrd[(fspOrd['DsDist']>=minDist) & (fspOrd['DsDist']<=maxDist)]

        # interpolate DOF for the FSPs with the gauges
        gaugeOrd = gaugeOrd.sort_values('DsDist') # for using np.interp(), x must be ascending!
        fspOrd['Dof'] = np.interp(fspOrd['DsDist'], gaugeOrd['DsDist'], gaugeOrd['Dof'].astype(np.float64))
        # print(fspOrd)

        # append the interpolated SFPs
        # fspDof = fspDof.append(fspOrd,ignore_index=True)
        fspDof = pd.concat([fspDof,fspOrd],ignore_index=True)
        # print(fspDof)
    
    # select and rename columns
    fspDof = fspDof[['FspId','Dof']]
    # print(fspDof)

    # return interpolated DOF for the FSPs
    return fspDof

#
# Decide tiles need to be mapped
# 
def Tiles2Map(libFolder,libName,fspDof='MinDtf',aoiExtent=None):
# Find the tiles need to be mapped for the library
    #
    # Read in the fsp-tile index and tile index files for selecting tiles for mapping
    #
    # read in fsp-tile index file to select the tiles for mapping
    fspIdxFile = os.path.join(libFolder, libName, fspTileIndexFileName)
    fspIdxDf = pd.read_csv(fspIdxFile)
    # print(fspIdxDf)

    # tile index file stores tile and FPP extents for the tile
    tileIdxFile = os.path.join(libFolder, libName, tileIndexFileName)
    tileIdxDf = pd.read_csv(tileIdxFile)
    # print(tileIdxDf)
    
    #
    # Select the tiles for mapping based on the FSPs and fsp-tile index
    #
    # print('Select the tiles need to be mapped ...')
    # for 'MinDtf', 'NumOfFsps' and 'Depression'
    if (isinstance(fspDof,(str)) and fspDof == 'MinDtf') or (isinstance(fspDof,(str)) and fspDof == 'NumOfFsps') or (isinstance(fspDof,(str)) and fspDof == 'Depression'):
        # map all the tiles
        # fspTiles = fspIdxDf['TileId'].drop_duplicates().sort_values().tolist()
        # use tileIdxDf is faster!
        fspTiles = tileIdxDf['TileId'].sort_values().tolist()
        # same as: fspTiles = tileIdxDf['TileId'].sort_values().to_list()
    
    # for constant FSP DOF
    elif isinstance(fspDof, numbers.Number): # constant stage for all the FSPs
        # find which tiles need to be mapped
        # select those tiles whose FSP's DOF > MinDtf
        fspTiles = fspIdxDf[float(fspDof)>fspIdxDf['MinDtf']]
        # print(fspTiles)
        # find the tiles need to be mapped
        # fspTiles = fspTiles['TileId'].unique()
        fspTiles = fspTiles['TileId'].drop_duplicates().sort_values().tolist()

    # for a dataframe of FSPs
    elif isinstance(fspDof, pd.DataFrame):
        # find which tiles need to be mapped
        fspTiles = pd.merge(fspIdxDf, fspDof, how='inner', on=['FspId'])
        # print(fspTiles)
        # select those where DOF > minDtf
        fspTiles = fspTiles[fspTiles['Dof']>fspTiles['MinDtf']]
        # print(fspTiles)
        # find the tiles need to be mapped
        # fspTiles = fspTiles['TileId'].unique()
        fspTiles = fspTiles['TileId'].drop_duplicates().sort_values().tolist()
    else:
        print(f'Unsupported fspDof type {fspDof}!')
        return

    # tiles selected based on the FSPs
    # print('Tiles selected based on FSPs: ', fspTiles)

    # further limit the tiles to those that intersect with the AOI extent
    if aoiExtent is None:
        tiles = fspTiles
    else:
        # select the tiles intersecting AOI extent based on the FPPs' extent of the tile
        aoiMinX,aoiMaxX,aoiMinY,aoiMaxY = aoiExtent
        aoiTiles = tileIdxDf[~((tileIdxDf['FppMinX']>aoiMaxX) | (tileIdxDf['FppMaxX']<aoiMinX))] # rectangles are NOT on left or right of each other
        aoiTiles = aoiTiles[~((aoiTiles['FppMinY']>aoiMaxY) | (aoiTiles['FppMaxY']<aoiMinY))] # rectangles are NOT on top or bottom of each other
        aoiTiles = aoiTiles['TileId'].drop_duplicates().sort_values().tolist()
        print('Tiles selected based on AOI extent: ', aoiTiles)
        # intersect the lists
        tiles = list(set(fspTiles) & set(aoiTiles))
    
    # tiles selected
    if len(tiles) == 0:
        # print('No tile needs to be mapped!')
        return None,None
    else:
        # get each tile's fppExtent
        fppExtents=[]
        for tid in tiles:
            fppExtent = tileIdxDf[tileIdxDf['TileId']==tid].reset_index().loc[0,['FppMinX','FppMaxX','FppMinY','FppMaxY']].values.tolist()
            fppExtents.append(fppExtent)
        return tiles,fppExtents
    
#
# Decide tiles need to be mapped
# 
def Tiles2MapBlob(libBlobSerClient,libName,fspDof='MinDtf',aoiExtent=None):
# Find the tiles need to be mapped for the library
    #
    # Read in the fsp-tile index and tile index files for selecting tiles for ampping
    #
    # create a container client, assuming the container already exists
    container_client = libBlobSerClient.get_container_client(container=libName)
    
    # read in fsp-tile index file to select the tiles for mapping 
    # get blob client
    blob_client = container_client.get_blob_client(fspTileIndexFileName)
    # create a SAS token
    sas_token = azure.storage.blob.generate_blob_sas(
        container_client.account_name,
        container_client.container_name,
        blob_client.blob_name,
        account_key=container_client.credential.account_key,
        permission=["read"],
    )
    # construct the URL
    url = blob_client.url + "?" + urllib.parse.quote_plus(sas_token)
    # read the blob
    fspIdxDf = pd.read_csv(url)
    # print(fspIdxDf)

    # tile index file stores tile and FPP extents for the tile
    # get blob client
    blob_client = container_client.get_blob_client(tileIndexFileName)
    # create a SAS token
    sas_token = azure.storage.blob.generate_blob_sas(
        container_client.account_name,
        container_client.container_name,
        blob_client.blob_name,
        account_key=container_client.credential.account_key,
        permission=["read"],
    )
    # construct the URL
    url = blob_client.url + "?" + urllib.parse.quote_plus(sas_token)
    # read the blob
    tileIdxDf = pd.read_csv(url)
    # print(tileIdxDf)
    
    #
    # Select the tiles for mapping based on the FSPs and fsp-tile index
    #
    # print('Select the tiles need to be mapped ...')
    # for 'MinDtf', 'NumOfFsps' and 'Depression'
    if (isinstance(fspDof,(str)) and fspDof == 'MinDtf') or (isinstance(fspDof,(str)) and fspDof == 'NumOfFsps') or (isinstance(fspDof,(str)) and fspDof == 'Depression'):
        # map all the tiles
        # fspTiles = fspIdxDf['TileId'].drop_duplicates().sort_values().tolist()
        # use tileIdxDf is faster!
        fspTiles = tileIdxDf['TileId'].sort_values().tolist()
        # same as: fspTiles = tileIdxDf['TileId'].sort_values().to_list()
    
    # for constant FSP DOF
    elif isinstance(fspDof, numbers.Number): # constant stage for all the FSPs
        # find which tiles need to be mapped
        # select those tiles whose FSP's DOF > MinDtf
        fspTiles = fspIdxDf[float(fspDof)>fspIdxDf['MinDtf']]
        # print(fspTiles)
        # find the tiles need to be mapped
        # fspTiles = fspTiles['TileId'].unique()
        fspTiles = fspTiles['TileId'].drop_duplicates().sort_values().tolist()

    # for a dataframe of FSPs
    elif isinstance(fspDof, pd.DataFrame):
        # find which tiles need to be mapped
        fspTiles = pd.merge(fspIdxDf, fspDof, how='inner', on=['FspId'])
        # print(fspTiles)
        # select those where DOF > minDtf
        fspTiles = fspTiles[fspTiles['Dof']>fspTiles['MinDtf']]
        # print(fspTiles)
        # find the tiles need to be mapped
        # fspTiles = fspTiles['TileId'].unique()
        fspTiles = fspTiles['TileId'].drop_duplicates().sort_values().tolist()
    else:
        print(f'Unsupported fspDof type {fspDof}!')
        return

    # tiles selected based on the FSPs
    # print('Tiles selected based on FSPs: ', fspTiles)

    # further limit the tiles to those that interset with the AOI extent
    if aoiExtent is None:
        tiles = fspTiles
    else:
        # select the tiles intersecting AOI extent based on the FPPs' extent of the tile
        aoiMinX,aoiMaxX,aoiMinY,aoiMaxY = aoiExtent
        aoiTiles = tileIdxDf[~((tileIdxDf['FppMinX']>aoiMaxX) | (tileIdxDf['FppMaxX']<aoiMinX))] # rectangles are NOT on left or right of each other
        aoiTiles = aoiTiles[~((aoiTiles['FppMinY']>aoiMaxY) | (aoiTiles['FppMaxY']<aoiMinY))] # rectangles are NOT on top or bottom of each other
        aoiTiles = aoiTiles['TileId'].drop_duplicates().sort_values().tolist()
        print('Tiles selected based on AOI extent: ', aoiTiles)
        # intersect the lists
        tiles = list(set(fspTiles) & set(aoiTiles))
    
    # tiles selected
    if len(tiles) == 0:
        # print('No tile needs to be mapped!')
        return None,None
    else:
        # get each tile's fppExtent
        fppExtents=[]
        for tid in tiles:
            fppExtent = tileIdxDf[tileIdxDf['TileId']==tid].reset_index().loc[0,['FppMinX','FppMaxX','FppMinY','FppMaxY']].values.tolist()
            fppExtents.append(fppExtent)
        return tiles,fppExtents
    
#
# Map flood depth with tiled library based on FSP DOF and AOI extent
# 
def MapOneTile(libFolder,libName,tid,fppExtent,cellSize,libSr,fileFormat,outMapFolder,fspDof='MinDtf',aoiExtent=None):
# Map one tile as a GeoTif file   

    # print('Mapping tile: ', tid)
    # print('Read tile file ...')
    if fileFormat == 'snappy':
        # tileName = os.path.join(libFolder, libName, tileFileMainName+'_'+str(tid)+'.gzip') # for gzip
        tileName = os.path.join(libFolder, libName, tileFileMainName+'_'+str(tid)+'.snz') # for snappy
        tdf = pd.read_parquet(tileName) # the original column datatypes are kept when read into a DF!
    elif fileFormat == 'mat':
        # Tiles can also be saved as .mat 
        tileName = os.path.join(libFolder, libName,  tileFileMainName+'_'+str(tid)+'.mat')
        # tileName = os.path.join('~/fldpln/libraries', libName,  tileFileMainName+'_'+str(tid)+'.mat')
        # read from mat file
        matFile = sio.loadmat(tileName)
        df1 = pd.DataFrame(matFile['FspFpps'], columns=relColumnNames[0:3])
        df2 = pd.DataFrame(matFile['DtfFilledDepth'], columns=relColumnNames[-2::])
        tdf = pd.concat([df1, df2], axis=1)
    else:
        print('Unsupported file format!')
        return None

    # Turn FSP-FPP relations to a 2D array
    dtfArray, noData, mapMinX, mapMaxY = TileFspFppRelations2Array(tdf, fppExtent, cellSize, fspDof, aoiExtent)
    
    # map the tile
    if not (dtfArray is None): # needs to be mapped
        # Create and save map as a GeoTif file
        # print('Saving map as a TIF raster ...')
        
        # output file name
        rasterName = os.path.join(outMapFolder,libName+'_tile_'+str(tid)+'.tif')
        
        # create GeoTIFF profile
        # create an Affine transformation from upper left corner coordinates and pixel sizes
        transform = rasterio.transform.from_origin(mapMinX, mapMaxY, cellSize, cellSize)
        profile = dict(
            driver="GTiff",
            height = dtfArray.shape[0], 
            width = dtfArray.shape[1],
            count=1,
            dtype=str(dtfArray.dtype),
            crs=libSr,
            transform=transform,
            nodata=noData
        )
        
        # write to COG file
        with MemoryFile() as memfile:
            # write the array to a memory file
            with memfile.open(**profile) as mem:
                # Populate the input file with numpy array
                mem.write(dtfArray,1)
            # open the memory file reading
            with memfile.open(mode='r') as mem:
                dst_profile = cog_profiles.get("deflate")
                cog_translate(
                    mem,
                    rasterName,
                    dst_profile,
                    in_memory=True,
                    quiet=True,
                )
        return rasterName
    
        # # code to save tile as regular GeoTIFF file
        # with rasterio.open(rasterName, 'w', **profile) as tifRaster:
        #     tifRaster.write(dtfArray, 1)
        # return rasterName
    else:
        return None
    
#
# Map flood depth with tiled library based on FSP DOF and AOI extent using blob
# 
def MapOneTileBlob(libBlobSerClient,libName,tid,fppExtent,cellSize,libSr,fileFormat,mapContainerClient,fspDof='MinDtf',aoiExtent=None):
# Map one tile as a GeoTif file   

    # create a container client, assuming the container already exists
    container_client = libBlobSerClient.get_container_client(container=libName)
    
    # print('Mapping tile: ', tid)
    # print('Read tile file ...')
    if fileFormat == 'snappy':
        tileName = tileFileMainName+'_'+str(tid)+'.snz' # for snappy
        # get blob client
        blob_client = container_client.get_blob_client(tileName)
        # create a SAS token
        sas_token = azure.storage.blob.generate_blob_sas(
            container_client.account_name,
            container_client.container_name,
            blob_client.blob_name,
            account_key=container_client.credential.account_key,
            permission=["read"],
        )
        # construct the URL
        url = blob_client.url + "?" + urllib.parse.quote_plus(sas_token)
        # read the blob
        tdf = pd.read_parquet(url)
        
    elif fileFormat == 'mat':
        print('Not supported yet!')
        # # Tiles can also be saved as .mat 
        # tileName = os.path.join(libFolder, libName,  tileFileMainName+'_'+str(tid)+'.mat')
        # # tileName = os.path.join('~/fldpln/libraries', libName,  tileFileMainName+'_'+str(tid)+'.mat')
        # # read from mat file
        # matFile = sio.loadmat(tileName)
        # df1 = pd.DataFrame(matFile['FspFpps'], columns=relColumnNames[0:3])
        # df2 = pd.DataFrame(matFile['DtfFilledDepth'], columns=relColumnNames[-2::])
        # tdf = pd.concat([df1, df2], axis=1)
    else:
        print('Unsupported file format!')
        return None

    # Turn FSP-FPP relations to a 2D array
    dtfArray, noData, mapMinX, mapMaxY = TileFspFppRelations2Array(tdf, fppExtent, cellSize, fspDof, aoiExtent)
    
    # map the tile
    if not (dtfArray is None): # needs to be mapped
        # Create and save map as a GeoTif file
        # print('Saving map as a TIF raster ...')

        # output file name
        rasterName = libName+'_tile_'+str(tid)+'.tif'
        
        # create GeoTIFF profile
        # create an Affine transformation from upper left corner coordinates and pixel sizes
        transform = rasterio.transform.from_origin(mapMinX, mapMaxY, cellSize, cellSize)
        profile = dict(
            driver="GTiff",
            height = dtfArray.shape[0], 
            width = dtfArray.shape[1],
            count=1,
            dtype=str(dtfArray.dtype),
            crs=libSr,
            transform=transform,
            nodata=noData
        )
       
        # write the array to blob storage as a COG file
        with MemoryFile() as memfile:
            # write the array to a memory file
            with memfile.open(**profile) as mem:
                # Populate the input file with numpy array
                mem.write(dtfArray,1)
            # open the memory file reading
            with memfile.open(mode='r') as mem:
                dst_profile = cog_profiles.get("deflate")
                # translate the memfile into a COG memfile
                with MemoryFile() as mem_dst:
                    # Important, we pass `mem_dst.name` as output dataset path
                    cog_translate(mem, mem_dst.name, dst_profile, in_memory=True,quiet=True)
                    # upload the mem file to blob storage
                    blob_client = mapContainerClient.get_blob_client(rasterName)
                    blob_client.upload_blob(mem_dst, overwrite=True)
        return rasterName
        
#         # code to save tile as a regular GeoTIFF file
#         rasterName = libName+'_tile_'+str(tid)+'.tif'
#         # create an Affine transformation from upper left corner coordinates and pixel sizes
#         transform = rasterio.transform.from_origin(mapMinX, mapMaxY, cellSize, cellSize)

#         # Write data to an in-memory io.BytesIO buffer
#         # open an in-memory buffer
#         with io.BytesIO() as buffer:
#             # write Geotif to the buffer
#             with rasterio.open(buffer, 'w', driver='GTiff',
#                                     height = dtfArray.shape[0], width = dtfArray.shape[1],
#                                     count=1, dtype=str(dtfArray.dtype),
#                                     crs=libSr,
#                                     transform=transform,
#                                     nodata=noData) as tifRaster:
#                 tifRaster.write(dtfArray, 1)
#             # upload the in-memory tif to blob storage
#             buffer.seek(0)
#             blob_client = mapContainerClient.get_blob_client(rasterName)
#             blob_client.upload_blob(buffer, overwrite=True)
    
#         return rasterName
    else:
        return None

#
# Map flood depth with tiled library based on FSP DOF and AOI extent
# 
def MapFloodDepthWithTiles(libFolder,libName,fileFormat,outMapFolder,fspDof='MinDtf',aoiExtent=None):
# fileFormat--'snappy' or 'mat'. 'snappy' format needs to install the 'fastparquet' python package
# fspDof--Cab be 'MinDtf', 'NumOfFsps', 'Depression', a float number, and a DF of FSPs with DOF. 
#         When fspDof is a DF, it must have 3 columns ['FspX','FspY','Dof'] storing FSP's coordinates and DOF
# aoiExtent--rectangle area interested, further limits the tiles decided by the FSPs' DOF. Can be None or a list of [minX,maxX,minY,maxY], default is None.
# keepTileMaps--false or true, default is false
# 
    # create the folder for generating tile maps
    os.makedirs(outMapFolder,exist_ok=True)

    #
    # Read lib meta data file
    #
    metaDataFile = os.path.join(libFolder, libName, metaDataFileName)
    with open(metaDataFile,'r') as jf:
        md = json.load(jf)
    cellSize = md['CellSize']
    srText = md['SpatialReference']
    libSr = rasterio.crs.CRS.from_wkt(srText)

    #
    # decide the tiles to map
    #
    tileIds,fppExtents = Tiles2Map(libFolder,libName,fspDof,aoiExtent=None)
    print('Tiles need to be mapped:',tileIds)

    #
    # map the selected tiles
    #
    if tileIds is None:
        tileTifs = None
    else:
        tileTifs = []
        for tid,fppExtent in zip(tileIds,fppExtents):
            tif=MapOneTile(libFolder,libName,tid,fppExtent,cellSize,libSr,fileFormat,outMapFolder,fspDof,aoiExtent)
            if not(tif is None):
                tileTifs.append(tif)
        if not tileTifs: # empty list
            tileTifs = None
    
    return tileTifs

#
# Map flood depth with tiled library based on FSP DOF and AOI extent
# 
def MapFloodDepthWithTilesAsDag(libFolder,libName,fileFormat,outMapFolder,fspDof='MinDtf',aoiExtent=None):
# fileFormat--'snappy' or 'mat'. 'snappy' format needs to install the 'fastparquet' python package
# fspDof--Cab be 'MinDtf', 'NumOfFsps', 'Depression', a float number, and a DF of FSPs with DOF. 
#         When fspDof is a DF, it must have 3 columns ['FspX','FspY','Dof'] storing FSP's coordinates and DOF
# aoiExtent--rectangle area interested, further limits the tiles decided by the FSPs' DOF. Can be None or a list of [minX,maxX,minY,maxY], default is None.
# keepTileMaps--false or true, default is false
# 
    # create the folder for generating tile maps
    os.makedirs(outMapFolder,exist_ok=True)

    #
    # Read lib meta data file
    #
    metaDataFile = os.path.join(libFolder, libName, metaDataFileName)
    with open(metaDataFile,'r') as jf:
        md = json.load(jf)
    cellSize = md['CellSize']
    srText = md['SpatialReference']
    libSr = rasterio.crs.CRS.from_wkt(srText)

    #
    # decide the tiles to map
    #
    tileIds,fppExtents = Tiles2Map(libFolder,libName,fspDof,aoiExtent=None)
    print('Tiles need to be mapped:',tileIds)

    #
    # map the selected tiles
    #
    if tileIds is None:
        dag = None
        dagRootName = None
    else:
        dag = {}
        for tid,fppExtent in zip(tileIds,fppExtents):
            # tif=MapOneTileBlob(libBlobSerClient,libName,tid,fppExtent,cellSize,libSr,fileFormat,mapContainerClient,fspDof,aoiExtent)
            dag[f'MapOneTile_{tid}'] = (MapOneTile,libFolder,libName,tid,fppExtent,cellSize,libSr,fileFormat,outMapFolder,fspDof,aoiExtent)
        
        # MosaicGtifsBlob(mapContClient,tileTifs,outName,keepTileMaps)  
        dagRootName = 'MapTiles'
        # dag[dagRootName] = (MosaicGtifsBlob,mapContClient,list(dag.keys()),outName,False)
        dag[dagRootName] = (GetTileTifs,list(dag.keys()))

    return dag,dagRootName

#
# Map flood depth with tiled library based on FSP DOF and AOI extent using data in Azure Blob Storage
# 
def MapFloodDepthWithTilesBlob(libBlobSerClient,libName,fileFormat,mapContainerClient,fspDof='MinDtf',aoiExtent=None):
# fileFormat--'snappy' or 'mat'. 'snappy' format needs to install the 'fastparquet' python package
# fspDof--Cab be 'MinDtf', 'NumOfFsps', 'Depression', a float number, and a DF of FSPs with DOF. 
#         When fspDof is a DF, it must have 3 columns ['FspX','FspY','Dof'] storing FSP's coordinates and DOF
# aoiExtent--rectangle area interested, further limits the tiles decided by the FSPs' DOF. Can be None or a list of [minX,maxX,minY,maxY], default is None.
# 
    #
    # Read lib meta data file
    #    
    # create a container client, assuming the container already exists
    container_client = libBlobSerClient.get_container_client(container=libName)
    # get blob client
    blob_client = container_client.get_blob_client(metaDataFileName)
    # read the blob into memory
    streamdownloader = blob_client.download_blob()
    md = json.loads(streamdownloader.readall())
    cellSize = md['CellSize']
    srText = md['SpatialReference']
    libSr = rasterio.crs.CRS.from_wkt(srText)

    #
    # decide the tiles to map
    #
    tileIds,fppExtents = Tiles2MapBlob(libBlobSerClient,libName,fspDof,aoiExtent=None)
    print('Tiles need to be mapped:',tileIds)

    #
    # map the selected tiles
    #
    if tileIds is None:
        tileTifs = None
    else:
        tileTifs = []
        for tid,fppExtent in zip(tileIds,fppExtents):
            tif=MapOneTileBlob(libBlobSerClient,libName,tid,fppExtent,cellSize,libSr,fileFormat,mapContainerClient,fspDof,aoiExtent)
            if not(tif is None):
                tileTifs.append(tif)
    print('Actual tiles mapped:',tileTifs)
    
    return tileTifs

#
# Map flood depth with tiled library based on FSP DOF and AOI extent using data in Azure Blob Storage
# 
def MapFloodDepthWithTilesBlobAsDag(libBlobSerClient,libName,fileFormat,mapContainerClient,fspDof='MinDtf',aoiExtent=None):
# fileFormat--'snappy' or 'mat'. 'snappy' format needs to install the 'fastparquet' python package
# fspDof--Cab be 'MinDtf', 'NumOfFsps', 'Depression', a float number, and a DF of FSPs with DOF. 
#         When fspDof is a DF, it must have 3 columns ['FspX','FspY','Dof'] storing FSP's coordinates and DOF
# aoiExtent--rectangle area interested, further limits the tiles decided by the FSPs' DOF. Can be None or a list of [minX,maxX,minY,maxY], default is None.
# 
    #
    # Read lib meta data file
    #    
    # create a container client, assuming the container already exists
    container_client = libBlobSerClient.get_container_client(container=libName)
    # get blob client
    blob_client = container_client.get_blob_client(metaDataFileName)
    # read the blob into memory
    streamdownloader = blob_client.download_blob()
    md = json.loads(streamdownloader.readall())
    cellSize = md['CellSize']
    srText = md['SpatialReference']
    libSr = rasterio.crs.CRS.from_wkt(srText)

    #
    # decide the tiles to map
    #
    tileIds,fppExtents = Tiles2MapBlob(libBlobSerClient,libName,fspDof,aoiExtent=None)
    print('Tiles need to be mapped:',tileIds)

    #
    # map the selected tiles
    #
    if tileIds is None:
        dag = None
        dagRootName = None
    else:
        dag = {}
        for tid,fppExtent in zip(tileIds,fppExtents):
            # tif=MapOneTileBlob(libBlobSerClient,libName,tid,fppExtent,cellSize,libSr,fileFormat,mapContainerClient,fspDof,aoiExtent)
            dag[f'MapOneTileBlob_{tid}'] = (MapOneTileBlob,libBlobSerClient,libName,tid,fppExtent,cellSize,libSr,fileFormat,mapContainerClient,fspDof,aoiExtent)
        
        # MosaicGtifsBlob(mapContClient,tileTifs,outName,keepTileMaps)  
        dagRootName = 'MapTiles'
        # dag[dagRootName] = (MosaicGtifsBlob,mapContClient,list(dag.keys()),outName,False)
        dag[dagRootName] = (GetTileTifs,list(dag.keys()))

    return dag,dagRootName

#
# place holder function to get tile Geotif files
#
def GetTileTifs(tifFiles):
    tileTifs = []
    for tif in tifFiles:
        if not(tif is None):
            tileTifs.append(tif)
    return tileTifs
    
#
# Turn a dataframe of FSP-FPP relations to a 2D array of flood depth
# returns a np array as the map
#
def TileFspFppRelations2Array(fspFppRels, fppExtent, cellSize, fspDof='MinDtf', aoiExtent=None, noData=-9999):
# The minimum bounding extent of the FPPs in the relations is always used when create the map for the tile!
#
# FspFppRels-- a dataframe of FSP-FPP relations which have the columns of ["FspId", "FppCol", "FppRow", "Dtf", "FilledDepth"] from a tile
# fppExtent--a list of [minX, maxX, minY, maxY], FPP's external extent of the tile and is also used to locate FPP's columns and rows in map coordinate
# fspDof--Cab be 'MinDtf', 'NumOfFsps', 'Depression', a float number, and a DF of FSP depth of flow, i.e., FSP stage. 
#         When fspDof is a table, it must have 3 columns ['FspX','FspY','Dof'] storing the coordinates and "Depth of Flow" for the FSPs
# aoiExtent--None or a rectabgle extent of [minX, maxX, minY, maxY] that INTERSECTs with the fppExtent

# Returns: dtfArray, noData, mapMinX, mapMinY

    tdf = fspFppRels
    # print('Number of FSP-FPP relations:', len(tdf))
    if len(tdf)==0:
        # no FPP needs to be mapping
        return None, None, None, None
    
    # Limit the FPPs in the tile to the AOI extent when provided
    if not (aoiExtent is None):
        # Note that the aoiExtent intersects with the tile, otherwise the tile won't be selected for mapping!
        fppMinX,fppMaxX,fppMinY,fppMaxY = fppExtent
        aoiMinX,aoiMaxX,aoiMinY,aoiMaxY = aoiExtent
        # calculate new FPP extent within the fppExtent
        newFppMinX, newFppMinY= max(fppMinX,aoiMinX), max(fppMinY,aoiMinY)
        newFppMaxX, newFppMaxY= min(fppMaxX,aoiMaxX), min(fppMaxY,aoiMaxY)
        # calculate FPP col & row extent for the new FPP extent
        minFppCol,maxFppCol = int(round((newFppMinX-fppMinX)/cellSize)), int(round((newFppMaxX-fppMinX)/cellSize))-1
        minFppRow,maxFppRow = int(round((fppMaxY-newFppMaxY)/cellSize)), int(round((fppMaxY-newFppMinY)/cellSize))-1
        # select the FPPs within the the new fppExtent based on FppCol & FppRow
        tdf = tdf[(tdf['FppCol']>=minFppCol) & (tdf['FppCol']<=maxFppCol) & (tdf['FppRow']>=minFppRow) & (tdf['FppRow']<=maxFppRow)].copy() # tell pandas we want a copy to avoid "SettingWithCopyWarning" in line 459, 465 

        if len(tdf)==0:
            # no FPP needs to be mapping
            return None, None, None, None

    #
    # Calculate pixel values at each FPP based on the types of fspDof: 'MinDtf', 'NumOfFsps', 'Depression', a constant DOF, and a list of DOF
    # Pixel value at each FPP is saved in the 'Dtf' column.
    #
    if isinstance(fspDof,(str)) and fspDof == 'MinDtf':
        # no FSP DOF is provide, map the minimum DTF at FPPs
        # print('Map the minimum DTF ...')
        # calculate the minimum DTF at each FPP
        tdf = tdf.groupby(['FppCol', 'FppRow'],as_index=False).agg({'Dtf': 'min'}) #,MaxDtf = ('Dtf', max))
        # print(tdf)

    elif isinstance(fspDof,(str)) and fspDof == 'NumOfFsps':
        # no FSP DOF is provide, map the number of FSPs associated with each FPP (neighborhood size of each FPP)
        # print('Map the number of FSPs associated with each FPP ...')
        tdf = tdf.groupby(['FppCol', 'FppRow'],as_index=False).agg({'Dtf':'count'}) #size() # count the # of FSPs associated with each FPP
        # tdf.rename(columns={'size':'Depth'},inplace=True) # inplace changing column name
    
    elif isinstance(fspDof,(str)) and fspDof == 'Depression':
        # print('Map depression depth ...')
        # assign 'Dtf' to filled drpression
        tdf['Dtf'] = tdf['FilledDepth']
        tdf = tdf.groupby(['FppCol', 'FppRow'],as_index=False).agg({'Dtf':'first'})
        
    elif isinstance(fspDof, numbers.Number): # constant stage for all the FSPs
        # all the FSPs in the tile have the same DOF
        # print(f"Map a constant FSP DOF of {fspDof} ...")
        tdf['Dtf'] = float(fspDof) - tdf['Dtf']
        tdf = tdf[tdf['Dtf']>0]

        tdf = tdf.groupby(['FppCol', 'FppRow'],as_index=False).agg({'Dtf':'max','FilledDepth':'first'})
        # add the depth of filled drpression
        tdf['Dtf'] = tdf['Dtf'] + tdf['FilledDepth']

        # code used to find negative flood depth for library 'midkan'
        # t = tdf['Dtf']<0
        # if t.any():
        #     print('Negative DTF!')
        
    # Map the tile with a FSP DOF df
    elif isinstance(fspDof, pd.DataFrame):
        # print('Map with a list of FSPs with DOFs ...')

        # Only keep those relations whose DTF is less than or equal to the max interpolated DOF. 
        # This significantly saves memory and time when merge the relations with the DOFs!
        maxDof = fspDof['Dof'].max()
        tdf = tdf[tdf['Dtf'] < maxDof] # tdf.drop(tdf[tdf['Dtf']<=0].index, inplace=True) # saves memory than tdf = tdf[tdf['Dtf'] > 0]?
        # print('Number of relations to be mapped: ',len(tdf))
        
        # set FSP DOF column data types to speed merge
        fspDof = fspDof.astype(dtype={"FspId":np.int32,"Dof":np.float32},copy=False)

        # create index to speed up merge
        # tdf.astype(np.float32,copy=False).set_index(keys=['FspX','FspY'],inplace=True)
        # fspDof.astype(np.float32,copy=False).set_index(keys=['FspX','FspY'],inplace=True)
        # tdf = pd.merge(tdf, fspDof, how='inner', left_index=True,right_index=True)
        
        # map the FPPs whose FSPs' DOF > the MinDOF
        tdf = pd.merge(tdf, fspDof, how='inner', on=['FspId']) #.astype(np.float32,copy=False)
        
        # calculate DTF
        tdf['Dtf'] = tdf['Dof'] - tdf['Dtf']
        tdf = tdf[tdf['Dtf'] > 0] # tdf.drop(tdf[tdf['Dtf']<=0].index, inplace=True) # saves memory than tdf = tdf[tdf['Dtf'] > 0]?
                
        tdf = tdf.groupby(['FppCol', 'FppRow'],as_index=False).agg({'Dtf':'max','FilledDepth':'first'}) #Depth = ('Dtf', max),FilledDepth=('FilledDepth',first))
        # print(tdf)
        # add the depth of filled drpression
        tdf['Dtf'] = tdf['Dtf'] + tdf['FilledDepth']
        # drop 'FilledDepth'
    else:
        print(f'Unsupported fspDof type {fspDof}!')
        return None, None, None, None
    #
    # Turn relations into 2D array
    #
    if len(tdf)==0:
        # no FPP needs to be mapping
        return None, None, None, None

    # drop off not-used columns in the DF
    tdf = tdf[['FppCol','FppRow','Dtf']]
    # tdf.drop(columns=['FilledDepth'],axis=1,inplace=True)

    # Determine the minimum map extent to speed up the mapping
    # original map extent is the FPP's extent
    mapMinX,mapMaxX,mapMinY,mapMaxY = fppExtent

    # further reduce map extent if FPP extent is reduced
    if (not (aoiExtent is None)) or isinstance(fspDof,(int, float)) or isinstance(fspDof, pd.DataFrame):
        # further reduce the map extent with the FPPs 
        mapMinCol,mapMaxCol = tdf['FppCol'].min(),tdf['FppCol'].max()
        mapMinRow,mapMaxRow = tdf['FppRow'].min(),tdf['FppRow'].max()
        # shift FPP's cols and rows
        tdf['FppCol'] = tdf['FppCol']-mapMinCol
        tdf['FppRow'] = tdf['FppRow']-mapMinRow
        # calculate map's new extent
        mapMaxX = mapMinX + (mapMaxCol+1)*cellSize # this line MUST before the next line as the next line changes mapMinX!
        mapMinX = mapMinX + mapMinCol*cellSize
        mapMinY = mapMaxY - (mapMaxRow+1)*cellSize # this line MUST before the next line as the next line changes mapMaxY!
        mapMaxY = mapMaxY - mapMinRow*cellSize
    
    # print('Map extent (minX, maxX, minY, maxY) :',(mapMinX, mapMaxX, mapMinY, mapMaxY))
    # Calculate map rows and columns
    tCols = int(round((mapMaxX-mapMinX)/cellSize))
    tRows = int(round((mapMaxY-mapMinY)/cellSize))
    # print(f'Turn FSP-FPP relations to a 2D array of {tRows, tCols} ...')
    
    # Initialize the array for saving as a raster
    dtfArray =  np.full(shape=(tRows,tCols),fill_value=noData,dtype=np.float32)
    
    # # update the array with FPP's DTF
    for (idx,idy,dtf) in tdf.itertuples(index=False): # itertuples() is the fastest way of iterating a df
        # idx,idy,dtf = (getattr(row,'FppCol'),getattr(row,'FppRow'),getattr(row,'Dtf')) 
        dtfArray[idy,idx] = dtf
 
    return dtfArray, noData, mapMinX, mapMaxY

#
# Functions to mosaic GeoTifs to replace arcpy-based mosaic function
#
def MosaicGtifs(outMapFolder,gtifs,mosaicTifName, keepTifs=False):
# Mosaic a list of Gtifs into one Gtif using rasterio.merge module. See https://medium.com/spatial-data-science/how-to-mosaic-merge-raster-data-in-python-fb18e44f3c8
# This func may cause memory overflow as the merge() first creates the mosaiced array in memory!

    # open all the Gtifs
    ras2Mosaic = []
    for gtif in gtifs: # assuming no None item in the list
        gtifFullName = os.path.join(outMapFolder,gtif)
        ras = rasterio.open(gtifFullName)
        ras2Mosaic.append(ras)

    # create array representing all source rasters mosaicked together
    mosaicedArray, output = merge(ras2Mosaic)
    
    # close all the tifs
    for ras in ras2Mosaic:
        ras.close()

    # Prepareto write the array into one tif file
    outMeta = ras2Mosaic[0].meta.copy()
    outMeta.update(
        {"driver": "GTiff",
            "height": mosaicedArray.shape[1],
            "width": mosaicedArray.shape[2],
            "transform": output,
        }
    )

    # write to COG file
    mosaicTifFullName = os.path.join(outMapFolder,mosaicTifName)
    with MemoryFile() as memfile:
        # write the array to a memory file
        with memfile.open(**outMeta) as mem:
            # Populate the input file with numpy array
            mem.write(mosaicedArray)
        # open the memory file reading
        with memfile.open(mode='r') as mem:
            dst_profile = cog_profiles.get("deflate")
            cog_translate(
                mem,
                mosaicTifFullName,
                dst_profile,
                in_memory=True,
                quiet=True,
            )

    # # save the mosaiced array to a regular GeoTIFF file
    # mosaicTifFullName = os.path.join(outMapFolder,mosaicTifName)
    # with rasterio.open(mosaicTifFullName, 'w', **outMeta) as m:
    #     m.write(mosaicedArray)

    # delete tile maps
    if not keepTifs: 
        # print('Delete tile maps ...')
        for tm in gtifs:
            os.remove(tm)

    return mosaicTifFullName

#
# Functions to mosaic GeoTifs to replace arcpy-based mosaic function
#
def MosaicGtifsBlob(mapContClient, gtifs, outGtif, keepTifs=False):
# Mosaic a list of Gtifs into one Gtif using rasterio.merge module. See https://medium.com/spatial-data-science/how-to-mosaic-merge-raster-data-in-python-fb18e44f3c8
# This func may cause memory overflow as the merge() first creates the mosaiced array in memory!
    
    # open all the Gtifs
    ras2Mosaic = []
    for gtif in gtifs: # assuming no None tif file names in the list
        blob_client = mapContClient.get_blob_client(gtif)
        # create a SAS token
        sas_token = azure.storage.blob.generate_blob_sas(
            mapContClient.account_name,
            mapContClient.container_name,
            blob_client.blob_name,
            account_key=mapContClient.credential.account_key,
            permission=["read"],
        )
        # Note that the container or the blob must have a access level of Anonymous access
        url = blob_client.url + "?" + urllib.parse.quote_plus(sas_token)
        ras = rasterio.open(url)
        ras2Mosaic.append(ras)

    # create array representing all source rasters mosaicked together
    mosaicedArray, output = merge(ras2Mosaic)
    
    # close all the tifs
    for ras in ras2Mosaic:
        ras.close()

    # Prepareto write the array into one tif file
    outMeta = ras2Mosaic[0].meta.copy()
    outMeta.update(
        {"driver": "GTiff",
            "height": mosaicedArray.shape[1],
            "width": mosaicedArray.shape[2],
            "transform": output,
        }
    )

    # write the array to blob storage as a COG file
    with MemoryFile() as memfile:
        # write the array to a memory file
        with memfile.open(**outMeta) as mem:
            # Populate the input file with numpy array
            mem.write(mosaicedArray) # or mem.write(mosaicedArray,1)
        # open the memory file reading
        with memfile.open(mode='r') as mem:
            dst_profile = cog_profiles.get("deflate")
            # translate the memfile into a COG memfile
            with MemoryFile() as mem_dst:
                # Important, we pass `mem_dst.name` as output dataset path
                cog_translate(mem, mem_dst.name, dst_profile, in_memory=True, quiet=True)
                # upload the mem file to blob storage
                blob_client = mapContClient.get_blob_client(outGtif)
                blob_client.upload_blob(mem_dst, overwrite=True)  

    # #
    # # original code to save the mosaiced array as a regular GeoTIFF file
    # #
    # # Write data to an in-memory io.BytesIO buffer
    # # open an in-memory buffer
    # with io.BytesIO() as buffer:
    #     # write Geotif to the buffer
    #     with rasterio.open(buffer, 'w', **outMeta) as tifRaster:
    #         tifRaster.write(mosaicedArray)
    #     # upload the in-memory tif to blob storage
    #     buffer.seek(0)
    #     blob_client = mapContClient.get_blob_client(outGtif)
    #     blob_client.upload_blob(buffer, overwrite=True)
    
    # delete tile maps
    if not keepTifs: 
        # print('Delete tile maps ...')
        for gtif in gtifs:
            if not(gtif is None):
                blob_client = mapContClient.get_blob_client(gtif)
                blob_client.delete_blob()

    return

#
# Functions to mosaic Geotifs
#
def MosaicGtifsUsingVirtualRaster(gtifs, outGtif):
# Mosaic GeoTifs using GDAL virtual raster
# Easiest way of mosaic very large Gtif. Based on the video at https://www.youtube.com/watch?v=sBBMKbAj8XE

    # Create a XML-based virtual raster file for mosaicing
    vrtFolder = os.path.dirname(outGtif)
    vrtName = os.path.basename(outGtif) + '.vrt'
    vrtFullName = os.path.join(vrtFolder,vrtName)
    vrt = gdal.BuildVRT(vrtFullName, gtifs)

    # access meta data from the first gtif
    ras = rasterio.open(gtifs[0])
    rasMeta = ras.meta
    # get cell size in x and y
    tran = rasMeta['transform'] 
    xCellSize, yCellSize = tran.a, tran.e

    # mosaic the gtifs
    gdal.Translate(outGtif, vrt, xRes = xCellSize, yRes = yCellSize)
    
    # clean up
    vrt = None
    # delete the VRT file
    if os.path.isfile(vrtFullName):
        os.remove(vrtFullName)
    return

#
# A function to download and unzip tiled libraries
#
def DownloadTiledLibrary(libUrl,libName,localLibFolder ):
    # create local folder if not existing
    os.makedirs(localLibFolder,exist_ok=True)

    # If you need to redownload for whatever reason
    if os.path.exists(os.path.join(localLibFolder, libName)):
        shutil.rmtree(os.path.join(localLibFolder, libName))
    os.mkdir(os.path.join(localLibFolder, libName))

    # Download base library
    print(f'Downloading library {libName} ...')
    urllib.request.urlretrieve(libUrl+'/'+libName+'.zip',os.path.join(localLibFolder, libName+'.zip'))
    
    # unzip library
    print(f'Unzip library {libName} ...')
    with zipfile.ZipFile(os.path.join(localLibFolder,libName+'.zip'),'r') as zip_ref:
        zip_ref.extractall(os.path.join(localLibFolder, libName))

    # clean up folder
    os.remove(os.path.join(localLibFolder, libName+'.zip'))
    print("Done for "+libName)
    return