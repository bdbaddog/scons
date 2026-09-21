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

"""Unit tests for C++20 modules P1689 handling."""

import json
import os.path
import unittest

from SCons.Tool.cxxmodules import (
    P1689Error,
    bmi_name,
    check_scan_usable,
    collate,
    find_cycle,
    parse_p1689,
    scanner_available,
    transitive_closure,
)


def ddi(rules, version: int = 1) -> str:
    """Build a P1689 document as a JSON string."""
    return json.dumps({"version": version, "rules": rules})


class ParseP1689TestCase(unittest.TestCase):
    def test_minimal_document(self) -> None:
        """A document with no rules content still parses."""
        infos = parse_p1689('t.ddi', ddi([]))
        self.assertEqual(infos, [])

    def test_provides_and_requires(self) -> None:
        infos = parse_p1689('t.ddi', ddi([{
            "primary-output": "b.o",
            "provides": [{"logical-name": "B", "source-path": "b.cppm"}],
            "requires": [{"logical-name": "A"}],
        }]))
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].provides, ["B"])
        self.assertEqual(infos[0].requires, ["A"])
        self.assertEqual(infos[0].source, "b.cppm")

    def test_source_path_preferred_over_primary_output(self) -> None:
        """source-path names the source; primary-output names the object."""
        infos = parse_p1689('t.ddi', ddi([{
            "primary-output": "obj/b.o",
            "provides": [{"logical-name": "B", "source-path": "src/b.cppm"}],
        }]))
        self.assertEqual(infos[0].source, "src/b.cppm")

    def test_is_interface_defaults_true(self) -> None:
        """P1689R5 says is-interface defaults to true when absent."""
        infos = parse_p1689('t.ddi', ddi([{
            "primary-output": "a.o",
            "provides": [{"logical-name": "A", "source-path": "a.cppm"}],
        }]))
        self.assertEqual(infos[0].interface_names, ["A"])

    def test_is_interface_false_excluded(self) -> None:
        """Implementation units provide no importable BMI."""
        infos = parse_p1689('t.ddi', ddi([{
            "primary-output": "p.o",
            "provides": [{
                "logical-name": "A:impl",
                "source-path": "p.cppm",
                "is-interface": False,
            }],
        }]))
        self.assertEqual(infos[0].provides, ["A:impl"])
        self.assertEqual(infos[0].interface_names, [])

    def test_optional_fields_may_be_absent(self) -> None:
        """logical-name is the only required module-description field."""
        infos = parse_p1689('t.ddi', ddi([{
            "provides": [{"logical-name": "M"}],
            "requires": [{"logical-name": "N"}],
        }]))
        self.assertEqual(infos[0].provides, ["M"])
        self.assertEqual(infos[0].requires, ["N"])

    def test_revision_optional(self) -> None:
        doc = json.dumps({"version": 1, "revision": 0, "rules": []})
        self.assertEqual(parse_p1689('t.ddi', doc), [])

    def test_missing_version_rejected(self) -> None:
        with self.assertRaises(P1689Error):
            parse_p1689('t.ddi', json.dumps({"rules": []}))

    def test_missing_rules_rejected(self) -> None:
        with self.assertRaises(P1689Error):
            parse_p1689('t.ddi', json.dumps({"version": 1}))

    def test_invalid_json_rejected(self) -> None:
        with self.assertRaises(P1689Error):
            parse_p1689('t.ddi', '{not json')

    def test_missing_logical_name_rejected(self) -> None:
        with self.assertRaises(P1689Error):
            parse_p1689('t.ddi', ddi([{"requires": [{"source-path": "x"}]}]))

    def test_header_unit_angle_rejected(self) -> None:
        """Header units are unsupported: fail loudly, never silently."""
        with self.assertRaises(P1689Error) as cm:
            parse_p1689('t.ddi', ddi([{
                "primary-output": "m.o",
                "requires": [{
                    "logical-name": "vector",
                    "lookup-method": "include-angle",
                }],
            }]))
        self.assertIn('header units are not supported', str(cm.exception))
        self.assertIn('vector', str(cm.exception))

    def test_header_unit_quote_rejected(self) -> None:
        with self.assertRaises(P1689Error):
            parse_p1689('t.ddi', ddi([{
                "requires": [{
                    "logical-name": "my.h",
                    "lookup-method": "include-quote",
                }],
            }]))

    def test_by_name_lookup_accepted(self) -> None:
        """by-name is the default and denotes a named module."""
        infos = parse_p1689('t.ddi', ddi([{
            "requires": [{"logical-name": "A", "lookup-method": "by-name"}],
        }]))
        self.assertEqual(infos[0].requires, ["A"])


