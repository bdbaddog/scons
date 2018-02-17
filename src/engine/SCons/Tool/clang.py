# -*- coding: utf-8; -*-

"""SCons.Tool.clang

Tool-specific initialization for clang.

There normally shouldn't be any need to import this module directly.
It will usually be imported through the generic SCons.Tool.Tool()
selection method.

"""

#
# __COPYRIGHT__
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
# KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

# __revision__ = "__FILE__ __REVISION__ __DATE__ __DEVELOPER__"

# Based on SCons/Tool/gcc.py by Paweł Tomulik 2014 as a separate tool.
# Brought into the SCons mainline by Russel Winder 2017.

import os
import re
import subprocess
import sys

import SCons.Util
import SCons.Tool.cc
from SCons.Tool.clangCommon import get_clang_install_dirs


compilers = ['clang']

def generate(env):
    """Add Builders and construction variables for clang to an Environment."""
    SCons.Tool.cc.generate(env)
    
    if env['PLATFORM'] == 'win32':
        # we have msvc env setup so we want to us MSVC compatible clang-cl
        if 'msvc' in env['TOOLS']:
            compilers[0] = 'clang-cl'
            env['SHCCFLAGS'] = SCons.Util.CLVar('$CCFLAGS')
        else:
            if env['PLATFORM'] in ['cygwin', 'win32']:
                env['SHCCFLAGS'] = SCons.Util.CLVar('$CCFLAGS')
                # for static linking with cygwin env, we still need ar
                ar = SCons.Tool.find_program_path(env, 'ar', default_paths=get_clang_install_dirs(env['PLATFORM']))
                if ar:
                    ar_bin_dir = os.path.dirname(ar)
                    env.AppendENVPath('PATH', ar_bin_dir)
            else: # must be linux or linux like
                env['SHCCFLAGS'] = SCons.Util.CLVar('$CCFLAGS -fPIC')
            
        # Ensure that we have a proper path for clang
        clang = SCons.Tool.find_program_path(env, compilers[0], default_paths=get_clang_install_dirs(env['PLATFORM']))
        if clang:
            clang_bin_dir = os.path.dirname(clang)
            env.AppendENVPath('PATH', clang_bin_dir)
        
    env['CC'] = env.Detect(compilers) or 'clang'

    # determine compiler version
    if env['CC']:
        #pipe = SCons.Action._subproc(env, [env['CC'], '-dumpversion'],
        pipe = SCons.Action._subproc(env, [env['CC'], '--version'],
                                     stdin='devnull',
                                     stderr='devnull',
                                     stdout=subprocess.PIPE)
        if pipe.wait() != 0: return
        # clang -dumpversion is of no use
        line = pipe.stdout.readline()
        if sys.version_info[0] > 2:
            line = line.decode()
        match = re.search(r'clang +version +([0-9]+(?:\.[0-9]+)+)', line)
        if match:
            env['CCVERSION'] = match.group(1)

def exists(env):
    return env.Detect(compilers)

# Local Variables:
# tab-width:4
# indent-tabs-mode:nil
# End:
# vim: set expandtab tabstop=4 shiftwidth=4:
