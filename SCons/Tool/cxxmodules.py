#
# MIT License
#
# Copyright The SCons Foundation
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

"""Common support for C++20 modules.

C++20 modules require dependency information that is not knowable until
the module sources have been parsed: ``import foo;`` depends on a BMI
(Built Module Interface) produced by compiling whichever source contains
``export module foo;``.  Neither the module name nor the producing source
can be determined from a filename.

Rather than parse C++ ourselves, we ask the compiler.  All three major
toolchains emit the same JSON dependency format, P1689R5:

    GCC    -fdeps-format=p1689r5 -fdeps-file=FILE
    Clang  clang-scan-deps -format=p1689
    MSVC   /scanDependencies FILE

This module holds the compiler-independent half of the implementation:
parsing that JSON, collating the results into a module-name -> BMI map,
and computing the transitive closure each translation unit needs.  The
per-compiler flag spellings live in the individual tool modules, in the
same way the Fortran module flags do (see gfortran.py, ifort.py).

BMI files are named after the *source file*, never the module name.
Module names are only known after scanning, but SCons emitters run while
the SConscript is read and cannot see file contents.  Deriving BMI paths
from source paths keeps every target knowable at that point.
"""

from __future__ import annotations

import json
import os.path

import SCons.Errors
import SCons.Util

#: Source suffixes that are treated as C++ module interface units.
#:
#: Deliberately kept separate from ``SCons.Tool.cxx.CXXSuffixes``: that
#: list is imported directly by other tools (compilation_db.py) and is
#: duplicated in msvc.py and mwcc.py, so extending it in place would
#: change behaviour for projects that do not use modules at all.
CXXModuleSuffixes = ['.cppm', '.ixx', '.cxxm', '.c++m', '.mpp']

#: Suffix for the P1689 dependency-info files produced by the scan step.
CXXModuleDepSuffix = '.ddi'

#: ``lookup-method`` values that denote a header unit rather than a
#: named module.  Header units are not supported yet; seeing one of
#: these is an error rather than something we silently get wrong.
HEADER_UNIT_LOOKUP_METHODS = ('include-angle', 'include-quote')


class P1689Error(SCons.Errors.UserError):
    """Raised when a P1689 dependency file cannot be used."""


class ModuleInfo:
    """What one translation unit provides and requires.

    Built from a single rule in a P1689 file.  ``provides`` and
    ``requires`` hold module logical names; ``source`` is the scanned
    source file the rule describes.
    """

    __slots__ = ('source', 'provides', 'requires', 'interface_names')

    def __init__(self, source, provides=None, requires=None,
                 interface_names=None) -> None:
        self.source = source
        self.provides = provides if provides is not None else []
        self.requires = requires if requires is not None else []
        # Subset of provides that are interface units (is-interface true).
        # Only these produce a BMI other translation units can consume.
        self.interface_names = (
            interface_names if interface_names is not None else []
        )

    def __repr__(self) -> str:
        return (
            f"ModuleInfo(source={self.source!r}, "
            f"provides={self.provides!r}, requires={self.requires!r})"
        )


def _module_names(entries, kind, path, skip_header_units: bool = False):
    """Pull logical names out of a P1689 ``provides``/``requires`` array.

    *entries* is the raw list from the JSON, *kind* is ``"provides"`` or
    ``"requires"`` (used only for error messages), and *path* is the file
    the data came from.

    ``logical-name`` is the only field P1689R5 requires, so it is the only
    one we insist on.  Everything else may legitimately be missing, and
    the three compilers differ in what they choose to emit.

    Header units are detected here via ``lookup-method``.  They are not
    supported yet, so rather than resolve them to something wrong we raise
    with a message naming the header.
    """
    names = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise P1689Error(
                f"{path}: malformed {kind} entry (expected an object, "
                f"got {type(entry).__name__})"
            )

        lookup = entry.get('lookup-method', 'by-name')
        if lookup in HEADER_UNIT_LOOKUP_METHODS:
            if skip_header_units:
                continue
            name = entry.get('logical-name', '<unknown>')
            raise P1689Error(
                f"{path}: C++20 header units are not supported "
                f"(found 'import {name};' with lookup-method "
                f"'{lookup}').  Only named modules are supported."
            )

        try:
            name = entry['logical-name']
        except KeyError:
            raise P1689Error(
                f"{path}: {kind} entry is missing the required "
                f"'logical-name' field"
            ) from None
        names.append(name)
    return names


