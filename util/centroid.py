#dasp, the Durham Adaptive optics Simulation Platform.
#Copyright (C) 2004-2016 Alastair Basden and Durham University.

#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU Affero General Public License as
#published by the Free Software Foundation, either version 3 of the
#License, or (at your option) any later version.

#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU Affero General Public License for more details.

#You should have received a copy of the GNU Affero General Public License
#along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""A module to compute the centroids of an input phase, as if this phase has been put into a SHS.
This can be used by the aosim simulation, or as standalone code.  When using
as stand alone code, typically you would create a centroid object, and then 
call the "run" method, passing in your phase.  Currently, using as stand alone
code means that the FPGAs cannot be easily used - though you can probably
change this easily enough if required.
"""
import util.flip,cmod.binimg
import cmod.imgnoise
import scipy.interpolate
import numpy,numpy.random,numpy.fft
import util.arrayFromArray
import util.poisson,time,os
import util.dist
import util.centcmod
import util.correlation
# haveFPGA=1
# try:
#     import fpga
# except:
#     print "FPGA module not installed."
#     haveFPGA=0
# haveCell=1
# try:
#     import util.centcell
# except:
#     print "cell centcell/centppu module not installed"
#     haveCell=0


def pxlToRadTiltTheoretical(nsubx,phasesize,nimg,wfslam,telDiam):
    """compute the centroid pixel to radians of tilt scaling factor theoretically.  telDiam is in m, wfslam in nm.
    The logic behind this is as follows:
    Consider a collimated beam incident on a lens with focal length f.  The offset of the focussed
    spot in the image plane, x, is then x=f tan(t) where t is the angle of the incident wavefront.
    So, the question then is what is f in the simulation?  For each subaperture, there are n_p
    phase pixels, each with width z_p.  Similarly there are n_d detector pixels with width z_d.
    We note that n_p * z_p = n_d * z_d.
    Now, the airy disk created by the simulation is 2.44 * oversamplefactor pixels in diameter,
    where oversamplefactor is n_d/n_p.  The diameter of an airy spot is 2.44 lambda f/d = 2.44*l*f/(n_p*z_p).
    However, this is equal to the number of detector pixels wide, times the width of a detector
    pixel, i.e. 2.44*(n_d/n_p)*z_d.
    (Each pixel is lambda/d/oversamplefactor wide).  
    Equating these two expressions and cancelling terms therefore gives f = n_p * z_p^2/l.
    Therefore:
    t(x)=arctan(l * x / (n_p * z_p^2))

    So, multiply the centroids (in pixels) by this value to get the phase slopes in radians.
    When doing this, use x=1 pixel, ie x=telDiam/nsubx/nimg
    """
    npup=phasesize*nsubx
    x=telDiam/nsubx/nimg
    return numpy.arctan2((wfslam*1e-9*x),(phasesize*(telDiam/npup)**2.))#this is the radians of tilt that would give a 1 pixel shift in centroid algorithm.

def pxlToRadPistonTheoretical(nsubx,phasesize,nimg,wfslam,telDiam):
    """compute the centroid pixel to radians of piston scaling factor theoretically.  Here, the radians of piston are the wavefront that gives a certain tilt across a subaperture.
    """
    tilt=pxlToRadTiltTheoretical(nsubx,phasesize,nimg,wfslam,telDiam)#get radians of tilt that give a centroid shift of 1 pixel.
    #Then convert this tilt into a piston...
    x=numpy.tan(tilt)*(telDiam/nsubx)#piston in m...
    return x*2*numpy.pi/(wfslam*1e-9)
    
    
def wfs_sig(bandwidth,thruput,rateFactor,telDiam,nsubx,integTime,magnitude):
    """wfs signal per exposure
    bandwidth in angstroms (optical bandwidth)
    thruput including DQE etc
    rateFactor Photons/cm^2/s/Angstrom
    telDiam in m
    """
    pupilArea=(telDiam*100./nsubx)**2.      # Pupil area/cm^2
    sig=rateFactor*thruput*bandwidth*integTime*pupilArea/(2.5**magnitude) # Detected image photons
    #print 'WFS  photons/subap/integration: ',sig
    return sig

class centroid:
    """This class can be used as a library, to do wfs/centroid calculations.
    It is also used by the AO simulation, wfscent.py module.  So, any
    changes made here, will affect the simulation.
    This module can use the FPGAs.
    When used in the simulation framework, it enables resource sharing
    (memory and FPGA shared by more than one wfscent algorithm calculator).

    To use on the command line, you need:
    c=util.centroid.centroid(nsubx,util.tel.Pupil(npup,npup/2,0,nsubx),fftsize=fftsize,binfactor=None,phasesize=phasesize,nimg=nimg,ncen=ncen)#addPoisson=0,sig=1.
    c.easy()
    c.runCalc({"cal_source":0})
    c.outputData is the slopes
    c.cmodbimg is the wfs image (divided into subaps).
    Then, put your data into self.reorderedPhs... 
    c.reformatImg() can be used to get a displayable image.
    If you have a 2D phase map, you can put this into reorderdPhs by calling:
    c.reformatPhs(phs)

    Or, you can use util.centroid.compute(phase,nsubx) which does the same thing.

    """
    #def __init__(self,nsubx,pup=None,oversamplefactor=1,readnoise=0.,readbg=0.,addPoisson=0,noiseFloor=0.,binfactor=1,sig=1.,skybrightness=0.,warnOverflow=None,atmosPhaseType="phaseonly",fpDataType=numpy.float32,useFPGA=0,waitFPGA=0,waitFPGATime=0.,phasesize=None,fftsize=None,clipsize=None,nimg=None,ncen=None,tstep=0.05,integtime=0.05,latency=0.,wfs_minarea=0.5,spotpsf=None,centroidPower=None,opticalBinning=0,useCell=0,waitCell=1,usecmod=1,subtractTipTilt=0,magicCentroiding=0,linearSteps=None,stepRangeFrac=1.,phaseMultiplier=1,centWeight=None,correlationCentroiding=0,corrThresh=0.,corrPattern=None,threshType=0,imageOnly=0,calNCoeff=0,useBrightest=0):
    def __init__(self, nsubx, pup=None, oversamplefactor=1, readnoise=0,
          readbg=0., addPoisson=0, noiseFloor=0., binfactor=1, sig=1.,
          skybrightness=0., warnOverflow=None, atmosPhaseType="phaseonly",
          fpDataType=numpy.float32, phasesize=None, fftsize=None, clipsize=None,
          nimg=None, ncen=None, tstep=0.05, integtime=0.05, latency=0.,
          wfs_minarea=0.5, spotpsf=None, centroidPower=None, opticalBinning=0,
          usecmod=1, subtractTipTilt=0, magicCentroiding=0, linearSteps=None,
          stepRangeFrac=1., phaseMultiplier=1, centWeight=None,
          correlationCentroiding=0, corrThresh=0., 
          corrPattern=None, threshType=0, imageOnly=0, calNCoeff=0,
          useBrightest=0, printLinearisationForcing=0, rowintegtime=None,
                 preBinningFactor=1,parabolicFit=0,gaussianFitVals=None,seed=1,integstepFn=None,inputImage=None,subapLocation=None):
        """
        Variables are:
         - sig: is the number of photons per phase pixel if pupfn is specified,
           or is the number of photons per subap if not (ie same...)  Or is a
           2D array, with a value for each subap.  If this is just a number, it
           will be scaled by the number of used phase pixels for each subap.
           If an array, assumes that this scaling has already been done.  Use
           an array version for eg LGS spot elongation.
         - nsubx: number of subaps in 1 direction
         - pupfn: pupil function array (pupil mask) or util.tel.Pupil instance
           (if using PS3).
         - oversamplefactor: scaling to expand phase by when doing FFTs.
           Ignored if fftsize!=None.
         - readnoise: ccd readnoise
         - readbg: mean added signal from CCD.
         - addPoisson: whether to add photon shot noise
         - noiseFloor: Floor to apply to images.
         - binfactor: Bin factor to apply to get from FFT'd data to image.
           Ignored if nimg!=None.
         - sig: signal
         - skybrightness: photons to add per pixel due to sky background
         - warnOverflow: will warn if the CCD is about to overflow
           (warnOverflow holds the saturation value)
         - atmosPhaseType: Type of phase from atmos module, eg phaseonly
         - fpDataType: data type used for calculations.
         - useFPGA: Whether FPGA should be used - shouldn't change.
         - waitFPGA: whether to wait for FPGA to finish before returning from
           calc.
         - waitFPGATime: time to wait before polling begins.
         - phasesize: wfs_n - number of phase pixels per subap
         - fftsize: wfs_nfft - number of pixels to use for FFT (zero pad
           phasesize...)
         - nimg: Number of pixels wide the subap image should be.
         - ncen: Number of subap image pixels used to compute centroid (eg
           could leave a dead ring around edge etc).
         - tstep: time per iteration
         - integtime: total integration time
         - rowintegtime: integration time per sub-aperture row (default=None),
           should be <integtime.  Non-default use of this parameter is designed
           for *crude* simulation of a rolling shutter. Properly, each pixel
           row of the WFS should be staggered but this variable only permit
           staggering of each sub-aperture row. Currently only implemented in
           the Python version.
         - latency: latency between readout starting and centroids being
           returned.
         - wfs_minarea: minimum fraction of subap receiving phase to allow it
           to be counted.
         - spotpsf: array (2 or 4d) of spot pattern PSFs.
         - centroidPower: None, or value to raise image to before centroiding.
         - opticalBinning: whether cylindrical lenslets are used, to do binning
           in 1 direction...
         - magicCentroiding: whether to measure phase slopes directly, or use
           SHS
         - linearSteps: None, or the number of steps to be used to try to use
           SH centroiding, but with a linear response (useful for openloop).
           If None, linearisation is not carried out.
         - stepRangeFrac: The fraction of a subap over which to calibrate using
           linearSteps... default 1 for all of a subap.
         - phaseMultiplier can be non-unity if phase is at a different
           wavelength than you want to wfs at.
         - centWeight - weighting factor (array, 2 or 4D) for weight CoG
           centroiding.
         - correlationCentroiding - whether correlation centroiding is used.
         - corrThresh - subtraction threshold if using correlation cnetroiding
         - corrPattern - e.g. spot PSFs.
         - threshType - the threshold type for removing CCD read noise: If ==0,
           where(ccd<thresh:0:ccd-thresh) If ==1, where(ccd<thresh:0,ccd)
         - imageOnly - usually 0, but can be 1 or 2 if want to compute the CCD
           image only.
         - calNCoeff - used if linearSteps!=0, the number of coeffencients to
           use in polynomial fit (if this is zero, an interpolation routine is
           used instead)
         - useBrightest - int or array, if want to use brightest pixels
           algorithm.
         - preBinningFactor - integer to bin the FFT'd phase, before convolving
           with PSF.
         - seed - random number seed
         - integstepFn - None or a function to return the number of integration steps, which is called at the start of each integration.
         - inputImage - only used if wfscent is gettting image rather than phase data.  
         - subapLocation - optionally used if inputImage is used.  For each subap, this has (yfrom,yto,xfrom,xto) - i.e. same as darc but without the step.
        """
        self.nsubx=nsubx
        self.warnOverflow=warnOverflow
        self.sig=sig
        self.timing=0
        self.skybrightness=skybrightness
        self.pup=pup
        if type(pup)==numpy.ndarray or type(pup)==type(None):
            self.pupfn=pup
        else:
            self.pupfn=pup.fn
        self.oversamplefactor=oversamplefactor
        self.readnoise=readnoise
        self.readbg=readbg
        self.threshType=threshType
        self.imageOnly=imageOnly
        self.useBrightest=useBrightest
        self.preBinningFactor=preBinningFactor
        self.binfactor=binfactor
        self.atmosPhaseType=atmosPhaseType
        self.fpDataType=fpDataType
        # self.useFPGA=useFPGA#shouldn't change
        # self.waitFPGA=waitFPGA
        # self.waitFPGATime=waitFPGATime
        # self.useCell=useCell#shouldn't change
        # self.waitCell=waitCell
        self.phasesize=phasesize
        self.fftsize=fftsize
        self.clipsize=clipsize
        self.nimg=nimg
        self.ncen=ncen
        if self.clipsize==None:
            self.clipsize=self.fftsize
        if self.fftsize!=None and self.phasesize!=None:
            self.oversamplefactor=float(self.fftsize)/self.phasesize
        if self.clipsize!=None and self.nimg!=None:
            self.binfactor=float(self.clipsize)/self.nimg
        self.tstep=tstep
        self.integtime=integtime
        self.latency=latency
        self.integstepFn=integstepFn#None, or a function if variable integration time is required.  
        self.nIntegrations=int(numpy.ceil(self.integtime/self.tstep))
        self.rowintegtime=None # start with this
        if rowintegtime!=None:
            if usecmod:
               raise RuntimeError("ERROR: Currently you cannot have the "+
                     "rolling shutter integrated with the C-module")
            if rowintegtime>integtime:
               print("ERROR:**centroid**: rowintegtime>integtime")
            elif (rowintegtime/integtime)>1:
               print("ERROR:**centroid**: Oops! rowintegtime long")
            elif (rowintegtime<tstep):
               print("ERROR:**centroid**: Woah! rowinteg<tstep")
            else:
               self.rowintegtime=rowintegtime
               self.rowinteg_nIntegrations=int(numpy.ceil(rowintegtime/tstep))
        if self.rowintegtime!=None:
            r=self.rowintegtime/self.tstep
            l=self.nIntegrations-r
            print("INFORMATION:DEBUG:**centroid**:"+
                     "Rolling Shutter approximation")
            print("INFORMATION:DEBUG:**centroid**:"+
                     "**r**=# integ/row,**l**=# integ skipped for last row")
            print("INFORMATION:DEBUG:**centroid**:"+
                     "**r**={0[0]:d}, **l**={0[1]:d}".format(
                           [int(x) for x in (r,l)]))
            print("INFORMATION:DEBUG:**centroid**:"+
                     "**#**integ.={0:d}".format( int(self.nIntegrations) ))
        self.wfs_minarea=wfs_minarea
        self.psf=spotpsf#eg createAiryDisc(self.fftsize,self.fftsize/2,0.5,0.5)
        self.centroidPower=centroidPower
        self.opticalBinning=opticalBinning
        self.parabolicFit=parabolicFit
        self.gaussianFitVals=gaussianFitVals
        self.centWeight=centWeight

        #stuff for correlation centroiding...
        self.correlationCentroiding=correlationCentroiding
        self.corrThresh=corrThresh
        self.corrPatternUser=corrPattern
    
        if correlationCentroiding:
            self.corrimg=numpy.zeros(corrPattern.shape,numpy.float32)
            if correlationCentroiding==1:
                self.corrPattern=util.correlation.transformPSF(self.corrPatternUser)
            else:
                self.corrPattern=self.corrPatternUser.copy()
        else:
            self.corrPattern=None
            self.corrimg=None
        self.refCents=None

        self.convFactor=1.#convert from radians to centroids.
        self.printmax=0
        self.texp=0.#current exposure time.
        self.lastCalSource=0#value of calSource in last iteration (do we need to reload FPGA values?)
        self.addPoisson=addPoisson
        self.noiseFloor=noiseFloor
        self.usecmod=usecmod#should we use the cmodule version?
        self.subtractTipTilt=subtractTipTilt
        self.printLinearisationForcing=printLinearisationForcing
        self.phasesize_v=self.phasesize#if using cell, this gets increased to a vectorised version (see below).
        if type(self.pupfn)!=type(None) and oversamplefactor!=None:
            self.subarea=numpy.ones((nsubx,nsubx),numpy.float64)
            n=self.pupfn.shape[0]/nsubx
            for i in range(nsubx):
                for j in range(nsubx):
                    self.subarea[i,j]=numpy.sum(numpy.sum(self.pupfn[i*n:(i+1)*n,j*n:(j+1)*n]))
        else:
            self.subarea=None
        self.wfsn=8#this is changed when phase is input...
        if self.nsubx!=1 and oversamplefactor!=None and binfactor!=None:
            self.computePxlToRad(self.wfsn)

        self.magicCentroiding=magicCentroiding
        self.linearSteps=linearSteps
        self.calNCoeff=calNCoeff
        self.stepRangeFrac=stepRangeFrac
        self.inputImage=inputImage
        self.subapLocation=subapLocation
        self.phaseMultiplier=phaseMultiplier
        if magicCentroiding:
            self.magicSlopes=None#self.magicSHSlopes()
        self.outSquare=None#for covariance calculation.
        self.outSum=None
        self.outN=0
        #if self.pupfn==None:
        #    pfn=numpy.ones((1,1),self.fpDataType)
        #else:
        self.subarea = self._calculateSubAreas()
        (  self.indices, self.nsubaps ) = self._calculateIndices()
        self.seed=seed
        #print "Created centroid object"
    
    def _calculateSubAreas(self):
        subarea = numpy.zeros((self.nsubx,self.nsubx),numpy.float64)
        n=self.phasesize
        pfn = numpy.array( self.pupfn ).astype(self.fpDataType)
        # This could (and would be nice to) be replaced by
        # util.tel.pupil.getSubapFlag, but the "indeces" should be taken care
        # of (a bit of work), so we leave like this for now:
        for i in xrange(self.nsubx):        
            for j in xrange(self.nsubx):
                # Get pupil fn over subaps 
                subarea[i,j]=pfn[i*n:(i+1)*n,j*n:(j+1)*n].sum()
        return subarea

    def _calculateIndices(self):
        n=self.phasesize
        pfn = self.pupfn.astype(self.fpDataType)
        indices=[]
        self.subflag = numpy.zeros((self.nsubx,self.nsubx),numpy.int8)
        if self.subflag.itemsize==8:
            print("WARNING:**centroid**:untested with 8 byte longs...(wfs)")
        # This could (and would be nice to) be replaced by
        # util.tel.pupil.getSubapFlag, but the "indeces" should be taken care
        # of (a bit of work), so we leave like this for now:
        for i in xrange(self.nsubx):        
            for j in xrange(self.nsubx):
                # Flag vignetted subaps Changed to >= by agb 28th Jun 2013 (to
                # match util.tel).
                if(self.subarea[i,j]>=(self.wfs_minarea*n*n)):
                    self.subflag[i,j]=1
                    indices.append((i*self.nsubx+j)*2)
                    indices.append((i*self.nsubx+j)*2+1)
        indices = numpy.array(indices,dtype=numpy.int32) 
        nsubaps = self.subflag.sum()
        return( indices, nsubaps )

    def updatePsf(self,psf,updateSig=None):
        """updateSig:  if None, nothing done.  If 1, will compute it from the summed PSF.  If an array or other value will update to this.
        """
        self.psf=psf
        self.centcmod.spotpsf=psf
        self.centcmod.update(util.centcmod.SPOTPSF,psf)
        if updateSig==1:
            sig=psf.sum(3).sum(2).astype(numpy.float32).ravel()
            self.centcmod.update(util.centcmod.SIG,sig)
        elif updateSig!=None:
            self.centcmod.update(util.centcmod.SIG,updateSig)

    def easy(self,nthreads=2,calsource=1):
        """Prepare for single use..., eg from a python commandline.
        Assumes that oversamplefactor=None, binfactor=None and that phasesize etc specified.
        """
        self.initMem(0)
        self.finishInit()
        self.initialiseCmod(nthreads,calsource)
        self.takeReference({'cal_source':1})
        self.outputData[:]=0
        #Then, put your data into self.reorderedPhs... 
        #Now, can use self.runCalc({'cal_source':0/1})

    def reformatImg(self,indata=None,out=None):
        if indata is None:
            indata=self.cmodbimg
        if out is None:
            out=numpy.zeros((indata.shape[0]*indata.shape[2],indata.shape[1]*indata.shape[3]),numpy.float32)
        nsubx=indata.shape[0]
        nimg=indata.shape[2]
        for i in xrange(nsubx):
            for j in xrange(nsubx):
                out[i*nimg:(i+1)*nimg,j*nimg:(j+1)*nimg]=indata[i,j]
        return out

    def reformatPhs(self,indata,out=None):
        if out is None:
            out=self.reorderedPhs
        nsubx=out.shape[0]
        n=out.shape[-1]
        sh=out.shape
        out.shape=nsubx,nsubx,n,n
        for i in range(nsubx):
            for j in range(nsubx):
                out[i,j]=indata[i*n:i*n+n,j*n:j*n+n]
        out.shape=sh
        return out
            

    def initMem(self,shareReorderedPhs=0,subimgMem=None,bimgMem=None,pupsubMem=None,reorderedPhsMem=None,outputDataMem=None):
        """initialise memory banks - useful if resource sharing is used in the simulation.
        Not needed if not using simulation framework.
        if useFPGA is set, tells us that we're using the FPGA... (only used
        if allocating the memories here...)
        if useCell is set, tells us that we're using the cell...
        if all resource sharing objects expect to do the wfs/cent calc every iteration, then they can share reorderedPhs.  Otherwise, they must each have their own version.
        """
        #print "centroid - initMem"
        nsubx=self.nsubx
        phasesize=self.phasesize
        fftsize=self.fftsize
        nIntegrations=self.nIntegrations
        self.fittedSubaps=None
        self.shareReorderedPhs=shareReorderedPhs
        phasesize_v=self.phasesize_v
        if shareReorderedPhs==0 or type(reorderedPhsMem)==type(None):
            if self.atmosPhaseType=="phaseonly":
                self.reorderedPhs=numpy.empty((nsubx,nsubx,nIntegrations,phasesize,phasesize_v),numpy.float32)
            else:
                self.reorderedPhs=numpy.empty((nsubx,nsubx,nIntegrations,phasesize,phasesize_v,2),numpy.float32)
            self.reorder(None,numpy.nan) # fill with nan
        else:
            if self.atmosPhaseType=="phaseonly":
                self.reorderedPhs=util.arrayFromArray.arrayFromArray(reorderedPhsMem,(nsubx,nsubx,nIntegrations,phasesize,phasesize_v),numpy.float32)
            else:
                self.reorderedPhs=util.arrayFromArray.arrayFromArray(reorderedPhsMem,(nsubx,nsubx,nIntegrations,phasesize,phasesize_v,2),numpy.float32)
        if type(outputDataMem)==type(None):
            if self.imageOnly==0:
                self.outputData=numpy.zeros((nsubx,nsubx,2),numpy.float32)       # Centroid arrays
            elif self.imageOnly==1:
                self.outputData=numpy.zeros((nsubx,nsubx,self.nimg,self.nimg),numpy.float32)
            else:
                self.outputData=numpy.zeros((nsubx*self.nimg,nsubx*self.nimg),numpy.float32)

        else:
            if self.imageOnly==0:
                self.outputData=util.arrayFromArray.arrayFromArray(outputDataMem,(nsubx,nsubx,2),numpy.float32)
            elif self.imageOnly==1:
                self.outputData=util.arrayFromArray.arrayFromArray(outputDataMem,(nsubx,nsubx,self.nimg,self.nimg),numpy.float32)
            else:
                self.outputData=util.arrayFromArray.arrayFromArray(outputDataMem,(nsubx*self.nimg,nsubx*self.nimg),numpy.float32)
        if self.imageOnly==0:
            self.centx=self.outputData[:,:,0]
            self.centy=self.outputData[:,:,1]
        else:
            self.centx=None
            self.centy=None
        #self.outputData.savespace(1)
        if type(subimgMem)==type(None):
            # SH sub-images (high LL):
            self.subimg=numpy.zeros((self.nsubx,self.nsubx,self.fftsize,self.fftsize),numpy.float64)
        else:
            self.subimg=util.arrayFromArray.arrayFromArray(subimgMem,(self.nsubx,self.nsubx,self.fftsize,self.fftsize),numpy.float64)
        if type(bimgMem)==type(None):
            self.bimg=numpy.zeros((self.nsubx,self.nsubx,self.nimg,self.nimg),numpy.float64)
        else:
            self.bimg=util.arrayFromArray.arrayFromArray(bimgMem,(self.nsubx,self.nsubx,self.nimg,self.nimg),numpy.float64)
        #self.bimg.savespace(1)
        if self.usecmod:
            self.cmodbimg=util.arrayFromArray.arrayFromArray(self.bimg,(self.nsubx,self.nsubx,self.nimg,self.nimg),numpy.float32)
        else:
            self.cmodbimg=None
        if type(pupsubMem)==type(None):
            self.pupsub=numpy.zeros((self.nsubx,self.nsubx,self.phasesize,self.phasesize),self.fpDataType)
        else:
            self.pupsub=util.arrayFromArray.arrayFromArray(pupsubMem,(self.nsubx,self.nsubx,self.phasesize,self.phasesize),self.fpDataType)

    def initialiseCmod(self,nthreads=8,calsource=0,seed=1):
        self.nthreads=nthreads
        if self.usecmod:
            print("INFORMATION:**centroid**:initialising cmod, nthreads = "+
                  "{0}".format(nthreads))
            sig=self.sig
            if type(self.sig)==numpy.ndarray:
                sig=self.sig.ravel()
            #temporary til I get it done properly...
            self.centcmod=util.centcmod.centcmod(nthreads,self.nsubx,self.ncen,self.fftsize,self.clipsize,
                                                 self.nimg,self.phasesize,self.readnoise,self.readbg,
                                                 self.addPoisson,self.noiseFloor,sig,self.skybrightness,
                                                 calsource,self.centroidPower,self.nIntegrations,seed,
                                                 self.reorderedPhs,self.pup,self.psf,self.outputData,
                                                 self.cmodbimg,self.wfs_minarea,self.opticalBinning,
                                                 self.centWeight,self.correlationCentroiding,
                                                 self.corrThresh,self.corrPattern,self.corrimg,
                                                 self.threshType,self.imageOnly,self.useBrightest,self.preBinningFactor,self.parabolicFit,self.gaussianFitVals,self.inputImage,self.subapLocation)
            #print "initialised cmod - done"
        else:
            self.centcmod=None





    def finishInit(self):
        """other initialisations to be carried out after initMem has been called.
        Not needed if not using simulation framework"""
        #print "centroid - finishInit"
        self.xtiltfn=((numpy.fromfunction(self.tilt,(self.phasesize,self.phasesize))-float(self.phasesize)/2.+0.5)/float(self.phasesize)).astype(self.fpDataType)# subap tilt fn
        self.ytiltfn=numpy.transpose(self.xtiltfn)
        #if self.fpDataType==numpy.float64:
        #    self.fftwPlan=cmod.mkimg.setup(self.subimg[0][0])                   # Setup imaging FFTs for subaps
        #else:
        #    self.fftwPlan=cmod.mkimgfloat.setup(self.subimg[0][0])
        self.tmpImg=numpy.zeros((self.fftsize,self.fftsize),self.fpDataType)
        n=self.phasesize
        pfn=self.pupfn.astype(self.fpDataType)
        for i in xrange(self.nsubx):        
            for j in xrange(self.nsubx):
                #print "%d %d %s %s %d"%(i,j,str(self.pupsub[i][j].shape),str(pfn.shape),n)
                self.pupsub[i][j]=pfn[i*n:(i+1)*n,j*n:(j+1)*n]    # Get pupil fn over subaps
        self.cenmask=None
        self.tilt_indx = (numpy.array(range(self.nimg),numpy.float64))-float(self.nimg/2)+0.5#Index fns for centroiding
        #print "centroid - finishInit done"

    # def closeCell(self):
    #     if self.canUseCell:
    #         self.cellObj.close()

    def runSlopeCalc(self,control):
        doref=1
        if self.usecmod:
            self.runCmodSlope(control["cal_source"])
            if self.linearSteps==None or self.psf!=None or self.correlationCentroiding!=None or self.calNCoeff!=0:
                doref=0#ref subtraction is done in c code...
        else:
            raise Exception("Only cmodule currently supported here")
        if self.linearSteps!=None:
            self.applyCalibration()
        if doref:
            if self.refCents is not None:
                self.outputData-=self.refCents
                
    def runCalc(self,control):
        doref=1
        if self.phaseMultiplier!=1:
            self.reorderedPhs*=self.phaseMultiplier
        # if control.get("useFPGA",0) and self.canUseFPGA:
        #     # use the FPGA - note that you might get a non-zero centroid value for parts of the array which are masked off simply because of the ccd readout noise.  The software version handles this incorrectly.
        #     self.setFPGARegs(control["cal_source"])#check whether registers are still valid for this object, and if not, change them so that they are.
        #     self.runFPGA()
        # elif control.get("useCell",0) and self.canUseCell:
        #     self.runCell(control["cal_source"])
        if control.get("useCmod",1):
            self.runCmod(control["cal_source"])
            # no calibration done, or done in c, so ref can be done by c:
            if self.linearSteps is None or self.psf is not None or self.correlationCentroiding!=None or self.calNCoeff!=0:
                doref=0#ref subtraction is done in c code...
        else:
            # use software version
            # t=time.time()
            # Create the images
            self.runPy(control["cal_source"])
        if self.linearSteps is not None:
            self.applyCalibration()
        if doref:
            if self.refCents is not None:
                self.outputData-=self.refCents

    # def runCell(self,calsource):
    #     """Tell the cell to perform computations."""
    #     if self.magicCentroiding:
    #         self.magicShackHartmann()
    #         return
    #     if self.canUseCell:
    #         self.cellObj.setCalSource(calsource)
    #         self.cellObj.startProcessing(block=self.waitCell)#if waitCell==0, will need to call self.cellObj.waitForCents() at some later time.

    def runPy(self,calsource):
        """run the python version"""
        if self.magicCentroiding:
            self.magicShackHartmann()
            return
        self.createSHImgs()
        self.tidyImage(calsource)
        self.calc_cents(calsource)

        
    def runCmodSlope(self,calsource):
        """run the c version"""
        if self.magicCentroiding:
            raise Exception("Cannot perform magic centroiding when input is an image")
        self.centcmod.runSlope(calsource)
        if self.imageOnly==0:
            pass
        else:
            raise Exception("no point getting here!  If you want the image only, don't use this module.")
    def runCmod(self,calsource):
        """run the c version"""
        if self.magicCentroiding:
            self.magicShackHartmann()
            return
        self.centcmod.run(calsource)
        if self.imageOnly==0:
            pass
        elif self.imageOnly==1:
            #copy image into outputdata
            self.outputData[:]=self.cmodbimg
        else:
            #copy image as image into outputdata
            for i in xrange(self.nsubx):
                for j in xrange(self.nsubx):
                    self.outputData[i*self.nimg:(i+1)*self.nimg,j*self.nimg:(j+1)*self.nimg]=self.cmodbimg[i,j]

    def closeCmod(self):
        self.centcmod.free()
        self.centcmod=None

    def updateIntegTime(self,steps):#this is to simulate rtc jitter.  Note, the exposure time/flux isn't changed...
        self.integtime=steps*self.tstep
        self.centcmod.update(util.centcmod.INTEGSTEPS,int(steps))
            

    def calcCovariance(self):
        if self.outSquare is not None:
            cov=self.outSquare/self.outN-(self.outSum/self.outN)**2
        else:
            cov=None
        return cov






        
    # def runFPGA(self):
    #     """Tell the FPGA where the data is..."""
    #     if self.magicCentroiding:
    #         self.magicShackHartmann()
    #         return
    #     fpid=self.fpid
    #     #now, we set the FPGA going (after copying data if necessary).
    #     t0=time.time()
    #     #print "runfpga"
    #     if self.doPartialFPGA:
    #         #array is too large to DMA all at once to FPGA, so do in parts.
    #         #calculate number of times a full array is needed...
    #         if self.atmosPhaseType=="phaseonly":
    #             reordered=util.arrayFromArray.arrayFromArray(self.reorderedPhs,(self.nsubx*nsubx,self.nIntegrations,self.phasesize,self.phasesize),numpy.float32)
    #         else:
    #             raise Exception("not phaseonly")
    #         output=util.arrayFromArray.arrayFromArray(self.outputData,(self.nsubx*self.nsubx,2),numpy.float32)
    #         fpga.writeAddr(fpid,self.fpgaInArr,1)#input address
    #         fpga.writeReg(fpid,self.fittedSubaps*self.nIntegrations*self.phasesize*self.phasesize*4/8,2)#size (quad words)
    #         fpga.writeAddr(fpid,self.fpgaOutArr,3)#output address
    #         fpga.writeReg(fpid,self.fittedSubaps,4)#size to write (in bytes).
    #         for i in range(self.partialFull):
    #             #copy memory into FPGA buffer
    #             self.fpgaInArr[:,]=reordered[i*self.fittedSubaps:(i+1)*self.fittedSubaps]
    #             fpga.writeReg(fpid,0x2,6)#reinitialise
    #             fpga.writeReg(fpid,1,6)#set it going.
    #             time.sleep(self.waitFPGATime/self.partialFull)#wait for it to complete (or almost)
    #             while fpga.readReg(fpid,5)!=7:#wait for reading to complete by checking register.
    #                 pass
    #             #copy centroids to the output...
    #             output[i*self.fittedSubaps:(i+1)*self.fittedSubaps]=self.fpgaOutArr
    #         if self.partialLeftOver>0:#copy the last bit...
    #             self.fpgaInArr[:self.partialLeftOver]=reordered[self.partialFull*self.fittedSubaps:self.partialFull*self.fittedSubaps+self.partialLeftOver]
    #             fpga.writeReg(fpid,0x2,6)#reinitialise
    #             fpga.writeReg(fpid,self.partialLeftOver*self.nIntegrations*self.phasesize*self.phasesize*4/8,2)#read siz
    #             fpga.writeReg(fpid,self.partialLeftOver,4)#size to write
    #             fpga.writeReg(fpid,1,6)#set it going
    #             time.sleep(self.waitLeftOver)
    #             while fpga.readReg(fpid,5)!=7:#wait til finished
    #                 pass
    #             #and copy centroids to the output array.
    #             output[self.partialFull*self.fittedSubaps:self.partialFull*self.fittedSubaps+self.partialLeftOver]=self.fpgaOutArr[:self.partialLeftOver]

    #             #now reset the registers for next time...
    #             fpga.writeReg(fpid,self.fittedSubaps*self.nIntegrations*self.phasesize*self.phasesize*4/8,2)#read siz
    #             fpga.writeReg(fpid,self.fittedSubaps,4)#size to write

                      
    #     else:
    #         #all subaps at once...
    #         if self.shareReorderedPhs:#this must be the only object using it...
    #             pass#already in the fpga array
    #         else:#copy to fpga array.
    #             self.fpgaInput[:,]=self.reorderedPhs
    #         fpga.writeReg(fpid,0x2,6)#reinitialise
    #         fpga.writeAddr(fpid,self.fpgaarr,1)#input address
    #         fpga.writeReg(fpid,self.nsubx*self.nsubx*self.nIntegrations*self.phasesize*self.phasesize*4/8,2)#size (quad words)
    #         fpga.writeAddr(fpid,self.outputData,3)#output address
    #         fpga.writeReg(fpid,self.nsubx*self.nsubx,4)#size to write (in bytes).
    #         #print "reading fpga reg %s"%hex(fpga.readReg(fpid,5))
    #         t0=time.time()
    #         fpga.writeReg(fpid,1,6)#set it going.
    #         if self.waitFPGA:
    #             if self.waitFPGATime>0:
    #                 time.sleep(self.waitFPGATime)#wait for it to complete (or almost).
    #             v=fpga.readReg(fpid,5)
    #             #print hex(v)
    #             while v!=7:#wait for reading to complete by checking register...
    #                 v=fpga.readReg(fpid,5)
    #                 #print hex(v)
    #                 pass
    #     if self.timing:
    #         t1=time.time()
    #         print "WFSCent time taken: %s"%str(t1-t0)
        #print "runfpgadone"
    def reorder(self,phs,pos):
        """Do a reodering of the phase buffer, so that it is in the form ready
        for the fpga.  Phases corresponding to subaps should be placed next to
        those for the same subap at a later time (greater pos).
        Also use with createSHImg() but not integrate().  If the FPGA has been
        initialised, this will place it in FPGA readable memory...
        
        To support a rolling shutter, calling with pos==-1 rolls the buffer
        backwards.
      
         -- time/pos ------------------------------>
           |-- j -->
            <-----> = r
                    <---- -> = r
                             <---- -> = r
         _          <---> = l         
         | |1111111-22222|22#33333-3344444#44
         ' |.111111-12222|22#23333-3334444#444
         i |..11111-11222|22#22333-3333444#4444
         , |...1111-11122|22#22233-3333344#44444
         | |....111-11112|22#22223-3333334#444444
         V |.....11-11111|22#22222-3333333#4444444
            <---> = l         

        The intepretation of the above is that the first frame lies between the
        '|' symbols, the second between the '-', and the third between the '#',
        The '.' symbol implies recorded data which is later discarded.
        The actual processing of the data is done in createSHimg; here only the
        appropriate storage of the data is considered.
        Thus for the first frame, all positions must be filled, for the
        subsequent (after calling with pos=-1), only those corresponding to the
        final row which is specified by 'l' are stored i.e. skip the first l.
        This action preserves the values recorded in the previous frame, and so
        most accurately represents a rolling shutter.
        At the end of the first frame (after calling with pos=-1), roll the array
        back by 'r'.
        To start a camera streaming, the reorderedPhs array should be set to NaN
        so any 'dirty' data is wiped: call with pos==numpy.nan.
        """
        if numpy.isnan(pos):
            # It is not thought that this clause will ever be true after
            # initialization (see above) since the WFS never stops receiving
            # data... 
            # Implemented for completeness.

            # wipe array and return
            self.reorderedPhs[:]=numpy.nan # fill with nan
            return
        if not self.atmosPhaseType in ("phaseonly","atmosphasetype"):
            raise NotImplementedError("self.atmosPhaseType")

        ## it is assumed that the two functions below are compiled into
        ## efficient bytecode, hence the switch only occurs once per
        ## call to reorder
        elif self.atmosPhaseType=="phaseonly":
            #If the phase isn't the same size as expected, interpolate it.  This works best when there is no dm pupil - and its best to check that the new pupil specified for this centroid object is the right size.  i.e. have a look at (in simCtrl):  
            #w=wfscentList[0].thisObjList[0].wfscentObj;data=w.phsInterp.copy()*w.pupfn
            #It might be necessary to slightly oversize the pupil for atmos module, so that interpolation is okay.
            if phs.shape!=(self.nsubx*self.phasesize,self.nsubx*self.phasesize):
                x=numpy.arange(phs.shape[1])/float(phs.shape[1]-1)
                if phs.shape[0]!=phs.shape[1]:
                    raise Exception("Expected square phase")
                b=scipy.interpolate.interp2d(x,x,phs,kind="cubic")
                n=self.nsubx*self.phasesize
                xnew=(numpy.arange(n)*phs.shape[1]/float(n)-(((n-1)*phs.shape[1])/float(n) - (phs.shape[1]-1))/2.)/float(phs.shape[1]-1)
                phs=b(xnew,xnew).astype(self.reorderedPhs.dtype)
                self.phsInterp=phs#just save in case someone wants to view it later.  Maybe this is a waste of memory...
            def _doassign(i,j,pos,n,phs,typecode):
                self.reorderedPhs[i,j,pos,:,:n]=phs[i*n:(i+1)*n,j*n:(j+1)*n]#.astype(typecode)
        elif self.atmosPhaseType=="phaseamp":
            #interpolating phase not yet implemented.
            def _doassign(i,j,pos,n,phs,typecode):
                self.reorderedPhs[i,j,pos,:,:n,0]=phs[0,i*n:(i+1)*n,j*n:(j+1)*n].astype(typecode)#phase
                self.reorderedPhs[i,j,pos,:,:n,1]=phs[1,i*n:(i+1)*n,j*n:(j+1)*n].astype(typecode)#amplitude
        #nsubx=    self.nsubx
        n=self.phasesize
        typecode=self.reorderedPhs.dtype
        if self.rowintegtime!=None:
            # support for rolling shutter model
            r=self.rowintegtime/self.tstep
            l=self.nIntegrations-r
            if int(pos)==0: # first frame
                # roll backwards, irrelevant for the first exposure since it all wraps around
                self.reorderedPhs[:,:,:,:,:n]=numpy.roll(
                     self.reorderedPhs[:,:,:,:,:n], -int(r), axis=2 )
##(DEBUGing)                print("DEBUG:rolling back by **{0:d}**".format(-int(r)))

            # If the array isn't nan (hi gramps!) then we know some of the
            # data is valid and for rolling shutter mode, don't overwrite the first
            # l position, so the i loop is j dependent.  If the array is nan (hi gran!)
            # then this is the first frame.
        for i in xrange(self.nsubx):
            for j in xrange(self.nsubx):
                if self.rowintegtime!=None and pos<l and j==0:
                    # only needs to be carried out for the the first j:-
                    # if rolling shutter and are at the start, either,
                    # (a) check i and if not used in the next frame, overwrite
                    #     the unused parts with nan or, more simply,
                    # (b) skip overwriting and hope for the best.
                    # Option (b) is harder to diagnose if there is a mistake in
                    # the code.
                    # To enable option (b), comment out the if statement.
                    # To enable option (a), keep the if statement.
                    # Both require the escape-from-the-loop clause.
                    # <<< EOL                                     # option (a) 
                    if pos<int(i*(self.nsubx-1)**-1.0*l+0.5):     # option (a) 
                        self.reorderedPhs[i,:,pos,:,:n]=numpy.nan # option (a) 
##(DEBUGing)                        print("DEBUG:setting {0[0]:d},{0[2]:d} to nan".format((i,j,pos)))
                    continue                         # option (a) & option (b)
                _doassign(i,j,pos,n,phs,typecode) # more efficient than switching everytime

    def makeImage(self,phs,img,pup):
        tmpphs=numpy.zeros(img.shape,numpy.complex64)
        tmpphs[:phs.shape[0],:phs.shape[1]]=(pup*(numpy.cos(phs)+1j*numpy.sin(phs))).astype(numpy.complex64)
        tmp=numpy.fft.fft2(tmpphs)
        img[:,]=(tmp.real*tmp.real+tmp.imag*tmp.imag).astype(numpy.float32)

    def createSHImgs(self):
        """Do the FFTs etc and add integrations to create the powerspectra (high light level images).
        All this will eventually (we hope) be done in the FPGAs"""
        tmp=0.5*float(self.phasesize)/float(self.fftsize)*2.*numpy.pi
        self.subimg*=0.0                                                  # Zero the CCD
        if self.rowintegtime!=None:
            r=self.rowintegtime/self.tstep
            l=self.nIntegrations-r
##(DEBUGing)            print("DEBUG:createSHImgs:",r,l)
        #nsubx=self.nsubx
        for i in xrange(self.nsubx):
           for j in xrange(self.nsubx):
              if self.subflag[i][j]!=1: continue
              for k in xrange(self.nIntegrations):
                 if ( self.rowintegtime!=None and
                       ( k<int(i*(self.nsubx-1)**-1.0*l+0.5) or
                         k>int(i*(self.nsubx-1)**-1.0*l+r-0.5) )):
                   # algorithm is::
                   #    if before the start : i<j/(nsubx-1)*l
                   # or if after the end : i>j/(nsubx-1)*l+r-1
                   # then continue
                   continue
##(DEBUGing)                 elif self.rowintegtime!=None:
##(DEBUGing)                   print("DEBUG:**centroid**:using {0:d}:{1:d}".format(i,k))
                 if self.atmosPhaseType=="phaseonly":
                     phssub=(self.reorderedPhs[i,j,k,:,:self.phasesize]-tmp*self.xtiltfn-tmp*self.ytiltfn).astype(self.fpDataType)
                 elif self.atmosPhaseType=="phaseamp":
                     phssub=(self.reorderedPhs[i,j,k,:,:,0]-tmp*self.xtiltfn-tmp*self.ytiltfn).astype(self.fpDataType)
                 #now do the FFT: plan, phsin, imgout, pypupil
                 if self.fpDataType==numpy.float64:
                     if phssub.dtype!=self.fpDataType or self.tmpImg.dtype!=self.fpDataType or self.pupsub.dtype!=self.fpDataType:
                         print("ERROR:**centroid**: typecode error")
                         raise Exception("Error with typecodes in wfs.py mkimg")
                     if self.atmosPhaseType=="phaseonly":
                         #cmod.mkimg.mkimg(self.fftwPlan,phssub,self.tmpImg,self.pupsub[i][j])
                         self.makeImage(phssub,self.tmpImg,self.pupsub[i,j])
                     elif self.atmosPhaseType=="phaseamp":
                         #cmod.mkimg.mkimg(self.fftwPlan,phssub,self.tmpImg,(self.pupsub[i,j]*self.reorderedPhs[i,j,k,:,:,1]).astype(self.fpDataType))
                         self.makeImage(pupsub,self.tmpImg,(self.pupsub[i,j]*self.reorderedPhs[i,j,k,:,:,1]).astype(self.fpDataType))
                     elif self.atmosPhaseType=="realimag":
                         raise Exception("realimag")
                 else:
                     if phssub.dtype!=self.fpDataType or self.tmpImg.dtype!=self.fpDataType or self.pupsub.dtype!=self.fpDataType:
                         print("ERROR:**centroid**: typecode error"
                                +str((phssub.dtype,self.tmpImg.dtype,
                                      self.pupsub.dtype)) )
                         raise Exception("Error with typecodes in "+
                                "wfs.py mkimg")
                     if self.atmosPhaseType=="phaseonly":
                         #cmod.mkimgfloat.mkimg(self.fftwPlan,phssub,self.tmpImg,self.pupsub[i][j])
                         self.makeImage(phssub,self.tmpImg,self.pupsub[i,j])
                     elif self.atmosPhaseType=="phaseamp":
                         #cmod.mkimgfloat.mkimg(self.fftwPlan,phssub,self.tmpImg,(self.pupsub[i,j]*self.reorderedPhs[i,j,k,:,:,1]).astype(self.fpDataType))
                         self.makeImage(phssub,self.tmpImg,(self.pupsub[i,j]*self.reorderedPhs[i,j,k,:,:,1]).astype(self.fpDataType))
                     elif self.atmosPhaseType=="realimag":
                         raise Exception("realimag")
                 self.subimg[i][j]+=self.tmpImg                    # Long exposure image

    def tidyImage(self,calSource):
        """Flip image (to correct for FFT), then bin the image up if
        oversampled, then add read and shot noise."""
        
        #self.shimg*=0.                                                # Reset...=zeros((nsubx*nimg,nsubx*nimg),float)
        readnoise=  self.readnoise
        mean=self.readbg
##         m=0
##         mn=1000000
        #nsubx=self.nsubx
        for i in range(self.nsubx):                                        # Loop over subaps
            for j in range(self.nsubx):
                if(self.subflag[i][j]==1):
                    bimg=self.bimg[i][j]
                    img=util.flip.fliparray(self.subimg[i][j])                          # Get subap image, flip it
                    #agb - test convolution... is this the right place?
                    if type(self.psf)!=type(None):
                        if len(self.psf.shape)==4:
                            ca=self.psf[i,j]
                        else:
                            ca=self.psf
                        img[:,]=self.conv(img,ca)

                    cmod.binimg.binimg(img,bimg)                              # Bin it up
                    totsig = numpy.sum(numpy.sum(bimg))
                    nphs=float(self.subarea[i,j])/self.phasesize**2#fraction of active phase pixels
                    if(totsig>0.):
                        if type(self.sig)==type(0.0):
                            bimg*=self.sig*nphs/totsig  #rescale the image.
                            # Note, used to be an error here - should also scale by the number of pixels that receive photons.  Fixed...
                        else:
                            bimg*=self.sig[i,j]/totsig
#                        if self.atmosPhaseType!="phaseonly":
#                            print "Scaling of SH image? Is it needed when have phase an amplitude for atmosphere"
# Answer:- at present, yes, because it is assumed by (for example) the spatial filter module that
# intensity in unknown and so arbitrary.
# --NAB June/2013
                    #now add sky brightness scaled by the number of phase pixels that are in the aperture:
                    if not calSource:#self.control["cal_source"]:
                        bimg+=self.skybrightness*nphs
                        if self.opticalBinning:
                            s1=numpy.sum(bimg)/2#bin in 1 dimension and take half the light (beam splitter).
                            s2=numpy.sum(numpy.transpose(bimg))/2#bin in other dimension
                            bimg[0]=s1#and store back in bimg.
                            bimg[1]=s2
                            bimg[2:,]=0.#this isn't necessary but makes nicer image...
                            bimg=bimg[:2]
                        if totsig>0. or self.skybrightness*nphs>0.:
                            # Inject shot noise
                            #cmod.imgnoise.shot(bimg,bimg)
                            bimg[:]=numpy.random.poisson(bimg)

                        if readnoise>1e-12:
                           # Generate random read noise :
                           bimg+=(numpy.random.normal(mean,
                              readnoise,bimg.shape)+0.5).astype("i") # round to integer
                    #self.shimg[i*self.wfs_nimg:(i+1)*self.wfs_nimg,j*self.wfs_nimg:(j+1)*self.wfs_nimg]=bimg    # Tessalate up for WFS display

    def calc_cents(self,calSource):
        """Centroid calculation:
        Subtracts noise background
        Computes centroids
        No return value."""
        nfft=   self.fftsize
        nimg=self.nimg
        nsubx=  self.nsubx
        floor=  self.noiseFloor
        #read=  self.wfs_read
        indx=   self.tilt_indx
        #bimg=self.bimg
        self.outputData[:,]=0.                                      # Reset...
        #self.centx=zeros((nsubx,nsubx),float)
        #self.centy=zeros((nsubx,nsubx),float)
        #self.shimg*=0.#reset...=zeros((nsubx*nimg,nsubx*nimg),float)
        if self.cenmask is None:
            self.cenmask=numpy.zeros((self.nimg,self.nimg),numpy.float32)             # Define centroiding mask
            self.cenmask[self.nimg/2-self.ncen/2:self.nimg/2+self.ncen/2,self.nimg/2-self.ncen/2:self.nimg/2+self.ncen/2]=1.

        cenmask=self.cenmask
        if self.opticalBinning:
            cenmask=1
        for i in range(nsubx):                                  # Loop over subaps
            for j in range(nsubx):
                if(self.subflag[i][j]==1):
                    bimg=self.bimg[i,j]
                    if self.opticalBinning:
                        bimg=bimg[:2]
                    #threshold the SH images.
                    if not calSource:#self.control["cal_source"]:
                        cimg=numpy.where(bimg<self.noiseFloor,0,bimg-self.noiseFloor)*cenmask
                    else:
                        cimg=bimg*cenmask
                    if self.opticalBinning:#using a cylindrical lenslet array...
                        s1=numpy.sum(cimg[0])
                        if s1>0:
                            self.centx[i,j]=numpy.sum(cimg[0]*indx)/s1
                        else:
                            self.centx[i,j]=0.
                        s1=numpy.sum(cimg[1])
                        if s1>0:
                            self.centy[i,j]=numpy.sum(cimg[1]*indx)/s1
                        else:
                            self.centy[i,j]=0.
                    else:
                        totsig = numpy.sum(numpy.sum(cimg))
                        if(totsig==0.):
                            totsig=1.#division by zero...
                        # Centroid calculation
                        self.centx[i,j]=numpy.sum(numpy.sum(cimg,0)*indx)/totsig  
                        self.centy[i,j]=numpy.sum(numpy.sum(cimg,1)*indx)/totsig



    def tilt(self,x,y):
        return y

    def computeHLL(self,phase):
        """Compute high light level image from phase, with nsubx subapertures
        in x and y directions.
        oversample is the factor used for oversampling the FFT.
        convarr is an optional array image (2 or 4d) which gets convolved
        with the SHS spots - eg an airy disc or LGS spot elongations...
        If an airy disc, create it with xoff=yoff=0.5.
        """
        nsubx=self.nsubx
        pupfn=self.pupfn
        oversample=self.oversamplefactor
        self.wfsn=n=phase.shape[0]/nsubx
        nfft=n*oversample
        subimg=numpy.zeros((nsubx,nsubx,nfft,nfft),"d")
        #fftwPlan=cmod.mkimg.setup(subimg[0,0])
        pupsub=numpy.ones((nsubx,nsubx,n,n),"d")
        if type(pupfn)!=type(None):
            if pupfn.shape!=phase.shape:
                print("ERROR:**centroid**: pupil function shape not equal to "+
                      "phase shape.")
            for i in range(nsubx):
                for j in range(nsubx):
                    pupsub[i,j]=pupfn[i*n:(i+1)*n,j*n:(j+1)*n].astype("d")
        phase=numpy.array(phase)
        tmp=0.5*n/nfft*2*numpy.pi
        xtiltfn=((numpy.fromfunction(self.tilt,(n,n))-float(n)/2.+0.5)/float(n)).astype("d")# subap tilt fn

        tiltfn=tmp*(xtiltfn+numpy.transpose(xtiltfn))
        for i in range(nsubx):
            for j in range(nsubx):
                phs=phase[i*n:i*n+n,j*n:j*n+n].astype("d")
                phs-=tiltfn
                #cmod.mkimg.mkimg(fftwPlan,phs,subimg[i,j],pupsub[i,j])
                self.makeImage(phs,subimg[i,j],pupsub[i,j])
                subimg[i,j]=util.flip.fliparray(subimg[i,j])
                if type(self.psf)!=type(None):
                    if len(self.psf.shape)==4:
                        ca=self.psf[i,j]
                    else:
                        ca=self.psf
                    subimg[i,j]=self.conv(subimg[i,j],ca)
        self.subimg=subimg
        return subimg#long exp image.

    def conv(self,img1,img2):
        """Convolve images, eg subap image with a PSF
        e.g. LGS spot shape or airy disc.
        Note, if using an airy disc form img2, create it with xoff=yoff=0.5"""
        temp1=numpy.fft.rfft2(img1)
        temp2=numpy.fft.rfft2(util.flip.fliparray2(img2))
        convimg=numpy.fft.irfft2(temp1*temp2)
        return convimg

        
        

    def makeshimg(self,subimg):
        shape=subimg.shape
        self.tilenoiseless=numpy.zeros((shape[0]*shape[2],shape[1]*shape[3]),subimg.dtype)
        for i in range(shape[0]):
            for j in range(shape[1]):
                self.tilenoiseless[i*shape[2]:(i+1)*shape[2],j*shape[3]:(j+1)*shape[3]]=subimg[i,j]
        return self.tilenoiseless
    
    def calcCents(self,subimg,ninteg=1):
        binfactor=self.binfactor
        nsubx=subimg.shape[0]
        nfft=subimg.shape[2]
        nimg=nfft/binfactor
        self.nimg=nimg
        n=nfft/self.oversamplefactor
        nsubs=nsubx*nsubx
        bimg=numpy.zeros((nsubx,nsubx,nimg,nimg),"d")
        self.bimg=bimg
        cent=numpy.zeros((nsubs*2,),"d")
        self.centx=util.arrayFromArray.arrayFromArray(cent[:nsubs],(nsubx,nsubx),cent.dtype)
        self.centy=util.arrayFromArray.arrayFromArray(cent[nsubs:,],(nsubx,nsubx),cent.dtype)
        self.tile=numpy.zeros((nimg*nsubx,nimg*nsubx),subimg.dtype)
        self.photPerSubap=numpy.zeros((nsubx,nsubx),"d")
        indx = (numpy.array(range(nimg),numpy.float64))-float(nimg/2)+0.5
        for i in range(nsubx):
            for j in range(nsubx):
                cmod.binimg.binimg(subimg[i,j],bimg[i,j])
                totsig=numpy.sum(numpy.sum(bimg[i,j]))
                if type(self.subarea)==type(None):
                    nphs=1.
                else:
                    nphs=float(self.subarea[i,j])/(n*n)#fraction of active pxls.
                if totsig>0:
                    if type(self.sig)==type(0.0):
                        bimg[i,j]*=self.sig*nphs/totsig
                    else:
                        bimg[i,j]*=self.sig[i,j]/totsig
                bimg[i,j]+=self.skybrightness*nphs
                for k in range(ninteg):#perform several integrations...
                    tmpimg=bimg[i,j].copy()
                    if self.addPoisson:
                        #cmod.imgnoise.shot(tmpimg,tmpimg)
                        tmpimg[:]=numpy.random.poisson(tmpimg)
                    if self.readnoise>0 or self.readbg>0:
                        tmpimg+=numpy.random.normal(self.readbg,self.readnoise,tmpimg.shape)
                    tmpimg[:,]=numpy.where(tmpimg<self.noiseFloor,0,tmpimg-self.noiseFloor)
                bimg[i,j]=tmpimg
                self.tile[i*nimg:(i+1)*nimg,j*nimg:(j+1)*nimg]=bimg[i,j]
                totsig=numpy.sum(numpy.sum(bimg[i,j]))
                self.photPerSubap[i,j]=totsig
                if totsig==0:
                    totsig=1.
                if self.centroidPower==None:
                    self.centx[i,j]=numpy.sum(numpy.sum(bimg[i,j],0)*indx)/totsig
                    self.centy[i,j]=numpy.sum(numpy.sum(numpy.transpose(bimg[i,j]),0)*indx)/totsig
                else:
                    self.centx[i,j]=numpy.sum(numpy.sum(bimg[i,j]**self.centroidPower,0)*indx)/totsig
                    self.centy[i,j]=numpy.sum(numpy.sum(numpy.transpose(bimg[i,j]**self.centroidPower),0)*indx)/totsig

        self.cent=cent
        if self.warnOverflow!=None:
            if max(self.tile.flat)>self.warnOverflow:
                print("WARNING:**centroid**:Max value in CCD is "
                     +str(max(self.tile.flat)) )
        if self.printmax:
            print("INFORMATION:**centroid**:Max value in CCD is"
                  +str( max(self.tile.flat) ) )
            print("INFORMATION:**centroid**:Mean signal in CCD is "
                  +str( numpy.average(self.tile.flat) ) )
            
        return self.cent

    def run(self,phase,ninteg=1):
        hll=self.computeHLL(phase)
        simg=self.makeshimg(hll)
        c=self.calcCents(hll,ninteg)
        return self

    def calc(self,phase):
        return self.calcCents(self.computeHLL(phase))

    def getCentral(self,npxls=4,offset=0):
        """Return an image of SH spots, but only the central few spots are shown.  This can be useful if you have a system with a large number of pxls per subap, and a fairly flat wavelength, and wish to view eg in gist..."""
        nsubx=self.nsubx
        nimg=self.nimg
        s=nimg/2-npxls/2+offset
        e=s+npxls
        img=numpy.zeros((npxls*nsubx,npxls*nsubx),"d")
        for i in range(nsubx):
            for j in range(nsubx):
                img[i*npxls:(i+1)*npxls,j*npxls:(j+1)*npxls]=self.bimg[i,j,s:e,s:e]
        return img
    def computePxlToRad(self,n):
        c=centroid(1,oversamplefactor=self.oversamplefactor,binfactor=self.binfactor)
        phs=numpy.zeros((n,n),"d")
        phs[:,]=numpy.arange(n).astype("d")/(n-1)
        cc=c.calc(phs)
        self.convFactor=abs(1./cc[0])#multiply the centroids (in pixels) by this value to get the mean phase slopes (centroids) in radians.


    def computeNoiseCovariance(self,niters=10,wfsn=8,convertToRad=0):
        """puts flat phase in, and computes centroids for several iterations,
        and then computes covariance."""
        if type(self.pupfn)!=type(None):
            phase=numpy.zeros(self.pupfn.shape,numpy.float64)
        else:
            phase=numpy.zeros((self.nsubx*wfsn,self.nsubx*wfsn),numpy.float64)
        n=self.nsubx*self.nsubx*2
        c2=numpy.zeros((n,),numpy.float64)
        csum=numpy.zeros((n,),numpy.float64)
        for i in range(niters):
            self.run(phase)
            csum+=self.cent
            c2+=self.cent*self.cent
        mean=csum/n
        var=c2/n-mean*mean
        convFactor=1.
        if convertToRad:
            self.computePxlToRad(wfsn)
            convFactor=self.convFactor**2
            
        return var*convFactor
        
    def magicShackHartmann(self):
        """Taken from TB - just takes slope measurement."""
        nsubx=self.nsubx
        pupfn=self.pupfn
        n=self.pupfn.shape[0]/nsubx
        if self.magicSlopes is None:
            self.magicSlopes=self.magicSHSlopes()
        magicSlopes=self.magicSlopes

        #now need to reorder... first average the different integration times
        #Actually, maybe we should just use the latest, since we're magic... oh well.
        phs=(self.reorderedPhs.sum(2)/self.reorderedPhs.shape[2])[:,:,:,:self.phasesize]
        #phs.shape=nsubx,nsubx,phasesize,phasesize_v
        

        #tmp1=phs*magicSlopes#*R0_LAMBDA/WFS_LAMBDA
        #tmp2=phs*magicSlopes.transpose()#*R0_LAMBDA/WFS_LAMBDA
        cent=self.outputData#numpy.zeros((nsubx**2,2),numpy.float32)
        for i in range(nsubx):
            for j in range(nsubx):
                if self.subflag[i,j]:
                    cent[i,j,0]=(phs[i,j]*magicSlopes[i*n:(i+1)*n,j*n:(j+1)*n]).sum()
                    cent[i,j,1]=(phs[i,j]*magicSlopes.transpose()[i*n:(i+1)*n,j*n:(j+1)*n]).sum()
        return cent

    def magicSHSlopes(self):
        npup=self.pupfn.shape[0]
        slop=numpy.zeros((npup,npup),numpy.float32)
        slop[:]=numpy.arange(npup)+1.
        slop*=self.pupfn
        n=self.pupfn.shape[0]/self.nsubx
        #self.subflag=numpy.zeros((self.nsubx,self.nsubx),numpy.int32)
        for i in range(self.nsubx):
            for j in range(self.nsubx):
                #if self.pupfn[i*n:(i+1)*n,j*n:(j+1)*n].sum()>=self.wfs_minarea*n*n:
                #   self.subflag[i,j]=1
                if self.subflag[i,j]>0:
                    p=slop[i*n:(i+1)*n,j*n:(j+1)*n].sum()/float(self.pupfn[i*n:(i+1)*n,j*n:(j+1)*n].sum())
                    slop[i*n:(i+1)*n,j*n:(j+1)*n]-=p*self.pupfn[i*n:(i+1)*n,j*n:(j+1)*n]
                    s2=(slop[i*n:(i+1)*n,j*n:(j+1)*n]**2).sum()
                    slop[i*n:(i+1)*n,j*n:(j+1)*n]/=-numpy.sqrt(s2)
                else:
                    slop[i*n:(i+1)*n,j*n:(j+1)*n]*=0.
        return slop

#    def calibrateSHSUnique(self,control={"cal_source":1,"useFPGA":0,"useCell":0,"useCmod":1}):
    def calibrateSHSUnique(self,control={"cal_source":1,"useCmod":1}):
        if self.linearSteps==None:
            return
        #Can we cache the information on disk?  reliably?  Depends on pupil mask, nsubx, minarea, many many things... but might be worth considering - would save a lot of time!
        print("INFORMATION:**centroid**:Calibrating centroids (all subaps "+
               "treated differently)")
        steps=self.linearSteps
        self.linearSteps=None
        #create a (fairly large) array to store the data.
        self.calibrateData=numpy.zeros((2,self.nsubx,self.nsubx,steps),numpy.float32)
        #compute the phase slopes to use...
        stepList=(numpy.arange(steps)-steps/2.+0.5)/(steps/2.-0.5)*numpy.pi*self.stepRangeFrac

        self.calibrateSteps=stepList.astype(numpy.float32)
        c=control["cal_source"]
        #control["cal_source"]=1
        control["cal_source"]=0
        if self.centcmod!=None:
            self.centcmod.update(util.centcmod.ADDPOISSON,0)
            self.centcmod.update(util.centcmod.READNOISE,0)
        else:
            raise Exception("Not yet sorted for non-cmod type things")
        for i in range(steps):
            #put a slope into it
            tilt=-numpy.arange(self.phasesize)*stepList[i]
            self.reorderedPhs[:,:,:]=tilt
            #compute centroids (x)
            self.runCalc(control)
            #Now take the x centroids and store...
            self.calibrateData[0,:,:,i]=self.centx

            #And now repeat for the y centroids
            self.reorderedPhs[:,:,:]=tilt[None].transpose()
            self.runCalc(control)
            self.calibrateData[1,:,:,i]=self.centy
        if self.centcmod!=None:#restore the original values.
            self.centcmod.update(util.centcmod.ADDPOISSON,self.centcmod.addPoisson)
            self.centcmod.update(util.centcmod.READNOISE,self.centcmod.readnoise)
        control["cal_source"]=c
        self.linearSteps=steps
        #self.calibrateDataOrig=self.calibrateData.copy()
        #Now compute the bounds for which this is single valued (since, when cent gets too close to edge, it starts wrapping round).
        self.calibrateBounds=numpy.zeros((2,self.nsubx,self.nsubx,2),numpy.int32)
        for i in range(self.nsubx):
            for j in range(self.nsubx):
                #x
                self.calibrateBounds[0,i,j,0]=numpy.argmin(self.calibrateData[0,i,j])
                self.calibrateBounds[0,i,j,1]=numpy.argmax(self.calibrateData[0,i,j])
                #and y
                self.calibrateBounds[1,i,j,0]=numpy.argmin(self.calibrateData[1,i,j])
                self.calibrateBounds[1,i,j,1]=numpy.argmax(self.calibrateData[1,i,j])
        #Also need to check that the calibrateData[:,:,:,i] is increasing always - otherwise the interpolation won't work.  What should we do if its not increasing???
        linearPointsForced=0
        maxShift=0
        if self.calNCoeff==0:
            for i in range(self.nsubx):
                for j in range(self.nsubx):
                    for k in range(self.calibrateBounds[0,i,j,0],self.calibrateBounds[0,i,j,1]):
                        if self.calibrateData[0,i,j,k]>self.calibrateData[0,i,j,k+1]:
                            val=(self.calibrateData[0,i,j,k-1]+self.calibrateData[0,i,j,k+1])/2.
                            if self.printLinearisationForcing:
                                print(("INFORMATION:**centroid**: Forcing SHS "+
                                    "calibration for point ({0:d},{1:d}) step "+
                                    "{2:d} from {3:g} to {4:g}").format(
                                       i,j,k,self.calibrateData[0,i,j,k],val))
##(old)                                print("INFORMATION:**centroid**: Forcing SHS calibration for point (%d,%d) step %d from %g to %g"%(i,j,k,self.calibrateData[0,i,j,k],val))
                            #and save for a summary at the end.
                            linearPointsForced+=1
                            shift=abs(self.calibrateData[0,i,j,k]-val)
                            if shift>maxShift:
                                maxShift=shift
                            self.calibrateData[0,i,j,k]=val
                    for k in range(self.calibrateBounds[1,i,j,0],self.calibrateBounds[1,i,j,1]):
                        if self.calibrateData[1,i,j,k]>self.calibrateData[1,i,j,k+1]:
                            val=(self.calibrateData[1,i,j,k-1]+self.calibrateData[1,i,j,k+1])/2.
                            if self.printLinearisationForcing:
                                print(("INFORMATION:**centroid**: Forcing SHS "+
                                    "calibration for point ({0:d},{1:d}) step "+
                                    "{2:d} from {3:g} to {4:g}").format(
                                       i,j,k,self.calibrateData[1,i,j,k],val))
##(old)                                print("INFORMATION:**centroid**: Forcing SHS calibration for point (%d,%d) step %d from %g to %g"%(i,j,k,self.calibrateData[1,i,j,k],val)
                            #and save for a summary at the end.
                            linearPointsForced+=1
                            shift=abs(self.calibrateData[0,i,j,k]-val)
                            if shift>maxShift:
                                maxShift=shift
                            self.calibrateData[1,i,j,k]=val
        print(("INFORMATION:**centroid**:Finished calibrating centroids: Forced "+
              "{0:d} max shift {1:g})").format(linearPointsForced,maxShift))
##(old)        print("INFORMATION:**centroid**:Finished calibrating centroids: Forced %d, max shift %g"%(linearPointsForced,maxShift))

    def applyCalibrationUnique(self,data=None):
        """Uses the calibration, to replace data with a calibrated version of data.
        Data.shape should be nsubx,nsubx,2
        Typically it will be self.outputData
        """
        if data is None:
            data=self.outputData
        if self.calNCoeff==0:
            for i in range(self.nsubx):
                for j in range(self.nsubx):
                    if self.subflag[i,j]:
                        cx,cy=data[i,j]#the x,y centroids.
                        if cx>self.calibrateData[0,i,j,self.calibrateBounds[0,i,j,1]] or cx<self.calibrateData[0,i,j,self.calibrateBounds[0,i,j,0]]:
                            print(("WARNING:**centroid**: x centroid at %d,%d "+
                                 "with value %g is outside the calibrated "+
                                 "bounds").format(i,j,cx))
##(old)                            print("WARNING:**centroid**: x centroid at %d,%d with value %g is outside the calibrated bounds"%(i,j,cx))
                        if cy>self.calibrateData[1,i,j,self.calibrateBounds[1,i,j,1]] or cy<self.calibrateData[1,i,j,self.calibrateBounds[1,i,j,0]]:
                            print(("WARNING:**centroid**: y centroid at %d,%d "+
                                  "with value %g is outside the calibrated "+
                                  "bounds").format(i,j,cy))
##(old)                            print("WARNING:**centroid**: y centroid at %d,%d with value %g is outside the calibrated bounds"%(i,j,cy))
                        data[i,j,0]=numpy.interp([cx],self.calibrateData[0,i,j,self.calibrateBounds[0,i,j,0]:self.calibrateBounds[0,i,j,1]+1],self.calibrateSteps[self.calibrateBounds[0,i,j,0]:self.calibrateBounds[0,i,j,1]+1])[0]
                        #print "applyCalibration error %d %d 0 %g %d %d"%(i,j,cx,self.calibrateBounds[0,i,j,0],self.calibrateBounds[0,i,j,1]+1)
                        data[i,j,1]=numpy.interp([cy],self.calibrateData[1,i,j,self.calibrateBounds[1,i,j,0]:self.calibrateBounds[1,i,j,1]+1],self.calibrateSteps[self.calibrateBounds[1,i,j,0]:self.calibrateBounds[1,i,j,1]+1])[0]
                        #print "applyCalibration error %d %d 1 %g %d %d"%(i,j,cy,self.calibrateBounds[1,i,j,0],self.calibrateBounds[1,i,j,1]+1)
        else:#calibration using interpolation
            klist=range(self.calNCoeff)
            for i in range(self.nsubx):
                for j in range(self.nsubx):
                    if self.subflag[i,j]:
                        resx=0.
                        resy=0.
                        xc=1.
                        yc=1.
                        cx,cy=data[i,j]
                        for k in klist:
                            resx+=xc*self.calCoeff[i,j,0,k]
                            xc*=cx
                            resy+=yc*self.calCoeff[i,j,1,k]
                            yc*=cy
                        data[i,j]=resx,resy
#    def calibrateSHSIdentical(self,control={"cal_source":1,"useFPGA":0,"useCell":0,"useCmod":1}):
    def calibrateSHSIdentical(self,control={"cal_source":1,"useCmod":1}):
        if self.linearSteps==None:
            return
        print("INFORMATION:**centroid**:Calibrating centroids (identical subap "+
               "pupil functions treated same)")
        steps=self.linearSteps
        self.linearSteps=None
        #create a (fairly large) array to store the data.
        self.calibrateData=numpy.zeros((2,self.nsubx,self.nsubx,steps),numpy.float32)
        self.calMaskType=numpy.zeros((self.nsubx,self.nsubx),numpy.int32)
        self.calDataDict={}
        typ=1
        d={0:[]}
        for i in range(self.nsubx):
            for j in range(self.nsubx):
                if self.subflag[i,j]:
                    keys=d.keys()
                    typ=None
                    for key in keys:
                        if numpy.alltrue(d[key]==self.pupfn[i*self.phasesize:(i+1)*self.phasesize,j*self.phasesize:(j+1)*self.phasesize]):
                            typ=key
                            break
                    if typ==None:#new type needed
                        typ=max(keys)+1
                        d[typ]=self.pupfn[i*self.phasesize:(i+1)*self.phasesize,j*self.phasesize:(j+1)*self.phasesize]
                    self.calMaskType[i,j]=typ


        #compute the phase slopes to use...
        stepList=(numpy.arange(steps)-steps/2.+0.5)/(steps/2.-0.5)*numpy.pi*self.stepRangeFrac
        self.calibrateSteps=stepList.astype(numpy.float32)
        c=control["cal_source"]
        #control["cal_source"]=1
        control["cal_source"]=0
        if self.centcmod!=None:
            self.centcmod.update(util.centcmod.ADDPOISSON,0)
            self.centcmod.update(util.centcmod.READNOISE,0)
        else:
            raise Exception("Not yet sorted for non-cmod type things")
        #TODO: the best way of doing this is to use cal_source==0, and set addPoisson=0, readnoise=0, and that way the backgrounds are correct.
        for i in range(steps):
            #put a slope into it
            tilt=-numpy.arange(self.phasesize)*stepList[i]
            self.reorderedPhs[:,:,:]=tilt
            #compute centroids (x)
            self.runCalc(control)
            #Now take the x centroids and store...
            self.calibrateData[0,:,:,i]=self.centx

            #And now repeat for the y centroids
            self.reorderedPhs[:,:,:]=tilt[None].transpose()
            self.runCalc(control)
            self.calibrateData[1,:,:,i]=self.centy
        if self.centcmod!=None:#restore the original values.
            self.centcmod.update(util.centcmod.ADDPOISSON,self.centcmod.addPoisson)
            self.centcmod.update(util.centcmod.READNOISE,self.centcmod.readnoise)
        control["cal_source"]=c
        self.linearSteps=steps
        #self.calibrateDataOrig=self.calibrateData.copy()
        #Now compute the bounds for which this is single valued (since, when cent gets too close to edge, it starts wrapping round).
        self.calibrateBounds=numpy.zeros((2,self.nsubx,self.nsubx,2),numpy.int32)
        linearPointsForced=0
        maxShift=0.
        for i in range(self.nsubx):
            for j in range(self.nsubx):
                if self.subflag[i,j]:
                    if not self.calDataDict.has_key(self.calMaskType[i,j]):
                        # Create a new store for this type of subap
                        xf=numpy.argmin(self.calibrateData[0,i,j])
                        xt=numpy.argmax(self.calibrateData[0,i,j])+1
                        yf=numpy.argmin(self.calibrateData[1,i,j])
                        yt=numpy.argmax(self.calibrateData[1,i,j])+1
                        xc=self.calibrateData[0,i,j,xf:xt].copy()
                        yc=self.calibrateData[1,i,j,yf:yt].copy()
                        xr=self.calibrateSteps[xf:xt]
                        yr=self.calibrateSteps[yf:yt]
                        self.calDataDict[self.calMaskType[i,j]]=CalData(xc,xr,yc,yr)
                        cd=self.calDataDict[self.calMaskType[i,j]]
                        #mod=0
                        for k in range(cd.xc.shape[0]-1):
                            if cd.xc[k]>=cd.xc[k+1]:
                                #mod=1
                                #print cd.xc
                                #import util.FITS
                                #util.FITS.Write(cd.xc,"tmp.fits")
                                if k==0:
                                    val=cd.xc[k+1]-(cd.xc[k+2]-cd.xc[k+1])
                                else:
                                    val=(cd.xc[k-1]+cd.xc[k+1])/2.
#                                 if val==cd.xc[k+1]:
#                                     if val>0:
#                                         val*=0.99999
#                                     else:
#                                         val*=1.00001
                                #print "Forcing SHS x calibration for point (%d,%d) step %g from %g to %g"%(i,j,cd.xr[k],cd.xc[k],val)
                                linearPointsForced+=1
                                if abs(val-cd.xc[k])>maxShift:
                                    maxShift=abs(val-cd.xc[k])
                                cd.xc[k]=val
                        notsame=numpy.nonzero(cd.xc[1:]!=cd.xc[:-1])[0]
                        cd.xc=cd.xc[notsame]
                        cd.xr=cd.xr[notsame]
                        for k in range(cd.yc.shape[0]-1):
                            if cd.yc[k]>=cd.yc[k+1]:
                                if k==0:
                                    val=cd.yc[k+1]-(cd.yc[k+2]-cd.yc[k+1])
                                else:
                                    val=(cd.yc[k-1]+cd.yc[k+1])/2.
#                                 if val==cd.yc[k+1]:
#                                     if val>0:
#                                         val*=0.99999
#                                     else:
#                                         val*=1.00001
                                #print "Forcing SHS y calibration for point (%d,%d) step %g from %g to %g"%(i,j,cd.yr[k],cd.yc[k],val)
                                linearPointsForced+=1
                                if abs(val-cd.yc[k])>maxShift:
                                    maxShift=abs(val-cd.yc[k])
                                cd.yc[k]=val
                        notsame=numpy.nonzero(cd.yc[1:]!=cd.yc[:-1])[0]
                        cd.yc=cd.yc[notsame]
                        cd.yr=cd.yr[notsame]
                        #if mod:
                        #    util.FITS.Write(cd.xc,"tmp.fits")
                    # and store this subap index.
                    cd=self.calDataDict[self.calMaskType[i,j]]
                    cd.indx.append(i*self.nsubx+j)
        for k in self.calDataDict.keys():
            cd=self.calDataDict[k]
            cd.xindx=numpy.array(cd.indx).astype(numpy.int32)*2
            cd.yindx=cd.xindx+1
        #print(("INFORMATION:**centroid**:Finished calibrating centroids, shifted {0:d}, maxShift {1:g}").format(linearPointsForced,maxShift))
        print("INFORMATION:**centroid**:Finished calibrating centroids, shifted %d, maxShift %g"%(linearPointsForced,maxShift))

    def applyCalibrationIdentical(self,data=None):
        """Uses the calibration, to replace data with a calibrated version of data.
        Data.shape should be nsubx,nsubx,2
        Typically it will be self.outputData
        """
        if data is None:
            data=self.outputData
        if numpy.any(numpy.isnan(data)):
            print("WARNING:**centroid**: nan prior to applyCalibrationIdentical")
        rdata=data.ravel()
        warnx=0
        warny=0
        for k in self.calDataDict.keys():
            cd=self.calDataDict[k]
            x=numpy.take(rdata,cd.xindx)
            y=numpy.take(rdata,cd.yindx)
            #print "x,y",x,y
            if cd.xc.size==0 or numpy.any(x>cd.xc[-1]) or numpy.any(x<cd.xc[0]):
                if warnx<1:
                    warnx=1
                #opstr=()
                if cd.xc.size==0:
                    warnx=2
                    #opstr+=", because there aren't any"
                #print(opstr)
            if cd.yc.size==0 or numpy.any(y>cd.yc[-1]) or numpy.any(y<cd.yc[0]):
                if warny<1:
                    warny=1
                #opstr=("WARNING:**centroid**: y centroid is outside calibrated "+                     "bounds")
                if cd.yc.size==0:
                    warny=2
                    #opstr+=", because there aren't any"
                #print(opstr)
            #now put the calibrated values back (using numpy fancy indexing)
            if cd.xc.size!=0:
                rdata[cd.xindx]=numpy.interp(x,cd.xc,cd.xr).astype(numpy.float32)
            if cd.yc.size!=0:
                rdata[cd.yindx]=numpy.interp(y,cd.yc,cd.yr).astype(numpy.float32)
            indx=numpy.nonzero(numpy.isnan(rdata[cd.xindx]))[0]
            if indx.size>0:
                print("INFORMATION:**centroid**:applyCalibrationIdentical, indx"+
                     str((indx,numpy.take(rdata[cd.xindx],indx),
                          numpy.take(x,indx))) )
                print("INFORMATION:**centroid**:applyCalibrationIdentical "+
                     str((cd.xc,cd.xr)) )
            #print "rdata",rdata[cd.xindx],rdata[cd.yindx]
        if warnx==1:
            print("WARNING:**centroid**: x centroid is outside calibrated bounds")
        elif warnx==2:
            print("WARNING:**centroid**: x centroid is outside calibrated bounds because there aren't any")
        if warny==1:
            print("WARNING:**centroid**: y centroid is outside calibrated bounds")
        elif warny==2:
            print("WARNING:**centroid**: y centroid is outside calibrated bounds because there aren't any")
        
        if not data.flags.c_contiguous:
            #need to copy the data back in.
            print("WARNING:**centroid**: flattening non-contiguous centroid data")
            rdata.shape=data.shape
            data[:]=rdata
        if numpy.any(numpy.isnan(data)):
            print("WARNING:**centroid**: nan after applyCalibrationIdentical")

    def makeCalibrationCoeffs(self):
        self.calCoeff=numpy.zeros((self.nsubx,self.nsubx,2,self.calNCoeff),numpy.float32)
        print("INFORMATION:**centroid**: todo makeCalibrationCoeffs - check "+
              "whether is giving best performance (calibrateSHSUnique does "+
              "some adjustment to the data, so it may not) - should be use "+
              "the bounds, or use the whole think unadjusted...?")
        for i in range(self.nsubx):
            for j in range(self.nsubx):
                if self.subflag[i,j]:
                    f,t=self.calibrateBounds[0,i,j]
                    self.calCoeff[i,j,0]=numpy.polyfit(self.calibrateData[0,i,j,f:t],self.calibrateSteps[f:t],self.calNCoeff-1)[::-1]
                    self.calCoeff[i,j,1]=numpy.polyfit(self.calibrateData[1,i,j,f:t],self.calibrateSteps[f:t],self.calNCoeff-1)[::-1]


#    def calibrateSHS(self,control={"cal_source":1,"useFPGA":0,"useCell":0,"useCmod":1}):
    def calibrateSHS(self,control={"cal_source":1,"useCmod":1}):
        if self.linearSteps==None:
            return
        if self.psf is None and self.correlationCentroiding==0 and self.calNCoeff==0:
            self.calibrateSHSIdentical(control)
        else:
            self.calibrateSHSUnique(control)
            if self.calNCoeff!=0:
                self.makeCalibrationCoeffs()
                if self.centcmod!=None:
                    self.centcmod.update(util.centcmod.CALCOEFF,self.calCoeff)
            else:
                if self.centcmod!=None:
                    self.centcmod.update(util.centcmod.CALDATA,(self.calibrateData,self.calibrateBounds,self.calibrateSteps))

    def applyCalibration(self,data=None):
        if self.psf is None and self.correlationCentroiding==0 and self.calNCoeff==0:
            self.applyCalibrationIdentical(data)
        else:
            if self.centcmod==None:#otherwise its been done in the c module.
                self.applyCalibrationUnique(data)


    def takeReference(self,control,cameraInput=None):
        """Measure noiseless centroid offsets for flat input.  These are then subsequently used as reference centroids.
        """
        # compute centroids (x)
        c=control["cal_source"]
        control["cal_source"]=1
        #steps=self.linearSteps
        #self.linearSteps=None
        if self.centcmod!=None:
            if self.linearSteps==None or self.psf is not None or self.correlationCentroiding!=None or self.calNCoeff!=0:#no calibration done, or done in c, so ref can be done by c.
                self.centcmod.update(util.centcmod.REFCENTS,None)


        if cameraInput is not None or self.inputImage is not None:
            if cameraInput is not None:
                self.inputImage[:]=cameraInput
            else:
                pass#use whatever is in the inputImage array as reference.
            print "Taking reference slopes from current camera input"
            self.runSlopeCalc(control)
        else:
            self.reorderedPhs[:]=0
            self.runCalc(control)
        control["cal_source"]=c
        #self.linearSteps=steps
        # Now take the x centroids and store...
        self.refCents=self.outputData.copy()
        #Now, we need reference to be taken after calibration has been done.
        #So, we should only pass refs to cmod if cmod is also doing calibration (or if no calibration is being done).
        if self.centcmod!=None:
            if self.linearSteps==None or self.psf is not None or self.correlationCentroiding!=None or self.calNCoeff!=0:#no calibration done, or done in c, so ref can be done by c.
                self.centcmod.update(util.centcmod.REFCENTS,self.refCents)
        return self.refCents

    def setRefSlopes(self,refSlopes):
        """Sets ref slopes to something provided"""
        self.refCents=refSlopes.copy().astype(numpy.float32)
        if self.centcmod!=None:
            if self.linearSteps==None or self.psf is not None or self.correlationCentroiding!=None or self.calNCoeff!=0:#no calibration done, or done in c, so ref can be done by c.
                self.centcmod.update(util.centcmod.REFCENTS,self.refCents)

    
    def takeCorrImage(self,control,cameraInput=None):
        """If correlationCentroiding==1, but corrPattern==None, use a default SH spot pattern as the reference.
        """
        data=None
        if self.correlationCentroiding:
            if self.corrPattern is None:
                c=control["cal_source"]
                control["cal_source"]=1
                steps=self.linearSteps
                self.linearSteps=None
                if self.centcmod!=None:
                    self.centcmod.update(util.centcmod.CORRELATIONCENTROIDING,0)
                else:
                    raise Exception("Not yet sorted for non-cmod type things")
                if cameraInput is not None or self.inputImage is not None:
                    if cameraInput is not None:
                        self.inputImage[:]=cameraInput
                    else:
                        pass#use whatever is in the inputImage array as reference.
                    print "Taking reference slopes from current camera input"
                    self.runSlopeCalc(control)
                else:
                    self.reorderedPhs[:]=0
                    self.runCalc(control)
                self.centcmod.update(util.centcmod.CORRELATIONCENTROIDING,self.correlationCentroiding)
                control["cal_source"]=c
                self.linearSteps=steps
                if self.corrPatternUser is None:
                    self.corrPatternUser=self.cmodbimg.copy()
                else:#copy into existing, and make correct shape.
                    if self.corrPatternUser.shape==self.cmodbimg.shape:
                        self.corrPatternUser[:]=self.cmodbimg
                    else:
                        self.corrPatternUser[:]=0
                        if len(self.corrPatternUser.shape)==4:
                            s=(self.corrPatternUser.shape[-2]-self.cmodbimg.shape[-2])//2
                            e=s+self.cmodbimg.shape[-2]
                            self.corrPatternUser[:,:,s:e,s:e]=self.cmodbimg
                        else:
                            print self.corrPatternUser.shape
                            raise Exception("Not yet implemented... padding of 2d corr images")
                if self.correlationCentroiding==1:
                    self.corrPatternUser/=max(self.corrPatternUser.ravel())#normalise
                    self.corrPattern=util.correlation.transformPSF(self.corrPatternUser)
                else:#other modes don't need a transformed psf...
                    self.corrPattern=self.corrPatternUser.copy()
                self.centcmod.update(util.centcmod.CORRPATTERN,self.corrPattern)
                data=self.corrPatternUser
        return data
    def takeCentWeight(self,control):
        """If centWeight is a string (eg make or something similar), use a default SH spot pattern as the reference centroid weighting.
        """
        if type(self.centWeight)==type(""):
            #Need to create the centroid weighting.
            if self.corrPattern is None:
                c=control["cal_source"]
                control["cal_source"]=1
                steps=self.linearSteps
                self.linearSteps=None
                if self.centcmod==None:
                    raise Exception("Not yet sorted for non-cmod type things")
                self.reorderedPhs[:]=0
                self.runCalc(control)
                control["cal_source"]=c
                self.linearSteps=steps
                self.centWeight=self.cmodbimg.copy()
                self.centcmod.update(util.centcmod.CENTWEIGHT,self.centWeight)

def computeOld(phase,nsubx):
    """Simple interface..."""
    c=centroid(nsubx,pup=util.tel.Pupil(phase.shape[0],phase.shape[0]/2,0))
    c.run(phase)
    return c

def compute(phase,nsubx):
    """Simple interface"""
    import util.tel
    npup=phase.shape[0]
    fftsize=npup/nsubx*2
    phasesize=npup/nsubx
    nimg=phasesize
    ncen=phasesize
    c=util.centroid.centroid(nsubx,util.tel.Pupil(npup,npup/2,0,nsubx),fftsize=fftsize,binfactor=None,phasesize=phasesize,nimg=nimg,ncen=ncen)#addPoisson=0,sig=1.
    c.easy()
    c.reformatPhs(phase)
    c.runCalc({"cal_source":0})
    #c.outputData is the slopes
    #c.cmodbimg is the wfs image (divided into subaps).
    #Then, put your data into self.reorderedPhs... 
    img=c.reformatImg()# can be used to get a displayable image.
    #If you have a 2D phase map, you can put this into reorderdPhs by calling:
    return img,c

def createAiryDisc(npup,halfwidth=1.,xoff=0.,yoff=0.):
    """Creates an airy disk pattern central on an array npup pixels wide,
    with a width (2*halfwidth) specified in pixels.
    xoff/yoff can be used to shift the airy disc around the array:
    central by default for both odd and even sized arrays.
    This can be used for convolving with the high light level SHS spots
    (ie before noise addition).
    """
    import scipy.special
    #first zero of j1 occurs at 3.8317 (http://mathworld.wolfram.com/BesselFunctionZeros.html).
    #However, this should occur at 1.22lambda/D.  So need to scale this.
    center=(npup%2-1.)/2
    dist=util.dist.dist(npup,dy=center+yoff,dx=center+xoff)*3.8317/halfwidth
    disc=scipy.special.j1(dist)/dist#ignore division by zero - the nan is removed later
    disc=numpy.where(dist==0,0.5,disc)**2#remove NaN and square...
    return disc.astype(numpy.float32)

def createAiryDisc2(npup,halfwidth,xoff=0.,yoff=0.,defocus=0):
    """Creates an airy disc pattern using an FFT method.  With offset==0, will be centred.
    halfwidth is the radius of the first Airy minimum
    Widths:  For pad==2, width=5, pad==4, width=10, pad=8, width=20, pad=16 width=38, pad=32 width=79.
    Binning then reduces this by the bin factor.

    Optional defocus is given in units of radians P-V of the focus zernike
    """
    import util.sci
    import util.tel
    #compute the padding and binning required to give requested halfwidth.
    #pxlscale = lam/diam*n/nfft*binfactor*180*3600/numpy.pi
    #First min at 1.22lambda/d, so diameter 2.44lambda/d radians.  Therefore this is 2.44*nfft/(n*bn) pixels.  So given halfwidth, compute nfft, n, bn.
    #i.e. halfwidth=1.22*nfft/(n*bn)
    #Also, npup=nfft/bn (npup is the output size).  So:
    #halfwidth=1.22*npup/n where n is the initial phase size.  bn, n, nfft and npup must be integer.
    #Therefore, n=1.22*npup/halfwidth

    n=1.22*npup/halfwidth
    bn=int(n/npup)+1
    #bn=1
    nfft=npup*bn
    print "createAiryDisc2:  n=%g, nfft=%d, binfactor=%d"%(n,nfft,bn)
    pup=util.tel.Pupil(int(numpy.ceil(n)),n/2,0).fn
    #centre on 2x2 pixels
    yoff-=0.5/bn
    xoff-=0.5/bn
    #xoff,yoff of 1 will move it by a pixel in the unbinned image.  So, to move by 1 pixel in the binned image, increase this by the bin factor.
    tilt=computePhaseTilt(pup,nfft,1,xoff*bn,yoff*bn)
    if defocus!=0:
        #add zernike focus of strength.
        import util.zernikeMod
        f=util.zernikeMod.Zernike(pup,4,computeInv=0).zern[3]
        f-=f.min()
        f*=defocus/f.max()
        tilt+=f
        
    psf=util.sci.computeShortExposurePSF(tilt,pup,pad=nfft/numpy.ceil(n)).astype(numpy.float32)
    if bn!=1:
        psf.shape=psf.shape[0]/bn,bn,psf.shape[1]/bn,bn
        psf=psf.sum(3).sum(1)
    return psf
def computePhaseTilt(pup,nfft,binfactor,xoff=0.,yoff=0.):
    """A phase tilt is necessary since binning with an even number...
    This ensures the PSF is squarely spaced before binning"""
    npup=pup.shape[0]
    bf=binfactor
    tmp=float(npup)/float(nfft)*2*numpy.pi#*(bf-1)
    tmpx=tmp*xoff
    tmpy=tmp*yoff
    xtiltfn=((numpy.fromfunction(lambda x,y:y,(npup,npup))-float(npup)/2.+0.5)/float(npup)).astype(numpy.float32)# subap tilt fn
    phaseTilt=(pup*(tmpx*xtiltfn+tmpy*numpy.transpose(xtiltfn))).astype(numpy.float32)
    return phaseTilt


def calccentroid(data):
    x=numpy.arange(data.shape[0])-data.shape[0]/2.+0.5
    s=data.sum()
    if s==0:
        cx=cy=0
    else:
        cx=(data.sum(0)*x).sum()/s
        cy=(data.sum(1)*x).sum()/s
    return cx,cy

class CalData:
    def __init__(self,xc,xr,yc,yr):
        self.xc=xc#x centroids
        self.xr=xr#x range
        self.yc=yc
        self.yr=yr
        self.indx=[]
        self.xindx=None
        self.yindx=None
