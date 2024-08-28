"""Module for handling gauge data for flood mapping
"""

# 
# Some of the functions are moved to here from fldpln.py and fldpln_reorg.py
#
# imports from standard libraries
import math
import os
import tarfile
import requests
from datetime import datetime,timedelta # import this module after arcpy as arcpy has the same datetime object in it!
import tempfile

# imports from 3rd party libraries
from lxml import html
import numpy as np
import pandas as pd
import geopandas as gpd
from osgeo import ogr
from pyproj import CRS
import psycopg2
import pandas.io.sql as psql

# import the mapping module from THIS package
from .mapping import * 

# Import file config.py which is used for connecting to the postgresql database for Kansas FIM Dashboard
# from config import config 

#
# Get USGS gauges. This function get USGS gauges within a box and project them
#
def GetUsgsGauges(geobox, epsg=32614):
    """Get USGS gauges within a box and project them
        Parameters:
            geobox: a geographic box of (minX,minY,maxX,maxY)
            epsg: projected coordinate system, default to UTM14 (epsg=32614) for Kansas
        Returns: a dataframe of USGS gauges
    """
    
    # USGS site/gauge table fields:
    #  agency_cd       -- Agency
    #  site_no         -- Site identification number
    #  station_nm      -- Site name
    #  site_tp_cd      -- Site type
    #  dec_lat_va      -- Decimal latitude
    #  dec_long_va     -- Decimal longitude
    #  coord_acy_cd    -- Latitude-longitude accuracy
    #  dec_coord_datum_cd -- Decimal Latitude-longitude datum
    #  alt_va          -- Altitude of gauge/land surface
    #  alt_acy_va      -- Altitude accuracy
    #  alt_datum_cd    -- Altitude datum
    #  huc_cd          -- Hydrologic unit code
    #
    # # read in USGS gauges from Excel file which is manually generated from USGS gauge web site
    # # See Chapter 5 in book Flood Mapping in Kansas.
    # # This can be automated too!
    # gaugeExcelFile = 'usgs_gauges_ks_nearby.xlsx'
    # sheetName = 'usgs_gauges_ks_nearby'
    # gdf = pd.read_excel(gaugeExcelFile, sheet_name=sheetName,dtype={'site_no':str,'huc_cd':str})
    # # print('USGS gauges from web:',gdf)

    # USGS Site Web Service
    usgsSiteServiceUrl = 'http://waterservices.usgs.gov/nwis/site'

    # prepare a query URL to retrieve active lake and stream USGS gauges with instantaneous values
    # usgsSiteServiceUrl = 'http://waterservices.usgs.gov/nwis/site/?format=rdb,1.0&bBox=-99.610000,36.810000,-94.200000,40.250000&siteType=LK,ST&siteStatus=active&hasDataTypeCd=iv'
    # parameters
    bBox = ','.join([str(c) for c in geobox])
    params = {'format':'rdb', 'bBox':bBox, 'siteType': 'LK,ST', 'siteStatus':'active', 'hasDataTypeCd': 'iv'}

    # Send the request with the get method
    response = requests.get(usgsSiteServiceUrl, params=params, verify=False)
    print(response.request.url)

    # turn content into list of lines
    contentLst = response.text.split('\n')

    # find the number of lines of the header in the RDB file
    numOfHeaderLn = 0
    for ln in contentLst:
        if ln[0] == '#':
            numOfHeaderLn += 1
        else:
            break

    # get field names
    fieldNames = contentLst[numOfHeaderLn].split('\t')
    # print(fieldNames)

    # turn each line into a list
    gLst = [row.split('\t') for row in contentLst[numOfHeaderLn+2:-1]]
    # convert lat, longitude, and datum elevation to floats
    for g in gLst:
        g[4] = float(g[4])
        g[5] = float(g[5])
        if g[8] != '':
            g[8] = float(g[8])
        else:
            g[8] = None
        if g[9] != '':
            g[9] = float(g[9])
        else:
            g[9] = None

    # create a df from the list
    gdf = pd.DataFrame(gLst, columns=fieldNames)

    # turn pd into gpd using gauge's latitude and longitude coordinates
    ggdf = gpd.GeoDataFrame(gdf, geometry=gpd.points_from_xy(gdf.dec_long_va, gdf.dec_lat_va))

    # Project gauge location 
    # define gauge CRS, i.e., GCS on NAD83, assuming all USGS gauges are based on NAD83
    ggdf = ggdf.set_crs(epsg=4326)
    # project ggdf to library coordinate system, i.e., UTM 14N
    ggdf = ggdf.to_crs(epsg=epsg)
    # save the projected shapefile
    # ggdf.to_file(shpFullName)

    # add gauge's coordinates as fields
    ggdf['x'] = ggdf['geometry'].x
    ggdf['y'] = ggdf['geometry'].y

    # USGS gauges in UTM 14N
    gdf = ggdf.drop(columns=['geometry'])
    # print('Gauges with UTM 14N coordinates:',gdf)
    # print(f'Total gauges: {len(gdf)}')

    return gdf

#
# Get USGS gauge information with DF of gauge IDs
#
def GetUsgsGaugeInfo(ids):
# ids-- a list of USGS IDs

    # USGS site/gauge table fields:
    #  agency_cd       -- Agency
    #  site_no         -- Site identification number
    #  station_nm      -- Site name
    #  site_tp_cd      -- Site type
    #  dec_lat_va      -- Decimal latitude
    #  dec_long_va     -- Decimal longitude
    #  coord_acy_cd    -- Latitude-longitude accuracy
    #  dec_coord_datum_cd -- Decimal Latitude-longitude datum
    #  alt_va          -- Altitude of gauge/land surface
    #  alt_acy_va      -- Altitude accuracy
    #  alt_datum_cd    -- Altitude datum
    #  huc_cd          -- Hydrologic unit code
    #
    # # read in USGS gauges from Excel file which is manually generated from USGS gauge web site
    # # See Chapter 5 in book Flood Mapping in Kansas.
    # # This can be automated too!
    # gaugeExcelFile = 'usgs_gauges_ks_nearby.xlsx'
    # sheetName = 'usgs_gauges_ks_nearby'
    # gdf = pd.read_excel(gaugeExcelFile, sheet_name=sheetName,dtype={'site_no':str,'huc_cd':str})
    # # print('USGS gauges from web:',gdf)

    # USGS Site Web Service
    usgsSiteServiceUrl = 'http://waterservices.usgs.gov/nwis/site'

    # prepare a query URL to retrieve active lake and stream USGS gauges with instantaneous values
    # usgsSiteServiceUrl = https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=01646500,06891478&siteStatus=all
    # prepare parameters
    idstr = ",".join(ids)
    params = {'format':'rdb', 'sites':idstr}

    # Send the request with the get method
    response = requests.get(usgsSiteServiceUrl, params=params, verify=False)
    # print(response.request.url)

    # turn content into list of lines
    contentLst = response.text.split('\n')

    # find the number of lines of the header in the RDB file
    numOfHeaderLn = 0
    for ln in contentLst:
        if ln[0] == '#':
            numOfHeaderLn += 1
        else:
            break

    # get field names
    fieldNames = contentLst[numOfHeaderLn].split('\t')
    # print(fieldNames)

    # turn each line into a list
    gLst = [row.split('\t') for row in contentLst[numOfHeaderLn+2:-1]]
    # convert lat, longitude, and datum elevation to floats
    for g in gLst:
        g[4] = float(g[4])
        g[5] = float(g[5])
        if g[8] != '':
            g[8] = float(g[8])
        else:
            g[8] = None
        if g[9] != '':
            g[9] = float(g[9])
        else:
            g[9] = None

    # create a df from the list
    gInfo = pd.DataFrame(gLst, columns=fieldNames)
    # print(gInfo)

    return gInfo