class RealCompilerOutputTestCase(unittest.TestCase):
    """Documents how actual compiler output differs from the examples.

    Verified against GCC 15.2.0 and the clang-scan-deps documentation.
    The compilers disagree about which optional fields they emit, so
    these guard the portability assumptions the rest of the code makes.
    """

    # Verbatim from g++-15 -fdeps-format=p1689r5.  Note: no source-path
    # anywhere, primary-output is an object name, and version is 0.
    GCC_OUTPUT = """{
    "rules": [
    {
    "primary-output": "a-b.o",
    "provides": [
    {
    "logical-name": "B",
    "is-interface": true
    }
    ],
    "requires": [
    {
    "logical-name": "A"
    }
    ]
    }
    ],
    "version": 0,
    "revision": 0
    }"""

    def test_gcc_output_parses(self) -> None:
        infos = parse_p1689('b.ddi', self.GCC_OUTPUT)
        self.assertEqual(infos[0].provides, ["B"])
        self.assertEqual(infos[0].requires, ["A"])

    def test_gcc_version_zero_accepted(self) -> None:
        """GCC reports version 0; only presence is required."""
        self.assertTrue(parse_p1689('b.ddi', self.GCC_OUTPUT))

    def test_explicit_source_overrides_primary_output(self) -> None:
        """BMI names must not depend on the compiler's object naming.

        Without an explicit source, GCC's output would yield a BMI named
        after 'a-b.o'.  SCons knows the real source and supplies it.
        """
        infos = parse_p1689('b.ddi', self.GCC_OUTPUT, source='b.cppm')
        self.assertEqual(infos[0].source, 'b.cppm')
        provided, _ = collate(infos, suffix='.gcm')
        self.assertEqual(provided, {"B": "b.gcm"})

    def test_without_explicit_source_falls_back(self) -> None:
        infos = parse_p1689('b.ddi', self.GCC_OUTPUT)
        self.assertEqual(infos[0].source, 'a-b.o')

    def test_clang_style_source_path_used(self) -> None:
        """Clang does emit source-path; it is honoured when present."""
        doc = ddi([{
            "primary-output": "M.o",
            "provides": [{
                "is-interface": True,
                "logical-name": "M",
                "source-path": "M.cppm",
            }],
        }])
        infos = parse_p1689('m.ddi', doc)
        self.assertEqual(infos[0].source, 'M.cppm')


class BmiNameTestCase(unittest.TestCase):
    def test_derived_from_source_not_module(self) -> None:
        self.assertEqual(bmi_name('a.cppm', '.pcm'), 'a.pcm')
        self.assertEqual(bmi_name('src/a.ixx', '.ifc'), 'a.ifc')

    def test_moddir_applied(self) -> None:
        self.assertEqual(
            bmi_name('src/a.cppm', '.gcm', 'bmi'),
            os.path.join('bmi', 'a.gcm'),
        )


