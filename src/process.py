"""
Created on Sat Aug 12 2017

@author: yboetz

Catch ZFS subprocess errors, forked from https://bitbucket.org/stevedrake/weir/
"""

import re
import shutil
import errno as _errno
import subprocess as sp
import socket

PIPE = sp.PIPE


class ZFSError(OSError):
    def __init__(self, dataset):
        super(ZFSError, self).__init__(self.errno, self.strerror, dataset)

class DatasetNotFoundError(ZFSError):
    errno = _errno.ENOENT
    strerror = 'dataset does not exist'

class DatasetExistsError(ZFSError):
    errno = _errno.EEXIST
    strerror = 'dataset already exists'

class DatasetBusyError(ZFSError):
    errno = _errno.EBUSY
    strerror = 'dataset is busy'

class HoldTagNotFoundError(ZFSError):
    errno = _errno.ENOENT
    strerror = 'no such tag on this dataset'

class HoldTagExistsError(ZFSError):
    errno = _errno.EEXIST
    strerror = 'tag already exists on this dataset'

class CompletedProcess(sp.CompletedProcess):
    def check_returncode(self):
        # check for known errors of form "cannot <action> <dataset>: <reason>"
        if self.returncode == 1:
            pattern = r"^cannot ([^ ]+(?: [^ ]+)*?) ([^ ]+): (.+)$"
            match = re.search(pattern, self.stderr)
            if match:
                _, dataset, reason = match.groups()
                if dataset[0] == dataset[-1] == "'":
                    dataset = dataset[1:-1]
                for error in (DatasetNotFoundError,
                              DatasetExistsError,
                              DatasetBusyError,
                              HoldTagNotFoundError,
                              HoldTagExistsError):
                    if reason == error.strerror:
                        raise error(dataset)

        # did not match known errors, defer to superclass
        super(CompletedProcess, self).check_returncode()


# ssh is a connected instance of paramiko.client.SSHClient
def check_output(*popenargs, timeout=None, ssh=None, **kwargs):
    """check_output for zfs commands. Catches some errors if
    returncode is not 0."""

    if 'stdout' in kwargs:
        raise ValueError('stdout argument not allowed, it will be overridden.')
    if 'universal_newlines' in kwargs:
        raise ValueError('universal_newlines argument not allowed, it will be overridden.')
    
    if 'input' in kwargs and kwargs['input'] is None:
    # Explicitly passing input=None was previously equivalent to passing an
    # empty string. That is maintained here for backwards compatibility.
        kwargs['input'] = '' if kwargs.get('universal_newlines', False) else b''

    ret = sp.run(*popenargs, stdout=PIPE, stderr=PIPE, timeout=timeout,
                 universal_newlines=True, ssh=ssh, **kwargs)
    ret.check_returncode()
    out = ret.stdout

    return None if out is None else [line.split('\t') for line in out.splitlines()]


def run(*popenargs, timeout=None, check=False, ssh=None, **kwargs):
    """Run command for ZFS functions that also works over ssh."""

    if ssh is None:
        with sp.Popen(*popenargs, **kwargs) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except sp.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                raise sp.TimeoutExpired(process.args, timeout, output=stdout, stderr=stderr)
            except:
                process.kill()
                process.wait()
                raise
            retcode = process.poll()
            if check and retcode:
                raise sp.CalledProcessError(retcode, process.args, output=stdout, stderr=stderr)
    else:
        args = ' '.join(popenargs[0]) if not isinstance(popenargs[0], str) else popenargs[0]

        try:
            stdin, stdout, stderr = ssh.exec_command(args, *popenargs[1:], timeout=timeout)
            if kwargs.get('stdin', None):
                shutil.copyfileobj(kwargs['stdin'], stdin, 128*1024)
            stdin.close()
            retcode = stdout.channel.recv_exit_status()
            stdout, stderr = ''.join(stdout.readlines()), ''.join(stderr.readlines())
        except socket.timeout:
            stdout, stderr, retcode = None, None, 1
            raise sp.TimeoutExpired(popenargs[0], timeout, output=stdout, stderr=stderr)

        if check and retcode:
            raise sp.CalledProcessError(retcode, popenargs[0], output=stdout, stderr=stderr)

    return sp.CompletedProcess(popenargs[0], retcode, stdout, stderr)


sp.CompletedProcess = CompletedProcess
sp.run = run
sp.check_output = check_output