#
# Get AHPS gauges. Get AHPS current observation (shapefile) and project it into UTM14N
#
def GetAhpsGauges(geobox,epsg=32614):
# geobox--a geographic box of (minX,minY,maxX,maxY)
# epsg--projected coordinate system, default to UTM14 for Kansas
    
    with tempfile.TemporaryDirectory() as scratchFolder:
        print('Downloading AHPS gauge shapefile ...')
        
        # Clean out existing obs file
        if os.path.isfile(os.path.join(scratchFolder,'ahps_download.tgz')):
            os.remove(os.path.join(scratchFolder,'ahps_download.tgz'))

        # delete the shapefile if existing
        shpFullName = os.path.join(scratchFolder,'national_shapefile_obs.shp')
        shpDriver = ogr.GetDriverByName("ESRI Shapefile")
        if os.path.exists(shpFullName):
            shpDriver.DeleteDataSource(shpFullName)
                
        # download current gauge observations
        ahpsUrl = r"https://water.weather.gov/ahps/download.php?data=tgz_obs"
        ahpsDownload = requests.get(ahpsUrl)
        # save the download in a file
        zippedFile = os.path.join(scratchFolder, "ahps_download.tgz")
        with open(zippedFile, "wb") as f:
            f.write(ahpsDownload.content)

        # unzipping the tgz and tar
        with tarfile.open(zippedFile, 'r:gz') as tf:
            tf.extractall(path=scratchFolder)

        # read AHPS shapefile
        gauges = gpd.read_file(shpFullName)
        # fields in the shapefile:
        # 'GaugeLID', 'count', 'Status', 'Location', 'Latitude', 'Longitude',
        #    'Waterbody', 'State', 'Observed', 'ObsTime', 'Units', 'Action', 'Flood',
        #    'Moderate', 'Major', 'LowThresh', 'LowThreshU', 'WFO', 'HDatum',
        #    'PEDTS', 'SecValue', 'SecUnit', 'URL'

        # select the gauges within a geographical box
        minX,minY,maxX,maxY = geobox
        gauges = gauges[(gauges['Longitude']>=minX) & (gauges['Longitude']<=maxX) & (gauges['Latitude']>=minY) & (gauges['Latitude']<=maxY)]

        print('Project the shapefile to library coordinate system ...')
        # project gauges to library coordinate system, i.e., UTM 14N
        gauges = gauges.to_crs(epsg=epsg)
        # save the projected shapefile
        # gauges.to_file(shpFullName)

        # add gauge's coordinates as fields
        gauges['x'] = gauges['geometry'].x
        gauges['y'] = gauges['geometry'].y

        # turn gpd to pd
        gauges = gauges.drop(columns=['geometry'])
        # # select cols
        # cols = ['GaugeLID','Status','Location','Latitude','Longitude','Waterbody','State','WFO','HDatum','URL','Units','Action','Flood','Moderate','Major','X','Y']
        # gauges = gauges[cols]
        # print('Gauges with UTM 14N coordinates:',gauges)
        # print(f'Total gauges: {len(gauges)}')
        
    return gauges

#
# Retrieve gauge stage datum elevation and vertical datum name from AHPS web HTML page
#
def GetAhpsGaugeDatumElevation(ahpsGaugeUrl):

    # request the html page
    response = requests.get(ahpsGaugeUrl)
    htmlTree= html.fromstring(response.content)

    navd88Path= '//table[@class="aboutthislocation_toggle"]/tr/td/table[1]/tr[4]/td/text()'
    ngvd29Path= '//table[@class="aboutthislocation_toggle"]/tr/td/table[1]/tr[5]/td/text()'
    otherPath= '//table[@class="aboutthislocation_toggle"]/tr/td/table[1]/tr[7]/td/text()'
    datums = [htmlTree.xpath(path)[0:2] for path in [navd88Path,ngvd29Path,otherPath]]

    datumEle = np.nan
    for datum in datums:
        datumName=datum[0].replace(' ','')
        if datumName == 'Other':
            datumName = np.nan
        datumEleStr= datum[1]
        if datumEleStr != 'Not Available':
            datumEleStr=datumEleStr.split(' ')[0].replace(',','')
            datumEle = float(datumEleStr)
            break
    # print(f'Datum name: {datumName}, Datum elevation: {datumEle}')
    return (datumName,datumEle)

#
# Calculate vertical datum shift between NGVD29 and NAVD88 using NGS web service
#
def NGVD29ToNAVD88OrthoHeightAdjustment(lat,lon,inDatum,outDatum,inVertDatum='NGVD29',outVertDatum='NAVD88',orthoHt=0.0):
    # NGS Latitude-longitude-height Service
    # https://www.ngs.noaa.gov/web_services/ncat/lat-long-height-service.shtml

    # ngsUrl = f'https://geodesy.noaa.gov/api/ncat/llh?lat={lat}&lon={lon}&inDatum={inDatum}&outDatum={outDatum}&inVertDatum={inVertDatum}&outVertDatum={outVertDatum}&orthoHt={orthoHt}'
    ngsUrl = 'https://geodesy.noaa.gov/api/ncat/llh'
    payload = {'lat':lat,'lon': lon, 'inDatum':inDatum,'outDatum':outDatum, 'inVertDatum':inVertDatum,'outVertDatum':outVertDatum,'orthoHt':orthoHt}
    
    # request the html page
    response = requests.get(ngsUrl, params=payload)
    result = response.json()
    destOrthoht = result['destOrthoht']

    # convert meter to US Survey ft
    m2usft = 3.2808333333
    destOrthoht = float(destOrthoht) * m2usft

    return destOrthoht