def parse_p1689(path, contents=None, source=None):
    """Parse a P1689R5 dependency file into a list of ``ModuleInfo``.

    *path* names the file (used in diagnostics); *contents* may be
    supplied directly to avoid a read, which is what the unit tests do.
    *source* is the source file that was scanned.

    Pass *source* whenever it is known.  ``source-path`` is optional in
    P1689R5 and the compilers disagree about it: Clang emits it, GCC
    does not and reports only ``primary-output`` (an object file name).
    Since BMI paths are derived from the source file name, taking the
    source from the .ddi would make BMI names depend on which compiler
    produced it.  SCons always knows which source it scanned, so it
    supplies the name rather than trusting the file.

    The schema is defined by
    https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2022/p1689r5.html
    Only ``version`` and ``rules`` are required at the top level, and
    within a module description only ``logical-name``.  We read
    ``is-interface`` (default true) to tell interface units from
    implementation units, and ignore ``compiled-module-path`` entirely:
    SCons decides where BMIs live, because not every compiler populates
    that field.
    """
    if contents is None:
        try:
            with open(path, encoding='utf-8') as f:
                contents = f.read()
        except OSError as e:
            raise P1689Error(f"could not read {path}: {e}") from None

    try:
        data = json.loads(contents)
    except ValueError as e:
        raise P1689Error(f"{path}: not valid JSON: {e}") from None

    if not isinstance(data, dict):
        raise P1689Error(
            f"{path}: expected a JSON object at the top level, "
            f"got {type(data).__name__}"
        )

    if 'version' not in data:
        raise P1689Error(f"{path}: missing required 'version' field")

    try:
        rules = data['rules']
    except KeyError:
        raise P1689Error(f"{path}: missing required 'rules' field") from None

    if not SCons.Util.is_List(rules):
        raise P1689Error(f"{path}: 'rules' must be an array")

    infos = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise P1689Error(
                f"{path}: malformed rule (expected an object, "
                f"got {type(rule).__name__})"
            )

        provides_raw = rule.get('provides', [])
        requires_raw = rule.get('requires', [])

        provides = _module_names(provides_raw, 'provides', path)
        requires = _module_names(requires_raw, 'requires', path)

        # is-interface defaults to true per P1689R5.  Only interface
        # units yield a BMI that other TUs can import.
        interface_names = [
            e['logical-name'] for e in provides_raw
            if isinstance(e, dict)
            and 'logical-name' in e
            and e.get('is-interface', True)
        ]

        rule_source = source
        if rule_source is None:
            # No explicit source: fall back to what the file says.
            rule_source = rule.get('primary-output')
            for entry in provides_raw:
                if isinstance(entry, dict) and entry.get('source-path'):
                    rule_source = entry['source-path']
                    break

        infos.append(
            ModuleInfo(rule_source, provides, requires, interface_names)
        )

    return infos


def bmi_name(source, suffix: str = '.pcm', moddir: str = '') -> str:
    """Return the BMI path for a module source file.

    Named after the *source file*, not the module it exports.  Module
    names are only known once scanning has run, but emitters run while
    the SConscript is read; deriving the name from the source path keeps
    BMI targets knowable at that point.  It also means two modules can
    never collide on a BMI path just because of how they are named.
    """
    base = os.path.splitext(os.path.basename(str(source)))[0]
    return os.path.join(moddir, base + suffix) if moddir else base + suffix


def collate(infos, suffix: str = '.pcm', moddir: str = ''):
    """Build the module map from parsed P1689 results.

    Returns ``(provided_by, required_by)``:

    * ``provided_by`` maps a module logical name to the BMI path that
      compiling its source will produce.
    * ``required_by`` maps a source path to the module names that source
      imports directly.

    Raises on a module exported by two different sources, which would
    otherwise produce a build that succeeds non-deterministically
    depending on which compile ran last.
    """
    provided_by = {}
    required_by = {}
    origin = {}

    for info in infos:
        if info.interface_names and info.source is None:
            # logical-name is the only field P1689R5 requires, so a
            # conforming file can name a module without saying which
            # source defines it.  We cannot place a BMI without that, and
            # guessing would produce a silently wrong build.
            raise P1689Error(
                f"module(s) {', '.join(info.interface_names)} are exported "
                f"by a rule with no 'source-path' or 'primary-output'; "
                f"cannot determine where to write the BMI"
            )
        for name in info.interface_names:
            bmi = bmi_name(info.source, suffix, moddir)
            if name in provided_by and origin.get(name) != info.source:
                raise P1689Error(
                    f"module '{name}' is exported by more than one source: "
                    f"{origin[name]} and {info.source}"
                )
            provided_by[name] = bmi
            origin[name] = info.source
        if info.source is not None:
            required_by[info.source] = list(info.requires)

    return provided_by, required_by


def find_cycle(required_by, provider_source):
    """Return a module-name cycle if the import graph has one, else None.

    SCons detects dependency cycles only after the taskmaster walk stalls
    (Taskmaster.cleanup), and reports them as a list of file nodes.  For
    modules that is a poor diagnostic: the user wrote ``import``
    statements, so the error should name modules.  Detecting it here, at
    collation time, lets us say something useful before the build starts.

    *required_by* maps source -> imported module names; *provider_source*
    maps module name -> the source that exports it.
    """
    # Build a module-name graph: module -> modules its source imports.
    graph = {}
    for name, source in provider_source.items():
        graph[name] = [
            req for req in required_by.get(source, [])
            if req in provider_source
        ]

    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(graph, WHITE)

    def visit(node, stack):
        colour[node] = GREY
        stack.append(node)
        for nxt in graph.get(node, []):
            if colour.get(nxt, BLACK) == GREY:
                # Found a back edge: slice the cycle out of the stack.
                return stack[stack.index(nxt):] + [nxt]
            if colour.get(nxt, BLACK) == WHITE:
                found = visit(nxt, stack)
                if found:
                    return found
        stack.pop()
        colour[node] = BLACK
        return None

    for node in graph:
        if colour[node] == WHITE:
            found = visit(node, [])
            if found:
                return found
    return None


