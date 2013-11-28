#!/usr/bin/env python
import sys
import os
import string

paramList=["strehl","strehlpeak","inbox","d50","fwhm","rms","rmserr","rmserrerr"]

def getArgs(args):
    glist=[]#list of strings required for selection
    flist=[]#list of files
    ilist=[]#outputs - strehl, etc.
    printid=0
    printdict=0
    printall=0
    printfile=0
    printindex=0
    for a in args:
        if a[:7]=="--grep=":
            glist.append(a[7:])
        elif a[:6]=="--help":
            print "Usage: --grep=STRING --file=FILENAME --param=PARAMETER [--printid --printall --printdict --printall --printfile --printindex]"
            print "Or:  grep string filename parameter"
            print "Note, strehl and inbox can be prefixed with % to return in percentage, eg %strehl %inbox0.1"
            sys.exit(0)
        elif a[:7]=="--file=":
            flist.append(a[7:])
        elif a[:8]=="--param=":
            ilist.append(a[8:])
        elif a[:9]=="--printid":
            printid=1
            if a[:11]=="--printid=0":
                printid=0
        elif a[:11]=="--printdict":
            printdict=1
            if a[:13]=="--printdict=0":
                printdict=0
        elif a[:10]=="--printall":
            printall=1
            if a[:12]=="--printall=0":
                printall=0
        elif a[:11]=="--printfile":
            printfile=1
            if a[:13]=="--printfile=0":
                printfile=0
        elif a[:12]=="--printindex":
            printindex=1
            if a[:14]=="--printindex=0":
                printindex=0
        else:
            if os.path.exists(a):#is it a filename?
                flist.append(a)
            else:
                got=0
                for p in paramList:
                    if p==string.lower(a)[:len(p)] or (a[0]=="%" and p==string.lower(a[1:])[:len(p)]):#its a parameter
                        ilist.append(a)
                        got=1
                if got==0:#its a grep string
                    glist.append(a)
    return glist,flist,ilist,printid,printdict,printall,printfile,printindex


def grep(glist,flist,ilist,printid=0,printdict=0,printall=0,printfile=0,printindex=0):
    outtxt=""
    cnt=0
    for f in flist:
        lines=open(f).readlines()
        for line in lines:
            ok=1
            for g in glist:
                if g not in line:
                    ok=0
                    break
            if ok:#select the parameters now...
                try:
                    indx=line.index("{")
                    dicttxt=line[indx:]
                except:
                    dicttxt="{}"
                try:
                    indx1=dicttxt.index("}")
                    dicttxt=dicttxt[:indx1+1]
                except:
                    dicttxt="{}"
                try:
                    sciDict=eval(dicttxt)
                except:
                    sciDict={}
                try:
                    indx1=line.index("RMS: ")
                    rmsList=line[indx1+5:].split()
                    sciDict["RMS"]=float(rmsList[0])
                    sciDict["RMSErr"]=float(rmsList[2])
                    sciDict["RMSErrErr"]=float(rmsList[4])
                except:
                    pass
                if printall:
                    ilist=sciDict.keys()
                txt=""
                if printindex:
                    txt+="\t%d"%cnt
                cnt+=1
                if printfile:
                    txt+="\t%s"%f
                if printid:
                    txt+="\t%s"%line[:indx]
                for param in ilist:
                    if param[0]=="%":
                        m=100.
                        key=param[1:]
                    else:
                        key=param
                        m=1.
                    #if param in ["strehl","strehlPeak"] or param[:5]=="inbox":
                    #    m=100.
                    #else:
                    #    m=1.
                    if sciDict.has_key(key):
                        if printdict:
                            txt+="\t%s"%key
                        try:
                            txt+="\t%.3g"%(sciDict[key]*m)
                        except:
                            txt+="\t%s"%(str(sciDict[key]))

                outtxt+="%s\n"%txt[1:]
    return outtxt


if __name__=="__main__":
    glist,flist,ilist,printid,printdict,printall,printfile,printindex=getArgs(sys.argv[1:])
    txt=grep(glist,flist,ilist,printid,printdict,printall,printfile,printindex)
    print txt