#
# Merge USGs and AHPS gauges
#
def MergeUsgsAhpsGauges(usgsGauges, ahpsGauges, nearDist=350):
    distFieldName='dist'
    # find the nearest AHPS gauge for each USGS gauge. Note that multiple USGS gauges have the same nearest AHPS gauge!
    usgsNearGauges = NearestPoint(usgsGauges, 'x', 'y', ahpsGauges, 'x', 'y', distFieldName=distFieldName,otherColumns=['GaugeLID'])
    usgsNearGauges = usgsNearGauges[usgsNearGauges[distFieldName]<=nearDist][['GaugeLID','site_no']]
    print(f'USGS nearest AHPS gauges: {len(usgsNearGauges)}')

    # find the nearest USGS gauge for each AHPS gauge. Note that multiple AHPS gauges have the same nearest USGS gauge!
    ahpsNearGauges = NearestPoint(ahpsGauges, 'x', 'y', usgsGauges, 'x', 'y', distFieldName=distFieldName, otherColumns=['site_no'])
    ahpsNearGauges = ahpsNearGauges[ahpsNearGauges[distFieldName]<=nearDist][['GaugeLID','site_no']]
    print(f'AHPS nearest USGS gauges: {len(ahpsNearGauges)}')

    # find the USGS and AHPS gauges that are nearest gauge to each other
    # There is ONE AHPS gauge which is the nearest gauge of two USGS gauges
    commGaugeIds = pd.merge(ahpsNearGauges,usgsNearGauges,how='inner',on=['GaugeLID','site_no'])
    
    # # clean up the original gauges. This is necessary when using NearestPointInPlace()
    # usgsGauges.drop(columns=['GaugeLID',distFieldName],inplace=True)
    # ahpsGauges.drop(columns=['site_no',distFieldName],inplace=True)

    # get the common gauges from USGS gauges
    mGauges = pd.merge(usgsGauges,commGaugeIds,how='left',on='site_no')
    commGauges = mGauges[~mGauges['GaugeLID'].isna()]

    # get just USGS gauges
    justUsgsGauges = mGauges[mGauges['GaugeLID'].isna()]

    # just AHPS gauges
    justAhpsGauges = pd.merge(ahpsGauges,commGaugeIds,how='left',on='GaugeLID')
    justAhpsGauges = justAhpsGauges[justAhpsGauges['site_no'].isna()]
    print(f'Common: {len(commGauges)}, Just USGS: {len(justUsgsGauges)}, Just AHPS: {len(justAhpsGauges)}')
    # print(justAhpsGauges.columns)

    #
    # Standardize gauges
    #
    # USGS site/gauge table fields:
        #  agency_cd       -- Agency
        #  site_no         -- Site identification number
        #  station_nm      -- Site name
        #  site_tp_cd      -- Site type
        #  dec_lat_va      -- Decimal latitude
        #  dec_long_va     -- Decimal longitude
        #  coord_acy_cd    -- Latitude-longitude accuracy
        #  dec_coord_datum_cd -- Decimal Latitude-longitude datum
        #  alt_va          -- Altitude of gauge/land surface
        #  alt_acy_va      -- Altitude accuracy
        #  alt_datum_cd    -- Altitude datum
    # AHPS fields:
        # 'GaugeLID', 'count', 'Status', 'Location', 'Latitude', 'Longitude',
        #    'Waterbody', 'State', 'Observed', 'ObsTime', 'Units', 'Action', 'Flood',
        #    'Moderate', 'Major', 'LowThresh', 'LowThreshU', 'WFO', 'HDatum',
        #    'PEDTS', 'SecValue', 'SecUnit', 'URL'

    # create an empty DF
    fields=['stationid','name','organization','stype','stationurl','graphurl',
                'action_stage','flood_stage','moderate_stage','major_stage',
                'datum_elevation','vdatum','to_navd88',
                'latitude','longitude','hdatum','x','y']
    gauges = pd.DataFrame(columns=fields)

    # add common gauges
    for row in commGauges.itertuples():  
        stationid,name,organization,stype,datum_elevation,vdatum,latitude,longitude,hdatum,x,y = (row.site_no,row.station_nm,row.agency_cd,row.site_tp_cd,row.alt_va,row.alt_datum_cd,row.dec_lat_va,row.dec_long_va,row.dec_coord_datum_cd,row.x,row.y)
        to_navd88 = np.nan

        # get values from the AHPS gauge
        r = ahpsGauges.loc[ahpsGauges.GaugeLID==row.GaugeLID]
        # turn the row DF into a list of objects
        r = r.to_records(index=False)[0]

        # station URL uses AHPS instead of USGS as AHPS station may have vertical datum information when USGS station URL doesn't
        stationurl = f'http://water.weather.gov/ahps2/hydrograph.php?wfo={r.WFO}&gage={r.GaugeLID}' # station URL from AHPS
        # stationurl = 'https://waterdata.usgs.gov/nwis/inventory/?site_no='+str(stationid) # USGS station URL

        # add datum elevation from AHPS station HTML page
        if math.isnan(datum_elevation):
            datumName, datumEle = GetAhpsGaugeDatumElevation(stationurl)
            datum_elevation, vdatum = (datumEle,datumName)

        # other fields from AHPS
        action_stage,flood_stage,moderate_stage,major_stage = (r.Action, r.Flood, r.Moderate, r.Major)
        graphurl = f'http://water.weather.gov/resources/hydrographs/{r.GaugeLID.lower()}_hg.png'

        # create a new row
        nr = {'stationid':stationid+','+r.GaugeLID,'name':name,'organization':organization+','+'AHPS','stype':stype,'stationurl':stationurl,'graphurl':graphurl,
            'action_stage':action_stage,'flood_stage':flood_stage,'moderate_stage':moderate_stage,'major_stage':major_stage,
            'datum_elevation':datum_elevation,'vdatum':vdatum,'to_navd88':to_navd88,
            'latitude':latitude,'longitude':longitude,'hdatum':hdatum,'x':x,'y':y}
        # append
        # gauges = gauges.append(nr,ignore_index=True)
        gauges = pd.concat([gauges, nr],ignore_index=True)
    # print(gauges.columns)
    # print(gauges)

    # add just USGS gauges
    for row in justUsgsGauges.itertuples(): 
        stationid,name,organization,stype,datum_elevation,vdatum,latitude,longitude,hdatum,x,y = (row.site_no,row.station_nm,row.agency_cd,row.site_tp_cd,row.alt_va,row.alt_datum_cd,row.dec_lat_va,row.dec_long_va,row.dec_coord_datum_cd,row.x,row.y)
        stationurl = 'https://waterdata.usgs.gov/nwis/inventory/?site_no='+str(stationid)
        graphurl = f'http://waterdata.usgs.gov/nwisweb/graph?site_no={stationid}&parm_cd=00065&period=7'
        to_navd88 = np.nan

        # nothing from AHPS
        action_stage,flood_stage,moderate_stage,major_stage = (np.nan,np.nan,np.nan,np.nan)
        
        # create a new row
        nr = {'stationid':stationid,'name':name,'organization':organization,'stype':stype,'stationurl':stationurl,'graphurl':graphurl,
            'action_stage':action_stage,'flood_stage':flood_stage,'moderate_stage':moderate_stage,'major_stage':major_stage,
            'datum_elevation':datum_elevation,'vdatum':vdatum,'to_navd88':to_navd88,
            'latitude':latitude,'longitude':longitude,'hdatum':hdatum,'x':x,'y':y}
        # append
        # gauges = gauges.append(nr,ignore_index=True)
        gauges = pd.concat([gauges, nr],ignore_index=True)
    # print(gauges)

    # add just AHPS gauges
    for row in justAhpsGauges.itertuples(): 
        # nothing from USGS gauges
        
        # get values from the AHPS gauge
        r = ahpsGauges.loc[ahpsGauges.GaugeLID==row.GaugeLID]
        # turn the row DF into a list of objects
        r = r.to_records(index=False)[0]

        # decide gauge type
        if (' Lake' in r.Location) or (' Reservoir' in r.Location):
            stype = 'LK'
        else:
            stype = 'ST'

        # add datum elevation from AHPS station HTML page
        stationurl = f'http://water.weather.gov/ahps2/hydrograph.php?wfo={r.WFO}&gage={r.GaugeLID}'
        datumName, datumEle = GetAhpsGaugeDatumElevation(stationurl)
        datum_elevation, vdatum = (datumEle,datumName)
        to_navd88 = np.nan

        # other attributes
        stationid,name,organization,latitude,longitude,hdatum,x,y = (r.GaugeLID,r.Location+', '+r.State,'AHPS',r.Latitude, r.Longitude,r.HDatum,r.x,r.y)
        action_stage,flood_stage,moderate_stage,major_stage = (r.Action, r.Flood, r.Moderate, r.Major)
        graphurl = f'http://water.weather.gov/resources/hydrographs/{r.GaugeLID.lower()}_hg.png'

        # create a new row
        nr = {'stationid':stationid,'name':name,'organization':organization,'stype':stype,'stationurl':stationurl,'graphurl':graphurl,
            'action_stage':action_stage,'flood_stage':flood_stage,'moderate_stage':moderate_stage,'major_stage':major_stage,
            'datum_elevation':datum_elevation,'vdatum':vdatum,'to_navd88':to_navd88,
            'latitude':latitude,'longitude':longitude,'hdatum':hdatum,'x':x,'y':y}
        # append
        # gauges = gauges.append(nr,ignore_index=True)
        gauges = pd.concat([gauges, nr],ignore_index=True)

    return gauges

