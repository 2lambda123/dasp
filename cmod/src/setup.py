from distutils.core import setup, Extension
import sys,os.path
idnumpy=[sys.prefix+'/lib/python%d.%d/site-packages/numpy/core/include'%(sys.version_info[0],sys.version_info[1]),sys.prefix+'/include']
idgsl=['/opt/local/include'] # Added for different GSL locations, NAB 08/Apr/2013

# platorm dependant stuff
if sys.platform=='darwin':
	# MacOSX vecLib framework, for BLAS, NAB 08/Apr/2013
	idveclib=['/System/Library/Frameworks/vecLib.framework/Versions/A/Headers/'] 
	scrnmodule_extra_link_args=['-lgsl','-framework vecLib']
else:
	scrnmodule_extra_link_args=['-lm','-lcblas','-latlas','-lgsl']

ld=[sys.prefix+'/lib']
fft=Extension('fftmodule',
              include_dirs=idnumpy,
              library_dirs=ld,
              libraries=["pthread","fftw3f_threads","fftw3f"],
              extra_compile_args=[],
              extra_link_args=["-lpthread","-lfftw3f_threads","-lm"],#,"-lfftw3f"
              sources=["fftmodule.c"]
              )
cent = Extension('centmodule',
		include_dirs = idnumpy+idgsl,
		library_dirs=ld,
#			runtime_library_dirs=['/usr/local/lib'],
		libraries=["fftw3f"],
                extra_compile_args=["-pthread"],
		extra_link_args=["-lfftw3f",'-lgsl','-lgslcblas','-lm','-lpthread'],
	        sources = ['centmodule.c']
		)
binimg=Extension('binimgmodule',
		include_dirs=idnumpy,
		sources=['binimgmodule.c'],
		library_dirs=ld,
		extra_link_args=['-lm'],
		)
imgnoise=Extension('imgnoisemodule',
		include_dirs=idnumpy+idgsl,
		sources=['imgnoisemodule.c'],
		library_dirs=ld+[os.path.realpath('..'),os.path.realpath('.')],
		extra_link_args=['-lgsl','-lgslcblas','-lm'],
		)
utils=Extension('utilsmodule',
		include_dirs=idnumpy,
		sources=['utils.c'],
		library_dirs=ld,
		extra_link_args=['-lm'],
		 extra_objects = ['mvm.o']
		)
sor=Extension('sormodule',
              include_dirs=idnumpy,
              sources=['sormodule.c'],
              library_dirs=ld,
#              extra_link_args=['-lm'],
              )
interp=Extension('interpmodule',
#                 extra_compile_args=["-g"],
                 include_dirs=idnumpy+idgsl,
                 sources=['interpmodule.c','interpolate.c'],
                 library_dirs=ld+[os.path.realpath('..'),os.path.realpath('.')],
                 extra_link_args=['-lgsl','-lgslcblas','-lm'],
#                 extra_objects = ['interpolate.o']
                 )
phaseCov=Extension('phaseCovmodule',
                 include_dirs=idnumpy+idgsl,
                 sources=['phaseCovmodule.c'],
                 library_dirs=ld+[os.path.realpath('..'),os.path.realpath('.')],
                   extra_compile_args=["-pthread"],
                 extra_link_args=['-lgsl','-lgslcblas','-lm','-lpthread'],
                 )
zernike=Extension('zernikemodule',
                 include_dirs=idnumpy,
                 sources=['zernikemodule.c','josesubs.c'],
                 library_dirs=ld,
                 extra_link_args=['-lm'],
                 )
xpoke=Extension('xpokemodule',
                 include_dirs=idnumpy,
                 sources=['xpokemodule.c','josesubs.c'],
                 library_dirs=ld,
                 extra_link_args=['-lm'],
                 )
psfparams=Extension('psfparamsmodule',
                 include_dirs=idnumpy,
                 sources=['psfparamsmodule.c','josesubs.c'],
                 library_dirs=ld,
                 extra_link_args=['-lm'],
                 )
scrn=Extension('scrnmodule',
      include_dirs=idnumpy+idveclib+idgsl,
		sources=['scrnmodule.c'],
		library_dirs=ld+["/usr/lib64","/usr/lib64/atlas"],
		extra_link_args=scrnmodule_extra_link_args,
		)

setup (ext_modules = [fft,cent,binimg,imgnoise,utils,sor,interp,phaseCov,zernike,xpoke,psfparams,scrn])
