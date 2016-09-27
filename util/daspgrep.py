#!/usr/bin/env python
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
import sys
import os
import string

paramList=["strehl","strehlpeak","inbox","d50","fwhm","rms","rmserr","rmserrerr"]

def getArgs(args):
    glist=[]#list of strings required for selection
    flist=[]#list of files
    ilist=[]#outputs - strehl, etc.
    exclude=[]#list of strings to exclude
    vallist=[]#values to be printed
    valcharlist=[]#tuples of (N,text) where N is the number of characters after finding text to print.
    printid=0
    printdict=0
    printall=0
    printfile=0
    printindex=0
    precision=0
    space=0
    printval=0
    before=None
    after=None
    for a in args:
        if a[:7]=="--grep=":
            glist.append(a[7:])
        elif a[:6]=="--help":
            print "Usage: --grep=STRING --file=FILENAME --param=PARAMETER [--printid --printidBefore --printall --printdict --printall --printfile --printindex --space --precision --exclude=xxx --val=xxx --printval --before=yymmddhhmmss --after=yymmddhhmmss"
            print "Or:  grep string filename parameter"
            print "Note, strehl and inbox can be prefixed with % to return in percentage, eg %strehl %inbox0.1"
            print "Exclude parameter is a text string to be excluded"
            print "val parameter is a text string after which the next value is printed"
            sys.exit(0)
        elif a[:7]=="--file=":
            flist.append(a[7:])
        elif a[:8]=="--param=":
            ilist.append(a[8:])
        elif a[:9]=="--printid":
            if a[:15]=="--printidBefore":
                printid=-1
            else:
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
        elif a[:7]=="--space":
            space=1
            if a=="--space=0":
                space=0
        elif a[:7]=="--comma":
            if a=="--comma=0":
                pass
            else:
                space=2
        elif a[:11]=="--precision":
            precision=1
        elif a[:10]=="--exclude=":
            exclude.append(a[10:])
        elif a[:6]=="--val=":
            vallist.append(a[6:])
        elif a[:5]=="--val":
            valcharlist.append((int(a[5:a.index("=")]),a[a.index("=")+1:]))
        elif a[:10]=="--printval":
            printval=1
        elif a[:9]=="--before=":
            before=a[9:]
            before+="0"*(12-len(before))
        elif a[:8]=="--after=":
            after=a[8:]
            after+="0"*(12-len(after))
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
    return glist,flist,ilist,printid,printdict,printall,printfile,printindex,space,precision,exclude,vallist,printval,valcharlist,before,after


def grep(glist,flist,ilist,printid=0,printdict=0,printall=0,printfile=0,printindex=0,space=0,precision=0,exclude=[],vallist=[],printval=0,valcharlist=[],before=None,after=None):
    outtxt=""
    pretxt=""
    cnt=0
    fillchr="\t"
    if space==1:
        fillchr=" "
    elif space==2:
        fillchr=",\t"
    for f in flist:
        lines=open(f).readlines()
        for line in lines:
            ok=1
            for g in glist:
                if g not in line:
                    ok=0
                    break
            for e in exclude:
                if e in line:
                    ok=0
                    break
            if (before is not None) or (after is not None):
                try:
                    indx=line.index("iters, batchno")
                    indx=indx+15+line[indx+15:].index(" ")+1#skip the batchno
                except:
                    ok=0
                tstamp=line[indx:indx+6]+line[indx+7:indx+13]
                if before is not None and before<tstamp:
                    ok=0
                if after is not None and after>tstamp:
                    ok=0
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
                    txt+="%s%d"%(fillchr,cnt)
                cnt+=1
                if printfile:
                    txt+="%s%s"%(fillchr,f)
                if printid==1:
                    txt+="%s%s"%(fillchr,line[:indx])
                elif printid==-1:
                    pretxt+="%s%s\n"%(fillchr,line[:indx])
                for v in vallist:
                    try:
                        indx=line.index(v)+len(v)
                    except:
                        indx=None
                    if not printval:
                        v=""
                    if indx!=None:
                        pos=1
                        val=None
                        ll=line[indx:].strip()
                        minus=None
                        if ll[0]=="-":
                            ll=ll[1:]
                            minus=-1
                        err=0
                        while 1:
                            try:
                                val=eval(ll[:pos])
                                pos+=1
                                err=0
                            except:#err allows one extra test...
                                if err==1:
                                    break
                                else:
                                    pos+=1
                                    err=1
                        if minus!=None:
                            val=minus*val
                        txt+="%s%s%s"%(fillchr,v,str(val))
                    else:
                        txt+="%s%sNone"%(fillchr,v)
                for n,v in valcharlist:
                    try:
                        indx=line.index(v)+len(v)
                    except:
                        indx=None
                    if not printval:
                        v=""
                    if indx!=None:
                        txt+="%s%s%s"%(fillchr,v,line[indx:indx+n])
                    else:
                        txt+="%s%sNONE"%(fillchr,v)
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
                            txt+="%s%s"%(fillchr,key)
                        try:
                            if precision==0:
                                txt+="%s%.4g"%(fillchr,sciDict[key]*m)
                            else:
                                txt+="%s%g"%(fillchr,sciDict[key]*m)
                        except:
                            txt+="%s%s"%(fillchr,str(sciDict[key]))
                if space==2:
                    outtxt+="["
                    endline="],"
                else:
                    endline=""
                outtxt+="%s%s\n"%(txt[len(fillchr):],endline)

    return pretxt+outtxt


if __name__=="__main__":
    glist,flist,ilist,printid,printdict,printall,printfile,printindex,space,precision,exclude,vallist,printval,valcharlist,before,after=getArgs(sys.argv[1:])
    txt=grep(glist,flist,ilist,printid,printdict,printall,printfile,printindex,space,precision,exclude,vallist,printval,valcharlist,before,after)
    print txt