# #
# # Get gauge observation from AHPS.
# # obsType can be: "Observed","ObsTime",'Action','Flood','Moderate','Major'
# #
# def GetAhpsGaugeObservations(libFolder,scratchFolder,obsType='Observed'):
#     print('Downloading national observations (current) from AHPS')
    
#     # Clean out existing obs file
#     if os.path.isfile(os.path.join(scratchFolder,'ahps_download.tgz')):
#         os.remove(os.path.join(scratchFolder,'ahps_download.tgz'))

#     # delete the shapefile if existing
#     shpFullName = os.path.join(scratchFolder,'national_shapefile_obs.shp')
#     shpDriver = ogr.GetDriverByName("ESRI Shapefile")
#     if os.path.exists(shpFullName):
#         shpDriver.DeleteDataSource(shpFullName)
            
#     # download current gauge observations
#     ahpsUrl = r"https://water.weather.gov/ahps/download.php?data=tgz_obs"
#     ahpsDownload = requests.get(ahpsUrl)
#     # save the download in a file
#     zippedFile = os.path.join(scratchFolder, "ahps_download.tgz")
#     with open(zippedFile, "wb") as f:
#         f.write(ahpsDownload.content)

#     ## unzipping the tgz and tar
#     with tarfile.open(zippedFile, 'r:gz') as tf:
#         tf.extractall(path=scratchFolder)

#     ## Transfer to numpy and then pandas
#     gaugeColumns = ["GaugeLID","Status","Observed","ObsTime",'Action','Flood','Moderate','Major']
#     gaugeObsDf = gpd.read_file(shpFullName)
#     gaugeObsDf = gaugeObsDf[gaugeColumns]
#     # print(gaugeObsDf)
    
#     if obsType == 'Observed':
#         # some gauge obs may have latency 
#         nowTime = datetime.now()
#         threeDaysAgo = nowTime - timedelta(days=3)
#         # select obs within 3 days
#         gaugeObsDf = gaugeObsDf[gaugeObsDf.ObsTime > str(threeDaysAgo)]
#         # print(gaugeObsDf)

#     # select the stage based on obs type
#     stageColumn = obsType
#     ## Merge with precomputed datum, clean up resulting frame
#     gaugeDatumFile = os.path.join(libFolder,ahpsGaugeDatumFileName)
#     gaugeWithDatum = pd.read_csv(gaugeDatumFile)[['GaugeLID','X','Y','Datum']]
#     gaugeObsDf = gaugeObsDf[['GaugeLID',stageColumn]]
#     gaugeObsDf = gaugeObsDf.merge(gaugeWithDatum, how='left', on='GaugeLID')
#     # print(gaugeObsDf)
    
#     # gaugeObsDf['Stage'] = pd.to_numeric(gaugeObsDf[stageColumn], errors='coerce')
#     gaugeObsDf[stageColumn] = pd.to_numeric(gaugeObsDf[stageColumn], errors='coerce')
#     gaugeObsDf['Datum'] = pd.to_numeric(gaugeObsDf['Datum'])

#     ## Create DTF value
#     gaugeObsDf['GaugeWSE'] = gaugeObsDf[stageColumn] + gaugeObsDf['Datum']
#     # remove nodata rows/gauges
#     # gaugeObsDf = gaugeObsDf[gaugeObsDf['GaugeWSE'].notna()]
#     # print(gaugeObsDf)

#     # gaugeObsDf.to_csv('GaugeObs.csv',index=False)

#     return gaugeObsDf

#
# Get gauge current observation or forecast from AHPS.
# fcstLength is a number between 0 and 14 (inclusive) days. 0 means current observation
#
def GetAhpsGaugeForecast(scratchFolder,fcstLength,gaugeDatumFile):
    print('Downloading AHPS gauge data ...')
    
    if isinstance(fcstLength,int) and (fcstLength>=0) and (fcstLength<=14):
        if fcstLength == 0:
            # current observation
            ahpsFileName = 'tgz_obs'
        else:
            # forecast between 1 to 14 days
            numOfHours=fcstLength*24
            fcstHours = f'f{numOfHours:03}'
            ahpsFileName = 'tgz_fcst_'+fcstHours
    else:
        print('Illegal type!')
        return None
    
    # Clean out existing obs file
    if os.path.isfile(os.path.join(scratchFolder,'ahps_download.tgz')):
        os.remove(os.path.join(scratchFolder,'ahps_download.tgz'))

    # delete the shapefile if existing
    if fcstLength == 0:
        # current observation
        shpFullName = os.path.join(scratchFolder,'national_shapefile_obs.shp')
    else:
        # forecast
        shpFullName = os.path.join(scratchFolder,f'national_shapefile_fcst_{fcstHours}.shp')
        
    shpDriver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(shpFullName):
        shpDriver.DeleteDataSource(shpFullName)
            
    # download current gauge observations
    ahpsUrl = r"https://water.weather.gov/ahps/download.php?data=" + ahpsFileName #tgz_obs"
    ahpsDownload = requests.get(ahpsUrl)
    # save the download in a file
    zippedFile = os.path.join(scratchFolder, "ahps_download.tgz")
    with open(zippedFile, "wb") as f:
        f.write(ahpsDownload.content)

    # unzipping the tgz and tar
    with tarfile.open(zippedFile, 'r:gz') as tf:
        tf.extractall(path=scratchFolder)

    # read gauge stage
    if fcstLength == 0:
        # current observation
        gaugeColumns = ["GaugeLID","Status","Observed","ObsTime"]
        gaugeObsDf = gpd.read_file(shpFullName)
        gaugeObsDf = gaugeObsDf[gaugeColumns]
        # print(gaugeObsDf)

        # some gauge obs may have latency 
        nowTime = datetime.now()
        threeDaysAgo = nowTime - timedelta(days=3)
        # select obs within 3 days
        gaugeObsDf = gaugeObsDf[gaugeObsDf.ObsTime > str(threeDaysAgo)]
        # print(gaugeObsDf)

        # select the stage based on obs type
        stageColumn = 'Observed'
    else:
        # forecast between 1 to 14 days
        gaugeColumns = ["GaugeLID","Status","Forecast","FcstTime","FcstIssunc"]
        gaugeObsDf = gpd.read_file(shpFullName)
        gaugeObsDf = gaugeObsDf[gaugeColumns]
        # print(gaugeObsDf)

        # select the stage based on obs type
        stageColumn = 'Forecast'
        
    ## Merge with precomputed datum, clean up resulting frame
    # gaugeDatumFile = os.path.join(libFolder,ahpsGaugeDatumFileName)
    gaugeWithDatum = pd.read_csv(gaugeDatumFile)[['GaugeLID','X','Y','Datum']]
    gaugeObsDf = gaugeObsDf[['GaugeLID',stageColumn]]
    gaugeObsDf = gaugeObsDf.merge(gaugeWithDatum, how='left', on='GaugeLID')
    # print(gaugeObsDf)
    
    # gaugeObsDf['Stage'] = pd.to_numeric(gaugeObsDf[stageColumn], errors='coerce')
    gaugeObsDf[stageColumn] = pd.to_numeric(gaugeObsDf[stageColumn], errors='coerce')
    gaugeObsDf['Datum'] = pd.to_numeric(gaugeObsDf['Datum'])

    # Create DTF value
    gaugeObsDf['GaugeWSE'] = gaugeObsDf[stageColumn] + gaugeObsDf['Datum']
    # remove nodata rows/gauges
    # gaugeObsDf = gaugeObsDf[gaugeObsDf['GaugeWSE'].notna()]
    # print(gaugeObsDf)

    # gaugeObsDf.to_csv('GaugeObs.csv',index=False)

    return gaugeObsDf

