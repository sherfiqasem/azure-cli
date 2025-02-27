# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
from pkg_resources import parse_version

from azure.cli.core.extension import ext_compat_with_cli, WHEEL_INFO_RE
from azure.cli.core.extension._index import get_index_extensions

from knack.log import get_logger
from knack.util import CLIError

logger = get_logger(__name__)


class NoExtensionCandidatesError(Exception):
    pass


def _is_not_platform_specific(item):
    parsed_filename = WHEEL_INFO_RE(item['filename'])
    p = parsed_filename.groupdict()
    if p.get('abi') == 'none' and p.get('plat') == 'any':
        return True
    logger.debug("Skipping '%s' as not universal wheel."
                 "We do not currently support platform specific extension detection. "
                 "They can be installed with the full URL %s", item['filename'], item.get('downloadUrl'))
    return False


def _is_compatible_with_cli_version(item):
    is_compatible, cli_core_version, min_required, max_required, min_ext_required = ext_compat_with_cli(
        item['metadata'])
    if is_compatible:
        return True
    logger.debug("Skipping '%s' as not compatible with this version of the CLI. "
                 "Extension compatibility result: is_compatible=%s cli_core_version=%s ext_version=%s "
                 "min_core_required=%s max_core_required=%s min_ext_required=%s", item['filename'], is_compatible,
                 cli_core_version, item['metadata'].get('version'), min_required, max_required, min_ext_required)
    return False


def _is_greater_than_cur_version(cur_version):
    if not cur_version:
        return None
    cur_version_parsed = parse_version(cur_version)

    def filter_func(item):
        item_version = parse_version(item['metadata']['version'])
        if item_version > cur_version_parsed:
            return True
        logger.debug("Skipping '%s' as %s not greater than current version %s", item['filename'],
                     item_version, cur_version_parsed)
        return False
    return filter_func


def resolve_from_index(extension_name, cur_version=None, index_url=None, target_version=None, cli_ctx=None):
    """
    Gets the download Url and digest for the matching extension

    :param cur_version: threshold verssion to filter out extensions.
    """
    candidates = get_index_extensions(index_url=index_url, cli_ctx=cli_ctx).get(extension_name, [])

    if not candidates:
        raise NoExtensionCandidatesError("No extension found with name '{}'".format(extension_name))

    filters = [_is_not_platform_specific, _is_compatible_with_cli_version]
    if not target_version:
        filters.append(_is_greater_than_cur_version(cur_version))

    for f in filters:
        logger.debug("Candidates %s", [c['filename'] for c in candidates])
        candidates = list(filter(f, candidates))
    if not candidates:
        raise NoExtensionCandidatesError("No suitable extensions found.")

    candidates_sorted = sorted(candidates, key=lambda c: parse_version(c['metadata']['version']), reverse=True)
    logger.debug("Candidates %s", [c['filename'] for c in candidates_sorted])

    if target_version:
        try:
            chosen = [c for c in candidates_sorted if c['metadata']['version'] == target_version][0]
        except IndexError:
            raise NoExtensionCandidatesError('Extension with version {} not found'.format(target_version))
    else:
        logger.debug("Choosing the latest of the remaining candidates.")
        chosen = candidates_sorted[0]

    logger.debug("Chosen %s", chosen)
    download_url, digest = chosen.get('downloadUrl'), chosen.get('sha256Digest')
    if not download_url:
        raise NoExtensionCandidatesError("No download url found.")
    azmirror_endpoint = cli_ctx.cloud.endpoints.azmirror_storage_account_resource_id if cli_ctx and \
        cli_ctx.cloud.endpoints.has_endpoint_set('azmirror_storage_account_resource_id') else None
    config_index_url = cli_ctx.config.get('extension', 'index_url', None) if cli_ctx else None
    if azmirror_endpoint and not config_index_url:
        # when extension index and wheels are mirrored in airgapped clouds from public cloud
        # the content of the index.json is not updated, so we need to modify the wheel url got
        # from the index.json here.
        import posixpath
        whl_name = download_url.split('/')[-1]
        download_url = posixpath.join(azmirror_endpoint, 'extensions', whl_name)
    return download_url, digest


def resolve_project_url_from_index(extension_name):
    """
    Gets the project url of the matching extension from the index
    """
    candidates = get_index_extensions().get(extension_name, [])
    if not candidates:
        raise NoExtensionCandidatesError("No extension found with name '{}'".format(extension_name))
    try:
        return candidates[0]['metadata']['extensions']['python.details']['project_urls']['Home']
    except KeyError as ex:
        logger.debug(ex)
        raise CLIError('Could not find project information for extension {}.'.format(extension_name))
