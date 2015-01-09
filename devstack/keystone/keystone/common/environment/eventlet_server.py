# Copyright 2012 OpenStack Foundation
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import errno
import re
import socket
import ssl
import sys

import eventlet
import eventlet.wsgi
import greenlet

from keystone.i18n import _
from keystone.i18n import _LE
from keystone.i18n import _LI
from keystone.openstack.common import log


LOG = log.getLogger(__name__)


class EventletFilteringLogger(log.WritableLogger):
    # NOTE(morganfainberg): This logger is designed to filter out specific
    # Tracebacks to limit the amount of data that eventlet can log. In the
    # case of broken sockets (EPIPE and ECONNRESET), we are seeing a huge
    # volume of data being written to the logs due to ~14 lines+ per traceback.
    # The traceback in these cases are, at best, useful for limited debugging
    # cases.
    def __init__(self, *args, **kwargs):
        super(EventletFilteringLogger, self).__init__(*args, **kwargs)
        self.regex = re.compile(r'errno (%d|%d)' %
                                (errno.EPIPE, errno.ECONNRESET), re.IGNORECASE)

    def write(self, msg):
        m = self.regex.search(msg)
        if m:
            self.logger.log(log.logging.DEBUG, 'Error(%s) writing to socket.',
                            m.group(1))
        else:
            self.logger.log(self.level, msg.rstrip())


class Server(object):
    """Server class to manage multiple WSGI sockets and applications."""

    def __init__(self, application, host=None, port=None, threads=1000,
                 keepalive=False, keepidle=None):
        self.application = application
        self.host = host or '0.0.0.0'
        self.port = port or 0
        self.pool = eventlet.GreenPool(threads)
        self.socket_info = {}
        self.greenthread = None
        self.do_ssl = False
        self.cert_required = False
        self.keepalive = keepalive
        self.keepidle = keepidle
        self.socket = None

    def listen(self, key=None, backlog=128):
        """Create and start listening on socket.

        Call before forking worker processes.

        Raises Exception if this has already been called.
        """

        # TODO(dims): eventlet's green dns/socket module does not actually
        # support IPv6 in getaddrinfo(). We need to get around this in the
        # future or monitor upstream for a fix.
        # Please refer below link
        # (https://bitbucket.org/eventlet/eventlet/
        # src/e0f578180d7d82d2ed3d8a96d520103503c524ec/eventlet/support/
        # greendns.py?at=0.12#cl-163)
        info = socket.getaddrinfo(self.host,
                                  self.port,
                                  socket.AF_UNSPEC,
                                  socket.SOCK_STREAM)[0]

        try:
            self.socket = eventlet.listen(info[-1], family=info[0],
                                          backlog=backlog)
        except EnvironmentError:
            LOG.error(_LE("Could not bind to %(host)s:%(port)s"),
                      {'host': self.host, 'port': self.port})
            raise

        LOG.info(_LI('Starting %(arg0)s on %(host)s:%(port)s'),
                 {'arg0': sys.argv[0],
                  'host': self.host,
                  'port': self.port})

    def start(self, key=None, backlog=128):
        """Run a WSGI server with the given application."""

        if self.socket is None:
            self.listen(key=key, backlog=backlog)

        dup_socket = self.socket.dup()
        if key:
            self.socket_info[key] = self.socket.getsockname()
        # SSL is enabled
        if self.do_ssl:
            if self.cert_required:
                cert_reqs = ssl.CERT_REQUIRED
            else:
                cert_reqs = ssl.CERT_NONE

            dup_socket = eventlet.wrap_ssl(dup_socket, certfile=self.certfile,
                                           keyfile=self.keyfile,
                                           server_side=True,
                                           cert_reqs=cert_reqs,
                                           ca_certs=self.ca_certs)

        # Optionally enable keepalive on the wsgi socket.
        if self.keepalive:
            dup_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            # This option isn't available in the OS X version of eventlet
            if hasattr(socket, 'TCP_KEEPIDLE') and self.keepidle is not None:
                dup_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE,
                                      self.keepidle)

        self.greenthread = self.pool.spawn(self._run,
                                           self.application,
                                           dup_socket)

    def set_ssl(self, certfile, keyfile=None, ca_certs=None,
                cert_required=True):
        self.certfile = certfile
        self.keyfile = keyfile
        self.ca_certs = ca_certs
        self.cert_required = cert_required
        self.do_ssl = True

    def stop(self):
        if self.greenthread is not None:
            self.greenthread.kill()

    def wait(self):
        """Wait until all servers have completed running."""
        try:
            self.pool.waitall()
        except KeyboardInterrupt:
            pass
        except greenlet.GreenletExit:
            pass

    def reset(self):
        """Required by the service interface.

        The service interface is used by the launcher when receiving a
        SIGHUP. The service interface is defined in
        keystone.openstack.common.service.Service.

        Keystone does not need to do anything here.
        """
        pass

    def _run(self, application, socket):
        """Start a WSGI server in a new green thread."""
        logger = log.getLogger('eventlet.wsgi.server')
        try:
            eventlet.wsgi.server(socket, application, custom_pool=self.pool,
                                 log=EventletFilteringLogger(logger),
                                 debug=False)
        except greenlet.GreenletExit:
            # Wait until all servers have completed running
            pass
        except Exception:
            LOG.exception(_('Server error'))
            raise
