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
"""Code to make a reconstructor from a very big (sparse) poke matrix.
See the __main__ part at the bottom for the recommended way to start...

After doing this and finding a typical minimum value to use for the reconstructor, if you need to investigate different svd conditioning, can then use finalDot(rmxtype=1), to give a csr output without needing to make the huge dense reconstructor.  This should be quite a bit faster since paging won't be needed.

Saving files - we by default save them not byteswapped - to they would look like nonsense if read by a normal viewer.  However, util.FITS.Read and associated methods knows about this, and to if it finds an UNORDERD key, it doesn't byteswap even if asked to.
"""
import util.FITS,numpy
import sys,time,os
import util.gradientOperator
#import util.dot as quick
#sys.path.insert(0,"/home/ali/c/lapack")
#import svd
acml=0
atlas=0
openblas=0
try:
    import cmod.mkl as mkl
except:
    print "Cannot import mkl - trying acml..."
    try:
        import cmod.acml as mkl
        acml=1
    except:
        print "Cannot import mkl or acml - trying atlas..."
        try:
            import cmod.atlas as mkl
            atlas=1
        except:
            print "Cannot import atlas either - trying openblas"
            try:
                import cmod.openblas as mkl
                openblas=1
            except:
                print "Warning: in computeRecon.py - cmod.mkl, cmod.acml and cmod.atlas not found - this may cause problems depending what functions you want - but continuing anyway"

try:        
    import cmod.svd
except:
    print "WARNING: util.computeRecon unable to import cmod.svd"
import scipy.sparse

def keyboard(banner=None):
    """A class that allows us to break to python console on exception."""
    import code, sys

    # use exception trick to pick up the current frame
    try:
        raise None
    except:
        frame = sys.exc_info()[2].tb_frame.f_back

    # evaluate commands in current namespace
    namespace = frame.f_globals.copy()
    namespace.update(frame.f_locals)

    code.interact(banner=banner, local=namespace)



class sparseHolder:
    def __init__(self):
        self.data=None
        self.shape=None
        self.colind=None
        self.indptr=None

