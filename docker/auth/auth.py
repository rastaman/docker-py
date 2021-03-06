# Copyright 2013 dotCloud inc.

#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at

#        http://www.apache.org/licenses/LICENSE-2.0

#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import base64
import fileinput
import json
import logging
import os
import warnings

import six

from .. import constants
from .. import errors

INDEX_NAME = 'index.docker.io'
INDEX_URL = 'https://{0}/v1/'.format(INDEX_NAME)
DOCKER_CONFIG_FILENAME = os.path.join('.docker', 'config.json')
LEGACY_DOCKER_CONFIG_FILENAME = '.dockercfg'

log = logging.getLogger(__name__)


def resolve_repository_name(repo_name, insecure=False):
    if insecure:
        warnings.warn(
            constants.INSECURE_REGISTRY_DEPRECATION_WARNING.format(
                'resolve_repository_name()'
            ), DeprecationWarning
        )

    if '://' in repo_name:
        raise errors.InvalidRepository(
            'Repository name cannot contain a scheme ({0})'.format(repo_name))
    parts = repo_name.split('/', 1)
    if '.' not in parts[0] and ':' not in parts[0] and parts[0] != 'localhost':
        # This is a docker index repo (ex: foo/bar or ubuntu)
        return INDEX_NAME, repo_name
    if len(parts) < 2:
        raise errors.InvalidRepository(
            'Invalid repository name ({0})'.format(repo_name))

    if 'index.docker.io' in parts[0]:
        raise errors.InvalidRepository(
            'Invalid repository name, try "{0}" instead'.format(parts[1])
        )

    return parts[0], parts[1]


def resolve_authconfig(authconfig, registry=None):
    """
    Returns the authentication data from the given auth configuration for a
    specific registry. As with the Docker client, legacy entries in the config
    with full URLs are stripped down to hostnames before checking for a match.
    Returns None if no match was found.
    """
    # Default to the public index server
    registry = convert_to_hostname(registry) if registry else INDEX_NAME
    log.debug("Looking for auth entry for {0}".format(repr(registry)))

    if registry in authconfig:
        log.debug("Found {0}".format(repr(registry)))
        return authconfig[registry]

    for key, config in six.iteritems(authconfig):
        if convert_to_hostname(key) == registry:
            log.debug("Found {0}".format(repr(key)))
            return config

    log.debug("No entry found")
    return None


def convert_to_hostname(url):
    return url.replace('http://', '').replace('https://', '').split('/', 1)[0]


def encode_auth(auth_info):
    return base64.b64encode(auth_info.get('username', '') + b':' +
                            auth_info.get('password', ''))


def decode_auth(auth):
    if isinstance(auth, six.string_types):
        auth = auth.encode('ascii')
    s = base64.b64decode(auth)
    login, pwd = s.split(b':', 1)
    return login.decode('ascii'), pwd.decode('ascii')


def encode_header(auth):
    auth_json = json.dumps(auth).encode('ascii')
    return base64.b64encode(auth_json)


def parse_auth(entries):
    """
    Parses authentication entries

    Args:
      entries: Dict of authentication entries.

    Returns:
      Authentication registry.
    """

    conf = {}
    for registry, entry in six.iteritems(entries):
        username, password = decode_auth(entry['auth'])
        log.debug(
            'Found entry (registry={0}, username={1})'
            .format(repr(registry), repr(username))
        )
        conf[registry] = {
            'username': username,
            'password': password,
            'email': entry['email'],
            'serveraddress': registry,
        }
    return conf


def load_config(config_path=None):
    """
    Loads authentication data from a Docker configuration file in the given
    root directory or if config_path is passed use given path.
    """
    conf = {}
    data = None

    # Prefer ~/.docker/config.json.
    config_file = config_path or os.path.join(os.path.expanduser('~'),
                                              DOCKER_CONFIG_FILENAME)

    log.debug("Trying {0}".format(config_file))

    if os.path.exists(config_file):
        try:
            with open(config_file) as f:
                for section, data in six.iteritems(json.load(f)):
                    if section != 'auths':
                        continue
                    log.debug("Found 'auths' section")
                    return parse_auth(data)
            log.debug("Couldn't find 'auths' section")
        except (IOError, KeyError, ValueError) as e:
            # Likely missing new Docker config file or it's in an
            # unknown format, continue to attempt to read old location
            # and format.
            log.debug(e)
            pass
    else:
        log.debug("File doesn't exist")

    config_file = config_path or os.path.join(os.path.expanduser('~'),
                                              LEGACY_DOCKER_CONFIG_FILENAME)

    log.debug("Trying {0}".format(config_file))

    if not os.path.exists(config_file):
        log.debug("File doesn't exist - returning empty config")
        return {}

    log.debug("Attempting to parse as JSON")
    try:
        with open(config_file) as f:
            return parse_auth(json.load(f))
    except Exception as e:
        log.debug(e)
        pass

    # If that fails, we assume the configuration file contains a single
    # authentication token for the public registry in the following format:
    #
    # auth = AUTH_TOKEN
    # email = email@domain.com
    log.debug("Attempting to parse legacy auth file format")
    try:
        data = []
        for line in fileinput.input(config_file):
            data.append(line.strip().split(' = ')[1])
        if len(data) < 2:
            # Not enough data
            raise errors.InvalidConfigFile(
                'Invalid or empty configuration file!')

        username, password = decode_auth(data[0])
        conf[INDEX_NAME] = {
            'username': username,
            'password': password,
            'email': data[1],
            'serveraddress': INDEX_URL,
        }
        return conf
    except Exception as e:
        log.debug(e)
        pass

    log.debug("All parsing attempts failed - returning empty config")
    return {}
