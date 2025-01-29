""" The FLDPLN model module. This module implements the FLDPLN singleton class which exposes the MATLAB functions in the fldpln_py package/library created by MATLAB. 
    In essence, the FLDPLN class hides the conversion from Python variables to MATLAB data types in those functions. 
"""

# 
# Compared with the module implementation in fldplnpy0.py, implementing it as a singleton class has the following advantages:
# 1. It hide the fldpln_py_handle variable into the instance instead of exposing it as a module variable which can reduce potential conflict and over-writing
# 2. It hides the initialization and termination steps in the constructor and destructor so that the object behaviors more like a typical/normal object
#

# # import FLDPLN python package created by MATLAB
# import fldpln_py # commented as it cannot be installed using pip
# # MATLAB Compiler SDK generated Python modules. Import the matlab module only after you have imported other packages
# import matlab # commented as it cannot be installed using pip

#
# The FLDPLN singleton class for using the fldpln_py Python package generated in MATLAB
#
class FLDPLN:
    """ A singleton class for using the fldpln_py Python package generated in MATLAB.
    """

    # implement the FLDPLN class as a Singleton class, i.e., only one instance for the class
    # see https://www.geeksforgeeks.org/singleton-pattern-in-python-a-complete-guide/
    def __new__(cls):
        # import FLDPLN python package created by MATLAB
        import fldpln_py

        if not hasattr(cls, 'instance'):
            # first (and ONLY instance)
            cls.instance = super(FLDPLN, cls).__new__(cls) 

            # initialize the fldpln_py library when the only instance is created
            try:
                print('Initialize the FLDPLN model ...')
                cls.instance.fldpln_py_handle = fldpln_py.initialize()
                print('Done!')
            
            except Exception as e:
                print('Error initializing fldpln_py package\\n:{}'.format(e))
                exit(1)

        return cls.instance
    
    # Calling destructor to terminate the reference to the library
    def __del__(self):

        print('Terminate the FLDPLN model ...')
        self.fldpln_py_handle.terminate()

    # Initialize the library
    # def Initialize(self):
    #     # Initialize MATLAB fldpln_py library and retrieve a handle to it
    #     print('Initialize the fldpln_py library ...')
    #     try:
    #         self.fldpln_py_handle = fldpln_py.initialize()
        
    #     except Exception as e:
    #         print('Error initializing fldpln_py package\\n:{}'.format(e))
    #         exit(1)

    # Generate stream segments for building library
    def GenerateSegments(self,fdrf, facf, strfac, segfac, seglen, segdir):
        """ Generate stream segments for building segment-based FLDPLN library
            Args:
                fdrf (str): Flow direction BIL file path
                facf (str): Flow accumulation BIL file path
                strfac (int): Stream flow accumulation threshold (in sq. miles) for identifying stream networks
                segfac (int): Stream flow accumulation threshold (in sq. miles) used for creating segments along stream networks
                seglen (int): Segment length threshold (in miles) used for creating segments along stream networks
                segdir (str): Output directory for segment files

            Returns:
                None: No return value
        """

        import matlab

        try:
            # generate stream segments
            fdrfIn = fdrf
            facfIn = facf
            strfacIn = matlab.double([strfac], size=(1, 1))
            segfacIn = matlab.double([segfac], size=(1, 1))
            seglenIn = matlab.double([seglen], size=(1, 1))
            segdirIn = segdir

            print('Generate segments ...')
            self.fldpln_py_handle.rp_generate_segments(fdrfIn, facfIn, strfacIn, segfacIn, seglenIn, segdirIn, nargout=0)
            print('Done!')
            
        except Exception as e:
            print('Error occurred during program execution\\n:{}'.format(e))

    # Write segment and FSP as CSV files
    def WriteSegmentFspCsvFiles(self,bildir, segdir, seg_list, outdir=None, fileType='csv'):
        """ Write segment and FSP as CSV files for viewing or creating segment shapefile
            Args:
                bildir (str): BIL file directory
                segdir (str): Segment file directory
                seg_list (list): List of integer segment IDs to be exported. If empty, all segments will be exported
                outdir (str): Output directory for the CSV files. If None, the output will be saved in the segment file directory
                fileType (str): FSP output file type. Choose from {'mat', 'csv'}. default is 'csv'

            Returns:
                None: No return value
        """

        import matlab

        try:
            # write FSP and segment info CSV files
            bildirIn = bildir
            segdirIn = segdir

            # handle segment list
            segLstLen = len(seg_list)
            if segLstLen == 0: # empty list, all segments will be exported
                seg_listIn = matlab.double([], size=(0, 0)) 
            else:
                seg_listIn = matlab.double(seg_list, size=(segLstLen, 1))

            # prepare output folder
            if outdir is None:
                outdirIn = segdirIn
            else:
                outdirIn = outdir

            print('Write FSP and segment files ...')
            self.fldpln_py_handle.ut_write_fsp_segment_csv_files(bildirIn, segdirIn, seg_listIn, outdirIn, fileType, nargout=0)
            print('Done!')
            
        except Exception as e:
            print('Error occurred during program execution\\n:{}'.format(e))

    # Create FLDPLN segment-based library
    def CreateSegmentLibrary(self,bildir, segdir, filmskfile, segshpfile, fldmn, fldmx, dh, mxht, libdir, mtype, para):
        """ Create segment-based FLDPLN library
            Args:
                bildir (str): BIL file directory
                segdir (str): Segment file directory
                filmskfile (str): Spatial mask BIL file path used to limit the modeling. If no mask, set to ''
                segshpfile (str): A shapefile that contains the segments to be used in the library. If all segments are used, set to ''
                segshpfile (dict): Dictionary containing the shapefile information
                    file (str): Shapefile path that contains the select subset of segments, set to '' if all segments are used
                    segid_field (str): Field name in the shapefile that contains the segment ID
                    seg_fldmx_field (str): Field name in the shapefile that contains the fldmx value. Set to '' if all segments use the same fldmx
                fldmn (float): Minimum flood stage assumed, typically set to 1 centimeter or 0.0328084 foot depends on DEM's vertical unit
                fldmx (float): Maximum stage modeled
                dh (float): Vertical step size in DEM's vertical unit
                mxht (float): max dem+flood height to cease flooding. Usually set 0 for no cap height
                libdir (str): Output directory for the segment-based library
                mtype (str): FLDPLN model type. Choose from {'hd', 'ram0', 'ram'}
                para (dict): Dictionary containing parallelization settings when running the model.
                    type (str): Parallelization type. Choose from {'none', 'parfor', 'parfeval'}
                    numcores (int): Number of cores to use. Set to 0 to use all available cores
                    worker_type (str): Type of workers, 'Processes' or 'Threads'. Default is 'Processes' as MATLAB Runtime does not support 'Threads'

            Returns:
                None: No return value
        """

        import matlab

        try:
            bildirIn = bildir
            segdirIn = segdir
            filmskfileIn = filmskfile
            segshpfileIn = segshpfile
            fldmnIn = matlab.double([fldmn], size=(1, 1))
            fldmxIn = matlab.double([fldmx], size=(1, 1))
            dhIn = matlab.double([dh], size=(1, 1))
            mxhtIn = matlab.double([mxht], size=(1, 1)) # default 0
            libdirIn = libdir

            # model types: hd, ram0, ram
            mtypeIn = mtype

            # parallelization settings
            paraIn = para
            if 'numcores' in para.keys():
                # convert user input of core number to MATLAB data type, and keep other string parameters
                # paraIn = {"type": para['type'], "numcores": matlab.double([para['numcores']], size=(1, 1))}
                paraIn["numcores"] = matlab.double([para['numcores']], size=(1, 1))

            # create library
            print('Create segment-based library ...')
            self.fldpln_py_handle.rp_create_segment_library_v8(bildirIn, segdirIn, filmskfileIn, segshpfileIn, fldmnIn, fldmxIn, dhIn, mxhtIn, libdirIn, mtypeIn, paraIn, nargout=0)
            print('Done!')

        except Exception as e:
            print('Error occurred during program execution\\n:{}'.format(e))

    # Reformat segment-based library for tiling and mapping
    def FormatSegmentLibrary(self,bildir, segdir, libdir, dirout):
        """ Reformat segment-based library for tiling and mapping

            Args:
                bildir (str): BIL file directory
                segdir (str): Segment file directory
                libdir (str): Raw segment-based library directory
                dirout (str): Output directory for the reformatted library

            Returns:
                None: No return value
        """

        try:
            bildirIn = bildir
            segdirIn = segdir
            libdirIn = libdir
            diroutIn = dirout

            print('Reformat segment-based library ...')
            self.fldpln_py_handle.rp_format_segment_library(bildirIn, segdirIn, libdirIn, diroutIn, nargout=0)
            print('Done!')

        except Exception as e:
            print('Error occurred during program execution\\n:{}'.format(e))

    def GenerateStreamOrder(self, bildir, segdir, segshp):
        """ Generate stream order for the segments

            Args:
                bildir (str): BIL file directory
                segdir (str): Segment file directory
                segshp (str): Selected segment shapefile

            Returns:
                None: No return value
        """

        try:
            bildirIn = bildir
            segdirIn = segdir
            segshpIn = segshp

            print('Generate stream order ...')
            self.fldpln_py_handle.rp_generate_stream_order(bildirIn, segdirIn, segshpIn, nargout=0)
            print('Done!')
            
        except Exception as e:
            print('Error occurred during program execution\\n:{}'.format(e))

