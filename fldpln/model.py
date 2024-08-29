# 
# This class module exposes the MATLAB functions in the fldpln_py package/library which is created by MATLAB.
# In essence, it hides the conversion from Python variables to MATLAB data types in those functions. 
#
# Compared with the module implementation in fldplnpy0.py, implementing it as a singleton class has the following advantages:
# 1. It hide the fldpln_py_handle variable into the instance instead of exposing it as a module variable which can reduce potential conflict and over-writing
# 2. It hides the initialization and termination steps in the constructor and destructor so that the object behaviors more like a typical/normal object
#

# # import FLDPLN python package created by MATLAB
# import fldpln_py

# # Import the matlab module only after you have imported 
# # MATLAB Compiler SDK generated Python modules.
# import matlab

#
# The FLDPLN singleton class for using the fldpln_py Python package generated in MATLAB
#
class FLDPLN:

    # implement the FLDPLN class as a Singleton class, i.e., only one instance for the class
    # see https://www.geeksforgeeks.org/singleton-pattern-in-python-a-complete-guide/
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            # first (and ONLY instance)
            cls.instance = super(FLDPLN, cls).__new__(cls) 

            # initialize the fldpln_py library when the only instance is created
            print('Initialize FLDPLN model python package ...')
            try:
                cls.instance.fldpln_py_handle = fldpln_py.initialize()
            
            except Exception as e:
                print('Error initializing fldpln_py package\\n:{}'.format(e))
                exit(1)

        return cls.instance
    
    # Calling destructor to terminate the reference to the library
    def __del__(self):
        print('Terminate FLDPLN model python package.')
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
        try:
            # generate stream segments
            fdrfIn = fdrf
            facfIn = facf
            strfacIn = matlab.double([strfac], size=(1, 1))
            segfacIn = matlab.double([segfac], size=(1, 1))
            seglenIn = matlab.double([seglen], size=(1, 1))
            segdirIn = segdir
            self.fldpln_py_handle.rp_generate_segments(fdrfIn, facfIn, strfacIn, segfacIn, seglenIn, segdirIn, nargout=0)
            
        except Exception as e:
            print('Error occurred during program execution\\n:{}'.format(e))

    # Write segment and FSP as CSV files
    def WriteSegmentFspCsvFiles(self,bildir, segdir, seg_list, outdir=None):
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

            self.fldpln_py_handle.ut_write_fsp_segment_csv_files(bildirIn, segdirIn, seg_listIn, outdirIn, nargout=0)
            
        except Exception as e:
            print('Error occurred during program execution\\n:{}'.format(e))

    # Create FLDPLN segment-based library
    def CreateSegmentLibrary(self,bildir, segdir, filmskfile, segshpfile, fldmn, fldmx, dh, mxht, libdir, mtype, para):

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
                # convert user input of core number to MATLAB data type, and keep other sting parameters
                # paraIn = {"type": para['type'], "numcores": matlab.double([para['numcores']], size=(1, 1))}
                paraIn["numcores"] = matlab.double([para['numcores']], size=(1, 1))

            # create library
            self.fldpln_py_handle.rp_create_segment_library_v8(bildirIn, segdirIn, filmskfileIn, segshpfileIn, fldmnIn, fldmxIn, dhIn, mxhtIn, libdirIn, mtypeIn, paraIn, nargout=0)

        except Exception as e:
            print('Error occurred during program execution\\n:{}'.format(e))

    # Reformat segment-based library for tiling and mapping
    def FormatSegmentLibrary(self,bildir, segdir, libdir, dirout):
        try:
            bildirIn = bildir
            segdirIn = segdir
            libdirIn = libdir
            diroutIn = dirout
            self.fldpln_py_handle.rp_format_segment_library(bildirIn, segdirIn, libdirIn, diroutIn, nargout=0)

        except Exception as e:
            print('Error occurred during program execution\\n:{}'.format(e))

    # # Terminate the library
    # def Terminate(self):
    #     print('Terminate the fldpln_py library.')
    #     self.fldpln_py_handle.terminate()

#
# test the module        
#
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
    fldpln.WriteSegmentFspCsvFiles(bildir, segdir, seg_list, segdir)

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
    # model type: choos one from {'hd', 'ram0', 'ram'}. 
    mtype = 'ram' # choos either 'ram' (machine has RAM >= 64G) or 'hd' (uses least RAM)
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
    dirout = 'E:/fldpln/sites/wildcat_10m_3dep/seglib_py' # reformated library for tiling and mapping
    # dirout = 'E:/fldpln/sites/verdigris_10m/lib_fldsensing'

    # Format raw segment library
    fldpln.FormatSegmentLibrary(bildir, segdir, libdir, dirout)

    #
    # Note that the fldpln_py library is automatically terminated when the FLDPLN object destroyed at the end of the script!
    #