#
# Get AHPS gauge historical flood stages: 'Action','Flood','Moderate','Major'
#
def GetAhpsGaugeHistoricalFloodStages(scratchFolder,gaugeDatumFile):
    print('Downloading AHPS historical flood stages ...')
    
    # Clean out existing obs file
    if os.path.isfile(os.path.join(scratchFolder,'ahps_download.tgz')):
        os.remove(os.path.join(scratchFolder,'ahps_download.tgz'))

    # delete the shapefile if existing
    shpFullName = os.path.join(scratchFolder,'national_shapefile_obs.shp')
    shpDriver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(shpFullName):
        shpDriver.DeleteDataSource(shpFullName)
            
    # download current gauge observations
    ahpsUrl = r"https://water.weather.gov/ahps/download.php?data=tgz_obs"
    ahpsDownload = requests.get(ahpsUrl)
    # save the download in a file
    zippedFile = os.path.join(scratchFolder, "ahps_download.tgz")
    with open(zippedFile, "wb") as f:
        f.write(ahpsDownload.content)

    # unzipping the tgz and tar
    with tarfile.open(zippedFile, 'r:gz') as tf:
        tf.extractall(path=scratchFolder)

    # read historical gauge stages
    gaugeColumns = ["GaugeLID","Status",'Action','Flood','Moderate','Major']
    gaugeObsDf = gpd.read_file(shpFullName)
    gaugeObsDf = gaugeObsDf[gaugeColumns]
    # print(gaugeObsDf)

    # Merge with precomputed datum, clean up resulting frame
    # gaugeDatumFile = os.path.join(libFolder,ahpsGaugeDatumFileName)
    gaugeWithDatum = pd.read_csv(gaugeDatumFile)[['GaugeLID','X','Y','Datum']]
    gaugeObsDf = gaugeObsDf.merge(gaugeWithDatum, how='left', on='GaugeLID')
    # print(gaugeObsDf)
    
    # convert stage columns into numeric type
    gaugeObsDf['Datum'] = pd.to_numeric(gaugeObsDf['Datum'])
    for stageColumn in ['Action','Flood','Moderate','Major']:
        gaugeObsDf[stageColumn] = pd.to_numeric(gaugeObsDf[stageColumn], errors='coerce')
        # convert stage to water surface elevation
        gaugeObsDf[stageColumn] = gaugeObsDf[stageColumn] + gaugeObsDf['Datum']
    
    # gaugeObsDf.to_csv('GaugeHistoricalStages.csv',index=False)

    return gaugeObsDf

#
# Prepare AHPS gauges for flood mapping 
#
def PrepareAhpsGaugeDatum(scratchFolder,libFolder,prjFileName,datumFile):
    print('Downloading AHPS gauge shapefile ...')
    
    # Clean out existing obs file
    if os.path.isfile(os.path.join(scratchFolder,'ahps_download.tgz')):
        os.remove(os.path.join(scratchFolder,'ahps_download.tgz'))

    # delete the shapefile if existing
    shpFullName = os.path.join(scratchFolder,'national_shapefile_obs.shp')
    shpDriver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(shpFullName):
        shpDriver.DeleteDataSource(shpFullName)
            
    # download current gauge observations
    ahpsUrl = r"https://water.weather.gov/ahps/download.php?data=tgz_obs"
    ahpsDownload = requests.get(ahpsUrl)
    # save the download in a file
    zippedFile = os.path.join(scratchFolder, "ahps_download.tgz")
    with open(zippedFile, "wb") as f:
        f.write(ahpsDownload.content)

    # unzipping the tgz and tar
    with tarfile.open(zippedFile, 'r:gz') as tf:
        tf.extractall(path=scratchFolder)

    # read AHPS shapefile
    gauges = gpd.read_file(shpFullName)

    print('Project the shapefile to library coordinate system ...')
    # read in spatial reference of the library
    srFile = os.path.join(libFolder,prjFileName)
    with open(srFile, 'r') as srf:
        srText = srf.read()
    # set geodataframe CRS
    libSr = CRS.from_wkt(srText)

    # project gauges to library coordinate system
    gauges = gauges.to_crs(libSr)
    # save the projected shapefile
    # gauges.to_file(shpFullName)

    # add gauge's coordinates as fields
    gauges['X'] = gauges['geometry'].x
    gauges['Y'] = gauges['geometry'].y

    # select cols
    cols = ['GaugeLID','Status','Location','Latitude','Longitude','Waterbody','State','WFO','HDatum','URL','Units','Action','Flood','Moderate','Major','X','Y']
    gauges = gauges[cols]
    # Add datum col
    gauges['Datum'] = np.nan

    print('Save gauge datum file ...')
    # Save the file
    # datumFile = os.path.join(scratchFolder,datumFileName)
    gauges.to_csv(datumFile, index=False)

    return gauges