class makeRecon:
    def __init__(self,pmxfname,rcond=0.1,regularisation=0.):
        self.pmxfname=pmxfname
        if regularisation!=0:
            pmxfname=pmxfname[:-5]+"reg%g.fits"%regularisation
        self.rcond=rcond
        self.dottedname=pmxfname[:-5]+"_dotted.fits"
        self.uname=pmxfname[:-5]+"_u.fits"
        self.vtname=pmxfname[:-5]+"_vt.fits"
        self.ename=pmxfname[:-5]+"_evals.fits"
        self.invname=pmxfname[:-5]+"_inv%g.fits"%rcond
        self.rmxdensename=pmxfname[:-5]+"_rmxden%g.fits"%rcond
        self.rmxcsrname=pmxfname[:-5]+"_rmxcsr%g.fits"%rcond
        self.rmxcscname=pmxfname[:-5]+"_rmxcsc%g.fits"%rcond
        self.timename=pmxfname[:-5]+"_timing.txt"
        self.cntname=pmxfname[:-5]+"_cnt.txt"
        self.regularisation=regularisation

    def initFromParams(paramList=["params.xml"],batchno=0):
        import base.readConfig
        self.c=base.readConfig.AOXml(paramList,batchno=batchno)
        c=self.c

    def log(self,txt):
        f=open(self.timename,"a")
        f.write(txt)
        f.close()
    def dotdot(self,csc=None,diagScaling=None,save=1):
        """Do the sparse dot product with self transposed...
        If have a diagonal scaling, want to multiply each col by the sqrt of this value in the pmx, before dotting..., i.e. if A is the diagonal scaling mx, and B is sqrt(A)

        PAP^T = PB BP^T

        """
        pmxfname=None
        if csc is None:
            pmxfname=self.pmxfname
            csc=util.FITS.loadSparse(pmxfname,doByteSwap=1)
        if isinstance(csc,numpy.ndarray):
            shape=csc.shape
            if diagScaling is not None:
                if type(diagScaling)==numpy.ndarray:#can also be None or float.
                    if diagScaling.shape[0]!=shape[1] or len(diagScaling.shape)!=1:
                        raise Exception("Wrong diagonal scaling (%s), expected shape %d (pmx=%s)"%(str(diagScaling.shape),shape[1],str(shape)))
                    diagScaling=numpy.sqrt(diagScaling)
                else:
                    diagScaling=numpy.ones((shape[1],),numpy.float32)*numpy.sqrt(diagScaling)
            if atlas or openblas:
                res=numpy.zeros((shape[0],shape[0]),csc.dtype,order="C")
            else:
                res=numpy.zeros((shape[0],shape[0]),csc.dtype,order="F")
            lines=open("/proc/meminfo").readlines()
            for line in lines:
                if "MemTotal:" in line:
                    mem=int(line.split()[1])
                    multiplier={"kB":1024,"b":1,"B":1,"mB":1024*1024,"MB":1024**2,"GB":1024**3,"gB":1024**3}
                    if line.split()[2] in multiplier.keys():
                        mem*=multiplier[line.split()[2]]
                    else:
                        print "WARNING - multiplier %s not known for memory"
                    print "Total system memory %d bytes"%mem
                    break

            #compute the number of blocks to divide the multiplication into...
            nblock=1
            while (shape[0]/nblock*shape[1]*2+(shape[0]/nblock)**2)*csc.itemsize>mem:
                nblock+=1
            print "Doing gemm in %d quadrants, shape %s"%(nblock*nblock,str(csc.shape))
            size=shape[0]/nblock
            t0=time.time()
            warn=0
            for i in range(nblock):
                vstart=i*size
                vend=(i+1)*size
                if i==nblock-1:
                    vend=shape[0]
                a=csc[vstart:vend]#c contig still.
                for j in range(nblock):
                    ustart=j*size
                    uend=(j+1)*size
                    if j==nblock-1:
                        uend=shape[0]
                    if diagScaling is not None and i==0:
                        #scale the elements. - we do it in blocks to avoid potential swapping if csc is large.
                        for si in xrange(csc.shape[1]):
                            csc[ustart:uend,si]*=diagScaling[si]
                    b=csc[ustart:uend].transpose()#f contig
                    print "Starting gemm %d %d"%(i,j)
                    t1=time.time()
                    mkl.gemm(a,b,res[vstart:vend,ustart:uend])
                    t2=time.time()
                    print "GEMM time %gs"%(t2-t1)
                    del(b)
                    if diagScaling is not None and i==nblock-1:#scale back so as not the alter csc.
                        for si in xrange(csc.shape[1]):
                            if diagScaling[si]!=0:
                                csc[ustart:uend,si]/=diagScaling[si]
                            else:
                                warn=1
                del(a)
            if warn:
                print "Warning - not able to revert pmx back to what it was... (if covariance==0 and wfs is unused, doesn't matter)"
            t2=time.time()
            print "Total GEMM time %gs"%(t2-t0)
            open(self.timename,"a").write("mx dot mx dense %gs\n"%(t2-t1))
            extraHeader=None
            if self.regularisation!=0.:
                print "Doing regularisation %g"%self.regularisation
                for i in range(res.shape[0]):
                    res[i,i]+=self.regularisation
                print "Regularisation done"
                extraHeader="REGULARD= %g"%self.regularisation
            if save:
                util.FITS.Write(res,self.dottedname,doByteSwap=0,extraHeader=extraHeader)
            del(csc)
        else:
            if diagScaling is not None:
                raise Exception("Not yet implemented:  diagScaling in dotdot() in util/computeRecon.py")
            csr=csc.tocsr()
            csc=csr.transpose()
            #resindptr=numpy.zeros((csr.shape[0]+1,),numpy.int32)
            #rescolind=numpy.zeros((csr.nnz*2,),numpy.int32)
            #resdata=numpy.zeros((csr.nnz*2,),numpy.float32)
            print "Doing sparse dot %s %s"%(str(csr.shape),str(csc.shape))
            t1=time.time()
            res=cmod.svd.csrDotCsc(csr.data,csr.colind,csr.indptr,csc.data,csc.rowind,csc.indptr,8)#resdata,rescolind,resindptr,8)
            t2=time.time()
            print "Time for mx dot mx %gs"%(t2-t1)
            open(self.timename,"a").write("mx dot mx %gs\n"%(t2-t1))
            res=scipy.sparse.csr_matrix(res,dims=(csr.shape[0],csr.shape[0]))
            if save:
                util.FITS.saveSparse(res,self.dottedname,doByteSwap=0)
            del(csc)
            del(csr)
        return res

    def dosvd(self,issparse=1,dtype=numpy.float32,a=None,usesdd=0):
        """Here, a is the densified result from dotdot, ie a square matrix"""
        fname=self.dottedname
        #res=util.FITS.loadSparse(fname,doByteSwap=1)#scipy.sparse.csr_matrix() fails for large sparse matrix...
        if a is None:
            if issparse:
                res=util.FITS.Read(fname,doByteSwap=1,savespace=1)
                shape=eval(res[0]["parsed"]["SHAPE"])
                if res[0]["parsed"].has_key("REGULARD"):
                    print "Using regularised matrix (%g added to diag)"%float(res[0]["parsed"]["REGULARD"])
                if res[0]["parsed"]["FORMAT"]!="csr":
                    raise Exception("Must be CSR matrix")
                #print "Loaded sparse",res.shape,res.data.shape,res.data.dtype.char,type(res),res.indptr.shape
                a=numpy.zeros(shape,res[1].dtype)
                sp=sparseHolder()
                sp.shape=shape
                sp.data=res[1]
                sp.colind=res[3].view(numpy.uint32)
                sp.indptr=res[5].view(numpy.uint32)
                cmod.svd.densifyCsr(a,sp)
                #a=res.todense()#seems to fail if a==18GB.
                print "done todense"
                del(sp)
                del(res)
            else:
                res=util.FITS.Read(fname,doByteSwap=1,savespace=1)
                a=res[1]
                if res[0]["parsed"].has_key("REGULARD"):
                    print "Using regularised matrix (%g added to diag)"%float(res[0]["parsed"]["REGULARD"])
        if not a.flags.c_contiguous:
            print "Transposing a before svd to make c contiguous"
            a=a.transpose()#should now be c-contiguous.
        if not a.flags.c_contiguous:
            raise Exception("A not contiguous")
        if a.dtype!=dtype:
            a=a.astype(dtype)
        print "SVD of matrix with shape",a.shape
        u=a
        #usesdd=0
        vt=numpy.zeros(a.shape,dtype)
        evals=numpy.zeros((a.shape[0],),dtype)
        print "Computing lwork"
        lwork=mkl.svd(a,u,evals,vt,None,usesdd)
        # there is an issue here, that when lwork is large, it isn't accurately represented by a 32 bit float, so is wrong in the conversion.  So, need to work out a larger value that it could be.  This is a bug with intel MKL
        i=0
        aa=numpy.zeros((2,),dtype)
        aa[:]=lwork
        while aa.astype("l")[0]==aa.astype("l")[1]:
            aa[1]=aa[0]+i
            i+=1
        lwork=aa.astype("l")[1]
        print "Got lwork (both) of %d"%lwork
        work=numpy.zeros((lwork,),dtype)
        print "Doing SVD"
        t1=time.time()
        mkl.svd(a,u,evals,vt,work,usesdd)#may take a bit of time of paging at the start, but then should run okay.
        t2=time.time()
        print "SVD time %g"%(t2-t1)
        open(self.timename,"a").write("SVD %gs\n"%(t2-t1))
        # note, u and vt are swapped around compared with what I'm used to from numpy.svd, so I swap them back here...
        util.FITS.Write(evals,self.ename,doByteSwap=0)
        util.FITS.Write(u,self.vtname,doByteSwap=0)
        util.FITS.Write(vt,self.uname,doByteSwap=0)
        return vt,evals,u

    def makeInv(self):
        """Use the SVD result to make the inverse"""
        rcond=self.rcond
        evals=util.FITS.Read(self.ename,savespace=1,doByteSwap=1)[1]
        ievals=numpy.where(evals<evals[0]*rcond,0.,1/evals).astype(evals.dtype)
        neig=numpy.nonzero(ievals)[0][-1]+1
        print "neig %d"%neig
        print "Normalised cancelled evals:",evals[neig:]/evals[0]
        del(evals)
        #Now work out how many stages to do the multiply in...
        #ie optimal memory use...
        lines=open("/proc/meminfo").readlines()
        for line in lines:
            if "MemTotal:" in line:
                mem=int(line.split()[1])
                multiplier={"kB":1024,"b":1,"B":1,"mB":1024*1024,"MB":1024**2,"GB":1024**3,"gB":1024**3}
                if line.split()[2] in multiplier.keys():
                    mem*=multiplier[line.split()[2]]
                else:
                    print "WARNING - multiplier %s not known for memory"
                print "Total system memory %d bytes"%mem
                break

        invmem=ievals.shape[0]**2*ievals.itemsize#memory to store the inverse - and also the memory to store u and vt as well, since all same size.
        memleft=mem-invmem
        if memleft>0:#compute the number of blocks to divide u and vt into.
            nblock=int(numpy.ceil(invmem*2./memleft))
        else:#??? just try doing the whole thing in memory!
            nblock=1
        print "Doing gemm in %d quadrants"%(nblock*nblock)
        size=ievals.shape[0]/nblock
        veut=None
        t0=time.time()
        for i in range(nblock):
            vstart=i*size
            vend=(i+1)*size
            if i==nblock-1:
                vend=ievals.shape[0]
            vt=util.FITS.Read(self.vtname,savespace=1,doByteSwap=1)[1]#c contig
            #tmp=vt[:,vstart:vend].copy()
            #del(vt)
            #vt=tmp
            #del(tmp)
            vt=vt[:neig,vstart:vend].transpose()#not contig
            v=vt.copy()#c contig
            del(vt)
            for k in xrange(neig):
                v[:,k]*=ievals[k]#multiply column by eval.
            for j in range(nblock):
                ustart=j*size
                uend=(j+1)*size
                if j==nblock-1:
                    uend=ievals.shape[0]
                u=util.FITS.Read(self.uname,savespace=1,doByteSwap=1)[1]
                tmp=u[ustart:uend,:neig].copy()#c contig
                del(u)
                ut=tmp.transpose()#fcontig
                del(tmp)

                if type(veut)==type(None):
                    veut=numpy.zeros((ievals.shape[0],ievals.shape[0]),ut.dtype,order="F")
                print "Starting gemm %d %d"%(i,j)
                t1=time.time()
                mkl.gemm(v,ut,veut[vstart:vend,ustart:uend])
                t2=time.time()
                print "GEMM time %gs"%(t2-t1)
                del(ut)
            del(v)
        t2=time.time()
        #if veut.dtype!=numpy.float32:
        #    veut=veut.astype(numpy.float32)
        util.FITS.Write(veut,self.invname,doByteSwap=0)
        print "Total GEMM time %gs"%(t2-t0)
        open(self.timename,"a").write("makeInv %gs\n"%(t2-t0))
        self.log("rcond=%g"%self.rcond)
        return veut

    def makeLUInv(self,a=None,dtype=numpy.float32,save=1):
        """Do LU decomposition to compute inverse..."""
        if type(a)!=numpy.ndarray:
            if type(a)==type(""):
                fname=a
            else:
                fname=self.dottedname
            res=util.FITS.Read(fname,doByteSwap=1,savespace=1)
            a=res[1]
            if res[0]["parsed"].has_key("REGULARD"):
                print "Using regularised matrix (%g added to diag)"%float(res[0]["parsed"]["REGULARD"])
        else:
            print "Will overwrite a with inv(a)"
        if not a.flags.c_contiguous:
            print "Transposing a before LU inversion to make c contiguous"
            a=a.transpose()#should now be c-contiguous.
        if not a.flags.c_contiguous:
            raise Exception("A not contiguous")
        if a.dtype!=dtype:
            a=a.astype(dtype)
        if acml or atlas or openblas:
            ipiv=numpy.zeros((min(a.shape),),numpy.int32)
        else:
            ipiv=numpy.zeros((min(a.shape),),numpy.int64)
        t1=time.time()
        mkl.ludecomp(a,ipiv)
        if acml or atlas or openblas:
            lw=1
        else:
            lw=mkl.luinv(a,ipiv,None)
        work=numpy.zeros((lw,),a.dtype)
        mkl.luinv(a,ipiv,work)
        t2=time.time()
        if save:
            util.FITS.Write(a,self.invname,doByteSwap=0)
        self.log("makeLUInv time %g\n"%(t2-t1))
        return a


    def denseDotDense(self,a=None,b=None,transA=0,transB=0,resname=None,diagScaling=None,save=1):
        """Dot product of the poke matrix with the gen inv of pmx dot pmxT to give the reconstructor, assuming inputs and output all dense.
        a and b must be the filenames
        Can be used instead of finalDot() giving a dense result...
        
        DiagScaling can be used for introducing noise covariance (also required in dotdot).  
        """
        if a is None:
            pmxfname=self.pmxfname
        else:
            pmxfname=a
        #pmx=util.FITS.Read(pmxfname,savespace=1,doByteSwap=1)[1]
        pmxh=util.FITS.ReadHeader(pmxfname)["parsed"]
        bytepix=-int(pmxh["BITPIX"])/8
        print "Using %d byte itemsize for denseDotDense"%bytepix
        if pmxh["NAXIS"]!="2":
            raise Exception("A Matrix must be 2d")
        if transA:
            pmxshape=int(pmxh["NAXIS1"]),int(pmxh["NAXIS2"])
        else:
            pmxshape=int(pmxh["NAXIS2"]),int(pmxh["NAXIS1"])
        #if transA:
        #    pmx=pmx.transpose()
        #if not pmx.flags.c_contiguous:
        #    pmx=pmx.copy()

        if diagScaling is not None:
            if type(diagScaling)==numpy.ndarray:#can also be None or float.
                if diagScaling.shape[0]!=int(pmxh["NAXIS1"]) or len(diagScaling.shape)!=1:
                    raise Exception("Wrong diagonal scaling, expected shape %d (pmx=%s)"%(shape[1],str(shape)))
                #diagScaling=numpy.sqrt(diagScaling)
            else:
                diagScaling=numpy.ones((shape[1],),numpy.float32)*diagScaling


        if b is None:
            invname=self.invname
        else:
            invname=b
        #veut=util.FITS.Read(invname,savespace=1,doByteSwap=1)[1]
        veuth=util.FITS.ReadHeader(invname)["parsed"]
        if veuth["NAXIS"]!="2":
            raise Exception("B matrix must be 2d")
        if transB:
            veutshape=int(veuth["NAXIS1"]),int(veuth["NAXIS2"])
        else:
            veutshape=int(veuth["NAXIS2"]),int(veuth["NAXIS1"])
        #if not veut.flags.c_contiguous:
        #    veut=veut.copy()
        if resname is None:
            resname=self.rmxdensename
        mem=self.getMem()*0.9#get available memory - problems when required is just less then available - swapping - so reduce total by x0.9... 
        ansmem=pmxshape[0]*veutshape[1]*bytepix#memory to store the result
        memleft=mem-ansmem
        if memleft>0:
            nblock=int(numpy.ceil((pmxshape[0]*pmxshape[1]*bytepix+veutshape[0]*veutshape[1]*bytepix)/float(memleft)))
        else:
            print "Warning - the multiply result will fill entire memory plus - this could take a while... (%d,%d)"%(pmxshape[0],veutshape[1])
            nblock=4
        print "Doing gemm in %d quadrants.  Total shape %s x %s"%(nblock*nblock,str(pmxshape),str(veutshape))
        asize=pmxshape[0]/nblock
        bsize=veutshape[1]/nblock
        res=None
        t0=time.time()
        for i in range(nblock):
            astart=i*asize
            aend=(i+1)*asize
            if i==nblock-1:
                aend=pmxshape[0]
            try:
                a=util.FITS.Read(pmxfname,savespace=1,doByteSwap=1,memmap="r")[1]
            except:
                print "Unable to memmap %s, reading..."%pmxfname
                a=util.FITS.Read(pmxfname,savespace=1,doByteSwap=1)[1]
            if transA:
                a2=a[:,astart:aend].transpose()#not contig
                a2=a2.copy()#c contig
            else:
                a2=a[astart:aend]#c contig
            del(a)
            a=a2
            del(a2)
            if diagScaling is not None:
                #shape is nslopesPartial,nacts.
                for si in xrange(a.shape[0]):
                    a[si]*=diagScaling[si+astart]
                
                

            for j in range(nblock):
                bstart=j*bsize
                bend=(j+1)*bsize
                if j==nblock-1:
                    bend=veutshape[1]
                try:
                    b=util.FITS.Read(invname,savespace=1,doByteSwap=1,memmap="r")[1]
                except:
                    print "Unable to memmap %s, reading..."%invname
                    b=util.FITS.Read(invname,savespace=1,doByteSwap=1)[1]
                if transB:
                    b2=b[:,bstart:bend].copy()#c contig.
                    b2=b2.transpose()#now f contig and transposed, what we want.
                else:
                    b2=b[:,bstart:bend].transpose().copy()#c contig, transposed
                    b2=b2.transpose()#now f contig... which is what we want.
                del(b)
                b=b2
                del(b2)
                if type(res)==type(None):
                    if atlas or openblas:
                        res=numpy.empty((pmxshape[0],veutshape[1]),a.dtype,order="C")
                    else:
                        res=numpy.empty((pmxshape[0],veutshape[1]),a.dtype,order="F")
                print "Starting gemm %d %d"%(i,j)
                t1=time.time()
                mkl.gemm(a,b,res[astart:aend,bstart:bend])
                t2=time.time()
                print "GEMM time %gs"%(t2-t1)
                del(b)
            del(a)
        if save:
            util.FITS.Write(res,resname,doByteSwap=0)
        t1=time.time()
        print "Total GEMM time %gs"%(t2-t0)
        open(self.timename,"a").write("denseDotDense %gs\n"%(t2-t0))
        return res
        
    def dot(self,a,b,res=None,order=None):
        """A simple dot product using mkl"""
        if res is None:
            if order is None:
                if atlas or openblas:
                    order="C"
                else:
                    order="F"
            res=numpy.empty((a.shape[0],b.shape[1]),b.dtype,order=order)
        t1=time.time()
        mkl.gemm(a,b,res)
        t2=time.time()
        print "dot GEMM time %gs"%(t2-t1)
        #if order=="C":
        #    res=res.T
        return res

    def finalDot(self,veut=None,rmxtype=2,valmin=0.,save=1,maxelements=2**30,minelements=0):
        """Dot product of the poke matrix with the generalised inverse of pmx dot pmxT, to give the reconstructor.
        rmxtype can be 0 (csc), 1 (csr) or 2 (dense).  For testing purposes, dense is recommended, until you know a suitable valmin value, and is only slightly slower than a non-paged csr/csc type.
        maxelements is the max number of elements allowed.  The default is 2**30, which corresponds to 8GB (2 arrays of this size, each elemnt is 4 bytes).
        mn and mx are the min and max number of elements (fraction or whole) allowed in the final sparse matrix.  If not specified, anything is allowed.
        """
        self.log("finalDot max %g min %g"%(maxelements,minelements))
        pmxfname=self.pmxfname
        if type(veut)==type(None):
            veut=util.FITS.Read(self.invname,savespace=1,doByteSwap=1)[1]
        if not veut.flags.c_contiguous:
            veut=veut.copy()
        csc=util.FITS.loadcsc(pmxfname,doByteSwap=1)
        if maxelements is not None and maxelements<=1:
            maxelements=int(maxelements*veut.shape[0]*csc.shape[1])
        if minelements is not None and minelements<1:
            minelements=int(minelements*veut.shape[0]*csc.shape[1])
        nthreads=8

        done=0
        vallist=[]#this list will contain failed values of valmin.
        donecnt=0
        while done==0:
            print "Starting denseDotCsc with valmin %g"%valmin
            self.log("Trying denseDotCsc with valmin %g"%valmin)
            vallist.append(valmin)
            t1=time.time()
            rmx=cmod.svd.denseDotCsc(veut,csc,valmin,rmxtype,nthreads,maxelements)
            t2=time.time()
            open(self.timename,"a").write("denseDotCsc %gs\n"%(t2-t1))
            print "denseDotCsc time %gs"%(t2-t1)
            if type(rmx)==type(0):#failed when reached maxelements...
                #the value of rmx is the row reached - which will help us guess a new value for valmin.
                #Need to increase valmin.
                if rmxtype==0:
                    frac=float(rmx)*nthreads/csc.shape[1]
                else:
                    frac=float(rmx)*nthreads/veut.shape[0]
                tmp=0
                for v in vallist:
                    if v>valmin:#can't go larger than v
                        if v<tmp or tmp==0:
                            tmp=v
                if tmp==0:
                    if valmin==0:
                        valmin=frac
                    else:
                        valmin/=frac#*=1.5
                else:
                    valmin=(valmin+tmp)/2.

                print "denseDotCsc failed - return value %d - increasing valmin to %g and trying again."%(rmx,valmin)
            elif type(rmx)==type(()):#csc or csr...
                if rmx[2][-1]<minelements or rmx[2][-1]>maxelements:
                    if rmx[2][-1]<minelements:#valmin too high...
                        tmp=0
                        for v in vallist:
                            if v<valmin:#can't go lower than v
                                if v>tmp:
                                    tmp=v
                        if tmp==0:#no previous elements
                            valmin/=4.
                        else:
                            valmin=(valmin+tmp)/2.
                    else:#valmin too low (too many values)
                        tmp=0
                        for v in vallist:
                            if v>valmin:#can't go larger than v
                                if v<tmp or tmp==0:
                                    tmp=v
                        if tmp==0:
                            if valmin==0:
                                valmin=0.1
                            else:
                                valmin*=1.5
                        else:
                            valmin=(valmin+tmp)/2.
                    print "finalDot - sparse matrix created with %d elements, not in allowed range of %d to %d - trying again with valmin %g"%(rmx[2][-1],minelements,maxelements,valmin)
                else:
                    done=1
            else:
                done=1
            donecnt+=1
        print "finalDot done in %d iterations"%donecnt
        self.log("finalDot done in %d iters"%donecnt)
        cscshape=csc.shape
        veutshape=veut.shape
        del(csc)
        del(veut)

        if rmxtype==2:
            if save:
                util.FITS.Write(rmx,self.rmxdensename,doByteSwap=0)
        elif rmxtype==1:
            rmx=scipy.sparse.csr_matrix(rmx,(veutshape[0],cscshape[1]))
            if save:
                util.FITS.saveSparse(rmx,self.rmxcsrname,doByteSwap=0)
        elif rmxtype==0:
            rmx=scipy.sparse.csc_matrix(rmx,(veutshape[0],cscshape[1]))
            if save:
                util.FITS.saveSparse(rmx,self.rmxcscname,doByteSwap=0)
        return rmx

    def count(self,vals,rmx=None):
        """vals is an array (or a list) of values to be counted.  This method returns a count array, with the values equal to the number of times a number greater or equal to the corresponding vals occurs in rmx.
        """
        vals=numpy.array(vals).astype(numpy.float32)
        cnt=numpy.zeros(vals.shape,numpy.int64)
        if type(rmx)==type(None):
            rmx=util.FITS.Read(self.rmxdensename,doByteSwap=1)[1]
        t1=time.time()
        cmod.svd.countInstances(rmx,vals,cnt)
        t2=time.time()
        print "Count time %gs"%(t2-t1)
        open(self.timename,"a").write("count time %gs\n"%(t2-t1))
        f=open(self.cntname,"w")
        for i in range(cnt.shape[0]):
            f.write("%g\t%d\n"%(vals[i],cnt[i]))
        f.close()
        return cnt

    def sparsify(self,rmx,csr,val):
        """Sparsify the rmx to a csr matrix.  Here, the csr matrix shopuld be large enough to hold all values in rmx with an absolute value greater or equal to val.  This can be determined by previously calling the count method."""
        t1=time.time()
        cmod.svd.sparsifyCsr(rmx,csr,val)
        t2=time.time()
        print "Sparsify time %gs"%(t2-t1)
        open(self.timename,"a").write("sparsify time %gs\n"%(t2-t1))
        util.FITS.saveSparse(csr,self.rmxcsrname,doByteSwap=0)

    def autoSparsify(self,rmx=None,frac=0.1,fracmin=0.,vals=None):
        """Sparsify the rmx to frac sparsity (or there abouts)"""
        if rmx is None:
            rmx=self.rmxdensename
        if type(rmx)==type(""):
            print "Loading rmx"
            try:
                rmx=util.FITS.Read(rmx,memmap="r")[1]
            except:
                print "Couldn't load memmapped - trying normally..."
                rmx=util.FITS.Read(rmx,memmap="r")[1]
        size=min(int(rmx.size*frac),2**31-1)
        sizemin=min(int(rmx.size*fracmin),size)
        print "Looking for count between",sizemin,size
        val=0
        if vals is None:
            vals=numpy.array([1e-6,1e-5,1e-4,1e-3,1e-2,0.05,0.1,0.2,0.5,1.,2.,5.,10.,100.,1e3,1e4,1e6]).astype("f")
        else:
            vals=numpy.array(vals).astype("f")
        found=0
        while found==0:
            valmin=1e-100
            valmax=1e100
            print "Counting for",vals
            cnt=self.count(vals,rmx)
            print cnt
            for i in range(cnt.shape[0]):
                if cnt[i]<=size:
                    if cnt[i]>=sizemin:#have found the correct one
                        val=vals[i]
                        ndata=cnt[i]
                        found=1
                        break
                    else:
                        valmax=vals[i]
                        if i==0:
                            valmin=0.
                        else:
                            valmin=vals[i-1]
                        break
            if found==0:
                #set up a new vals array...
                print "Setting up new vals ranging from %g to %g"%(valmin,valmax)
                vals=numpy.arange(10)*(valmax-valmin)/9.+valmin
        print "Got val %g cnt %d sparsity %g (looking for %d)"%(val,ndata,ndata/float(rmx.size),size)
        if val>0:
            #csr=scipy.sparse.csr_matrix(rmx.shape,nzmax=ndata,dtype=numpy.float32)
            tdata=numpy.zeros((ndata,),numpy.float32)
            tcolind=numpy.zeros((ndata,),numpy.uint32)
            tindptr=numpy.zeros((rmx.shape[0]+1,),numpy.uint32)
            class dummy:
                data=tdata
                colind=tcolind
                indptr=tindptr
                shape=rmx.shape
                format="csr"
            d=dummy()
            #csr=scipy.sparse.csr_matrix((data,colind,indptr),shape=rmx.shape)
            #csr.data=data
            #csr.colind=colind
            #csr.indptr=indptr
            self.sparsify(rmx,d,val)
            try:
                csr=scipy.sparse.csr_matrix((tdata,tcolind,tindptr),shape=rmx.shape)
            except:
                csr=scipy.sparse.csr_matrix((tdata,tcolind,tindptr),dims=rmx.shape)
            try:
                csr.check_format()
            except:
                print "WARNING: csr.check_format() failed - method may not exist (scipy version?) or csr may be invalid."
            return csr,cnt
        else:
            print "Unable to autoSparsify"
            return None,cnt
        
        
    def getMem(self):
        lines=open("/proc/meminfo").readlines()
        for line in lines:
            if "MemTotal:" in line:
                mem=int(line.split()[1])
                multiplier={"kB":1024,"b":1,"B":1,"mB":1024*1024,"MB":1024**2,"GB":1024**3,"gB":1024**3}
                if line.split()[2] in multiplier.keys():
                    mem*=multiplier[line.split()[2]]
                else:
                    print "WARNING - multiplier %s not known for memory"
                print "Total system memory %d bytes"%mem
                break
        return mem


    def test(self,rcond,valmin=0.):
        """Only use this on small matricees"""
        csc=util.FITS.loadcsc(self.pmxfname,doByteSwap=1)
        data=csc.todense()
        dd=quick.dot(data,data.transpose())
        idd=numpy.linalg.pinv(dd,rcond)
        rmx=quick.dot(idd,data)
        rmx=numpy.where(numpy.fabs(rmx)<valmin,0,rmx).astype("f")
        return data,dd,idd,rmx

    def compress(self,rmx=None,level=None):
        """Compress the rmx.
        This can be useful for simulations where rmx is too big to fit in memory, but compressed version isn't - the sim can then uncompress each iteration (may be faster than paging...), and means that only one machine is required, rather than splitting the mvm by MPI over more than one.
        TODO later maybe.  Use compression to fit the RMX in memory, then decompress bits at a time in tomoRecon.py.
        """
        

