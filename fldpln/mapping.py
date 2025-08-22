"""Module for mapping tile-based library.
"""

# imports from Python standard library
import os
from math import sqrt
import math
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

# from osgeo import gdal # gdal cannot be installed using pip. So we move it to the functions that use it and DO NOT add it in requirements.txt. It's user's responsibility to install it.

from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

# import the common module from THIS package
from .common import *
from .tile import *

############################################################################################################################################
# Functions
############################################################################################################################################

#
# Create folders for storing temporary file and output maps
#
def CreateFolders(outFolder,scratchFolderName='scratch',outMapFolderName='maps',removeExist=True):
    """ Create folders for storing temporary files and output maps.

        Args:
            outFolder (str): output folder
            scratchFolderName (str): name of the folder for storing temporary files
            outMapFolderName (str): name of the folder for storing output maps, default is 'maps'
            removeExist (str): bool whether to remove existing folders, default is True

        Return: 
            tuple: folder for output maps, folder for temporary files.
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
#
def NearestPoint(p1df, x1FieldName, y1FieldName, p2df, x2FieldName, y2FieldName, distFieldName='dist',otherColumns=None):
    """ Join two sets of points by nearest distance. The returned data frame will have, in addition to p1df fields, a new distance field (i.e., distFieldName), 
        plus other fields (i.e., otherColumns) copied from p2df.

        Args:
            p1df (data frame): the first set of points as a pandas DataFrame
            x1FieldName (str): the field name of y coordinates in p1df
            y1FieldName (str): the field name of y coordinates in p1df
            p2df (data frame): the second set of points as a pandas DataFrame
            x2FieldName (str): the field name of x coordinates in p2df
            y2FieldName (str): the field name y coordinates in p2df
            distFieldName (str): the name of the distance field in the returned data frame, default is 'dist'
            otherColumns (list): the names of other fields to be copied from p2df to the returned data frame, default is None.

        Return: 
            data frame: a data frame with the nearest points from p2df for each point in p1df.
    """
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
# Join two sets of points by nearest distance in place (i.e., change p1df)
# 
def NearestPointInPlace(p1df, x1FieldName, y1FieldName, p2df, x2FieldName, y2FieldName, distFieldName='dist', otherColumns=None):
    """ Join two sets of points by nearest distance. p1df will have a new distance field (i.e., distFieldName), plus other fields (i.e., otherColumns) copied from p2df.
        Note that this function changes p1df. This is the only difference between this function and NearestPoint()! This is the only difference between this function and NearestPoint()!

        Args:
            p1df (data frame): the first set of points as a pandas DataFrame
            x1FieldName (str): the field name of y coordinates in p1df
            y1FieldName (str): the field name of y coordinates in p1df
            p2df (data frame): the second set of points as a pandas DataFrame
            x2FieldName (str): the field name of x coordinates in p2df
            y2FieldName (str): the field name y coordinates in p2df
            distFieldName (str): the name of the distance field in the returned data frame, default is 'dist'
            otherColumns (list): the names of other fields to be copied from p2df to the returned data frame, default is None

        Return:
            data frame: p1df with the nearest points from p2df.
    """
    
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
#
def SnapGauges2Fsps(libFolder,libNames,gauges,snapDist=350,gaugeXField='X',gaugeYField='Y',fspColumns=['FspId','FspX','FspY','FilledElev']):
    """ Snap gauges to library FSPs. The function will return a data frame with the nearest FSPs for each gauge in each library. 
        Note that multiple FSPs from different libraries might be snapped to the same gauge!

        Args:
            libFolder (str): the folder where the libraries are located
            libNames (list): a list of library names that the gauges will be snapped to
            gauges (str or data frame): a text file or a pandas DF of gauges. It must have the columns of 'X' and 'Y' in FSP's coordinate system
            snapDist (float): the distance to snap gauges to FSPs, default is 350
            gaugeXField (str): the field name of x coordinates in gauges, default is 'X'
            gaugeYField (str): the field name of y coordinates in gauges, default is 'Y'
            fspColumns (list): the names of FSP columns to be returned, default is ['FspId','FspX','FspY','FilledElev']

        Return:
            data frame: a data frame with the nearest FSPs for each gauge in each library.
    """
   
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
# Snap gauges to library FSPs on Microsoft Planetary Computer (MPC) using Azure Blob Storage.
#
def SnapGauges2FspsBlob(libBlobSerClient,libName,gaugesDf,snapDist=350,gaugeIdField='GaugeLID',gaugeXField='X',gaugeYField='Y'):
    """ Snap gauges to library FSPs on Microsoft Planetary Computer (MPC) using Azure Blob Storage. The function has NOT been checked yet!

        Args:
            libBlobSerClient (BlobServiceClient): a blob service client
            libName (str): the name of the library that the gauges will be snapped to
            gaugesDf (data frame): a pandas DF of gauges. It must have the columns of 'X' and 'Y' in FSP's coordinate system
            snapDist (float): the distance to snap gauges to FSPs, default is 350
            gaugeIdField (str): the field name of gauge IDs in gauges, default is 'GaugeLID'
            gaugeXField (str): the field name of x coordinates in gauges, default is 'X'
            gaugeYField (str): the field name of y coordinates in gauges, default is 'Y'

        Return:
            data frame: a data frame with the nearest FSPs for each gauge in the library.
    """
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
# Snap gauges to library FSPs. What's different from SnapGauges2Fsps() is that this function returns the snapped gauges only?
#
def SnapGaugesToFsps(libFolder,libName,gauges,snapDist=250,gaugeIdField='GaugeLID',gaugeXField='X',gaugeYField='Y'):
    """ Snap gauges to library FSPs. The function will return a data frame with the snapped gauges only.

        Args:
            libFolder (str): the folder where the libraries are located
            libName (str): the name of the library that the gauges will be snapped to
            gauges (str or data frame): a text file or a pandas data frame of gauges. It must have the columns of 'X' and 'Y' in FSP's coordinate system
            snapDist (float): the distance to snap gauges to FSPs, default is 250
            gaugeIdField (str): the field name of gauge IDs in gauges, default is 'GaugeLID'
            gaugeXField (str): the field name of x coordinates in gauges, default is 'X'
            gaugeYField (str): the field name of y coordinates in gauges, default is 'Y'

        Return:
            data frame: a data frame with the snapped gauges only.
    """

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
    """ Snap gauges to library FSPs on Microsoft Planetary Computer (MPC) using Azure Blob Storage. The function is has NOT been checked yet!

        Args:
            libBlobSerClient (BlobServiceClient): a blob service client
            libName (str): the name of the library that the gauges will be snapped to
            gaugesDf (data frame): a pandas DF of gauges. It must have the columns of 'X' and 'Y' in FSP's coordinate system
            snapDist (float): the distance to snap gauges to FSPs, default is 250
            gaugeIdField (str): the field name of gauge IDs in gauges, default is 'GaugeLID'
            gaugeXField (str): the field name of x coordinates in gauges, default is 'X'
            gaugeYField (str): the field name of y coordinates in gauges, default is 'Y'

        Return:
            data frame: a data frame with the snapped gauges only.
    """

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
    """ Interpolate FSP DOF (Depth of Flow, i.e., FSP stage) based on FSP's elevation (fe) or distance (fx) between two gauges.

        Args:
            fx (float or vector of float): FSP's distance from downstream outlet.
            fe (float or vector of float): FSP's elevation. Can be a vector
            gx1 (float): gauge1's distance from downstream outlet
            ge1 (float): gauge1's elevation
            gy1 (float): gauge1's DOF
            gx2 (float): gauge2's distance from downstream outlet
            ge2 (float): gauge2's elevation
            gy2 (float): gauge2's DOF
            weightingType (str): 'V' for vertical distance-based or 'H' for horizontal distance-based, default is 'V'

        Return:
            float or vector of float: interpolated DOF at fx