#
# New functions
#
#
# Get AHPS gauge stage from web service
#
def GetAhpsGaugeStageFromWebService(ahpsIds, fcstDays=0, histFloodType=None):
# fcstDays: forecast days, 0-14, 0--current
# histFloodType: historical flood types, Major, Moderate, Flood, Action

    # # NWS/AHPS local WFS layers. NOT working
    # ahpsWfsServices = ['https://idpgis.ncep.noaa.gov/arcgis/rest/services/NWS_Observations/ahps_riv_gauges/MapServer/{}/query'.format(id) for id in range(16)]
    # # Select a WFS service
    # sUrl = ahpsWfsServices[0]

    # NWS/NOAA/AHPS AWS feature service layers
    # fields in the features are available best through the shapefiles from https://water.weather.gov/ahps/download.php
    # Meaning of the WFS service ID: 0--Observed; 1-- forecast 1-day; ...; 14--forecast 14-day; 15--same as 14?
    ahpsAwsWfsServices = ['https://mapservices.weather.noaa.gov/eventdriven/rest/services/water/ahps_riv_gauges/MapServer/{}/query'.format(id) for id in range(16)]
    
    #
    # Prepare service query
    #
    # creating the query strings and request a json response from the site
    whereClause = " OR ".join([f"gaugelid='{x}'" for x in ahpsIds])
    # query parameters
    payload = {'where': whereClause, 'outFields':'*','f':'pjson'} # pjson = plain JSON?

    # Select services based fcstDays: 0--Observed; 1-- forecast 1-day; ...; 14--forecast 14-day; 15--same as 14?
    if fcstDays in range(16):
        sUrl = ahpsAwsWfsServices[fcstDays]
    else:
        print('Incorrect fcstDays!')
        return None
        
    # send request
    response = requests.get(sUrl, params=payload, verify=False) # trust the service
    # print(response.request.url)
 
    # get the features and put them into a dataframe
    features = response.json()['features']
    attributes = [x['attributes'] for x in features]

    # select attributes based on stage type
    if histFloodType is None:
        # get forecast stage
        if fcstDays == 0:
            df = pd.DataFrame(attributes)[['gaugelid','observed','obstime']] #,'status']]
            df = df.rename(columns={'gaugelid':'stationid','observed':'stage_ft','obstime':'stage_time'})
        else:
            df = pd.DataFrame(attributes)[['gaugelid','forecast','fcsttime']] #,'status']]
            df = df.rename(columns={'gaugelid':'stationid','forecast':'stage_ft','fcsttime':'stage_time'})
    elif histFloodType in ['Major', 'Moderate', 'Flood', 'Action']:
        # get historical flood stage
        df = pd.DataFrame(attributes)[['gaugelid',histFloodType.lower()]]
        df = df.rename(columns={'gaugelid':'stationid',histFloodType.lower():'stage_ft'})
        df['stage_time'] = ''

    # turn field "stage_ft" into numeric
    df['stage_ft'] = pd.to_numeric(df['stage_ft'], errors='coerce')

    # reset index
    df.reset_index(drop=True,inplace=True)

    return df

#
# Get AHPS gauge stage from web service
#
def GetAhpsGaugeStageFromWebServiceOld(ahpsIds):
   
    # # NWS/AHPS local WFS layers. NOT working
    # ahpsWfsServices = ['https://idpgis.ncep.noaa.gov/arcgis/rest/services/NWS_Observations/ahps_riv_gauges/MapServer/{}/query'.format(id) for id in range(16)]
    # # Select a WFS service
    # sUrl = ahpsWfsServices[0]

    # NWS/NOAA/AHPS AWS feature service layers
    # fields in the features are available best through the shapefiles from https://water.weather.gov/ahps/download.php
    # Meaning of the WFS service ID: 0--Observed; 1-- forecast 1-day; ...; 14--forecast 14-day; 15--same as 14?
    # ahpsAwsWfsServices = ['https://mapservices.weather.noaa.gov/eventdriven/rest/services/water/ahps_riv_gauges/MapServer/{}/query'.format(id) for id in range(16)]
    ahpsAwsWfsServices = ['https://mapservices.weather.noaa.gov/eventdriven/rest/services/water/riv_gauges/MapServer/{}/query'.format(id) for id in range(16)] # new service since 5/28/2024
    
    # Access observed stage
    sUrl = ahpsAwsWfsServices[0] # current obs.

    # creating the query strings and request a json response from the site
    whereClause = " OR ".join([f"gaugelid='{x}'" for x in ahpsIds])
    # query parameters
    payload = {'where': whereClause, 'outFields':'*','f':'pjson'} # pjson = plain JSON?

    # send request
    response = requests.get(sUrl, params=payload, verify=False) # trust the service
    # print(response.request.url)
 
    # get the features and put them into a dataframe
    features = response.json()['features']
    attributes = [x['attributes'] for x in features]
    df = pd.DataFrame(attributes)[['gaugelid','observed','obstime','status']]
    df = df.rename(columns={'gaugelid':'stationid','observed':'stage_ft','obstime':'stage_time'})
    return df

#
# Get USGS gauge stage from web service
#
def GetUsgsGaugeStageFromWebService(usgsIds, startDate='Now', endDate='MostRecent'):
# usgsIds: a list of USGS IDs
# periodInDays: an integer indicates the time period (in days) from now to periodInDays before. Default to 7 days.

    # USGS Instantaneous Values Service URL: https://waterservices.usgs.gov/rest/IV-Test-Tool.html
    # base URL
    ivUrl = r'https://waterservices.usgs.gov/nwis/iv'
    # For stream gauges:
    #   Most recent: /?format=json&indent=on&sites={}&parameterCd=00065&siteStatus=all'
    #   From a period from now: /?format=json&indent=on&sites={}&period=P7D&parameterCd=00065&siteStatus=all'
    #   Between two dates: /?format=json&indent=on&sites={}&startDT=2018-09-02&endDT=2018-09-04&parameterCd=00065&siteStatus=all'
    # For lake gauges:
    #   parameterCd=62614, Lake or reservoir water surface elevation above NGVD 1929, feet 

    # prepare FIXed parameters for stream and lake gauges
    if startDate == 'Now':
        if endDate == 'MostRecent':
            # most recent stage
            paramsSt = {'format':'json', 'parameterCd':'00065','siteStatus':'all'}
            paramsLk = {'format':'json', 'parameterCd':'62614','siteStatus':'all'}
        else:
            # from Now to endDate (an integer!)
            periodPara = f'P{endDate}D'
            paramsSt = {'format':'json', 'period':periodPara, 'parameterCd':'00065','siteStatus':'all'} 
            paramsLk = {'format':'json', 'period':periodPara, 'parameterCd':'62614','siteStatus':'all'}
    else:
        # between startDate and endDate
        paramsSt = {'format':'json', 'startDT':startDate, 'endDT':endDate, 'parameterCd':'00065','siteStatus':'all'}
        paramsLk = {'format':'json', 'startDT':startDate, 'endDT':endDate, 'parameterCd':'62614','siteStatus':'all'}

    # get gauge type: ST or LK
    gt = GetUsgsGaugeInfo(usgsIds)['site_tp_cd'].to_list()

    # split gauges into STREAM and LAKE groups
    stIds=[]; lkIds=[]
    for t, id in zip(gt, usgsIds):
        if t == 'ST':
            stIds.append(id)
        if t == 'LK':
            lkIds.append(id)

    # concatenate ids as strings
    stIdStr = ",".join(stIds)
    lkIdStr = ",".join(lkIds)

    # prepare query for stream and lake gauges
    paramsSt.update({'sites':stIdStr})
    paramsLk.update({'sites':lkIdStr})

    # print('querying the USGS web service')
    cols = ['stationid','stage_ft', 'stage_time']
    df =pd.DataFrame(columns=cols)
    for params in [paramsSt, paramsLk]:
        if params['sites'] != '': # only query web service if there are sites!
            response = requests.get(ivUrl, params=params, verify=False)
            # print(response.request.url)
            response = response.json()['value']['timeSeries']
            # print(response)

            # extracting information from the web service json response
            for row in response:
                # site_name = row['sourceInfo']['siteName']
                site_code = row['sourceInfo']['siteCode'][0]['value']
                siteValues = row['values']
                for v in row['values']:
                    for v2 in v['value']:
                        gauge_height = v2['value'] # assume each gauge only has one value. But some gauge (for example, 06891080, KANSAS R AT LAWRENCE, KS) has TWO values, one above the dam and one below the dam
                        obs_time     = v2['dateTime']
                        # add the nearest point to the nearest point DF
                        t = pd.DataFrame([[site_code, gauge_height,obs_time]], columns=cols)
                        # df = df.append(t,ignore_index=False)
                        df = pd.concat([df, t],ignore_index=False)

    # turn field "stage_ft" into numeric
    df['stage_ft'] = pd.to_numeric(df['stage_ft'], errors='coerce')

    # reset index
    df.reset_index(drop=True,inplace=True)

    return df