def getMem():
    lines=open("/proc/meminfo").readlines()
    for line in lines:
        if "MemTotal:" in line:
            mem=int(line.split()[1])
            multiplier={"kB":1024,"b":1,"B":1,"mB":1024*1024,"MB":1024**2,"GB":1024**3,"gB":1024**3}
            if line.split()[2] in multiplier.keys():
                mem*=multiplier[line.split()[2]]
            else:
                print "WARNING - multiplier %s not known for memory"
            print "Total system memory %d bytes"%mem
            break
    return mem


def compress(rmx,mbits=15,outfile=None):
    """Compress a float32 array into truncated floating point consisting of bits bits per element
    Can be used to compress large reconstructors so that they fit in memory - they can then be uncompressed on the fly, a bit at a time.
    """

    import cmod.utils
    if type(rmx)==type(""):
        rmx=util.FITS.Read(rmx)[1]
    else:
        print "computeRecon.compress: Destroying input"
    r=rmx.ravel()
    mn,mx=cmod.utils.compressFloatArrayAll(r,mbits)
    offset=mx-mn+1
    ebits=1
    while (offset>>ebits)>0:
        ebits+=1
    bits=mbits+ebits+1
    words=(rmx.size*bits+31)/32
    print "Got ebits=%d, total=%d, giving %d words (shape %s)"%(ebits,bits,words,str(rmx.shape))
    r=r[:words]
    if outfile is not None:
        #don't bother byteswapping because this data isn't in a standard format anyway (eg 24 bit float???)
        util.FITS.Write(r,outfile,extraHeader=["COMPBITS= %d"%mbits,"SHAPE   = %s"%str(rmx.shape),"EXPMIN  = %d"%mn,"EXPMAX  = %d"%mx],doByteSwap=0)
    return r


