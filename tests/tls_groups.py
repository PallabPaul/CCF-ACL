# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache 2.0 License.
import http
import os
import subprocess

import infra.checker
import infra.e2e_args
import infra.network
import suite.test_requirements as reqs
from loguru import logger as LOG


@reqs.description("Exercise configured TLS group on RPC and node join connections")
@reqs.at_least_n_nodes(2)
def test_configured_tls_group(network, args):
    assert args.tls_groups, "At least one --tls-group is required"
    assert args.expected_tls_group, "--expected-tls-group is required"
    assert args.expected_negotiated_tls_group, (
        "--expected-negotiated-tls-group is required"
    )
    primary, backup = network.find_primary_and_any_backup()

    endpoint = primary.get_public_rpc_address()
    service_cert = os.path.join(network.common_dir, "service_cert.pem")
    request = (
        "GET /node/network HTTP/1.0\r\nHost: localhost\r\n\r\n"
    ).encode()
    process = subprocess.Popen(
        [
            "openssl",
            "s_client",
            "-connect",
            endpoint,
            "-tls1_3",
            "-groups",
            args.expected_tls_group,
            "-CAfile",
            service_cert,
            "-verify_return_error",
            "-quiet",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = process.communicate(input=request, timeout=2)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        remaining_stdout, remaining_stderr = process.communicate()
        stdout = (exc.output or b"") + remaining_stdout
        stderr = (exc.stderr or b"") + remaining_stderr

    assert b"HTTP/1.1 200" in stdout, stdout.decode(errors="replace")
    assert b"verify error" not in stderr.lower(), stderr.decode(errors="replace")

    with primary.client() as client:
        response = client.get("/node/network")
        assert response.status_code == http.HTTPStatus.OK, response

    infra.checker.check_can_progress(primary)
    infra.checker.check_can_progress(backup)

    expected_log = (
        "Context::handshake() : Success, negotiated TLS group "
        f"{args.expected_negotiated_tls_group}"
    )
    out_path, _ = primary.get_logs()
    assert out_path is not None
    with open(out_path, encoding="utf-8") as output:
        output_text = output.read()
    assert expected_log in output_text, (
        f"Did not find negotiated group in {out_path}: {expected_log}"
    )

    LOG.success(
        "RPC request and node join succeeded with TLS group {}",
        args.expected_negotiated_tls_group,
    )
    return network


def run(args):
    with infra.network.network(
        args.nodes, args.binary_dir, args.debug_nodes, pdb=args.pdb
    ) as network:
        network.start_and_open(args)
        test_configured_tls_group(network, args)


if __name__ == "__main__":
    args = infra.e2e_args.cli_args()
    args.package = "samples/apps/logging/logging"
    args.nodes = infra.e2e_args.min_nodes(args, f=1)
    args.log_level = "Debug"
    run(args)