class BrokenScannerTestCase(unittest.TestCase):
    """GCC 14's scanner reports nothing; that must not pass silently."""

    # Verbatim from g++-mp-14 (MacPorts GCC 14.3.0) scanning a file
    # that contains 'export module stats;' and 'import math;'.
    GCC14_OUTPUT = """{
    "rules": [
    {
    "primary-output": "stats.o",
    "requires": [
    ]
    }
    ],
    "version": 0,
    "revision": 0
    }"""

    def test_gcc14_output_has_nothing(self) -> None:
        """Document the actual broken output: no provides, no requires."""
        infos = parse_p1689('stats.ddi', self.GCC14_OUTPUT,
                            source='stats.cppm')
        self.assertEqual(infos[0].provides, [])
        self.assertEqual(infos[0].requires, [])

    def test_empty_scan_rejected(self) -> None:
        infos = parse_p1689('stats.ddi', self.GCC14_OUTPUT,
                            source='stats.cppm')
        with self.assertRaises(P1689Error) as cm:
            check_scan_usable(infos, ['stats.cppm'])
        msg = str(cm.exception)
        self.assertIn('no modules at all', msg)
        self.assertIn('GCC 15', msg)

    def test_empty_scan_would_yield_empty_map(self) -> None:
        """Without the guard this silently produces no ordering."""
        infos = parse_p1689('stats.ddi', self.GCC14_OUTPUT,
                            source='stats.cppm')
        provided, _ = collate(infos)
        self.assertEqual(provided, {})

    def test_no_infos_is_not_an_error(self) -> None:
        """Nothing scanned at all is a different situation."""
        check_scan_usable([])

    def test_working_scan_accepted(self) -> None:
        infos = parse_p1689('t.ddi', ddi([{
            "primary-output": "a.o",
            "provides": [{"logical-name": "A", "source-path": "a.cppm"}],
        }]))
        check_scan_usable(infos, ['a.cppm'])

    def test_consumer_only_scan_accepted(self) -> None:
        """A TU that only imports is still evidence the scanner works."""
        infos = parse_p1689('t.ddi', ddi([{
            "primary-output": "main.o",
            "requires": [{"logical-name": "A"}],
        }]))
        check_scan_usable(infos, ['main.cpp'])


class CollateTestCase(unittest.TestCase):
    def test_maps_module_to_bmi(self) -> None:
        infos = parse_p1689('t.ddi', ddi([
            {"primary-output": "a.o",
             "provides": [{"logical-name": "A", "source-path": "a.cppm"}]},
            {"primary-output": "b.o",
             "provides": [{"logical-name": "B", "source-path": "b.cppm"}],
             "requires": [{"logical-name": "A"}]},
        ]))
        provided, required = collate(infos, suffix='.pcm')
        self.assertEqual(provided, {"A": "a.pcm", "B": "b.pcm"})
        self.assertEqual(required["b.cppm"], ["A"])

    def test_duplicate_export_rejected(self) -> None:
        infos = parse_p1689('t.ddi', ddi([
            {"provides": [{"logical-name": "A", "source-path": "a.cppm"}]},
            {"provides": [{"logical-name": "A", "source-path": "c.cppm"}]},
        ]))
        with self.assertRaises(P1689Error) as cm:
            collate(infos)
        self.assertIn("exported by more than one source", str(cm.exception))

    def test_export_without_source_rejected(self) -> None:
        """Cannot place a BMI when the rule never names its source."""
        infos = parse_p1689('t.ddi', ddi([{"provides": [{"logical-name": "M"}]}]))
        with self.assertRaises(P1689Error) as cm:
            collate(infos)
        self.assertIn("cannot determine where to write the BMI",
                      str(cm.exception))

    def test_rule_without_provides_needs_no_source(self) -> None:
        """A consumer-only rule with no source is harmless."""
        infos = parse_p1689('t.ddi', ddi([{"requires": [{"logical-name": "M"}]}]))
        provided, _ = collate(infos)
        self.assertEqual(provided, {})