#
# Get USGS gauge stage from web service
#
def GetUsgsGaugeStageFromWebServiceOld(usgsIds):
    
    # USGS Instantaneous Values Service URL: https://waterservices.usgs.gov/rest/IV-Test-Tool.html
    ivUrl = r'https://waterservices.usgs.gov/nwis/iv' #/?format=json&indent=on&sites={}&parameterCd=00065&siteStatus=all'
    # prepare parameters
    idstr = ",".join(usgsIds)
    params = {'format':'json', 'sites':idstr, 'parameterCd':'00065','siteStatus':'all'} 

    # prepare query 
    # print('querying the USGS web service')
    response = requests.get(ivUrl, params=params, verify=False)
    # print(response.request.url)
    response = response.json()['value']['timeSeries']

    # extracting information from the web service json response
    cols = ['stationid','stage_ft', 'stage_time']
    df =pd.DataFrame(columns=cols)
    for row in response:
        # site_name = row['sourceInfo']['siteName']
        site_code = row['sourceInfo']['siteCode'][0]['value']
        gauge_height = row['values'][0]['value'][0]['value'] # assume each gauge only has one value. But some gauge (for example, 06891080, KANSAS R AT LAWRENCE, KS) has TWO values, one above the dam and one below the dam
        obs_time     = row['values'][0]['value'][0]['dateTime']
        # add the nearest point to the nearest point DF
        t = pd.DataFrame([[site_code, gauge_height,obs_time]], columns=cols)
        # df = df.append(t,ignore_index=False)
        df = pd.concat([df, t],ignore_index=False)
    
    return df

#
# read AHPS/USGS gauge stage from their respective web services
#
def GetAhpsUsgsGaugeStageFromWebServices(gaugeIdOrgs, whichStage='Nowcast', periodInDays=7):
# gaugeIdOrgs: a DF with columns of ["stationid", "organization"]. 
#               stationid is either USGS, AHPS, or the combination of their gauge IDs
#               organization is either USGS, AHPS or both.
# whichStage: Nowcast, Forecast, Postcast, and historical stages Action, Flood, Moderate, Major
# fields to return: stationid, x, y, stage_elevation, stage_time

    # get gauge id of each organization and put them into 4 gauge ID groups
    ahpsIds = [] # only AHPS gauges
    usgsIds = [] # only USGS gauges 
    commAhpsIds=[]; commUsgsIds=[] # both AHPS and USGS gauges
    idDict={} # dict to map common gauges from AHPS or USGS ID to combined ID (e.g., sid)
    for row in gaugeIdOrgs.itertuples(): 
        sid, org = row.stationid, row.organization
        if 'AHPS' in org: 
            if org == 'AHPS':
                # only AHPS
                ahpsId = sid
                ahpsIds.append(ahpsId)
                idDict.update({ahpsId:sid})
            else: # common gauges
                commUsgsId, commAhpsId = sid.split(',')
                commAhpsIds.append(commAhpsId)
                commUsgsIds.append(commUsgsId)
                idDict.update({commAhpsId:sid})
                idDict.update({commUsgsId:sid})
        elif org == 'USGS':
            # only USGS
            usgsId = sid
            usgsIds.append(sid)
            idDict.update({usgsId:sid})
    # print(f'AHPS gauges: {len(ahpsIds)}, USGS gauges: {len(usgsIds)}')

    #
    # Get gauge stage from their web services
    #
    # Use different gauges for different stage types
    # Action, Flood, Moderate, Major: only AHPS + common AHPS
    # Nowcast : only AHPS + common AHPS + only USGS
    # Forecast: only AHPS + common AHPS
    # Postcast: only USGS + common USGS
    #
    ahpsIds = ahpsIds + commAhpsIds
    # use just AHPS gauges
    if whichStage in ['Action', 'Flood', 'Moderate', 'Major']:
        gaugeStages = GetAhpsGaugeStageFromWebService(ahpsIds,fcstDays=0,histFloodType=whichStage)

    # use all the gauges
    if whichStage in ['Nowcast']:
        ahpsStages = GetAhpsGaugeStageFromWebService(ahpsIds,fcstDays=0)
        print(f'AHPS gauges with stages: {len(ahpsStages)}')
        usgsStages = GetUsgsGaugeStageFromWebService(usgsIds,startDate='Now',endDate='MostRecent')
        print(f'USGS gauges with stages: {len(usgsStages)}')
        # combine the gauges
        gaugeStages = pd.concat([ahpsStages, usgsStages])
        
    # use just AHPS gauges
    if whichStage in ['Forecast']:
        gaugeStages = GetAhpsGaugeStageFromWebService(ahpsIds, periodInDays)
            
    # use just USGS gauges
    if whichStage in ['Postcast']:
        gaugeStages = GetUsgsGaugeStageFromWebService(usgsIds+commUsgsIds, startDate='Now',endDate=periodInDays)
        # find the max stage within the time period
        maxStages = gaugeStages.groupby(['stationid'],as_index=False).agg({'stage_ft':'max'})
        # find the most recent time with the max stage
        df = pd.merge(gaugeStages, maxStages, how='inner', on=['stationid','stage_ft'])
        gaugeStages = df.groupby(['stationid'], as_index=False).agg({'stationid':'first','stage_ft':'first','stage_time':'max'})
                
    # change stationid to the original id (i.e., AHPS ID + USGS ID)
    gaugeStages.reset_index(drop=True,inplace=True)
    for idx, row in gaugeStages.iterrows():    
        gaugeStages.at[idx,'stationid'] = idDict[row['stationid']]
    # print(gaugeStages)
    # gaugeStages.to_excel('gauge_stages.xlsx', index=False)

    return gaugeStages

