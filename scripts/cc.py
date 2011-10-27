#!/usr/bin/env python

__author__ = 'Adam R. Smith'
__license__ = 'Apache 2.0'

import argparse

import yaml
from uuid import uuid4

#
# WARNING - DO NOT IMPORT GEVENT OR PYON HERE. IMPORTS **MUST** BE DONE IN THE MAIN()
# DUE TO DAEMONIZATION.
#
# SEE: http://groups.google.com/group/gevent/browse_thread/thread/6223805ffcd5be22?pli=1
#

version = "2.0"     # TODO: extract this from the code once versioning is automated again
description = '''
pyon (ION capability container) v%s
''' % (version)

def setup_ipython():
    from IPython.config.loader import Config
    cfg = Config()
    shell_config = cfg.InteractiveShellEmbed
    shell_config.prompt_in1 = '><> '
    shell_config.prompt_in2 = '... '
    shell_config.prompt_out = '--> '
    shell_config.confirm_exit = False

    # First import the embeddable shell class
    from IPython.frontend.terminal.embed import InteractiveShellEmbed

    # Now create an instance of the embeddable shell. The first argument is a
    # string with options exactly as you would type them if you were starting
    # IPython at the system command line. Any parameters you want to define for
    # configuration can thus be specified here.
    ipshell = InteractiveShellEmbed(config=cfg,
                           banner1 = 'Dropping into IPython',
                           exit_msg = 'Leaving Interpreter, back to program.')

    ipshell('Pyon shell (ION R2)')

# From http://stackoverflow.com/questions/6037503/python-unflatten-dict/6037657#6037657
def unflatten(dictionary):
    resultDict = dict()
    for key, value in dictionary.iteritems():
        parts = key.split(".")
        d = resultDict
        for part in parts[:-1]:
            if part not in d:
                d[part] = dict()
            d = d[part]
        d[parts[-1]] = value
    return resultDict
    
def main(opts, *args, **kwargs):
    print 'Starting ION CC with options: ', opts
    from pyon.public import Container
    from pyon.container.cc import IContainerAgent
    from pyon.net.endpoint import RPCClient

    container = Container(*args, **kwargs)

    # start and wait for container to signal ready
    ready = container.start()
    ready.get()

    if opts.rel:
        client = RPCClient(node=container.node, name=container.name, iface=IContainerAgent)
        client.start_rel_from_url(opts.rel)

    if not opts.noshell and not opts.daemon:
        setup_ipython()
    else:
        container.serve_forever()

    container.stop()

def parse_args(tokens):
    """ Exploit yaml's spectacular type inference (and ensure consistency with config files) """
    args, kwargs = [], {}
    for token in tokens:
        token = token.lstrip('-')
        if '=' in token:
            key,val = token.split('=', 1)
            cfg = unflatten({key: yaml.load(val)})
            kwargs.update(cfg)
        else:
            args.append(yaml.load(token))

    return args, kwargs

if __name__ == '__main__':
    #proc_types = GreenProcessSupervisor.type_callables.keys()

    # NOTE: Resist the temptation to add manual parameters here! Most container config options
    # should be in the config file (pyon.yml), which can also be specified on the command-line via the extra args
    
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('-d', '--daemon', action='store_true')
    parser.add_argument('-n', '--noshell', action='store_true')
    parser.add_argument('-r', '--rel', type=str, help='Path to a rel file to launch.')
    parser.add_argument('-p', '--pidfile', type=str, help='PID file to use when --daemon specified. Defaults to cc-<rand>.pid')
    parser.add_argument('--version', action='version', version='pyon v%s' % (version))
    opts, extra = parser.parse_known_args()
    args, kwargs = parse_args(extra)

    if opts.daemon:
        # TODO: The daemonizing code may need to be moved inside the Container class (so it happens per-process)
        from daemon import DaemonContext
        from lockfile import FileLock

        #logg = open('hi.txt', 'w+')
        #slogg = open('hi2.txt', 'w+')

        # TODO: May need to generate a pidfile based on some parameter or cc name
        pidfile = opts.pidfile or 'cc-%s.pid' % str(uuid4())[0:4]
        with DaemonContext(pidfile=FileLock(pidfile)):#, stdout=logg, stderr=slogg):
            main(opts, *args, **kwargs)
    else:
        main(opts, *args, **kwargs)
    