"""
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
# Interpolate FSP DOF using the DOFs observed at a list of gauges
#
# fx, fe -- FSP distance from downstream outlet and FSP filled DEM elevation
# gx, ge, gy --  gauge distance from downstream outlet, filled DEM elevation and DOF
#
def InterpDofWithGauges(fx,fe,gx,ge,gy,weightingType='V'):
    """ Interpolate FSP DOF (Depth of Flow, i.e., FSP stage) using the DOFs observed at a list of gauges.

        Args:
            fx (vector of float): FSP's distance from downstream outlet.
            fe (vector of float): FSP's elevation.
            gx (vector of float): gauge's distance from downstream outlet.
            ge (vector of float): gauge's elevation.
            gy (vector of float): gauge's DOF.
            weightingType (str): 'V' for vertical distance-based or 'H' for horizontal distance-based, default is 'V'

        Return:
            vector of float: interpolated DOF at fx    
    """
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
    """ Interpolate FSP DOF (Depth of Flow, i.e., FSP stage) from observed gauge DOFs using distance-(horizontal) or 
        elevation-based (vertical) linear interpolation. Different from EstimateFspDofFromGauge(), 
        this function assumes gauge FSPs already have their DOF calculated!

        Args:
            libFolder (str): the folder where the libraries are located
            libName (str): the name of the library that the gauges will be snapped to
            gaugeFspDf (data frame): a data frame of gauge FSPs (i.e., FSPs to which gauges are snapped). It should have at least 4 columns ['lib_name','FspX','FspY','Dof'].
            minGaugeDof (float): min DOF a gauge should have, by default is 1 cm = 0.0328083989501312 foot
            weightingType (str): 'V' for vertical distance-based or 'H' for horizontal distance-based, default is 'V'

        Return:
            data frame: a data frame with interpolated FSP DOFs.
    """
    
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
    """ Estimate/interpolate FSP DOF (Depth of Flow, i.e., FSP stage) from observed gauge DOFs using 
        distance-(horizontal) or elevation-based (vertical) linear interpolation.

        Args:
            libFolder (str): the folder where the libraries are located
            libName (str): the name of the library that the gauges will be snapped to
            gaugeFspDf (data frame): a data frame of gauge FSPs (i.e., FSPs to which gauges are snapped). It should have at least 4 columns ['stage_elevation','lib_name','FspX','FspY'].
            minGaugeDof (float): min DOF a gauge should have, by default is 1 cm = 0.0328083989501312 foot
            weightingType (str): 'V' for vertical distance-based or 'H' for horizontal distance-based, default is 'V'

        Return:
            data frame: a data frame with interpolated FSP DOFs.
    """

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

# #
# # Estimate/interpolate FSP Depth of Flow (i.e., FSP stage) from gauge DOF
# #
# def EstimateFspDofFromGaugeOld(libFolder,libName,gaugeFspDf,minGaugeDof=0.0328084):
# # gaugeFspDf--A DF of gauge FSPs (i.e., FSPs to which gauges are snapped). 
# #       It should have at least 4 columns['stage_elevation','lib_name','FspX','FspY'].
# # minGaugeDof--min DOF a gauge should have, by default is 1 cm = 0.0328083989501312 foot. Negative may occur as incorrect gauge datum
    
#     # select the gauge FSPs in the library
#     gaugeFspDf = gaugeFspDf[gaugeFspDf['lib_name']==libName]

#     # read in FSP and stream order network files
#     fspFile = os.path.join(libFolder, libName, fspInfoFileName)
#     strOrdFile = os.path.join(libFolder, libName, strOrdNetFileName)
#     fspDf = pd.read_csv(fspFile) 
#     strOrdDf = pd.read_csv(strOrdFile) 
# 
#     # Get gauge stream order for interpolation by stream orders
#     gaugeFspDf = pd.merge(gaugeFspDf,fspDf,how='inner',on=['FspX','FspY'])[['FspX','FspY','StrOrd','DsDist','SegId','FilledElev','stage_elevation']]
#     # print(gaugeFspDf)

#     # calculate gauge FSP's DOF
#     gaugeFspDf['Dof'] = gaugeFspDf['stage_elevation'] - gaugeFspDf['FilledElev']
#     # reset gauge FSP DOF, if it's < 0 or nodata, to minGaugeDof
#     gaugeFspDf.loc[(gaugeFspDf['Dof']<=minGaugeDof)|gaugeFspDf['Dof'].isna(),['Dof']] = minGaugeDof
#     # print(gaugeFspDf)

#     # create an empty DF to store interpolated FSP DOFs
#     fspDof = pd.DataFrame(columns=['FspId','FspX','FspY','DsDist','Dof'])
#     # interpolate DoF for each stream order from low to high (low order means high priority!)
#     # get the stream orders with gauges on them
#     strOrds = gaugeFspDf['StrOrd'].drop_duplicates().sort_values().tolist()
#     if len(strOrds)==0:
#         print('No stream found for the gauges!')
#         return None

#     for ord in strOrds:
#         # gauges on the stream order
#         gaugeOrd = gaugeFspDf[gaugeFspDf['StrOrd']==ord].sort_values('DsDist')

#         #
#         # create the upstream ending gauge assuming a level water elevation at the gauge
#         #
#         # get upstream gauge's segment IDs
#         t = gaugeOrd.tail(1)[['SegId','FilledElev','Dof','FspX','FspY']].values.flatten().tolist()
#         upSegId, gElev, dof, gx,gy = t 
#         # get segment FSPs and find the level-off FSP
#         t = fspDf[fspDf['SegId']==upSegId].copy() # tell pandas we want a copy to avoid "SettingWithCopyWarning"
#         t['Dof'] = gElev+dof-t['FilledElev']
#         t = t[t['Dof']>=0].sort_values('DsDist').tail(1)[['FspX','FspY','DsDist','Dof']]
#         # check if the ending gauge is the gauge itself
#         tx,ty = t.iat[0,0], t.iat[0,1]
#         # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
#         if (gx==tx) and (gy==ty):
#             # the gauge is the ending gauge.
#             usEndGauge = pd.DataFrame() # an empty DF
#         else:
#             usEndGauge = t
#         # print(usEndGauge)
        
#         #
#         # create downstream ending gauge
#         #
#         # get the downstream order and junction FSP's coordinates
#         t = strOrdDf[strOrdDf['StrOrd']==ord][['DsStrOrd','JunctionFspX', 'JunctionFspY']].values.flatten().tolist()
#         dsStrOrd,fspx,fspy = t 

#         # whether there is a junction/confluence gauge
#         if dsStrOrd !=0:
#             # there is a downstream order. see whether the junction's DOF has an interpolated DOF
#             juncDf = fspDof[(fspDof['FspX']==fspx) &(fspDof['FspY']==fspy)]
#             if len(juncDf) != 0:
#                 # Junction has DOF. Create downstream ending gauge with the junction FSP
#                 dsEndGauge = juncDf[['FspX','FspY','DsDist','Dof']]
#             else:
#                 juncDf = None

#         # No downstream order or junction FSP
#         if (dsStrOrd == 0) or (juncDf is None):
#             # Create downstream ending gauge with the last FSP in the segment
#             # get the downstream and upstream segment IDs
#             dsSegId, gx,gy = gaugeOrd.head(1)[['SegId','FspX','FspY']].values.flatten().tolist()
#             # get the first FSP on the downstream segment
#             t = fspDf[fspDf['SegId']==dsSegId].tail(1)[['FspX','FspY','DsDist']]
#             # check if the ending gauge is the gauge itself
#             tx,ty = t.iat[0,0], t.iat[0,1]
#             # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
#             if (gx==tx) and (gy==ty):
#                 # the gauge is the ending gauge.
#                 dsEndGauge = pd.DataFrame() # an empty DF
#             else:
#                 dsEndGauge = t
#                 dsEndGauge['Dof']=0
#         # print(dsEndGauge)
                  
#         # put all the gauges together
#         gaugeOrd = gaugeOrd[['FspX','FspY','DsDist','Dof']]
#         # gaugeOrd = gaugeOrd.append(usEndGauge)
#         # gaugeOrd = gaugeOrd.append(dsEndGauge)
#         gaugeOrd = pd.concat([gaugeOrd,usEndGauge])
#         gaugeOrd = pd.concat([gaugeOrd,dsEndGauge])
#         # print(f"Gauges with DOFs on stream order ({ord}): \n",gaugeOrd)
        
#         # calculate the min and max downstream distance
#         minDist = gaugeOrd['DsDist'].min()
#         maxDist = gaugeOrd['DsDist'].max()

#         # select the FSPs on the stream order
#         fspOrd = fspDf[fspDf['StrOrd']==ord][['FspId','FspX','FspY','DsDist']]
#         fspOrd = fspOrd[(fspOrd['DsDist']>=minDist) & (fspOrd['DsDist']<=maxDist)]

#         # interpolate DOF for the FSPs with the gauges
#         gaugeOrd = gaugeOrd.sort_values('DsDist') # for using np.interp(), x must be ascending!
#         fspOrd['Dof'] = np.interp(fspOrd['DsDist'], gaugeOrd['DsDist'], gaugeOrd['Dof'].astype(np.float64))
#         # print(fspOrd)

#         # append the interpolated SFPs
#         # fspDof = fspDof.append(fspOrd,ignore_index=True)
#         fspDof = pd.concat([fspDof,fspOrd],ignore_index=True)
#         # print(fspDof)
    
#     # select and rename columns
#     fspDof = fspDof[['FspId','Dof']]
#     # print(fspDof)

#     # return interpolated DOF for the FSPs
#     return fspDof

# #
# # Estimate FSP Depth of Flow (DoF), i.e., FSP stage from gauges
# #
# def EstimateFspDofFromGaugeReallyOld(libFolder,libName,gaugeDf,gaugeElevField,minGaugeDof=0.0328084):
# # gaugeElevField --  field in gaugeDf that stores gauge's water surface elevation
# # gaugeDf--A DF with snapped FSP columns ['FspX','FspY','FspFilledElev','Dist']
# # minGaugeDof--min DOF a gauge should have, by default is 1 cm = 0.0328083989501312 foot. Negative may occur as incorrect gauge datum
    
#     # calculate FSP DOF
#     gaugeDf['Dof'] = gaugeDf[gaugeElevField] - gaugeDf['FspFilledElev']
#     # reset DOF, if it's < 0 or nodata, to minGaugeDof
#     gaugeDf.loc[(gaugeDf['Dof']<=minGaugeDof)|gaugeDf['Dof'].isna(),['Dof']] = minGaugeDof
#     # print(gaugeDf)

#     # read in FSP and stream order network files
#     fspFile = os.path.join(libFolder, libName, fspInfoFileName)
#     strOrdFile = os.path.join(libFolder, libName, strOrdNetFileName)
#     fspDf = pd.read_csv(fspFile) 
#     strOrdDf = pd.read_csv(strOrdFile) 

#     # Get gauge stream order for interpolation by stream orders
#     gaugeDf = pd.merge(gaugeDf,fspDf,how='inner',on=['FspX','FspY'])[['FspX','FspY','Dof','StrOrd','DsDist','SegId','FilledElev']]
#     # print(gaugeDf)

#     # create an empty DF to store interpolated FSP DOFs
#     fspDof = pd.DataFrame(columns=['FspId','FspX','FspY','DsDist','Dof'])
#     # interpolate DoF for each stream order from low to high (low order means high priority!)
#     # get the stream orders with gauges on them
#     strOrds = gaugeDf['StrOrd'].drop_duplicates().sort_values().tolist()
#     if len(strOrds)==0:
#         print('No stream found for the gauges!')
#         return None

#     for ord in strOrds:
#         # gauges on the stream order
#         gaugeOrd = gaugeDf[gaugeDf['StrOrd']==ord].sort_values('DsDist')

#         #
#         # create the upstream ending gauge assuming a level water elevation at the gauge
#         #
#         # get upstream gauge's segment IDs
#         t = gaugeOrd.tail(1)[['SegId','FilledElev','Dof','FspX','FspY']].values.flatten().tolist()
#         upSegId, gElev, dof, gx,gy = t 
#         # get segment FSPs and find the level-off FSP
#         t = fspDf[fspDf['SegId']==upSegId].copy() # tell pandas we want a copy to avoid "SettingWithCopyWarning"
#         t['Dof'] = gElev+dof-t['FilledElev']
#         t = t[t['Dof']>=0].sort_values('DsDist').tail(1)[['FspX','FspY','DsDist','Dof']]
#         # check if the ending gauge is the gauge itself
#         tx,ty = t.iat[0,0], t.iat[0,1]
#         # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
#         if (gx==tx) and (gy==ty):
#             # the gauge is the ending gauge.
#             usEndGauge = pd.DataFrame() # an empty DF
#         else:
#             usEndGauge = t
#         # print(usEndGauge)
        
#         #
#         # create downstream ending gauge
#         #
#         # get the downstream order and junction FSP's coordinates
#         t = strOrdDf[strOrdDf['StrOrd']==ord][['DsStrOrd','JunctionFspX', 'JunctionFspY']].values.flatten().tolist()
#         dsStrOrd,fspx,fspy = t 

#         # whether there is a junction/confluence gauge
#         if dsStrOrd !=0:
#             # there is a downstream order. see whether the junction's DOF has an interpolated DOF
#             juncDf = fspDof[(fspDof['FspX']==fspx) &(fspDof['FspY']==fspy)]
#             if len(juncDf) != 0:
#                 # Junction has DOF. Create downstream ending gauge with the junction FSP
#                 dsEndGauge = juncDf[['FspX','FspY','DsDist','Dof']]
#             else:
#                 juncDf = None

#         # No downstream order or junction FSP
#         if (dsStrOrd == 0) or (juncDf is None):
#             # Create downstream ending gauge with the last FSP in the segment
#             # get the downstream and upstream segment IDs
#             dsSegId, gx,gy = gaugeOrd.head(1)[['SegId','FspX','FspY']].values.flatten().tolist()
#             # get the first FSP on the downstream segment
#             t = fspDf[fspDf['SegId']==dsSegId].tail(1)[['FspX','FspY','DsDist']]
#             # check if the ending gauge is the gauge itself
#             tx,ty = t.iat[0,0], t.iat[0,1]
#             # same as: tx,ty = t[['FspX','FspY']].values.flatten().tolist()
#             if (gx==tx) and (gy==ty):
#                 # the gauge is the ending gauge.
#                 dsEndGauge = pd.DataFrame() # an empty DF
#             else:
#                 dsEndGauge = t
#                 dsEndGauge['Dof']=0
#         # print(dsEndGauge)
                  
#         # put all the gauges together
#         gaugeOrd = gaugeOrd[['FspX','FspY','DsDist','Dof']]
#         # gaugeOrd = gaugeOrd.append(usEndGauge)
#         # gaugeOrd = gaugeOrd.append(dsEndGauge)
#         gaugeOrd = pd.concat([gaugeOrd,usEndGauge])
#         gaugeOrd = pd.concat([gaugeOrd,dsEndGauge])
#         # print(f"Gauges with DOFs on stream order ({ord}): \n",gaugeOrd)
        
#         # calculate the min and max downstream distance
#         minDist = gaugeOrd['DsDist'].min()
#         maxDist = gaugeOrd['DsDist'].max()

#         # select the FSPs on the stream order
#         fspOrd = fspDf[fspDf['StrOrd']==ord][['FspId','FspX','FspY','DsDist']]
#         fspOrd = fspOrd[(fspOrd['DsDist']>=minDist) & (fspOrd['DsDist']<=maxDist)]

#         # interpolate DOF for the FSPs with the gauges
#         gaugeOrd = gaugeOrd.sort_values('DsDist') # for using np.interp(), x must be ascending!
#         fspOrd['Dof'] = np.interp(fspOrd['DsDist'], gaugeOrd['DsDist'], gaugeOrd['Dof'].astype(np.float64))
#         # print(fspOrd)

#         # append the interpolated SFPs
#         # fspDof = fspDof.append(fspOrd,ignore_index=True)
#         fspDof = pd.concat([fspDof,fspOrd],ignore_index=True)
#         # print(fspDof)
    
#     # select and rename columns
#     fspDof = fspDof[['FspId','Dof']]
#     # print(fspDof)

#     # reset DOF if it's less than minGaugeDof
#     fspDof.loc[(fspDof['Dof']<=minGaugeDof),['Dof']] = minGaugeDof

#     # return interpolated DOF for the FSPs
#     return fspDof

#
# Estimate FSP Depth of Flow (DoF), i.e., FSP stage from gauges
#
def EstimateFspDofFromGaugeBlob(libBlobSerClient,libName,gaugeDf,gaugeElevField,minGaugeDof=0.0328084):
    """ Estimate FSP Depth of Flow (DoF), i.e., FSP stage from gauges on Microsoft Planetary Computer using Azure Blob Storage.

        Args:
            libBlobSerClient (BlobServiceClient): a BlobServiceClient object
            libName (str): the name of the library that the gauges will be snapped to
            gaugeDf (data frame): a data frame of gauges. It should have at least 4 columns ['FspX','FspY','FspFilledElev','Dist']
            gaugeElevField (str): the field in gaugeDf that stores gauge's water surface elevation
            minGaugeDof (float): min DOF a gauge should have, default is 1 cm = 0.0328083989501312 foot. Negative DOF may occur as incorrect gauge datum

        Return:
            data frame: a data frame with interpolated FSP DOFs.
    """

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
    """ Decide the tiles need to be mapped for the library.

        Args:
            libFolder (str): the folder where the libraries are stored
            libName (str): the name of the library
            fspDof (str, float, or data frame): the FSP DOF for mapping flood depth. default is 'MinDtf'.
                If it's a string, it can be 'MinDtf', 'NumOfFsps', or 'Depression'.
                If it's a float, it's a constant stage for all the FSPs.
                If it's a data frame, it's a data frame of FSPs with DOF.
            aoiExtent (list): the extent of the area of interest [minX,maxX,minY,maxY]. default is None.

        Return:
            tuple: a list of tile IDs, a list of tile FPP extents
    """

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
    """ Decide the tiles need to be mapped for the library on Microsoft Planetary Computer using Azure Blob Storage.

        Args:
            libBlobSerClient (BlobServiceClient): a BlobServiceClient object
            libName (str): the name of the library
            fspDof (str, float, or data frame): the FSP DOF for mapping flood depth. default is 'MinDtf'.
                If it's a string, it can be 'MinDtf', 'NumOfFsps', or 'Depression'.
                If it's a float, it's a constant stage for all the FSPs.
                If it's a data frame, it's a data frame of FSPs with DOF.
            aoiExtent (list): the extent of the area of interest [minX,maxX,minY,maxY]. default is None.

        Return:
            tuple: a list of tile IDs, a list of tile FPP extents
    """

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
    """ Map one tile as a GeoTif file based on FSP DOF and AOI extent

        Args:
            libFolder (str): the folder where the libraries are stored
            libName (str): the name of the library
            tid (int): the tile ID
            fppExtent (list): the extent of the FPPs in the tile [minX,maxX,minY,maxY]
            cellSize (float): the cell size of the raster
            libSr (str): the spatial reference of the library
            fileFormat (str): the file format of the tile, 'snappy' or 'mat'
            outMapFolder (str): the folder where the mapped tiles will be saved
            fspDof (str, float, or data frame): the FSP DOF for mapping flood depth. default is 'MinDtf'.
                If it's a string, it can be 'MinDtf', 'NumOfFsps', or 'Depression'.
                If it's a float, it's a constant stage for all the FSPs.
                If it's a data frame, it's a data frame of FSPs with DOF.
            aoiExtent (list): the extent of the area of interest [minX,maxX,minY,maxY]. default is None 

        Return:
            str: the name of the mapped tile as a GeoTif file
    """

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
    """ Map one tile as a GeoTif file based on FSP DOF and AOI extent on Microsoft Planetary Computer using Azure Blob Storage.

        Args:
            libBlobSerClient (BlobServiceClient): a BlobServiceClient object
            libName (str): the name of the library
            tid (int): the tile ID
            fppExtent (list): the extent of the FPPs in the tile [minX,maxX,minY,maxY]
            cellSize (float): the cell size of the raster
            libSr (str): the spatial reference of the library
            fileFormat (str): the file format of the tile, 'snappy' or 'mat'
            mapContainerClient (ContainerClient): a ContainerClient object for the container to store the mapped tiles
            fspDof (str, float, or data frame): the FSP DOF for mapping flood depth. default is 'MinDtf'.
                If it's a string, it can be 'MinDtf', 'NumOfFsps', or 'Depression'.
                If it's a float, it's a constant stage for all the FSPs.
                If it's a data frame, it's a data frame of FSPs with DOF.
            aoiExtent (list): the extent of the area of interest [minX,maxX,minY,maxY], default is None

        Return:
            str: the name of the mapped tile as a GeoTif file
    """

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
    """ Map flood depth with tiled library based on FSP DOF and AOI extent
    
        Args:
            libFolder (str): the folder where the libraries are stored
            libName (str): the name of the library
            fileFormat (str): the file format of the tile, 'snappy' or 'mat'
            outMapFolder (str): the folder where the mapped tiles will be saved
            fspDof (str, float, or data frame): the FSP DOF for mapping flood depth. default is 'MinDtf'. 
                If it's a string, it can be 'MinDtf', 'NumOfFsps', or 'Depression'. 
                If it's a float, it's a constant stage for all the FSPs. 
                If it's a data frame, it's a data frame of FSPs with DOF.
            aoiExtent (list): the extent of the area of interest [minX,maxX,minY,maxY]. default is None

        Return:
            list: a list of mapped tile names as GeoTif files.
    """

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
    """ Map flood depth with tiled library based on FSP DOF and AOI extent as a Directed Acyclic Graph (DAG)
    
        Args:
            libFolder (str): the folder where the libraries are stored
            libName (str): the name of the library
            fileFormat (str): the file format of the tile, 'snappy' or 'mat'
            outMapFolder (str): the folder where the mapped tiles will be saved
            fspDof (str, float, or data frame): the FSP DOF for mapping flood depth. default is 'MinDtf'. 
                If it's a string, it can be 'MinDtf', 'NumOfFsps', or 'Depression'. 
                If it's a float, it's a constant stage for all the FSPs. 
                If it's a data frame, it's a data frame of FSPs with DOF.
            aoiExtent (list): the extent of the area of interest [minX,maxX,minY,maxY]. default is None

        Return:
            tuple: a Directed Acyclic Graph (DAG) and the root node name.
    """
 
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
    """ Map flood depth with tiled library based on FSP DOF and AOI extent on Microsoft Planetary Computer using data in Azure Blob Storage.
    
        Args:
            libBlobSerClient (BlobServiceClient): a BlobServiceClient object
            libName (str): the name of the library
            fileFormat (str): the file format of the tile, 'snappy' or 'mat'
            mapContainerClient (ContainerClient): a ContainerClient object for the container to store the mapped tiles
            fspDof (str, float, or data frame): the FSP DOF for mapping flood depth. default is 'MinDtf'. 
                If it's a string, it can be 'MinDtf', 'NumOfFsps', or 'Depression'. 
                If it's a float, it's a constant stage for all the FSPs. 
                If it's a data frame, it's a data frame of FSPs with DOF.
            aoiExtent (list): the extent of the area of interest [minX,maxX,minY,maxY]. default is None

        Return:
            list: a list of mapped tile names as GeoTif files
    """

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
    """ Map flood depth with tiled library based on FSP DOF and AOI extent on Microsoft Planetary Computer using data in Azure Blob Storage 
        as a Directed Acyclic Graph (DAG).
    
        Args:
            libBlobSerClient (BlobServiceClient): a BlobServiceClient object
            libName (str): the name of the library
            fileFormat (str): the file format of the tile, 'snappy' or 'mat'
            mapContainerClient (ContainerClient): a ContainerClient object for the container to store the mapped tiles
            fspDof (str, float, or data frame): the FSP DOF for mapping flood depth. default is 'MinDtf'. 
                If it's a string, it can be 'MinDtf', 'NumOfFsps', or 'Depression'. 
                If it's a float, it's a constant stage for all the FSPs. 
                If it's a data frame, it's a data frame of FSPs with DOF.
            aoiExtent (list): the extent of the area of interest [minX,maxX,minY,maxY]. default is None

        Return:
            tuple: a Directed Acyclic Graph (DAG) and the root node name
    """

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
    """ Get tile Geotif files
    
        Args:
            tifFiles (list): a list of tile Geotif files

        Return:
            list: a list of tile Geotif files
    """

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
    """ Turn a dataframe of FSP-FPP relations to a 2D array of flood depth. 
        The minimum bounding extent of the FPPs in the relations is always used when create the map for the tile!
    
        Args:
            fspFppRels (data frame): a dataframe of FSP-FPP relations which have the columns of ["FspId", "FppCol", "FppRow", "Dtf", "FilledDepth"] from a tile
            fppExtent (list): a list of [minX, maxX, minY, maxY], FPP's external extent of the tile and is also used to locate FPP's columns and rows in map coordinate
            cellSize (float): the cell size of the raster
            fspDof (str, float, or data frame): the FSP DOF for mapping flood depth. default is 'MinDtf'.
                If it's a string, it can be 'MinDtf', 'NumOfFsps', or 'Depression'.
                If it's a float, it's a constant stage for all the FSPs.
                If it's a data frame, it's a data frame of FSPs with DOF.
            aoiExtent (list): the extent of the area of interest [minX,maxX,minY,maxY]. default is None
            noData (int): the no data value, default is -9999

        Return:
            tuple: a tuple of the np array as the map, the no data value, the minimum X value, and the minimum Y value
    """

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
    """ Mosaic a list of GeoTifs into one GeoTif file using rasterio.merge module.
        See https://medium.com/spatial-data-science/how-to-mosaic-merge-raster-data-in-python-fb18e44f3c8.
        This func may cause memory overflow as the merge() first creates the mosaiced array in memory!
    
        Args:
            outMapFolder (str): the folder where the mosaiced tif will be saved
            gtifs (list): a list of tile GeoTifs to be mosaiced
            mosaicTifName (str): the name of the mosaiced GeoTif file
            keepTifs (bool): whether to keep the tile GeoTifs, default is False

        Return:
            str: the name of the mosaiced GeoTif.
    """

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
    """ Mosaic a list of GeoTifs into one GeoTif file using rasterio.merge module on Microsoft Planetary Computer using data in Azure Blob Storage.
        See https://medium.com/spatial-data-science/how-to-mosaic-merge-raster-data-in-python-fb18e44f3c8.
        This func may cause memory overflow as the merge() first creates the mosaiced array in memory!
        
        Args:
            mapContClient (ContainerClient): a ContainerClient object for the container to store the mosaiced tif
            gtifs (list): a list of tile GeoTifs to be mosaiced
            outGtif (str): the name of the mosaiced GeoTif file
            keepTifs (bool): whether to keep the tile GeoTifs, default is False

        Return:
            None: no return.
    """
  
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
    """ Mosaic a list of GeoTifs into one GeoTif file using GDAL virtual raster.
        Easiest way of mosaic very large Gtif. Based on the video at https://www.youtube.com/watch?v=sBBMKbAj8XE

        Args:
            gtifs (list): a list of tile GeoTifs to be mosaiced
            outGtif (str): the name of the mosaiced GeoTif file

        Return:
            None: no return
    """

    from osgeo import gdal # since gdal cannot be installed using pip, we leave the import here and it's up to the user to install gdal.

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
    """ Download and unzip tiled libraries.
    
        Args:
            libUrl (str): the url of the library
            libName (str): the name of the library
            localLibFolder (str): the folder where the library will be saved

        Return:
            None: no return.
    """

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

#############################################################################################################################
# Reach (reach tree) class for volume-based DOF interpolation
#############################################################################################################################
# import necessary packages
from scipy.interpolate import interp1d

#
# A reach is a list of stream segments (in FLDPLN's term) between the start of a stream or a confluence and an immediate downstream confluence or the end of a stream 
# A reach stream network is a tree where the outlet reach is the root and each node is a reach consisting of an ordered (down-->up stream) segments.
# Each reach is one of the following types:
#   TC: terminal (i.e., head-water) reach that flows into a confluence,
#   TO: terminal reach that flows into network outlet, 
#   CC: confluence reach that flows into a confluence,
#   CO: confluence reach that flows into network outlet.
#
#
# A reach tree/network class
#
class ReachNetwork: # This class is NOT used and may have errors. It's just a place holder for future implementation
    def __init__(self, root=None):
        self.root = root  # root node of the reach tree
 
    # @classmethod
    # def create_network_from_seginfo(cls, seg, segInfoDf, reachId=0):
    #     ''' Generate a reach network tree from an outlet segment ID. The reach that contains the outlet/start segment is the root reach of the reach network/tree.
    #         seg: segment ID of the outlet/start segment
    #         segInfoDf: segment info DataFrame with columns ['SegId', 'DsSegId'] which stores segment network connectivity
    #         reachId: start reach ID, default is 0
    #     '''        
    #     return cls(GenerateReachNetworkTree(seg, segInfoDf, reachId))
    
    def insert_reach(self, reach, parent=None):
        # insert a reach into a tree
        if self.root is None:
            self.root = reach
            parent = self.root
        else:
            parent.add_child(reach)
            parent = parent.children[0]
        return parent
    
    def add_reach(self, reach):
        if self.root is None:
            self.root = reach
        else:
            self.root.add_child(reach)
        self.reach_count += 1

    def show_network(self):
        if self.root is not None:
            self.root.show_tree()
        else:
            print('No reach network generated!')

#
# Reach class
#
class Reach: 
    def __init__(self, id=0, seg_ids=[]):
        self.id = id            # reach ID
        self.seg_ids = seg_ids  # reach segment ids
        self.type = None        # reach type: TC, TO, CC, or CO where T is for terminal (i.e., head-water), C is for confluence reach, and O is for outlet
        self.children = []      # children nodes, i.e., upstream reaches
        # additional attributes may be added when applying a function to the reach using apply_func method
        
    def add_child(self, child_node):
        self.children.append(child_node)

    def remove_child(self, child_node):
         self.children.remove(child_node)
    
    def breadth_first_traverse(self):
        print(self.seg_ids, end=" ")
        for child in self.children:
            child.breadth_first_traverse()

    def breadth_first_traverse2(self): # none recursive version
        nodes_list = [self]
        while nodes_list:
            current_node = nodes_list.pop(0)
            print(current_node.seg_ids, end=" ")
            nodes_list.extend(current_node.children)

    def depth_first_traverse(self):
        if len(self.children) == 0:
            # leaf node
            print((self.id, self.seg_ids[::-1], self.type, self.down_volume), end=" ")
            return
        else:
            for child in self.children:
                child.depth_first_traverse()
            print((self.id, self.seg_ids[::-1], self.type, self.down_volume), end=" ")
  
    def edges_updown(self):
        edges = []
        if len(self.children) == 0:
            return edges
        else:
            for child in self.children:
                edges.extend(child.edges_updown())
                edges.extend([(child.id, self.id)]) 
                # edges.extend([(child.seg_ids[::-1], self.seg_ids[::-1])]) # .reverse() change the original list and returns None
            return edges
    
    def edges_downup(self):
        edges = []
        if len(self.children) == 0:
            return edges
        else:
            for child in self.children:
                edges.extend([(self.id, child.id)])
                # edges.extend([(self.seg_ids, child.seg_ids)])
                edges.extend(child.edges_downup())
            return edges
    
    def show_tree(self):
        if self is not None:
                # show tree nodes
                print('network nodes:', end=" ")
                self.depth_first_traverse()
                print()

                # show tree edges
                edges = self.edges_updown()
                # edges = tree.edges_downup()
                print('network edges (updown):', edges)     
        else:
            print('No tree generated!') 
        return self
    
    #
    # Turn reach attributes into a list of tuples
    #
    def reach_attrs_to_list(self, attrs=['id', 'seg_ids'], traverse_type='Depth-First'):
        ''' Turn reach attributes into a list of tuples in a specific order.
            attrs: list of attributes to be included in the output list
            traverse_type: 'Depth-First' or 'Breadth-First'
        '''
        if self is None:
            print('No reach, tree is empty!')
            return []
        else:
            attrLst = []
            if traverse_type == 'Depth-First':
                if len(self.children) == 0:
                    # leaf node
                    t = [getattr(self, a) for a in attrs]
                    attrLst.extend([t])
                    return attrLst
                else:
                    # traverse the children nodes
                    for child in self.children:
                        attrLst.extend(child.reach_attrs_to_list(attrs, traverse_type))
                        
                    # add the current reach attributes to the list
                    t = [getattr(self, a) for a in attrs]
                    attrLst.extend([t])
                    return attrLst
            else: # assume traverse_type == 'Breadth-First'!
                t = [getattr(self, a) for a in attrs]
                attrLst.extend([t])
                for child in self.children:
                    attrLst.extend(child.reach_attrs_to_list(attrs, traverse_type))
                return attrLst
        
    #
    # filter gauged reaches and their downstream reaches from a reach tree. Keep the reach if it has least one gauge on it or any of its upstream reaches has a gauge.
    #
    def filter_gauged_reaches(self, gaugedSegLst, parent=None):
        ''' Filter gauged reaches and their downstream reaches from a reach tree. Keep the reach if it has least one gauge on it or any of its upstream reaches has a gauge.
        
        Parameters:
                gaugedSegLst: list of gauged segment IDs
                parent: parent node of the current reach, None for the root node
        '''
        # filter the upstream reaches of the current reach
        children = self.children.copy() # NEED to make a copy of the children list of current reach as the children list will be modified in the recursion
        for child in children:
            child.filter_gauged_reaches(gaugedSegLst, self)

        # process the current reach
        # find the gauged segments on the current reach
        gsegs = [s for s in self.seg_ids if s in gaugedSegLst]
        
        if len(self.children) == 0 and len(gsegs) == 0:
            # A terminal reach with no gauged segments, remove it from the tree
            if parent is not None:  
                parent.remove_child(self)
            else:
                # current reach is the root node and the tree is empty
                return None

        return self

    #
    # Apply a function to each reach in the Deep-First order
    # 
    def apply_func(self, order, func, *args):
        ''' Apply a function to each reach in the Deep-First order.
            Parameters:
            order: 'Depth-First' or 'Breadth-First', 
                   'Depth-First' applies the function to the reach and its children first, then to the parent reach,
                   'Breadth-First' applies the function to the parent reach first, then to its children. This has NOT been implemented yet.
            func: function to be applied to each reach
            args: additional arguments to be passed to the function
        '''
        if len(self.children) == 0: 
            # A terminal reach
            # Apply the function to the terminal reach
            func(self, *args)
        else:
            # A confluence reach 
            # Applying the function to its upstream reaches first
            for child in self.children:
                child.apply_func(order, func, *args)

            # Apply the function to the confluence reach
            func(self, *args)
        return self

##################################################################################################################################
# functions to interpolate reach FSP DOF using gauged volume
##################################################################################################################################

def InterpolateReachFspDof(reach, libPath, gaugeFspDf, segInfo, libFspDf, dsPropSegNum=2, outVarName='fsp_dof'):
    ''' Interpolate reach FSP DOF from gauged FSPs through segment volumes.
        
        Parameters:
            reach: a reach node with segment IDs and gauged segments
            libPath: path to the folder where segment's DOF-volume files are stored
            gaugeFspDf: DataFrame with gauged FSPs including columns ['lib_name', 'SegId', 'FspX', 'FspY', 'FilledElev', 'DsDist', 'Dof']
            segsInfo: DataFrame with all segment information including columns [SegId, MidDsDist]
            libFspDf: DataFrame with library FSPs including columns ['lib_name', 'SegId', 'FspX', 'FspY', 'FilledElev', 'DsDist']
            dsPropSegNum: number of segments to propagate the volume downstream from the most downstream gauged segment for TO & CO reaches, default is 2
            outVarName: name of the output variable to store interpolated segment volumes, default is

        Note: This function stores the interpolated reach downstream volume as an attribute of the reach in addition to the interpolated FSP DOF.
    '''

    # Create a segment-id:mid downstream distance dictionary
    segDistDict = dict(zip(segInfo['SegId'], segInfo['MidDsDist']))
    # all gauged segments in the library
    libGaugedSegs = gaugeFspDf['SegId'].to_list() 

    #
    # Prepare gauged segments to include detailed gauge information on each segment
    # Note that a segment may have multiple gauges!
    #
    # find unique gauged segments on the reach in the order of the reach segment IDs, i.e., downstream to upstream
    gsegs = [s for s in reach.seg_ids if s in libGaugedSegs] 
    # # sort gauges on each segment by downstream distance and get their information. Is the for loop implementation more efficient???
    # gInfo = [{'FspX':       gaugeFspDf[gaugeFspDf['SegId']==s].sort_values('DsDist',ascending=False)['FspX'].to_list(), 
    #          'FspY':        gaugeFspDf[gaugeFspDf['SegId']==s].sort_values('DsDist',ascending=False)['FspY'].to_list(), 
    #          'FilledElev':  gaugeFspDf[gaugeFspDf['SegId']==s].sort_values('DsDist',ascending=False)['FilledElev'].to_list(),
    #          'DsDist':      gaugeFspDf[gaugeFspDf['SegId']==s].sort_values('DsDist',ascending=False)['DsDist'].to_list(), 
    #          'Dof':         gaugeFspDf[gaugeFspDf['SegId']==s].sort_values('DsDist',ascending=False)['Dof'].to_list()} for s in gsegs]
    
    gInfo = []
    for s in gsegs:
        # sort gauges on each segment by downstream distance and get their information.
        g = gaugeFspDf[gaugeFspDf['SegId']==s].sort_values('DsDist',ascending=False)
        d = {
            'FspX':        g['FspX'].to_list(), 
            'FspY':        g['FspY'].to_list(), 
            'FilledElev':  g['FilledElev'].to_list(),
            'DsDist':      g['DsDist'].to_list(), 
            'Dof':         g['Dof'].to_list()
        }
        gInfo.append(d) # append the gauge information for the segment

    # create a segment gauge information dictionary of {segment-id: {gauge-info}}
    gsegs_dict = dict(zip(gsegs, gInfo)) # gsegs stores the gauged segment IDs in the order of downstream to upstream; gsegs_dict is a dictionary (NO ORDER) of gauged segments with their gauge information

    #
    # Calculate segment DOF from gauged DOFs on each gauged segment and calculate segment volume from the segment DOF
    # 
    # calculate mean gauged DOFs as the segment DOF
    gdofs = [(k, gsegs_dict[k]['Dof']) for k in gsegs_dict]
    sdofs = [(sid, sum(d)/len(d) if len(d)>0 else math.nan) for sid, d in gdofs]
    
    # add to the dictionary of gauged segments
    for sid, dof in sdofs:
        gsegs_dict[sid]['SegMidDsDist'] = segDistDict[sid] # mid downstream distance of the segment
        gsegs_dict[sid]['SegDof'] = dof
        gsegs_dict[sid]['SegVol'] = SegDof2Volume(libPath, sid, dof) # segment volume from the segment DOF
        gsegs_dict[sid]['SegGaugeType'] = 'RG' # segment gauge type, 'PG' for REAL gauge; 'SG' for PSEUDO gauge, etc.

    #
    # Add the confluence segment as a gauged segment if it is not gauged but has upstream reaches with volume
    #
    # only apply to CC or CO reaches
    if reach.type in ['CC', 'CO']:
        cseg_id = reach.seg_ids[-1] # the confluence segment (i.e., the most upstream segment) on the reach

        # calculate the confluence segment volume 
        if len(gsegs_dict)==0 or (not (cseg_id in gsegs_dict)):
            # confluence segment is not gauged, calculate the confluence segment volume from upstream reaches
            up_volume = [child.down_volume for child in reach.children] 
            up_volume = [v for v in up_volume if not math.isnan(v)] # remove NaN values
            if len(up_volume) == 0: cseg_volume = math.nan # no upstream each has valid volume, set confluence segment volume to NaN
            else: cseg_volume = sum(up_volume) # sum upstream reach volumes as the confluence segment volume
                
            # add the confluence segment as a gauged segment if upstream segments have volume
            # note that the confluence segment may not have upstream reach volume (i.e., sum of upstream reach volumes is NaN)!
            if not math.isnan(cseg_volume):
                # put the pseudo gauge at the middle FSP of the confluence segment
                segFsps = libFspDf[libFspDf['SegId']==cseg_id].copy()
                segFsps['Dist'] = (segFsps['DsDist'] - segDistDict[cseg_id]).abs() # distance from FSP to the middle point
                segFsps = segFsps.sort_values('Dist', ascending=True) # sort FSPs by the distance from the middle point
                fspx,fspy,elev,dist = segFsps.head(1)[['FspX','FspY','FilledElev','DsDist']].values.flatten().tolist() 

                # put the confluence segment into the gauged segments dictionary
                gsegs_dict[cseg_id] = {
                    'FspX': fspx,  
                    'FspY': fspy,
                    'FilledElev': elev,  
                    'DsDist': dist,  
                    'Dof': None,  
                    'SegMidDsDist': segDistDict[cseg_id],
                    'SegDof': None,  
                    'SegVol': cseg_volume,
                    'SegGaugeType': 'PG'
                }
                gsegs.append(cseg_id) # add the confluence segment to the gauged segments) 
    
    #
    # Interpolate segment volume and FSP DOF along the reach
    #
    if len(gsegs) > 0: # only do interpolation if there is at least one gauged segment on the reach
        # index of the last (i.e., most upstream) gauged segment on the reach
        upIdx = reach.seg_ids.index(gsegs[-1])
        # index of the first (i.e., most downstream) gauged segment on the reach
        downIdx = reach.seg_ids.index(gsegs[0]) 
        
        #
        # Handle the most upstream gauged segment
        #
        sid = reach.seg_ids[upIdx]; vol = gsegs_dict[sid]['SegVol']
        dofs = SegVolume2FspDof(libPath, libFspDf, sid, vol)

        # Level water elevation at the upstream ending gauge for segment with REAL gauge
        if gsegs_dict[sid]['SegGaugeType'] == 'RG':
            # get the most upstream gauge on the most upstream segment of the reach
            gElev, gDof, gDsDist = [gsegs_dict[sid][k][0] for k in ['FilledElev','Dof','DsDist']] 
            # get FSPs above the gauge and calculate their DOF
            fsps = libFspDf[(libFspDf['SegId']==sid) & (libFspDf['DsDist']>=gDsDist)].copy() 
            fsps['Dof'] = gElev + gDof - fsps['FilledElev']
            fsps = fsps[fsps['Dof']>0][['FspId', 'Dof']] # keep only FSPs with positive DOF
            # replace the segment FSP DOF with the level-off DOF
            if not fsps.empty:
                dofs.set_index('FspId', inplace=True)
                fsps.set_index('FspId', inplace=True)
                dofs.update(fsps)
                dofs.reset_index(inplace=True)
        # put segment id, volume, and FSP DOF into a list
        up_seg = [(sid, vol, dofs)]

        #
        # Handle the most downstream gauged segment on the reach
        #
        if downIdx == upIdx: # only one gauged segment on the reach
            down_seg = []
        else:
            # calculate the segment volume and FSP DOF for the most downstream gauged segment
            sid = reach.seg_ids[downIdx]; vol = gsegs_dict[sid]['SegVol']
            down_seg = [(sid, vol, SegVolume2FspDof(libPath, libFspDf, sid, vol))]
            
        #
        # Handle the segments downstream of the most downstream gauged segment on the reach
        # Propagate the volume of the most downstream gauged segment down dsPropSegNum segments
        # 
        post_down_segs = []
        minIdx = 0  # for reach type of TC and CC
        if reach.type in ['TO', 'CO']:
            # the outletSegNum of segments above the outlet will not be interpolated
            # minIdx = min(outletSegNum, downIdx)
            # only propagate the volume to certain number of segments downstream of it
            minIdx = max(downIdx-dsPropSegNum, 0) # make sure minIdx is not negative
        if downIdx >= minIdx:
            vol = gsegs_dict[gsegs[0]]['SegVol'] # volume of the most downstream gauged segment
            # assign the volume to the segments downstream of the most downstream gauged segment
            sids = reach.seg_ids[minIdx:downIdx] 
            vols = [vol] * len(sids)
            # calculate FSP DOF for the segments downstream of the most downstream gauged segment
            post_down_segs = [(s, v, SegVolume2FspDof(libPath, libFspDf, s, v)) for s, v in zip(sids, vols)] 

        #
        # Handle the segments between between the first and last gauged segments on the reac
        # Linearly interpolate segment volumes
        #
        between_segs = []
        if (upIdx - downIdx) > 1: # there are segments between the first and last gauged segments on the reach
            # Create a volume interpolator
            gSegDists = [segDistDict[s] for s in gsegs] # mid downstream distances of the gauged segments
            gSegVols = [gsegs_dict[s]['SegVol'] for s in gsegs] # volumes
            VolumeInterpolator = interp1d(gSegDists, gSegVols, kind='linear', fill_value='extrapolate')

            # interpolate volumes between the first and last gauged segments
            interSegIds = reach.seg_ids[downIdx+1:upIdx] # segments to be interpolated, NOT including the first and last gauged segments
            interSegDists = [segDistDict[s] for s in interSegIds] # mid downstream distances of the segments to be interpolated
            interSegVols = VolumeInterpolator(interSegDists)
            between_segs = [(s, v, SegVolume2FspDof(libPath, libFspDf, s, v)) for s, v in zip(interSegIds, interSegVols)] 

        # concatenate interpolated segments, a list of (sid, vol, dof), from downstream to upstream
        all_segs = post_down_segs + down_seg + between_segs + up_seg

        # get segment FSP DOF as a list
        sfspDofs = [item[2] for item in all_segs if item[2] is not None] # keep only segments with FSP DOF
        fspDof = pd.concat(sfspDofs, ignore_index=True)
        
        # store the downstream volume of the reach. This MUST be stored as an attribute of the reach in order to calculate downstream confluence segment volume
        reach.down_volume = all_segs[0][1] if len(all_segs) > 0 else math.nan

        # store interpolated FSP DOF as an attribute of the reach
        setattr(reach, outVarName, fspDof)

        # store segment volume as an attribute for checking the code. This can be removed later!
        reach.seg_vols = [(s, v) for s, v, dof in all_segs]
        # store gauged segments and their attributes for checking the code. 
        reach.gsegs_dict = gsegs_dict

    else:
        # no gauged segments on the reach, set the downstream volume to NaN
        reach.down_volume = math.nan
        # set interpolated FSP DOF to an empty DataFrame
        # setattr(reach, outVarName, pd.DataFrame(columns=['FspId', 'Dof']))
        setattr(reach, outVarName, None)
        # set segment volumes to an empty list
        reach.seg_vols = []
        # set gauged segments and their volumes to an empty list
        reach.gsegs_dict = None
    
    return reach

#
# Generate stream reach network as a tree where each node is a reach consisting of an ordered (down-->up stream) segments
#
def GenerateReachNetworkTree(seg, segInfoDf, reachId=0, parent=None):
    ''' Generate a reach network tree from an outlet segment ID. The reach that contains the outlet/start segment is the root reach of the reach network/tree.
        This function also assign reach type as one of the following:
                TC: terminal (i.e., head-water) reach that flows into a confluence,
                TO: terminal reach that flows into network outlet, 
                CC: confluence reach that flows into a confluence,
                CO: confluence reach that flows into network outlet.
    Parameters:
        seg: segment ID of the outlet/start segment
        segInfoDf: segment info DataFrame with columns ['SegId', 'DsSegId'] which stores segment network connectivity
        reachId: start reach ID, default is 0
        parent: parent reach of the current reach, None for the root reach
    '''
    # find reach segments, i.e., segments between the start of a stream or a confluence and a confluence or the end of a stream
    reachSegs = [seg] 
    upSegs=segInfoDf[segInfoDf['DsSegId']==seg]['SegId'].to_list()
    # move up stream, add segments to the reach until encounter a confluence segment
    while len(upSegs)==1:
        # add current seg to the reach segment list
        seg = upSegs[0]
        reachSegs.append(seg)
        # move to upstream segment
        upSegs=segInfoDf[segInfoDf['DsSegId']==seg]['SegId'].to_list()

    # decide reach type
    if parent is None:
        if len(upSegs) > 1:
            type = 'CO' # outlet reach that flows into a confluence, i.e., 'CO' type
        else:
            type = 'TO' # outlet reach that flows into outlet, i.e., 'TO' type
    else:
        if len(upSegs) > 1:
            type = 'CC' # confluence reach that flows into a confluence, i.e., 'CC' type
        else:
            type = 'TC' # confluence reach that flows into outlet, i.e., 'TC' type

    # set current reach as the root of the tree
    root  = Reach(reachId, reachSegs)
    root.type = type
    reachId += 1
    parent = root

    # add upstream reach trees as the children of current reach
    for s in upSegs:
        t = GenerateReachNetworkTree(s, segInfoDf, reachId, parent)
        if t is not None: 
            root.add_child(t)
            reachId += 1

    return root

#
# Interpolate FSP DOF from gauge FSP DOFs through segment volumes
#
def InterpolateFspDofFromGaugeThroughVolume(libFolder, libName, gaugeFspDf):
    ''' Interpolate library segment volumes from gauged FSPs.
        libFolder: folder where the library is stored
        libName: name of the library
        gaugeFspDf: DataFrame with gauged FSPs including columns ['lib_name', 'SegId', 'FspX', 'FspY', 'FilledElev', 'DsDist', 'Dof']
    '''
    # Read in library FSP info CSV file
    fspFile = os.path.join(libFolder, libName, fspInfoFileName)
    libFspDf = pd.read_csv(fspFile) 
    # print(libFspDf)

    # read in segment info Excel file. segInfoColumnNames = ['SegId','CellCount','DsSegId', 'StFac','EdFac', 'Length','DsDist']
    segInfoFile = os.path.join(libFolder, libName, segInfoFileName)
    segInfoDf = pd.read_csv(segInfoFile,float_precision='round_trip',index_col=False)

    # calculate segment mid-point downstream distance
    segInfoDf['MidDsDist'] = segInfoDf['Length']/2.0 + segInfoDf['DsDist']
    # segDf = segDf[['SegId','MidDsDist']] # keep only necessary columns?
    # print(segDf)

    # find the outlet stream segment in each library's stream networks
    outletSegs = segInfoDf[segInfoDf['DsSegId']==0]['SegId'].to_list()
    print(f'{libName} has {len(outletSegs)} stream networks.')

    # interpolate reach FSP DOF for each reach network
    libReachFspDof = [] #
    for olSeg in outletSegs:
        print(f'Processing stream network with outlet segment {olSeg} ...')

        # generate reach network as a tree
        tree = GenerateReachNetworkTree(olSeg, segInfoDf)
        # tree = ReachNetwork.create_network_from_seginfo(olSeg, segInfoDf).root
        reachLst = tree.reach_attrs_to_list(['id', 'seg_ids','type'])
        print(f'Original reach network/tree ({len(reachLst)} reaches):')
        print(reachLst)
  
        # # filter gauged reaches and their downstream reaches from the reach tree
        # # This is NOT necessary with the current implementation of the InterpolateReachSegmentVolume function!!!
        # tree = tree.filter_gauged_reaches(gaugedSegLst)
        # if tree is not None:
        #     reachLst = tree.reach_attrs_to_list(['id', 'seg_ids','type'])
        #     print(f'Gauged reach network/tree ({len(reachLst)} reaches):')
        #     print(reachLst)
        # else:
        #     print('No gauged reaches found in the stream network.')

       # interpolate reach FSP DOF from gauged FSPs through segment volumes

        if tree is not None: 
            libPath = os.path.join(libFolder, libName)
            tree.apply_func('Depth-First', InterpolateReachFspDof, libPath, gaugeFspDf, segInfoDf[['SegId','MidDsDist']], libFspDf, 2, 'func_out')
            # print(tree.reach_attrs_to_list(['id', 'type', 'gsegs_dict','func_out'])) # for checking the output

            # get interpolated FSP DOF from the reach tree
            dvol = tree.reach_attrs_to_list(['id','down_volume','seg_vols'])
            print(f'Interpolated reach downstream volume:')
            print(dvol)
            
            netReachDof = tree.reach_attrs_to_list(['func_out'])
            numOfFsps = sum([df.shape[0] for df_lst in netReachDof for df in df_lst if df is not None])
            print(f'Interpolated {numOfFsps} reach FSP DOF.')
            # print(netReachDof)

            # add the network reach FSP DOF to library reach FSP DOF list
            libReachFspDof.extend(netReachDof)
    
    # flatten the list of list 
    reachFspDofLst = [x for xs in libReachFspDof for x in xs if x is not None] 
    numOfFsps = sum([df.shape[0] for df in reachFspDofLst])
    print(f'Interpolated {numOfFsps} FSP DOFs on {len(reachFspDofLst)} reaches in {libName} library.\n')
    # print(reachFspDofLst)
    
    # create a DataFrame to store FSP ID and DOF
    fspDof = pd.concat(reachFspDofLst, ignore_index=True)    

    return fspDof

# def SegDof2Volume(libPath, segId, dof):
#     return segId

# def SegVolume2Dof(libPath, segId, vol):
#     return vol/10

def SegDof2Volume(libPath, segId, dof):
    # get segment volume using the segment ID and DOF
    mf = os.path.join(libPath, stageVolumeFileFolderName, f'{stageVolumeFileMainName}{int(segId)}_stats.mat')

    # read mat file
    matVar = ReadMatFile(mf,stageVolumeVariableName)
    # converting array to a dataframe
    df = pd.DataFrame(matVar, columns=stageVolumeColumnNames) 

    # Create a volume interpolator
    intp = interp1d(df['DTF'], df['vol_cuft'], kind='linear')
    # interpolate the volume at the given DOF
    vol = intp(dof)
    
    return vol.item()

def SegVolume2Dof(libPath, segId, vol):
    # get segment volume using the segment ID and DOF
    mf = os.path.join(libPath, stageVolumeFileFolderName, f'{stageVolumeFileMainName}{int(segId)}_stats.mat')

    # read mat file
    matVar = ReadMatFile(mf,stageVolumeVariableName)
    # converting array to a dataframe
    df = pd.DataFrame(matVar, columns=stageVolumeColumnNames)

    # Create a volume interpolator
    intp = interp1d(df['vol_cuft'], df['DTF'], kind='linear')
    # interpolate the volume at the given DOF
    dof = intp(vol)
    
    return dof.item()

def SegVolume2FspDof(libPath, libFspDf, segId, vol):
    # get segment volume using the segment ID and DOF
    mf = os.path.join(libPath, stageVolumeFileFolderName, f'{stageVolumeFileMainName}{int(segId)}_stats.mat')

    # read mat file
    matVar = ReadMatFile(mf,stageVolumeVariableName)
    # converting array to a dataframe
    df = pd.DataFrame(matVar, columns=stageVolumeColumnNames)

    # Create a volume interpolator
    intp = interp1d(df['vol_cuft'], df['DTF'], kind='linear')
    # interpolate the volume at the given DOF
    dof = intp(vol)
    
    # select the FSPs on the segment
    segFsps = libFspDf[libFspDf['SegId']==segId][['FspId']]

    segFsps['Dof'] = dof # or use the following line to add DOF to the segment FSPs
    # segFsps.loc[:,'Dof'] = dof

    return segFsps

#
# Find upstream segments of a given segment and assign a flow volume in a segment network defined by the segment info table/DataFrame.
# This function is used to generate CatFIM depth raster.
#
def FindUpstreamSegments(seg, volume, segInfoDf, dist, volumeDistributionType='SFA', distanceType='Topology'):
    ''' Find upstream segments of a given segment and assign a flow volume in a segment network defined by the segment info table/DataFrame
    Parameters:
        seg: segment ID of the outlet/start segment
        volume: volume of the segment
        segInfoDf: segment info DataFrame with columns ['SegId', 'DsSegId'] which stores segment network connectivity
        dist: distance (number of segments) to look upstream
        volumeDistributionType: types ('SFA'--same for all, 'WTA'--winner takes all, 'EQU'--equal distribution, or 'FAC'--flow accumulation based) of volume distribution to upstream segments at a confluence, default is 'WTA'.
        distanceType: types ('Topology'--(0, inf), 'Network', 'Euclidean') of distance to use, default is 'Topology'. This is not used in this function but can be used in the future for different distance calculations.
    Returns:
        a list of upstream segment IDs        
    '''
    # initialize the upstream segments list and distance
    allUpSegs = []; d = 0
    # move upstream, add segments to the list until exceeding the distance or encountering a confluence
    upSegs=segInfoDf[segInfoDf['DsSegId']==seg]['SegId'].to_list()
    while len(upSegs)==1 and (d < dist):
        # add current seg to the list
        seg = upSegs[0]
        allUpSegs.append((seg, volume))
        d += 1
        # if the distance is reached, stop moving upstream
        if d >= dist:
            break
        # move to upstream segment
        upSegs=segInfoDf[segInfoDf['DsSegId']==seg]['SegId'].to_list()

    if d >= dist or len(upSegs) == 0:
        # if the distance is reached or no more upstream segments, return the upstream segment list
        return allUpSegs
    else:
        # encounter a confluence, find the segments from all upstream streams
        for s in upSegs:
            t = FindUpstreamSegments(s, volume, segInfoDf, dist - d)
            allUpSegs.extend(t)

    return allUpSegs

#
# Find downstream segments of a given segment and assign a flow volume in a segment network defined by the segment info table/DataFrame.
# This function is used to generate CatFIM depth raster.
#
def FindDownstreamSegments(seg, volume, segInfoDf, dist, volumeDistributionType='SFA', distanceType='Topology'):
    ''' Find downstream segments of a given segment and assign a flow volume in a segment network defined by the segment info table/DataFrame
    Parameters:
        seg: segment ID of the outlet/start segment
        volume: volume of the segment
        segInfoDf: segment info DataFrame with columns ['SegId', 'DsSegId'] which stores segment network connectivity
        dist: distance (number of segments) to look downstream
        volumeDistributionType: types ('SFA'--same for all, 'WTA'--winner takes all, 'EQU'--equal distribution, or 'FAC'--flow accumulation based) of volume distribution to upstream segments at a confluence, default is 'WTA'.
        distanceType: types ('Topology'--(0, inf), 'Network', 'Euclidean') of distance to use, default is 'Topology'. This is not used in this function but can be used in the future for different distance calculations.
    Returns:
        a list of downstream segment IDs
    '''
    # initialize the downstream segments list and distance
    allDownSegs = []; d = 0
    # move downstream, add segments to the list until exceeding the distance or encountering a confluence
    downSegs=segInfoDf[segInfoDf['SegId']==seg]['DsSegId'].to_list()
    while len(downSegs)==1 and (d < dist):
        # add current seg to the list
        seg = downSegs[0]
        allDownSegs.append((seg, volume))
        d += 1
        # if the distance is reached, stop moving downstream
        if d >= dist:
            break
        # move to downstream segment
        downSegs=segInfoDf[segInfoDf['SegId']==seg]['DsSegId'].to_list()

    if d >= dist or len(downSegs) == 0:
        # if the distance is reached or no more downstream segments, return the downstream segment list
        return allDownSegs
    else:
        # encounter a confluence, find the segments from all upstream streams
        for s in downSegs:
            t = FindDownstreamSegments(s, volume, segInfoDf, dist - d)
            allDownSegs.extend(t)

    return allDownSegs

#
# Interpolate FSP DOF for gauge category flood inundation mapping through segment volumes
#
def InterpolateCategoryFspDofFromGaugeThroughVolume(libFolder, libName, gaugeFspDf, upDist=1, dsDist=2):
    ''' Interpolate library segment volumes from gauged FSPs.
        libFolder: folder where the library is stored
        libName: name of the library
        gaugeFspDf: DataFrame with gauged FSPs including columns ['lib_name', 'SegId', 'FspX', 'FspY', 'FilledElev', 'DsDist', 'Dof']
    '''
    # Read in library FSP info CSV file
    fspFile = os.path.join(libFolder, libName, fspInfoFileName)
    libFspDf = pd.read_csv(fspFile) 
    # print(libFspDf)

    # read in segment info Excel file. segInfoColumnNames = ['SegId','CellCount','DsSegId', 'StFac','EdFac', 'Length','DsDist']
    segInfoFile = os.path.join(libFolder, libName, segInfoFileName)
    segInfoDf = pd.read_csv(segInfoFile,float_precision='round_trip',index_col=False)

    # find gauged segments in the library's stream networks
    gaugedSegments = gaugeFspDf['SegId'].to_list()
    print(f'{libName} has {len(gaugedSegments)} gauged segments.')

    # interpolate FSP DOF for each gauged segment
    allGaugeFspDofList = [] #
    for gdSeg in gaugedSegments:
        print(f'Processing gauged segment {gdSeg} ...')

        # calculate the volue of the gauged segment
        segDof = gaugeFspDf[gaugeFspDf['SegId']==gdSeg]['Dof'].mean()
        segVol = SegDof2Volume(os.path.join(libFolder, libName), gdSeg, segDof)
        print(f'Segment {gdSeg} has DOF of {segDof:.2f} ft and volume of {segVol:.2f} acre-ft.')

        # find the upstream segments within certain distance 
        upSegs = FindUpstreamSegments(gdSeg, segVol, segInfoDf, upDist)
        print(f'Segment {gdSeg} has {len(upSegs)} upstream segments within {upDist} segments: {upSegs}')
        # find the downstream segments within certain distance
        downSegs = FindDownstreamSegments(gdSeg, segVol, segInfoDf, dsDist)
        print(f'Segment {gdSeg} has {len(downSegs)} downstream segments within {dsDist} segments: {downSegs}')
        # combine the upstream and downstream segments with the gauged segment
        allSegs = upSegs + [(gdSeg, segVol)] + downSegs
        print(f'Segment {gdSeg} has {len(allSegs)} upstream and downstreamsegments: {allSegs}')

        # get all segment IDs
        allSegIds = [s for s, v in allSegs]
        # print(f'Segment {gdSeg} has {len(allSegIds)} segments: {allSegIds}')
        # calculate FSP DOF for all the segments
        segFspDofList = [SegVolume2FspDof(os.path.join(libFolder, libName), libFspDf, s, v) for s, v in allSegs] 
        # combine the FSP DOF DataFrames in the list
        segFspDofs = pd.concat(segFspDofList, ignore_index=True) #.reset_index(drop=True)
        print(f'Interpolated FSP DOF for segment {gdSeg} with {segFspDofs.shape[0]} FSPs.', segFspDofs)

        # add the network reach FSP DOF to library reach FSP DOF list
        allGaugeFspDofList.append(segFspDofs)

    # create a DataFrame to store FSP ID and DOF
    fspDof = allGaugeFspDofList[0] if len(allGaugeFspDofList)>0 else pd.DataFrame(columns=['FspId', 'Dof'])

    return fspDof