#
# read gauge stage from AHPS or USGS web services
#
def GetGaugeStageFromAhpsUsgsWebServices(gaugeFile, whichStage='Nowcast'):
# whichStage: Nowcast, Forecast, Postcast, and historical stages Action, Flood, Moderate, Major
# fields to return: stationid, x, y, stage_elevation, stage_time, status

    # read gauge file
    gauges = pd.read_excel(gaugeFile, sheet_name='Sheet1')
    
    # Get gauge IDs and organization from the DB table
    gaugeIdOrgs = gauges[["stationid", "organization"]]
    # print(gaugeIdOrgs)

    # get gauge id from the database table for each organization
    ahpsIds = []; usgsIds = []; idDict={}
    for row in gaugeIdOrgs.itertuples(): 
        sid, org = row.stationid, row.organization
        if 'AHPS' in org: # common gauges put into AHPS gauges
            if org == 'AHPS':
                ahpsId = sid
            else: # common gauges
                ahpsId = sid.split(',')[1]
            ahpsIds.append(ahpsId)
            idDict.update({ahpsId:sid})
        elif org == 'USGS':
            usgsIds.append(sid)
    # print(f'AHPS gauges: {len(ahpsIds)}, USGS gauges: {len(usgsIds)}')

    #
    # Get gauge stage from their web services
    #
    ahpsStages = GetAhpsGaugeStageFromWebService(ahpsIds)
    # change stationid to the original id
    for idx, row in ahpsStages.iterrows():    
        # set vertical datum adjustment
        ahpsStages.at[idx,'stationid'] = idDict[row['stationid']]
    print(f'AHPS gauges with stages: {len(ahpsStages)}')
    usgsStages = GetUsgsGaugeStageFromWebService(usgsIds)
    print(f'USGS gauges with stages: {len(usgsStages)}')
    gaugeStages = pd.concat([ahpsStages, usgsStages])
    # gaugeStages.to_excel('gauge_stages.xlsx', index=False)
    # print(gaugeStages)

    # join with the gauges using station ID
    gauges = pd.merge(gauges,gaugeStages,how='left',on='stationid')
    # print(gauges)

    # calculate stage elevation based on "whichStage"
    stageFieldDic = {'Nowcast': 'stage_ft',
                'Forecast': 'stage_ft',
                'Postcast': 'stage_ft',
                'Action': 'action_stage',
                'Flood': 'flood_stage',
                'Moderate': 'moderate_stage',
                'Major': 'major_stage'
                }
    stages = pd.to_numeric(gauges[stageFieldDic[whichStage]], errors='coerce')
    gauges['stage_elevation'] = stages + gauges['datum_elevation'] + gauges['to_navd88']
    # print(gauges)

    # only keep necessary fields
    keptFields = ['stationid','x','y','stage_elevation','stage_time','status']
    gauges = gauges[keptFields]
    # print(gauges)

    # remove stations with nan stage elevation (because of no datum elevation)
    # gauges = gauges[gauges['stage_elevation'].isnull()]

    return gauges

#
# read gauge stage from gauge FC in PostgreSQL database
#
def GetGaugeStageFromGaugeFc(gaugeFcName, whichStage='Nowcast'):
# whichStage: Nowcast, Forecast, Postcast, and historical stages Action, Flood, Moderate, Major
# fields to return: stationid, x, y, stage_elevation, stage_time, status

    #
    # connect to the db
    #
    # read connection parameters
    params = config() # see config.py, parameters are in database.ini
    # connect to the PostgreSQL server
    conn = psycopg2.connect(**params)
    
    # field dic for whichStage
    fieldDic = {'Nowcast': ['stationid','x','y','status','stage_ft','stage_time','datum_elevation','to_navd88'],
                'Forecast': ['stationid','x','y','status','stage_ft','stage_time','datum_elevation','to_navd88'],
                'Postcast': ['stationid','x','y','status','stage_ft','stage_time','datum_elevation','to_navd88'],
                'Action': ['stationid','x','y','status','action_stage','stage_time','datum_elevation','to_navd88'],
                'Flood': ['stationid','x','y','status','flood_stage','stage_time','datum_elevation','to_navd88'],
                'Moderate': ['stationid','x','y','status','moderate_stage','stage_time','datum_elevation','to_navd88'],
                'Major': ['stationid','x','y','status','major_stage','stage_time','datum_elevation','to_navd88'],
                }
    stageFieldDic = {'Nowcast': 'stage_ft',
                'Forecast': 'stage_ft',
                'Postcast': 'stage_ft',
                'Action': 'action_stage',
                'Flood': 'flood_stage',
                'Moderate': 'moderate_stage',
                'Major': 'major_stage'
                }
    # perform query
    fields = fieldDic[whichStage]
    fieldStr = ','.join(fields)
    sqlQuery = f'SELECT {fieldStr} FROM {gaugeFcName}'
    gauges = psql.read_sql(sqlQuery, conn) # or gauges = psql.read_sql_query('select * from fldpln_ks_gauges', conn)
    # print(gauges)

    # calculate stage elevation
    # gauges['stage_elevation'] = gauges['stage_ft']+gauges['datum_elevation']+gauges['to_navd88']
    gauges['stage_elevation'] = gauges[stageFieldDic[whichStage]]+gauges['datum_elevation']+gauges['to_navd88']

    # only keep necessary fields
    keptFields = ['stationid','x','y','stage_elevation','stage_time','status']
    gauges = gauges[keptFields]
    # print(gauges)

    # remove stations with nan stage elevation (because of no datum elevation)
    # gauges = gauges[gauges['stage_elevation'].isnull()]

    return gauges

#
# read gauge stage from PostgreSQL database. THIS FUNCTION IS USED IN OLD CODE IN task_lib2map_gauge_table.py
#
def GetGaugeStageFromPostgres(dbName, gaugeTableName, whichStage='Nowcast'):
# whichStage: Nowcast, Forecast, Postcast, and historical stages Action, Flood, Moderate, Major
# fields to return: stationid, x_utm14, y_utm14, stage_elevation, stage_time, status

    # connect to the db
    conn = psycopg2.connect(
        host="itprdkarsap.home.ku.edu",
        database=dbName,
        user="sde",
        password="avhRR=landsat") 

    # field dic for whichStage
    fieldDic = {'Nowcast': ['stationid','x_utm14','y_utm14','status','stage_ft','stage_time','datum_elevation','to_navd88'],
                'Forecast': ['stationid','x_utm14','y_utm14','status','stage_ft','stage_time','datum_elevation','to_navd88'],
                'Postcast': ['stationid','x_utm14','y_utm14','status','stage_ft','stage_time','datum_elevation','to_navd88'],
                'Action': ['stationid','x_utm14','y_utm14','action_stage','datum_elevation','to_navd88'],
                'Flood': ['stationid','x_utm14','y_utm14','flood_stage','datum_elevation','to_navd88'],
                'Moderate': ['stationid','x_utm14','y_utm14','moderate_stage','datum_elevation','to_navd88'],
                'Major': ['stationid','x_utm14','y_utm14','major_stage','datum_elevation','to_navd88'],
                }
    
    # perform query
    fields = fieldDic[whichStage]
    fieldStr = ','.join(fields)
    sqlQuery = f'SELECT {fieldStr} FROM {gaugeTableName}'
    gauges = psql.read_sql(sqlQuery, conn) # or gauges = psql.read_sql_query('select * from fldpln_ks_gauges', conn)
    # print(gauges)

    # calculate stage elevation
    gauges['stage_elevation'] = gauges['stage_ft']+gauges['datum_elevation']+gauges['to_navd88']

    # only keep necessary fields
    keptFields = ['stationid','x_utm14','y_utm14','stage_elevation','stage_time','status']
    gauges = gauges[keptFields]
    # print(gauges)

    # remove stations with nan stage elevation (because of no datum elevation)
    # gauges = gauges[gauges['stage_elevation'].isnull()]

    return gauges