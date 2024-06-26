# __COPYRIGHT__
#
# Benchmarks for testing various possible implementations
# of the is_Dict(), is_List() and is_String() functions in
# src/engine/SCons/Util.py.

import types
from collections import UserDict, UserList, UserString

DictType = dict
ListType = list
StringType = str


# The original implementations, pretty straightforward checks for the
# type of the object and whether it's an instance of the corresponding
# User* type.

def original_is_Dict(e):
    return isinstance(e, (dict, UserDict))

def original_is_List(e):
    return isinstance(e, (list, UserList))

def original_is_String(e):
    return isinstance(e, (str, UserString))


# New candidates that explicitly check for whether the object is an
# InstanceType before calling isinstance() on the corresponding User*
# type.
# InstanceType was only for old-style classes, so absent in Python 3
# this this is no different than the previous

def checkInstanceType_is_Dict(e):
    return isinstance(e, (dict, UserDict))

def checkInstanceType_is_List(e):
    return isinstance(e, (list, UserList))

def checkInstanceType_is_String(e):
    return isinstance(e, (str, UserString))


# Improved candidates that cache the type(e) result in a variable
# before doing any checks.

def cache_type_e_is_Dict(e):
    t = type(e)
    return t is dict or isinstance(e, UserDict)

def cache_type_e_is_List(e):
    t = type(e)
    return t is list or isinstance(e, UserList)

def cache_type_e_is_String(e):
    t = type(e)
    return t is str or isinstance(e, UserString)


# Improved candidates that cache the type(e) result in a variable
# before doing any checks, but using the global names for
# DictType, ListType and StringType.

def global_cache_type_e_is_Dict(e):
    t = type(e)
    return t is DictType or isinstance(e, UserDict)

def global_cache_type_e_is_List(e):
    t = type(e)
    return t is ListType or isinstance(e, UserList)

def global_cache_type_e_is_String(e):
    t = type(e)
    return t is StringType or isinstance(e, UserString)


# Alternative that uses a myType() function to map the User* objects
# to their corresponding underlying types.

instanceTypeMap = {
    UserDict : dict,
    UserList : list,
    UserString : str,
}

def myType(obj):
    t = type(obj)
    if t is types.InstanceType:
        t = instanceTypeMap.get(obj.__class__, t)
    return t

def myType_is_Dict(e):
    return myType(e) is dict

def myType_is_List(e):
    return myType(e) is list

def myType_is_String(e):
    return myType(e) is str




def Func01(obj):
    """original_is_String"""
    for i in IterationList:
        original_is_String(obj)

def Func02(obj):
    """original_is_List"""
    for i in IterationList:
        original_is_List(obj)

def Func03(obj):
    """original_is_Dict"""
    for i in IterationList:
        original_is_Dict(obj)

def Func04(obj):
    """checkInstanceType_is_String"""
    for i in IterationList:
        checkInstanceType_is_String(obj)

def Func05(obj):
    """checkInstanceType_is_List"""
    for i in IterationList:
        checkInstanceType_is_List(obj)

def Func06(obj):
    """checkInstanceType_is_Dict"""
    for i in IterationList:
        checkInstanceType_is_Dict(obj)

def Func07(obj):
    """cache_type_e_is_String"""
    for i in IterationList:
        cache_type_e_is_String(obj)

def Func08(obj):
    """cache_type_e_is_List"""
    for i in IterationList:
        cache_type_e_is_List(obj)

def Func09(obj):
    """cache_type_e_is_Dict"""
    for i in IterationList:
        cache_type_e_is_Dict(obj)

def Func10(obj):
    """global_cache_type_e_is_String"""
    for i in IterationList:
        global_cache_type_e_is_String(obj)

def Func11(obj):
    """global_cache_type_e_is_List"""
    for i in IterationList:
        global_cache_type_e_is_List(obj)

def Func12(obj):
    """global_cache_type_e_is_Dict"""
    for i in IterationList:
        global_cache_type_e_is_Dict(obj)

#def Func13(obj):
#    """myType_is_String"""
#    for i in IterationList:
#        myType_is_String(obj)
#
#def Func14(obj):
#    """myType_is_List"""
#    for i in IterationList:
#        myType_is_List(obj)
#
#def Func15(obj):
#    """myType_is_Dict"""
#    for i in IterationList:
#        myType_is_Dict(obj)



# Data to pass to the functions on each run.  Each entry is a
# three-element tuple:
#
#   (
#       "Label to print describing this data run",
#       ('positional', 'arguments'),
#       {'keyword' : 'arguments'},
#   ),

class A:
    pass

Data = [
    (
        "String",
        ('',),
        {},
    ),
    (
        "List",
        ([],),
        {},
    ),
    (
        "Dict",
        ({},),
        {},
    ),
    (
        "UserString",
        (UserString(''),),
        {},
    ),
    (
        "UserList",
        (UserList([]),),
        {},
    ),
    (
        "UserDict",
        (UserDict({}),),
        {},
    ),
    (
        "Object",
        (A(),),
        {},
    ),
]

# Local Variables:
# tab-width:4
# indent-tabs-mode:nil
# End:
# vim: set expandtab tabstop=4 shiftwidth=4:
