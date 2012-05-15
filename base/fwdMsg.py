#$Id: fwdMsg.py,v 1.5 2005/11/17 13:40:55 ali Exp $
import types,Numeric
class fwdMsg:
    """This class is little used, and should only be considered in extremely rare cases.  When used, it should be used to pass messages in the opposite direction to simulation data flow.

    A class for preparing a message for forwarding.  strng must be a string
    of length less than 16 bytes, i is an integer (4 bytes)
    and f is a double (8 bytes).
    It is necessary to be so strict about these things so that messages can
    also be passed over shm connections (ie fixed size, known size array).\n
    Class variables (important to simulation programmer):\n
    s - string, possible message for predecessor object\n
    i - int, message\n
    f - float, message\n
    Class variables (not important to simulation programmer):\n
    arr - Numeric array, holding serialised messages\n
    @cvar s: String message
    @type s: String
    @cvar i: Integer message
    @type i: Int
    @cvar f: Floating point message
    @type f: Float64
    @cvar arr: Serialised version of the message
    @type arr: Numeric array (28),'1'
    """
    def __init__(self,s="",i=0,f=0.0):
        """Initialise the fwdMsg with an optional string, integer and floating point number.\n
        Arguments:\n
        s - a string length less than 16.\n
        i - an integer number\n
        f - a floating point number (double)\n
        @param s: possible string message
        @type s: string
        @param i: possible int message
        @type i: int
        @param f: possible float message
        @type f: float
        """
        if len(s)>16:
            print "fwdMsg string greater than 16 bytes",s,i,f
            raise "ERROR: fwdMsg string greater than 16 bytes."
        if type(s)!=types.StringType or type(i)!=types.IntType or type(f)!=types.FloatType:
            print "fwdMsg type error",s,i,f,type(s),type(i),type(f)
            raise "ERROR: wrong type for fwdMsg"
        self.s=s
        self.i=i
        self.f=f
        self.arr=Numeric.zeros((28,),"1")#byte array
        
    def toArray(self,arr=None):
        """Copy the stored string, int and float into a Numeric array.
        @param arr: None, or array to serialise into
        @type arr: None or Numeric array
        @return: The array used for serialising
        @rtype: Numeric array
        """
        if type(arr)==types.NoneType:
            arr=self.arr
        arr*=Numeric.array(0,"1")#memset(arr,0,sizeof(arr)...
        l=len(self.s)
        if l>16:
            l=16
            self.s=self.s[:16]
        arr[0:l]=self.s
        arr[16:20]=Numeric.array(self.i,"i").tostring()
        arr[20:28]=Numeric.array(self.f,"d").tostring()
        return arr

    def fromArray(self,arr=None):
        """Retrieve a string, int and float from a Numeric array.
        @param arr: The array to serialise from
        @type arr: Numeric array
        @return: None"""
        if type(arr)==types.NoneType:
            arr=self.arr
        self.f=Numeric.fromstring(arr[20:28],"d")[0]
        self.i=Numeric.fromstring(arr[16:20],"i")[0]
        self.s=arr[0:16].tostring().replace('\0','')#note, this means that the
        #users string cannot contain a '\0' (unless they don't use fromArray).
        
    def __repr__(self):
        """Print details of this class"""
        return "fwdMsg instance: %d, %g, '%s'\n"%(self.i,self.f,self.s)
        
