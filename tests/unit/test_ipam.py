# Copyright 2015 Metaswitch Networks
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import unittest
from StringIO import StringIO

from pycalico.block import AlreadyAssignedError

from ipam import IpamPlugin, _exit_on_error, main
from mock import patch, MagicMock, ANY, Mock
from netaddr import IPNetwork, AddrFormatError
from nose.tools import assert_equal, assert_raises
from pycalico.ipam import IPAMClient

from calico_cni.constants import *
from calico_cni.util import CniError


class CniIpamTest(unittest.TestCase):
    """
    Test class for IPAM plugin.
    """
    def setUp(self):
        """
        Per-test setup method.
        """
        self.container_id = "ff3afbd1-17ad-499d-b514-72438c009e81"
        self.network_config = {
            "name": "ut-network",
            "type": "calico",
            "ipam": {
                "type": "calico-ipam",
                ASSIGN_IPV4_KEY: "true",
                ASSIGN_IPV6_KEY: "true"
            }
        }
        self.env = {
                CNI_CONTAINERID_ENV: self.container_id,
                CNI_IFNAME_ENV: "eth0",
                CNI_ARGS_ENV: "",
                CNI_COMMAND_ENV: CNI_CMD_ADD, 
                CNI_PATH_ENV: "/usr/bin/rkt/",
                CNI_NETNS_ENV: "netns",
        }

        # Create the CniPlugin to test.
        self.plugin = IpamPlugin(self.env, self.network_config["ipam"])

        # Mock out the datastore client.
        self.m_datastore_client = MagicMock(spec=IPAMClient)
        self.plugin.datastore_client = self.m_datastore_client

        # Set expected values.
        self.expected_handle = self.container_id

    @patch('sys.stdout', new_callable=StringIO)
    def test_execute_add_mainline(self, m_stdout):
        # Mock
        self.plugin.command = CNI_CMD_ADD
        ip4 = IPNetwork("1.2.3.4/32")
        ip6 = IPNetwork("ba:ad::be:ef/128")
        self.plugin._assign_address = MagicMock(spec=self.plugin._assign_address)
        self.plugin._assign_address.return_value = ip4, ip6

        # Call 
        ret = self.plugin.execute()

        # Assert
        expected = json.dumps({"ip4": {"ip": "1.2.3.4/32"}, 
                               "ip6": {"ip": "ba:ad::be:ef/128"}})
        assert_equal(ret, expected)

    @patch('sys.stdout', new_callable=StringIO)
    def test_execute_del_mainline(self, m_stdout):
        # Mock
        self.plugin.command = CNI_CMD_DELETE

        # Call 
        self.plugin.execute()

        # Assert
        expected = ''
        assert_equal(m_stdout.getvalue().strip(), expected)
        self.plugin.datastore_client.release_ip_by_handle.assert_called_once_with(handle_id=self.expected_handle)

    @patch('sys.stdout', new_callable=StringIO)
    def test_execute_del_not_assigned(self, m_stdout):
        # Mock
        self.plugin.command = CNI_CMD_DELETE
        self.plugin.datastore_client.release_ip_by_handle.side_effect = KeyError

        # Call 
        self.plugin.execute()

        # Assert
        expected = ''
        assert_equal(m_stdout.getvalue().strip(), expected)

    @patch('sys.stdout', new_callable=StringIO)
    def test_execute_add_user_supplied(self, m_stdout):
        # Mock
        self.plugin.command = CNI_CMD_ADD
        self.plugin.ip = "1.2.3.4"
        ip4 = IPNetwork("1.2.3.4/32")
        self.plugin._assign_existing_address = MagicMock(spec=self.plugin._assign_existing_address)
        self.plugin._assign_existing_address.return_value = ip4

        # Call
        ret = self.plugin.execute()

        # Assert
        expected = json.dumps({"ip4": {"ip": "1.2.3.4/32"}})
        assert_equal(ret, expected)

    def test_assign_address_mainline(self):
        # Mock
        ip4 = IPNetwork("1.2.3.4/32")
        ip6 = IPNetwork("ba:ad::be:ef/128")
        self.plugin.datastore_client.auto_assign_ips = MagicMock(spec=self.plugin._assign_address)
        self.plugin.datastore_client.auto_assign_ips.return_value = [ip4], [ip6]

        # Args
        handle_id = "abcdef12345"

        # Call
        ret_ip4, ret_ip6 = self.plugin._assign_address(handle_id)

        # Assert
        assert_equal(ip4, ret_ip4)
        assert_equal(ip6, ret_ip6)

    def test_assign_address_runtime_err(self):
        # Mock
        self.plugin.datastore_client.auto_assign_ips = MagicMock(spec=self.plugin._assign_address)
        self.plugin.datastore_client.auto_assign_ips.side_effect = RuntimeError

        # Args
        handle_id = "abcdef12345"

        # Call
        with assert_raises(CniError) as err:
            self.plugin._assign_address(handle_id)
        e = err.exception
        assert_equal(e.code, ERR_CODE_GENERIC)

    @patch("ipam._exit_on_error", autospec=True)
    def test_assign_address_no_ipv4(self, m_exit):
        # Mock
        ip6 = IPNetwork("ba:ad::be:ef/128")
        self.plugin.datastore_client.auto_assign_ips = MagicMock(spec=self.plugin._assign_address)
        self.plugin.datastore_client.auto_assign_ips.return_value = [], [ip6]

        # Args
        handle_id = "abcdef12345"

        # Call
        with assert_raises(CniError) as err:
            self.plugin._assign_address(handle_id)
        e = err.exception

        # Assert
        assert_equal(e.code, ERR_CODE_GENERIC)

    @patch("ipam._exit_on_error", autospec=True)
    def test_assign_address_no_ipv6(self, m_exit):
        # Mock
        ip4 = IPNetwork("1.2.3.4/32")
        self.plugin.datastore_client.auto_assign_ips = MagicMock(spec=self.plugin._assign_address)
        self.plugin.datastore_client.auto_assign_ips.return_value = [ip4], []

        # Args
        handle_id = "abcdef12345"

        # Call
        with assert_raises(CniError) as err:
            self.plugin._assign_address(handle_id)
        e = err.exception

        # Assert
        assert_equal(e.code, ERR_CODE_GENERIC)

    def test_assign_address_user_supplied_mainline(self):
        # Mock
        input_address = "192.123.123.123"
        expected = IPNetwork(input_address)

        self.plugin.ip = input_address
        self.plugin.datastore_client.assign_ip = Mock(spec=self.plugin._assign_existing_address())

        # Call
        ipv4 = self.plugin._assign_existing_address()

        # Assert
        assert_equal(ipv4, expected)

    def test_assign_address_user_supplied_malformed(self):
        # Mock
        input_address = "192.123.123.321"

        self.plugin.ip = input_address

        # Call
        with assert_raises(CniError) as err:
            self.plugin._assign_existing_address()
        e = err.exception
        assert_equal(e.code, ERR_CODE_GENERIC)

    def test_assign_address_user_supplied_already_assigned(self):
        # Mock
        input_address = "192.123.123.123"

        self.plugin.ip = input_address
        self.plugin.datastore_client.assign_ip = Mock(spec=self.plugin._assign_existing_address())
        self.plugin.datastore_client.assign_ip.side_effect = AlreadyAssignedError()

        with assert_raises(CniError) as err:
            self.plugin._assign_existing_address()
        e = err.exception
        assert_equal(e.code, ERR_CODE_GENERIC)

    def test_assign_address_user_supplied_runtime_error(self):
        # Mock
        input_address = "192.123.123.123"

        self.plugin.ip = input_address
        self.plugin.datastore_client.assign_ip = Mock(spec=self.plugin._assign_existing_address())
        self.plugin.datastore_client.assign_ip.side_effect = RuntimeError()

        with assert_raises(CniError) as err:
            self.plugin._assign_existing_address()
        e = err.exception
        assert_equal(e.code, ERR_CODE_GENERIC)

    def test_parse_environment_no_command(self):
        # Delete command.
        del self.env[CNI_COMMAND_ENV]

        # Call
        with assert_raises(CniError) as err:
            self.plugin._parse_environment(self.env)
        e = err.exception
        assert_equal(e.code, ERR_CODE_GENERIC)

    def test_parse_environment_invalid_command(self):
        # Change command.
        self.env[CNI_COMMAND_ENV] = "invalid"

        # Call
        with assert_raises(CniError) as err:
            self.plugin._parse_environment(self.env)
        e = err.exception
        assert_equal(e.code, ERR_CODE_GENERIC)

    def test_parse_environment_invalid_container_id(self):
        # Delete container ID.
        del self.env[CNI_CONTAINERID_ENV] 

        # Call
        with assert_raises(CniError) as err:
            self.plugin._parse_environment(self.env)
        e = err.exception
        assert_equal(e.code, ERR_CODE_GENERIC)

    def test_exit_on_error(self):
        with assert_raises(SystemExit) as err:
            _exit_on_error(1, "message", "details")
        e = err.exception
        assert_equal(e.code, 1)

    @patch("ipam.os", autospec=True)
    @patch("ipam.sys", autospec=True)
    @patch("ipam.IpamPlugin", autospec=True)
    @patch("ipam.configure_logging", autospec=True)
    def test_main(self, m_conf_log, m_plugin, m_sys, m_os):
        # Mock
        m_os.environ = self.env
        m_sys.stdin.readlines.return_value = json.dumps(self.network_config)
        m_plugin.reset_mock()

        # Call
        main()

        # Assert
        m_plugin.assert_called_once_with(self.env, self.network_config["ipam"])
        m_plugin(self.env, self.network_config["ipam"]).execute.assert_called_once_with()

    @patch("ipam.os", autospec=True)
    @patch("ipam.sys", autospec=True)
    @patch("ipam.IpamPlugin", autospec=True)
    @patch("ipam.configure_logging", autospec=True)
    @patch("ipam._exit_on_error", autospec=True)
    def test_main_execute_cni_error(self, m_exit, m_conf_log, m_plugin, m_sys, m_os):
        # Mock
        m_os.environ = self.env
        m_sys.stdin.readlines.return_value = json.dumps(self.network_config)
        m_plugin.reset_mock()
        m_plugin(self.env, self.network_config["ipam"]).execute.side_effect = CniError(50, "Message", "Details") 

        # Call
        main()

        # Assert
        m_exit.assert_called_once_with(50, "Message", "Details")

    @patch("ipam.os", autospec=True)
    @patch("ipam.sys", autospec=True)
    @patch("ipam.IpamPlugin", autospec=True)
    @patch("ipam.configure_logging", autospec=True)
    @patch("ipam._exit_on_error", autospec=True)
    def test_main_execute_unhandled_error(self, m_exit, m_conf_log, m_plugin, m_sys, m_os):
        # Mock
        m_os.environ = self.env
        m_sys.stdin.readlines.return_value = json.dumps(self.network_config)
        m_plugin.reset_mock()
        m_plugin(self.env, self.network_config["ipam"]).execute.side_effect = Exception

        # Call
        main()

        # Assert
        m_exit.assert_called_once_with(ERR_CODE_GENERIC, message=ANY, details=ANY)


class CniIpamKubernetesTest(CniIpamTest):
    """
    Test class for IPAM plugin when running under Kubernetes.
    """
    def setUp(self):
        """
        Per-test setup method.
        """
        CniIpamTest.setUp(self)
        self.container_id = "ff3afbd1-17ad-499d-b514-72438c009e81"
        self.env = {
                CNI_CONTAINERID_ENV: self.container_id,
                CNI_IFNAME_ENV: "eth0",
                CNI_ARGS_ENV: "K8S_POD_NAME=podname;K8S_POD_NAMESPACE=k8sns",
                CNI_COMMAND_ENV: CNI_CMD_ADD, 
                CNI_PATH_ENV: "/usr/bin/rkt/",
                CNI_NETNS_ENV: "netns",
        }

        # Create the CniPlugin to test.
        self.plugin = IpamPlugin(self.env, self.network_config["ipam"])

        # Mock out the datastore client.
        self.m_datastore_client = MagicMock(spec=IPAMClient)
        self.plugin.datastore_client = self.m_datastore_client

        # Set expected values.
        self.expected_handle = "k8sns.podname" 