class TransitiveClosureTestCase(unittest.TestCase):
    """Clang and MSVC need every transitive BMI named explicitly."""

    def setUp(self) -> None:
        self.provided = {"A": "a.pcm", "B": "b.pcm", "C": "c.pcm"}
        self.provider_source = {
            "A": "a.cppm", "B": "b.cppm", "C": "c.cppm",
        }
        # C imports B, B imports A, main imports C only.
        self.required = {
            "a.cppm": [],
            "b.cppm": ["A"],
            "c.cppm": ["B"],
            "main.cpp": ["C"],
        }

    def test_direct_import(self) -> None:
        self.assertEqual(
            transitive_closure("b.cppm", self.required, self.provided,
                               self.provider_source),
            ["a.pcm"],
        )

    def test_indirect_imports_included(self) -> None:
        """main imports only C, but needs A and B's BMIs too."""
        self.assertEqual(
            transitive_closure("main.cpp", self.required, self.provided,
                               self.provider_source),
            ["a.pcm", "b.pcm", "c.pcm"],
        )

    def test_no_imports(self) -> None:
        self.assertEqual(
            transitive_closure("a.cppm", self.required, self.provided,
                               self.provider_source),
            [],
        )

    def test_result_is_sorted(self) -> None:
        """Stable ordering keeps command lines from churning."""
        result = transitive_closure("main.cpp", self.required, self.provided,
                                    self.provider_source)
        self.assertEqual(result, sorted(result))

    def test_unknown_module_ignored(self) -> None:
        """An import with no known provider contributes no BMI."""
        required = {"main.cpp": ["Nonexistent"]}
        self.assertEqual(
            transitive_closure("main.cpp", required, self.provided,
                               self.provider_source),
            [],
        )

    def test_diamond_yields_no_duplicates(self) -> None:
        required = {
            "a.cppm": [],
            "b.cppm": ["A"],
            "c.cppm": ["A"],
            "main.cpp": ["B", "C"],
        }
        self.assertEqual(
            transitive_closure("main.cpp", required, self.provided,
                               self.provider_source),
            ["a.pcm", "b.pcm", "c.pcm"],
        )


class ScannerAvailableTestCase(unittest.TestCase):
    """Clang needs a separate clang-scan-deps binary that may be absent."""

    class FakeEnv(dict):
        def __init__(self, found=None, **kw) -> None:
            super().__init__(**kw)
            self._found = found

        def WhereIs(self, prog):
            return self._found

    def test_missing_scan_binary(self) -> None:
        env = self.FakeEnv(found=None, CXXMODULESCAN='clang-scan-deps')
        self.assertFalse(scanner_available(env))

    def test_present_scan_binary(self) -> None:
        env = self.FakeEnv(found='/usr/bin/clang-scan-deps',
                           CXXMODULESCAN='clang-scan-deps')
        self.assertTrue(scanner_available(env))

    def test_absolute_path_accepted(self) -> None:
        """An explicit absolute path need not be on PATH."""
        env = self.FakeEnv(found=None,
                           CXXMODULESCAN='/opt/llvm/bin/clang-scan-deps')
        self.assertTrue(scanner_available(env))

    def test_driver_based_scan(self) -> None:
        """GCC and MSVC scan with the compiler itself, not a separate tool."""
        env = self.FakeEnv(found=None, CXXMODULESCANCOM='$CXX -fdeps-format=...')
        self.assertTrue(scanner_available(env))

    def test_nothing_configured(self) -> None:
        self.assertFalse(scanner_available(self.FakeEnv(found=None)))


class FindCycleTestCase(unittest.TestCase):
    """Report cycles as module names, before the taskmaster stalls."""

    def test_no_cycle(self) -> None:
        self.assertIsNone(
            find_cycle({"a.cppm": [], "b.cppm": ["A"]},
                       {"A": "a.cppm", "B": "b.cppm"})
        )

    def test_two_module_cycle(self) -> None:
        cycle = find_cycle({"a.cppm": ["B"], "b.cppm": ["A"]},
                           {"A": "a.cppm", "B": "b.cppm"})
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle[0], cycle[-1])
        self.assertIn("A", cycle)
        self.assertIn("B", cycle)

    def test_self_cycle(self) -> None:
        self.assertEqual(find_cycle({"a.cppm": ["A"]}, {"A": "a.cppm"}),
                         ["A", "A"])

    def test_three_module_cycle(self) -> None:
        cycle = find_cycle(
            {"a.cppm": ["B"], "b.cppm": ["C"], "c.cppm": ["A"]},
            {"A": "a.cppm", "B": "b.cppm", "C": "c.cppm"},
        )
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle[0], cycle[-1])

    def test_diamond_is_not_a_cycle(self) -> None:
        """A diamond DAG must not be mistaken for a cycle."""
        self.assertIsNone(find_cycle(
            {"a.cppm": [], "b.cppm": ["A"], "c.cppm": ["A"],
             "d.cppm": ["B", "C"]},
            {"A": "a.cppm", "B": "b.cppm", "C": "c.cppm", "D": "d.cppm"},
        ))


if __name__ == "__main__":
    unittest.main()
