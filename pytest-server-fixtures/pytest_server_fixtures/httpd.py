import os
import socket
import string

import pytest
import path

from pytest_fixture_config import yield_requires_config
from pytest_server_fixtures import CONFIG

from .http import HTTPTestServer


@yield_requires_config(CONFIG, ['httpd_executable', 'httpd_modules'])
@pytest.yield_fixture(scope='function')
def httpd_server():
    """ Function-scoped httpd server in a local thread.
    
        Methods
        -------
        query_url()   : Query url relative to the server root.
        ..              Parse as json and retry failures by default.
        post_to_url() : Post payload to url relative to the server root.
        ..              Parse as json and retry failures by default.
    """
    test_server = HTTPDServer()
    test_server.start()
    yield test_server
    test_server.teardown()


class HTTPDServer(HTTPTestServer):
    port_seed = 65531
    cfg_template = string.Template("""
      LoadModule headers_module $modules/mod_headers.so
      LoadModule proxy_module $modules/mod_proxy.so
      LoadModule proxy_http_module $modules/mod_proxy_http.so
      LoadModule proxy_connect_module $modules/mod_proxy_connect.so
      LoadModule alias_module $modules/mod_alias.so
      LoadModule dir_module $modules/mod_dir.so
      LoadModule autoindex_module $modules/mod_autoindex.so
      <IfModule !mod_log_config.c>
          LoadModule log_config_module $modules/mod_log_config.so
      </IfModule>
      LoadModule mime_module $modules/mod_mime.so

      StartServers 1
      ServerLimit 8

      TypesConfig /etc/mime.types
      DefaultType text/plain


      ServerRoot $server_root
      Listen $listen_addr
      PidFile $server_root/run/httpd.pid

      ErrorLog $log_dir/error.log
      LogFormat "%h %l %u %t \\"%r\\" %>s %b" common
      CustomLog $log_dir/access.log common
      LogLevel info

      $proxy_rules

      Alias / $document_root/

      <Directory $server_root>
          Options +Indexes
      </Directory>

      $extra_cfg
    """)

    def __init__(self, proxy_rules=None, extra_cfg='', document_root=None, log_dir=None, **kwargs):
        """ httpd Proxy Server

        Parameters
        ----------
        proxy_rules: `dict`
            { proxy_src: proxy_dest }. Eg   {'/downstream_url/' : server.uri}
        extra_cfg: `str`
            Any extra Apache config
        document_root : `str`
            Server document root, defaults to temporary workspace
        log_dir : `str`
            Server log directory, defaults to $(workspace)/logs
        """
        self.proxy_rules = proxy_rules if proxy_rules is not None else {}
        self.extra_cfg = extra_cfg

        # Always print debug output for this process
        os.environ['DEBUG'] = '1'

        # Discover externally accessable hostname so selenium can get to it
        kwargs['hostname'] = kwargs.get('hostname', socket.gethostbyname(os.uname()[1]))

        super(HTTPDServer, self).__init__(**kwargs)
        
        self.document_root = document_root or self.workspace
        self.document_root = path.path(self.document_root)
        self.log_dir = log_dir or self.workspace / 'logs'
        self.log_dir = path.path(self.log_dir)

    def pre_setup(self):
        """ Write out the config file
        """
        self.config = self.workspace / 'httpd.conf'
        rules = []
        for source in self.proxy_rules:
            rules.append("ProxyPass {} {}".format(source, self.proxy_rules[source]))
            rules.append("ProxyPassReverse {} {} \n".format(source, self.proxy_rules[source]))
        cfg = self.cfg_template.substitute(
            server_root=self.workspace,
            document_root=self.document_root,
            log_dir=self.log_dir,
            listen_addr="{host}:{port}".format(host=self.hostname, port=self.port),
            proxy_rules='\n'.join(rules),
            extra_cfg=self.extra_cfg,
            modules=CONFIG.httpd_modules,
        )
        self.config.write_text(cfg)

        # This is where it stores PID files
        (self.workspace / 'run').mkdir()
        if not os.path.exists(self.log_dir):
            self.log_dir.mkdir()

    @property
    def run_cmd(self):
        return [CONFIG.httpd_executable, '-f', self.config]