def reconstruct(config=["params.xml"],batchno=0,pmx=None,rcond=1e-06,startStage=0,idstr=None,power=-2,coneScale=1,actSpacingScale=-5./3,noiseScale=1.,noisePower=1.,hlist=None,strList=None,initDict=None,deleteTemp=1):
    if type(config) in [type(""),type([])]:
        import base.readConfig
        config=base.readConfig.AOXml(config,batchno=batchno,initDict=initDict)
    c=config
    if idstr is not None and len(idstr)>0:
        c.setSearchOrder(["tomoRecon_%s"%idstr,"tomoRecon","globals"])
    else:
        c.setSearchOrder(["tomoRecon","globals"])
    if pmx is None:
        pmx=c.getVal("pmxFilename")

    atmosGeom=c.getVal("atmosGeom")
    dmObj=c.getVal("dmOverview",raiseerror=0)
    if dmObj is None or type(dmObj)!=type(atmosGeom):
        print "DEPRECATION: warning: dmObj should now be dmOverview"
    #dmObj=c.getVal("dmObj")
    dmList=dmObj.makeDMList(idstr)
    print dmList
    nactsCumList=[0]
    pup=c.getVal("pupil")
    
    if hlist is None:
        hlist=c.getVal("hListdm",raiseerror=0)
        if hlist is None:
            hlist=c.getVal("dmHeight")
    hlistOrig=hlist
    if strList is None:
        cn2Orig=numpy.array(c.getVal("strListdm"))
    else:
        cn2Orig=strList
    cn2=numpy.array(c.getVal("strReconList",default=cn2Orig))
    cn2/=cn2Orig.sum()#same scaling
    print "cn2: %s"%str(cn2)
    if coneScale:
        #Scale strenghts because of cone effect...
        hlist=numpy.array(hlist)
        alt=c.getVal("lgsAlt")
        if alt>0:
            if numpy.any(hlist>alt):
                raise Exception("Unhandled - layer above LGS")
            cn2*=((alt-hlist)/alt)**(5./3)

    cn2=cn2**power*rcond
    cn2=numpy.where(numpy.isinf(cn2),0,cn2)
    if actSpacingScale!=0:
        #Scale regularisation due to actuator spacing.  So, scale proportional to spacing^(5/3).  I think. But -5/3 worked best for EAGLE!
        cn2*=numpy.array([x.actSpacing for x in dmList])**actSpacingScale
    print "Modified cn2: %s"%str(cn2)
    hlist=hlistOrig#c.getVal("hListdm")
    laplist=[]
    for dm in dmList:
        if dm.zonalDM:
            tmp=dm.getDMFlag(atmosGeom,centObscuration=pup.r2)
            nacts=int(tmp.sum())
        else:
            nacts=dm.nact
        print nacts
        nactsCumList.append(nactsCumList[-1]+nacts)
        g=util.gradientOperator.gradientOperatorType1(pupilMask=tmp.astype("f"),sparse=1)
        util.gradientOperator.genericLaplacianCalcOp_NumpyArray(g)
        laplacian2=numpy.dot(g.op,g.op)
        indx=list(hlist).index(dm.height)
        laplacian2*=cn2[indx]
        print "laplist shape %s"%str(laplacian2.shape)
        laplist.append(laplacian2)
    ll=[x.shape[0] for x in laplist]
    print "lapList %s"%str(ll)
    lapCumList=numpy.concatenate([[0],numpy.array(ll).cumsum()])
    print "lapCumList %s"%str(lapCumList)
    print "nactsCumList %s"%str(nactsCumList)
    for i in range(len(nactsCumList)):
        if lapCumList[i]!=nactsCumList[i]:
            print "Actuator counts don't agree (maxActDist may need changing)"
            keyboard()
            raise Exception("Actuator counts don't agree - change maxActDist or something.  Or force to gradientOperator pupil.")

    #First separate out lgs, ngs.
    minarea=c.getVal("wfs_minarea",0.5)
    ngsList=atmosGeom.makeNGSList(idstr,minarea=minarea)#self.nsubxDict,None)
    lgsList=atmosGeom.makeLGSList(idstr,minarea=minarea)
    #Note, in reconmx and pmx, ngsList comes first.
    ncents=0
    ncentNgsList=[]
    ncentLgsList=[]
    indiceNgsList=[]
    indiceLgsList=[]
    for gs in ngsList:
        subflag=pup.getSubapFlag(gs.nsubx,gs.minarea)
        indiceNgsList.append(numpy.nonzero(subflag.ravel())[0])
        ncentNgsList.append(numpy.sum(subflag.ravel()))
    for gs in lgsList:
        subflag=pup.getSubapFlag(gs.nsubx,gs.minarea)
        indiceLgsList.append(numpy.nonzero(subflag.ravel())[0])
        ncentLgsList.append(numpy.sum(subflag.ravel()))
    ncentList=ncentNgsList+ncentLgsList
    ncentsNgs=sum(ncentNgsList)*2
    ncentsLgs=sum(ncentLgsList)*2
    ncents=ncentsNgs+ncentsLgs

    #compute the noise covariance...
    invNoiseCov=numpy.zeros((ncents,),numpy.float32)
    invNoiseCovNgs=numpy.zeros((ncentsNgs,),numpy.float32)
    lgssig=c.getVal("wfs_sig",raiseerror=0)
    if len(lgsList)>0 and lgssig is None:
        lgssig=numpy.array([x.sig for x in lgsList]).mean()
    else:#no lgs.
        lgssig=0.
    wfsSigList=c.getVal("wfsSigList",raiseerror=0)
    wfsSigList=[x.sig for x in ngsList]
    print "Noise covariance scaling by %s for ngs, %g for lgs"%(str((numpy.array(wfsSigList)/1e6*noiseScale)**noisePower),(lgssig/1e6*noiseScale)**noisePower)
    start=0
    for i in range(len(ngsList)):
        gs=ngsList[i]
        end=start+ncentNgsList[i]
        if wfsSigList[i]==0:
            inc=0
        else:
            inc=(wfsSigList[i]/1e6*noiseScale)**noisePower
        invNoiseCov[start:end]=inc
        invNoiseCovNgs[start:end]=inc
        invNoiseCov[start+ncents/2:end+ncents/2]=inc
        invNoiseCovNgs[start+ncentsNgs/2:end+ncentsNgs/2]=inc
        start=end
    for i in range(len(lgsList)):
        gs=lgsList[i]
        end=start+ncentLgsList[i]
        invNoiseCov[start:end]=(lgssig/1e6*noiseScale)**noisePower
        invNoiseCov[start+ncents/2:end+ncents/2]=(lgssig/1e6*noiseScale)**noisePower
        start=end
    if deleteTemp==0:
        util.FITS.Write(invNoiseCov,"invNoiseCov.fits")
    #Now separate out ngs and lgs for split tomo.
    #First, use both lgs and ngs, for high order...
    data=util.FITS.Read(pmx)[1]
    print "%g slopes ngs, %g slopes lgs, pmx shape: %s"%(ncentsNgs,ncentsLgs,str(data.shape))
    if data.shape[0]!=nactsCumList[-1]:
        if data.shape[1]==nactsCumList[-1]:
            print "Transposing matrix... this could lead to slowness later on."
            data=data.T
        else:
            raise Exception("Not expected... %d %d"%(data.shape[0],nactsCumList[-1]))
    #lgsngsarr=numpy.empty((nactsCumList[-1],ncentsLgs),data.dtype)
    ##copy in data - x, then y.
    #lgsarr[:,:ncentsLgs/2]=data[:,ncentsNgs/2:ncents/2]
    #lgsarr[:,ncentsLgs/2:]=data[:,ncents/2+ncentsNgs/2:]
    pmxOrig=pmx
    #pmx="/var/ali/tmplgs.fits"
    #util.FITS.Write(lgsarr,pmx)
    #del(lgsarr)
    #Now take just the ngs part...
    if len(lgsList)>0:
        ngsarr=numpy.empty((nactsCumList[-1],ncentsNgs),data.dtype)
        ngsarr[:,:ncentsNgs/2]=data[:,:ncentsNgs/2]
        ngsarr[:,ncentsNgs/2:]=data[:,ncents/2:ncents/2+ncentsNgs/2]
    #Now, if sig for any is zero, set to zero.
    start=0
    resavepmx=0
    for i in range(len(ngsList)):
        gs=ngsList[i]
        end=start+ncentNgsList[i]
        if wfsSigList[i]==0:#this wfs isn't used...
            if len(lgsList)>0:
                ngsarr[:,start:end]=0
                ngsarr[:,ncentsNgs/2+start:ncentsNgs/2+end]=0
            resavepmx=1
            data[:,start:end]=0
            data[:,ncents/2+start:ncents/2+end]=0
        start=end
    if len(lgsList)>0:
        util.FITS.Write(ngsarr,"/var/ali/tmpngs.fits",doByteSwap=0)
        print "ngsarr shape %s"%str(ngsarr.shape)
        del(ngsarr)
    if resavepmx:
        print "Overwriting pmx with some zeros... for sig==0 wfss"
        util.FITS.Write(data,pmx,doByteSwap=0)
    print "Search for NaNs: %s"%numpy.any(numpy.isnan(data))
    del(data)
    

    t1=time.time()
    mr=util.computeRecon.makeRecon(pmx,rcond)#,regularisation=regparam)
    if startStage==0:
        print "invNoiseCov Nans: %s, max %g, min %g"%(numpy.any(numpy.isnan(invNoiseCov)),invNoiseCov.max(),invNoiseCov.min())
        res=mr.dotdot(diagScaling=invNoiseCov)
        print "Doing fancy regularisation"
        if res.shape[0]!=nactsCumList[-1]:
            raise Exception("Wrong number of acts: %s, %s"%(str(res.shape),str(nactsCumList)))

        for i in range(len(nactsCumList)-1):#add the laplacian...
            res[nactsCumList[i]:nactsCumList[i+1],nactsCumList[i]:nactsCumList[i+1]]+=laplist[i]#If this is wrong, try changing maxActDist.
        print "Saving laplacian..."
        util.FITS.Write(res,mr.dottedname,doByteSwap=0,extraHeader="REGPARAM= %s"%str(cn2))
        del(res)
        startStage=1
    print "Using LU decomposition"
    if startStage==1:
        inva=mr.makeLUInv()
        startStage=3
        del(inva)

    if startStage==3:
        rmx=mr.denseDotDense(transA=1,diagScaling=invNoiseCov)#finalDot(rmxtype=1,valmin=0.02,maxelements=0.1,minelements=0.05)
        startStage=4
        # Now subtract TT.  Here, subtract from the NGS too... but only if there are LGS present.
        if len(lgsList)>0:
            nxOld=0
            pos=0#ncentsNgs/2
            print "ncentLgsList: %s, rmx shape %s"%(str(ncentLgsList),str(rmx.shape))
            for i in range(len(ncentList)):
                nx=ncentList[i]
                if nx!=nxOld:
                    rmtt=numpy.identity(nx)-1./nx
                    nxOld=nx
                rmx[pos:pos+nx]=numpy.dot(rmtt,rmx[pos:pos+nx])
                rmx[pos+ncents/2:pos+ncents/2+nx]=numpy.dot(rmtt,rmx[pos+ncents/2:pos+ncents/2+nx])
                pos+=nx
                #rmx[i*nx:(i+1)*nx]=numpy.dot(rmtt,rmx[i*nx:(i+1)*nx])
            print "Writing TT-subtracted rmx to %s"%mr.rmxdensename
        else:
            print "Writing rmx to %s (no LGS, so no TT-subtraction)"%mr.rmxdensename
                    
        util.FITS.Write(rmx,mr.rmxdensename,doByteSwap=0)
    t2=time.time()
    open(mr.timename,"a").write("Total time %gs\n"%(t2-t1))




    #rmx shaoe ncents,nacts.
    if deleteTemp:
        print "Removing temporary files"
        try:
            os.unlink(pmx[:-5]+"_dotted.fits")
        #os.unlink(pmx[:-5]+".fits")
            os.unlink(pmx[:-5]+"_inv%g.fits"%rcond)
            os.unlink(pmx[:-5]+"_timing.txt")
        except:
            pass
    #And write rmx into the correct parts of a larger matrix...
    #rmxAll=numpy.empty((ncents,rmx.shape[1]),rmx.dtype)
    #rmxAll[ncentsNgs/2:ncents/2]=rmx[:ncentsLgs/2]
    #rmxAll[ncents/2+ncentsNgs/2:ncents]=rmx[ncentsLgs/2:]
    rmxAll=rmx

    if len(lgsList)>0:
        #Now do the ngs part too.
        print "Doing ngs",rmx.shape,nactsCumList[-1],ncents
        pmx="/var/ali/tmpngs.fits"
        startStage=0
        t1=time.time()
        mr=util.computeRecon.makeRecon(pmx,rcond)#,regularisation=regparam)
        if startStage==0 and len(ngsList)>0:
            res=mr.dotdot(diagScaling=invNoiseCovNgs)
            print "Doing fancy regularisation"
            if res.shape[0]!=nactsCumList[-1]:
                raise Exception("Wrong number of acts: %s, %s"%(str(res.shape),str(nactsCumList)))

            for i in range(len(nactsCumList)-1):#add the laplacian...
                res[nactsCumList[i]:nactsCumList[i+1],nactsCumList[i]:nactsCumList[i+1]]+=laplist[i]#If this is wrong, try changing maxActDist.
            print "Saving laplacian..."
            util.FITS.Write(res,mr.dottedname,doByteSwap=0,extraHeader="REGPARAM= %s"%str(cn2))
            del(res)
            startStage=1
        print "Using LU decomposition"
        if startStage==1 and len(ngsList)>0:
            inva=mr.makeLUInv()
            startStage=3
            del(inva)

        if startStage==3:
            if len(ngsList)>0:
                rmx=mr.denseDotDense(transA=1,diagScaling=invNoiseCovNgs)#finalDot(rmxtype=1,valmin=0.02,maxelements=0.1,minelements=0.05)
                startStage=4
                # Now average TT (since its ngs).
                nxOld=0
                pos=0
                for i in range(len(ncentNgsList)):
                    nx=ncentNgsList[i]
                    if nx!=nxOld:
                        avtt=numpy.ones((nx,nx),numpy.float32)/nx
                        nxOld=nx
                    rmxAll[pos:pos+nx]+=numpy.dot(avtt,rmx[pos:pos+nx])
                    rmxAll[pos+ncents/2:pos+ncents/2+nx]+=numpy.dot(avtt,rmx[pos+ncentsNgs/2:pos+ncentsNgs/2+nx])
                    pos+=nx

            #Get the expected output filename...
            mr=util.computeRecon.makeRecon(pmxOrig,rcond)#,regularisation=regparam)

            print "Writing TT-ngs/lgs rmx to %s"%mr.rmxdensename
            util.FITS.Write(rmxAll,mr.rmxdensename,doByteSwap=0)
        if deleteTemp:
            print "Removing more temporary files"
            try:
                os.unlink(pmx[:-5]+"_dotted.fits")
                os.unlink(pmx[:-5]+".fits")
                os.unlink(pmx[:-5]+"_inv%g.fits"%rcond)
                os.unlink(pmx[:-5]+"_timing.txt")
            except:
                print "Unable to remove some non-existant files"

    t2=time.time()
    open(mr.timename,"a").write("Total time %gs\n"%(t2-t1))
    return rmxAll




if __name__=="__main__":
    if len(sys.argv)>=2:
        fname=sys.argv[1]
    else:
        fname="/var/ali/spmx42mb0.fits"
    if len(sys.argv)>=3:
        rcond=float(sys.argv[2])
    else:
        rcond=0.01
    if len(sys.argv)>=4:
        frac=float(sys.argv[3])
    else:
        frac=0.01
    t1=time.time()
    mr=makeRecon(fname,rcond)
    res=mr.dotdot()
    del(res)
    u,e,vt=mr.dosvd()
    del(u)
    del(e)
    del(vt)
    inv=mr.makeInv()
    del(inv)
    rmx=mr.finalDot(rmxtype=1,valmin=0.01,save=1,maxelements=0.1,minelements=0.05)
    #csr,cnt=mr.autoSparsify(rmx,frac)
    
    t2=time.time()
    print "Completed in %gs"%(t2-t1)
    open(mr.timename,"a").write("Total time %gs\n"%(t2-t1))