def transitive_closure(source, required_by, provided_by, provider_source):
    """Return every BMI *source* needs, directly or indirectly.

    GCC resolves transitive imports itself, but Clang and MSVC require
    every transitively-imported BMI to be named on the command line.
    Passing the full closure is correct for all three -- GCC tolerates the
    redundancy -- so we compute it once rather than per compiler.

    Returns BMI paths in a deterministic (sorted) order so command lines
    are stable between runs and do not cause needless rebuilds.
    """
    seen = set()
    stack = list(required_by.get(source, []))

    while stack:
        name = stack.pop()
        if name in seen or name not in provided_by:
            continue
        seen.add(name)
        nxt = provider_source.get(name)
        if nxt is not None:
            stack.extend(required_by.get(nxt, []))

    return sorted(provided_by[name] for name in seen)


def _read_module_map(env):
    """Return the collated module map, computing it once per environment.

    The map is built from every ``.ddi`` the scan step has produced.  It is
    cached on the Environment because ``$_CXXMODULEFLAGS`` expands once per
    translation unit and re-collating for each would be wasteful.
    """
    cache = env.get('_CXXMODULE_MAP_CACHE')
    if cache is not None:
        return cache

    ddi_nodes = env.get('_CXXMODULE_DDI_NODES', [])
    suffix = env.subst('$CXXMODULESUFFIX')
    moddir = env.subst('$CXXMODULEDIR')

    infos = []
    for node in ddi_nodes:
        path = str(node)
        if not os.path.exists(path):
            # Scan has not run yet for this TU.  Not an error: the flags
            # are substituted again once the .ddi exists.
            continue
        # The .ddi node records the source it was scanned from, so BMI
        # names stay independent of what the compiler chose to report.
        src = getattr(node.attributes, 'cxxmodule_source', None)
        infos.extend(parse_p1689(path, source=src))

    provided_by, required_by = collate(infos, suffix, moddir)

    provider_source = {}
    for info in infos:
        for name in info.interface_names:
            provider_source[name] = info.source

    cycle = find_cycle(required_by, provider_source)
    if cycle is not None:
        raise P1689Error(
            "circular module dependency: " + " -> ".join(cycle)
        )

    cache = (provided_by, required_by, provider_source)
    env['_CXXMODULE_MAP_CACHE'] = cache
    return cache


def _cxxmodule_flags(source, target, env, for_signature):
    """Generate the BMI flags a translation unit needs.

    Emits one ``$CXXMODULEFLAGPREFIX`` per BMI in the transitive closure.
    Clang and MSVC require the full closure; GCC resolves transitive
    imports itself but tolerates being told, so one code path serves all
    three.
    """
    if not source:
        return []

    try:
        provided_by, required_by, provider_source = _read_module_map(env)
    except P1689Error:
        if for_signature:
            # During signature calculation a missing/incomplete scan is
            # expected; the real error surfaces when the action runs.
            return []
        raise

    src = str(source[0])
    bmis = transitive_closure(src, required_by, provided_by, provider_source)

    prefix = env.subst('$CXXMODULEFLAGPREFIX')
    return [prefix + bmi for bmi in bmis]


def generate(env) -> None:
    """Add C++20 module construction variables to *env*.

    Only the compiler-independent defaults live here.  Each compiler tool
    overrides the spellings it needs, in the same way gfortran.py and
    ifort.py override the Fortran module flags.
    """
    env['CXXMODULESUFFIX'] = '.pcm'
    env['CXXMODULEDEPSUFFIX'] = CXXModuleDepSuffix
    env['CXXMODULEDIR'] = ''
    env['CXXMODULEFLAGPREFIX'] = '-fmodule-file='
    env['CXXMODULEOUTPUTFLAG'] = '-fmodule-output='
    # Language standard used for the scan step.  Modules require at
    # least C++20; the scan must agree with the eventual compile or the
    # compiler may report different imports than it later honours.
    env['CXXMODULESTD'] = 'c++20'
    env['CXXMODULESCANFLAGS'] = SCons.Util.CLVar('')
    # Sink for scan output we do not want (see gxx.py's -MF).
    env['CXXMODULESCANDEVNULL'] = os.devnull
    env['_CXXMODULEFLAGS'] = _cxxmodule_flags
    # Plain assignment rather than SetDefault: generate() must work with
    # the minimal dict-like environments used in the tool unit tests.
    if 'CXXMODULESUFFIXES' not in env:
        env['CXXMODULESUFFIXES'] = list(CXXModuleSuffixes)


def exists(env) -> bool:
    """C++20 module support needs no tool of its own."""
    return True