# end of class FLDPLN


####################################################################################################
# test the module        
####################################################################################################
if __name__ == "__main__":
    import os

    # Create the FLDPLN object, which initializes the fldpln_py library
    fldpln = FLDPLN()

    # # Test FLDPLN as a singleton class!
    # fldpln2 = FLDPLN()
    # print('fldpln is fldpln2: ', fldpln is fldpln2)
    
    #
    # Generate stream network segments
    #
    # Wildcat example
    bildir = 'E:/fldpln/sites/wildcat_10m_3dep/bil'
    segdir = 'E:/fldpln/sites/wildcat_10m_3dep/segs_py'
    # Verdigris example
    # bildir = 'E:/fldpln/sites/verdigris_10m/bil'
    # segdir = 'E:/fldpln/sites/verdigris_10m/segs'

    # Input flow direction and accumulation BIL files
    fdrf = os.path.join(bildir,'fdr.bil')
    facf = os.path.join(bildir,'fac.bil')

    # segment parameters
    strfac = 50 # flow accumulation threshold (in sq. miles) for identifying stream networks. 50 for Wildcat to include the upstream gauge. 70 for Verdigris and most KS watersheds
    segfac = 25 # flow accumulation threshld (in sq. miles) for segment stream networks. 25 is the default in KS
    seglen = 2 # segment length in miles. usually is the SQRT of sgefac. 2 for Wildcat and 5 for Verdigris and others in KS

    # generate segments
    fldpln.GenerateSegments(fdrf, facf, strfac, segfac, seglen, segdir)

    #
    # write FSP and segment info CSV files for creating segment shapefile
    #
    seg_list = [] # for all the segments
    # seg_list = [1,2,3] # for a subset of segments
    fldpln.WriteSegmentFspCsvFiles(bildir, segdir, seg_list, segdir, 'mat')

    #
    # Create segment-based library
    #
    # set input and output folders
    # Wildcat example
    bildir = 'E:/fldpln/sites/wildcat_10m_3dep/bil' 
    segdir = 'E:/fldpln/sites/wildcat_10m_3dep/segs_py'
    libdir = 'E:/fldpln/sites/wildcat_10m_3dep/rawlib_py' # raw sgement-based library

    # Verdigris example
    # bildir = 'E:/fldpln/sites/verdigris_10m/bil' # 'wildcat_10m' downsampled from 2m LIDAR DEM; #'wildcat_3dep' from NWC input
    # segdir = 'E:/fldpln/sites/verdigris_10m/segs'
    # lib1--all segments with same fldmx; lib2--selected segments with the same fldmx; lib3--selected segments with different fldmx
    # libdir = 'E:/fldpln/sites/verdigris_10m/seglib_dam'
    # libdir = 'E:/fldpln/sites/verdigris_10m/seglib_fldsensing'

    # Applying spatial mask if provided. The masked filled DEM removes waterbodies to prevent flooding them.
    # In the future, only a mask raster BIL is need which will be applied to filled DEM instead of a masked filled DEM that's currently used!
    filmskfile = '' # no spatial mask for Wildcat
    # filmskfile = 'E:/fldpln/sites/verdigris_10m/bil/fil_masked.bil'

    # Select a subset of segments or remove segments within waterbodies before creating a FLDPLN library
    # The subset of segments is defined using a shapefile.
    # segshpfile = {'file': ''} # all the segments will be used and they use the fldmx
    segshpfile = {'file':'E:/fldpln/sites/wildcat_10m_3dep/segment_shapefiles/wildcat_segments.shp'} # wildcat creek segments
    # segshpfile = {'file':'E:/fldpln/sites/verdigris_10m/segs_5mi/dam_break_segments.shp'} # verdigris

    # Additional attributes if a sgement shapefile is provided
    segshpfile['segid_field'] = 'grid_code'
    segshpfile['seg_fldmx_field'] = '' # set to '' when all the segments use the fldmx. Otherwise specify a field in the shapefile

    # Set FLDPLN model parameters
    fldmn = 0.01 # typically set to 1 centermeter or 0.0328084 foot DEM's vertical unit
    fldmx = 15 # max. stage modeled. wildcat_10m_3dep and verdigris DEM vertical unit is in meters
    dh = 1 # vertical step size in DEM's vertical unit
    mxht = 0 # max(dem+flood height) to cease flooding. enter 0 for no cap height

    # FLDPLN model efficiency parameters
    # model type: choose one from {'hd', 'ram0', 'ram'}. 
    mtype = 'ram' # choose either 'ram' (machine has RAM >= 64G) or 'hd' (uses least RAM)
    # parallelization setting: 'none', 'parfor', 'parfeval'; recommend either 'parfeval'
    para = {'type': 'parfeval'}
    # Can also set the number of cores. Will use max. cores if the attribute is NOT set
    para['numcores'] = 6 # my office computer has 8 core. Comment out to use all the cores available
    para['worker_type'] = 'Processes' # 'Processes' is default
    # para['worker_type'] = 'Threads' # 'Threads' is not supported by compiled Python package!

    # Create segment library
    fldpln.CreateSegmentLibrary(bildir, segdir, filmskfile, segshpfile, fldmn, fldmx, dh, mxht, libdir, mtype, para)
    
    #
    # Format segment-based library for tiling and mapping
    #
    # BIL file directory
    bildir = 'E:/fldpln/sites/wildcat_10m_3dep/bil' # Wildcat
    # bildir = 'E:/fldpln/sites/verdigris_10m/bil'
    # segment file directory
    segdir = 'E:/fldpln/sites/wildcat_10m_3dep/segs_py'
    # segdir = 'E:/fldpln/sites/verdigris_10m/segs'

    # raw segment library dir
    libdir = 'E:/fldpln/sites/wildcat_10m_3dep/rawlib_py'
    # libdir = 'E:/fldpln/sites/verdigris_10m/seglib_fldsensing'

    # Outputs:
    # Output library folder
    dirout = 'E:/fldpln/sites/wildcat_10m_3dep/seglib_py' # reformatted library for tiling and mapping
    # dirout = 'E:/fldpln/sites/verdigris_10m/lib_fldsensing'

    # Format raw segment library
    fldpln.FormatSegmentLibrary(bildir, segdir, libdir, dirout)

    #
    # Generate stream order for the selected segments
    #
    # BIL file directory
    bildir = 'E:/fldpln/sites/wildcat_10m_3dep/bil' # Wildcat
    # segment file directory
    segdir = 'E:/fldpln/sites/wildcat_10m_3dep/segs_py'
    # Selected segment shapefile
    segshp = 'E:/fldpln/sites/wildcat_10m_3dep/segment_shapefiles/wildcat_segments.shp' # Wildcat

    # Generate stream order
    fldpln.GenerateStreamOrder(bildir, segdir, segshp)

    #
    # Note that the fldpln_py library is automatically terminated when the FLDPLN object destroyed at the end of the script!
    #