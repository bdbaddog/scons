import os
import re
import shutil
import sys
import time

from TestSCons import TestSCons


class Stat:
    def __init__(self, name, units, expression, convert=None):
        if convert is None:
            convert = lambda x: x
        self.name = name
        self.units = units
        self.expression = re.compile(expression)
        self.convert = convert


StatList = [
    Stat('memory-initial', 'kbytes',
         r'Memory before reading SConscript files:\s+(\d+)',
         convert=lambda s: int(s) // 1024),
    Stat('memory-prebuild', 'kbytes',
         r'Memory before building targets:\s+(\d+)',
         convert=lambda s: int(s) // 1024),
    Stat('memory-final', 'kbytes',
         r'Memory after building targets:\s+(\d+)',
         convert=lambda s: int(s) // 1024),

    Stat('time-sconscript', 'seconds',
         r'Total SConscript file execution time:\s+([\d.]+) seconds'),
    Stat('time-scons', 'seconds',
         r'Total SCons execution time:\s+([\d.]+) seconds'),
    Stat('time-commands', 'seconds',
         r'Total command execution time:\s+([\d.]+) seconds'),
    Stat('time-total', 'seconds',
         r'Total build time:\s+([\d.]+) seconds'),
]


class TimeSCons(TestSCons):
    """Class for timing SCons."""
    def __init__(self, *args, **kw):
        """
        In addition to normal TestSCons.TestSCons initialization,
        this enables verbose mode (which causes the command lines to
        be displayed in the output) and copies the contents of the
        directory containing the executing script to the temporary
        working directory.
        """
        self.variables = kw.get('variables')
        default_calibrate_variables = []
        if self.variables is not None:
            for variable, value in self.variables.items():
                value = os.environ.get(variable, value)
                try:
                    value = int(value)
                except ValueError:
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                    else:
                        default_calibrate_variables.append(variable)
                else:
                    default_calibrate_variables.append(variable)
                self.variables[variable] = value
            del kw['variables']
        calibrate_keyword_arg = kw.get('calibrate')
        if calibrate_keyword_arg is None:
            self.calibrate_variables = default_calibrate_variables
        else:
            self.calibrate_variables = calibrate_keyword_arg
            del kw['calibrate']

        self.calibrate = os.environ.get('TIMESCONS_CALIBRATE', '0') != '0'

        if 'verbose' not in kw and not self.calibrate:
            kw['verbose'] = True

        TestSCons.__init__(self, *args, **kw)

        # TODO(sgk):    better way to get the script dir than sys.argv[0]
        self.test_dir = os.path.dirname(sys.argv[0])
        test_name = os.path.basename(self.test_dir)

        if not os.path.isabs(self.test_dir):
            self.test_dir = os.path.join(self.orig_cwd, self.test_dir)
        self.copy_timing_configuration(self.test_dir, self.workpath())

    def main(self, *args, **kw):
        """
        The main entry point for standard execution of timings.

        This method run SCons three times:

          Once with the --help option, to have it exit after just reading
          the configuration.

          Once as a full build of all targets.

          Once again as a (presumably) null or up-to-date build of
          all targets.

        The elapsed time to execute each build is printed after
        it has finished.
        """
        if 'options' not in kw and self.variables:
            options = []
            for variable, value in self.variables.items():
                options.append('%s=%s' % (variable, value))
            kw['options'] = ' '.join(options)
        if self.calibrate:
            self.calibration(*args, **kw)
        else:
            self.uptime()
            self.startup(*args, **kw)
            self.full(*args, **kw)
            self.null(*args, **kw)

    def trace(self, graph, name, value, units, sort=None):
        fmt = "TRACE: graph=%s name=%s value=%s units=%s"
        line = fmt % (graph, name, value, units)
        if sort is not None:
          line = line + (' sort=%s' % sort)
        line = line + '\n'
        sys.stdout.write(line)
        sys.stdout.flush()

    def report_traces(self, trace, stats):
        self.trace('TimeSCons-elapsed',
                   trace,
                   self.elapsed_time(),
                   "seconds",
                   sort=0)
        for name, args in stats.items():
            self.trace(name, trace, **args)

    def uptime(self):
        try:
            fp = open('/proc/loadavg')
        except EnvironmentError:
            pass
        else:
            avg1, avg5, avg15 = fp.readline().split(" ")[:3]
            fp.close()
            self.trace('load-average',  'average1', avg1, 'processes')
            self.trace('load-average',  'average5', avg5, 'processes')
            self.trace('load-average',  'average15', avg15, 'processes')

    def collect_stats(self, input):
        result = {}
        for stat in StatList:
            m = stat.expression.search(input)
            if m:
                value = stat.convert(m.group(1))
                # The dict keys match the keyword= arguments
                # of the trace() method above so they can be
                # applied directly to that call.
                result[stat.name] = {'value':value, 'units':stat.units}
        return result

    def add_timing_options(self, kw, additional=None):
        """
        Add the necessary timings options to the kw['options'] value.
        """
        options = kw.get('options', '')
        if additional is not None:
            options += additional
        kw['options'] = options + ' --debug=memory,time'

    def startup(self, *args, **kw):
        """
        Runs scons with the --help option.

        This serves as a way to isolate just the amount of startup time
        spent reading up the configuration, since --help exits before any
        "real work" is done.
        """
        self.add_timing_options(kw, ' --help')
        # Ignore the exit status.  If the --help run dies, we just
        # won't report any statistics for it, but we can still execute
        # the full and null builds.
        kw['status'] = None
        self.run(*args, **kw)
        sys.stdout.write(self.stdout())
        stats = self.collect_stats(self.stdout())
        # Delete the time-commands, since no commands are ever
        # executed on the help run and it is (or should be) always 0.0.
        del stats['time-commands']
        self.report_traces('startup', stats)

    def full(self, *args, **kw):
        """
        Runs a full build of SCons.
        """
        self.add_timing_options(kw)
        self.run(*args, **kw)
        sys.stdout.write(self.stdout())
        stats = self.collect_stats(self.stdout())
        self.report_traces('full', stats)
        self.trace('full-memory', 'initial', **stats['memory-initial'])
        self.trace('full-memory', 'prebuild', **stats['memory-prebuild'])
        self.trace('full-memory', 'final', **stats['memory-final'])

    def calibration(self, *args, **kw):
        """
        Runs a full build of SCons, but only reports calibration
        information (the variable(s) that were set for this configuration,
        and the elapsed time to run.
        """
        self.add_timing_options(kw)
        self.run(*args, **kw)
        for variable in self.calibrate_variables:
            value = self.variables[variable]
            sys.stdout.write('VARIABLE: %s=%s\n' % (variable, value))
        sys.stdout.write('ELAPSED: %s\n' % self.elapsed_time())

    def null(self, *args, **kw):
        """
        Runs an up-to-date null build of SCons.
        """
        # TODO(sgk):  allow the caller to specify the target (argument)
        # that must be up-to-date.
        self.add_timing_options(kw)
        self.up_to_date(arguments='.', **kw)
        sys.stdout.write(self.stdout())
        stats = self.collect_stats(self.stdout())
        # time-commands should always be 0.0 on a null build, because
        # no commands should be executed.  Remove it from the stats
        # so we don't trace it, but only if it *is* 0 so that we'll
        # get some indication if a supposedly-null build actually does
        # build something.
        if float(stats['time-commands']['value']) == 0.0:
            del stats['time-commands']
        self.report_traces('null', stats)
        self.trace('null-memory', 'initial', **stats['memory-initial'])
        self.trace('null-memory', 'prebuild', **stats['memory-prebuild'])
        self.trace('null-memory', 'final', **stats['memory-final'])

    def elapsed_time(self):
        """
        Returns the elapsed time of the most recent command execution.
        """
        return self.endTime - self.startTime

    def run(self, *args, **kw):
        """
        Runs a single build command, capturing output in the specified file.

        Because this class is about timing SCons, we record the start
        and end times of the elapsed execution, and also add the
        --debug=memory and --debug=time options to have SCons report
        its own memory and timing statistics.
        """
        self.startTime = time.time()
        try:
            result = TestSCons.run(self, *args, **kw)
        finally:
            self.endTime = time.time()
        return result

    def copy_timing_configuration(self, source_dir, dest_dir):
        """
        Copies the timing configuration from the specified source_dir (the
        directory in which the controlling script lives) to the specified
        dest_dir (a temporary working directory).

        This ignores all files and directories that begin with the string
        'TimeSCons-', and all '.svn' subdirectories.
        """
        for root, dirs, files in os.walk(source_dir):
            if '.svn' in dirs:
                dirs.remove('.svn')
            dirs = [ d for d in dirs if not d.startswith('TimeSCons-') ]
            files = [ f for f in files if not f.startswith('TimeSCons-') ]
            for dirname in dirs:
                source = os.path.join(root, dirname)
                destination = source.replace(source_dir, dest_dir)
                os.mkdir(destination)
                if sys.platform != 'win32':
                    shutil.copystat(source, destination)
            for filename in files:
                source = os.path.join(root, filename)
                destination = source.replace(source_dir, dest_dir)
                shutil.copy2(source, destination)